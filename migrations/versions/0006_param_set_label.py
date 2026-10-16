"""0006_param_set_label — param_sets.label(사용자 표시 이름, 예 "쿠션 v1") 추가(phase3 §13 S8). 명시적 DDL(B14).

기존 행은 NULL(화면은 출처 경로를 대신 표시). models.label과 같은 형식(String(120), NULL 허용).

Revision ID: 0006_param_set_label
Revises: 0005_pscfg_optional
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006_param_set_label"
down_revision = "0005_pscfg_optional"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("param_sets", sa.Column("label", sa.String(120), nullable=True))


def downgrade() -> None:
    raise RuntimeError("PhysicsAI migration은 downgrade를 지원하지 않습니다(데이터 보호)")
