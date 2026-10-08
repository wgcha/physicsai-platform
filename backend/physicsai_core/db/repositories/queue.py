"""대기열 조회(§10.2 GET /queue)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import Connection

from ..tables import jobs, studies, worker_slot
from .jobs import row_dict


def slot_row(conn: Connection) -> dict[str, Any]:
    return row_dict(conn.execute(select(worker_slot).where(worker_slot.c.id == 1)).one())


def active_jobs(conn: Connection) -> list[dict[str, Any]]:
    q = (
        select(jobs, studies.c.title.label("study_title"))
        .select_from(jobs.join(studies, studies.c.id == jobs.c.study_id))
        .where(jobs.c.state.in_(["QUEUED", "RUNNING", "WAITING_HPC", "COLLECTING"]))
        .order_by(jobs.c.queue_seq.nulls_first(), jobs.c.created_at)
    )
    return [row_dict(r) for r in conn.execute(q)]
