"""0009_scx_gateway — SCX 잡 제출(phase3 §16.9, D3-57). 명시적 DDL(B14).

- hpc_jobs 열 9개: remote_dir·request_id(부분 유일 WHERE request_id IS NOT NULL)·staged·output_path·output_rel·
  submission_unknown(NOT NULL DEFAULT false)·resolve_request·resolved_by·resolved_at. 상태 CHECK는 그대로(UNKNOWN 이미 있음).
- notifications.event CHECK에 HPC_SUBMISSION_UNKNOWN 추가.

Revision ID: 0009_scx_gateway
Revises: 0008_contour_capture
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP

revision = "0009_scx_gateway"
down_revision = "0008_contour_capture"
branch_labels = None
depends_on = None

NOTIFICATION_EVENTS = (
    "'JOB_STARTED','JOB_SUCCEEDED','JOB_FAILED','JOB_CANCELED','JOB_INTERRUPTED','MY_TURN_NEXT','HPC_COLLECTED',"
    "'HPC_PARTIAL_FAILED','ENV_CHECK_DONE','HPC_CANCEL_FAILED','PREDICT_BATCH_DONE','HPC_SUBMISSION_UNKNOWN'"
)


def upgrade() -> None:
    op.add_column("hpc_jobs", sa.Column("remote_dir", sa.String(1024), nullable=True))
    op.add_column("hpc_jobs", sa.Column("request_id", sa.String(128), nullable=True))
    op.add_column("hpc_jobs", sa.Column("staged", JSONB(), nullable=True))
    op.add_column("hpc_jobs", sa.Column("output_path", sa.String(1024), nullable=True))
    op.add_column("hpc_jobs", sa.Column("output_rel", sa.String(1024), nullable=True))
    op.add_column("hpc_jobs", sa.Column("submission_unknown", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("hpc_jobs", sa.Column("resolve_request", JSONB(), nullable=True))
    op.add_column("hpc_jobs", sa.Column("resolved_by", sa.String(), nullable=True))
    op.add_column("hpc_jobs", sa.Column("resolved_at", TIMESTAMP(timezone=True), nullable=True))
    op.create_index("ux_hpc_jobs_request_id", "hpc_jobs", ["request_id"], unique=True,
                    postgresql_where=sa.text("request_id IS NOT NULL"))
    op.drop_constraint("ck_notifications_event", "notifications", type_="check")
    op.create_check_constraint("ck_notifications_event", "notifications", f"event IN ({NOTIFICATION_EVENTS})")


def downgrade() -> None:
    raise RuntimeError("PhysicsAI migration은 downgrade를 지원하지 않습니다(데이터 보호)")
