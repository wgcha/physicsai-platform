"""Study 목록·조회·생성·수정·보관과 단계 상태(§10.3)."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, select

from physicsai_core.db.repositories import jobs as jobs_repo
from physicsai_core.db.repositories import models as models_repo
from physicsai_core.db.repositories import param_sets as ps_repo
from physicsai_core.db.repositories import studies as studies_repo
from physicsai_core.db.tables import jobs
from physicsai_core.errors import DomainError
from physicsai_core.fileutil import write_json

from ..auth import Principal
from ..context import AppContext
from .common import (
    audit,
    clamp_limit,
    decode_cursor,
    encode_cursor,
    model_out,
    require_config_ok,
    require_power,
    study_out,
)

# ---- Study ----------------------------------------------------------------


def list_studies(ctx: AppContext, principal: Principal, project_id: str | None, status: str | None,
                 limit: int | None, cursor: str | None) -> tuple[list[dict[str, Any]], str | None]:
    lim, off = clamp_limit(limit), decode_cursor(cursor)
    with ctx.engine.connect() as conn:
        rows = studies_repo.list_(conn, project_id=project_id, status=status, limit=lim + 1, offset=off)
    nxt = encode_cursor(off + lim) if len(rows) > lim else None
    return [study_out(s, principal, ctx.settings.storage.ai_root) for s in rows[:lim]], nxt


def _stage_status(conn: Any, study_id: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for stage in (1, 2, 3, 4, 5):  # phase2 C15: ①·②·⑤ 추가(작업 stage 컬럼 = 단계)
        r = conn.execute(
            select(jobs.c.id, jobs.c.job_type, jobs.c.state, jobs.c.created_at)
            .where(and_(jobs.c.study_id == study_id, jobs.c.stage == stage))
            .order_by(jobs.c.created_at.desc())
            .limit(1)
        ).first()
        out[str(stage)] = (
            {"latest_job_id": r.id, "latest_job_type": r.job_type, "latest_state": r.state}
            if r else {"latest_job_id": None, "latest_job_type": None, "latest_state": None}
        )
    return out


def get_study(ctx: AppContext, principal: Principal, study_id: str) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        s = studies_repo.require(conn, study_id)
        out = study_out(s, principal, ctx.settings.storage.ai_root)
        fm = models_repo.get(conn, s["final_model_id"]) if s["final_model_id"] else None
        out["final_model"] = model_out(fm, s["final_model_id"], with_curve=False, study=s, ai_root=ctx.settings.storage.ai_root) if fm else None
        out["stage_status"] = _stage_status(conn, study_id)
        cur = ps_repo.current(conn, study_id)
        out["current_param_set_id"] = cur["id"] if cur else None
    return out


def create_study(ctx: AppContext, principal: Principal, token: str | None, body: Any, rid: str, ip: str | None) -> dict[str, Any]:
    projects = ctx.auth.projects(principal, token, rid)
    if body.project_id not in {p["id"] for p in projects}:
        raise DomainError("PROJECT_NOT_FOUND", "대시보드 프로젝트를 찾을 수 없습니다", status=404)
    require_power(principal, body.project_id)
    require_config_ok(ctx)
    sid = str(uuid.uuid4())
    ai_root = os.path.normpath(ctx.settings.storage.ai_root)
    folder = os.path.join(ai_root, body.folder_name)
    with ctx.engine.begin() as conn:
        studies_repo.insert(conn, {
            "id": sid, "project_id": body.project_id, "folder_name": body.folder_name, "title": body.title,
            "status": "ACTIVE", "ai_root_snapshot": ai_root, "created_by": principal.user_id,
            "created_by_name": principal.display_name,
        })
        if os.path.lexists(folder):
            raise DomainError("FOLDER_EXISTS", "AI 루트에 같은 이름의 폴더가 이미 있습니다", status=409)
        os.mkdir(folder)
        os.mkdir(os.path.join(folder, "00_inbox"))
        write_json(os.path.join(folder, "study.json"), {
            "id": sid, "project_id": body.project_id, "title": body.title,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        audit(conn, principal, "STUDY_CREATE", "study", sid, {"folder_name": body.folder_name}, rid, ip)
        s = studies_repo.require(conn, sid)
    return study_out(s, principal, ctx.settings.storage.ai_root)


def patch_study(ctx: AppContext, principal: Principal, study_id: str, body: Any, rid: str, ip: str | None) -> dict[str, Any]:
    with ctx.engine.begin() as conn:
        s = studies_repo.require(conn, study_id)
        require_power(principal, s["project_id"])
        s = studies_repo.update_cas(conn, study_id, body.version, title=body.title)
        audit(conn, principal, "STUDY_UPDATE", "study", study_id, {"title": body.title}, rid, ip)
    return study_out(s, principal, ctx.settings.storage.ai_root)


def archive_study(ctx: AppContext, principal: Principal, study_id: str, rid: str, ip: str | None) -> dict[str, Any]:
    with ctx.engine.begin() as conn:
        s = studies_repo.require(conn, study_id, for_update=True)
        require_power(principal, s["project_id"])
        if jobs_repo.has_active_jobs(conn, study_id):
            raise DomainError("STUDY_HAS_ACTIVE_JOB", "대기 중이거나 실행 중인 작업이 있어 보관할 수 없습니다", status=409)
        s = studies_repo.update_cas(conn, study_id, None, status="ARCHIVED")
        audit(conn, principal, "STUDY_ARCHIVE", "study", study_id, None, rid, ip)
    return study_out(s, principal, ctx.settings.storage.ai_root)
