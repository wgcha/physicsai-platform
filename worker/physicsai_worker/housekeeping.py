"""리퍼(§11.2)·알림 보관기간 정리(§13.2)."""

from __future__ import annotations

from sqlalchemy.engine import Engine

from physicsai_core.db.repositories import jobs as jobs_repo
from physicsai_core.db.repositories import notifications as notif_repo


def reap(engine: Engine) -> list[str]:
    with engine.begin() as conn:
        return jobs_repo.reap_expired(conn)


def purge_notifications(engine: Engine, retention_days: int) -> int:
    with engine.begin() as conn:
        return notif_repo.purge_older_than(conn, retention_days)
