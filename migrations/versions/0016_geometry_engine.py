"""0016_geometry_engine — native 형상 엔진(geometry-engine.md §7.5). 명시적 DDL(B14).

- param_sets: engine('altair' 기본, 기존 행 = altair)·geom_options(JSONB NULL)·engine_version, tpl_rel NULL 허용
  (CHECK: native 아니면 tpl_rel 필요, native는 assembly 입력만)
- train_setups: engine·features_rel / train_does: engine·geom_options·engine_version
- datasets: engine(NULL = 모름)·engine_version / models: engine / predict_batch_runs: engine_version
- artifacts.kind에 FEATURE_PNG 추가
- 다운그레이드는 기존 정책(거부)

Revision ID: 0016_geometry_engine
Revises: 0015_doe_platform_gen
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0016_geometry_engine"
down_revision = "0015_doe_platform_gen"
branch_labels = None
depends_on = None

ARTIFACT_KINDS = (
    "'PREVIEW_JSON','PREVIEW_IMAGE','CURVE_JSON','RESPONSE_TABLE','SCORE_FILE','PACKAGE_COMMANDS','SPLIT_JSON',"
    "'CURATION_CFG','FILE_LIST','DOE_SAMPLES','RUN_CONFIG','OPT_SUMMARY','OPT_FILE','CONTOUR_IMAGE','CONTOUR_VIDEO','FEATURE_PNG'"
)


def upgrade() -> None:
    # ---- param_sets ----
    op.add_column("param_sets", sa.Column("engine", sa.String(16), nullable=False, server_default="altair"))
    op.add_column("param_sets", sa.Column("geom_options", JSONB(), nullable=True))
    op.add_column("param_sets", sa.Column("engine_version", sa.String(32), nullable=True))
    op.alter_column("param_sets", "tpl_rel", existing_type=sa.String(), nullable=True)
    op.create_check_constraint("ck_param_sets_engine", "param_sets", "engine IN ('altair','native')")
    op.create_check_constraint("ck_param_sets_tpl_engine", "param_sets", "engine = 'native' OR tpl_rel IS NOT NULL")
    op.create_check_constraint("ck_param_sets_native_assembly", "param_sets", "engine <> 'native' OR input_kind = 'assembly'")
    # ---- ① 학습데이터 ----
    op.add_column("train_setups", sa.Column("engine", sa.String(16), nullable=False, server_default="altair"))
    op.add_column("train_setups", sa.Column("features_rel", sa.String(), nullable=True))
    op.create_check_constraint("ck_train_setups_engine", "train_setups", "engine IN ('altair','native')")
    op.add_column("train_does", sa.Column("engine", sa.String(16), nullable=False, server_default="altair"))
    op.add_column("train_does", sa.Column("geom_options", JSONB(), nullable=True))
    op.add_column("train_does", sa.Column("engine_version", sa.String(32), nullable=True))
    op.create_check_constraint("ck_train_does_engine", "train_does", "engine IN ('altair','native')")
    # ---- 데이터셋·모델: 기존 행 = 모름(NULL) ----
    op.add_column("datasets", sa.Column("engine", sa.String(16), nullable=True))
    op.add_column("datasets", sa.Column("engine_version", sa.String(32), nullable=True))
    op.create_check_constraint("ck_datasets_engine", "datasets", "engine IS NULL OR engine IN ('altair','native')")
    op.add_column("models", sa.Column("engine", sa.String(16), nullable=True))
    op.create_check_constraint("ck_models_engine", "models", "engine IS NULL OR engine IN ('altair','native')")
    op.add_column("predict_batch_runs", sa.Column("engine_version", sa.String(32), nullable=True))
    # ---- artifacts.kind ----
    op.drop_constraint("ck_artifacts_kind", "artifacts", type_="check")
    op.create_check_constraint("ck_artifacts_kind", "artifacts", f"kind IN ({ARTIFACT_KINDS})")


def downgrade() -> None:
    raise RuntimeError("PhysicsAI migration은 downgrade를 지원하지 않습니다(데이터 보호)")
