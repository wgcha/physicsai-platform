"""② 큐레이션 저장소(phase2 §5.4)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, select, text, update
from sqlalchemy.engine import Connection

from ..tables import curations, datasets, jobs
from .jobs import row_dict

# ---- curations ------------------------------------------------------------------


def insert_curation(conn: Connection, values: dict[str, Any]) -> None:
    conn.execute(curations.insert().values(**values))


def get_curation(conn: Connection, cid: str) -> dict[str, Any] | None:
    return row_dict(conn.execute(select(curations).where(curations.c.id == cid)).first())


def list_curations(conn: Connection, study_id: str, kind: str | None = None) -> list[dict[str, Any]]:
    q = select(curations).where(curations.c.study_id == study_id)
    if kind:
        q = q.where(curations.c.kind == kind)
    return [row_dict(r) for r in conn.execute(q.order_by(curations.c.created_at.desc(), curations.c.id))]


def set_curation(conn: Connection, cid: str, **values: Any) -> None:
    conn.execute(update(curations).where(curations.c.id == cid).values(**values))


def set_building_job(conn: Connection, cid: str, job_id: str) -> None:
    """재시도: 큐레이션 행을 새 작업으로 다시 BUILDING."""
    conn.execute(update(curations).where(curations.c.id == cid).values(status="BUILDING", job_id=job_id))


def fail_building_curation(conn: Connection, job_id: str) -> None:
    conn.execute(update(curations).where(and_(curations.c.job_id == job_id, curations.c.status == "BUILDING")).values(status="FAILED"))


def datasets_using_curation(conn: Connection, cid: str) -> list[str]:
    """③-1 DATASET_CREATE params.curation_id로 만든 데이터셋 id(phase2 §12.6 used_by_dataset_ids)."""
    q = (
        select(datasets.c.id)
        .select_from(datasets.join(jobs, jobs.c.id == datasets.c.job_id))
        .where(text("(jobs.params->>'curation_id') = :cid"))
        .order_by(datasets.c.created_at)
    )
    return [r.id for r in conn.execute(q, {"cid": cid})]


def curation_id_for_dataset(conn: Connection, job_id: str | None) -> str | None:
    if not job_id:
        return None
    v = conn.execute(select(jobs.c.params).where(jobs.c.id == job_id)).scalar()
    return (v or {}).get("curation_id")
