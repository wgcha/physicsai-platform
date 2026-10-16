"""컨투어 캡처 결과 조회(phase3 §15 S10): 예측 작업의 방향별 이미지·동영상 = 작업 result.media + 성공한 재캡처(방향별 덮어쓰기).

재캡처 작업(CONTOUR_RECAPTURE, params.source_job_id)은 원래 예측 작업의 result를 고치지 않고 자기 result.media에 남긴다.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import and_, select, update
from sqlalchemy.engine import Connection

from ...stage4_predict.contour_capture import media_items, merge_media
from ...state_machine import TERMINAL
from ..tables import artifacts, jobs, param_sets
from .jobs import row_dict

RECAPTURE = "CONTOUR_RECAPTURE"


def _source_col() -> Any:
    return jobs.c.params["source_job_id"].astext


def recaptures(conn: Connection, source_ids: Sequence[str]) -> list[dict[str, Any]]:
    """source 작업들의 재캡처 작업(전 상태), 생성 순."""
    if not source_ids:
        return []
    q = (select(jobs.c.id, jobs.c.state, jobs.c.result, jobs.c.params, jobs.c.created_at, jobs.c.finished_at)
         .where(and_(jobs.c.job_type == RECAPTURE, _source_col().in_(list(source_ids))))
         .order_by(jobs.c.created_at, jobs.c.id))
    return [row_dict(r) for r in conn.execute(q)]


def effective_media(conn: Connection, job: dict[str, Any]) -> dict[str, Any]:
    """{items:[{view, image_artifact_id, video_artifact_id, job_id}], capture(최근 결과 요약), recapture(진행 중|최근)}."""
    items = [{**m, "job_id": job["id"]} for m in media_items(job.get("result"))]
    capture = (job.get("result") or {}).get("capture")
    latest: dict[str, Any] | None = None
    for r in recaptures(conn, [job["id"]]):
        latest = r
        if r["state"] == "SUCCEEDED":
            items = merge_media(items, media_items(r["result"]), r["id"])
            capture = (r["result"] or {}).get("capture") or capture
    recap = None
    if latest is not None:
        recap = {"job_id": latest["id"], "state": latest["state"], "active": latest["state"] not in TERMINAL}
    return {"items": items, "capture": capture, "recapture": recap}


def media_views_for_jobs(conn: Connection, job_ids: Sequence[str]) -> dict[str, list[str]]:
    """예측 작업 id → 이미지가 있는 방향 목록(B 일괄 예측 행 `media_views`). 쿼리 2번."""
    ids = [j for j in job_ids if j]
    if not ids:
        return {}
    out: dict[str, list[dict[str, Any]]] = {}
    for r in conn.execute(select(jobs.c.id, jobs.c.result).where(jobs.c.id.in_(ids))):
        out[r.id] = [{**m, "job_id": r.id} for m in media_items(r.result)]
    for r in recaptures(conn, ids):
        src = (r["params"] or {}).get("source_job_id")
        if r["state"] == "SUCCEEDED" and src in out:
            out[src] = merge_media(out[src], media_items(r["result"]), r["id"])
    return {k: [m["view"] for m in v] for k, v in out.items()}


def _batch_param(conn: Connection, batch_id: str, key: str) -> dict[str, Any] | None:
    """그 배치 PREDICT_BATCH 작업 중 `key`가 있는 처음 작업의 params[key](실패만 다시 실행한 부모 params에는 없다)."""
    q = (select(jobs.c.params).where(and_(jobs.c.job_type == "PREDICT_BATCH", jobs.c.params["batch_id"].astext == batch_id,
                                         jobs.c.params.has_key(key)))  # noqa: W601 - JSONB ? 연산자
         .order_by(jobs.c.created_at, jobs.c.id).limit(1))
    r = conn.execute(q).first()
    v = (r.params or {}).get(key) if r is not None else None
    return v if isinstance(v, dict) else None


def batch_display(conn: Connection, batch_id: str) -> dict[str, Any] | None:
    """일괄 예측 배치의 표시 설정 = 처음 PREDICT_BATCH 작업 params.display."""
    return _batch_param(conn, batch_id, "display")


def batch_capture(conn: Connection, batch_id: str) -> dict[str, Any] | None:
    """일괄 예측 배치의 캡처 옵션 `{enabled, views?, video?}` = 처음 PREDICT_BATCH 작업 params.capture(D3-53). 없으면 None."""
    return _batch_param(conn, batch_id, "capture")


def artifacts_by_ids(conn: Connection, ids: Sequence[str]) -> dict[str, dict[str, Any]]:
    ids = [i for i in ids if i]
    if not ids:
        return {}
    return {r.id: row_dict(r) for r in conn.execute(select(artifacts).where(artifacts.c.id.in_(ids)))}


def set_param_set_display(conn: Connection, ps_id: str, display: dict[str, Any] | None) -> None:
    conn.execute(update(param_sets).where(param_sets.c.id == ps_id).values(display=display))
