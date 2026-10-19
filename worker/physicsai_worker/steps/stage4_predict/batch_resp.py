"""④ PB_RESP_EXTRACT — 끝난 일괄 예측 배치의 H3D 성능 다시 추출(phase3 §22.3.5 S17): PX_PREP → RESPONSE_EXTRACT_RUNS → PX_TABLE.

재사용 배치에 나중에 정의한 H3D 성능 값을 채운다. run마다 기존 `H3D_REQUESTS.txt`·`RESPONSES.*`·`responses_pred.csv`를
`_backup`으로 옮기고 현재 템플릿 H3D 성능 전부로 다시 추출한 뒤 CURVE 값을 포함해 `responses_pred.csv`를 다시 쓴다.
배치 표(`predict_batch_runs.responses`)만 갱신하고 하위 PREDICT의 `result.response_table`은 그대로 둔다(§22.17 R-5).
"""

from __future__ import annotations

import math
import os
from typing import Any

from physicsai_core.db.repositories import jobs as jobs_repo
from physicsai_core.db.repositories import param_sets as ps_repo
from physicsai_core.db.repositories import predict_batches as pb_repo
from physicsai_core.errors import StepFailure
from physicsai_core.parsers.name_value import read_name_value_csv
from physicsai_core.stage4_predict import performance, run_metrics
from physicsai_core.stage4_predict import responses as resp_mod

from ..response_tcl import curve_values, extract_in_folder, merge_curve, warn_reasons, write_values_csv

PRED_CSV = "responses_pred.csv"


def _batch_ps(ctx: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    bid = ctx.params.get("batch_id")
    with ctx.ex.engine.connect() as conn:
        b = pb_repo.get(conn, bid) if isinstance(bid, str) else None
        ps = ps_repo.get(conn, b["param_set_id"]) if b else None
    if b is None or b["study_id"] != ctx.study["id"] or ps is None:
        raise StepFailure("INPUT_INVALID", "일괄 예측 배치 또는 템플릿을 찾을 수 없습니다")
    return b, ps


def px_prep(ctx: Any) -> None:
    b, ps = _batch_ps(ctx)
    h3d_names = [n for n, d in performance.perf_defs(ps.get("responses")).items() if d.source == "H3D"]
    if not h3d_names:
        raise StepFailure("INPUT_INVALID", "템플릿에 H3D 성능이 없습니다")
    targets: list[dict[str, Any]] = []
    missing: list[str] = []
    ambiguous: list[str] = []
    with ctx.ex.engine.connect() as conn:
        for r in pb_repo.runs_with_jobs(conn, b["id"]):
            if pb_repo.row_state(r, r["job_state"]) != "SUCCEEDED":
                continue
            files = run_metrics.locate_run_files(conn, ctx.root, jobs_repo.get_job(conn, r["predict_job_id"]))
            if files.result_dir is None:
                missing.append(r["run_key"])
                continue
            h3ds = resp_mod.h3d_candidates(files.result_dir)
            if len(h3ds) != 1:
                ambiguous.append(r["run_key"])
                continue
            targets.append({"doe_no": r["doe_no"], "run_key": r["run_key"], "result_rel": ctx.rel(files.result_dir),
                            "h3d": h3ds[0], "curve_rel": ctx.rel(files.curve_json) if files.curve_json else None})
    if missing:
        ctx.add_warning("RUN_RESULT_MISSING", f"결과 폴더가 없는 run {len(missing)}개를 건너뜀: {', '.join(missing[:10])}")
    if ambiguous:
        ctx.add_warning("RESP_H3D_AMBIGUOUS", f"h3d가 정확히 1개가 아닌 run {len(ambiguous)}개를 건너뜀: {', '.join(ambiguous[:10])}")
    if not targets:
        raise StepFailure("INPUT_INVALID", "성능을 다시 추출할 run이 없습니다(성공 run 중 결과 h3d가 1개인 run 없음)")
    ctx.log(f"대상 run {len(targets)}개 · H3D 성능 {', '.join(h3d_names)}")
    ctx.patch_result({"batch_id": b["id"], "param_set_id": ps["id"], "performances": h3d_names, "targets": targets})


def px_extract(ctx: Any) -> None:
    """run 사이에 취소 확인. run 실패는 경고만(계속)."""
    from physicsai_worker.limiter.base import LimiterError

    _b, ps = _batch_ps(ctx)
    responses = list(ps.get("responses") or [])
    targets = ctx.result().get("targets") or []
    ok: list[int] = []
    failed: list[str] = []
    for k, t in enumerate(targets, 1):
        ctx.checkpoint_cancel()
        res_dir = ctx.abs(t["result_rel"])
        P = os.path.dirname(res_dir)
        ctx.log(f"=== [{k}/{len(targets)}] {t['run_key']} ===")
        try:
            ctx.backup([os.path.join(P, PRED_CSV)])
            values, reasons = extract_in_folder(ctx, responses, res_dir, os.path.join(res_dir, t["h3d"]))
        except (StepFailure, LimiterError) as exc:
            ctx.log(f"[RUN FAIL] {t['run_key']}: {exc.code} {exc.message}")
            failed.append(t["run_key"])
        else:
            curve = ctx.abs(t["curve_rel"]) if t.get("curve_rel") else os.path.join(P, "curve.json")
            cvals, creasons = curve_values(ctx, responses, curve)
            merge_curve(responses, values, reasons, cvals, creasons)
            warn_reasons(ctx, reasons, f"{t['run_key']}: ")
            write_values_csv(ctx, os.path.join(P, PRED_CSV), values)
            ok.append(t["doe_no"])
        ctx.progress(k / len(targets) * 100.0, f"{k}/{len(targets)} {t['run_key']}", force=True)
    if failed:
        ctx.add_warning("PARTIAL_OUTPUT", f"run {len(targets)}개 중 {len(failed)}개 추출 실패: {', '.join(failed[:10])}")
    ctx.patch_result({"extracted": ok, "failed_runs": failed})


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None


def px_table(ctx: Any) -> None:
    b, ps = _batch_ps(ctx)
    res = ctx.result()
    names = {str(r.get("name")) for r in ps.get("responses") or [] if isinstance(r, dict)}
    by_no = {t["doe_no"]: t for t in res.get("targets") or []}
    updates: dict[int, dict[str, float]] = {}
    for no in res.get("extracted") or []:
        t = by_no.get(no)
        if t is None:
            continue
        vals = read_name_value_csv(os.path.join(os.path.dirname(ctx.abs(t["result_rel"])), PRED_CSV))
        updates[no] = {k: f for k, v in vals.items() if (f := _num(v)) is not None}

    def tx(c: Any) -> None:
        cur = {r["doe_no"]: r for r in pb_repo.runs(c, b["id"])}
        for no, vals in updates.items():
            old = (cur.get(no) or {}).get("responses") or {}
            keep = {k: v for k, v in old.items() if k not in names}  # 템플릿 밖 이름(실측 열 등)은 둔다
            pb_repo.set_run(c, b["id"], no, responses={**keep, **vals})

    ctx.ex.db(tx)
    summary = {"targets": len(by_no), "extracted": len(updates), "failed": len(res.get("failed_runs") or [])}
    ctx.log(f"배치 표 갱신: {summary}")
    ctx.patch_result({"summary": summary})


HANDLERS = {
    ("PB_RESP_EXTRACT", "PX_PREP"): px_prep,
    ("PB_RESP_EXTRACT", "RESPONSE_EXTRACT_RUNS"): px_extract,
    ("PB_RESP_EXTRACT", "PX_TABLE"): px_table,
}
