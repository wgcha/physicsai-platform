"""③ 데이터셋·모델, ④ 파라미터 세트 테이블(계약 §6, phase2 §5 origin·train_doe_id)."""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Table,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

from ._base import ID, TS, metadata

datasets = Table(
    "datasets",
    metadata,
    Column("id", ID, primary_key=True),
    Column("study_id", ID, ForeignKey("studies.id"), nullable=False, index=True),
    Column("job_id", ID, ForeignKey("jobs.id"), nullable=True),
    Column("source_path", String, nullable=False),
    Column("h3d_count", Integer, nullable=True),
    Column("train_count", Integer, nullable=True),
    Column("eval_count", Integer, nullable=True),
    Column("holdout_ratio", Numeric(4, 3), nullable=False, server_default="0.1"),
    Column("seed", BigInteger, nullable=False),
    Column("split_group", String, nullable=False),
    Column("options_json", JSONB, nullable=False),
    Column("split_rel", String, nullable=True),
    Column("train_psdata_rel", String, nullable=True),
    Column("train_psdata_size", BigInteger, nullable=True),
    Column("eval_psdata_rel", String, nullable=True),
    Column("eval_psdata_size", BigInteger, nullable=True),
    Column("package_rel", String, nullable=True),
    Column("status", String, nullable=False),
    Column("created_by", String, nullable=False),
    Column("created_by_name", String, nullable=False),
    Column("created_at", TS, nullable=False, server_default=func.now()),
    Column("engine", String(16), nullable=True),  # geometry-engine.md §7.5: 학습데이터 형상 엔진(NULL = 모름, 0016)
    Column("engine_version", String(32), nullable=True),  # paicad 버전(altair·모름 = NULL, §17.3)
    CheckConstraint("engine IS NULL OR engine IN ('altair','native')", name="ck_datasets_engine"),
    CheckConstraint("status IN ('BUILDING','READY','FAILED')", name="ck_datasets_status"),
    CheckConstraint("split_group IN ('file','parent_dir')", name="ck_datasets_split_group"),
)

models = Table(
    "models",
    metadata,
    Column("id", ID, primary_key=True),
    Column("study_id", ID, ForeignKey("studies.id"), nullable=False, index=True),
    Column("name", String(64), nullable=False),
    Column("version", Integer, nullable=False),
    Column("label", String(120), nullable=True),
    Column("dataset_id", ID, ForeignKey("datasets.id"), nullable=True),
    Column("source_path", String, nullable=False),
    Column("stored_rel", String, nullable=False),
    Column("psmdl_rel", String, nullable=False),
    Column("psmdl_sha256", String(64), nullable=False),
    Column("psmdl_size", BigInteger, nullable=False),
    Column("pscfg_rel", String, nullable=True),  # D3-43: pscfg 선택(0005_pscfg_optional)
    Column("pscfg_sha256", String(64), nullable=True),
    Column("log_rel", String, nullable=True),
    Column("log_status", String, nullable=False),
    Column("log_parser", String, nullable=True),
    Column("epochs_total", Integer, nullable=True),
    Column("last_epoch", Integer, nullable=True),
    Column("final_loss", Float, nullable=True),
    Column("min_loss", Float, nullable=True),
    Column("min_loss_epoch", Integer, nullable=True),
    Column("loss_curve", JSONB, nullable=True),
    Column("eval_status", String, nullable=False, server_default="NONE"),
    Column("eval_job_id", ID, ForeignKey("jobs.id"), nullable=True),
    Column("eval_score", JSONB, nullable=True),
    Column("status", String, nullable=False, server_default="ACTIVE"),
    Column("registered_by", String, nullable=False),
    Column("registered_by_name", String, nullable=False),
    Column("registered_at", TS, nullable=False, server_default=func.now()),
    Column("row_version", BigInteger, nullable=False, server_default="1"),
    Column("engine", String(16), nullable=True),  # geometry-engine.md §7.7: 학습 데이터셋의 형상 엔진(NULL = 모름, 0016)
    UniqueConstraint("study_id", "name", "version", name="uq_models_study_name_version"),
    CheckConstraint("engine IS NULL OR engine IN ('altair','native')", name="ck_models_engine"),
    CheckConstraint("log_status IN ('PARSED','UNRECOGNIZED','MISSING')", name="ck_models_log_status"),
    CheckConstraint("eval_status IN ('NONE','RUNNING','DONE','FAILED')", name="ck_models_eval_status"),
    CheckConstraint("status IN ('ACTIVE','ARCHIVED','INVALID')", name="ck_models_status"),
)

param_sets = Table(
    "param_sets",
    metadata,
    Column("id", ID, primary_key=True),
    Column("study_id", ID, ForeignKey("studies.id"), nullable=False, index=True),
    Column("source_path", String, nullable=False),
    Column("stored_rel", String, nullable=False),
    Column("unit_system", String, nullable=False, server_default="mm-ton-s"),
    Column("parameters", JSONB, nullable=False),
    Column("responses", JSONB, nullable=False),
    Column("sample_count", Integer, nullable=False),
    Column("sample_has_measured", Boolean, nullable=False),
    Column("cad_file_name", String, nullable=False),
    Column("tpl_rel", String, nullable=True),  # native는 NULL(ck_param_sets_tpl_engine, 0016)
    Column("assem_rel", String, nullable=True),  # phase3 §14.3: mesh_only면 NULL(0007_predict_batch)
    Column("starter_name", String, nullable=True),
    Column("tpl_params", JSONB, nullable=False),
    Column("is_current", Boolean, nullable=False, server_default=text("false")),
    Column("registered_by", String, nullable=False),
    Column("registered_by_name", String, nullable=False),
    Column("registered_at", TS, nullable=False, server_default=func.now()),
    Column("origin", String, nullable=False, server_default="FOLDER"),
    Column("train_doe_id", ID, ForeignKey("train_does.id", use_alter=True, name="fk_param_sets_train_doe"), nullable=True),
    Column("label", String(120), nullable=True),  # phase3 §13 S8 사용자 표시 이름(0006_param_set_label)
    # phase3 §14.3 S9 템플릿 입력 종류: assembly(조립 폴더 포함) | mesh_only(m1 메시 그대로 예측)
    Column("input_kind", String(16), nullable=False, server_default="assembly"),
    Column("display", JSONB, nullable=True),  # phase3 §15 S10 컨투어 표시 설정(0008_contour_capture)
    # geometry-engine.md §7.5 (0016): 형상 엔진·세트별 옵션 덮어쓰기(기본값 아님)·paicad 버전
    Column("engine", String(16), nullable=False, server_default="altair"),
    Column("geom_options", JSONB, nullable=True),
    Column("engine_version", String(32), nullable=True),
    CheckConstraint("engine IN ('altair','native')", name="ck_param_sets_engine"),
    CheckConstraint("engine = 'native' OR tpl_rel IS NOT NULL", name="ck_param_sets_tpl_engine"),
    CheckConstraint("engine <> 'native' OR input_kind = 'assembly'", name="ck_param_sets_native_assembly"),
    CheckConstraint("origin IN ('FOLDER','TRAIN_DOE')", name="ck_param_sets_origin"),
    CheckConstraint("input_kind IN ('mesh_only','assembly')", name="ck_param_sets_input_kind"),
    CheckConstraint("input_kind <> 'assembly' OR (assem_rel IS NOT NULL AND starter_name IS NOT NULL)",
                    name="ck_param_sets_assembly_files"),
)
Index("ux_param_sets_current", param_sets.c.study_id, unique=True, postgresql_where=text("is_current"))
