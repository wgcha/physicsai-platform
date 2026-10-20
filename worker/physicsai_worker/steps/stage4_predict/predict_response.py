"""④ PREDICT 응답 추출(원본 ⑤ m_4 TCL 방식)·응답 표 step — predict에서 재노출."""

from __future__ import annotations

import json
import os
from typing import Any

from physicsai_core.commands import fwd
from physicsai_core.errors import StepFailure
from physicsai_core.fileutil import write_json
from physicsai_core.parsers.name_value import read_name_value_csv

from ...signals import StepSkipped
from ..response_tcl import (
    append_curve_csv,
    curve_values,
    extract_in_folder,
    has_h3d,
    merge_curve,
    single_h3d,
    uses_tcl,
    warn_reasons,
    write_values_csv,
)
from .predict_inputs import (
    is_prepared,
    param_set,
)
from .predict_inputs import predict_dir as _P


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
    ok = True
    if not has_h3d(responses):  # S17 §22.3.4: CURVE 성능뿐이면 TCL·요청 파일 없이 curve.json에서만
        values, reasons = extract_in_folder(ctx, responses, res_dir, "")
    elif h3d is None:
        ok = False
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
            ok = False
    cvals, creasons = curve_values(ctx, responses, os.path.join(P, "curve.json"))
    merge_curve(responses, values, reasons, cvals, creasons)
    warn_reasons(ctx, reasons if ok else creasons)
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
    append_curve_csv(ctx, ps["responses"], out, os.path.join(P, "curve.json"))  # S17 §22.3.4: 옛 방식도 CURVE 값


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
