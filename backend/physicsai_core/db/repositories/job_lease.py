"""작업 lease 저장소(§11.2): claim(SLOT·LIGHT·COLLECTING)·renew(CAS lease).

SQL·CAS 조건은 repositories/jobs.py에서 그대로 옮겼다(refactor-plan R9). 300줄 분할(R12)로 종료 전이·리퍼는
`job_lease_end.py`, lease 토큰으로 지키는 기록은 `lease_guard.py`로 나눴고, 기존 이름은 여기서 재노출한다
(`job_lease.release`·`job_lease.LeaseLost` 등 import 경로 불변).
"""

from __future__ import annotations

import secrets
from datetime import timedelta
from typing import Any

from sqlalchemy import and_, func, literal_column, select, update
from sqlalchemy.engine import Connection

from ...state_machine import (
    COLLECTING,
    QUEUED,
    RUNNING,
    check_transition,
)
from ..tables import (
    jobs,
    worker_slot,
)
from . import notifications as notif_repo
from .jobs import get_job
from .job_lease_end import _interrupt, continue_running, reap_expired, release  # noqa: F401 - 기존 경로 재노출
from .lease_guard import (  # noqa: F401 - 기존 경로 재노출(lease_repo.step_update 등)
    LeaseLost,
    _lease_guard,
    add_warning,
    assert_lease,
    job_update,
    patch_result,
    step_update,
)


def _ttl(seconds: float) -> Any:
    return func.now() + timedelta(seconds=float(seconds))


def _lease_values(worker_id: str, token: str, gen: int, ttl_s: float) -> dict[str, Any]:
    return dict(
        lease_owner_id=worker_id,
        lease_token=token,
        lease_generation=gen,
        lease_acquired_at=func.now(),
        lease_expires_at=_ttl(ttl_s),
    )


def _mark_started(conn: Connection, job_id: str, env_snapshot: dict[str, Any] | None) -> None:
    if env_snapshot is not None:
        conn.execute(
            update(jobs).where(and_(jobs.c.id == job_id, jobs.c.env_snapshot.is_(None))).values(env_snapshot=env_snapshot)
        )


def claim_slot(
    conn: Connection, worker_id: str, ttl_s: float, env_snapshot: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    """SLOT 레인 claim(T2). 호출자가 트랜잭션을 연다(conn.begin())."""
    slot = conn.execute(select(worker_slot).where(worker_slot.c.id == 1).with_for_update()).one()
    if slot.lease_token is not None:
        alive = conn.execute(select(literal_column("1")).where(slot.lease_expires_at > func.now())).first()
        if alive:
            return None
        if slot.holder_job_id:
            holder = get_job(conn, slot.holder_job_id, for_update=True)
            if holder and holder["state"] in (RUNNING, COLLECTING) and holder["lease_token"] == slot.lease_token:
                _interrupt(conn, holder)
        conn.execute(
            update(worker_slot)
            .where(worker_slot.c.id == 1)
            .values(holder_job_id=None, lease_owner_id=None, lease_token=None, lease_acquired_at=None, lease_expires_at=None)
        )
    target = conn.execute(
        select(jobs.c.id, jobs.c.version, jobs.c.started_at)
        .where(and_(jobs.c.state == QUEUED, jobs.c.lane == "SLOT", jobs.c.cancel_requested_at.is_(None)))
        .order_by(jobs.c.queue_seq)
        .limit(1)
        .with_for_update(skip_locked=True)
    ).first()
    if target is None:
        return None
    check_transition(QUEUED, RUNNING)
    token = secrets.token_urlsafe(32)
    gen = int(slot.lease_generation) + 1
    lv = _lease_values(worker_id, token, gen, ttl_s)
    r1 = conn.execute(
        update(worker_slot)
        .where(and_(worker_slot.c.id == 1, worker_slot.c.lease_generation == slot.lease_generation))
        .values(holder_job_id=target.id, **lv)
    )
    r2 = conn.execute(
        update(jobs)
        .where(and_(jobs.c.id == target.id, jobs.c.state == QUEUED, jobs.c.version == target.version))
        .values(
            state=RUNNING,
            holds_slot=True,
            queue_seq=None,
            started_at=func.coalesce(jobs.c.started_at, func.now()),
            updated_at=func.now(),
            version=jobs.c.version + 1,
            **lv,
        )
    )
    if r1.rowcount != 1 or r2.rowcount != 1:
        raise ClaimRace()
    _mark_started(conn, target.id, env_snapshot)
    if target.started_at is None:
        notif_repo.notify_job(conn, target.id, "JOB_STARTED")
    notif_repo.recompute_my_turn(conn)
    return get_job(conn, target.id)


class ClaimRace(RuntimeError):
    pass


def claim_light(
    conn: Connection, worker_id: str, ttl_s: float, env_snapshot: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    busy = conn.execute(
        select(jobs.c.id).where(and_(jobs.c.state == RUNNING, jobs.c.lane == "LIGHT")).limit(1)
    ).first()
    if busy:
        return None
    target = conn.execute(
        select(jobs.c.id, jobs.c.version, jobs.c.started_at, jobs.c.lease_generation)
        .where(and_(jobs.c.state == QUEUED, jobs.c.lane == "LIGHT", jobs.c.cancel_requested_at.is_(None)))
        .order_by(jobs.c.queue_seq)
        .limit(1)
        .with_for_update(skip_locked=True)
    ).first()
    if target is None:
        return None
    check_transition(QUEUED, RUNNING)
    token = secrets.token_urlsafe(32)
    lv = _lease_values(worker_id, token, int(target.lease_generation) + 1, ttl_s)
    r = conn.execute(
        update(jobs)
        .where(and_(jobs.c.id == target.id, jobs.c.state == QUEUED, jobs.c.version == target.version))
        .values(
            state=RUNNING,
            holds_slot=False,
            queue_seq=None,
            started_at=func.coalesce(jobs.c.started_at, func.now()),
            updated_at=func.now(),
            version=jobs.c.version + 1,
            **lv,
        )
    )
    if r.rowcount != 1:
        raise ClaimRace()
    _mark_started(conn, target.id, env_snapshot)
    if target.started_at is None:
        notif_repo.notify_job(conn, target.id, "JOB_STARTED")
    return get_job(conn, target.id)


def claim_collecting(conn: Connection, worker_id: str, ttl_s: float) -> dict[str, Any] | None:
    """회수기: lease 없는 COLLECTING 작업에 lease 부여."""
    target = conn.execute(
        select(jobs.c.id, jobs.c.version, jobs.c.lease_generation)
        .where(and_(jobs.c.state == COLLECTING, jobs.c.lease_token.is_(None)))
        .order_by(jobs.c.updated_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    ).first()
    if target is None:
        return None
    token = secrets.token_urlsafe(32)
    lv = _lease_values(worker_id, token, int(target.lease_generation) + 1, ttl_s)
    conn.execute(
        update(jobs)
        .where(and_(jobs.c.id == target.id, jobs.c.version == target.version))
        .values(updated_at=func.now(), version=jobs.c.version + 1, **lv)
    )
    return get_job(conn, target.id)


def renew(conn: Connection, job_id: str, token: str, ttl_s: float, *, slot: bool) -> bool:
    r = conn.execute(
        update(jobs)
        .where(and_(jobs.c.id == job_id, jobs.c.lease_token == token, jobs.c.lease_expires_at > func.now()))
        .values(lease_expires_at=_ttl(ttl_s))
    )
    if r.rowcount != 1:
        return False
    if slot:
        r2 = conn.execute(
            update(worker_slot)
            .where(and_(worker_slot.c.id == 1, worker_slot.c.lease_token == token, worker_slot.c.lease_expires_at > func.now()))
            .values(lease_expires_at=_ttl(ttl_s))
        )
        if r2.rowcount != 1:
            return False
    return True


