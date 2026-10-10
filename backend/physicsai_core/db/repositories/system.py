"""DB 상태 확인(phase2 §9.2 환경 점검): 연결 확인과 적용된 migration 버전."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection


def ping(conn: Connection) -> None:
    conn.execute(text("select 1"))


def migration_version(conn: Connection) -> Any:
    """alembic_version.version_num(없으면 None)."""
    return conn.execute(text("select version_num from alembic_version")).scalar()
