"""MCP 테이블(mcp.md §14, migration 0020_mcp): API 토큰·확인 계획·토큰 요청 감사.

본문 저장 금지: 토큰 원문·confirm_token 원문·요청/응답 본문·파라미터 값은 어떤 열에도 넣지 않는다(해시·수치 요약만).
"""

from __future__ import annotations

from sqlalchemy import CheckConstraint, Column, Index, Integer, String, Table, func, text
from sqlalchemy.dialects.postgresql import JSONB

from ._base import ID, TS, metadata

api_tokens = Table(
    "api_tokens",
    metadata,
    Column("id", ID, primary_key=True),
    Column("user_id", String, nullable=False),
    Column("username", String, nullable=False),
    Column("display_name", String, nullable=False),
    Column("name", String(64), nullable=False),
    Column("scope", String(8), nullable=False),
    Column("token_prefix", String(16), nullable=False),
    Column("token_hash", String(64), nullable=False, unique=True),
    Column("principal_snapshot", JSONB, nullable=False),
    Column("snapshot_at", TS, nullable=False),
    Column("created_at", TS, nullable=False, server_default=func.now()),
    Column("expires_at", TS, nullable=False),
    Column("last_used_at", TS, nullable=True),
    Column("last_used_ip", String, nullable=True),
    Column("revoked_at", TS, nullable=True),
    Column("revoked_by", String, nullable=True),
    CheckConstraint("scope IN ('read','run','admin')", name="ck_api_tokens_scope"),
)
Index("ix_api_tokens_user_revoked", api_tokens.c.user_id, api_tokens.c.revoked_at)
Index("ux_api_tokens_user_name_active", api_tokens.c.user_id, api_tokens.c.name, unique=True,
      postgresql_where=text("revoked_at IS NULL"))

mcp_plans = Table(
    "mcp_plans",
    metadata,
    Column("id", ID, primary_key=True),
    Column("api_token_id", ID, nullable=True),
    Column("user_id", String, nullable=False),
    Column("kind", String(64), nullable=False),
    Column("kind_version", Integer, nullable=False),
    Column("study_id", ID, nullable=False),
    Column("params_sha256", String(64), nullable=False),
    Column("confirm_hash", String(64), nullable=False, unique=True),
    Column("summary", JSONB, nullable=False),
    Column("created_at", TS, nullable=False, server_default=func.now()),
    Column("expires_at", TS, nullable=False),
    Column("used_at", TS, nullable=True),
    Column("used_job_id", ID, nullable=True),
)
Index("ix_mcp_plans_expires", mcp_plans.c.expires_at)

api_audit = Table(
    "api_audit",
    metadata,
    Column("id", ID, primary_key=True),
    Column("occurred_at", TS, nullable=False, server_default=func.now()),
    Column("user_id", String, nullable=True),
    Column("username", String, nullable=True),
    Column("api_token_id", ID, nullable=True),
    Column("token_prefix", String(16), nullable=True),
    Column("operation_id", String, nullable=True),
    Column("tool", String(64), nullable=True),
    Column("method", String(8), nullable=False),
    Column("route", String, nullable=True),
    Column("target_type", String(32), nullable=True),
    Column("target_id", String, nullable=True),
    Column("study_id", ID, nullable=True),
    Column("kind", String(64), nullable=True),
    Column("job_id", ID, nullable=True),
    Column("plan_id", ID, nullable=True),
    Column("status_code", Integer, nullable=False),
    Column("result_code", String(64), nullable=True),
    Column("duration_ms", Integer, nullable=True),
    Column("request_id", String, nullable=True),
    Column("client_ip", String, nullable=True),
    Column("params_sha256", String(64), nullable=True),
)
Index("ix_api_audit_occurred", api_audit.c.occurred_at)
Index("ix_api_audit_token_occurred", api_audit.c.api_token_id, api_audit.c.occurred_at)
Index("ix_api_audit_user_occurred", api_audit.c.user_id, api_audit.c.occurred_at)
