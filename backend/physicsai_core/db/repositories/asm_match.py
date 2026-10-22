"""조립 매칭 작업 조회(asm-match.md §6.3, AM-12 — DB 변경 없음): 매칭 묶음 → Study·작업은 `jobs`(job_type ASM_MATCH)에서 찾는다.

`jobs.params.match_id`가 묶음 id. 묶음 상태·행은 파일(`match.json`)에 있고, 이 저장소는 작업 행만 읽는다.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import Connection

from ...state_machine import ACTIVE
from ..tables import jobs, studies

JOB_TYPE = "ASM_MATCH"


def jobs_of(conn: Connection, match_id: str, limit: int = 20) -> list[dict[str, Any]]:
    """묶음의 ASM_MATCH 작업(최신순)."""
    q = (select(jobs).where(jobs.c.job_type == JOB_TYPE, jobs.c.params["match_id"].astext == match_id)
         .order_by(jobs.c.created_at.desc(), jobs.c.id).limit(limit))
    return [dict(r._mapping) for r in conn.execute(q)]


def study_of(conn: Connection, match_id: str) -> dict[str, Any] | None:
    """묶음이 속한 Study(첫 작업 기준). 없으면 None."""
    q = (select(studies).select_from(jobs.join(studies, studies.c.id == jobs.c.study_id))
         .where(jobs.c.job_type == JOB_TYPE, jobs.c.params["match_id"].astext == match_id).limit(1))
    r = conn.execute(q).first()
    return dict(r._mapping) if r is not None else None


def active_of(conn: Connection, study_id: str) -> dict[str, Any] | None:
    """Study의 대기·실행 중 ASM_MATCH 작업(Study당 1개만 — ux_jobs_study_type_active)."""
    q = select(jobs).where(jobs.c.study_id == study_id, jobs.c.job_type == JOB_TYPE, jobs.c.state.in_(sorted(ACTIVE))).limit(1)
    r = conn.execute(q).first()
    return dict(r._mapping) if r is not None else None
