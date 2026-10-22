"""작업 lease 저장소(§11.2): claim(GPU·CPU·LIGHT·PREVIEW·COLLECTING)·renew(CAS lease).

job-queues.md: 전역 SLOT 레인을 GPU 슬롯 1개(`claim_gpu` — 기존 worker_slot 행 잠금 + generation CAS)와 CPU 슬롯 N개
(`claim_cpu` — advisory lock + 실행 수 상한)로 나눴다. `jobs.lane`은 현재 대기열이고 T17이 경계에서 바꾼다.

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


def claim_gpu(
    conn: Connection, worker_id: str, ttl_s: float, env_snapshot: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    """GPU 대기열 claim(T2). 슬롯 1개(worker_slot id=1 `FOR UPDATE` + generation CAS). 호출자가 트랜잭션을 연다(conn.begin())."""
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
    target = _pick_target(conn, "GPU")
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
    r2 = _start(conn, target, holds_slot=True, lv=lv)
    if r1.rowcount != 1 or r2.rowcount != 1:
        raise ClaimRace()
    return _after_claim(conn, target, env_snapshot)


CPU_CLAIM_LOCK = 7_317_018  # pg_advisory_xact_lock 키(CPU 대기열 claim 직렬화 — 실행 수 검사와 claim 사이 경합 차단, JQ-6)
CPU_LOCK_ENABLED = True  # 시험 전용 우회(V-JQ-4 대조군: 잠금 없이는 상한을 넘는 경합이 재현된다). 운영 코드는 바꾸지 않는다


def claim_cpu(
    conn: Connection, worker_id: str, ttl_s: float, max_concurrent: int, env_snapshot: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    """CPU 대기열 claim(T2): 실행 중 CPU 작업 < max_concurrent일 때 최소 queue_seq. 슬롯 행 없음(holds_slot=false) — 개수는 RUNNING 행 수.
    메모리 문(`cpu.min_free_memory_gb`)은 워커가 호출 전에 검사한다. 호출자가 트랜잭션을 연다."""
    if CPU_LOCK_ENABLED:
        conn.execute(select(func.pg_advisory_xact_lock(CPU_CLAIM_LOCK)))
    running = conn.execute(
        select(func.count()).select_from(jobs).where(and_(jobs.c.state == RUNNING, jobs.c.lane == "CPU"))
    ).scalar() or 0
    if running >= max(1, int(max_concurrent)):
        return None
    target = _pick_target(conn, "CPU")
    if target is None:
        return None
    check_transition(QUEUED, RUNNING)
    lv = _lease_values(worker_id, secrets.token_urlsafe(32), int(target.lease_generation) + 1, ttl_s)
    r = _start(conn, target, holds_slot=False, lv=lv)
    if r.rowcount != 1:
        raise ClaimRace()
    return _after_claim(conn, target, env_snapshot)


def claim_next_slot(
    conn: Connection, worker_id: str, ttl_s: float, cpu_limit: int, env_snapshot: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    """시험·개발용: GPU·CPU 대기열 중 가장 앞선(queue_seq 최소) 작업부터 claim — 앞 대기열이 막혔으면(GPU 슬롯 사용 중·CPU 상한) 다음.
    운영 워커는 gpu-slot·cpu-slot 스레드가 `claim_gpu`·`claim_cpu`를 따로 부른다."""
    heads = conn.execute(
        select(jobs.c.lane, func.min(jobs.c.queue_seq).label("seq"))
        .where(and_(jobs.c.state == QUEUED, jobs.c.lane.in_(["CPU", "GPU"]), jobs.c.cancel_requested_at.is_(None)))
        .group_by(jobs.c.lane)
        .order_by(func.min(jobs.c.queue_seq))
    ).all()
    for h in heads:
        job = claim_gpu(conn, worker_id, ttl_s, env_snapshot) if h.lane == "GPU" else claim_cpu(conn, worker_id, ttl_s, cpu_limit, env_snapshot)
        if job is not None:
            return job
    return None


def _pick_target(conn: Connection, lane: str) -> Any:
    return conn.execute(
        select(jobs.c.id, jobs.c.version, jobs.c.started_at, jobs.c.lease_generation)
        .where(and_(jobs.c.state == QUEUED, jobs.c.lane == lane, jobs.c.cancel_requested_at.is_(None)))
        .order_by(jobs.c.queue_seq)
        .limit(1)
        .with_for_update(skip_locked=True)
    ).first()


def _start(conn: Connection, target: Any, *, holds_slot: bool, lv: dict[str, Any]) -> Any:
    return conn.execute(
        update(jobs)
        .where(and_(jobs.c.id == target.id, jobs.c.state == QUEUED, jobs.c.version == target.version))
        .values(
            state=RUNNING,
            holds_slot=holds_slot,
            queue_seq=None,
            started_at=func.coalesce(jobs.c.started_at, func.now()),
            updated_at=func.now(),
            version=jobs.c.version + 1,
            **lv,
        )
    )


def _after_claim(conn: Connection, target: Any, env_snapshot: dict[str, Any] | None) -> dict[str, Any] | None:
    _mark_started(conn, target.id, env_snapshot)
    if target.started_at is None:  # JQ-14: 첫 시작 전만 — T17 재진입은 알림 없음
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


PREVIEW_CLAIM_LOCK = 7_317_017  # pg_advisory_xact_lock 키(PREVIEW 레인 claim 직렬화 — 동시 수 검사와 claim 사이 경합 차단)


def claim_preview(
    conn: Connection, worker_id: str, ttl_s: float, max_concurrent: int, env_snapshot: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    """PREVIEW 레인 claim(geometry-view.md §6.2): 실행 중 PREVIEW < max_concurrent일 때 최소 queue_seq. 전역 worker_slot 미사용,
    lease 규칙은 LIGHT와 같다(holds_slot=false). DOE·일괄 예측이 슬롯을 쥐고 있어도 실행한다."""
    conn.execute(select(func.pg_advisory_xact_lock(PREVIEW_CLAIM_LOCK)))
    running = conn.execute(
        select(func.count()).select_from(jobs).where(and_(jobs.c.state == RUNNING, jobs.c.lane == "PREVIEW"))
    ).scalar() or 0
    if running >= max(1, int(max_concurrent)):
        return None
    target = conn.execute(
        select(jobs.c.id, jobs.c.version, jobs.c.started_at, jobs.c.lease_generation)
        .where(and_(jobs.c.state == QUEUED, jobs.c.lane == "PREVIEW", jobs.c.cancel_requested_at.is_(None)))
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
        .values(state=RUNNING, holds_slot=False, queue_seq=None, started_at=func.coalesce(jobs.c.started_at, func.now()),
                updated_at=func.now(), version=jobs.c.version + 1, **lv)
    )
    if r.rowcount != 1:
        raise ClaimRace()
    _mark_started(conn, target.id, env_snapshot)  # 알림 없음(notify_success=False·미리보기는 화면이 폴링)
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


