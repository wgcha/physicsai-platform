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


def list_for_job_with_elapsed(conn: Connection, job_id: str) -> list[dict[str, Any]]:
    """작업의 HPC 행 + 경과 초(elapsed: 종료 전이면 지금까지). (attempt_no, run_key) 순."""
    rows = conn.execute(
        select(hpc_jobs, func.extract("epoch", func.coalesce(hpc_jobs.c.finished_at, func.now()) - hpc_jobs.c.submitted_at).label("elapsed"))
        .where(hpc_jobs.c.job_id == job_id)
        .order_by(hpc_jobs.c.attempt_no, hpc_jobs.c.run_key)
    ).all()
    return [dict(r._mapping) for r in rows]


def get_many(conn: Connection, ids: list[str]) -> list[dict[str, Any]]:
    """id 목록의 HPC 행(순서 보장 없음)."""
    return [dict(r._mapping) for r in conn.execute(select(hpc_jobs).where(hpc_jobs.c.id.in_(ids)))]


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


def to_collecting_partial(conn: Connection, job: dict[str, Any], failed: int, total: int) -> bool:
    """T10b(phase2 §7.1): 일부 run 실패 → 성공 run 회수. attention_code=HPC_RUN_FAILED, 경고·알림 HPC_PARTIAL_FAILED."""
    warnings = list(job.get("warnings") or [])
    warnings.append({"code": "HPC_PARTIAL_FAILED", "message": f"PBS 해석 {total}개 중 {failed}개 실패 — 성공한 run만 회수합니다"})
    result = dict(job.get("result") or {})
    result.update({"submitted": total, "failed": failed})
    ok = _transition(conn, job, COLLECTING, attention_code="HPC_RUN_FAILED", warnings=warnings, result=result)
    if ok:
        _step_state(conn, job["id"], "HPC_WAIT", "SUCCEEDED", finished_at=func.now(),
                    progress_label=f"{total}개 중 {failed}개 실패")
        notif_repo.notify_job(conn, job["id"], "HPC_PARTIAL_FAILED")
    return ok


def summary_for_jobs(conn: Connection, job_ids: list[str]) -> dict[str, dict[str, int]]:
    """작업별 hpc_summary(phase2 §12.9): 최신 attempt 기준 {total, queued, running, succeeded, failed, collected}."""
    if not job_ids:
        return {}
    rows = conn.execute(
        select(hpc_jobs.c.job_id, hpc_jobs.c.state, hpc_jobs.c.collect_state).where(hpc_jobs.c.job_id.in_(job_ids))
    ).all()
    out: dict[str, dict[str, int]] = {}
    for r in rows:
        d = out.setdefault(r.job_id, {"total": 0, "queued": 0, "running": 0, "succeeded": 0, "failed": 0, "collected": 0})
        d["total"] += 1
        if r.state in ("SUBMITTING", "QUEUED", "UNKNOWN"):
            d["queued"] += 1
        elif r.state in ("RUNNING", "CANCEL_REQUESTED"):
            d["running"] += 1
        elif r.state == "SUCCEEDED":
            d["succeeded"] += 1
        elif r.state in ("FAILED", "LOST"):
            d["failed"] += 1
        if r.collect_state == "COLLECTED":
            d["collected"] += 1
    return out


def set_collect_state(conn: Connection, hid: str, collect_state: str, collected: Any = None) -> None:
    vals: dict[str, Any] = {"collect_state": collect_state}
    if collect_state == "COLLECTED":
        vals["collected_at"] = func.now()
        vals["collected"] = collected
    conn.execute(update(hpc_jobs).where(hpc_jobs.c.id == hid).values(**vals))


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

