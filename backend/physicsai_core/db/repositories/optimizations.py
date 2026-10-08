"""⑤ 최적화 저장소(phase2 §5.6)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, select, update
from sqlalchemy.engine import Connection

from ..tables import optimizations
from .jobs import row_dict

# ---- optimizations --------------------------------------------------------------


def insert_opt(conn: Connection, values: dict[str, Any]) -> None:
    conn.execute(optimizations.insert().values(**values))


def get_opt(conn: Connection, oid: str) -> dict[str, Any] | None:
    return row_dict(conn.execute(select(optimizations).where(optimizations.c.id == oid)).first())


def opt_for_job(conn: Connection, job_id: str) -> dict[str, Any] | None:
    return row_dict(conn.execute(select(optimizations).where(optimizations.c.job_id == job_id)).first())


def list_opts(conn: Connection, study_id: str) -> list[dict[str, Any]]:
    q = select(optimizations).where(optimizations.c.study_id == study_id).order_by(optimizations.c.created_at.desc(), optimizations.c.id)
    return [row_dict(r) for r in conn.execute(q)]


def set_opt(conn: Connection, oid: str, **values: Any) -> None:
    conn.execute(update(optimizations).where(optimizations.c.id == oid).values(**values))


def fail_running_opt(conn: Connection, job_id: str) -> None:
    conn.execute(update(optimizations).where(and_(optimizations.c.job_id == job_id, optimizations.c.status == "RUNNING")).values(status="FAILED"))
