"""0015_doe_platform_gen — ① 학습 DOE 플랫폼 동시 생성(phase3 §23.7 S18, D3-66). 명시적 DDL(B14).

- train_does: 열 `generator VARCHAR(16) NOT NULL DEFAULT 'HYPERSTUDY'` + CHECK(`HYPERSTUDY`,`PLATFORM`), `sampling JSONB NULL`
  (기존 행 = HYPERSTUDY·NULL)
- 새 train_doe_points: run별 표본 값·생성 상태(수치·상태만). PK(doe_id, doe_no), UNIQUE(doe_id, run_key), INDEX(doe_id, gen_state)
- downgrade: PLATFORM 행이 있으면 실패(데이터 보존), 없으면 테이블·열을 지운다.

Revision ID: 0015_doe_platform_gen
Revises: 0014_multiobj (S17)
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP

revision = "0015_doe_platform_gen"
down_revision = "0014_multiobj"
branch_labels = None
depends_on = None

TS = TIMESTAMP(timezone=True)
ID = sa.String(36)


def upgrade() -> None:
    op.add_column("train_does", sa.Column("generator", sa.String(16), nullable=False, server_default="HYPERSTUDY"))
    op.create_check_constraint("ck_train_does_generator", "train_does", "generator IN ('HYPERSTUDY','PLATFORM')")
    op.add_column("train_does", sa.Column("sampling", JSONB(), nullable=True))
    op.create_table(
        "train_doe_points",
        sa.Column("doe_id", ID, sa.ForeignKey("train_does.id"), nullable=False),
        sa.Column("doe_no", sa.Integer(), nullable=False),
        sa.Column("run_key", sa.String(64), nullable=False),
        sa.Column("values", JSONB(), nullable=False),
        sa.Column("applied_values", JSONB(), nullable=False),
        sa.Column("gen_state", sa.String(16), nullable=False, server_default="PENDING"),
        sa.Column("gen_code", sa.String(64), nullable=True),
        sa.Column("gen_message", sa.String(480), nullable=True),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("doe_id", "doe_no", name="pk_train_doe_points"),
        sa.UniqueConstraint("doe_id", "run_key", name="uq_train_doe_points_run"),
        sa.CheckConstraint("gen_state IN ('PENDING','RUNNING','DONE','FAILED')", name="ck_train_doe_points_gen_state"),
    )
    op.create_index("ix_train_doe_points_state", "train_doe_points", ["doe_id", "gen_state"])


def downgrade() -> None:
    n = op.get_bind().execute(sa.text("SELECT count(*) FROM train_does WHERE generator = 'PLATFORM'")).scalar()
    if n:
        raise RuntimeError(f"플랫폼 생성 DOE {n}개가 있어 0015를 되돌릴 수 없습니다(데이터 보호)")
    op.drop_index("ix_train_doe_points_state", table_name="train_doe_points")
    op.drop_table("train_doe_points")
    op.drop_column("train_does", "sampling")
    op.drop_constraint("ck_train_does_generator", "train_does", type_="check")
    op.drop_column("train_does", "generator")
