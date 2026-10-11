"""0004_study_manage — jobs.stage 0 허용(Study 관리 작업, phase3 §5.10 R3-1). 명시적 DDL(B14).

Revision ID: 0004_study_manage
Revises: 0003_hpc_cancel_failed
"""

from __future__ import annotations

from alembic import op

revision = "0004_study_manage"
down_revision = "0003_hpc_cancel_failed"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_jobs_stage", "jobs", type_="check")
    op.create_check_constraint("ck_jobs_stage", "jobs", "stage BETWEEN 0 AND 5")


def downgrade() -> None:
    raise RuntimeError("PhysicsAI migration은 downgrade를 지원하지 않습니다(데이터 보호)")
