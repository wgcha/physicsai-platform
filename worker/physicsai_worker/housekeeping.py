"""리퍼(§11.2)·알림 보관기간 정리(§13.2)·scx 제출 중단 행 정리(phase3 §16.6)."""

from __future__ import annotations

import logging

from sqlalchemy.engine import Engine

from physicsai_core.db.repositories import env_checks as env_repo
from physicsai_core.db.repositories import hpc as hpc_repo
from physicsai_core.db.repositories import job_lease as lease_repo
from physicsai_core.db.repositories import notifications as notif_repo

log = logging.getLogger("physicsai_worker")


def reap(engine: Engine) -> list[str]:
    with engine.begin() as conn:
        out = lease_repo.reap_expired(conn)
    expire_env_checks(engine)
    scx_submitting_orphans(engine)
    return out


def scx_submitting_orphans(engine: Engine) -> dict[str, list[str]]:
    """워커 중단 후 남은 scx SUBMITTING 행 → UNKNOWN + submission_unknown(제출 중이었음) 또는 FAILED(업로드 중이었음)."""
    with engine.begin() as conn:
        out = hpc_repo.submitting_orphans_to_unknown(conn)
    if out["unknown"]:
        log.warning("워커 중단으로 SCX 제출 결과를 모르는 행 %d개 — 사용자 확인 필요", len(out["unknown"]))
    return out


def expire_env_checks(engine: Engine) -> list[str]:
    """환경 점검 만료(phase2 §9.4): PENDING·RUNNING 이고 expires_at < now() → EXPIRED + ENV_CHECK_DONE 알림."""
    with engine.begin() as conn:
        return env_repo.expire_due(conn)


def purge_notifications(engine: Engine, retention_days: int) -> int:
    with engine.begin() as conn:
        return notif_repo.purge_older_than(conn, retention_days)
