"""0007_predict_batch — 템플릿 예측·DOE 일괄 예측(phase3 §14.3 S9, D3-49). 명시적 DDL(B14).

- param_sets: input_kind('assembly' 기본, 기존 행 = assembly), assem_rel·starter_name NULL 허용
  (CHECK: assembly ⇒ 둘 다 NOT NULL)
- 새 테이블 predict_batches, predict_batch_runs
- notifications.event CHECK에 PREDICT_BATCH_DONE 추가
- ux_jobs_study_type_active: 일괄 예측 하위 PREDICT(params.batch_run 있음)는 제외 — 한 Study에 하위가 N개 대기한다(§14.5 BP_ENQUEUE)

Revision ID: 0007_predict_batch
Revises: 0006_param_set_label
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP

revision = "0007_predict_batch"
down_revision = "0006_param_set_label"
branch_labels = None
depends_on = None

TS = TIMESTAMP(timezone=True)
ID = sa.String(36)

NOTIFICATION_EVENTS = (
    "'JOB_STARTED','JOB_SUCCEEDED','JOB_FAILED','JOB_CANCELED','JOB_INTERRUPTED','MY_TURN_NEXT','HPC_COLLECTED',"
    "'HPC_PARTIAL_FAILED','ENV_CHECK_DONE','HPC_CANCEL_FAILED','PREDICT_BATCH_DONE'"
)
ACTIVE_WHERE_NEW = "state NOT IN ('SUCCEEDED','FAILED','CANCELED','INTERRUPTED') AND (params -> 'batch_run') IS NULL"


def upgrade() -> None:
    # ---- param_sets: 템플릿 입력 종류(K1) ----
    op.add_column("param_sets", sa.Column("input_kind", sa.String(16), nullable=False, server_default="assembly"))
    op.alter_column("param_sets", "assem_rel", existing_type=sa.String(), nullable=True)
    op.alter_column("param_sets", "starter_name", existing_type=sa.String(), nullable=True)
    op.create_check_constraint("ck_param_sets_input_kind", "param_sets", "input_kind IN ('mesh_only','assembly')")
    op.create_check_constraint(
        "ck_param_sets_assembly_files", "param_sets",
        "input_kind <> 'assembly' OR (assem_rel IS NOT NULL AND starter_name IS NOT NULL)",
    )

    # ---- predict_batches ----
    op.create_table(
        "predict_batches",
        sa.Column("id", ID, primary_key=True),
        sa.Column("study_id", ID, sa.ForeignKey("studies.id"), nullable=False),
        sa.Column("batch_no", sa.Integer(), nullable=False),
        sa.Column("job_id", ID, sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("param_set_id", ID, sa.ForeignKey("param_sets.id"), nullable=False),
        sa.Column("model_id", ID, sa.ForeignKey("models.id"), nullable=False),
        sa.Column("input_kind", sa.String(16), nullable=False),
        sa.Column("source_kind", sa.String(16), nullable=False),
        sa.Column("source_meta", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("multi_execution", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("run_count", sa.Integer(), nullable=False),
        sa.Column("dir_rel", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="GENERATING"),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("created_by_name", sa.String(), nullable=False),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", TS, nullable=True),
        sa.UniqueConstraint("study_id", "batch_no", name="uq_predict_batches_study_no"),
        sa.CheckConstraint("batch_no >= 1", name="ck_predict_batches_batch_no"),
        sa.CheckConstraint("input_kind IN ('mesh_only','assembly')", name="ck_predict_batches_input_kind"),
        sa.CheckConstraint("source_kind IN ('LHS','TABLE','TRAIN_DOE')", name="ck_predict_batches_source_kind"),
        sa.CheckConstraint("status IN ('GENERATING','PREDICTING','DONE','FAILED','CANCELED')",
                           name="ck_predict_batches_status"),
        sa.CheckConstraint("multi_execution >= 1", name="ck_predict_batches_multi_execution"),
        sa.CheckConstraint("run_count >= 1", name="ck_predict_batches_run_count"),
    )
    op.create_index("ix_predict_batches_job", "predict_batches", ["job_id"])

    # ---- predict_batch_runs ----
    op.create_table(
        "predict_batch_runs",
        sa.Column("batch_id", ID, sa.ForeignKey("predict_batches.id"), primary_key=True),
        sa.Column("doe_no", sa.Integer(), primary_key=True),
        sa.Column("run_key", sa.String(64), nullable=False),
        sa.Column("values", JSONB(), nullable=False),
        sa.Column("applied_values", JSONB(), nullable=False),
        sa.Column("out_of_range", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("gen_state", sa.String(), nullable=False, server_default="PENDING"),
        sa.Column("gen_code", sa.String(), nullable=True),
        sa.Column("gen_message", sa.String(500), nullable=True),
        sa.Column("input_rel", sa.String(), nullable=False),
        sa.Column("predict_job_id", ID, sa.ForeignKey("jobs.id"), nullable=True),
        sa.Column("responses", JSONB(), nullable=True),
        sa.UniqueConstraint("batch_id", "run_key", name="uq_predict_batch_runs_run_key"),
        sa.CheckConstraint("doe_no >= 1", name="ck_predict_batch_runs_doe_no"),
        sa.CheckConstraint("gen_state IN ('PENDING','RUNNING','DONE','FAILED')", name="ck_predict_batch_runs_gen_state"),
    )
    op.create_index("ix_predict_batch_runs_job", "predict_batch_runs", ["predict_job_id"])

    # ---- 알림 이벤트 ----
    op.drop_constraint("ck_notifications_event", "notifications", type_="check")
    op.create_check_constraint("ck_notifications_event", "notifications", f"event IN ({NOTIFICATION_EVENTS})")

    # ---- 같은 유형 활성 작업 1개 규칙: 일괄 예측 하위 PREDICT 제외 ----
    op.drop_index("ux_jobs_study_type_active", table_name="jobs")
    op.create_index("ux_jobs_study_type_active", "jobs", ["study_id", "job_type"], unique=True,
                    postgresql_where=sa.text(ACTIVE_WHERE_NEW))


def downgrade() -> None:
    raise RuntimeError("PhysicsAI migration은 downgrade를 지원하지 않습니다(데이터 보호)")
