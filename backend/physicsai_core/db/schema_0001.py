"""1차 스키마 동결본(0001_initial 전용). 수정 금지.

0001_initial migration은 이 메타데이터를 그대로 만든다(B14). 현재 스키마는 tables.py, 이후 변경은 0002 이후
migration의 명시적 DDL로 적는다. 0001이 tables.py를 쓰면 2차 테이블까지 0001에서 만들어지므로 분리했다.
"""

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
    MetaData,
    Numeric,
    Sequence,
    SmallInteger,
    String,
    Table,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP

metadata = MetaData()

TS = TIMESTAMP(timezone=True)
ID = String(36)

job_queue_seq = Sequence("job_queue_seq", metadata=metadata)

TERMINAL_STATES = ("SUCCEEDED", "FAILED", "CANCELED", "INTERRUPTED")


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
    CheckConstraint("lane IN ('SLOT','LIGHT')", name="ck_jobs_lane"),
    CheckConstraint("stage BETWEEN 1 AND 5", name="ck_jobs_stage"),
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
    postgresql_where=text("state NOT IN ('SUCCEEDED','FAILED','CANCELED','INTERRUPTED')"),
)

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
    Column("pscfg_rel", String, nullable=False),
    Column("pscfg_sha256", String(64), nullable=False),
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
    UniqueConstraint("study_id", "name", "version", name="uq_models_study_name_version"),
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
    Column("tpl_rel", String, nullable=False),
    Column("assem_rel", String, nullable=False),
    Column("starter_name", String, nullable=False),
    Column("tpl_params", JSONB, nullable=False),
    Column("is_current", Boolean, nullable=False, server_default=text("false")),
    Column("registered_by", String, nullable=False),
    Column("registered_by_name", String, nullable=False),
    Column("registered_at", TS, nullable=False, server_default=func.now()),
)
Index("ux_param_sets_current", param_sets.c.study_id, unique=True, postgresql_where=text("is_current"))

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
    CheckConstraint(
        "kind IN ('PREVIEW_JSON','PREVIEW_IMAGE','CURVE_JSON','RESPONSE_TABLE','SCORE_FILE','PACKAGE_COMMANDS','SPLIT_JSON')",
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
        "event IN ('JOB_STARTED','JOB_SUCCEEDED','JOB_FAILED','JOB_CANCELED','JOB_INTERRUPTED','MY_TURN_NEXT','HPC_COLLECTED')",
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

audit_events = Table(
    "audit_events",
    metadata,
    Column("id", ID, primary_key=True),
    Column("occurred_at", TS, nullable=False, server_default=func.now()),
    Column("user_id", String, nullable=False),
    Column("username", String, nullable=True),
    Column("action", String, nullable=False),
    Column("target_type", String, nullable=False),
    Column("target_id", String, nullable=True),
    Column("detail", JSONB, nullable=True),
    Column("request_id", String, nullable=True),
    Column("client_ip", String, nullable=True),
)

__all__ = [
    "metadata",
    "job_queue_seq",
    "studies",
    "jobs",
    "datasets",
    "models",
    "param_sets",
    "job_steps",
    "artifacts",
    "notifications",
    "worker_slot",
    "worker_heartbeats",
    "hpc_jobs",
    "audit_events",
    "TERMINAL_STATES",
]
