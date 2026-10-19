"""④ PREDICT(A)의 native 분기(geometry-engine.md §7.3.5): PR_PREP·TPL_RENDER·GEOM_UPDATE·MESH.

tpl 렌더·SimLab·HyperMesh 대신 `P/geom/{options.json, values.json, update/, morph/, check/, <mesh_include_name>}`를 만든다.
RAD_ASSEMBLE 이후는 기존 체인 그대로(`predict_inputs._assemble_parametric`).
"""

from __future__ import annotations

import os
from typing import Any

from physicsai_core.errors import StepFailure
from physicsai_core.fileutil import write_json
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
from .predict_inputs import predict_dir


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
    ensure_prep_ready(s, S, opts, ver)
    values = {k: float(v) for k, v in ctx.params["values"].items()}
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
    ctx.patch_result({"model_id": m["id"], "param_set_id": ps["id"], "values": values, "applied_values": values,
                      "out_of_range": [o["name"] for o in oor], "template_kind": "assembly", "nearest": None,
                      "engine": "native", "engine_version": ver, "ocp_version": ocp})


def tpl_render(ctx: Any) -> None:
    """TPL_RENDER(native) = `P/geom/values.json`(§4.4) 작성. CAD 사본 없음(paicad가 S/cad를 읽는다)."""
    r = ctx.result()
    dst = os.path.join(_G(ctx), "values.json")
    ctx.backup([dst])
    write_json(dst, values_document(r["values"], "predict", ctx.ex.job_id, r.get("engine_version")))
    ctx.add_output(dst)


def _inputs(ctx: Any, S: str) -> Any:
    return native_inputs(ctx.settings, S, os.path.join(S, "radioss_assem"))


def geom_update(ctx: Any, S: str) -> None:
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
