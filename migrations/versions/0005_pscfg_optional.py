"""0005_pscfg_optional — models.pscfg_rel·pscfg_sha256 NULL 허용(phase3 D3-43, 사용자 결정 2026-10-16·U7). 명시적 DDL(B14).

기존 행은 그대로(값 보존). NOT NULL만 푼다.

Revision ID: 0005_pscfg_optional
Revises: 0004_study_manage
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_pscfg_optional"
down_revision = "0004_study_manage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("models", "pscfg_rel", existing_type=sa.String(), nullable=True)
    op.alter_column("models", "pscfg_sha256", existing_type=sa.String(64), nullable=True)


def downgrade() -> None:
    raise RuntimeError("PhysicsAI migration은 downgrade를 지원하지 않습니다(데이터 보호)")
