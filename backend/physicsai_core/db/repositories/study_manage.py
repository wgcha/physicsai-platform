"""Study 관리(stage 0) 조회 저장소(phase3 §5): 스캔·정리 작업 조회, 낡음 판정 입력, 분류용 DB 행."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.engine import Connection

from ...state_machine import TERMINAL
from ...study_storage.classify import StudyRefs
from ..tables import curations, datasets, jobs, models, studies
from .jobs import row_dict

_TERMINAL = list(TERMINAL)


def latest_succeeded(conn: Connection, study_id: str, job_type: str) -> dict[str, Any] | None:
    """가장 최근(종료 시각 순) SUCCEEDED 작업."""
    return row_dict(conn.execute(
        select(jobs).where(and_(jobs.c.study_id == study_id, jobs.c.job_type == job_type, jobs.c.state == "SUCCEEDED"))
        .order_by(jobs.c.finished_at.desc().nulls_last(), jobs.c.created_at.desc()).limit(1)
    ).first())


def latest_finished(conn: Connection, study_id: str, job_type: str) -> dict[str, Any] | None:
    """가장 최근 종료 작업(상태 무관)."""
    return row_dict(conn.execute(
        select(jobs).where(and_(jobs.c.study_id == study_id, jobs.c.job_type == job_type, jobs.c.state.in_(_TERMINAL)))
        .order_by(jobs.c.finished_at.desc().nulls_last(), jobs.c.created_at.desc()).limit(1)
    ).first())


def active_of_type(conn: Connection, study_id: str, job_type: str) -> str | None:
    """비종료 작업 id(Study당 유형별 1개, ux_jobs_study_type_active)."""
    return conn.execute(
        select(jobs.c.id).where(and_(jobs.c.study_id == study_id, jobs.c.job_type == job_type,
                                     jobs.c.state.not_in(_TERMINAL))).limit(1)
    ).scalar()


def has_active_of_type(conn: Connection, study_id: str, job_type: str) -> bool:
    return active_of_type(conn, study_id, job_type) is not None


def has_active_except(conn: Connection, study_id: str, exclude_job_id: str | None = None) -> bool:
    """비종료 작업이 있는지(exclude_job_id 제외)."""
    q = select(jobs.c.id).where(and_(jobs.c.study_id == study_id, jobs.c.state.not_in(_TERMINAL)))
    if exclude_job_id:
        q = q.where(jobs.c.id != exclude_job_id)
    return conn.execute(q.limit(1)).first() is not None


def finished_after(conn: Connection, study_id: str, ts: datetime, exclude_types: tuple[str, ...]) -> int:
    """ts 이후 종료된 작업 수(exclude_types 제외)."""
    return int(conn.execute(
        select(func.count()).select_from(jobs).where(and_(
            jobs.c.study_id == study_id, jobs.c.state.in_(_TERMINAL), jobs.c.finished_at > ts,
            jobs.c.job_type.not_in(list(exclude_types)),
        ))
    ).scalar_one())


def study_refs(conn: Connection, study_id: str) -> StudyRefs:
    """분류(§5.5)에 필요한 행. 파일 본문 없음."""
    js = [dict(r._mapping) for r in conn.execute(
        select(jobs.c.id, jobs.c.job_type, jobs.c.state, jobs.c.created_at, jobs.c.finished_at, jobs.c.retry_of_job_id,
               jobs.c.params).where(jobs.c.study_id == study_id)
    )]
    ds = [dict(r._mapping) for r in conn.execute(
        select(datasets.c.id, datasets.c.package_rel, datasets.c.job_id).where(datasets.c.study_id == study_id))]
    params_of = {j["id"]: j["params"] or {} for j in js}
    counts: dict[str, int] = {}
    for d in ds:
        cid = params_of.get(d["job_id"] or "", {}).get("curation_id")
        if cid:
            counts[cid] = counts.get(cid, 0) + 1
    cs = [dict(r._mapping) for r in conn.execute(
        select(curations.c.id, curations.c.kind, curations.c.status, curations.c.output_rel)
        .where(curations.c.study_id == study_id))]
    ms = [dict(r._mapping) for r in conn.execute(
        select(models.c.id, models.c.name, models.c.version, models.c.eval_job_id).where(models.c.study_id == study_id))]
    final = conn.execute(select(studies.c.final_model_id).where(studies.c.id == study_id)).scalar()
    for j in js:
        j["params"] = j["params"] or {}
    return StudyRefs(jobs=js, datasets=ds, curations=cs, curation_dataset_counts=counts, models=ms, final_model_id=final)
