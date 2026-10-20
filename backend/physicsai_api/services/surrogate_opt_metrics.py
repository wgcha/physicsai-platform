"""⑤ 플랫폼 내장 최적화 지표(run_metrics·performance 값·새 지표·성능 스냅숏) — surrogate_opt_problem에서 재노출."""

from __future__ import annotations

from typing import Any

from physicsai_core.db.repositories import jobs as jobs_repo
from physicsai_core.db.repositories import predict_batches as pb_repo
from physicsai_core.stage4_predict import performance, run_metrics

from ..context import AppContext
from .common import study_root

PERF_PREFIX = "perf:"


def _p(out: list[dict[str, Any]], code: str, message: str, field: str | None = None, **extra: Any) -> None:
    out.append({"code": code, "field": field, "message": message, **extra})


# ---- 지표(run_metrics·performance) ------------------------------------------------------------------


def run_metric_rows(ctx: AppContext, conn: Any, study: dict[str, Any], batch_id: str) -> list[tuple[dict[str, Any], Any]]:
    """배치 run 행 + (성공이면) RunMetrics."""
    root = study_root(ctx, study)
    out = []
    for r in pb_repo.runs_with_jobs(conn, batch_id):
        m = None
        if pb_repo.row_state(r, r["job_state"]) == "SUCCEEDED":
            m = run_metrics.load_run_metrics(run_metrics.locate_run_files(conn, root, jobs_repo.get_job(conn, r["predict_job_id"])),
                                             max_bytes=ctx.settings.ui.max_artifact_bytes)
        out.append((r, m))
    return out


def metric_value(m: Any, metric: str, series: str | None, table: Any, perfs: dict[str, Any] | None = None
                 ) -> tuple[float | None, str | None]:
    """(값, 사유) — `perf:`는 performance.perf_value(사유 포함), 그 밖은 run_metrics.metric_value(사유 NO_VALUE)."""
    if m is None:
        return None, None
    if metric.startswith(PERF_PREFIX):
        d = (perfs or {}).get(metric[len(PERF_PREFIX):])
        if d is None:
            return None, "NOT_DEFINED"
        return performance.perf_value(d, m)
    try:
        v = run_metrics.metric_value(m, metric, series=series, table=table)
    except ValueError:
        return None, "NO_VALUE"
    return v, None if v is not None else "NO_VALUE"


def value(m: Any, metric: str, series: str | None, table: Any, perfs: dict[str, Any] | None = None) -> float | None:
    return metric_value(m, metric, series, table, perfs)[0]


def new_metrics(ps: dict[str, Any]) -> set[str]:
    """새 DOE에서 고를 수 있는 지표: 템플릿 응답 이름 → resp:<NAME>_MIN|_MAX, curve:*."""
    out = {f"curve:{k}" for k in run_metrics.CURVE_KINDS}
    for r in ps.get("responses") or []:
        name = r.get("name") if isinstance(r, dict) else None
        if isinstance(name, str):
            for suf in ("MIN", "MAX"):
                mid = f"resp:{name}_{suf}"
                if run_metrics.METRIC_RE.fullmatch(mid):
                    out.add(mid)
    return out


def snapshot_perfs(settings: dict[str, Any]) -> dict[str, Any]:
    """settings.performances 스냅샷 → PerfDef."""
    return performance.perf_defs([{"name": k, "unit": (v or {}).get("unit", ""), "spec": (v or {}).get("spec")}
                                  for k, v in (settings.get("performances") or {}).items()])
