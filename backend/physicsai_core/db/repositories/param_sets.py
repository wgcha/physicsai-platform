"""파라미터 세트 저장소(§6.5)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, select, update
from sqlalchemy.engine import Connection

from ..tables import param_sets
from .jobs import row_dict


def get(conn: Connection, ps_id: str) -> dict[str, Any] | None:
    return row_dict(conn.execute(select(param_sets).where(param_sets.c.id == ps_id)).first())


def current(conn: Connection, study_id: str) -> dict[str, Any] | None:
    q = select(param_sets).where(and_(param_sets.c.study_id == study_id, param_sets.c.is_current.is_(True)))
    return row_dict(conn.execute(q).first())


def list_for_study(conn: Connection, study_id: str, limit: int = 200, offset: int = 0) -> list[dict[str, Any]]:
    q = (
        select(param_sets)
        .where(param_sets.c.study_id == study_id)
        .order_by(param_sets.c.registered_at.desc(), param_sets.c.id)
        .limit(limit)
        .offset(offset)
    )
    return [row_dict(r) for r in conn.execute(q)]


def insert_current(conn: Connection, values: dict[str, Any]) -> None:
    conn.execute(
        update(param_sets).where(and_(param_sets.c.study_id == values["study_id"], param_sets.c.is_current.is_(True))).values(is_current=False)
    )
    conn.execute(param_sets.insert().values(is_current=True, **values))


def set_label(conn: Connection, ps_id: str, label: str | None) -> None:
    conn.execute(update(param_sets).where(param_sets.c.id == ps_id).values(label=label))


def set_responses(conn: Connection, ps_id: str, responses: list[dict[str, Any]]) -> None:
    """응답 정의 바꾸기(phase3 §14.6 S9) — `[{name, unit, spec|None}]`."""
    conn.execute(update(param_sets).where(param_sets.c.id == ps_id).values(responses=responses))


def set_values(conn: Connection, ps_id: str, **values: Any) -> None:
    """native 형상 엔진 필드(geom_options·engine_version 등) 갱신(geometry-engine.md §7.4)."""
    conn.execute(update(param_sets).where(param_sets.c.id == ps_id).values(**values))
