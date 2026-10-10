"""작업 저장소: 생성, 조회, 종료 부수효과, 취소, 대기열 이동(계약 §7). lease(claim/renew/release·리퍼)는 job_lease.py."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import and_, func, select, text, update
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

from ...errors import DomainError
from ...job_types import JOB_TYPES
from ...state_machine import (
    CANCELED,
    QUEUED,
    SUCCEEDED,
    TERMINAL,
    check_transition,
)
from ..tables import (
    datasets,
    job_queue_seq,
    job_steps,
    jobs,
    models,
    studies,
)
from . import notifications as notif_repo


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


def list_with_study_title(conn: Connection, *, study_id: str | None, states: list[str] | None, created_by: str | None,
                          job_type: str | None, limit: int, offset: int) -> list[dict[str, Any]]:
    """작업 목록(§10.2) + study_title. 최신순, limit·offset 그대로."""
    q = select(jobs, studies.c.title.label("study_title")).select_from(jobs.join(studies, studies.c.id == jobs.c.study_id))
    if study_id:
        q = q.where(jobs.c.study_id == study_id)
    if states:
        q = q.where(jobs.c.state.in_(states))
    if created_by:
        q = q.where(jobs.c.created_by == created_by)
    if job_type:
        q = q.where(jobs.c.job_type == job_type)
    q = q.order_by(jobs.c.created_at.desc(), jobs.c.id).limit(limit).offset(offset)
    return [dict(r._mapping) for r in conn.execute(q)]


def succeeded_predicts(conn: Connection, study_id: str, limit: int = 50) -> list[Any]:
    """같은 Study의 SUCCEEDED PREDICT 작업(최근 종료 순)."""
    return conn.execute(
        select(jobs).where(and_(jobs.c.study_id == study_id, jobs.c.job_type == "PREDICT", jobs.c.state == "SUCCEEDED"))
        .order_by(jobs.c.finished_at.desc().nulls_last(), jobs.c.created_at.desc()).limit(limit)
    ).mappings().all()


def latest_by_stage(conn: Connection, study_id: str, stage: int) -> dict[str, Any] | None:
    """단계(jobs.stage)별 가장 최근 작업의 id·job_type·state·created_at."""
    return row_dict(conn.execute(
        select(jobs.c.id, jobs.c.job_type, jobs.c.state, jobs.c.created_at)
        .where(and_(jobs.c.study_id == study_id, jobs.c.stage == stage))
        .order_by(jobs.c.created_at.desc())
        .limit(1)
    ).first())


# ---------------------------------------------------------------------------
# 종료 부수효과(lease 해제·리퍼·취소 공용). claim/renew/release는 job_lease.py
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
    # 엔터티 저장소가 이 모듈의 row_dict를 import하므로 지연 import(순환 회피)
    from . import curations as cur_repo
    from . import optimizations as opt_repo
    from . import spdm_imports as imp_repo
    from . import train as train_repo

    jt = job["job_type"]
    if jt == "TD_DOE_GEN":
        train_repo.fail_building_doe(conn, job["id"])
    elif jt in ("CU_H3D_CURATE", "CU_T01_CURVES"):
        cur_repo.fail_building_curation(conn, job["id"])
    elif jt == "SPDM_IMPORT":
        imp_repo.fail_building_import(conn, job["id"])
    elif jt == "OPTIMIZE":
        opt_repo.fail_running_opt(conn, job["id"])


# ---------------------------------------------------------------------------
# 취소 확인(step 기록은 job_lease.py)
# ---------------------------------------------------------------------------


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
    "insert_job",
    "get_job",
    "get_steps",
    "request_cancel",
    "move_in_queue",
]
