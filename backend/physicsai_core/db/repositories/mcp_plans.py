"""확인 계획 저장소(mcp.md §5.2): confirm_token은 해시만, (토큰·종류·Study·params 해시)에 결합, 1회용."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.engine import Connection

from ..tables import mcp_plans
from .jobs import row_dict


def insert(conn: Connection, **values: Any) -> None:
    conn.execute(mcp_plans.insert().values(**values))


def get_by_confirm_hash(conn: Connection, confirm_hash: str, *, for_update: bool = False) -> dict[str, Any] | None:
    q = select(mcp_plans).where(mcp_plans.c.confirm_hash == confirm_hash)
    if for_update:
        q = q.with_for_update()
    return row_dict(conn.execute(q).first())


def get(conn: Connection, plan_id: str) -> dict[str, Any] | None:
    return row_dict(conn.execute(select(mcp_plans).where(mcp_plans.c.id == plan_id)).first())


def claim(conn: Connection, plan_id: str, now: datetime) -> bool:
    """사용 표시를 원자적으로(동시 run_job 두 번 → 하나만 True)."""
    r = conn.execute(update(mcp_plans).where(mcp_plans.c.id == plan_id, mcp_plans.c.used_at.is_(None))
                     .values(used_at=now).returning(mcp_plans.c.id)).first()
    return r is not None


def release(conn: Connection, plan_id: str) -> None:
    """생성이 실패하면 사용 표시를 되돌린다(작업이 만들어지지 않은 확인 토큰은 다시 쓸 수 있게)."""
    conn.execute(update(mcp_plans).where(mcp_plans.c.id == plan_id, mcp_plans.c.used_job_id.is_(None))
                 .values(used_at=None))


def set_job(conn: Connection, plan_id: str, job_id: str | None) -> None:
    conn.execute(update(mcp_plans).where(mcp_plans.c.id == plan_id).values(used_job_id=job_id))


def purge_expired(conn: Connection, before: datetime) -> int:
    """만료 후 하루 지난 계획 삭제(§6.2 — 호출부가 before = now - 1일)."""
    return int(conn.execute(delete(mcp_plans).where(mcp_plans.c.expires_at < before)).rowcount or 0)
