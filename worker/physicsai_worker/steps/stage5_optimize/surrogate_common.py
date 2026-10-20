"""⑤ SURROGATE_OPT 공용 도우미(opt 행·반복 폴더·문제 행·적합 시계) — surrogate에서 재노출."""

from __future__ import annotations

import csv
import io
import os
import time
from typing import Any

from physicsai_core.db.repositories import surrogate_opts as so_repo
from physicsai_core.errors import StepFailure
from physicsai_core.stage4_predict import run_metrics
from physicsai_core.stage5_optimize.surrogate import algo as so_algo
from physicsai_core.stage5_optimize.surrogate import criteria
from physicsai_core.stage5_optimize.surrogate import dataset as ds
from physicsai_core.stage5_optimize.surrogate import limit_threads

STOP_TEXT = {ds.STOP_CONVERGED: "수렴", ds.STOP_MAX_ITER: "최대 반복", ds.STOP_NO_NEW: "새 후보 없음"}


# ---- 공용 ----------------------------------------------------------------------------------------


def _opt(ctx: Any) -> dict[str, Any]:
    oid = ctx.params.get("surrogate_opt_id")
    with ctx.ex.engine.connect() as conn:
        opt = so_repo.get(conn, oid) if isinstance(oid, str) else None
    if opt is None or opt["study_id"] != ctx.study["id"]:
        raise StepFailure("INPUT_INVALID", "내장 최적화를 찾을 수 없습니다")
    if opt["status"] not in so_repo.ACTIVE or opt["current_job_id"] != ctx.ex.job_id:
        raise StepFailure("SURROGATE_OPT_INACTIVE", "이 반복 작업은 진행 중인 내장 최적화의 최신 작업이 아닙니다(취소·종료됨)")
    return opt


def _round(ctx: Any) -> int:
    r = ctx.params.get("round")
    if not isinstance(r, int) or r < 1:
        raise StepFailure("INPUT_INVALID", "반복 번호가 올바르지 않습니다")
    return r


def _O(ctx: Any, opt: dict[str, Any]) -> str:
    return ctx.abs(opt["dir_rel"])


def _iter_dir(O: str, n: int) -> str:
    return os.path.join(O, f"iter_{n:02d}")


def _problem(opt: dict[str, Any]) -> ds.Problem:
    """opt-native ON-C4: 사용자가 정하지 않은 기준(방향·임계값·가중치·목적)은 채우지 않고 작업을 실패시킨다."""
    miss = criteria.settings_missing(opt["settings"])
    if miss:
        raise StepFailure(criteria.CODE, f"{criteria.MESSAGE}: {', '.join(miss)}")
    return ds.Problem.from_settings(opt["settings"])


def _metric(m: run_metrics.RunMetrics, metric: str, series: str | None, table: Any) -> float | None:
    try:
        return run_metrics.metric_value(m, metric, series=series, table=table)
    except ValueError:
        return None


def _read_points(ctx: Any, O: str, problem: ds.Problem, last_iter: int) -> list[ds.Point]:
    p = os.path.join(_iter_dir(O, last_iter), "dataset.csv")
    if not os.path.isfile(p):
        raise StepFailure("INPUT_CHANGED", f"자료 파일이 없습니다: {ctx.rel(p)}")
    with open(p, encoding="utf-8-sig") as fh:
        return ds.read_dataset_csv(fh.read(), problem)


def _threads(ctx: Any) -> None:
    s = ctx.settings
    limit_threads(min(s.surrogate_opt.blas_threads, s.worker.max_logical_cores or s.surrogate_opt.blas_threads))


class _Clock:
    """SO_FIT+SO_PROPOSE 합계 시간 한도(fit_timeout_s) + 취소 확인."""

    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx
        clk = ctx.result().get("fit_clock") or {}
        same = isinstance(clk, dict) and clk.get("job_id") == ctx.ex.job_id and isinstance(clk.get("t0"), (int, float))
        self.t0 = float(clk["t0"]) if same else time.time()  # 재시도(다른 작업)는 새로 잰다
        self.limit = ctx.settings.surrogate_opt.fit_timeout_s

    def __call__(self) -> None:
        self.ctx.checkpoint()
        if time.time() - self.t0 > self.limit:
            raise StepFailure(ds.FAIL_TIMEOUT, f"대리모델 학습·후보 탐색이 {self.limit}초를 넘었습니다 — 탐색 run·변수를 줄이세요")


# ---- SO_NEXT --------------------------------------------------------------------------------------


def _multi_matrix(ctx: Any, ps: dict[str, Any], st: dict[str, Any], rows: list[dict[str, Any]]) -> Any:
    from physicsai_core.geometry import baselines as bl
    from physicsai_core.stage4_predict.batch_multi import build_multi_table

    try:
        pm = bl.load(ctx.abs(ps["stored_rel"]), ctx.settings.geometry.max_report_bytes)
    except bl.MapError as exc:
        raise StepFailure(exc.code, exc.message) from None
    if pm is None or pm.get("status") != "confirmed":
        raise StepFailure("INPUT_CHANGED", "최적화를 시작한 뒤 다중 baseline 매칭표가 바뀌었습니다(미확정) — 확정 후 다시 실행하세요")
    levels = (st.get("levels") or {}).get("baseline") or []
    pts = []
    for v in rows:
        p = dict(v)
        if levels and isinstance(v.get("baseline"), (int, float)):
            p["baseline"] = levels[int(round(v["baseline"]))]
        pts.append(p)
    return build_multi_table(pts, ps, pm)


def _table_text(names: list[str], cands: list[dict[str, Any]]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(names)
    for c in cands:
        w.writerow([repr(float(c["values"][n])) for n in names])
    return buf.getvalue()


def _now() -> Any:
    from sqlalchemy import func

    return func.now()


def _algo_meta(s: dict[str, Any]) -> dict[str, Any]:
    """summary.json·opt.json 기록(§6.6): algorithm·algo_options(기본 채운 사용값)·verification."""
    return {"algorithm": so_algo.settings_algorithm(s), "algo_options": s.get("algo_options") or {},
            "verification": so_algo.settings_verification(s)}
