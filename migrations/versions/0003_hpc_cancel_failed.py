"""0003_hpc_cancel_failed — 알림 이벤트 HPC_CANCEL_FAILED 추가(phase2 변경 메모 C18). 명시적 DDL(B14).

Revision ID: 0003_hpc_cancel_failed
Revises: 0002_phase2
"""

from __future__ import annotations

from alembic import op

revision = "0003_hpc_cancel_failed"
down_revision = "0002_phase2"
branch_labels = None
depends_on = None

NOTIFICATION_EVENTS = (
    "'JOB_STARTED','JOB_SUCCEEDED','JOB_FAILED','JOB_CANCELED','JOB_INTERRUPTED','MY_TURN_NEXT','HPC_COLLECTED',"
    "'HPC_PARTIAL_FAILED','ENV_CHECK_DONE','HPC_CANCEL_FAILED'"
)


def upgrade() -> None:
    op.drop_constraint("ck_notifications_event", "notifications", type_="check")
    op.create_check_constraint("ck_notifications_event", "notifications", f"event IN ({NOTIFICATION_EVENTS})")


def downgrade() -> None:
    raise RuntimeError("PhysicsAI migration은 downgrade를 지원하지 않습니다(데이터 보호)")
