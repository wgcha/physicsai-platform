"""④ 일괄 예측 설계공간 지도 데이터(phase3 §17.4 S12, D3-59): run별 반영값 + 대표값(커브·RESP·결과 표).

PCA·PLS·평행 좌표는 프런트가 계산한다(§17.5). 여기서는 완료 run의 `curve.json`·`RESPONSES.txt`를 `run_metrics`로
요약만 한다(파일별 LRU — 두 번째 호출부터 파일을 다시 읽지 않음). 성공이 아닌 run은 파일을 읽지 않는다.
DB 조회는 한 연결에서 끝내고 파일 읽기는 연결 밖에서 한다(동기 라우터 = 스레드 풀).
"""

from __future__ import annotations

import math
from typing import Any

from physicsai_core.db.repositories import jobs as jobs_repo
from physicsai_core.db.repositories import param_sets as ps_repo
from physicsai_core.db.repositories import predict_batches as pb_repo
from physicsai_core.db.repositories import studies as studies_repo
from physicsai_core.stage4_predict.batch_matrix import batch_label
from physicsai_core.stage4_predict.nearest import integer_vars
from physicsai_core.stage4_predict.run_metrics import METRIC_RE, RunFiles, load_run_metrics, locate_run_files

from ..context import AppContext
from .common import study_root
from .predict_batches import _require_batch

CURVE_METRICS = (("curve:max", "커브 최대값"), ("curve:min", "커브 최소값"), ("curve:absmax", "커브 |최대|"))


def _finite(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return None
    return float(v)


def _resp_label(key: str) -> tuple[str, str]:
    """`CornerStress_MAX` → (`CornerStress`, `CornerStress 최대(RESP)`)."""
    name, _, stat = key.rpartition("_")
    return name, f"{name} {'최대' if stat == 'MAX' else '최소'}(RESP)"


def design_map(ctx: AppContext, batch_id: str) -> dict[str, Any]:
    max_bytes = ctx.settings.ui.max_artifact_bytes
    with ctx.engine.connect() as conn:
        b = _require_batch(conn, batch_id)
        s = studies_repo.require(conn, b["study_id"])
        ps = ps_repo.get(conn, b["param_set_id"]) or {}
        root = study_root(ctx, s)
        rows = pb_repo.runs_with_jobs(conn, batch_id)
        located: dict[int, RunFiles] = {}
        for r in rows:
            if r["predict_job_id"] and pb_repo.row_state(r, r["job_state"]) == "SUCCEEDED":
                located[r["doe_no"]] = locate_run_files(conn, root, jobs_repo.get_job(conn, r["predict_job_id"]))

    ints = integer_vars(list(ps.get("tpl_params") or []))
    params = [p for p in ps.get("parameters") or [] if isinstance(p, dict) and p.get("name")]
    units = {str(x.get("name")): (x.get("unit") or None) for x in ps.get("responses") or [] if isinstance(x, dict)}

    runs: list[dict[str, Any]] = []
    series: list[str] = []
    resp_keys: set[str] = set()
    counts = {"total": len(rows), "succeeded": 0, "no_curve": 0, "no_resp": 0}
    for r in rows:
        state = pb_repo.row_state(r, r["job_state"])
        applied = r["applied_values"] or {}
        values = {p["name"]: v for p in params if (v := _finite(applied.get(p["name"]))) is not None}
        out: dict[str, Any] = {"doe_no": r["doe_no"], "run_key": r["run_key"], "state": state, "values": values,
                               "curve": None, "resp": None, "tbl": None}
        files = located.get(r["doe_no"])
        if files is not None:
            counts["succeeded"] += 1
            m = load_run_metrics(files, max_bytes=max_bytes)
            if m.curve:
                out["curve"] = {k: {**v, "n": int(v["n"])} for k, v in m.curve.items()}
                series.extend(k for k in m.curve if k not in series)
            else:
                counts["no_curve"] += 1
            if m.resp is not None:
                out["resp"] = {k: v for k, v in m.resp.items() if METRIC_RE.fullmatch(f"resp:{k}")}
                resp_keys.update(out["resp"])
            else:
                counts["no_resp"] += 1
            out["tbl"] = {str(k): _finite(v) for k, v in (r["responses"] or {}).items()}
        runs.append(out)

    metrics: list[dict[str, Any]] = []
    if series:
        metrics += [{"id": i, "label": lb, "unit": None, "needs_series": True} for i, lb in CURVE_METRICS]
    for key in sorted(resp_keys):
        name, label = _resp_label(key)
        metrics.append({"id": f"resp:{key}", "label": label, "unit": units.get(name), "needs_series": False})
    has_resp_file = any(x["resp"] is not None for x in runs)
    if not has_resp_file:  # 옛 방식 배치(RESPONSES.txt 없음)만 결과 표 값
        for name, unit in units.items():
            mid = f"tbl:{name}"
            if METRIC_RE.fullmatch(mid) and any((x["tbl"] or {}).get(name) is not None for x in runs):
                metrics.append({"id": mid, "label": f"{name}(결과 표)", "unit": unit, "needs_series": False})

    return {
        "batch_id": b["id"], "label": batch_label(b["batch_no"]), "status": b["status"],
        "parameters": [{"name": p["name"], "integer": p["name"] in ints, "min": float(p["min"]), "max": float(p["max"])}
                       for p in params],
        "series": series, "metrics": metrics, "runs": runs, "counts": counts,
    }
