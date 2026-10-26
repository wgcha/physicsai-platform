"""DOE 표본 형상 그리드 미리보기(`doe_previews`)·셀 캐시 인덱스(`doe_preview_cells`) 저장소(doe-preview.md §6.4·§6.7).

미리보기 행 = 요청 1건(페이지 1개): QUEUED → RUNNING → DONE | FAILED | CANCELED. 작업 종료 훅(`on_job_end`)이 실패·취소·중단을 행에 반영한다.
셀 행 = 서버측 `<study>/_cache/doe_preview/cells/` 셀 1개(DONE | EXPIRED). ERROR 셀은 행을 만들지 않는다. 같은 셀을 두 작업이 동시에 만들 수
있어 `upsert_cell`이 PK 충돌을 덮어쓰기로 처리한다.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection

from ..tables import doe_preview_cells, doe_previews
from .jobs import row_dict

ACTIVE = ("QUEUED", "RUNNING")
LIVE = ("QUEUED", "RUNNING", "DONE")
CELL_ART_COLS = ("png_artifact_id", "glb_artifact_id", "manifest_artifact_id")


def insert(conn: Connection, values: dict[str, Any]) -> dict[str, Any]:
    rid = values.get("id") or str(uuid.uuid4())
    conn.execute(doe_previews.insert().values(id=rid, **{k: v for k, v in values.items() if k != "id"}))
    return get(conn, rid)  # type: ignore[return-value]


def get(conn: Connection, rid: str, *, for_update: bool = False) -> dict[str, Any] | None:
    q = select(doe_previews).where(doe_previews.c.id == rid)
    if for_update:
        q = q.with_for_update()
    return row_dict(conn.execute(q).first())


def set_values(conn: Connection, rid: str, **vals: Any) -> None:
    conn.execute(update(doe_previews).where(doe_previews.c.id == rid).values(**vals))


def live_by_grid_key(conn: Connection, study_id: str, grid_key: str, *, for_update: bool = False) -> dict[str, Any] | None:
    """같은 Study·같은 grid_key의 QUEUED·RUNNING·DONE 가운데 가장 최근 행(§6.4-1·2). 다른 Study의 같은 형상은 별도(셀 캐시·산출물이 Study별)."""
    q = select(doe_previews).where(and_(doe_previews.c.study_id == study_id, doe_previews.c.grid_key == grid_key,
                                        doe_previews.c.status.in_(LIVE))) \
        .order_by(doe_previews.c.created_at.desc()).limit(1)
    if for_update:
        q = q.with_for_update()
    return row_dict(conn.execute(q).first())


def active_count(conn: Connection, user_id: str) -> int:
    return int(conn.execute(select(func.count()).select_from(doe_previews).where(
        and_(doe_previews.c.created_by == user_id, doe_previews.c.status.in_(ACTIVE)))).scalar() or 0)


def queued_of_user(conn: Connection, user_id: str, study_id: str) -> list[dict[str, Any]]:
    """같은 사용자·같은 Study의 QUEUED(아직 시작 안 함) 미리보기 — 호출자가 출처가 같은 것만 골라 취소한다(§6.4-3, 최신 우선)."""
    q = select(doe_previews).where(and_(doe_previews.c.created_by == user_id, doe_previews.c.study_id == study_id,
                                        doe_previews.c.status == "QUEUED")).with_for_update()
    return [row_dict(r) for r in conn.execute(q)]


def on_job_end(conn: Connection, job: dict[str, Any], state: str) -> None:
    """DOE_PREVIEW 작업 종료(모든 경로): 성공은 DP_REGISTER가 DONE으로 둔다. 실패·중단 → FAILED, 취소 → CANCELED. 아직 QUEUED·RUNNING인 행만.
    완료 청크의 셀 캐시는 그대로 남는다(§6.1 취소)."""
    if job["job_type"] != "DOE_PREVIEW" or state == "SUCCEEDED":
        return
    new = "CANCELED" if state == "CANCELED" else "FAILED"
    conn.execute(update(doe_previews).where(and_(doe_previews.c.job_id == job["id"], doe_previews.c.status.in_(ACTIVE)))
                 .values(status=new, finished_at=func.now()))


# ---- 셀 ------------------------------------------------------------------------------------------------------


def get_cells(conn: Connection, keys: list[str]) -> dict[str, dict[str, Any]]:
    if not keys:
        return {}
    q = select(doe_preview_cells).where(doe_preview_cells.c.cache_key.in_(keys))
    return {r.cache_key: row_dict(r) for r in conn.execute(q)}


def done_cells(conn: Connection, study_id: str, keys: list[str]) -> dict[str, dict[str, Any]]:
    return {k: v for k, v in get_cells(conn, keys).items() if v["status"] == "DONE" and v["study_id"] == study_id}


def upsert_cell(conn: Connection, values: dict[str, Any]) -> None:
    """셀 행 삽입(이미 있으면 새 결과로 덮어씀 — EXPIRED 되살림·동시 생성 경합)."""
    stmt = pg_insert(doe_preview_cells).values(**values)
    upd = {k: stmt.excluded[k] for k in values if k not in ("cache_key", "created_at")}
    upd["last_access_at"] = func.now()
    conn.execute(stmt.on_conflict_do_update(index_elements=[doe_preview_cells.c.cache_key], set_=upd))


def touch_cells(conn: Connection, keys: list[str]) -> None:
    if keys:
        conn.execute(update(doe_preview_cells).where(doe_preview_cells.c.cache_key.in_(keys)).values(last_access_at=func.now()))


def set_cell(conn: Connection, key: str, **vals: Any) -> None:
    conn.execute(update(doe_preview_cells).where(doe_preview_cells.c.cache_key == key).values(**vals))


def purge_cell_candidates(conn: Connection, *, older_than_days: float) -> list[dict[str, Any]]:
    """보관 기간 초과(마지막 접근 기준) DONE 셀(§6.3)."""
    cut = datetime.now(timezone.utc) - timedelta(days=float(older_than_days))
    q = select(doe_preview_cells).where(and_(doe_preview_cells.c.status == "DONE", doe_preview_cells.c.last_access_at < cut)) \
        .order_by(doe_preview_cells.c.last_access_at)
    return [row_dict(r) for r in conn.execute(q)]


def lru_cells(conn: Connection) -> list[dict[str, Any]]:
    """총량 정리 후보: DONE 셀, 마지막 접근 오래된 순."""
    q = select(doe_preview_cells).where(doe_preview_cells.c.status == "DONE").order_by(doe_preview_cells.c.last_access_at)
    return [row_dict(r) for r in conn.execute(q)]


def active_job_ids(conn: Connection) -> set[str]:
    """QUEUED·RUNNING 미리보기의 작업 id — `jobs/<job_id>/` 폴더는 정리하지 않는다."""
    return {r.job_id for r in conn.execute(select(doe_previews.c.job_id).where(and_(doe_previews.c.status.in_(ACTIVE),
                                                                                    doe_previews.c.job_id.is_not(None))))}
