"""Alembic 환경. URL 우선순위: config.attributes['url'] > -x url=... > PHYSICSAI_DATABASE_URL."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from physicsai_core.db.engine import normalize_url  # noqa: E402
from physicsai_core.db.tables import metadata  # noqa: E402

config = context.config
target_metadata = metadata


def _url() -> str:
    url = config.attributes.get("url") or context.get_x_argument(as_dictionary=True).get("url") or os.environ.get(
        "PHYSICSAI_DATABASE_URL", ""
    )
    if not url:
        raise RuntimeError("PHYSICSAI_DATABASE_URL이 설정되지 않았습니다")
    return normalize_url(url)


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
        return
    engine = create_engine(_url())
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
