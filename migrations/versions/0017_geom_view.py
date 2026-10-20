"""0017_geom_view — 형상 3D 가시화·미리보기·결과 3D 컨투어(geometry-view.md §6.7·§13.5). 명시적 DDL(B14).

- jobs.lane CHECK에 'PREVIEW'(미리보기 전용 레인, 전역 슬롯 미사용)
- artifacts.kind에 GEOM_VIEW_GLB·GEOM_VIEW_MANIFEST·GEOM_PREVIEW_GLB·GEOM_PREVIEW_FE_GLB·GEOM_PREVIEW_MANIFEST·
  CONTOUR3D_GLB·CONTOUR3D_FRAMES·CONTOUR3D_MANIFEST
- ux_jobs_study_type_active: GEOM_PREVIEW·CONTOUR_3D 제외(동시 제한은 캐시 행 부분 unique + 서비스 규칙)
- 새 테이블 geom_previews·contour3d_cache(서버측 `<study>/_cache/` 캐시 인덱스 — 키·상태·수치 요약·산출물 id만)
- 다운그레이드: 미리보기·3D 컨투어 작업이나 새 kind 산출물이 하나라도 있으면 거부(데이터 보호), 없으면 되돌림

Revision ID: 0017_geom_view
Revises: 0016_geometry_engine
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP

revision = "0017_geom_view"
down_revision = "0016_geometry_engine"
branch_labels = None
depends_on = None

TS = TIMESTAMP(timezone=True)
ID = sa.String(36)

OLD_KINDS = (
    "'PREVIEW_JSON','PREVIEW_IMAGE','CURVE_JSON','RESPONSE_TABLE','SCORE_FILE','PACKAGE_COMMANDS','SPLIT_JSON',"
    "'CURATION_CFG','FILE_LIST','DOE_SAMPLES','RUN_CONFIG','OPT_SUMMARY','OPT_FILE','CONTOUR_IMAGE','CONTOUR_VIDEO','FEATURE_PNG'"
)
NEW_KINDS = ("'GEOM_VIEW_GLB','GEOM_VIEW_MANIFEST','GEOM_PREVIEW_GLB','GEOM_PREVIEW_FE_GLB','GEOM_PREVIEW_MANIFEST',"
             "'CONTOUR3D_GLB','CONTOUR3D_FRAMES','CONTOUR3D_MANIFEST'")
ACTIVE_WHERE_OLD = ("state NOT IN ('SUCCEEDED','FAILED','CANCELED','INTERRUPTED') AND (params -> 'batch_run') IS NULL"
                    " AND job_type <> 'CONTOUR_RECAPTURE'"
                    " AND NOT (job_type = 'PREDICT_BATCH' AND (params -> 'surrogate_opt') IS NOT NULL)"
                    " AND job_type <> 'FEM_VERIFY'"
                    " AND NOT (job_type = 'PREDICT' AND (params -> 'fem_verify_id') IS NOT NULL)")
ACTIVE_WHERE_NEW = ACTIVE_WHERE_OLD + " AND job_type NOT IN ('GEOM_PREVIEW','CONTOUR_3D')"
STATUSES = "status IN ('QUEUED','RUNNING','DONE','FAILED','CANCELED','EXPIRED')"
LIVE = "status IN ('QUEUED','RUNNING','DONE')"


def _common(name: str) -> list[sa.Column]:
    return [
        sa.Column("id", ID, primary_key=True),
        sa.Column("study_id", ID, sa.ForeignKey("studies.id"), nullable=False),
    ]


def upgrade() -> None:
    op.drop_constraint("ck_jobs_lane", "jobs", type_="check")
    op.create_check_constraint("ck_jobs_lane", "jobs", "lane IN ('SLOT','LIGHT','PREVIEW')")
    op.drop_constraint("ck_artifacts_kind", "artifacts", type_="check")
    op.create_check_constraint("ck_artifacts_kind", "artifacts", f"kind IN ({OLD_KINDS},{NEW_KINDS})")
    op.drop_index("ux_jobs_study_type_active", table_name="jobs")
    op.create_index("ux_jobs_study_type_active", "jobs", ["study_id", "job_type"], unique=True,
                    postgresql_where=sa.text(ACTIVE_WHERE_NEW))
    op.create_table(
        "geom_previews",
        *_common("geom_previews"),
        sa.Column("param_set_id", ID, sa.ForeignKey("param_sets.id"), nullable=False),
        sa.Column("cache_key", sa.String(64), nullable=False),
        sa.Column("job_id", ID, sa.ForeignKey("jobs.id"), nullable=True),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("fe", sa.String(8), nullable=False),
        sa.Column("values", JSONB(), nullable=False),
        sa.Column("engine_version", sa.String(32), nullable=True),
        sa.Column("result_status", sa.String(8), nullable=True),
        sa.Column("code", sa.String(64), nullable=True),
        sa.Column("category", sa.String(16), nullable=True),
        sa.Column("fe_status", sa.String(8), nullable=True),
        sa.Column("fe_code", sa.String(64), nullable=True),
        sa.Column("glb_artifact_id", ID, nullable=True),
        sa.Column("fe_glb_artifact_id", ID, nullable=True),
        sa.Column("manifest_artifact_id", ID, nullable=True),
        sa.Column("bytes", sa.BigInteger(), nullable=True),
        sa.Column("timing", JSONB(), nullable=True),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", TS, nullable=True),
        sa.Column("last_access_at", TS, nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(STATUSES, name="ck_geom_previews_status"),
        sa.CheckConstraint("fe IN ('off','check','morph')", name="ck_geom_previews_fe"),
    )
    op.create_index("ux_geom_previews_key_live", "geom_previews", ["cache_key"], unique=True, postgresql_where=sa.text(LIVE))
    op.create_index("ix_geom_previews_creator_status", "geom_previews", ["created_by", "status"])
    op.create_index("ix_geom_previews_last_access", "geom_previews", ["last_access_at"])
    op.create_table(
        "contour3d_cache",
        *_common("contour3d_cache"),
        sa.Column("cache_key", sa.String(64), nullable=False),
        sa.Column("job_id", ID, sa.ForeignKey("jobs.id"), nullable=True),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("source_kind", sa.String(12), nullable=False),
        sa.Column("source_ref", JSONB(), nullable=False),
        sa.Column("display", JSONB(), nullable=True),
        sa.Column("frames", sa.Integer(), nullable=True),
        sa.Column("nodes", sa.Integer(), nullable=True),
        sa.Column("bytes", sa.BigInteger(), nullable=True),
        sa.Column("result_status", sa.String(8), nullable=True),
        sa.Column("code", sa.String(64), nullable=True),
        sa.Column("glb_artifact_id", ID, nullable=True),
        sa.Column("frames_artifact_id", ID, nullable=True),
        sa.Column("manifest_artifact_id", ID, nullable=True),
        sa.Column("timing", JSONB(), nullable=True),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", TS, nullable=True),
        sa.Column("last_access_at", TS, nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(STATUSES, name="ck_contour3d_cache_status"),
        sa.CheckConstraint("source_kind IN ('SOLVER_H3D','PREDICT_H3D')", name="ck_contour3d_cache_source_kind"),
    )
    op.create_index("ux_contour3d_cache_key_live", "contour3d_cache", ["cache_key"], unique=True, postgresql_where=sa.text(LIVE))
    op.create_index("ix_contour3d_cache_creator_status", "contour3d_cache", ["created_by", "status"])
    op.create_index("ix_contour3d_cache_last_access", "contour3d_cache", ["last_access_at"])


def downgrade() -> None:
    bind = op.get_bind()
    jobs = bind.execute(sa.text("SELECT count(*) FROM jobs WHERE lane = 'PREVIEW' OR job_type IN ('GEOM_PREVIEW','CONTOUR_3D')")).scalar()
    arts = bind.execute(sa.text(f"SELECT count(*) FROM artifacts WHERE kind IN ({NEW_KINDS})")).scalar()
    rows = bind.execute(sa.text("SELECT (SELECT count(*) FROM geom_previews) + (SELECT count(*) FROM contour3d_cache)")).scalar()
    if jobs or arts or rows:
        raise RuntimeError(f"미리보기·3D 컨투어 작업 {jobs}개·산출물 {arts}개·캐시 행 {rows}개가 있어 0017을 되돌릴 수 없습니다(데이터 보호)")
    op.drop_table("contour3d_cache")
    op.drop_table("geom_previews")
    op.drop_index("ux_jobs_study_type_active", table_name="jobs")
    op.create_index("ux_jobs_study_type_active", "jobs", ["study_id", "job_type"], unique=True,
                    postgresql_where=sa.text(ACTIVE_WHERE_OLD))
    op.drop_constraint("ck_artifacts_kind", "artifacts", type_="check")
    op.create_check_constraint("ck_artifacts_kind", "artifacts", f"kind IN ({OLD_KINDS})")
    op.drop_constraint("ck_jobs_lane", "jobs", type_="check")
    op.create_check_constraint("ck_jobs_lane", "jobs", "lane IN ('SLOT','LIGHT')")
