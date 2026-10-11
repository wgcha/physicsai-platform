"""⑤ 최적화 테이블: optimizations(phase2 §5)."""

from __future__ import annotations

from sqlalchemy import CheckConstraint, Column, ForeignKey, Integer, String, Table, func, text
from sqlalchemy.dialects.postgresql import JSONB

from ._base import ID, TS, metadata

optimizations = Table(
    "optimizations",
    metadata,
    Column("id", ID, primary_key=True),
    Column("study_id", ID, ForeignKey("studies.id"), nullable=False, index=True),
    Column("job_id", ID, ForeignKey("jobs.id"), nullable=False),
    Column("approach", String, nullable=False),
    Column("opt_method", String, nullable=False),
    Column("max_designs", Integer, nullable=False),
    Column("model_id", ID, ForeignKey("models.id"), nullable=False),
    Column("param_set_id", ID, ForeignKey("param_sets.id"), nullable=False),
    Column("study_folder", String(64), nullable=False),
    Column("dir_rel", String, nullable=False),
    Column("runs_started", Integer, nullable=True),
    Column("responses", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("summary_status", String, nullable=False, server_default="NONE"),
    Column("summary_meta", JSONB, nullable=True),
    Column("file_count", Integer, nullable=True),
    Column("status", String, nullable=False, server_default="RUNNING"),
    Column("created_by", String, nullable=False),
    Column("created_by_name", String, nullable=False),
    Column("created_at", TS, nullable=False, server_default=func.now()),
    CheckConstraint("approach IN ('OPT','DOE')", name="ck_optimizations_approach"),
    CheckConstraint("opt_method IN ('ARSM','GRSM','SQP')", name="ck_optimizations_method"),
    CheckConstraint("summary_status IN ('NONE','PARSED','UNRECOGNIZED')", name="ck_optimizations_summary_status"),
    CheckConstraint("status IN ('RUNNING','DONE','FAILED')", name="ck_optimizations_status"),
)
