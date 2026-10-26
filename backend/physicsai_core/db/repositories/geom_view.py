"""형상 미리보기(`geom_previews`)·결과 3D 컨투어(`contour3d_cache`) 캐시 인덱스 저장소(geometry-view.md §6.4·§6.6·§13.5).

두 테이블은 같은 상태 모델(QUEUED → RUNNING → DONE | FAILED | CANCELED, housekeeping 삭제 후 EXPIRED)을 쓴다. 같은 cache_key의
QUEUED·RUNNING·DONE 행은 하나뿐(부분 unique). 작업 종료 훅(`on_job_end`)이 실패·취소·중단을 행에 반영한다.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import Table, and_, func, or_, select, update
from sqlalchemy.engine import Connection

from ..tables import contour3d_cache, doe_preview_cells, geom_previews
from .jobs import row_dict

LIVE = ("QUEUED", "RUNNING", "DONE")
ACTIVE = ("QUEUED", "RUNNING")
TABLES: dict[str, Table] = {"GEOM_PREVIEW": geom_previews, "CONTOUR_3D": contour3d_cache}
PREVIEWS, CONTOURS = "geom_previews", "contour3d_cache"  # 서비스는 테이블 대신 이름으로 부른다(레이어 규칙 4)
_BY_NAME: dict[str, Table] = {PREVIEWS: geom_previews, CONTOURS: contour3d_cache}


def _t(t: Table | str) -> Table:
    return _BY_NAME[t] if isinstance(t, str) else t
ART_COLS: dict[str, tuple[str, ...]] = {
    "geom_previews": ("glb_artifact_id", "fe_glb_artifact_id", "manifest_artifact_id"),
    "contour3d_cache": ("glb_artifact_id", "frames_artifact_id", "manifest_artifact_id"),
    "doe_preview_cells": ("png_artifact_id", "glb_artifact_id", "manifest_artifact_id"),  # doe-preview.md §6.7
}


def insert(conn: Connection, t: Table | str, values: dict[str, Any]) -> dict[str, Any]:
    t = _t(t)
    rid = values.get("id") or str(uuid.uuid4())
    conn.execute(t.insert().values(id=rid, **{k: v for k, v in values.items() if k != "id"}))
    return get(conn, t, rid)  # type: ignore[return-value]


def get(conn: Connection, t: Table | str, rid: str) -> dict[str, Any] | None:
    t = _t(t)
    return row_dict(conn.execute(select(t).where(t.c.id == rid)).first())


def by_job(conn: Connection, t: Table | str, job_id: str) -> dict[str, Any] | None:
    t = _t(t)
    return row_dict(conn.execute(select(t).where(t.c.job_id == job_id).order_by(t.c.created_at.desc()).limit(1)).first())


def live_by_key(conn: Connection, t: Table | str, key: str, *, for_update: bool = False) -> dict[str, Any] | None:
    t = _t(t)
    q = select(t).where(and_(t.c.cache_key == key, t.c.status.in_(LIVE)))
    if for_update:
        q = q.with_for_update()
    return row_dict(conn.execute(q).first())


def set_values(conn: Connection, t: Table | str, rid: str, **vals: Any) -> None:
    t = _t(t)
    conn.execute(update(t).where(t.c.id == rid).values(**vals))


def touch(conn: Connection, t: Table | str, rid: str) -> None:
    t = _t(t)
    conn.execute(update(t).where(t.c.id == rid).values(last_access_at=func.now()))


def active_count(conn: Connection, t: Table | str, user_id: str) -> int:
    t = _t(t)
    return int(conn.execute(select(func.count()).select_from(t).where(and_(t.c.created_by == user_id, t.c.status.in_(ACTIVE)))).scalar()
               or 0)


def queued_previews(conn: Connection, user_id: str, param_set_id: str) -> list[dict[str, Any]]:
    """같은 사용자·같은 세트의 QUEUED(아직 시작 안 함) 미리보기(§6.4-3 최신 값 우선 → 취소 대상)."""
    q = select(geom_previews).where(and_(geom_previews.c.created_by == user_id, geom_previews.c.param_set_id == param_set_id,
                                         geom_previews.c.status == "QUEUED")).with_for_update()
    return [row_dict(r) for r in conn.execute(q)]


def by_artifact(conn: Connection, artifact_id: str) -> tuple[str, dict[str, Any]] | None:
    """산출물 id를 가진 캐시 행(테이블 이름, 행) — 410 ARTIFACT_EXPIRED 판정용(산출물 행이 지워져도 id는 남는다)."""
    for t in (geom_previews, contour3d_cache, doe_preview_cells):
        cols = [t.c[c] for c in ART_COLS[t.name]]
        r = conn.execute(select(t).where(or_(*[c == artifact_id for c in cols])).limit(1)).first()
        if r is not None:
            return t.name, row_dict(r)
    return None


def on_job_end(conn: Connection, job: dict[str, Any], state: str) -> None:
    """GEOM_PREVIEW·CONTOUR_3D 작업 종료(모든 경로): 성공은 GV_REGISTER·C3_REGISTER가 DONE으로 둔다.
    실패·중단 → FAILED(캐시로 쓰지 않음), 취소 → CANCELED. 아직 QUEUED·RUNNING인 행만."""
    t = TABLES.get(job["job_type"])
    if t is None or state == "SUCCEEDED":
        return
    from ..tables import jobs

    new = "CANCELED" if state == "CANCELED" else "FAILED"
    vals: dict[str, Any] = {"status": new, "finished_at": func.now()}
    code = conn.execute(select(jobs.c.failure_code).where(jobs.c.id == job["id"])).scalar() or job.get("failure_code")
    if new == "FAILED" and code:  # 종료 전이가 이미 기록한 실패 코드(lease 해제 경로는 job dict에 없음)
        vals["code"] = str(code)[:64]
    conn.execute(update(t).where(and_(t.c.job_id == job["id"], t.c.status.in_(ACTIVE))).values(**vals))


def purge_candidates(conn: Connection, t: Table | str, *, older_than_days: float) -> list[dict[str, Any]]:
    """보관 기간 초과(마지막 접근 기준) DONE·FAILED·CANCELED 행. QUEUED·RUNNING은 건너뜀(§6.6 ①)."""
    t = _t(t)
    cut = datetime.now(timezone.utc) - timedelta(days=float(older_than_days))
    q = select(t).where(and_(t.c.status.in_(("DONE", "FAILED", "CANCELED")), t.c.last_access_at < cut)).order_by(t.c.last_access_at)
    return [row_dict(r) for r in conn.execute(q)]


def lru_rows(conn: Connection, t: Table | str) -> list[dict[str, Any]]:
    """총량 정리(§6.6 ②) 후보: 종료 행, 마지막 접근 오래된 순."""
    t = _t(t)
    q = select(t).where(t.c.status.in_(("DONE", "FAILED", "CANCELED"))).order_by(t.c.last_access_at)
    return [row_dict(r) for r in conn.execute(q)]


def active_keys(conn: Connection, t: Table | str) -> set[tuple[str, str]]:
    """(study_id, cache_key) — QUEUED·RUNNING 행의 폴더는 정리하지 않는다."""
    t = _t(t)
    return {(r.study_id, r.cache_key) for r in conn.execute(select(t.c.study_id, t.c.cache_key).where(t.c.status.in_(ACTIVE)))}


def recent_timings(conn: Connection, source_kind: str, limit: int = 10) -> list[dict[str, Any]]:
    """같은 원본 종류의 최근 성공 3D 컨투어 소요(timing) — 대기 안내 예상 시간(§13.6)."""
    t = contour3d_cache
    q = select(t.c.timing).where(and_(t.c.source_kind == source_kind, t.c.result_status == "OK", t.c.status.in_(("DONE", "EXPIRED")))) \
        .order_by(t.c.finished_at.desc()).limit(limit)
    return [r.timing for r in conn.execute(q) if isinstance(r.timing, dict)]
