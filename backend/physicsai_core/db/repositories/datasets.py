"""데이터셋 저장소(§6.3)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, select, update
from sqlalchemy.engine import Connection

from ..tables import datasets
from .jobs import row_dict


def get(conn: Connection, dataset_id: str) -> dict[str, Any] | None:
    return row_dict(conn.execute(select(datasets).where(datasets.c.id == dataset_id)).first())


def list_for_study(conn: Connection, study_id: str, limit: int = 200, offset: int = 0) -> list[dict[str, Any]]:
    q = (
        select(datasets)
        .where(datasets.c.study_id == study_id)
        .order_by(datasets.c.created_at.desc(), datasets.c.id)
        .limit(limit)
        .offset(offset)
    )
    return [row_dict(r) for r in conn.execute(q)]


def latest_ready(conn: Connection, study_id: str) -> dict[str, Any] | None:
    q = (
        select(datasets)
        .where(and_(datasets.c.study_id == study_id, datasets.c.status == "READY"))
        .order_by(datasets.c.created_at.desc())
        .limit(1)
    )
    return row_dict(conn.execute(q).first())


def insert(conn: Connection, values: dict[str, Any]) -> None:
    conn.execute(datasets.insert().values(**values))


def set_values(conn: Connection, dataset_id: str, **values: Any) -> None:
    conn.execute(update(datasets).where(datasets.c.id == dataset_id).values(**values))
