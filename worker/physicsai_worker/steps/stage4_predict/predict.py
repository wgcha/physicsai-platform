"""④ PREDICT(§8.9, phase3 §11.4·§11.5). 입력 준비 step(GEOM_UPDATE·MESH·RAD_ASSEMBLE)은 predict_inputs.
300줄 분할(R-B): 응답 추출·표(RESPONSE_EXTRACT·RESPONSE_TABLE)는 `predict_response`(여기서 재노출)."""

from __future__ import annotations

import glob
import os
from typing import Any

from physicsai_core.commands import fwd
from physicsai_core.errors import StepFailure
from physicsai_core.fileutil import copy_file, write_json, write_text
from physicsai_core.naming import TPL_NAME
from physicsai_core.stage4_predict import nearest as nearest_mod
from physicsai_core.stage4_predict.param_sets import read_samples
from physicsai_core.stage4_predict.xydata import parse_xydata
from physicsai_core.tpl_render import render_tpl

from ...signals import StepSkipped
from ..common import load_model, model_command_values, verify_model_integrity
from .predict_inputs import (
    MESH_ONLY,
    PREPARED_SKIP,
    _judge_output,
    check_prepared,
    geom_update,
    is_prepared,
    mesh,
    param_set,
    rad_assemble,
    require_param_set,
    template_kind,
)
from .predict_inputs import predict_dir as _P
from .predict_response import response_extract, build_table, response_table  # noqa: F401 - 기존 경로 재노출

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
    res = {
        "model_id": m["id"], "param_set_id": ps["id"] if ps else None, "input_mode": "prepared",
        "input_path": ctx.params["input_path"], "values": {}, "applied_values": {}, "out_of_range": [], "nearest": None,
    }
    run = _batch_run_row(ctx)
    if run is not None:  # 일괄 예측 하위(phase3 §14.5): 입력값은 run 행에서
        res.update(values=run["values"], applied_values=run["applied_values"], out_of_range=list(run["out_of_range"] or []),
                   batch={"batch_id": run["batch_id"], "doe_no": run["doe_no"], "run_key": run["run_key"]})
    ctx.patch_result(res)


def _batch_run_row(ctx: Any) -> dict[str, Any] | None:
    from physicsai_core.db.repositories import predict_batches as pb_repo

    ref = pb_repo.batch_run_ref(ctx.job)
    if ref is None:
        return None
    with ctx.ex.engine.connect() as conn:
        rows = [r for r in pb_repo.runs(conn, ref[0]) if r["doe_no"] == ref[1]]
    if not rows:
        raise StepFailure("INPUT_INVALID", "일괄 예측 run 행을 찾을 수 없습니다")
    return rows[0]


def pr_prep(ctx: Any) -> None:
    m = load_model(ctx, ctx.params["model_id"])
    verify_model_integrity(ctx, m)
    if is_prepared(ctx):
        return _pr_prep_prepared(ctx, m)
    ps, S = _ps(ctx)
    kind = template_kind(ctx, ps)
    needs = [TPL_NAME, os.path.join("cad", ps["cad_file_name"])]
    if kind != MESH_ONLY:  # mesh_only 템플릿은 조립 폴더 없음(phase3 §14.4)
        if not ps.get("starter_name"):
            raise StepFailure("INPUT_INVALID", "조립 폴더가 없는 템플릿(메시 단독)입니다 — 조립 체인으로 예측할 수 없습니다")
        needs.append(os.path.join("radioss_assem", ps["starter_name"]))
    for need in needs:
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
        "out_of_range": [o["name"] for o in oor], "template_kind": kind,
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
    # 성공 판정 = 원본 ⑤ 기준 Predict(opti:323-329)와 같이 h3d 존재만 본다(phase3 D3-37): rc≠0·로그 오류 패턴은 경고
    rc = ctx.run_local(
        "edspy_predict",
        {"pred_h3d": pred, **model_command_values(ctx, "edspy_predict", m), "starter": os.path.join(P, "INPUT", starter)},
        cwd=os.path.join(P, "INPUT"),
        outputs_to_backup=[pred],
        env_add=dict(ctx.settings.predict.env),
        allow_nonzero_exit=True,
        log_errors_fail=False,
    )
    match = getattr(ctx, "last_error_match", None)
    if match and not (os.path.isfile(pred) and os.path.getsize(pred) > 0):
        ctx.log(f"[LOG_ERROR] 로그 오류 패턴: {match}")
    _judge_output(ctx, rc, pred, "예측")
    if match:
        ctx.add_warning("LOG_ERROR_PATTERN", f"예측: 로그에 오류 패턴({match})이 있었지만 결과 {os.path.basename(pred)}이(가) 있어 성공으로 처리했습니다")
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
