"""0002_phase2 — 2차 스키마(phase2 §5). 명시적 DDL(B14).

- 새 테이블: train_setups, train_does, train_runs, curations, spdm_imports, optimizations, env_checks
- param_sets: origin, train_doe_id(FK train_does)
- artifacts.kind CHECK, notifications.event CHECK 확장
- hpc_jobs (job_id, state) 인덱스

Revision ID: 0002_phase2
Revises: 0001_initial
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP

revision = "0002_phase2"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

TS = TIMESTAMP(timezone=True)
ID = sa.String(36)
EMPTY_ARR = sa.text("'[]'::jsonb")
EMPTY_OBJ = sa.text("'{}'::jsonb")

ARTIFACT_KINDS = (
    "'PREVIEW_JSON','PREVIEW_IMAGE','CURVE_JSON','RESPONSE_TABLE','SCORE_FILE','PACKAGE_COMMANDS','SPLIT_JSON',"
    "'CURATION_CFG','FILE_LIST','DOE_SAMPLES','RUN_CONFIG','OPT_SUMMARY','OPT_FILE'"
)
NOTIFICATION_EVENTS = (
    "'JOB_STARTED','JOB_SUCCEEDED','JOB_FAILED','JOB_CANCELED','JOB_INTERRUPTED','MY_TURN_NEXT','HPC_COLLECTED',"
    "'HPC_PARTIAL_FAILED','ENV_CHECK_DONE'"
)


def upgrade() -> None:
    op.create_table(
        "train_setups",
        sa.Column("id", ID, primary_key=True),
        sa.Column("study_id", ID, sa.ForeignKey("studies.id"), nullable=False, unique=True),
        sa.Column("cad_source_path", sa.String, nullable=True),
        sa.Column("cad_file_name", sa.String, nullable=True),
        sa.Column("cad_sha256", sa.String(64), nullable=True),
        sa.Column("extract_job_id", ID, sa.ForeignKey("jobs.id"), nullable=True),
        sa.Column("parameters", JSONB, nullable=False, server_default=EMPTY_ARR),
        sa.Column("tpl_rel", sa.String, nullable=True),
        sa.Column("tpl_sha256", sa.String(64), nullable=True),
        sa.Column("tpl_generated_at", TS, nullable=True),
        sa.Column("tpl_params", JSONB, nullable=True),
        sa.Column("tpl_warnings", JSONB, nullable=False, server_default=EMPTY_ARR),
        sa.Column("updated_by", sa.String, nullable=True),
        sa.Column("updated_by_name", sa.String, nullable=True),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("version", sa.BigInteger, nullable=False, server_default="1"),
    )
    op.create_table(
        "train_does",
        sa.Column("id", ID, primary_key=True),
        sa.Column("study_id", ID, sa.ForeignKey("studies.id"), nullable=False),
        sa.Column("job_id", ID, sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("doe_label", sa.String, nullable=False),
        sa.Column("doe_type", sa.String, nullable=False),
        sa.Column("num_runs_requested", sa.Integer, nullable=True),
        sa.Column("options", JSONB, nullable=False, server_default=EMPTY_OBJ),
        sa.Column("multi_execution", sa.Integer, nullable=False, server_default="1"),
        sa.Column("radioss_assem_source_path", sa.String, nullable=False),
        sa.Column("dir_rel", sa.String, nullable=False),
        sa.Column("assem_rel", sa.String, nullable=False),
        sa.Column("parameters_snapshot", JSONB, nullable=False, server_default=EMPTY_ARR),
        sa.Column("tpl_sha256", sa.String(64), nullable=True),
        sa.Column("run_count", sa.Integer, nullable=True),
        sa.Column("sample_status", sa.String, nullable=False, server_default="PENDING"),
        sa.Column("samples_rel", sa.String, nullable=True),
        sa.Column("responses_rel", sa.String, nullable=True),
        sa.Column("status", sa.String, nullable=False, server_default="BUILDING"),
        sa.Column("created_by", sa.String, nullable=False),
        sa.Column("created_by_name", sa.String, nullable=False),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("sample_status IN ('PARSED','PARTIAL','MISSING','PENDING')", name="ck_train_does_sample_status"),
        sa.CheckConstraint("status IN ('BUILDING','READY','FAILED')", name="ck_train_does_status"),
    )
    op.create_index("ix_train_does_study_id", "train_does", ["study_id"])
    op.create_table(
        "train_runs",
        sa.Column("id", ID, primary_key=True),
        sa.Column("doe_id", ID, sa.ForeignKey("train_does.id"), nullable=False),
        sa.Column("run_key", sa.String(64), nullable=False),
        sa.Column("input_rel", sa.String, nullable=False),
        sa.Column("starter_name", sa.String, nullable=False),
        sa.Column("state", sa.String, nullable=False, server_default="GENERATED"),
        sa.Column("last_job_id", ID, sa.ForeignKey("jobs.id"), nullable=True),
        sa.Column("hpc_job_id", ID, sa.ForeignKey("hpc_jobs.id"), nullable=True),
        sa.Column("result_rel", sa.String, nullable=True),
        sa.Column("result_summary", JSONB, nullable=True),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("doe_id", "run_key", name="uq_train_runs_doe_run"),
        sa.CheckConstraint(
            "state IN ('GENERATED','SUBMITTED','SOLVED','SOLVE_FAILED','COLLECTED','COLLECT_FAILED')",
            name="ck_train_runs_state",
        ),
    )
    op.create_index("ix_train_runs_doe_state", "train_runs", ["doe_id", "state"])
    op.create_table(
        "curations",
        sa.Column("id", ID, primary_key=True),
        sa.Column("study_id", ID, sa.ForeignKey("studies.id"), nullable=False),
        sa.Column("job_id", ID, sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("kind", sa.String, nullable=False),
        sa.Column("source", JSONB, nullable=False),
        sa.Column("preview_job_id", ID, sa.ForeignKey("jobs.id"), nullable=True),
        sa.Column("selection", JSONB, nullable=False, server_default=EMPTY_OBJ),
        sa.Column("output_rel", sa.String, nullable=False),
        sa.Column("file_list_rel", sa.String, nullable=False),
        sa.Column("target_count", sa.Integer, nullable=True),
        sa.Column("ok_count", sa.Integer, nullable=True),
        sa.Column("failed_count", sa.Integer, nullable=True),
        sa.Column("missing_runs", JSONB, nullable=False, server_default=EMPTY_ARR),
        sa.Column("status", sa.String, nullable=False, server_default="BUILDING"),
        sa.Column("created_by", sa.String, nullable=False),
        sa.Column("created_by_name", sa.String, nullable=False),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("kind IN ('H3D','T01')", name="ck_curations_kind"),
        sa.CheckConstraint("status IN ('BUILDING','READY','FAILED')", name="ck_curations_status"),
    )
    op.create_index("ix_curations_study_id", "curations", ["study_id"])
    op.create_table(
        "spdm_imports",
        sa.Column("id", ID, primary_key=True),
        sa.Column("study_id", ID, sa.ForeignKey("studies.id"), nullable=False),
        sa.Column("job_id", ID, sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("spdm_path", sa.String, nullable=False),
        sa.Column("dest_rel", sa.String, nullable=False),
        sa.Column("file_count", sa.Integer, nullable=True),
        sa.Column("total_bytes", sa.BigInteger, nullable=True),
        sa.Column("renamed_count", sa.Integer, nullable=True),
        sa.Column("manifest_rel", sa.String, nullable=True),
        sa.Column("status", sa.String, nullable=False, server_default="BUILDING"),
        sa.Column("created_by", sa.String, nullable=False),
        sa.Column("created_by_name", sa.String, nullable=False),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('BUILDING','READY','FAILED')", name="ck_spdm_imports_status"),
    )
    op.create_index("ix_spdm_imports_study_id", "spdm_imports", ["study_id"])
    op.create_table(
        "optimizations",
        sa.Column("id", ID, primary_key=True),
        sa.Column("study_id", ID, sa.ForeignKey("studies.id"), nullable=False),
        sa.Column("job_id", ID, sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("approach", sa.String, nullable=False),
        sa.Column("opt_method", sa.String, nullable=False),
        sa.Column("max_designs", sa.Integer, nullable=False),
        sa.Column("model_id", ID, sa.ForeignKey("models.id"), nullable=False),
        sa.Column("param_set_id", ID, sa.ForeignKey("param_sets.id"), nullable=False),
        sa.Column("study_folder", sa.String(64), nullable=False),
        sa.Column("dir_rel", sa.String, nullable=False),
        sa.Column("runs_started", sa.Integer, nullable=True),
        sa.Column("responses", JSONB, nullable=False, server_default=EMPTY_ARR),
        sa.Column("summary_status", sa.String, nullable=False, server_default="NONE"),
        sa.Column("summary_meta", JSONB, nullable=True),
        sa.Column("file_count", sa.Integer, nullable=True),
        sa.Column("status", sa.String, nullable=False, server_default="RUNNING"),
        sa.Column("created_by", sa.String, nullable=False),
        sa.Column("created_by_name", sa.String, nullable=False),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("approach IN ('OPT','DOE')", name="ck_optimizations_approach"),
        sa.CheckConstraint("opt_method IN ('ARSM','GRSM','SQP')", name="ck_optimizations_method"),
        sa.CheckConstraint("summary_status IN ('NONE','PARSED','UNRECOGNIZED')", name="ck_optimizations_summary_status"),
        sa.CheckConstraint("status IN ('RUNNING','DONE','FAILED')", name="ck_optimizations_status"),
    )
    op.create_index("ix_optimizations_study_id", "optimizations", ["study_id"])
    op.create_table(
        "env_checks",
        sa.Column("id", ID, primary_key=True),
        sa.Column("state", sa.String, nullable=False, server_default="PENDING"),
        sa.Column("requested_by", sa.String, nullable=False),
        sa.Column("requested_by_name", sa.String, nullable=False),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", TS, nullable=False),
        sa.Column("worker_id", sa.String, nullable=True),
        sa.Column("started_at", TS, nullable=True),
        sa.Column("finished_at", TS, nullable=True),
        sa.Column("api_items", JSONB, nullable=False, server_default=EMPTY_ARR),
        sa.Column("worker_items", JSONB, nullable=True),
        sa.Column("summary", JSONB, nullable=False, server_default=EMPTY_OBJ),
        sa.Column("report_rel", sa.String, nullable=True),
        sa.Column("failure_message", sa.String(500), nullable=True),
        sa.CheckConstraint("state IN ('PENDING','RUNNING','DONE','FAILED','EXPIRED')", name="ck_env_checks_state"),
    )
    op.execute("CREATE INDEX ix_env_checks_created ON env_checks (created_at DESC)")
    op.execute("CREATE UNIQUE INDEX ux_env_checks_active ON env_checks ((true)) WHERE state IN ('PENDING','RUNNING')")

    # ---- 기존 테이블 변경(phase2 §5.8) ----
    op.add_column("param_sets", sa.Column("origin", sa.String, nullable=False, server_default="FOLDER"))
    op.add_column("param_sets", sa.Column("train_doe_id", ID, nullable=True))
    op.create_foreign_key("fk_param_sets_train_doe", "param_sets", "train_does", ["train_doe_id"], ["id"])
    op.create_check_constraint("ck_param_sets_origin", "param_sets", "origin IN ('FOLDER','TRAIN_DOE')")

    op.drop_constraint("ck_artifacts_kind", "artifacts", type_="check")
    op.create_check_constraint("ck_artifacts_kind", "artifacts", f"kind IN ({ARTIFACT_KINDS})")
    op.drop_constraint("ck_notifications_event", "notifications", type_="check")
    op.create_check_constraint("ck_notifications_event", "notifications", f"event IN ({NOTIFICATION_EVENTS})")

    op.create_index("ix_hpc_jobs_job_state", "hpc_jobs", ["job_id", "state"])


def downgrade() -> None:
    raise RuntimeError("PhysicsAI migration은 downgrade를 지원하지 않습니다(데이터 보호)")
