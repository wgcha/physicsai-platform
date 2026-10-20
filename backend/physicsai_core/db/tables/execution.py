"""작업 실행 테이블: step·산출물·알림·워커 슬롯·하트비트·HPC 작업(계약 §6)."""

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
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

from ._base import ID, TS, metadata

job_steps = Table(
    "job_steps",
    metadata,
    Column("id", ID, primary_key=True),
    Column("job_id", ID, ForeignKey("jobs.id"), nullable=False),
    Column("step_no", Integer, nullable=False),
    Column("step_key", String, nullable=False),
    Column("kind", String, nullable=False),
    Column("needs_slot", Boolean, nullable=False),
    Column("state", String, nullable=False, server_default="PENDING"),
    Column("started_at", TS, nullable=True),
    Column("finished_at", TS, nullable=True),
    Column("exit_code", Integer, nullable=True),
    Column("progress_pct", Float, nullable=True),
    Column("progress_label", String, nullable=True),
    Column("command", JSONB, nullable=True),
    Column("log_rel", String, nullable=True),
    Column("outputs", JSONB, nullable=True),
    Column("failure_code", String, nullable=True),
    Column("failure_message", String(500), nullable=True),
    UniqueConstraint("job_id", "step_no", name="uq_job_steps_job_step"),
    CheckConstraint("kind IN ('LOCAL','INTERNAL','HPC_SUBMIT','HPC_WAIT','COLLECT')", name="ck_job_steps_kind"),
    CheckConstraint(
        "state IN ('PENDING','RUNNING','SUCCEEDED','FAILED','SKIPPED','CANCELED')", name="ck_job_steps_state"
    ),
)

artifacts = Table(
    "artifacts",
    metadata,
    Column("id", ID, primary_key=True),
    Column("study_id", ID, ForeignKey("studies.id"), nullable=False),
    Column("job_id", ID, ForeignKey("jobs.id"), nullable=True, index=True),
    Column("kind", String, nullable=False),
    Column("rel_path", String, nullable=False),
    Column("size", BigInteger, nullable=False),
    Column("sha256", String(64), nullable=True),
    Column("content_type", String, nullable=False),
    Column("created_at", TS, nullable=False, server_default=func.now()),
    Column("meta", JSONB, nullable=True),  # phase3 §15 컨투어 캡처 방향 {view}(0008_contour_capture)
    CheckConstraint(
        "kind IN ('PREVIEW_JSON','PREVIEW_IMAGE','CURVE_JSON','RESPONSE_TABLE','SCORE_FILE','PACKAGE_COMMANDS','SPLIT_JSON',"
        "'CURATION_CFG','FILE_LIST','DOE_SAMPLES','RUN_CONFIG','OPT_SUMMARY','OPT_FILE','CONTOUR_IMAGE','CONTOUR_VIDEO','FEATURE_PNG',"
        "'GEOM_VIEW_GLB','GEOM_VIEW_MANIFEST','GEOM_PREVIEW_GLB','GEOM_PREVIEW_FE_GLB','GEOM_PREVIEW_MANIFEST',"
        "'CONTOUR3D_GLB','CONTOUR3D_FRAMES','CONTOUR3D_MANIFEST')",
        name="ck_artifacts_kind",
    ),
)

notifications = Table(
    "notifications",
    metadata,
    Column("seq", BigInteger, primary_key=True, autoincrement=True),
    Column("user_id", String, nullable=False),
    Column("event", String, nullable=False),
    Column("job_id", ID, nullable=True),
    Column("study_id", ID, nullable=True),
    Column("project_id", String, nullable=True),
    Column("title", String(120), nullable=False),
    Column("body", String(500), nullable=False, server_default=""),
    Column("created_at", TS, nullable=False, server_default=func.now()),
    Column("read_at", TS, nullable=True),
    CheckConstraint(
        "event IN ('JOB_STARTED','JOB_SUCCEEDED','JOB_FAILED','JOB_CANCELED','JOB_INTERRUPTED','MY_TURN_NEXT','HPC_COLLECTED',"
        "'HPC_PARTIAL_FAILED','ENV_CHECK_DONE','HPC_CANCEL_FAILED','PREDICT_BATCH_DONE','HPC_SUBMISSION_UNKNOWN',"
        "'SURROGATE_OPT_DONE','FEM_VERIFY_DONE')",  # phase3 §21.3.4 S16(0013_fem_verify)
        name="ck_notifications_event",
    ),
)
Index("ix_notifications_user_seq", notifications.c.user_id, notifications.c.seq.desc())
Index("ix_notifications_unread", notifications.c.user_id, postgresql_where=text("read_at IS NULL"))

worker_slot = Table(
    "worker_slot",
    metadata,
    Column("id", SmallInteger, primary_key=True),
    Column("holder_job_id", ID, nullable=True),
    Column("lease_owner_id", String, nullable=True),
    Column("lease_token", String, nullable=True),
    Column("lease_generation", BigInteger, nullable=False, server_default="0"),
    Column("lease_acquired_at", TS, nullable=True),
    Column("lease_expires_at", TS, nullable=True),
    CheckConstraint("id = 1", name="ck_worker_slot_single"),
    CheckConstraint(
        "(lease_owner_id IS NULL AND lease_token IS NULL AND lease_acquired_at IS NULL AND lease_expires_at IS NULL)"
        " OR (lease_owner_id IS NOT NULL AND lease_token IS NOT NULL AND lease_acquired_at IS NOT NULL"
        " AND lease_expires_at IS NOT NULL AND lease_expires_at > lease_acquired_at)",
        name="ck_worker_slot_lease_identity",
    ),
    CheckConstraint("(holder_job_id IS NULL) = (lease_token IS NULL)", name="ck_worker_slot_holder"),
)

worker_heartbeats = Table(
    "worker_heartbeats",
    metadata,
    Column("worker_id", String, primary_key=True),
    Column("host", String, nullable=False),
    Column("pid", Integer, nullable=False),
    Column("app_version", String, nullable=False),
    Column("started_at", TS, nullable=False, server_default=func.now()),
    Column("last_seen_at", TS, nullable=False, server_default=func.now()),
    Column("effective_limits", JSONB, nullable=True),
    Column("resources", JSONB, nullable=True),
    Column("limiter", String, nullable=True),
)

hpc_jobs = Table(
    "hpc_jobs",
    metadata,
    Column("id", ID, primary_key=True),
    Column("job_id", ID, ForeignKey("jobs.id"), nullable=False),
    Column("step_id", ID, ForeignKey("job_steps.id"), nullable=False),
    Column("run_key", String, nullable=False),
    Column("attempt_no", Integer, nullable=False),
    Column("gateway_mode", String, nullable=False),
    Column("external_job_id", String, nullable=True),
    Column("submit_argv", JSONB, nullable=True),
    Column("state", String, nullable=False),
    Column("external_state_raw", String, nullable=True),
    Column("exit_code", Integer, nullable=True),
    Column("collect_state", String, nullable=False, server_default="NONE"),
    Column("collected", JSONB, nullable=True),
    Column("submitted_at", TS, nullable=True),
    Column("last_polled_at", TS, nullable=True),
    Column("finished_at", TS, nullable=True),
    Column("collected_at", TS, nullable=True),
    Column("unknown_count", Integer, nullable=False, server_default="0"),
    Column("error_message", String(500), nullable=True),
    Column("version", BigInteger, nullable=False, server_default="1"),
    # phase3 §16.9 scx(0009_scx_gateway): 드라이브 잡 폴더(홈 기준 상대)·제출 request_id(pai-<id>)·올린 파일·결과 위치·결과 모름 조치
    Column("remote_dir", String(1024), nullable=True),
    Column("request_id", String(128), nullable=True),
    Column("staged", JSONB, nullable=True),
    Column("output_path", String(1024), nullable=True),
    Column("output_rel", String(1024), nullable=True),
    Column("submission_unknown", Boolean, nullable=False, server_default=text("false")),
    Column("resolve_request", JSONB, nullable=True),
    Column("resolved_by", String, nullable=True),
    Column("resolved_at", TS, nullable=True),
    UniqueConstraint("job_id", "run_key", "attempt_no", name="uq_hpc_jobs_run"),
    CheckConstraint(
        "state IN ('SUBMITTING','QUEUED','RUNNING','SUCCEEDED','FAILED','CANCEL_REQUESTED','CANCELED','UNKNOWN','LOST')",
        name="ck_hpc_jobs_state",
    ),
    CheckConstraint(
        "collect_state IN ('NONE','PENDING','COLLECTING','COLLECTED','FAILED')", name="ck_hpc_jobs_collect_state"
    ),
)
Index(
    "ux_hpc_jobs_external",
    hpc_jobs.c.gateway_mode,
    hpc_jobs.c.external_job_id,
    unique=True,
    postgresql_where=text("external_job_id IS NOT NULL"),
)

Index("ix_hpc_jobs_job_state", hpc_jobs.c.job_id, hpc_jobs.c.state)
Index("ux_hpc_jobs_request_id", hpc_jobs.c.request_id, unique=True, postgresql_where=text("request_id IS NOT NULL"))
