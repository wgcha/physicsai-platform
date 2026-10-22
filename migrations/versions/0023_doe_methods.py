"""0023_doe_methods — ④ 일괄 예측·⑥ 탐색 표본 방식 halton·random 추가(doe-methods.md DM-C3·§5.5). 명시적 DDL(B14).

down_revision은 0022_job_queues(대기열 분리, 같은 v0.2.9) — 두 마이그레이션은 서로 다른 제약(jobs lane·holds_slot / predict_batches source_kind)만 건드린다.

- predict_batches.source_kind CHECK 확장: HALTON·RANDOM 추가(기존 10개 유지, 열 길이 String(16)·기존 행 데이터 무변경)
- train_does.doe_type은 제약 없는 문자열이라 변경 없음. 방식 인자는 기존 source_meta·train_does.options·sampling JSONB.
- 다운그레이드: HALTON·RANDOM 행이 하나라도 있으면 거부(배치·입력 원본 보호, 0017~0021 선례), 없으면 CHECK를 기존 10개로 되돌림

Revision ID: 0023_doe_methods
Revises: 0022_job_queues
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0023_doe_methods"
down_revision = "0022_job_queues"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_predict_batches_source_kind", "predict_batches", type_="check")
    op.create_check_constraint(
        "ck_predict_batches_source_kind", "predict_batches",
        "source_kind IN ('LHS','LHS_OPT','SOBOL','FULLFACT','FRACFACT','PB','BBD','CCD','TABLE','TRAIN_DOE','HALTON','RANDOM')")


def downgrade() -> None:
    n = op.get_bind().execute(sa.text("SELECT count(*) FROM predict_batches WHERE source_kind IN ('HALTON','RANDOM')")).scalar()
    if n:
        raise RuntimeError(f"Halton·균일 랜덤 배치 {n}개가 있어 0023을 되돌릴 수 없습니다(입력 원본 보호)")
    op.drop_constraint("ck_predict_batches_source_kind", "predict_batches", type_="check")
    op.create_check_constraint(
        "ck_predict_batches_source_kind", "predict_batches",
        "source_kind IN ('LHS','LHS_OPT','SOBOL','FULLFACT','FRACFACT','PB','BBD','CCD','TABLE','TRAIN_DOE')")
