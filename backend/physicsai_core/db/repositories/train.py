"""① 학습데이터 저장소: train_setups·train_does·train_runs(phase2 §5.1~§5.3)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import and_, func, select, update
from sqlalchemy.engine import Connection

from ...errors import DomainError
from ..tables import jobs, train_does, train_runs, train_setups
from .jobs import row_dict

RUN_STATES = ("GENERATED", "SUBMITTED", "SOLVED", "SOLVE_FAILED", "COLLECTED", "COLLECT_FAILED")
RESUBMIT_STATES = ("GENERATED", "SOLVE_FAILED", "COLLECT_FAILED")


# ---- train_setups --------------------------------------------------------------


def get_setup(conn: Connection, study_id: str, *, for_update: bool = False) -> dict[str, Any] | None:
    q = select(train_setups).where(train_setups.c.study_id == study_id)
    if for_update:
        q = q.with_for_update()
    return row_dict(conn.execute(q).first())


def ensure_setup(conn: Connection, study_id: str) -> dict[str, Any]:
    s = get_setup(conn, study_id, for_update=True)
    if s is not None:
        return s
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    conn.execute(pg_insert(train_setups).values(id=str(uuid.uuid4()), study_id=study_id).on_conflict_do_nothing())
    return get_setup(conn, study_id, for_update=True)  # type: ignore[return-value]


def update_setup(conn: Connection, study_id: str, version: int | None, **values: Any) -> dict[str, Any]:
    """낙관적 동시성(version). version=None이면 무조건 갱신(워커)."""
    ensure_setup(conn, study_id)
    cond = [train_setups.c.study_id == study_id]
    if version is not None:
        cond.append(train_setups.c.version == version)
    r = conn.execute(
        update(train_setups).where(and_(*cond)).values(updated_at=func.now(), version=train_setups.c.version + 1, **values)
    )
    if r.rowcount != 1:
        raise DomainError("VERSION_CONFLICT", "다른 사용자가 먼저 수정했습니다. 새로 고친 뒤 다시 시도하세요", status=409)
    return get_setup(conn, study_id)  # type: ignore[return-value]


# ---- train_does ----------------------------------------------------------------


def insert_doe(conn: Connection, values: dict[str, Any]) -> None:
    conn.execute(train_does.insert().values(**values))


def get_doe(conn: Connection, doe_id: str) -> dict[str, Any] | None:
    return row_dict(conn.execute(select(train_does).where(train_does.c.id == doe_id)).first())


def list_does(conn: Connection, study_id: str) -> list[dict[str, Any]]:
    q = select(train_does).where(train_does.c.study_id == study_id).order_by(train_does.c.created_at.desc(), train_does.c.id)
    return [row_dict(r) for r in conn.execute(q)]


def set_doe(conn: Connection, doe_id: str, **values: Any) -> None:
    conn.execute(update(train_does).where(train_does.c.id == doe_id).values(**values))


def fail_building_doe(conn: Connection, job_id: str) -> None:
    conn.execute(
        update(train_does).where(and_(train_does.c.job_id == job_id, train_does.c.status == "BUILDING")).values(status="FAILED")
    )


# ---- train_runs ----------------------------------------------------------------


def insert_runs(conn: Connection, doe_id: str, runs: list[dict[str, Any]]) -> None:
    for r in runs:
        conn.execute(train_runs.insert().values(id=str(uuid.uuid4()), doe_id=doe_id, run_key=r["run_key"],
                                                input_rel=r["input_rel"], starter_name=r["starter_name"], state="GENERATED"))


def runs_for_doe(conn: Connection, doe_id: str, *, states: list[str] | None = None, limit: int | None = None,
                 offset: int = 0) -> list[dict[str, Any]]:
    q = select(train_runs).where(train_runs.c.doe_id == doe_id)
    if states:
        q = q.where(train_runs.c.state.in_(states))
    q = q.order_by(train_runs.c.run_key)
    if limit is not None:
        q = q.limit(limit).offset(offset)
    return [row_dict(r) for r in conn.execute(q)]


def run_state_counts(conn: Connection, doe_id: str) -> dict[str, int]:
    out = {s: 0 for s in RUN_STATES}
    for st, n in conn.execute(
        select(train_runs.c.state, func.count()).where(train_runs.c.doe_id == doe_id).group_by(train_runs.c.state)
    ):
        out[st] = int(n)
    return out


def set_run(conn: Connection, doe_id: str, run_key: str, **values: Any) -> None:
    conn.execute(
        update(train_runs)
        .where(and_(train_runs.c.doe_id == doe_id, train_runs.c.run_key == run_key))
        .values(updated_at=func.now(), **values)
    )


def set_run_state_by_hpc(conn: Connection, hpc_job_id: str, state: str) -> None:
    conn.execute(
        update(train_runs).where(train_runs.c.hpc_job_id == hpc_job_id).values(state=state, updated_at=func.now())
    )


def count_solve_jobs(conn: Connection, doe_id: str) -> int:
    q = select(func.count()).select_from(jobs).where(
        and_(jobs.c.job_type == "TD_SOLVE", jobs.c.params["doe_id"].astext == doe_id)
    )
    return int(conn.execute(q).scalar_one())

