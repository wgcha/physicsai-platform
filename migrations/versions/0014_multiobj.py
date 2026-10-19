"""0014_multiobj — ⑥ 내장 최적화 다목적·추가 검증(phase3 §22.8 S17, D3-65). 명시적 DDL(B14).

- surrogate_opt_iters: kind CHECK에 `EXTRA`(최적화 소유 추가 검증 배치) 추가, 열 `hv FLOAT NULL`·`front_size INTEGER NULL`·
  `predicted_front JSONB NULL`(수치만, ≤ 28점)
- surrogate_opts: 열 `hv_frame JSONB NULL`(HV 정규화 틀 {ideal, nadir, ref_offset, signs})
- 기존 행은 바꾸지 않는다(단일 목적 = NULL). job_type `PB_RESP_EXTRACT`는 코드만(jobs에 job_type CHECK 없음).
- downgrade: EXTRA 행이 있으면 실패(데이터 보존), 없으면 열·CHECK를 되돌린다.

Revision ID: 0014_multiobj
Revises: 0013_fem_verify (S16)
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0014_multiobj"
down_revision = "0013_fem_verify"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_surrogate_opt_iters_kind", "surrogate_opt_iters", type_="check")
    op.create_check_constraint("ck_surrogate_opt_iters_kind", "surrogate_opt_iters",
                               "kind IN ('EXPLORE','REUSE','VERIFY','FINAL','EXTRA')")
    op.add_column("surrogate_opt_iters", sa.Column("hv", sa.Float(), nullable=True))
    op.add_column("surrogate_opt_iters", sa.Column("front_size", sa.Integer(), nullable=True))
    op.add_column("surrogate_opt_iters", sa.Column("predicted_front", JSONB(), nullable=True))
    op.add_column("surrogate_opts", sa.Column("hv_frame", JSONB(), nullable=True))


def downgrade() -> None:
    n = op.get_bind().execute(sa.text("SELECT count(*) FROM surrogate_opt_iters WHERE kind = 'EXTRA'")).scalar()
    if n:
        raise RuntimeError(f"추가 검증(EXTRA) 반복 행 {n}개가 있어 0014를 되돌릴 수 없습니다(데이터 보호)")
    op.drop_column("surrogate_opts", "hv_frame")
    op.drop_column("surrogate_opt_iters", "predicted_front")
    op.drop_column("surrogate_opt_iters", "front_size")
    op.drop_column("surrogate_opt_iters", "hv")
    op.drop_constraint("ck_surrogate_opt_iters_kind", "surrogate_opt_iters", type_="check")
    op.create_check_constraint("ck_surrogate_opt_iters_kind", "surrogate_opt_iters",
                               "kind IN ('EXPLORE','REUSE','VERIFY','FINAL')")
