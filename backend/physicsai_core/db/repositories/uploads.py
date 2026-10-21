"""업로드 세션 저장소(upload-report.md §6.2). 경로는 AI 루트 기준 상대·상태·수치 요약만(파일 본문 없음)."""

from __future__ import annotations

import datetime as _dt
import uuid
from typing import Any

from sqlalchemy import and_, func, insert, select, update
from sqlalchemy.engine import Connection

from ..tables import uploads
from .jobs import row_dict

OPEN, COMPLETED, CANCELED, STALE = "OPEN", "COMPLETED", "CANCELED", "STALE"


def get(conn: Connection, upload_id: str, *, for_update: bool = False) -> dict[str, Any] | None:
    q = select(uploads).where(uploads.c.id == upload_id)
    if for_update:
        q = q.with_for_update()
    return row_dict(conn.execute(q).first())


def insert_row(conn: Connection, **values: Any) -> dict[str, Any]:
    uid = values.pop("id", None) or str(uuid.uuid4())
    conn.execute(insert(uploads).values(id=uid, **values))
    return get(conn, uid)  # type: ignore[return-value]


def update_row(conn: Connection, upload_id: str, **values: Any) -> dict[str, Any]:
    values.setdefault("updated_at", func.now())
    conn.execute(update(uploads).where(uploads.c.id == upload_id).values(**values))
    return get(conn, upload_id)  # type: ignore[return-value]


def lock_user(conn: Connection, user_id: str) -> None:
    """사용자당 OPEN 세션 수 검사를 직렬화(같은 트랜잭션에서 세고 넣는다)."""
    conn.execute(select(func.pg_advisory_xact_lock(func.hashtext("pai-upload:" + user_id))))


def count_open(conn: Connection, user_id: str) -> int:
    return conn.execute(select(func.count()).select_from(uploads).where(
        and_(uploads.c.user_id == user_id, uploads.c.state == OPEN))).scalar_one()


def open_rows(conn: Connection, *, exclude_id: str | None = None) -> list[dict[str, Any]]:
    """진행 중(OPEN) 세션 — 디스크 예약 합계용(남은 바이트)."""
    q = select(uploads.c.id, uploads.c.dir_rel, uploads.c.files).where(uploads.c.state == OPEN)
    if exclude_id:
        q = q.where(uploads.c.id != exclude_id)
    return [row_dict(r) for r in conn.execute(q)]


def list_for_study(conn: Connection, study_id: str, *, user_id: str | None, state: str | None,
                   limit: int = 50) -> list[dict[str, Any]]:
    q = select(uploads).where(uploads.c.study_id == study_id)
    if user_id is not None:
        q = q.where(uploads.c.user_id == user_id)
    if state:
        q = q.where(uploads.c.state == state)
    return [row_dict(r) for r in conn.execute(q.order_by(uploads.c.created_at.desc()).limit(limit))]


def db_now(conn: Connection) -> _dt.datetime:
    return conn.execute(select(func.now())).scalar_one()


def stale_ids(conn: Connection, cutoff: _dt.datetime) -> list[str]:
    return [r[0] for r in conn.execute(select(uploads.c.id).where(
        and_(uploads.c.state == OPEN, uploads.c.updated_at < cutoff)))]
