"""lease 종료 전이(§11.2): `release`(T5~T8·T14~T16), `continue_running`(T4), 리퍼 `reap_expired`·`_interrupt`(T9)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, func, select, update
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
from .job_end import _side_effects_on_end
from .jobs import get_job, row_dict
from .lease_guard import LeaseLost, assert_lease


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
    next_lane: str | None = None,
) -> dict[str, Any]:
    """lease 해제 + 전이(T5·T6·T7·T8·T14·T15·T16·T17). 알림 포함.

    next_state=QUEUED: RUNNING에서 오면 T17(step 경계 구간 전환 — lane = next_lane, 순번 = queue_origin_seq로 원래 자리, 알림 없음),
    COLLECTING에서 오면 T14(PBS 회수 후 — 2026-10-07 결정대로 맨 뒤: 새 순번을 queue_seq·queue_origin_seq 모두에 부여, lane = next_lane)."""
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
        values["queued_at"] = func.now()
        # 대기 중 화면(current_step_label)은 "다음에 실행할 step"을 보인다(재진입 행 '이어서 · 40% · <단계>')
        nxt = conn.execute(
            select(func.min(job_steps.c.step_no)).where(and_(job_steps.c.job_id == job_id, job_steps.c.state == "PENDING"))
        ).scalar()
        if nxt is not None:
            values["current_step_no"] = nxt
        if next_lane is not None:
            values["lane"] = next_lane
        if tno == "T17":  # 원래 등록 순번으로 재진입(JQ-5). 옛 진행 중 작업(origin NULL)은 새 순번
            origin = job.get("queue_origin_seq")
            if origin is None:
                origin = conn.execute(select(job_queue_seq.next_value())).scalar_one()
            values["queue_seq"] = values["queue_origin_seq"] = origin
        else:  # T14: 맨 뒤 + 이후 재진입에도 그 자리를 유지
            seq = conn.execute(select(job_queue_seq.next_value())).scalar_one()
            values["queue_seq"] = seq
            values["queue_origin_seq"] = seq
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
