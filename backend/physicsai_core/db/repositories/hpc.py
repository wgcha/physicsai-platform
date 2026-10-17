"""HPC job 저장소와 WAITING_HPC 전이(T10·T11·T12·T13, §6.10, §12.4). WAITING_HPC는 version CAS만 쓴다."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.engine import Connection

from ...state_machine import CANCELED, COLLECTING, FAILED, RUNNING, WAITING_HPC, check_transition
from ..tables import hpc_jobs, job_steps, jobs, train_does
from . import notifications as notif_repo
from .job_end import _side_effects_on_end
from .jobs import row_dict

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


# ---- scx(phase3 §16) ----------------------------------------------------------------------------

def insert_submitting(conn: Connection, *, job_id: str, step_id: str, run_key: str, attempt_no: int, remote_dir: str,
                      staged: dict[str, Any]) -> tuple[str, str]:
    """scx STAGE_IN 전 행 삽입(state SUBMITTING, request_id = "pai-" + id). (id, request_id)."""
    hid = str(uuid.uuid4())
    rid = "pai-" + hid
    conn.execute(
        hpc_jobs.insert().values(
            id=hid, job_id=job_id, step_id=step_id, run_key=run_key, attempt_no=attempt_no, gateway_mode="scx",
            external_job_id=None, submit_argv=None, state="SUBMITTING", remote_dir=remote_dir, request_id=rid, staged=staged,
        )
    )
    return hid, rid


def get(conn: Connection, hid: str, *, for_update: bool = False) -> dict[str, Any] | None:
    q = select(hpc_jobs).where(hpc_jobs.c.id == hid)
    if for_update:
        q = q.with_for_update()
    r = conn.execute(q).first()
    return row_dict(r) if r is not None else None


def set_fields(conn: Connection, hid: str, **values: Any) -> None:
    """버전 증가와 함께 열 갱신(워커 step 안 — 같은 행을 다른 곳이 바꾸지 않는 구간)."""
    conn.execute(update(hpc_jobs).where(hpc_jobs.c.id == hid).values(version=hpc_jobs.c.version + 1, **values))


def request_resolve(conn: Connection, hid: str, version: int, request: dict[str, Any]) -> bool:
    """API(§16.5): 조치 요청 기록(워커 폴러가 처리). version CAS."""
    r = conn.execute(
        update(hpc_jobs)
        .where(and_(hpc_jobs.c.id == hid, hpc_jobs.c.version == version, hpc_jobs.c.resolve_request.is_(None)))
        .values(version=hpc_jobs.c.version + 1, resolve_request=request)
    )
    return r.rowcount == 1


def pending_resolves(conn: Connection) -> list[dict[str, Any]]:
    """조치 요청이 있는 scx 행(작업 상태 무관 — 중단된 작업의 결과 모름 행도 정리할 수 있게)."""
    q = select(hpc_jobs).where(hpc_jobs.c.resolve_request.is_not(None)).order_by(hpc_jobs.c.submitted_at, hpc_jobs.c.id)
    return [row_dict(r) for r in conn.execute(q)]


def submitting_orphans_to_unknown(conn: Connection) -> dict[str, list[str]]:
    """housekeeping(§16.6): 워커 중단 후 남은 scx SUBMITTING 행(작업이 더 이상 RUNNING이 아님).
    제출 단계(staged.phase = submit, 또는 기록 없음)였으면 결과를 모르므로 UNKNOWN + submission_unknown,
    업로드 단계(stage_in)였으면 아직 아무것도 제출하지 않았으므로 FAILED. {"unknown": [...], "failed": [...]}."""
    rows = conn.execute(
        select(hpc_jobs.c.id, hpc_jobs.c.staged)
        .select_from(hpc_jobs.join(jobs, jobs.c.id == hpc_jobs.c.job_id))
        .where(and_(hpc_jobs.c.state == "SUBMITTING", hpc_jobs.c.gateway_mode == "scx", jobs.c.state != RUNNING))
        .with_for_update(of=hpc_jobs)
    ).all()
    out: dict[str, list[str]] = {"unknown": [], "failed": []}
    for r in rows:
        phase = (r.staged or {}).get("phase")
        if phase in ("stage_in", "stage_in_failed", "not_submitted"):
            out["failed"].append(r.id)
        else:
            out["unknown"].append(r.id)
    if out["unknown"]:
        conn.execute(
            update(hpc_jobs).where(hpc_jobs.c.id.in_(out["unknown"])).values(
                version=hpc_jobs.c.version + 1, state="UNKNOWN", submission_unknown=True,
                error_message="워커 중단으로 SCX 제출 결과를 알 수 없습니다 — SCX에서 확인 필요")
        )
    if out["failed"]:
        conn.execute(
            update(hpc_jobs).where(hpc_jobs.c.id.in_(out["failed"])).values(
                version=hpc_jobs.c.version + 1, state="FAILED", finished_at=func.now(),
                error_message="워커 중단(업로드 중) — 제출하지 않음")
        )
    return out


def doe_number(conn: Connection, study_id: str, doe_id: str) -> int:
    """D-<NNN>(§16.3): 그 Study의 train_does를 (created_at, id) 순으로 센 이 DOE의 번호(1부터)."""
    me = conn.execute(select(train_does.c.created_at).where(train_does.c.id == doe_id)).scalar_one()
    q = select(func.count()).select_from(train_does).where(and_(
        train_does.c.study_id == study_id,
        or_(train_does.c.created_at < me, and_(train_does.c.created_at == me, train_does.c.id <= doe_id))))
    return int(conn.execute(q).scalar_one())


def verify_number(conn: Connection, study_id: str, job_id: str) -> int:
    """V-<NNN>(§16.3): 그 Study의 PREDICT_VERIFY 작업을 (created_at, id) 순으로 센 이 작업의 번호(1부터)."""
    me = conn.execute(select(jobs.c.created_at).where(jobs.c.id == job_id)).scalar_one()
    q = select(func.count()).select_from(jobs).where(and_(
        jobs.c.study_id == study_id, jobs.c.job_type == "PREDICT_VERIFY",
        or_(jobs.c.created_at < me, and_(jobs.c.created_at == me, jobs.c.id <= job_id))))
    return int(conn.execute(q).scalar_one())


def unknown_open(conn: Connection, job_id: str) -> int:
    """작업의 결과 모름(UNKNOWN + submission_unknown) 행 수."""
    q = select(func.count()).select_from(hpc_jobs).where(and_(
        hpc_jobs.c.job_id == job_id, hpc_jobs.c.state == "UNKNOWN", hpc_jobs.c.submission_unknown.is_(True)))
    return int(conn.execute(q).scalar_one())


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


def add_waiting_warning(conn: Connection, job: dict[str, Any], code: str, message: str) -> bool:
    """T11(WAITING_HPC 유지) + 작업 경고 1건(scx 결과 모름 취소·조치 relay 실패)."""
    warnings = list(job.get("warnings") or [])
    warnings.append({"code": code, "message": message[:500]})
    return _transition(conn, job, WAITING_HPC, warnings=warnings)


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

