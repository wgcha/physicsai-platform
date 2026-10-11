"""① 학습데이터 생성 테이블: train_setups·train_does·train_runs(phase2 §5)."""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

from ._base import ID, TS, metadata

train_setups = Table(
    "train_setups",
    metadata,
    Column("id", ID, primary_key=True),
    Column("study_id", ID, ForeignKey("studies.id"), nullable=False, unique=True),
    Column("cad_source_path", String, nullable=True),
    Column("cad_file_name", String, nullable=True),
    Column("cad_sha256", String(64), nullable=True),
    Column("extract_job_id", ID, ForeignKey("jobs.id"), nullable=True),
    Column("parameters", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("tpl_rel", String, nullable=True),
    Column("tpl_sha256", String(64), nullable=True),
    Column("tpl_generated_at", TS, nullable=True),
    Column("tpl_params", JSONB, nullable=True),
    Column("tpl_warnings", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("updated_by", String, nullable=True),
    Column("updated_by_name", String, nullable=True),
    Column("updated_at", TS, nullable=False, server_default=func.now()),
    Column("version", BigInteger, nullable=False, server_default="1"),
)

train_does = Table(
    "train_does",
    metadata,
    Column("id", ID, primary_key=True),
    Column("study_id", ID, ForeignKey("studies.id"), nullable=False, index=True),
    Column("job_id", ID, ForeignKey("jobs.id"), nullable=False),
    Column("doe_label", String, nullable=False),
    Column("doe_type", String, nullable=False),
    Column("num_runs_requested", Integer, nullable=True),
    Column("options", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("multi_execution", Integer, nullable=False, server_default="1"),
    Column("radioss_assem_source_path", String, nullable=False),
    Column("dir_rel", String, nullable=False),
    Column("assem_rel", String, nullable=False),
    Column("parameters_snapshot", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("tpl_sha256", String(64), nullable=True),
    Column("run_count", Integer, nullable=True),
    Column("sample_status", String, nullable=False, server_default="PENDING"),
    Column("samples_rel", String, nullable=True),
    Column("responses_rel", String, nullable=True),
    Column("status", String, nullable=False, server_default="BUILDING"),
    Column("created_by", String, nullable=False),
    Column("created_by_name", String, nullable=False),
    Column("created_at", TS, nullable=False, server_default=func.now()),
    CheckConstraint("sample_status IN ('PARSED','PARTIAL','MISSING','PENDING')", name="ck_train_does_sample_status"),
    CheckConstraint("status IN ('BUILDING','READY','FAILED')", name="ck_train_does_status"),
)

train_runs = Table(
    "train_runs",
    metadata,
    Column("id", ID, primary_key=True),
    Column("doe_id", ID, ForeignKey("train_does.id"), nullable=False),
    Column("run_key", String(64), nullable=False),
    Column("input_rel", String, nullable=False),
    Column("starter_name", String, nullable=False),
    Column("state", String, nullable=False, server_default="GENERATED"),
    Column("last_job_id", ID, ForeignKey("jobs.id"), nullable=True),
    Column("hpc_job_id", ID, ForeignKey("hpc_jobs.id"), nullable=True),
    Column("result_rel", String, nullable=True),
    Column("result_summary", JSONB, nullable=True),
    Column("updated_at", TS, nullable=False, server_default=func.now()),
    UniqueConstraint("doe_id", "run_key", name="uq_train_runs_doe_run"),
    CheckConstraint(
        "state IN ('GENERATED','SUBMITTED','SOLVED','SOLVE_FAILED','COLLECTED','COLLECT_FAILED')", name="ck_train_runs_state"
    ),
)
Index("ix_train_runs_doe_state", train_runs.c.doe_id, train_runs.c.state)
