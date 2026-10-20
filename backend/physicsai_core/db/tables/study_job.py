"""Study·작업(jobs) 테이블과 대기열·활성 작업 인덱스(계약 §6)."""

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
    SmallInteger,
    String,
    Table,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

from ._base import ID, TS, metadata

studies = Table(
    "studies",
    metadata,
    Column("id", ID, primary_key=True),
    Column("project_id", String, nullable=False, index=True),
    Column("folder_name", String(64), nullable=False, unique=True),
    Column("title", String(120), nullable=False),
    Column("status", String, nullable=False, server_default="ACTIVE"),
    Column("final_model_id", ID, ForeignKey("models.id", use_alter=True, name="fk_studies_final_model"), nullable=True),
    Column("final_set_by", String, nullable=True),
    Column("final_set_at", TS, nullable=True),
    Column("ai_root_snapshot", String, nullable=False),
    Column("created_by", String, nullable=False),
    Column("created_by_name", String, nullable=False),
    Column("created_at", TS, nullable=False, server_default=func.now()),
    Column("updated_at", TS, nullable=False, server_default=func.now()),
    Column("version", BigInteger, nullable=False, server_default="1"),
    CheckConstraint("status IN ('ACTIVE','ARCHIVED')", name="ck_studies_status"),
    CheckConstraint("folder_name ~ '^[A-Za-z0-9][A-Za-z0-9_\\-]{0,63}$'", name="ck_studies_folder_name"),
)

jobs = Table(
    "jobs",
    metadata,
    Column("id", ID, primary_key=True),
    Column("study_id", ID, ForeignKey("studies.id"), nullable=False),
    Column("project_id", String, nullable=False),
    Column("job_type", String, nullable=False),
    Column("stage", SmallInteger, nullable=False),
    Column("lane", String, nullable=False),
    Column("state", String, nullable=False),
    Column("attention_code", String, nullable=True),
    Column("holds_slot", Boolean, nullable=False, server_default=text("false")),
    Column("queue_seq", BigInteger, nullable=True),
    Column("next_notified_at", TS, nullable=True),
    Column("queued_at", TS, nullable=True),
    Column("started_at", TS, nullable=True),
    Column("finished_at", TS, nullable=True),
    Column("current_step_no", Integer, nullable=True),
    Column("progress_pct", Float, nullable=True),
    Column("progress_label", String, nullable=True),
    Column("params", JSONB, nullable=False),
    Column("result", JSONB, nullable=True),
    Column("warnings", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("env_snapshot", JSONB, nullable=True),
    Column("failure_code", String, nullable=True),
    Column("failure_message", String(500), nullable=True),
    Column("cancel_requested_at", TS, nullable=True),
    Column("cancel_requested_by", String, nullable=True),
    Column("retry_of_job_id", ID, ForeignKey("jobs.id"), nullable=True),
    Column("resume_from_step", Integer, nullable=True),
    Column("lease_owner_id", String, nullable=True),
    Column("lease_token", String, nullable=True),
    Column("lease_generation", BigInteger, nullable=False, server_default="0"),
    Column("lease_acquired_at", TS, nullable=True),
    Column("lease_expires_at", TS, nullable=True),
    Column("created_by", String, nullable=False),
    Column("created_by_name", String, nullable=False),
    Column("created_at", TS, nullable=False, server_default=func.now()),
    Column("updated_at", TS, nullable=False, server_default=func.now()),
    Column("version", BigInteger, nullable=False, server_default="1"),
    CheckConstraint("lane IN ('SLOT','LIGHT','PREVIEW')", name="ck_jobs_lane"),  # PREVIEW: geometry-view.md §6.2(0017_geom_view)
    CheckConstraint("stage BETWEEN 0 AND 5", name="ck_jobs_stage"),
    CheckConstraint(
        "state IN ('QUEUED','RUNNING','WAITING_HPC','COLLECTING','SUCCEEDED','FAILED','CANCELED','INTERRUPTED')",
        name="ck_jobs_state",
    ),
    CheckConstraint("holds_slot = (state = 'RUNNING' AND lane = 'SLOT')", name="ck_jobs_holds_slot"),
    CheckConstraint("(queue_seq IS NOT NULL) = (state = 'QUEUED')", name="ck_jobs_queue_seq"),
    CheckConstraint(
        "(lease_owner_id IS NULL AND lease_token IS NULL AND lease_acquired_at IS NULL AND lease_expires_at IS NULL)"
        " OR (lease_owner_id IS NOT NULL AND lease_token IS NOT NULL AND lease_acquired_at IS NOT NULL"
        " AND lease_expires_at IS NOT NULL AND lease_expires_at > lease_acquired_at)",
        name="ck_jobs_lease_identity",
    ),
    CheckConstraint("lease_token IS NULL OR state IN ('RUNNING','COLLECTING')", name="ck_jobs_lease_state"),
    CheckConstraint(
        "(state NOT IN ('FAILED','INTERRUPTED')) OR failure_code IS NOT NULL", name="ck_jobs_failure_code"
    ),
)
Index("ix_jobs_state_lane_seq", jobs.c.state, jobs.c.lane, jobs.c.queue_seq)
Index("ix_jobs_study_created", jobs.c.study_id, jobs.c.created_at.desc())
Index("ix_jobs_creator_created", jobs.c.created_by, jobs.c.created_at.desc())
Index(
    "ux_jobs_study_type_active",
    jobs.c.study_id,
    jobs.c.job_type,
    unique=True,
    # phase3 §14.5: 일괄 예측 하위 PREDICT(params.batch_run)는 같은 Study에 여러 개 대기하므로 제외(0007_predict_batch)
    # phase3 §15: 컨투어 재캡처는 예측 작업마다(같은 원래 작업만 1개 — 서비스 RECAPTURE_ACTIVE) 제외(0008_contour_capture)
    # phase3 §18.3: 내장 최적화 소유 PREDICT_BATCH(params.surrogate_opt)는 수동 배치와 함께 대기할 수 있게 제외(0010_surrogate_opt)
    postgresql_where=text("state NOT IN ('SUCCEEDED','FAILED','CANCELED','INTERRUPTED') AND (params -> 'batch_run') IS NULL"
                          " AND job_type <> 'CONTOUR_RECAPTURE'"
                          " AND NOT (job_type = 'PREDICT_BATCH' AND (params -> 'surrogate_opt') IS NOT NULL)"
                          # phase3 §21.3.4 S16: FEM_VERIFY·동반 PREDICT(params.fem_verify_id) 제외(0013_fem_verify)
                          " AND job_type <> 'FEM_VERIFY'"
                          " AND NOT (job_type = 'PREDICT' AND (params -> 'fem_verify_id') IS NOT NULL)"
                          # geometry-view.md §6.7: 미리보기·결과 3D 컨투어는 캐시 행·서비스 규칙이 동시 제한(0017_geom_view)
                          " AND job_type NOT IN ('GEOM_PREVIEW','CONTOUR_3D')"
                          # equiv-check.md §4.5: 등가성 판정은 Study당 equiv_check.max_active(서비스 규칙)로 동시 제한(0018_equiv_check)
                          " AND job_type <> 'EQ_CHECK'"),
)
