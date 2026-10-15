"""④ PREDICT(§8.9, phase3 §11.4·§11.5). 입력 준비 step(GEOM_UPDATE·MESH·RAD_ASSEMBLE)은 predict_inputs."""

from __future__ import annotations

import glob
import json
import os
from typing import Any

from physicsai_core.commands import fwd
from physicsai_core.errors import StepFailure
from physicsai_core.fileutil import copy_file, write_json, write_text
from physicsai_core.naming import TPL_NAME
from physicsai_core.parsers.name_value import read_name_value_csv
from physicsai_core.stage4_predict import nearest as nearest_mod
from physicsai_core.stage4_predict.param_sets import read_samples
from physicsai_core.stage4_predict.xydata import parse_xydata
from physicsai_core.tpl_render import render_tpl

from ...signals import StepSkipped
from ..common import load_model, verify_model_integrity
from .predict_inputs import (
    PREPARED_SKIP,
    check_prepared,
    geom_update,
    is_prepared,
    mesh,
    param_set,
    rad_assemble,
    require_param_set,
)
from .predict_inputs import predict_dir as _P

_ps = require_param_set


def _pr_prep_prepared(ctx: Any, m: dict[str, Any]) -> None:
    """PR_PREP(prepared, phase3 §11.5): 입력 재검사·params.json. 형상 값 없음."""
    plan = check_prepared(ctx)
    ps, _S = param_set(ctx)
    P = _P(ctx)
    os.makedirs(P, exist_ok=True)
    pj = os.path.join(P, "params.json")
    ctx.backup([pj])
    write_json(pj, {
        "input_mode": "prepared", "input_path": ctx.params["input_path"], "input_kind": plan.kind,
        "starter_name": plan.starter, "files": [os.path.basename(f) for f in plan.files], "values": {},
        "model_id": m["id"], "param_set_id": ps["id"] if ps else None, "nearest": None,
    })
    ctx.patch_result({
        "model_id": m["id"], "param_set_id": ps["id"] if ps else None, "input_mode": "prepared",
        "input_path": ctx.params["input_path"], "values": {}, "applied_values": {}, "out_of_range": [], "nearest": None,
    })


def pr_prep(ctx: Any) -> None:
    m = load_model(ctx, ctx.params["model_id"])
    verify_model_integrity(ctx, m)
    if is_prepared(ctx):
        return _pr_prep_prepared(ctx, m)
    ps, S = _ps(ctx)
    for need in (TPL_NAME, os.path.join("cad", ps["cad_file_name"]), os.path.join("radioss_assem", ps["starter_name"])):
        if not os.path.isfile(os.path.join(S, need)):
            raise StepFailure("INPUT_CHANGED", f"파라미터 세트 파일이 없습니다: {need}")
    values = {k: float(v) for k, v in ctx.params["values"].items()}
    mode = ctx.settings.predict.integer_rounding
    applied = nearest_mod.applied_values(ps["tpl_params"], values, mode)
    rounded = nearest_mod.rounded(ps["tpl_params"], values, mode)
    oor = nearest_mod.out_of_range(ps["parameters"], values)
    _cols, samples = read_samples(S)
    near = nearest_mod.nearest_run(ps["parameters"], samples, applied) if samples else None
    P = _P(ctx)
    os.makedirs(P, exist_ok=True)
    pj = os.path.join(P, "params.json")
    ctx.backup([pj])
    write_json(pj, {
        "values": values, "applied_values": applied, "rounded": rounded,
        "value_source": ctx.params.get("value_source"), "source_run_key": ctx.params.get("source_run_key"),
        "out_of_range": oor, "nearest": near, "model_id": m["id"], "param_set_id": ps["id"],
        "unit_system": ps["unit_system"],
    })
    cad_dst = os.path.join(P, "geom", ps["cad_file_name"])
    ctx.backup([cad_dst])
    copy_file(os.path.join(S, "cad", ps["cad_file_name"]), cad_dst, checkpoint=ctx.checkpoint)
    ctx.patch_result({
        "model_id": m["id"], "param_set_id": ps["id"], "values": values, "applied_values": applied,
        "out_of_range": [o["name"] for o in oor],
        "nearest": {"run_key": near["run_key"], "distance": near["distance"]} if near else None,
    })


def tpl_render(ctx: Any) -> None:
    if is_prepared(ctx):
        raise StepSkipped(PREPARED_SKIP)
    ps, S = _ps(ctx)
    r = ctx.result()
    with open(os.path.join(S, TPL_NAME), encoding="utf-8-sig") as fh:
        text = fh.read()
    out = render_tpl(text, r["values"], r["applied_values"])
    dst = os.path.join(_P(ctx), "geom", ctx.settings.predict.rendered_script_name)
    ctx.backup([dst])
    write_text(dst, out)
    ctx.add_output(dst)


def edspy_predict(ctx: Any) -> None:
    m = load_model(ctx, ctx.params["model_id"])
    P = _P(ctx)
    starter = ctx.result()["starter"]
    stem = os.path.splitext(starter)[0]
    res_dir = os.path.join(P, "RESULT")
    os.makedirs(res_dir, exist_ok=True)
    pred = os.path.join(res_dir, f"{stem}_pred.h3d")
    ctx.run_local(
        "edspy_predict",
        {"pred_h3d": pred, "model_psmdl": ctx.abs(m["psmdl_rel"]), "model_pscfg": ctx.abs(m["pscfg_rel"]),
         "starter": os.path.join(P, "INPUT", starter)},
        cwd=os.path.join(P, "INPUT"),
        outputs_to_backup=[pred],
        env_add=dict(ctx.settings.predict.env),
    )
    if not os.path.isfile(pred):
        raise StepFailure("OUTPUT_MISSING", f"예측 결과 {os.path.basename(pred)}가 만들어지지 않았습니다")
    ctx.add_output(pred)
    ctx.patch_result({"pred_h3d_rel": ctx.rel(pred)})


def contour_preview(ctx: Any) -> None:
    P = _P(ctx)
    pred = ctx.abs(ctx.result()["pred_h3d_rel"])
    preview = os.path.join(P, "H3D_PREVIEW.json")
    images_before = {n for n in os.listdir(P) if n.lower().endswith((".png", ".jpg", ".jpeg"))}
    ctx.run_local(
        "contour_preview",
        {"preview_tcl": ctx.settings.resources.preview_pred_h3d_tcl, "pred_h3d_fwd": fwd(pred), "preview_json_fwd": fwd(preview)},
        cwd=P,
        outputs_to_backup=[preview],
    )
    if not os.path.isfile(preview):
        raise StepFailure("OUTPUT_MISSING", "H3D_PREVIEW.json이 만들어지지 않았습니다")
    pid = ctx.register_artifact("PREVIEW_JSON", preview, "application/json")
    image_ids = []
    for n in sorted(os.listdir(P)):
        if n.lower().endswith((".png", ".jpg", ".jpeg")) and n not in images_before:
            aid = ctx.register_artifact("PREVIEW_IMAGE", os.path.join(P, n))
            if aid:
                image_ids.append(aid)
    ctx.patch_result({"preview_json_artifact_id": pid, "image_artifact_ids": image_ids})


def curve_pick(ctx: Any) -> None:
    P = _P(ctx)
    res = os.path.join(P, "RESULT")
    cands = sorted(glob.glob(os.path.join(res, "*.xy")) + glob.glob(os.path.join(res, "*.xydata")), key=os.path.basename)
    if not cands:
        ctx.log("커브 파일 없음")
        ctx.patch_result({"curve_artifact_id": None, "curve": None})
        return
    data = parse_xydata(cands[0], display_name=os.path.basename(cands[0]))
    out = os.path.join(P, "curve.json")
    ctx.backup([out])
    write_json(out, data)
    aid = ctx.register_artifact("CURVE_JSON", out, "application/json")
    ctx.patch_result({"curve_artifact_id": aid})


def response_extract(ctx: Any) -> None:
    if ctx.settings.commands.response_extract is None:
        raise StepSkipped("추출 미구성")
    ps, S = param_set(ctx)  # prepared는 세트가 없을 수 있다(phase3 §11.5)
    if ps is None or S is None:
        raise StepSkipped("파라미터 세트 없음")
    resp = os.path.join(S, "responses.json")
    if not ps["responses"] or not os.path.isfile(resp):
        raise StepSkipped("응답 정의 없음")
    P = _P(ctx)
    pred = ctx.abs(ctx.result()["pred_h3d_rel"])
    out = os.path.join(P, "responses_pred.csv")
    ctx.run_local("response_extract", {"responses_json": resp, "pred_h3d": pred, "pred_h3d_fwd": fwd(pred),
                                        "out_csv": out, "work_dir": P}, cwd=P, outputs_to_backup=[out])
    if not os.path.isfile(out):
        raise StepFailure("OUTPUT_MISSING", "responses_pred.csv가 만들어지지 않았습니다")


def build_table(responses: list[dict[str, Any]], predicted: dict[str, float | None],
                measured: dict[str, Any] | None) -> list[dict[str, Any]]:
    rows = []
    for r in responses:
        pv = predicted.get(r["name"])
        mv = (measured or {}).get(r["name"])
        diff = None
        if pv is not None and mv is not None and mv != 0:
            diff = round((pv - mv) / abs(mv) * 100.0, 6)
        rows.append({"name": r["name"], "unit": r.get("unit", ""), "predicted": pv, "nearest_measured": mv, "diff_pct": diff})
    return rows


def response_table(ctx: Any) -> None:
    ps, _S = param_set(ctx)
    if is_prepared(ctx) and (ps is None or not ps["responses"]):  # phase3 §11.5: 응답 정의 없음 → 빈 표
        ctx.patch_result({"response_table": []})
        raise StepSkipped("응답 정의 없음")
    if ps is None:
        raise StepFailure("INPUT_INVALID", "파라미터 세트를 찾을 수 없습니다")
    P = _P(ctx)
    predicted = read_name_value_csv(os.path.join(P, "responses_pred.csv"))
    with open(os.path.join(P, "params.json"), encoding="utf-8") as fh:
        near = None if is_prepared(ctx) else json.load(fh).get("nearest")  # prepared: 최근접 실측 없음
    table = build_table(ps["responses"], predicted, (near or {}).get("measured"))
    out = os.path.join(P, "responses.json")
    ctx.backup([out])
    write_json(out, {"rows": table, "nearest_run_key": (near or {}).get("run_key")})
    aid = ctx.register_artifact("RESPONSE_TABLE", out, "application/json")
    ctx.patch_result({"response_table": table, "response_table_artifact_id": aid})


HANDLERS = {
    ("PREDICT", "PR_PREP"): pr_prep,
    ("PREDICT", "TPL_RENDER"): tpl_render,
    ("PREDICT", "GEOM_UPDATE"): geom_update,
    ("PREDICT", "MESH"): mesh,
    ("PREDICT", "RAD_ASSEMBLE"): rad_assemble,
    ("PREDICT", "EDSPY_PREDICT"): edspy_predict,
    ("PREDICT", "CONTOUR_PREVIEW"): contour_preview,
    ("PREDICT", "CURVE_PICK"): curve_pick,
    ("PREDICT", "RESPONSE_EXTRACT"): response_extract,
    ("PREDICT", "RESPONSE_TABLE"): response_table,
}
