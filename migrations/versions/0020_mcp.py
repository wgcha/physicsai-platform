"""0020_mcp — MCP 기능(mcp.md §14). 명시적 DDL(B14).

- 새 테이블 api_tokens(해시·접두·역할 스냅숏만, 평문 없음)·mcp_plans(confirm 해시·params 해시)·api_audit(토큰 요청 감사, 본문 없음)
- jobs.api_token_id(nullable, FK 없음 — 토큰 요청으로 만든 작업)
- 다운그레이드: 세 테이블에 행이 하나라도 있거나 api_token_id가 채워진 작업이 있으면 거부(데이터 보호, 0017·0018·0019 선례), 없으면 되돌림

Revision ID: 0020_mcp
Revises: 0019_extract_filter
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP

revision = "0020_mcp"
down_revision = "0019_extract_filter"
branch_labels = None
depends_on = None

TS = TIMESTAMP(timezone=True)
ID = sa.String(36)


def upgrade() -> None:
    op.create_table(
        "api_tokens",
        sa.Column("id", ID, primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("username", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("scope", sa.String(8), nullable=False),
        sa.Column("token_prefix", sa.String(16), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("principal_snapshot", JSONB(), nullable=False),
        sa.Column("snapshot_at", TS, nullable=False),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", TS, nullable=False),
        sa.Column("last_used_at", TS, nullable=True),
        sa.Column("last_used_ip", sa.String(), nullable=True),
        sa.Column("revoked_at", TS, nullable=True),
        sa.Column("revoked_by", sa.String(), nullable=True),
        sa.CheckConstraint("scope IN ('read','run','admin')", name="ck_api_tokens_scope"),
    )
    op.create_index("ix_api_tokens_user_revoked", "api_tokens", ["user_id", "revoked_at"])
    op.create_index("ux_api_tokens_user_name_active", "api_tokens", ["user_id", "name"], unique=True,
                    postgresql_where=sa.text("revoked_at IS NULL"))
    op.create_table(
        "mcp_plans",
        sa.Column("id", ID, primary_key=True),
        sa.Column("api_token_id", ID, nullable=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("kind_version", sa.Integer(), nullable=False),
        sa.Column("study_id", ID, nullable=False),
        sa.Column("params_sha256", sa.String(64), nullable=False),
        sa.Column("confirm_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("summary", JSONB(), nullable=False),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", TS, nullable=False),
        sa.Column("used_at", TS, nullable=True),
        sa.Column("used_job_id", ID, nullable=True),
    )
    op.create_index("ix_mcp_plans_expires", "mcp_plans", ["expires_at"])
    op.create_table(
        "api_audit",
        sa.Column("id", ID, primary_key=True),
        sa.Column("occurred_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("user_id", sa.String(), nullable=True),
        sa.Column("username", sa.String(), nullable=True),
        sa.Column("api_token_id", ID, nullable=True),
        sa.Column("token_prefix", sa.String(16), nullable=True),
        sa.Column("operation_id", sa.String(), nullable=True),
        sa.Column("tool", sa.String(64), nullable=True),
        sa.Column("method", sa.String(8), nullable=False),
        sa.Column("route", sa.String(), nullable=True),
        sa.Column("target_type", sa.String(32), nullable=True),
        sa.Column("target_id", sa.String(), nullable=True),
        sa.Column("study_id", ID, nullable=True),
        sa.Column("kind", sa.String(64), nullable=True),
        sa.Column("job_id", ID, nullable=True),
        sa.Column("plan_id", ID, nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("result_code", sa.String(64), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("request_id", sa.String(), nullable=True),
        sa.Column("client_ip", sa.String(), nullable=True),
        sa.Column("params_sha256", sa.String(64), nullable=True),
    )
    op.create_index("ix_api_audit_occurred", "api_audit", ["occurred_at"])
    op.create_index("ix_api_audit_token_occurred", "api_audit", ["api_token_id", "occurred_at"])
    op.create_index("ix_api_audit_user_occurred", "api_audit", ["user_id", "occurred_at"])
    op.add_column("jobs", sa.Column("api_token_id", ID, nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT (SELECT count(*) FROM api_tokens) + (SELECT count(*) FROM mcp_plans)"
                                " + (SELECT count(*) FROM api_audit)")).scalar()
    jobs = bind.execute(sa.text("SELECT count(*) FROM jobs WHERE api_token_id IS NOT NULL")).scalar()
    if rows or jobs:
        raise RuntimeError(f"API 토큰·계획·감사 {rows}행·토큰 작업 {jobs}개가 있어 0020을 되돌릴 수 없습니다(데이터 보호)")
    op.drop_column("jobs", "api_token_id")
    op.drop_table("api_audit")
    op.drop_table("mcp_plans")
    op.drop_table("api_tokens")
