"""작업 생성·조회·로그·취소·재시도·대기열(§10.2, §10.5, §8.2). 산출물·HPC 행·input.zip은 `job_files.py`."""

from __future__ import annotations

import os
import uuid
from typing import Any

from physicsai_core.db.repositories import hpc as hpc_repo
from physicsai_core.db.repositories import jobs as jobs_repo
from physicsai_core.db.repositories import queue as queue_repo
from physicsai_core.db.repositories import studies as studies_repo
from physicsai_core.errors import DomainError
from physicsai_core.paths import resolve_in_study
from physicsai_core.state_machine import TERMINAL

from ..auth import Principal
from ..context import AppContext
from .common import (
    MOVED_HINT,
    audit,
    clamp_limit,
    decode_cursor,
    encode_cursor,
    file_size,
    job_detail,
    job_summary,
    require_config_ok,
    require_global_admin,
    require_job,
    require_power,
    study_root,
)
from . import job_params
from .job_params.base import invalid_errors
from .job_params.study_manage import require_retryable_type, study_gate

MAX_LOG_LIMIT = 262144


# ---- 작업 생성 ----------------------------------------------------------------


def create_job(ctx: AppContext, principal: Principal, study_id: str, job_type: str, raw_params: dict[str, Any],
               rid: str, ip: str | None) -> dict[str, Any]:
    with ctx.engine.begin() as conn:
        study = studies_repo.require(conn, study_id, for_update=True)  # 게이트·삽입 사이 경합 차단(D3-25)
        require_power(principal, study["project_id"])
        require_config_ok(ctx)
        study_gate(conn, study, job_type)  # 보관(관리 작업 예외)·정리 중 차단(phase3 R3-2·R3-4)
        p = job_params.parse_params(job_type, raw_params)
        params, result, warnings = job_params.prepare(ctx, conn, study, job_type, p)
        job_id = str(uuid.uuid4())
        job = jobs_repo.insert_job(conn, study=study, job_type=job_type, params=params, user_id=principal.user_id,
                                   user_name=principal.display_name, result=result, warnings=warnings, job_id=job_id)
        job_params.after_insert(conn, principal, study, job_type, job_id, params, result)
        audit(conn, principal, "JOB_CREATE", "job", job_id, {"job_type": job_type, "study_id": study_id}, rid, ip)
        return job_detail(conn, job, principal, include_commands=False, ai_root=ctx.settings.storage.ai_root)


# ---- 조회 -------------------------------------------------------------------


def list_jobs(ctx: AppContext, principal: Principal, *, study_id: str | None, state: str | None, mine: bool,
              job_type: str | None, limit: int | None, cursor: str | None) -> tuple[list[dict[str, Any]], str | None]:
    lim, off = clamp_limit(limit), decode_cursor(cursor)
    with ctx.engine.connect() as conn:
        rows = jobs_repo.list_with_study_title(
            conn, study_id=study_id or None, states=state.split(",") if state else None,
            created_by=principal.user_id if mine else None, job_type=job_type or None, limit=lim + 1, offset=off,
        )
        pos = {"SLOT": jobs_repo.queue_positions(conn, "SLOT"), "LIGHT": jobs_repo.queue_positions(conn, "LIGHT")}
        hs = hpc_repo.summary_for_jobs(conn, [r["id"] for r in rows[:lim]])
    out = [job_summary(r, r["study_title"], pos[r["lane"]].get(r["id"]), hs.get(r["id"])) for r in rows[:lim]]
    return out, (encode_cursor(off + lim) if len(rows) > lim else None)


def get_job(ctx: AppContext, principal: Principal, job_id: str, include_commands: bool) -> tuple[dict[str, Any], str]:
    with ctx.engine.connect() as conn:
        j = require_job(conn, job_id)
        if include_commands:
            require_global_admin(principal)
        detail = job_detail(conn, j, principal, include_commands=include_commands, ai_root=ctx.settings.storage.ai_root)
        s = studies_repo.get(conn, j["study_id"])
    log_size = file_size(os.path.join(study_root(ctx, s), "logs", job_id, "job.log")) if s else 0
    etag = f'"{job_id}:{j["version"]}:{log_size}{":c" if include_commands else ""}"'
    return detail, etag


def job_etag(ctx: AppContext, job_id: str) -> str | None:
    with ctx.engine.connect() as conn:
        j = jobs_repo.get_job(conn, job_id)
        if j is None:
            return None
        s = studies_repo.get(conn, j["study_id"])
    log_size = file_size(os.path.join(study_root(ctx, s), "logs", job_id, "job.log")) if s else 0
    return f'"{job_id}:{j["version"]}:{log_size}"'


def read_log(ctx: AppContext, job_id: str, step_no: int | None, cursor: int, limit: int) -> dict[str, Any]:
    if cursor < 0 or limit < 1 or limit > MAX_LOG_LIMIT:
        raise invalid_errors([{"loc": ["query", "limit"], "msg": f"1~{MAX_LOG_LIMIT}"}])
    with ctx.engine.connect() as conn:
        j = require_job(conn, job_id)
        s = studies_repo.require(conn, j["study_id"])
        if step_no is None:
            rel = f"logs/{job_id}/job.log"
        else:
            steps = {x["step_no"]: x for x in jobs_repo.get_steps(conn, job_id)}
            if step_no not in steps:
                raise DomainError("NOT_FOUND", "step을 찾을 수 없습니다", status=404)
            rel = steps[step_no]["log_rel"]
    path = resolve_in_study(study_root(ctx, s), rel)
    if not os.path.isfile(path):
        msg = f"로그 파일이 없습니다. {MOVED_HINT}" if j["state"] in TERMINAL else "로그가 아직 없습니다"
        raise DomainError("LOG_NOT_FOUND", msg, status=404)
    size = os.path.getsize(path)
    with open(path, "rb") as fh:
        fh.seek(min(cursor, size))
        data = fh.read(limit)
    # 끝에서 잘린 UTF-8 문자는 다음 요청으로 넘긴다
    end = len(data)
    i = end - 1
    while i >= 0 and end - i <= 4 and (data[i] & 0xC0) == 0x80:
        i -= 1
    if i >= 0:
        lead = data[i]
        need = 1 if lead < 0x80 else 2 if lead >> 5 == 0b110 else 3 if lead >> 4 == 0b1110 else 4 if lead >> 3 == 0b11110 else 1
        if end - i < need:
            end = i
    if end == 0:
        end = len(data)
    chunk = data[:end]
    nxt = min(cursor, size) + end
    return {"text": chunk.decode("utf-8", errors="replace"), "next_cursor": nxt, "eof": nxt >= size, "size": size}


# ---- 취소·재시도·대기열 ---------------------------------------------------------


def cancel_job(ctx: AppContext, principal: Principal, job_id: str, rid: str, ip: str | None) -> dict[str, Any]:
    with ctx.engine.begin() as conn:
        require_job(conn, job_id)
        require_global_admin(principal)
        j = jobs_repo.request_cancel(conn, job_id, principal.user_id)
        audit(conn, principal, "JOB_CANCEL", "job", job_id, {"state": j["state"]}, rid, ip)
        return job_detail(conn, j, principal, include_commands=False, ai_root=ctx.settings.storage.ai_root)


def retry_job(ctx: AppContext, principal: Principal, job_id: str, from_step: int | None, rid: str, ip: str | None) -> dict[str, Any]:
    with ctx.engine.begin() as conn:
        old = require_job(conn, job_id)
        if old["created_by"] == principal.user_id:
            require_power(principal, old["project_id"])
        else:
            require_global_admin(principal)
        require_config_ok(ctx)
        job = retry_locked(conn, principal, old, from_step, rid, ip)
        return job_detail(conn, job, principal, include_commands=False, ai_root=ctx.settings.storage.ai_root)


def retry_locked(conn: Any, principal: Principal, old: dict[str, Any], from_step: int | None, rid: str | None,
                 ip: str | None) -> dict[str, Any]:
    """재시도 본체(권한·설정 확인은 호출부): 상태·유형 → Study 잠금·게이트 → 시작 step → 새 작업 + on_retry + 감사.
    일괄 예측 retry-failed(phase3 §14.7)가 하위마다 같은 트랜잭션에서 부른다."""
    job_id = old["id"]
    if old["state"] not in TERMINAL or old["state"] == "SUCCEEDED":
        raise DomainError("JOB_NOT_RETRYABLE", "실패·취소·중단된 작업만 재시도할 수 있습니다", status=409)
    require_retryable_type(old["job_type"])
    study = studies_repo.require(conn, old["study_id"], for_update=True)
    study_gate(conn, study, old["job_type"])
    steps = jobs_repo.get_steps(conn, job_id)
    default_from = next((s["step_no"] for s in steps if s["state"] in ("FAILED", "CANCELED", "PENDING", "RUNNING")), 1)
    if from_step is None:
        from_step = default_from
    if from_step > default_from or from_step > len(steps):
        raise invalid_errors([{"loc": ["from_step"], "msg": f"1~{default_from}"}])
    if from_step > 1 and old["job_type"] in ("PREDICT_VERIFY", "TD_SOLVE"):
        from_step = 1  # HPC 제출 이력은 재사용하지 않는다(phase2 §7.1: TD_SOLVE는 항상 TS_PREP부터)
    new_id = str(uuid.uuid4())
    job = jobs_repo.insert_job(
        conn, study=study, job_type=old["job_type"], params=old["params"], user_id=principal.user_id,
        user_name=principal.display_name, result=dict(old["result"] or {}), retry_of_job_id=job_id,
        resume_from_step=from_step if from_step > 1 else None, job_id=new_id,
    )
    job_params.on_retry(conn, old, new_id)
    audit(conn, principal, "JOB_RETRY", "job", new_id, {"retry_of": job_id, "from_step": from_step}, rid, ip)
    return job


def queue_view(ctx: AppContext) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        slot = queue_repo.slot_row(conn)
        rows = queue_repo.active_jobs(conn)
        hs = hpc_repo.summary_for_jobs(conn, [r["id"] for r in rows])
    out: dict[str, Any] = {
        "slot": {"holder_job_id": slot["holder_job_id"], "since": slot["lease_acquired_at"]},
        "running": None, "queued": [], "light": {"running": None, "queued": []}, "waiting_hpc": [], "collecting": [],
    }
    slot_pos = light_pos = 0
    for r in rows:
        if r["state"] == "QUEUED":
            if r["lane"] == "SLOT":
                slot_pos += 1
                out["queued"].append(job_summary(r, r["study_title"], slot_pos))
            else:
                light_pos += 1
                out["light"]["queued"].append(job_summary(r, r["study_title"], light_pos))
        elif r["state"] == "RUNNING":
            if r["lane"] == "SLOT":
                out["running"] = job_summary(r, r["study_title"], None)
            else:
                out["light"]["running"] = job_summary(r, r["study_title"], None)
        elif r["state"] == "WAITING_HPC":
            out["waiting_hpc"].append(job_summary(r, r["study_title"], None, hs.get(r["id"])))
        elif r["state"] == "COLLECTING":
            out["collecting"].append(job_summary(r, r["study_title"], None, hs.get(r["id"])))
    return out


def move_job(ctx: AppContext, principal: Principal, job_id: str, position: int, rid: str, ip: str | None) -> dict[str, Any]:
    with ctx.engine.begin() as conn:
        require_job(conn, job_id)
        require_global_admin(principal)
        jobs_repo.move_in_queue(conn, job_id, position)
        audit(conn, principal, "QUEUE_MOVE", "job", job_id, {"position": position}, rid, ip)
    return queue_view(ctx)
