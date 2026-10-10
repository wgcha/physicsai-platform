"""작업 lease 저장소(§11.2): claim·renew·release(CAS lease), 리퍼(T9), lease 토큰으로 지키는 step·작업 기록.

SQL·CAS 조건은 repositories/jobs.py에서 그대로 옮겼다(refactor-plan R9).
"""

from __future__ import annotations

import secrets
from datetime import timedelta
from typing import Any

from sqlalchemy import and_, func, literal_column, select, update
from sqlalchemy.engine import Connection

from ...state_machine import (
    CANCELED,
    COLLECTING,
    FAILED,
    INTERRUPTED,
    QUEUED,
    RUNNING,
    SUCCEEDED,
    TERMINAL,
    check_transition,
)
from ..tables import (
    job_queue_seq,
    job_steps,
    jobs,
    worker_slot,
)
from . import notifications as notif_repo
from .jobs import _side_effects_on_end, get_job, row_dict


class LeaseLost(RuntimeError):
    """lease 소유권 상실. 이후 그 작업에 어떤 상태 쓰기도 하지 않는다."""


def _ttl(seconds: float) -> Any:
    return func.now() + timedelta(seconds=float(seconds))


def _interrupt(conn: Connection, job: dict[str, Any]) -> None:
    """T9: lease 만료 → INTERRUPTED(WORKER_LOST). 실행 중 step FAILED, 슬롯 회수, 알림."""
    check_transition(job["state"], INTERRUPTED)
    res = conn.execute(
        update(jobs)
        .where(and_(jobs.c.id == job["id"], jobs.c.version == job["version"]))
        .values(
            state=INTERRUPTED,
            holds_slot=False,
            lease_owner_id=None,
            lease_token=None,
            lease_acquired_at=None,
            lease_expires_at=None,
            failure_code="WORKER_LOST",
            failure_message="워커 응답이 끊겨(lease 만료) 작업이 중단되었습니다",
            finished_at=func.now(),
            updated_at=func.now(),
            version=jobs.c.version + 1,
        )
    )
    if res.rowcount != 1:
        return
    conn.execute(
        update(job_steps)
        .where(and_(job_steps.c.job_id == job["id"], job_steps.c.state == "RUNNING"))
        .values(state="FAILED", failure_code="WORKER_LOST", failure_message="워커 중단", finished_at=func.now())
    )
    conn.execute(
        update(job_steps)
        .where(and_(job_steps.c.job_id == job["id"], job_steps.c.state == "PENDING"))
        .values(state="SKIPPED")
    )
    conn.execute(
        update(worker_slot)
        .where(and_(worker_slot.c.id == 1, worker_slot.c.holder_job_id == job["id"]))
        .values(holder_job_id=None, lease_owner_id=None, lease_token=None, lease_acquired_at=None, lease_expires_at=None)
    )
    _side_effects_on_end(conn, job, INTERRUPTED)
    notif_repo.notify_job(conn, job["id"], "JOB_INTERRUPTED")


def reap_expired(conn: Connection) -> list[str]:
    """리퍼: RUNNING/COLLECTING 중 lease_expires_at < now() → T9."""
    rows = conn.execute(
        select(jobs)
        .where(and_(jobs.c.state.in_([RUNNING, COLLECTING]), jobs.c.lease_expires_at < func.now()))
        .with_for_update(skip_locked=True)
    ).all()
    out = []
    for r in rows:
        _interrupt(conn, row_dict(r))
        out.append(r.id)
    # 슬롯만 남은 경우(작업은 이미 종료) 정리
    conn.execute(
        update(worker_slot)
        .where(and_(worker_slot.c.id == 1, worker_slot.c.lease_expires_at < func.now()))
        .values(holder_job_id=None, lease_owner_id=None, lease_token=None, lease_acquired_at=None, lease_expires_at=None)
    )
    if out:
        notif_repo.recompute_my_turn(conn)
    return out


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


def assert_lease(conn: Connection, job_id: str, token: str) -> dict[str, Any]:
    job = conn.execute(
        select(jobs).where(and_(jobs.c.id == job_id, jobs.c.lease_token == token)).with_for_update()
    ).first()
    if job is None:
        raise LeaseLost(job_id)
    return row_dict(job)


def release(
    conn: Connection,
    job_id: str,
    token: str,
    next_state: str,
    *,
    failure_code: str | None = None,
    failure_message: str | None = None,
    result_patch: dict[str, Any] | None = None,
    new_queue: bool = False,
) -> dict[str, Any]:
    """lease 해제 + 전이(T5·T6·T7·T8·T14·T15·T16). 알림 포함."""
    job = assert_lease(conn, job_id, token)
    tno = check_transition(job["state"], next_state)
    result = dict(job.get("result") or {})
    if result_patch:
        result.update(result_patch)
    values: dict[str, Any] = dict(
        state=next_state,
        holds_slot=False,
        lease_owner_id=None,
        lease_token=None,
        lease_acquired_at=None,
        lease_expires_at=None,
        result=result,
        updated_at=func.now(),
        version=jobs.c.version + 1,
    )
    if next_state in TERMINAL:
        values["finished_at"] = func.now()
        values["progress_label"] = None
    if next_state == SUCCEEDED:
        values["progress_pct"] = 100.0
    if failure_code:
        values["failure_code"] = failure_code
        values["failure_message"] = (failure_message or "")[:500]
    if next_state == QUEUED:
        values["queue_seq"] = job_queue_seq.next_value()
        values["queued_at"] = func.now()
        values["next_notified_at"] = None
    r = conn.execute(
        update(jobs)
        .where(and_(jobs.c.id == job_id, jobs.c.lease_token == token, jobs.c.lease_generation == job["lease_generation"]))
        .values(**values)
    )
    if r.rowcount != 1:
        raise LeaseLost(job_id)
    conn.execute(
        update(worker_slot)
        .where(and_(worker_slot.c.id == 1, worker_slot.c.lease_token == token))
        .values(holder_job_id=None, lease_owner_id=None, lease_token=None, lease_acquired_at=None, lease_expires_at=None)
    )
    if next_state in (FAILED, CANCELED):
        conn.execute(
            update(job_steps)
            .where(and_(job_steps.c.job_id == job_id, job_steps.c.state == "PENDING"))
            .values(state="SKIPPED" if next_state == FAILED else "CANCELED")
        )
        conn.execute(
            update(job_steps)
            .where(and_(job_steps.c.job_id == job_id, job_steps.c.state == "RUNNING"))
            .values(state="CANCELED" if next_state == CANCELED else "FAILED", finished_at=func.now())
        )
    job_after = {**job, "result": result}
    if next_state in TERMINAL:
        _side_effects_on_end(conn, job_after, next_state)
    if tno in ("T14", "T15"):
        notif_repo.notify_job(conn, job_id, "HPC_COLLECTED")
    event = {SUCCEEDED: "JOB_SUCCEEDED", FAILED: "JOB_FAILED", CANCELED: "JOB_CANCELED"}.get(next_state)
    if event:
        notif_repo.notify_job(conn, job_id, event)
    notif_repo.recompute_my_turn(conn)
    return get_job(conn, job_id)


def continue_running(conn: Connection, job_id: str, token: str) -> None:
    """T4(RUNNING → RUNNING): 다음 step 진행 기록."""
    job = assert_lease(conn, job_id, token)
    check_transition(job["state"], RUNNING)


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
