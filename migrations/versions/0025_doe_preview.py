"""0025_doe_preview — DOE 표본 형상 그리드 미리보기(doe-preview.md §6.7, DP-C6·DP-C7). 명시적 DDL(B14).

- artifacts.kind CHECK에 GEOM_THUMB_PNG 추가(셀 썸네일 PNG, image/png). 셀 GLB·manifest는 기존 GEOM_PREVIEW_GLB·GEOM_PREVIEW_MANIFEST
- ux_jobs_study_type_active: DOE_PREVIEW 제외(동시 제한은 doe_previews 행·서비스 규칙 max_active_per_user)
- 새 테이블 doe_previews(요청 1건 = 페이지 1개: 키·상태·정렬 요약·셀 키 순서)·doe_preview_cells(서버측 `<study>/_cache/doe_preview/cells/` 셀 캐시 인덱스 —
  키·수치 요약·산출물 id만). 산출물 id 열은 FK가 아니다(housekeeping이 artifacts 행을 지운 뒤에도 410 판정에 쓴다)
- 다운그레이드: DOE_PREVIEW 작업·GEOM_THUMB_PNG 산출물·두 테이블 행이 하나라도 있으면 거부(데이터 보호, 0017·0024 선례), 없으면 되돌림

Revision ID: 0025_doe_preview
Revises: 0024_contour3d_field
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP

revision = "0025_doe_preview"
down_revision = "0024_contour3d_field"
branch_labels = None
depends_on = None

TS = TIMESTAMP(timezone=True)
ID = sa.String(36)

OLD_KINDS = (
    "'PREVIEW_JSON','PREVIEW_IMAGE','CURVE_JSON','RESPONSE_TABLE','SCORE_FILE','PACKAGE_COMMANDS','SPLIT_JSON',"
    "'CURATION_CFG','FILE_LIST','DOE_SAMPLES','RUN_CONFIG','OPT_SUMMARY','OPT_FILE','CONTOUR_IMAGE','CONTOUR_VIDEO','FEATURE_PNG',"
    "'GEOM_VIEW_GLB','GEOM_VIEW_MANIFEST','GEOM_PREVIEW_GLB','GEOM_PREVIEW_FE_GLB','GEOM_PREVIEW_MANIFEST',"
    "'CONTOUR3D_GLB','CONTOUR3D_FRAMES','CONTOUR3D_MANIFEST','CONTOUR3D_DISP','CONTOUR3D_LOD'"
)
NEW_KINDS = "'GEOM_THUMB_PNG'"
ACTIVE_WHERE_OLD = ("state NOT IN ('SUCCEEDED','FAILED','CANCELED','INTERRUPTED') AND (params -> 'batch_run') IS NULL"
                    " AND job_type <> 'CONTOUR_RECAPTURE'"
                    " AND NOT (job_type = 'PREDICT_BATCH' AND (params -> 'surrogate_opt') IS NOT NULL)"
                    " AND job_type <> 'FEM_VERIFY'"
                    " AND NOT (job_type = 'PREDICT' AND (params -> 'fem_verify_id') IS NOT NULL)"
                    " AND job_type NOT IN ('GEOM_PREVIEW','CONTOUR_3D')"
                    " AND job_type <> 'EQ_CHECK'")
ACTIVE_WHERE_NEW = ACTIVE_WHERE_OLD + " AND job_type <> 'DOE_PREVIEW'"
PREVIEW_STATUSES = "status IN ('QUEUED','RUNNING','DONE','FAILED','CANCELED')"
CELL_STATUSES = "status IN ('DONE','EXPIRED')"


def upgrade() -> None:
    op.drop_constraint("ck_artifacts_kind", "artifacts", type_="check")
    op.create_check_constraint("ck_artifacts_kind", "artifacts", f"kind IN ({OLD_KINDS},{NEW_KINDS})")
    op.drop_index("ux_jobs_study_type_active", table_name="jobs")
    op.create_index("ux_jobs_study_type_active", "jobs", ["study_id", "job_type"], unique=True,
                    postgresql_where=sa.text(ACTIVE_WHERE_NEW))
    op.create_table(
        "doe_previews",
        sa.Column("id", ID, primary_key=True),
        sa.Column("study_id", ID, sa.ForeignKey("studies.id"), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("job_id", ID, sa.ForeignKey("jobs.id"), nullable=True),
        sa.Column("grid_key", sa.CHAR(64), nullable=False),
        sa.Column("source_kind", sa.String(12), nullable=False),
        sa.Column("source_ref", JSONB(), nullable=False),
        sa.Column("matrix_key", sa.CHAR(64), nullable=True),
        sa.Column("select", JSONB(), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("cell_keys", JSONB(), nullable=True),
        sa.Column("n_total", sa.Integer(), nullable=True),
        sa.Column("n_ok", sa.Integer(), nullable=True),
        sa.Column("n_fail", sa.Integer(), nullable=True),
        sa.Column("n_error", sa.Integer(), nullable=True),
        sa.Column("timing", JSONB(), nullable=True),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", TS, nullable=True),
        sa.CheckConstraint(PREVIEW_STATUSES, name="ck_doe_previews_status"),
        sa.CheckConstraint("source_kind IN ('train','param_set','train_doe')", name="ck_doe_previews_source_kind"),
    )
    op.create_index("ix_doe_previews_creator_status", "doe_previews", ["created_by", "status"])
    op.create_index("ix_doe_previews_grid_key", "doe_previews", ["grid_key"])
    op.create_table(
        "doe_preview_cells",
        sa.Column("cache_key", sa.CHAR(64), primary_key=True),
        sa.Column("study_id", ID, sa.ForeignKey("studies.id"), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("result_status", sa.String(8), nullable=True),
        sa.Column("code", sa.String(64), nullable=True),
        sa.Column("category", sa.String(16), nullable=True),
        sa.Column("max_disp_mm", sa.REAL(), nullable=True),
        sa.Column("clipped", sa.Boolean(), nullable=True),
        sa.Column("values", JSONB(), nullable=False),
        sa.Column("png_artifact_id", ID, nullable=True),
        sa.Column("glb_artifact_id", ID, nullable=True),
        sa.Column("manifest_artifact_id", ID, nullable=True),
        sa.Column("bytes", sa.BigInteger(), nullable=True),
        sa.Column("engine_version", sa.String(32), nullable=True),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("last_access_at", TS, nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(CELL_STATUSES, name="ck_doe_preview_cells_status"),
    )
    op.create_index("ix_doe_preview_cells_last_access", "doe_preview_cells", ["last_access_at"])


def downgrade() -> None:
    bind = op.get_bind()
    jobs = bind.execute(sa.text("SELECT count(*) FROM jobs WHERE job_type = 'DOE_PREVIEW'")).scalar()
    arts = bind.execute(sa.text(f"SELECT count(*) FROM artifacts WHERE kind IN ({NEW_KINDS})")).scalar()
    rows = bind.execute(sa.text("SELECT (SELECT count(*) FROM doe_previews) + (SELECT count(*) FROM doe_preview_cells)")).scalar()
    if jobs or arts or rows:
        raise RuntimeError(f"DOE 형상 미리보기 작업 {jobs}개·썸네일 산출물 {arts}개·미리보기·셀 행 {rows}개가 있어 0025를 되돌릴 수 없습니다(데이터 보호)")
    op.drop_table("doe_preview_cells")
    op.drop_table("doe_previews")
    op.drop_index("ux_jobs_study_type_active", table_name="jobs")
    op.create_index("ux_jobs_study_type_active", "jobs", ["study_id", "job_type"], unique=True,
                    postgresql_where=sa.text(ACTIVE_WHERE_OLD))
    op.drop_constraint("ck_artifacts_kind", "artifacts", type_="check")
    op.create_check_constraint("ck_artifacts_kind", "artifacts", f"kind IN ({OLD_KINDS})")
