"""⑤ 최적화 조회 API(phase2 §12.8)·응답 후보(§6.12.2)."""

from __future__ import annotations

import json
import os
from typing import Any

from physicsai_core.stage5_optimize import optimize as opt
from physicsai_core.db.repositories import artifacts as artifacts_repo
from physicsai_core.db.repositories import jobs as jobs_repo
from physicsai_core.db.repositories import models as models_repo
from physicsai_core.db.repositories import optimizations as opt_repo
from physicsai_core.db.repositories import studies as studies_repo
from physicsai_core.errors import DomainError
from physicsai_core.paths import display_path, resolve_in_study

from ..context import AppContext
from .common import study_root


def _artifact_id(conn: Any, job_id: str, kind: str) -> str | None:
    for a in artifacts_repo.list_for_job(conn, job_id):
        if a["kind"] == kind:
            return a["id"]
    return None


def opt_out(ctx: AppContext, conn: Any, st: dict[str, Any], o: dict[str, Any]) -> dict[str, Any]:
    m = models_repo.get(conn, o["model_id"])
    return {
        "id": o["id"], "study_id": o["study_id"], "job_id": o["job_id"], "status": o["status"], "approach": o["approach"],
        "opt_method": o["opt_method"], "max_designs": o["max_designs"], "model_id": o["model_id"],
        "model_name": f"{m['name']} v{m['version']}" if m else None, "param_set_id": o["param_set_id"],
        "study_folder": o["study_folder"], "runs_started": o["runs_started"], "responses": o["responses"] or [],
        "summary_status": o["summary_status"], "summary_meta": o["summary_meta"],
        "summary_artifact_id": _artifact_id(conn, o["job_id"], "OPT_SUMMARY"), "file_count": o["file_count"],
        "file_list_artifact_id": _artifact_id(conn, o["job_id"], "FILE_LIST"),
        "folder_display_path": display_path(ctx.settings.storage.ai_root, st["folder_name"], o["dir_rel"] + o["study_folder"]),
        "created_by_name": o["created_by_name"], "created_at": o["created_at"],
    }


def list_opts(ctx: AppContext, study_id: str) -> list[dict[str, Any]]:
    with ctx.engine.connect() as conn:
        st = studies_repo.require(conn, study_id)
        return [opt_out(ctx, conn, st, o) for o in opt_repo.list_opts(conn, study_id)]


def get_opt(ctx: AppContext, oid: str) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        o = opt_repo.get_opt(conn, oid)
        if o is None:
            raise DomainError("NOT_FOUND", "최적화를 찾을 수 없습니다", status=404)
        st = studies_repo.require(conn, o["study_id"])
        return opt_out(ctx, conn, st, o)


def _read_artifact_json(ctx: AppContext, st: dict[str, Any], a: dict[str, Any]) -> Any:
    try:
        p = resolve_in_study(study_root(ctx, st), a["rel_path"])
        if os.path.getsize(p) > ctx.settings.ui.max_artifact_bytes:
            return None
        with open(p, encoding="utf-8-sig") as fh:
            return json.load(fh)
    except (OSError, ValueError, DomainError):
        return None


def response_candidates(ctx: AppContext, study_id: str, model_id: str | None) -> dict[str, Any]:
    """같은 Study의 최근 SUCCEEDED PREDICT(모델 일치 우선) 미리보기·커브에서 콤보 후보."""
    with ctx.engine.connect() as conn:
        st = studies_repo.require(conn, study_id)
        rows = jobs_repo.succeeded_predicts(conn, study_id)
        pick = None
        if model_id:
            pick = next((r for r in rows if (r["params"] or {}).get("model_id") == model_id), None)
        pick = pick or (rows[0] if rows else None)
        if pick is None:
            return {"source_job_id": None, "h3d": None, "xydata": None}
        arts = artifacts_repo.list_for_job(conn, pick["id"])
    h3d = xy = None
    for a in arts:
        if a["kind"] == "PREVIEW_JSON" and h3d is None:
            h3d = opt.candidates_from_preview(_read_artifact_json(ctx, st, a))
        if a["kind"] == "CURVE_JSON" and xy is None:
            xy = opt.candidates_from_curve(_read_artifact_json(ctx, st, a))
    return {"source_job_id": pick["id"], "h3d": h3d, "xydata": xy}
