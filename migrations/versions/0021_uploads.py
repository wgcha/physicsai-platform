"""0021_uploads — 브라우저 분할 업로드 세션(upload-report.md §6.2). 명시적 DDL(B14).

- 새 테이블 uploads(경로는 AI 루트 기준 상대, 파일별 진행·검사 요약만 — 파일 본문 없음)
- 다운그레이드: 행이 하나라도 있으면 거부(업로드 폴더·입력 원본 보호, 0017·0018·0019·0020 선례), 없으면 되돌림

Revision ID: 0021_uploads
Revises: 0020_mcp
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP

revision = "0021_uploads"
down_revision = "0020_mcp"
branch_labels = None
depends_on = None

TS = TIMESTAMP(timezone=True)
ID = sa.String(36)


def upgrade() -> None:
    op.create_table(
        "uploads",
        sa.Column("id", ID, primary_key=True),
        sa.Column("study_id", ID, sa.ForeignKey("studies.id"), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("username", sa.String(), nullable=False),
        sa.Column("purpose", sa.String(), nullable=False),
        sa.Column("engine", sa.String(), nullable=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("dir_rel", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False, server_default="OPEN"),
        sa.Column("files", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("total_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("inspect", JSONB(), nullable=True),
        sa.Column("backup_rel", sa.String(), nullable=True),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", TS, nullable=True),
        sa.CheckConstraint("state IN ('OPEN','COMPLETED','CANCELED','STALE')", name="ck_uploads_state"),
        sa.CheckConstraint("total_bytes >= 0", name="ck_uploads_total_bytes"),
        sa.CheckConstraint("jsonb_typeof(files) = 'array'", name="ck_uploads_files_array"),
    )
    op.create_index("ix_uploads_user_state", "uploads", ["user_id", "state"])
    op.create_index("ix_uploads_state_updated", "uploads", ["state", "updated_at"])
    op.create_index("ix_uploads_study_created", "uploads", ["study_id", sa.text("created_at DESC")])


def downgrade() -> None:
    n = op.get_bind().execute(sa.text("SELECT count(*) FROM uploads")).scalar()
    if n:
        raise RuntimeError(f"업로드 세션 {n}행이 있어 0021을 되돌릴 수 없습니다(입력 원본 보호)")
    op.drop_table("uploads")
