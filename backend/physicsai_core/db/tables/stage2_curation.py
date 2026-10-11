"""② 데이터 정리 테이블: curations·spdm_imports(phase2 §5)."""

from __future__ import annotations

from sqlalchemy import BigInteger, CheckConstraint, Column, ForeignKey, Integer, String, Table, func, text
from sqlalchemy.dialects.postgresql import JSONB

from ._base import ID, TS, metadata

curations = Table(
    "curations",
    metadata,
    Column("id", ID, primary_key=True),
    Column("study_id", ID, ForeignKey("studies.id"), nullable=False, index=True),
    Column("job_id", ID, ForeignKey("jobs.id"), nullable=False),
    Column("kind", String, nullable=False),
    Column("source", JSONB, nullable=False),
    Column("preview_job_id", ID, ForeignKey("jobs.id"), nullable=True),
    Column("selection", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("output_rel", String, nullable=False),
    Column("file_list_rel", String, nullable=False),
    Column("target_count", Integer, nullable=True),
    Column("ok_count", Integer, nullable=True),
    Column("failed_count", Integer, nullable=True),
    Column("missing_runs", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("status", String, nullable=False, server_default="BUILDING"),
    Column("created_by", String, nullable=False),
    Column("created_by_name", String, nullable=False),
    Column("created_at", TS, nullable=False, server_default=func.now()),
    CheckConstraint("kind IN ('H3D','T01')", name="ck_curations_kind"),
    CheckConstraint("status IN ('BUILDING','READY','FAILED')", name="ck_curations_status"),
)

spdm_imports = Table(
    "spdm_imports",
    metadata,
    Column("id", ID, primary_key=True),
    Column("study_id", ID, ForeignKey("studies.id"), nullable=False, index=True),
    Column("job_id", ID, ForeignKey("jobs.id"), nullable=False),
    Column("spdm_path", String, nullable=False),
    Column("dest_rel", String, nullable=False),
    Column("file_count", Integer, nullable=True),
    Column("total_bytes", BigInteger, nullable=True),
    Column("renamed_count", Integer, nullable=True),
    Column("manifest_rel", String, nullable=True),
    Column("status", String, nullable=False, server_default="BUILDING"),
    Column("created_by", String, nullable=False),
    Column("created_by_name", String, nullable=False),
    Column("created_at", TS, nullable=False, server_default=func.now()),
    CheckConstraint("status IN ('BUILDING','READY','FAILED')", name="ck_spdm_imports_status"),
)
