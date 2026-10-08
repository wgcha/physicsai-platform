"""② SPDM 가져오기 저장소(phase2 §5.5)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, select, update
from sqlalchemy.engine import Connection

from ..tables import spdm_imports
from .jobs import row_dict

# ---- spdm_imports ---------------------------------------------------------------


def insert_import(conn: Connection, values: dict[str, Any]) -> None:
    conn.execute(spdm_imports.insert().values(**values))


def get_import(conn: Connection, iid: str) -> dict[str, Any] | None:
    return row_dict(conn.execute(select(spdm_imports).where(spdm_imports.c.id == iid)).first())


def list_imports(conn: Connection, study_id: str) -> list[dict[str, Any]]:
    q = select(spdm_imports).where(spdm_imports.c.study_id == study_id).order_by(spdm_imports.c.created_at.desc(), spdm_imports.c.id)
    return [row_dict(r) for r in conn.execute(q)]


def set_import(conn: Connection, iid: str, **values: Any) -> None:
    conn.execute(update(spdm_imports).where(spdm_imports.c.id == iid).values(**values))


def fail_building_import(conn: Connection, job_id: str) -> None:
    conn.execute(update(spdm_imports).where(and_(spdm_imports.c.job_id == job_id, spdm_imports.c.status == "BUILDING")).values(status="FAILED"))
