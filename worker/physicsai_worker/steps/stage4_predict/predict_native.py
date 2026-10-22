"""④ PREDICT(A)의 native 분기(geometry-engine.md §7.3.5): PR_PREP·TPL_RENDER·GEOM_UPDATE·MESH.

tpl 렌더·SimLab·HyperMesh 대신 `P/geom/{options.json, values.json, update/, morph/, check/, <mesh_include_name>}`를 만든다.
RAD_ASSEMBLE 이후는 기존 체인 그대로(`predict_inputs._assemble_parametric`).

단계 3S(§11.1): 값 중 쉘 두께(`source: prop`)는 values.json에서 빼고 RAD_ASSEMBLE 뒤 `props apply`로 P/INPUT 복사본에 적용.
형상 값이 없으면 GEOM_UPDATE·MESH는 SKIPPED, 조립은 기준 메시 그대로. 4B(§7.3.8): 확정된 다중 baseline 세트는 공통 이름 값을
배정한 baseline의 원 이름으로 바꿔 그 baseline 준비본으로 만든다(단건은 확정 게이트 대상 아님 — 미확정이면 base 이름 그대로).
"""

from __future__ import annotations

import os
from typing import Any

from physicsai_core.errors import StepFailure
from physicsai_core.fileutil import write_json
from physicsai_core.geometry import baselines as bl
from physicsai_core.geometry import shell as sh
from physicsai_core.geometry.prep import is_shell_only
from physicsai_core.geometry.native_files import values_document
from physicsai_core.geometry.options import usage_document
from physicsai_core.geometry.shell_native import SHELL_FILES_DIR, THICKNESS_JSON
from physicsai_core.stage4_predict import nearest as nearest_mod

from ..geometry_native import (
    LocalRunner,
    effective_opts,
    set_opts,
    engine_version,
    ensure_prep_ready,
    native_inputs,
    read_json,
    run_paicad,
)
from ...signals import StepSkipped
from .. import geometry_cushion as cushion
from .predict_inputs import MESH_ONLY, assemble_into, input_of, predict_dir, template_kind


def is_native_set(ps: dict[str, Any] | None) -> bool:
    return bool(ps) and ps.get("engine") == "native"  # type: ignore[union-attr]


def _G(ctx: Any) -> str:
    return os.path.join(predict_dir(ctx), "geom")


def pr_prep(ctx: Any, m: dict[str, Any], ps: dict[str, Any], S: str) -> None:
    """PR_PREP(native): 준비본 유효성(INPUT_CHANGED) + 옵션 사용값. 값은 반올림하지 않는다(GE-9)."""
    s = ctx.settings
    if not ps.get("starter_name") or not os.path.isfile(os.path.join(S, "radioss_assem", ps["starter_name"])):
        raise StepFailure("INPUT_CHANGED", "파라미터 세트 파일이 없습니다: radioss_assem/" + str(ps.get("starter_name")))
    opts = set_opts(s, S, ps.get("geom_options"))
    ver, ocp, shown = engine_version(ctx)
    ctx.log(f"형상 엔진: {shown}")
    values = {k: float(v) for k, v in ctx.params["values"].items()}
    geo, shell = sh.split_values(ps["parameters"], values)
    bid, root = _baseline_for(ctx, ps, S, geo)
    ensure_prep_ready(s, root, opts, ver)
    if bid is not None:
        geo = bl.original_values(ps["parameters"], bid, geo)
    oor = nearest_mod.out_of_range(ps["parameters"], values)
    P, G = predict_dir(ctx), _G(ctx)
    os.makedirs(G, exist_ok=True)
    pj = os.path.join(P, "params.json")
    oj = os.path.join(G, "options.json")
    ctx.backup([pj, oj])
    write_json(pj, {"values": values, "applied_values": values, "rounded": {}, "value_source": ctx.params.get("value_source"),
                    "source_run_key": ctx.params.get("source_run_key"), "out_of_range": oor, "nearest": None,
                    "model_id": m["id"], "param_set_id": ps["id"], "unit_system": ps["unit_system"], "engine": "native"})
    write_json(oj, usage_document(opts, ver))
    geometry = bool(geo) and not is_shell_only(root)
    kind = template_kind(ctx, ps)  # 실행의 입력 종류(input-kind.md IK-2): params template_kind(서버 확정) → 세트 값
    if kind == MESH_ONLY:  # 쿠션 입력: 명령 설정·쿠션 가능 세트인지 먼저 확인(§4.1 PR_PREP)
        cushion.require_command(s)
        cushion.require_cushion_capable(native_inputs(s, root, os.path.join(root, "radioss_assem"), need_cad=False), shell,
                                        is_shell_only(root))
    ctx.patch_result({"model_id": m["id"], "param_set_id": ps["id"], "values": values, "applied_values": values,
                      "out_of_range": [o["name"] for o in oor], "template_kind": kind, "input": input_of(kind), "nearest": None,
                      "engine": "native", "engine_version": ver, "ocp_version": ocp, "geometry_values": geo,
                      "shell_values": shell, "baseline_id": bid, "baseline_rel": ctx.rel(root) if bid else None,
                      "geometry_skipped": not geometry})


def _baseline_for(ctx: Any, ps: dict[str, Any], S: str, geo: dict[str, float]) -> tuple[str | None, str]:
    """다중 baseline 확정 세트면 (배정 baseline, 그 준비본 루트), 아니면 (None, S). range = 배정 규칙, topology = base."""
    s = ctx.settings
    try:
        pm = bl.load(S, s.geometry.max_report_bytes)
    except bl.MapError as exc:
        raise StepFailure(exc.code, exc.message) from None
    if pm is None or pm.get("status") != "confirmed":
        return None, S
    if pm.get("usage") == "topology":
        bid = bl.baseline_ids(pm)[0]
        ctx.add_warning("BASELINE_DEFAULT", f"위상 변형 세트의 단건 예측은 첫 baseline({bid})으로 만듭니다")
    else:
        bid = bl.assign_baseline(pm, ps["parameters"], geo)
        if bid is None:
            raise StepFailure(bl.NO_COVER, "값을 덮는 baseline이 없습니다(각 baseline의 모핑 가능 범위 밖)")
    return bid, bl.baseline_root(S, pm, bid)


def root_of(ctx: Any, S: str) -> str:
    rel = ctx.result().get("baseline_rel")
    return ctx.abs(rel) if rel else S


def tpl_render(ctx: Any) -> None:
    """TPL_RENDER(native) = `P/geom/values.json`(§4.4) 작성. CAD 사본 없음(paicad가 S/cad를 읽는다)."""
    r = ctx.result()
    dst = os.path.join(_G(ctx), "values.json")
    ctx.backup([dst])
    extra = {"baseline_id": r["baseline_id"], "common_values": dict(r["values"])} if r.get("baseline_id") else None
    write_json(dst, values_document(r.get("geometry_values", r["values"]), "predict", ctx.ex.job_id, r.get("engine_version"), extra=extra))
    ctx.add_output(dst)


def _inputs(ctx: Any, S: str) -> Any:
    root = root_of(ctx, S)
    return native_inputs(ctx.settings, root, os.path.join(root, "radioss_assem"), need_cad=not ctx.result().get("geometry_skipped"))


def _skip_if_no_geometry(ctx: Any) -> None:
    if ctx.result().get("geometry_skipped"):
        raise StepSkipped("형상 값 없음(쉘 두께만) — 형상 단계 생략")


def geom_update(ctx: Any, S: str) -> None:
    _skip_if_no_geometry(ctx)
    s, G = ctx.settings, _G(ctx)
    inp = _inputs(ctx, S)
    if inp.kind == "shell":
        return _shell_update(ctx, inp, G)
    U = os.path.join(G, "update")
    v = run_paicad(LocalRunner(ctx), s, "paicad_update",
                   {**inp.base_values(s), "values_json": os.path.join(G, "values.json"), "options_json": os.path.join(G, "options.json"),
                    "update_dir": U}, cwd=U, report=os.path.join(U, "update.json"), success=[os.path.join(U, "sample.brep")],
                   backup=[U], body_map=inp.body_map)
    v.raise_if_failed()
    ctx.add_output(os.path.join(U, "update.json"))
    ctx.patch_result({"geometry": {"update_elapsed_s": (v.report or {}).get("elapsed_s")}})


def mesh(ctx: Any, S: str) -> None:
    """MESH(native) = `paicad_morph` → `paicad_check`(PASS일 때만 `P/geom/{mesh_include_name}`).
    쿠션 입력(input-kind.md §4.1)이면 그 뒤 `paicad_cushion_write` → `P/geom/{simlab_mesh_name}`(형상 값이 없으면 morph·check 없이 기준 include로)."""
    is_cushion = ctx.result().get("template_kind") == MESH_ONLY
    s, G = ctx.settings, _G(ctx)
    if is_cushion and ctx.result().get("geometry_skipped"):
        inp = _inputs(ctx, S)
        return _cushion_write(ctx, inp, G, inp.baseline_inc)  # 형상 값 없음: 기준 쿠션 메시 그대로
    _skip_if_no_geometry(ctx)
    inp = _inputs(ctx, S)
    if inp.kind == "shell":
        return _shell_mesh(ctx, inp, G, S)
    U, Mo, C = (os.path.join(G, d) for d in ("update", "morph", "check"))
    out_inc = os.path.join(G, s.predict.mesh_include_name)
    base = {**inp.base_values(s), "values_json": os.path.join(G, "values.json"), "options_json": os.path.join(G, "options.json"),
            "update_dir": U, "morph_dir": Mo, "check_dir": C, "out_inc": out_inc}
    x = LocalRunner(ctx)
    v = run_paicad(x, s, "paicad_morph", base, cwd=Mo, report=os.path.join(Mo, "morph.json"),
                   success=[os.path.join(Mo, "morphed.inc")], backup=[Mo], body_map=inp.body_map)
    v.raise_if_failed()
    mj = v.report or {}
    v = run_paicad(x, s, "paicad_check", base, cwd=C, report=os.path.join(C, "check.json"), success=[out_inc],
                   backup=[C, out_inc], body_map=inp.body_map)
    v.raise_if_failed()
    cj = read_json(os.path.join(C, "check.json"), s.geometry.max_report_bytes)
    checks = cj.get("checks") if isinstance(cj.get("checks"), dict) else {}
    q = checks.get("quality") if isinstance(checks.get("quality"), dict) else {}
    d = checks.get("deviation") if isinstance(checks.get("deviation"), dict) else {}
    ctx.add_output(out_inc)
    prev = dict(ctx.result().get("geometry") or {})
    prev.update({"morph_max_disp_mm": mj.get("max_disp_mm"), "min_stretch": q.get("min_stretch"), "max_deviation_mm": d.get("max_mm"),
                 "check_elapsed_s": cj.get("elapsed_s"), "check_status": cj.get("status")})
    ctx.patch_result({"geometry": prev})
    if is_cushion:
        _cushion_write(ctx, inp, G, out_inc)


def _cushion_write(ctx: Any, inp: Any, G: str, cushion_inc: str) -> None:
    """`paicad cushion write`(GE-C19): `cushion_inc`(모핑 PASS include 또는 기준본)에서 쿠션 바디만의 rad → `P/geom/{simlab_mesh_name}`,
    보고 `P/geom/cushion/cushion.json`. 실패는 그 코드·한국어 문구로 MESH 단계 실패."""
    s = ctx.settings
    rad = os.path.join(G, s.predict.simlab_mesh_name)
    D = os.path.join(G, cushion.CUSHION_DIR)
    v = cushion.write_cushion(LocalRunner(ctx), s, inp, cushion_inc=cushion_inc, cushion_dir=D, cushion_rad=rad)
    v.raise_if_failed()
    ctx.add_output(rad)
    rep = v.report or {}
    prev = dict(ctx.result().get("geometry") or {})
    prev["cushion"] = {k: rep.get(k) for k in ("node_count", "elem_count", "bytes", "elapsed_s")}
    ctx.patch_result({"geometry": prev})


def rad_assemble(ctx: Any, S: str, inp_dir: str) -> str:
    """RAD_ASSEMBLE(native): 조립 폴더 사본(배정 baseline) + 새 include(형상 값 없으면 기준 메시 그대로) → P/INPUT, 그 뒤 쉘 두께 적용.
    starter 이름을 돌려준다(이후 commands.rad_assemble·결과 기록은 기존 체인)."""
    s, r = ctx.settings, ctx.result()
    inp = _inputs(ctx, S)
    if inp.kind == "shell" and not r.get("geometry_skipped"):  # SM §8.3: 조립 사본 + PASS 쉘 사본 덮어쓰기(기준 메시 교체 없음)
        from ..geometry_shell import assemble_copy, overlay

        starter = assemble_copy(s, inp.assem_dir, inp_dir, checkpoint=ctx.checkpoint, log=ctx.log)
        overlay(os.path.join(_G(ctx), SHELL_FILES_DIR), list(r.get("shell_files") or []), inp_dir, checkpoint=ctx.checkpoint, log=ctx.log)
    else:
        new_inc = inp.baseline_inc if r.get("geometry_skipped") else os.path.join(_G(ctx), s.predict.mesh_include_name)
        starter, warnings = assemble_into(s, inp.assem_dir, new_inc, inp_dir, checkpoint=ctx.checkpoint, log=ctx.log)
        for w in warnings:
            ctx.add_warning(*w)
    shell = r.get("shell_values") or {}
    if shell:
        from ..geometry_props import apply

        v = apply(LocalRunner(ctx), s, inp_dir, shell, os.path.join(S, *sh.PROPS_JSON.split("/")), os.path.join(_G(ctx), sh.APPLY_DIR),
                  r.get("engine_version"))
        v.raise_if_failed()
        ctx.log(f"쉘 두께 적용: {', '.join(f'{k}={v:g}' for k, v in shell.items())}")
    return starter


# ---- 쉘 판금 비드(shell-morph.md §8.2): GEOM_UPDATE = shell update(--fixed-dir), MESH = shell morph → check ----------------


def _shell_update(ctx: Any, inp: Any, G: str) -> None:
    from ..geometry_shell import UPDATE_JSON, require_shell_commands

    s = ctx.settings
    require_shell_commands(s, "paicad_shell_update")
    U = os.path.join(G, "update")
    v = run_paicad(LocalRunner(ctx), s, "paicad_shell_update",
                   {**inp.base_values(s), "values_json": os.path.join(G, "values.json"), "options_json": os.path.join(G, "options.json"),
                    "update_dir": U}, cwd=U, report=os.path.join(U, UPDATE_JSON), success=[os.path.join(U, "sample.brep")],
                   backup=[U], body_map=inp.body_map)
    v.raise_if_failed()
    ctx.add_output(os.path.join(U, UPDATE_JSON))
    ctx.patch_result({"geometry": {"kind": "shell", "update_elapsed_s": (v.report or {}).get("elapsed_s")}})


def _shell_mesh(ctx: Any, inp: Any, G: str, S: str) -> None:
    """MESH(쉘) = `paicad_shell_morph` → `paicad_shell_check`(PASS일 때만 `P/geom/shell_files/<rel>`). 3S 두께가 모핑 대상 part에
    있으면 `--thickness`(check (d) 간섭, SM §8.4)."""
    from ..geometry_shell import CHECK_JSON, MORPH_JSON, out_files, require_shell_commands, thickness_for, write_thickness

    s, r = ctx.settings, ctx.result()
    require_shell_commands(s, "paicad_shell_morph", "paicad_shell_check")
    U, Mo, C, F = (os.path.join(G, d) for d in ("update", "morph", "check", SHELL_FILES_DIR))
    tdoc = thickness_for(s, inp, os.path.join(S, *sh.PROPS_JSON.split("/")), r.get("shell_values") or None)
    tj = os.path.join(G, THICKNESS_JSON)
    if os.path.lexists(tj):
        ctx.backup([tj])
    base = {**inp.base_values(s), "values_json": os.path.join(G, "values.json"), "options_json": os.path.join(G, "options.json"),
            "update_dir": U, "morph_dir": Mo, "check_dir": C, "out_files_dir": F, "thickness_json": write_thickness(tj, tdoc)}
    x = LocalRunner(ctx)
    v = run_paicad(x, s, "paicad_shell_morph", base, cwd=Mo, report=os.path.join(Mo, MORPH_JSON), success=[], backup=[Mo],
                   body_map=inp.body_map)
    v.raise_if_failed()
    mj = v.report or {}
    v = run_paicad(x, s, "paicad_shell_check", base, cwd=C, report=os.path.join(C, CHECK_JSON), success=[], backup=[C, F],
                   body_map=inp.body_map)
    v.raise_if_failed()
    cj = v.report or {}
    rels = out_files(cj)
    checks = cj.get("checks") if isinstance(cj.get("checks"), dict) else {}
    q = checks.get("quality") if isinstance(checks.get("quality"), dict) else {}
    fx = checks.get("fixed") if isinstance(checks.get("fixed"), dict) else {}
    ctx.add_output(os.path.join(C, CHECK_JSON))
    prev = dict(r.get("geometry") or {})
    prev.update({"morph_max_disp_mm": mj.get("max_disp_mm"), "max_warpage_deg": q.get("max_warpage_deg"),
                 "min_jacobian": q.get("min_jacobian"), "moved_fixed_nodes": fx.get("moved_fixed_nodes"),
                 "check_elapsed_s": cj.get("elapsed_s"), "check_status": cj.get("status"), "shell_file_count": len(rels)})
    ctx.patch_result({"geometry": prev, "shell_files": rels})
