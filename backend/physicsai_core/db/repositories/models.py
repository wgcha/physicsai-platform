"""모델 저장소(§6.4)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, func, select, update
from sqlalchemy.engine import Connection

from ...errors import DomainError
from ..tables import models
from .jobs import row_dict


def get(conn: Connection, model_id: str, *, for_update: bool = False) -> dict[str, Any] | None:
    q = select(models).where(models.c.id == model_id)
    if for_update:
        q = q.with_for_update()
    return row_dict(conn.execute(q).first())


def require(conn: Connection, model_id: str, *, for_update: bool = False) -> dict[str, Any]:
    m = get(conn, model_id, for_update=for_update)
    if m is None:
        raise DomainError("NOT_FOUND", "모델을 찾을 수 없습니다", status=404)
    return m


def list_for_study(conn: Connection, study_id: str, status: str | None = None, limit: int = 200, offset: int = 0) -> list[dict[str, Any]]:
    q = select(models).where(models.c.study_id == study_id)
    if status:
        q = q.where(models.c.status == status)
    q = q.order_by(models.c.registered_at.desc(), models.c.id).limit(limit).offset(offset)
    return [row_dict(r) for r in conn.execute(q)]


def next_version(conn: Connection, study_id: str, name: str) -> int:
    v = conn.execute(
        select(func.coalesce(func.max(models.c.version), 0)).where(and_(models.c.study_id == study_id, models.c.name == name))
    ).scalar_one()
    return int(v) + 1


def insert(conn: Connection, values: dict[str, Any]) -> None:
    conn.execute(models.insert().values(**values))


def set_values(conn: Connection, model_id: str, **values: Any) -> None:
    conn.execute(update(models).where(models.c.id == model_id).values(row_version=models.c.row_version + 1, **values))


def update_cas(conn: Connection, model_id: str, row_version: int, **values: Any) -> dict[str, Any]:
    r = conn.execute(
        update(models)
        .where(and_(models.c.id == model_id, models.c.row_version == row_version))
        .values(row_version=models.c.row_version + 1, **values)
    )
    if r.rowcount != 1:
        raise DomainError("VERSION_CONFLICT", "다른 사용자가 먼저 수정했습니다. 새로 고친 뒤 다시 시도하세요", status=409)
    return require(conn, model_id)
