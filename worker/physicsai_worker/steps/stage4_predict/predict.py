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
from ..common import load_model, model_command_values, verify_model_integrity
from ..response_tcl import extract_in_folder, single_h3d, uses_tcl, warn_reasons, write_values_csv
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


def _response_extract_tcl(ctx: Any, ps: dict[str, Any]) -> None:
    """RESPONSE_EXTRACT 새 방식(phase3 §14.6): P/RESULT에 TCL 사본·H3D_REQUESTS.txt → RESPONSES.txt → P/responses_pred.csv.

    사용자 결정: 추출 실패는 그 응답만 "추출 실패"(값 null + 경고) — 예측 작업은 성공 유지. 응답별 사유는 result.response_errors.
    """
    from physicsai_worker.limiter.base import LimiterError

    responses = list(ps.get("responses") or [])
    if not responses:
        raise StepSkipped("응답 정의 없음")
    P = _P(ctx)
    res_dir = os.path.join(P, "RESULT")
    out = os.path.join(P, "responses_pred.csv")
    h3d, names = single_h3d(res_dir)
    if h3d is None:
        ctx.add_warning("RESP_H3D_AMBIGUOUS", f"응답 추출: 예측 결과 h3d가 정확히 1개가 아닙니다({len(names)}개) — 응답 값을 비워 둡니다")
        values: dict[str, float | None] = {r["name"]: None for r in responses}
        reasons = {r["name"]: "EXTRACT_FAILED" for r in responses}
    else:
        try:
            values, reasons = extract_in_folder(ctx, responses, res_dir, h3d)
        except (StepFailure, LimiterError) as exc:
            ctx.log(f"[RESPONSE FAIL] {exc.code}: {exc.message}")
            ctx.add_warning("RESPONSE_EXTRACT_FAILED",
                            f"응답 추출 실패({exc.code}): {exc.message} — 예측 결과는 그대로 사용합니다"[:480])
            values = {r["name"]: None for r in responses}
            reasons = {r["name"]: "EXTRACT_FAILED" for r in responses}
        else:
            warn_reasons(ctx, reasons)
    write_values_csv(ctx, out, values)
    ctx.add_output(out)
    ctx.patch_result({"response_errors": reasons})


def response_extract(ctx: Any) -> None:
    if ctx.settings.commands.response_extract is None:
        raise StepSkipped("추출 미구성")
    ps, S = param_set(ctx)  # prepared는 세트가 없을 수 있다(phase3 §11.5)
    if ps is None or S is None:
        raise StepSkipped("파라미터 세트 없음")
    if uses_tcl(ctx):
        return _response_extract_tcl(ctx, ps)
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
