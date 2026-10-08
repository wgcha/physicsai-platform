"""HPC job 저장소와 WAITING_HPC 전이(T10·T11·T12·T13, §6.10, §12.4). WAITING_HPC는 version CAS만 쓴다."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import and_, func, select, update
from sqlalchemy.engine import Connection

from ...state_machine import CANCELED, COLLECTING, FAILED, WAITING_HPC, check_transition
from ..tables import hpc_jobs, job_steps, jobs
from . import notifications as notif_repo
from .jobs import _side_effects_on_end, row_dict

HPC_TERMINAL = ("SUCCEEDED", "FAILED", "CANCELED", "LOST")


def insert(conn: Connection, *, job_id: str, step_id: str, run_key: str, attempt_no: int, gateway_mode: str,
           external_job_id: str, submit_argv: list[str] | None) -> str:
    hid = str(uuid.uuid4())
    conn.execute(
        hpc_jobs.insert().values(
            id=hid, job_id=job_id, step_id=step_id, run_key=run_key, attempt_no=attempt_no, gateway_mode=gateway_mode,
            external_job_id=external_job_id, submit_argv=submit_argv, state="QUEUED", submitted_at=func.now(),
        )
    )
    return hid


def for_job(conn: Connection, job_id: str) -> list[dict[str, Any]]:
    return [row_dict(r) for r in conn.execute(select(hpc_jobs).where(hpc_jobs.c.job_id == job_id).order_by(hpc_jobs.c.attempt_no))]


def update_hpc(conn: Connection, hid: str, version: int, **values: Any) -> bool:
    r = conn.execute(
        update(hpc_jobs)
        .where(and_(hpc_jobs.c.id == hid, hpc_jobs.c.version == version))
        .values(version=hpc_jobs.c.version + 1, last_polled_at=func.now(), **values)
    )
    return r.rowcount == 1


def waiting_jobs(conn: Connection) -> list[dict[str, Any]]:
    return [row_dict(r) for r in conn.execute(select(jobs).where(jobs.c.state == WAITING_HPC).order_by(jobs.c.updated_at))]


def _transition(conn: Connection, job: dict[str, Any], to: str, **values: Any) -> bool:
    check_transition(job["state"], to)
    r = conn.execute(
        update(jobs)
        .where(and_(jobs.c.id == job["id"], jobs.c.version == job["version"], jobs.c.state == job["state"]))
        .values(state=to, updated_at=func.now(), version=jobs.c.version + 1, **values)
    )
    return r.rowcount == 1


def _step_state(conn: Connection, job_id: str, kind: str, state: str, **values: Any) -> None:
    conn.execute(update(job_steps).where(and_(job_steps.c.job_id == job_id, job_steps.c.kind == kind)).values(state=state, **values))


def to_collecting(conn: Connection, job: dict[str, Any]) -> bool:
    """T10."""
    ok = _transition(conn, job, COLLECTING)
    if ok:
        _step_state(conn, job["id"], "HPC_WAIT", "SUCCEEDED", finished_at=func.now())
    return ok


def set_attention(conn: Connection, job: dict[str, Any], code: str | None, result: dict[str, Any] | None = None) -> bool:
    """T11(WAITING_HPC 유지 + attention_code)."""
    vals: dict[str, Any] = {"attention_code": code}
    if result is not None:
        vals["result"] = result
    return _transition(conn, job, WAITING_HPC, **vals)


def fail_waiting(conn: Connection, job: dict[str, Any], code: str, message: str) -> bool:
    """T13."""
    ok = _transition(conn, job, FAILED, failure_code=code, failure_message=message[:500], finished_at=func.now())
    if ok:
        _step_state(conn, job["id"], "HPC_WAIT", "FAILED", failure_code=code, failure_message=message[:500], finished_at=func.now())
        conn.execute(update(job_steps).where(and_(job_steps.c.job_id == job["id"], job_steps.c.state == "PENDING")).values(state="SKIPPED"))
        _side_effects_on_end(conn, job, FAILED)
        notif_repo.notify_job(conn, job["id"], "JOB_FAILED")
    return ok


def cancel_waiting(conn: Connection, job: dict[str, Any]) -> bool:
    """T12(WAITING_HPC → CANCELED). COLLECTING은 lease 소유 워커가 처리."""
    ok = _transition(conn, job, CANCELED, finished_at=func.now())
    if ok:
        conn.execute(
            update(job_steps)
            .where(and_(job_steps.c.job_id == job["id"], job_steps.c.state.in_(["PENDING", "RUNNING"])))
            .values(state="CANCELED")
        )
        notif_repo.notify_job(conn, job["id"], "JOB_CANCELED")
    return ok

