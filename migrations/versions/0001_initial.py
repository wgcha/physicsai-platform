"""0001_initial — 1차 전체 스키마(계약 §6 + audit_events + worker_slot 초기 행 + 시퀀스 job_queue_seq).

Revision ID: 0001_initial
Revises:
"""

from __future__ import annotations

from alembic import op

from physicsai_core.db.tables import metadata, worker_slot

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    # 0001은 physicsai_core.db.tables의 1차 스키마를 그대로 만든다.
    # 이후 스키마 변경은 tables.py 수정과 함께 0002 이후 migration에 명시적 DDL로 적는다.
    metadata.create_all(bind)
    op.execute(worker_slot.insert().values(id=1, lease_generation=0))


def downgrade() -> None:
    raise RuntimeError("PhysicsAI migration은 downgrade를 지원하지 않습니다(데이터 보호)")
