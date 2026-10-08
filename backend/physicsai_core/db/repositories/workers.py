"""워커 하트비트(§6.10)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection

from ..tables import worker_heartbeats
from .jobs import row_dict


def upsert(conn: Connection, *, worker_id: str, host: str, pid: int, app_version: str, limiter: str,
           effective_limits: dict[str, Any] | None = None, resources: dict[str, Any] | None = None) -> None:
    values = dict(worker_id=worker_id, host=host, pid=pid, app_version=app_version, limiter=limiter,
                  effective_limits=effective_limits, last_seen_at=func.now())
    if resources is not None:
        values["resources"] = resources
    stmt = pg_insert(worker_heartbeats).values(**values)
    upd = {k: stmt.excluded[k] for k in values if k != "worker_id"}
    conn.execute(stmt.on_conflict_do_update(index_elements=["worker_id"], set_=upd))


def latest(conn: Connection) -> dict[str, Any] | None:
    q = select(
        worker_heartbeats,
        (func.extract("epoch", func.now() - worker_heartbeats.c.last_seen_at)).label("age_s"),
    ).order_by(worker_heartbeats.c.last_seen_at.desc()).limit(1)
    return row_dict(conn.execute(q).first())
