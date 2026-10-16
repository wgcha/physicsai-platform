"""0008_contour_capture — 예측 컨투어 캡처(phase3 §15 S10). 명시적 DDL(B14).

- artifacts.kind CHECK에 CONTOUR_IMAGE·CONTOUR_VIDEO 추가, artifacts.meta(JSONB NULL — 방향 `{view}` 등) 추가
- param_sets.display(JSONB NULL) — 템플릿 표시 설정 `{field, component, avgmode, comps, legend, views}`
- ux_jobs_study_type_active: CONTOUR_RECAPTURE 제외(예측 작업마다 재캡처 — 같은 원래 작업 중복은 서비스가 409)

Revision ID: 0008_contour_capture
Revises: 0007_predict_batch
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0008_contour_capture"
down_revision = "0007_predict_batch"
branch_labels = None
depends_on = None

ARTIFACT_KINDS = (
    "'PREVIEW_JSON','PREVIEW_IMAGE','CURVE_JSON','RESPONSE_TABLE','SCORE_FILE','PACKAGE_COMMANDS','SPLIT_JSON',"
    "'CURATION_CFG','FILE_LIST','DOE_SAMPLES','RUN_CONFIG','OPT_SUMMARY','OPT_FILE','CONTOUR_IMAGE','CONTOUR_VIDEO'"
)


ACTIVE_WHERE_NEW = ("state NOT IN ('SUCCEEDED','FAILED','CANCELED','INTERRUPTED') AND (params -> 'batch_run') IS NULL"
                    " AND job_type <> 'CONTOUR_RECAPTURE'")


def upgrade() -> None:
    op.drop_constraint("ck_artifacts_kind", "artifacts", type_="check")
    op.create_check_constraint("ck_artifacts_kind", "artifacts", f"kind IN ({ARTIFACT_KINDS})")
    op.add_column("artifacts", sa.Column("meta", JSONB(), nullable=True))
    op.add_column("param_sets", sa.Column("display", JSONB(), nullable=True))
    op.drop_index("ux_jobs_study_type_active", table_name="jobs")
    op.create_index("ux_jobs_study_type_active", "jobs", ["study_id", "job_type"], unique=True,
                    postgresql_where=sa.text(ACTIVE_WHERE_NEW))


def downgrade() -> None:
    raise RuntimeError("PhysicsAI migration은 downgrade를 지원하지 않습니다(데이터 보호)")
