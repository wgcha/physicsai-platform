"""0011_surrogate_final — ⑤ 내장 최적화 마무리 캡처(phase3 D3-61). 명시적 DDL(B14).

- surrogate_opts: 열 `final`(JSONB NULL — 마무리 캡처 배치·상태·범례·완료 알림 문구), 상태 `FINALIZING` 추가,
  진행 중 부분 유일 인덱스에 FINALIZING 포함
- surrogate_opt_iters.kind에 `FINAL`(기준안·최적안 2행 캡처 배치) 추가

Revision ID: 0011_surrogate_final
Revises: 0010_surrogate_opt
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0011_surrogate_final"
down_revision = "0010_surrogate_opt"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("surrogate_opts", sa.Column("final", JSONB(), nullable=True))
    op.drop_constraint("ck_surrogate_opts_status", "surrogate_opts", type_="check")
    op.create_check_constraint(
        "ck_surrogate_opts_status", "surrogate_opts",
        "status IN ('EXPLORING','FITTING','VERIFYING','FINALIZING','DONE','FAILED','CANCELED')")
    op.drop_index("ux_surrogate_opts_active", table_name="surrogate_opts")
    op.create_index("ux_surrogate_opts_active", "surrogate_opts", ["study_id"], unique=True,
                    postgresql_where=sa.text("status IN ('EXPLORING','FITTING','VERIFYING','FINALIZING')"))
    op.drop_constraint("ck_surrogate_opt_iters_kind", "surrogate_opt_iters", type_="check")
    op.create_check_constraint("ck_surrogate_opt_iters_kind", "surrogate_opt_iters",
                               "kind IN ('EXPLORE','REUSE','VERIFY','FINAL')")


def downgrade() -> None:
    raise RuntimeError("PhysicsAI migration은 downgrade를 지원하지 않습니다(데이터 보호)")
