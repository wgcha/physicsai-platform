"""0012_sampling_kinds — ④ 일괄 예측 표본 방식 7종 추가(phase3 §20.8, D3-63). 명시적 DDL(B14).

- predict_batches.source_kind CHECK 확장: LHS_OPT·SOBOL·FULLFACT·FRACFACT·PB·BBD·CCD 추가(기존 LHS·TABLE·TRAIN_DOE 유지)
- 열 길이 String(16)·기존 행 데이터는 바꾸지 않는다. 방식 인자는 기존 source_meta JSONB.

Revision ID: 0012_sampling_kinds
Revises: 0011_surrogate_final
"""

from __future__ import annotations

from alembic import op

revision = "0012_sampling_kinds"
down_revision = "0011_surrogate_final"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_predict_batches_source_kind", "predict_batches", type_="check")
    op.create_check_constraint(
        "ck_predict_batches_source_kind", "predict_batches",
        "source_kind IN ('LHS','LHS_OPT','SOBOL','FULLFACT','FRACFACT','PB','BBD','CCD','TABLE','TRAIN_DOE')")


def downgrade() -> None:
    raise RuntimeError("PhysicsAI migration은 downgrade를 지원하지 않습니다(데이터 보호)")
