"""lease 토큰으로 지키는 작업 기록(§11.2): `LeaseLost`, `assert_lease`, step·작업 갱신, 결과 패치·경고 추가."""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, func, select, update
from sqlalchemy.engine import Connection

from ..tables import (
    job_steps,
    jobs,
)
from .jobs import row_dict


class LeaseLost(RuntimeError):
    """lease 소유권 상실. 이후 그 작업에 어떤 상태 쓰기도 하지 않는다."""


def assert_lease(conn: Connection, job_id: str, token: str) -> dict[str, Any]:
    job = conn.execute(
        select(jobs).where(and_(jobs.c.id == job_id, jobs.c.lease_token == token)).with_for_update()
    ).first()
    if job is None:
        raise LeaseLost(job_id)
    return row_dict(job)


def _lease_guard(job_id: str, token: str) -> Any:
    return select(jobs.c.id).where(and_(jobs.c.id == job_id, jobs.c.lease_token == token)).exists()


def step_update(conn: Connection, job_id: str, token: str, step_no: int, **values: Any) -> None:
    r = conn.execute(
        update(job_steps)
        .where(and_(job_steps.c.job_id == job_id, job_steps.c.step_no == step_no, _lease_guard(job_id, token)))
        .values(**values)
    )
    if r.rowcount != 1:
        raise LeaseLost(job_id)


def job_update(conn: Connection, job_id: str, token: str, **values: Any) -> None:
    r = conn.execute(
        update(jobs).where(and_(jobs.c.id == job_id, jobs.c.lease_token == token)).values(updated_at=func.now(), **values)
    )
    if r.rowcount != 1:
        raise LeaseLost(job_id)


def patch_result(conn: Connection, job_id: str, token: str, patch: dict[str, Any]) -> dict[str, Any]:
    job = assert_lease(conn, job_id, token)
    result = dict(job.get("result") or {})
    result.update(patch)
    job_update(conn, job_id, token, result=result)
    return result


def add_warning(conn: Connection, job_id: str, token: str, code: str, message: str) -> None:
    job = assert_lease(conn, job_id, token)
    w = list(job.get("warnings") or [])
    w.append({"code": code, "message": message[:500]})
    job_update(conn, job_id, token, warnings=w)
