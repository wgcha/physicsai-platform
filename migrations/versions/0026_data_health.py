"""0026_data_health — ③-1 데이터 점검(data-health.md §6.1, DH-11). 명시적 DDL(B14).

- datasets: excluded_count INT NOT NULL DEFAULT 0(기존 행 0), health_job_id(점검 작업 FK, 작업 삭제 시 NULL — 기록용)
  (이 저장소의 id는 문자열 36자 — 계약의 UUID 표기는 jobs.id 열 형식과 같은 String(36))
- artifacts.kind CHECK에 DATA_HEALTH_REPORT·DATA_HEALTH_CSV 추가(계약 §5 DH_REPORT가 등록하는 산출물)
- 새 결과 테이블 없음(run별 상세는 파일 03_dataset/_health/<job_id>/). ux_jobs_study_type_active는 그대로(Study당 활성 1개 = DATA_HEALTH_ACTIVE)
- 다운그레이드: DATA_HEALTH 산출물 행이나 datasets.health_job_id·excluded_count 값이 있으면 실패(데이터 보존, 0014와 같은 방식), 없을 때만 열·CHECK를 되돌린다

Revision ID: 0026_data_health
Revises: 0025_doe_preview
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0026_data_health"
down_revision = "0025_doe_preview"
branch_labels = None
depends_on = None

OLD_KINDS = (
    "'PREVIEW_JSON','PREVIEW_IMAGE','CURVE_JSON','RESPONSE_TABLE','SCORE_FILE','PACKAGE_COMMANDS','SPLIT_JSON',"
    "'CURATION_CFG','FILE_LIST','DOE_SAMPLES','RUN_CONFIG','OPT_SUMMARY','OPT_FILE','CONTOUR_IMAGE','CONTOUR_VIDEO','FEATURE_PNG',"
    "'GEOM_VIEW_GLB','GEOM_VIEW_MANIFEST','GEOM_PREVIEW_GLB','GEOM_PREVIEW_FE_GLB','GEOM_PREVIEW_MANIFEST',"
    "'CONTOUR3D_GLB','CONTOUR3D_FRAMES','CONTOUR3D_MANIFEST','CONTOUR3D_DISP','CONTOUR3D_LOD','GEOM_THUMB_PNG'"
)
NEW_KINDS = "'DATA_HEALTH_REPORT','DATA_HEALTH_CSV'"


def upgrade() -> None:
    op.add_column("datasets", sa.Column("excluded_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("datasets", sa.Column("health_job_id", sa.String(36), sa.ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True))
    op.drop_constraint("ck_artifacts_kind", "artifacts", type_="check")
    op.create_check_constraint("ck_artifacts_kind", "artifacts", f"kind IN ({OLD_KINDS},{NEW_KINDS})")


def downgrade() -> None:
    conn = op.get_bind()
    n_art = conn.execute(sa.text(f"SELECT count(*) FROM artifacts WHERE kind IN ({NEW_KINDS})")).scalar()
    n_ds = conn.execute(sa.text("SELECT count(*) FROM datasets WHERE health_job_id IS NOT NULL OR excluded_count <> 0")).scalar()
    if n_art or n_ds:
        raise RuntimeError(f"데이터 점검 산출물 행 {n_art}개·점검 기록이 있는 데이터셋 {n_ds}개가 있어 0026을 되돌릴 수 없습니다(데이터 보호)")
    op.drop_constraint("ck_artifacts_kind", "artifacts", type_="check")
    op.create_check_constraint("ck_artifacts_kind", "artifacts", f"kind IN ({OLD_KINDS})")
    op.drop_column("datasets", "health_job_id")
    op.drop_column("datasets", "excluded_count")
