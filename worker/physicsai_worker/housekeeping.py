"""리퍼(§11.2)·알림 보관기간 정리(§13.2)."""

from __future__ import annotations

from sqlalchemy.engine import Engine

from physicsai_core.db.repositories import env_checks as env_repo
from physicsai_core.db.repositories import jobs as jobs_repo
from physicsai_core.db.repositories import notifications as notif_repo


def reap(engine: Engine) -> list[str]:
    with engine.begin() as conn:
        out = jobs_repo.reap_expired(conn)
    expire_env_checks(engine)
    return out


def expire_env_checks(engine: Engine) -> list[str]:
    """환경 점검 만료(phase2 §9.4): PENDING·RUNNING 이고 expires_at < now() → EXPIRED + ENV_CHECK_DONE 알림."""
    with engine.begin() as conn:
        return env_repo.expire_due(conn)


def purge_notifications(engine: Engine, retention_days: int) -> int:
    with engine.begin() as conn:
        return notif_repo.purge_older_than(conn, retention_days)
