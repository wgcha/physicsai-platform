"""0010_surrogate_opt — ⑤ 플랫폼 내장 최적화(phase3 §18.3 S13, D3-60). 명시적 DDL(B14).

- 새 테이블 surrogate_opts(부분 유일 ux_surrogate_opts_active: Study당 진행 중 1개), surrogate_opt_iters
- notifications.event CHECK에 SURROGATE_OPT_DONE 추가
- ux_jobs_study_type_active: 최적화 소유 PREDICT_BATCH(params.surrogate_opt) 제외 — 사용자 수동 배치와 함께 대기 가능

Revision ID: 0010_surrogate_opt
Revises: 0009_scx_gateway
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP

revision = "0010_surrogate_opt"
down_revision = "0009_scx_gateway"
branch_labels = None
depends_on = None

TS = TIMESTAMP(timezone=True)
ID = sa.String(36)

NOTIFICATION_EVENTS = (
    "'JOB_STARTED','JOB_SUCCEEDED','JOB_FAILED','JOB_CANCELED','JOB_INTERRUPTED','MY_TURN_NEXT','HPC_COLLECTED',"
    "'HPC_PARTIAL_FAILED','ENV_CHECK_DONE','HPC_CANCEL_FAILED','PREDICT_BATCH_DONE','HPC_SUBMISSION_UNKNOWN',"
    "'SURROGATE_OPT_DONE'"
)
ACTIVE_WHERE_NEW = ("state NOT IN ('SUCCEEDED','FAILED','CANCELED','INTERRUPTED') AND (params -> 'batch_run') IS NULL"
                    " AND job_type <> 'CONTOUR_RECAPTURE'"
                    " AND NOT (job_type = 'PREDICT_BATCH' AND (params -> 'surrogate_opt') IS NOT NULL)")


def upgrade() -> None:
    op.create_table(
        "surrogate_opts",
        sa.Column("id", ID, primary_key=True),
        sa.Column("study_id", ID, sa.ForeignKey("studies.id"), nullable=False),
        sa.Column("opt_no", sa.Integer(), nullable=False),
        sa.Column("param_set_id", ID, sa.ForeignKey("param_sets.id"), nullable=False),
        sa.Column("model_id", ID, sa.ForeignKey("models.id"), nullable=False),
        sa.Column("input_kind", sa.String(16), nullable=False),
        sa.Column("settings", JSONB(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("iter_no", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("current_job_id", ID, sa.ForeignKey("jobs.id"), nullable=True),
        sa.Column("best", JSONB(), nullable=True),
        sa.Column("stop_reason", sa.String(32), nullable=True),
        sa.Column("dir_rel", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("created_by_name", sa.String(), nullable=False),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", TS, nullable=True),
        sa.UniqueConstraint("study_id", "opt_no", name="uq_surrogate_opts_study_no"),
        sa.CheckConstraint("opt_no >= 1", name="ck_surrogate_opts_opt_no"),
        sa.CheckConstraint("status IN ('EXPLORING','FITTING','VERIFYING','DONE','FAILED','CANCELED')",
                           name="ck_surrogate_opts_status"),
        sa.CheckConstraint("input_kind IN ('mesh_only','assembly')", name="ck_surrogate_opts_input_kind"),
    )
    op.create_index("ux_surrogate_opts_active", "surrogate_opts", ["study_id"], unique=True,
                    postgresql_where=sa.text("status IN ('EXPLORING','FITTING','VERIFYING')"))
    op.create_table(
        "surrogate_opt_iters",
        sa.Column("opt_id", ID, sa.ForeignKey("surrogate_opts.id"), primary_key=True),
        sa.Column("iter_no", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("batch_id", ID, sa.ForeignKey("predict_batches.id"), nullable=False),
        sa.Column("round_job_id", ID, sa.ForeignKey("jobs.id"), nullable=True),
        sa.Column("fit", JSONB(), nullable=True),
        sa.Column("candidates", JSONB(), nullable=True),
        sa.Column("best_value", sa.Float(), nullable=True),
        sa.Column("best_feasible", sa.Boolean(), nullable=True),
        sa.Column("improvement_rel", sa.Float(), nullable=True),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("iter_no >= 0", name="ck_surrogate_opt_iters_iter_no"),
        sa.CheckConstraint("kind IN ('EXPLORE','REUSE','VERIFY')", name="ck_surrogate_opt_iters_kind"),
    )
    op.create_index("ix_surrogate_opt_iters_batch", "surrogate_opt_iters", ["batch_id"])
    op.drop_constraint("ck_notifications_event", "notifications", type_="check")
    op.create_check_constraint("ck_notifications_event", "notifications", f"event IN ({NOTIFICATION_EVENTS})")
    op.drop_index("ux_jobs_study_type_active", table_name="jobs")
    op.create_index("ux_jobs_study_type_active", "jobs", ["study_id", "job_type"], unique=True,
                    postgresql_where=sa.text(ACTIVE_WHERE_NEW))


def downgrade() -> None:
    raise RuntimeError("PhysicsAI migration은 downgrade를 지원하지 않습니다(데이터 보호)")
