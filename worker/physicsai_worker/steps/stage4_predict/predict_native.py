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
from physicsai_core.stage4_predict import nearest as nearest_mod

from ..geometry_native import (
    LocalRunner,
    effective_opts,
    engine_version,
    ensure_prep_ready,
    native_inputs,
    read_json,
    run_paicad,
)
from ...signals import StepSkipped
from .predict_inputs import assemble_into, predict_dir


def is_native_set(ps: dict[str, Any] | None) -> bool:
    return bool(ps) and ps.get("engine") == "native"  # type: ignore[union-attr]


def _G(ctx: Any) -> str:
    return os.path.join(predict_dir(ctx), "geom")


def pr_prep(ctx: Any, m: dict[str, Any], ps: dict[str, Any], S: str) -> None:
    """PR_PREP(native): 준비본 유효성(INPUT_CHANGED) + 옵션 사용값. 값은 반올림하지 않는다(GE-9)."""
    s = ctx.settings
    if not ps.get("starter_name") or not os.path.isfile(os.path.join(S, "radioss_assem", ps["starter_name"])):
        raise StepFailure("INPUT_CHANGED", "파라미터 세트 파일이 없습니다: radioss_assem/" + str(ps.get("starter_name")))
    opts = effective_opts(s, ps.get("geom_options"))
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
    ctx.patch_result({"model_id": m["id"], "param_set_id": ps["id"], "values": values, "applied_values": values,
                      "out_of_range": [o["name"] for o in oor], "template_kind": "assembly", "nearest": None,
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
    U = os.path.join(G, "update")
    v = run_paicad(LocalRunner(ctx), s, "paicad_update",
                   {**inp.base_values(s), "values_json": os.path.join(G, "values.json"), "options_json": os.path.join(G, "options.json"),
                    "update_dir": U}, cwd=U, report=os.path.join(U, "update.json"), success=[os.path.join(U, "sample.brep")],
                   backup=[U], body_map=inp.body_map)
    v.raise_if_failed()
    ctx.add_output(os.path.join(U, "update.json"))
    ctx.patch_result({"geometry": {"update_elapsed_s": (v.report or {}).get("elapsed_s")}})


def mesh(ctx: Any, S: str) -> None:
    """MESH(native) = `paicad_morph` → `paicad_check`(PASS일 때만 `P/geom/{mesh_include_name}`)."""
    _skip_if_no_geometry(ctx)
    s, G = ctx.settings, _G(ctx)
    inp = _inputs(ctx, S)
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


def rad_assemble(ctx: Any, S: str, inp_dir: str) -> str:
    """RAD_ASSEMBLE(native): 조립 폴더 사본(배정 baseline) + 새 include(형상 값 없으면 기준 메시 그대로) → P/INPUT, 그 뒤 쉘 두께 적용.
    starter 이름을 돌려준다(이후 commands.rad_assemble·결과 기록은 기존 체인)."""
    s, r = ctx.settings, ctx.result()
    inp = _inputs(ctx, S)
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
