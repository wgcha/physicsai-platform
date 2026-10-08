"""작업 저장소: 생성, claim/renew/release(CAS lease), 전이, 리퍼, 취소, 대기열 이동(계약 §7, §11.2)."""

from __future__ import annotations

import secrets
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import and_, func, literal_column, select, text, update
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

from ...errors import DomainError
from ...job_types import JOB_TYPES
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
    curations,
    datasets,
    job_queue_seq,
    job_steps,
    jobs,
    models,
    optimizations,
    spdm_imports,
    train_does,
    worker_slot,
)
from . import notifications as notif_repo

TERMINAL_SQL = "('SUCCEEDED','FAILED','CANCELED','INTERRUPTED')"


class LeaseLost(RuntimeError):
    """lease 소유권 상실. 이후 그 작업에 어떤 상태 쓰기도 하지 않는다."""


def _ttl(seconds: float) -> Any:
    return func.now() + timedelta(seconds=float(seconds))


def row_dict(r: Any) -> dict[str, Any]:
    return dict(r._mapping) if r is not None else None  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# 생성(T1)
# ---------------------------------------------------------------------------


def insert_job(
    conn: Connection,
    *,
    study: dict[str, Any],
    job_type: str,
    params: dict[str, Any],
    user_id: str,
    user_name: str,
    result: dict[str, Any] | None = None,
    warnings: list[dict[str, str]] | None = None,
    retry_of_job_id: str | None = None,
    resume_from_step: int | None = None,
    job_id: str | None = None,
) -> dict[str, Any]:
    check_transition(None, QUEUED)
    jt = JOB_TYPES[job_type]
    job_id = job_id or str(uuid.uuid4())
    sp = conn.begin_nested()
    try:
        conn.execute(
            jobs.insert().values(
                id=job_id,
                study_id=study["id"],
                project_id=study["project_id"],
                job_type=job_type,
                stage=jt.stage,
                lane=jt.lane,
                state=QUEUED,
                holds_slot=False,
                queue_seq=job_queue_seq.next_value(),
                queued_at=func.now(),
                params=params,
                result=result,
                warnings=warnings or [],
                retry_of_job_id=retry_of_job_id,
                resume_from_step=resume_from_step,
                created_by=user_id,
                created_by_name=user_name,
            )
        )
        sp.commit()
    except IntegrityError as exc:
        sp.rollback()
        if "ux_jobs_study_type_active" in str(exc.orig):
            raise DomainError(
                "STUDY_JOB_BUSY", "이 Study에서 같은 종류의 작업이 이미 대기 중이거나 실행 중입니다", status=409
            ) from None
        raise
    for no, sd in enumerate(jt.steps, start=1):
        state = "PENDING"
        if resume_from_step is not None and no < resume_from_step:
            state = "SKIPPED"
        conn.execute(
            job_steps.insert().values(
                id=str(uuid.uuid4()),
                job_id=job_id,
                step_no=no,
                step_key=sd.key,
                kind=sd.kind,
                needs_slot=jt.needs_slot(sd),
                state=state,
                progress_label="이전 작업 산출물 재사용" if state == "SKIPPED" else None,
                log_rel=f"logs/{job_id}/step_{no:02d}_{sd.key}.log",
            )
        )
    notif_repo.recompute_my_turn(conn)
    return get_job(conn, job_id)


def get_job(conn: Connection, job_id: str, *, for_update: bool = False) -> dict[str, Any] | None:
    q = select(jobs).where(jobs.c.id == job_id)
    if for_update:
        q = q.with_for_update()
    return row_dict(conn.execute(q).first())


def get_steps(conn: Connection, job_id: str) -> list[dict[str, Any]]:
    return [row_dict(r) for r in conn.execute(select(job_steps).where(job_steps.c.job_id == job_id).order_by(job_steps.c.step_no))]


def root_job_id(conn: Connection, job: dict[str, Any]) -> str:
    """재시도 체인의 최초 작업 id(작업 폴더 이어받기, §10.5)."""
    cur = job
    seen = set()
    while cur.get("retry_of_job_id") and cur["id"] not in seen:
        seen.add(cur["id"])
        nxt = get_job(conn, cur["retry_of_job_id"])
        if nxt is None:
            break
        cur = nxt
    return cur["id"]


def queue_positions(conn: Connection, lane: str) -> dict[str, int]:
    rows = conn.execute(
        select(jobs.c.id).where(and_(jobs.c.state == QUEUED, jobs.c.lane == lane)).order_by(jobs.c.queue_seq)
    ).all()
    return {r.id: i for i, r in enumerate(rows, start=1)}


# ---------------------------------------------------------------------------
# claim / renew / release (§11.2)
# ---------------------------------------------------------------------------


def _side_effects_on_end(conn: Connection, job: dict[str, Any], state: str) -> None:
    """종료 시 관련 행 정리(데이터셋 FAILED, 평가 상태 FAILED)."""
    if state == SUCCEEDED:
        return
    res = job.get("result") or {}
    if job["job_type"] == "DATASET_CREATE" and res.get("dataset_id"):
        conn.execute(
            update(datasets)
            .where(and_(datasets.c.id == res["dataset_id"], datasets.c.status == "BUILDING"))
            .values(status="FAILED")
        )
    if job["job_type"] == "EVALUATE":
        conn.execute(
            update(models)
            .where(and_(models.c.eval_job_id == job["id"], models.c.eval_status == "RUNNING"))
            .values(eval_status="FAILED", row_version=models.c.row_version + 1)
        )
    # 2차 엔터티(phase2 §7.2): 작업 실패·취소·중단 → BUILDING/RUNNING 행 FAILED
    jt = job["job_type"]
    if jt == "TD_DOE_GEN":
        conn.execute(update(train_does).where(and_(train_does.c.job_id == job["id"], train_does.c.status == "BUILDING"))
                     .values(status="FAILED"))
    elif jt in ("CU_H3D_CURATE", "CU_T01_CURVES"):
        conn.execute(update(curations).where(and_(curations.c.job_id == job["id"], curations.c.status == "BUILDING"))
                     .values(status="FAILED"))
    elif jt == "SPDM_IMPORT":
        conn.execute(update(spdm_imports).where(and_(spdm_imports.c.job_id == job["id"], spdm_imports.c.status == "BUILDING"))
                     .values(status="FAILED"))
    elif jt == "OPTIMIZE":
        conn.execute(update(optimizations).where(and_(optimizations.c.job_id == job["id"], optimizations.c.status == "RUNNING"))
                     .values(status="FAILED"))


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
        raise _ClaimRace()
    _mark_started(conn, target.id, env_snapshot)
    if target.started_at is None:
        notif_repo.notify_job(conn, target.id, "JOB_STARTED")
    notif_repo.recompute_my_turn(conn)
    return get_job(conn, target.id)


class _ClaimRace(RuntimeError):
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
        raise _ClaimRace()
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


# ---------------------------------------------------------------------------
# step 기록
# ---------------------------------------------------------------------------


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


def is_cancel_requested(conn: Connection, job_id: str) -> bool:
    return conn.execute(select(jobs.c.cancel_requested_at).where(jobs.c.id == job_id)).scalar() is not None


# ---------------------------------------------------------------------------
# API: 취소·대기열 이동
# ---------------------------------------------------------------------------


def request_cancel(conn: Connection, job_id: str, user_id: str) -> dict[str, Any]:
    job = get_job(conn, job_id, for_update=True)
    if job is None:
        raise DomainError("NOT_FOUND", "작업을 찾을 수 없습니다", status=404)
    if job["state"] in TERMINAL:
        raise DomainError("JOB_TERMINAL", "이미 끝난 작업입니다", status=409)
    if job["state"] == QUEUED:
        check_transition(QUEUED, CANCELED)
        conn.execute(
            update(jobs)
            .where(and_(jobs.c.id == job_id, jobs.c.version == job["version"]))
            .values(
                state=CANCELED,
                queue_seq=None,
                cancel_requested_at=func.now(),
                cancel_requested_by=user_id,
                finished_at=func.now(),
                updated_at=func.now(),
                version=jobs.c.version + 1,
            )
        )
        conn.execute(
            update(job_steps).where(and_(job_steps.c.job_id == job_id, job_steps.c.state == "PENDING")).values(state="CANCELED")
        )
        _side_effects_on_end(conn, job, CANCELED)
        notif_repo.notify_job(conn, job_id, "JOB_CANCELED")
        notif_repo.recompute_my_turn(conn)
    elif job["cancel_requested_at"] is None:
        conn.execute(
            update(jobs)
            .where(jobs.c.id == job_id)
            .values(cancel_requested_at=func.now(), cancel_requested_by=user_id, updated_at=func.now(), version=jobs.c.version + 1)
        )
    return get_job(conn, job_id)


def move_in_queue(conn: Connection, job_id: str, position: int) -> None:
    """§7.3: SLOT 레인 QUEUED 전부를 잠그고 원하는 순서대로 queue_seq 재부여."""
    rows = conn.execute(
        select(jobs.c.id, jobs.c.state, jobs.c.lane)
        .where(and_(jobs.c.state == QUEUED, jobs.c.lane == "SLOT"))
        .order_by(jobs.c.queue_seq)
        .with_for_update()
    ).all()
    ids = [r.id for r in rows]
    if job_id not in ids:
        job = get_job(conn, job_id)
        if job is None:
            raise DomainError("NOT_FOUND", "작업을 찾을 수 없습니다", status=404)
        raise DomainError("JOB_NOT_QUEUED", "대기 중인 SLOT 작업만 순서를 바꿀 수 있습니다", status=409)
    ids.remove(job_id)
    pos = max(1, min(position, len(ids) + 1))
    ids.insert(pos - 1, job_id)
    for jid in ids:
        conn.execute(
            update(jobs).where(jobs.c.id == jid).values(queue_seq=job_queue_seq.next_value(), version=jobs.c.version + 1)
        )
    notif_repo.recompute_my_turn(conn)


def has_active_jobs(conn: Connection, study_id: str) -> bool:
    return (
        conn.execute(
            select(jobs.c.id).where(and_(jobs.c.study_id == study_id, jobs.c.state.not_in(list(TERMINAL)))).limit(1)
        ).first()
        is not None
    )


def model_in_use(conn: Connection, model_id: str) -> bool:
    """비종료 작업 params에 model_id가 있으면 사용 중."""
    q = select(jobs.c.id).where(
        and_(jobs.c.state.not_in(list(TERMINAL)), text("((jobs.params->>'model_id') = :mid OR (jobs.result->>'model_id') = :mid)"))
    ).limit(1)
    return conn.execute(q, {"mid": model_id}).first() is not None


__all__ = [
    "LeaseLost",
    "insert_job",
    "get_job",
    "get_steps",
    "claim_slot",
    "claim_light",
    "claim_collecting",
    "renew",
    "release",
    "reap_expired",
    "request_cancel",
    "move_in_queue",
]
