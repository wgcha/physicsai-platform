"""0019_extract_filter — native ①-1 추출 조건 기록(extract-filter.md §6.4). 명시적 DDL(B14).

- train_setups.extract_filter JSONB NULL: 마지막 native 추출에 쓴 조건(정규화본), NULL = 조건 없음(기존 행 포함)
- 다운그레이드: 조건이 기록된 행이 하나라도 있으면 거부(데이터 보호, 0014·0018 선례), 없으면 열을 지워 되돌림

Revision ID: 0019_extract_filter
Revises: 0018_equiv_check
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0019_extract_filter"
down_revision = "0018_equiv_check"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("train_setups", sa.Column("extract_filter", JSONB(), nullable=True))


def downgrade() -> None:
    rows = op.get_bind().execute(sa.text("SELECT count(*) FROM train_setups WHERE extract_filter IS NOT NULL")).scalar()
    if rows:
        raise RuntimeError(f"추출 조건이 기록된 ① 설정 {rows}행이 있어 0019를 되돌릴 수 없습니다(데이터 보호)")
    op.drop_column("train_setups", "extract_filter")
