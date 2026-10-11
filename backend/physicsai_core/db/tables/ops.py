"""운영 테이블: env_checks(phase2 §5.7)·audit_events(계약 §6)."""

from __future__ import annotations

from sqlalchemy import CheckConstraint, Column, Index, String, Table, func, text
from sqlalchemy.dialects.postgresql import JSONB

from ._base import ID, TS, metadata

env_checks = Table(
    "env_checks",
    metadata,
    Column("id", ID, primary_key=True),
    Column("state", String, nullable=False, server_default="PENDING"),
    Column("requested_by", String, nullable=False),
    Column("requested_by_name", String, nullable=False),
    Column("created_at", TS, nullable=False, server_default=func.now()),
    Column("expires_at", TS, nullable=False),
    Column("worker_id", String, nullable=True),
    Column("started_at", TS, nullable=True),
    Column("finished_at", TS, nullable=True),
    Column("api_items", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("worker_items", JSONB, nullable=True),
    Column("summary", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("report_rel", String, nullable=True),
    Column("failure_message", String(500), nullable=True),
    CheckConstraint("state IN ('PENDING','RUNNING','DONE','FAILED','EXPIRED')", name="ck_env_checks_state"),
    # 동시 1건(phase2 §5.7): 위반 시 409 ENV_CHECK_BUSY
    Index("ux_env_checks_active", text("(true)"), unique=True, postgresql_where=text("state IN ('PENDING','RUNNING')")),
)
Index("ix_env_checks_created", env_checks.c.created_at.desc())

audit_events = Table(
    "audit_events",
    metadata,
    Column("id", ID, primary_key=True),
    Column("occurred_at", TS, nullable=False, server_default=func.now()),
    Column("user_id", String, nullable=False),
    Column("username", String, nullable=True),
    Column("action", String, nullable=False),
    Column("target_type", String, nullable=False),
    Column("target_id", String, nullable=True),
    Column("detail", JSONB, nullable=True),
    Column("request_id", String, nullable=True),
    Column("client_ip", String, nullable=True),
)
