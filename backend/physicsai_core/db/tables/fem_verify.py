"""④ 조립 FEM 검증 테이블(phase3 §21.3.4 S16, migration 0013_fem_verify).

fem_verifications: 검증 1건(표시 `FV-003` = fv_no). 출처(source_kind·source_ref 수치만)·비교 대상 예측(predict_job_id, 동반이면
companion)·조립 원본(assem_kind·assem_ref·input_mode)·실행(job_id = 최신 FEM_VERIFY, attempt_no, status)·요약(수치만)."""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
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

FV_SOURCE_KINDS = ("PREDICT_JOB", "BATCH_RUN", "VALUES", "OPT_DESIGN")
FV_ASSEM_KINDS = ("PREDICT_INPUT", "TRAIN_DOE", "CUSTOM")
FV_INPUT_MODES = ("reuse", "rebuild")
FV_STATUSES = ("WAITING_PREDICT", "RUNNING", "DONE", "FAILED", "CANCELED")
FV_ACTIVE = ("WAITING_PREDICT", "RUNNING")


def _in(col: str, vals: tuple[str, ...]) -> str:
    return f"{col} IN (" + ",".join(f"'{v}'" for v in vals) + ")"


fem_verifications = Table(
    "fem_verifications",
    metadata,
    Column("id", ID, primary_key=True),
    Column("study_id", ID, ForeignKey("studies.id"), nullable=False),
    Column("fv_no", Integer, nullable=False),
    Column("source_kind", String(16), nullable=False),
    Column("source_ref", JSONB, nullable=False),
    Column("predict_job_id", ID, ForeignKey("jobs.id"), nullable=True),
    Column("companion", Boolean, nullable=False, server_default=text("false")),
    Column("param_set_id", ID, ForeignKey("param_sets.id"), nullable=True),
    Column("model_id", ID, ForeignKey("models.id"), nullable=True),
    Column("template_kind", String(16), nullable=True),
    Column("assem_kind", String(16), nullable=False),
    Column("assem_ref", JSONB, nullable=True),
    Column("input_mode", String(8), nullable=False),
    Column("options", JSONB, nullable=True),
    Column("job_id", ID, ForeignKey("jobs.id"), nullable=True),
    Column("attempt_no", Integer, nullable=False, server_default="0"),
    Column("status", String(16), nullable=False),
    Column("summary", JSONB, nullable=True),
    Column("failure_code", String(32), nullable=True),
    Column("failure_message", String(500), nullable=True),
    Column("dir_rel", String, nullable=False),
    Column("created_by", String, nullable=False),
    Column("created_by_name", String, nullable=False),
    Column("created_at", TS, nullable=False, server_default=func.now()),
    Column("finished_at", TS, nullable=True),
    UniqueConstraint("study_id", "fv_no", name="uq_fem_verifications_study_no"),
    CheckConstraint("fv_no >= 1", name="ck_fem_verifications_fv_no"),
    CheckConstraint(_in("source_kind", FV_SOURCE_KINDS), name="ck_fem_verifications_source_kind"),
    CheckConstraint(_in("assem_kind", FV_ASSEM_KINDS), name="ck_fem_verifications_assem_kind"),
    CheckConstraint(_in("input_mode", FV_INPUT_MODES), name="ck_fem_verifications_input_mode"),
    CheckConstraint(_in("status", FV_STATUSES), name="ck_fem_verifications_status"),
)
Index("ix_fem_verifications_study_created", fem_verifications.c.study_id, fem_verifications.c.created_at.desc())
Index("ix_fem_verifications_predict_job", fem_verifications.c.predict_job_id)
