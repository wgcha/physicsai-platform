"""리퍼(§11.2)·알림 보관기간 정리(§13.2)·scx 제출 중단 행 정리(phase3 §16.6)."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.engine import Engine

from physicsai_core.db.repositories import env_checks as env_repo
from physicsai_core.db.repositories import hpc as hpc_repo
from physicsai_core.db.repositories import job_lease as lease_repo
from physicsai_core.db.repositories import notifications as notif_repo

log = logging.getLogger("physicsai_worker")


def reap(engine: Engine) -> list[str]:
    with engine.begin() as conn:
        out = lease_repo.reap_expired(conn)
    expire_env_checks(engine)
    scx_submitting_orphans(engine)
    return out


def scx_submitting_orphans(engine: Engine) -> dict[str, list[str]]:
    """워커 중단 후 남은 scx SUBMITTING 행 → UNKNOWN + submission_unknown(제출 중이었음) 또는 FAILED(업로드 중이었음)."""
    with engine.begin() as conn:
        out = hpc_repo.submitting_orphans_to_unknown(conn)
    if out["unknown"]:
        log.warning("워커 중단으로 SCX 제출 결과를 모르는 행 %d개 — 사용자 확인 필요", len(out["unknown"]))
    return out


def expire_env_checks(engine: Engine) -> list[str]:
    """환경 점검 만료(phase2 §9.4): PENDING·RUNNING 이고 expires_at < now() → EXPIRED + ENV_CHECK_DONE 알림."""
    with engine.begin() as conn:
        return env_repo.expire_due(conn)


def purge_notifications(engine: Engine, retention_days: int) -> int:
    with engine.begin() as conn:
        return notif_repo.purge_older_than(conn, retention_days)


def purge_stale_uploads(engine: Engine, settings: Any) -> list[str]:
    """upload-report.md §4: updated_at이 upload.stale_hours보다 오래된 OPEN 업로드 세션 → 폴더를 `_backup`으로 옮기고 STALE(삭제 없음)."""
    from physicsai_core.uploads_retire import cleanup_stale

    return cleanup_stale(settings, engine)


def purge_mcp(engine: Engine, settings: Any, now: Any = None) -> dict[str, int]:
    """mcp.md §6.2: api_audit 보존 기간 초과 행·만료 후 하루 지난 확인 계획 삭제(플랫폼 내부 기록 — 사용자 산출물 아님)."""
    from datetime import datetime, timedelta, timezone

    from physicsai_core.db.repositories import api_audit as audit_repo
    from physicsai_core.db.repositories import mcp_plans as plans_repo

    now = now or datetime.now(timezone.utc)
    with engine.begin() as conn:
        audit = audit_repo.purge_older_than(conn, now - timedelta(days=settings.mcp.audit.retention_days))
        plans = plans_repo.purge_expired(conn, now - timedelta(days=1))
    return {"api_audit": audit, "mcp_plans": plans}


def purge_view_cache(engine: Engine, settings: Any) -> dict[str, int]:
    """서버측 미리보기·3D 컨투어 캐시 정리(geometry-view.md §6.6 — `<study>/_cache/`, 플랫폼 임시 산출물이라 `_backup` 이동 대신 삭제).

    ① 마지막 접근이 `retention_days`보다 오래된 DONE·FAILED·CANCELED 행 ② AI 루트 전체 캐시 합계가 `max_total_bytes`를 넘으면
    마지막 접근 오래된 순. QUEUED·RUNNING 행과 그 폴더는 건너뛴다. 삭제 = 실경로가 `<study>/_cache/<종류>/` 아래이고 링크·reparse
    point가 없을 때만 폴더 제거 + artifacts 행 삭제 + 행 status EXPIRED(요약은 남김). `_cache/` 밖은 이 규칙을 쓰지 않는다."""
    import os

    from sqlalchemy import delete, select

    from physicsai_core.cache_store import remove_cache_dir
    from physicsai_core.db.repositories import geom_view as gv_repo
    from physicsai_core.db.tables import artifacts, contour3d_cache, geom_previews, studies
    from physicsai_core.geometry.view import CACHE_DIR, CONTOUR_CACHE, PREVIEW_CACHE, cache_rel, dir_bytes
    from physicsai_core.paths import study_dir

    cfg = settings.geometry.view.cache
    prefixes = {geom_previews.name: PREVIEW_CACHE, contour3d_cache.name: CONTOUR_CACHE}
    roots: dict[str, str] = {}
    with engine.connect() as conn:
        for r in conn.execute(select(studies.c.id, studies.c.folder_name)):
            roots[r.id] = study_dir(settings.storage.ai_root, r.folder_name)
    out = {"expired": 0, "lru": 0, "skipped": 0}

    def drop(t: Any, row: dict[str, Any], why: str) -> int:
        root = roots.get(row["study_id"])
        if root is None:
            return 0
        prefix = prefixes[t.name]
        path = os.path.join(root, *cache_rel(prefix, row["cache_key"]).split("/"))
        size = dir_bytes(path) if os.path.isdir(path) and not os.path.islink(path) else 0
        if not remove_cache_dir(root, path, prefix):  # 삭제 지점은 cache_store 하나(경로 탈출·링크면 False)
            log.warning("캐시 폴더 확인 실패(경로 탈출·링크) — 건너뜀: %s", path)
            out["skipped"] += 1
            return 0
        ids = [row[c] for c in gv_repo.ART_COLS[t.name] if row.get(c)]
        with engine.begin() as conn:
            if ids:
                conn.execute(delete(artifacts).where(artifacts.c.id.in_(ids)))
            if t.name == "contour3d_cache" and row.get("job_id"):  # 변위·LOD 산출물은 캐시 행에 열이 없어 작업·kind로 지운다(C3F §5.6)
                conn.execute(delete(artifacts).where(artifacts.c.job_id == row["job_id"],
                                                     artifacts.c.kind.in_(("CONTOUR3D_DISP", "CONTOUR3D_LOD"))))
            gv_repo.set_values(conn, t, row["id"], status="EXPIRED")
        out[why] += 1
        return size

    for t in (geom_previews, contour3d_cache):
        with engine.connect() as conn:
            rows = gv_repo.purge_candidates(conn, t, older_than_days=cfg.retention_days)
        for row in rows:
            drop(t, row, "expired")
    total = sum(dir_bytes(os.path.join(r, CACHE_DIR)) for r in roots.values() if os.path.isdir(os.path.join(r, CACHE_DIR)))
    if total > cfg.max_total_bytes:
        with engine.connect() as conn:
            merged = sorted([(row["last_access_at"], t, row) for t in (geom_previews, contour3d_cache) for row in gv_repo.lru_rows(conn, t)],
                            key=lambda x: x[0])
        for _ts, t, row in merged:
            if total <= cfg.max_total_bytes:
                break
            total -= drop(t, row, "lru")
    if out["expired"] or out["lru"]:
        log.info("서버측 캐시 정리: 기간 초과 %d · 총량 초과 %d", out["expired"], out["lru"])
    return out
