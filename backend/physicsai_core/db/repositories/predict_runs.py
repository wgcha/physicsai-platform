"""④ 단일 예측 실행 목록 조회(phase3 §21.2 S16 V1) — 새 DB 없이 jobs(PREDICT)·param_sets·models 읽기만."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import and_, exists, or_, select, tuple_
from sqlalchemy.engine import Connection
from sqlalchemy.orm import aliased

from ..tables import jobs, models, param_sets
from .jobs import row_dict

MAX_CHAIN = 50


def list_runs(conn: Connection, study_id: str, *, mode: str, states: Sequence[str] | None, limit: int,
              after: tuple[datetime, str] | None) -> list[dict[str, Any]]:
    """그 Study의 PREDICT 중 일괄 하위(params.batch_run) 제외, 재시도된 이전 시도 제외. (created_at DESC, id DESC) 커서."""
    newer = aliased(jobs)
    conds = [jobs.c.job_type == "PREDICT", jobs.c.study_id == study_id, jobs.c.params["batch_run"].is_(None),
             ~exists(select(newer.c.id).where(newer.c.retry_of_job_id == jobs.c.id))]
    im = jobs.c.params["input_mode"].astext
    if mode == "template":
        conds.append(or_(im.is_(None), im == "parametric"))
    elif mode == "prepared":
        conds.append(im == "prepared")
    if states:
        conds.append(jobs.c.state.in_(list(states)))
    if after is not None:
        conds.append(tuple_(jobs.c.created_at, jobs.c.id) < tuple_(after[0], after[1]))
    q = select(jobs).where(and_(*conds)).order_by(jobs.c.created_at.desc(), jobs.c.id.desc()).limit(limit)
    return [row_dict(r) for r in conn.execute(q)]


def chain(conn: Connection, job: dict[str, Any]) -> tuple[int, str]:
    """(시도 수, 최초 작업 id). retry_of_job_id 사슬을 최대 MAX_CHAIN까지만 따라간다."""
    n, cur = 1, job
    seen = {job["id"]}
    while cur.get("retry_of_job_id") and n < MAX_CHAIN:
        r = conn.execute(select(jobs.c.id, jobs.c.retry_of_job_id).where(jobs.c.id == cur["retry_of_job_id"])).first()
        if r is None or r.id in seen:
            break
        seen.add(r.id)
        cur = {"id": r.id, "retry_of_job_id": r.retry_of_job_id}
        n += 1
    return n, cur["id"]


def param_sets_by_ids(conn: Connection, ids: Sequence[str]) -> dict[str, dict[str, Any]]:
    ids = sorted({i for i in ids if i})
    if not ids:
        return {}
    q = select(param_sets.c.id, param_sets.c.label, param_sets.c.input_kind).where(param_sets.c.id.in_(ids))
    return {r.id: row_dict(r) for r in conn.execute(q)}


def models_by_ids(conn: Connection, ids: Sequence[str]) -> dict[str, dict[str, Any]]:
    ids = sorted({i for i in ids if i})
    if not ids:
        return {}
    q = select(models.c.id, models.c.name, models.c.version).where(models.c.id.in_(ids))
    return {r.id: row_dict(r) for r in conn.execute(q)}


def latest_verify(conn: Connection, predict_job_ids: Sequence[str]) -> dict[str, dict[str, Any]]:
    """예측 작업 id → 이를 가리키는 최신 PREDICT_VERIFY {job_id, state}."""
    ids = [i for i in predict_job_ids if i]
    if not ids:
        return {}
    pj = jobs.c.params["predict_job_id"].astext
    q = (select(jobs.c.id, jobs.c.state, pj.label("pj")).where(and_(jobs.c.job_type == "PREDICT_VERIFY", pj.in_(ids)))
         .order_by(jobs.c.created_at.desc(), jobs.c.id.desc()))
    out: dict[str, dict[str, Any]] = {}
    for r in conn.execute(q):
        out.setdefault(r.pj, {"job_id": r.id, "state": r.state})
    return out
