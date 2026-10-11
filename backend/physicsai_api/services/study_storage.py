"""Study 용량·정리 보고서(phase3 §5.4, §5.6). 계산·이동은 워커 작업(STUDY_STORAGE_SCAN·STUDY_CLEANUP)이 한다."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.engine import Connection

from physicsai_core.db.repositories import study_manage as sm_repo
from physicsai_core.db.repositories import studies as studies_repo
from physicsai_core.paths import BACKUP_DIR
from physicsai_core.study_storage.categories import CATEGORY_IMPACTS, CLEANUP_JOB_TYPE, SCAN_JOB_TYPE
from physicsai_core.study_storage.stale import stale_reason

from ..auth import Principal
from ..context import AppContext
from .common import display_path


def is_stale(conn: Connection, ctx: AppContext, study_id: str, scan: dict[str, Any] | None) -> str | None:
    """§5.4 낡음 사유(낡지 않았으면 None). 보고서와 정리 사전조건이 같이 쓴다."""
    if scan is None:
        return stale_reason(None, finished_after=0, has_active=False, now=datetime.now(timezone.utc), stale_after_hours=1)
    return stale_reason(
        scan,
        finished_after=sm_repo.finished_after(conn, study_id, scan["started_at"], (SCAN_JOB_TYPE,)),
        has_active=sm_repo.has_active_except(conn, study_id, scan["id"]),
        now=datetime.now(timezone.utc),
        stale_after_hours=ctx.settings.study_storage.stale_after_hours,
    )


def scan_out(j: dict[str, Any]) -> dict[str, Any]:
    r = j["result"] or {}
    cats = [{**c, "impact": CATEGORY_IMPACTS.get(c["key"], "")} for c in r.get("categories") or []]
    return {
        "job_id": j["id"], "started_at": j["started_at"], "finished_at": j["finished_at"],
        "partial": bool(r.get("partial")), "total_bytes": r.get("total_bytes", 0), "total_files": r.get("total_files", 0),
        "skipped_links": r.get("skipped_links", 0), "errors": r.get("errors", 0), "backup_bytes": r.get("backup_bytes", 0),
        "backup_files": r.get("backup_files", 0), "folders": r.get("folders") or [], "top_files": r.get("top_files") or [],
        "categories": cats,
    }


def cleanup_out(j: dict[str, Any], ai_root: str, folder_name: str) -> dict[str, Any]:
    r = j["result"] or {}
    moved = r.get("moved") or []
    rel = r.get("backup_rel")
    return {
        "job_id": j["id"], "state": j["state"], "finished_at": j["finished_at"],
        "categories": list((j["params"] or {}).get("categories") or []),
        "moved_count": int(r.get("moved_count", len(moved))), "moved_bytes": int(r.get("moved_bytes", 0)),
        "skipped_count": int(r.get("skipped_count", len(r.get("skipped") or []))), "skipped": r.get("skipped") or [],
        "backup_rel": rel, "backup_display_path": display_path(ai_root, folder_name, rel) if rel else None,
    }


def get_report(ctx: AppContext, principal: Principal, study_id: str) -> dict[str, Any]:
    ai_root = ctx.settings.storage.ai_root
    with ctx.engine.connect() as conn:
        s = studies_repo.require(conn, study_id)
        scan = sm_repo.latest_succeeded(conn, study_id, SCAN_JOB_TYPE)
        reason = is_stale(conn, ctx, study_id, scan)
        active_scan = sm_repo.active_of_type(conn, study_id, SCAN_JOB_TYPE)
        active_cleanup = sm_repo.active_of_type(conn, study_id, CLEANUP_JOB_TYPE)
        last = sm_repo.latest_finished(conn, study_id, CLEANUP_JOB_TYPE)
    fn = s["folder_name"]
    return {
        "study_id": study_id, "scan": scan_out(scan) if scan else None, "stale": reason is not None, "stale_reason": reason,
        "active_scan_job_id": active_scan, "active_cleanup_job_id": active_cleanup,
        "last_cleanup": cleanup_out(last, ai_root, fn) if last else None,
        "study_display_path": display_path(ai_root, fn), "backup_display_path": display_path(ai_root, fn, BACKUP_DIR),
    }
