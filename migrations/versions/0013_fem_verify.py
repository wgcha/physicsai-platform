"""0013_fem_verify — ④ 조립 FEM 검증(phase3 §21.3.4 S16, D3-64). 명시적 DDL(B14).

- 새 테이블 fem_verifications(Study별 fv_no, 출처·예측·조립·실행·요약 — 수치·경로·상태만)
- ux_jobs_study_type_active: FEM_VERIFY·동반 PREDICT(params.fem_verify_id) 제외(Study당 동시 fem_verify.max_active는 서비스가 검사)
- notifications.event CHECK에 FEM_VERIFY_DONE 추가

Revision ID: 0013_fem_verify
Revises: 0012_sampling_kinds
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP

revision = "0013_fem_verify"
down_revision = "0012_sampling_kinds"
branch_labels = None
depends_on = None

TS = TIMESTAMP(timezone=True)
ID = sa.String(36)

NOTIFICATION_EVENTS = (
    "'JOB_STARTED','JOB_SUCCEEDED','JOB_FAILED','JOB_CANCELED','JOB_INTERRUPTED','MY_TURN_NEXT','HPC_COLLECTED',"
    "'HPC_PARTIAL_FAILED','ENV_CHECK_DONE','HPC_CANCEL_FAILED','PREDICT_BATCH_DONE','HPC_SUBMISSION_UNKNOWN',"
    "'SURROGATE_OPT_DONE','FEM_VERIFY_DONE'"
)
ACTIVE_WHERE_NEW = ("state NOT IN ('SUCCEEDED','FAILED','CANCELED','INTERRUPTED') AND (params -> 'batch_run') IS NULL"
                    " AND job_type <> 'CONTOUR_RECAPTURE'"
                    " AND NOT (job_type = 'PREDICT_BATCH' AND (params -> 'surrogate_opt') IS NOT NULL)"
                    " AND job_type <> 'FEM_VERIFY'"
                    " AND NOT (job_type = 'PREDICT' AND (params -> 'fem_verify_id') IS NOT NULL)")


def upgrade() -> None:
    op.create_table(
        "fem_verifications",
        sa.Column("id", ID, primary_key=True),
        sa.Column("study_id", ID, sa.ForeignKey("studies.id"), nullable=False),
        sa.Column("fv_no", sa.Integer(), nullable=False),
        sa.Column("source_kind", sa.String(16), nullable=False),
        sa.Column("source_ref", JSONB(), nullable=False),
        sa.Column("predict_job_id", ID, sa.ForeignKey("jobs.id"), nullable=True),
        sa.Column("companion", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("param_set_id", ID, sa.ForeignKey("param_sets.id"), nullable=True),
        sa.Column("model_id", ID, sa.ForeignKey("models.id"), nullable=True),
        sa.Column("template_kind", sa.String(16), nullable=True),
        sa.Column("assem_kind", sa.String(16), nullable=False),
        sa.Column("assem_ref", JSONB(), nullable=True),
        sa.Column("input_mode", sa.String(8), nullable=False),
        sa.Column("options", JSONB(), nullable=True),
        sa.Column("job_id", ID, sa.ForeignKey("jobs.id"), nullable=True),
        sa.Column("attempt_no", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("summary", JSONB(), nullable=True),
        sa.Column("failure_code", sa.String(32), nullable=True),
        sa.Column("failure_message", sa.String(500), nullable=True),
        sa.Column("dir_rel", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("created_by_name", sa.String(), nullable=False),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", TS, nullable=True),
        sa.UniqueConstraint("study_id", "fv_no", name="uq_fem_verifications_study_no"),
        sa.CheckConstraint("fv_no >= 1", name="ck_fem_verifications_fv_no"),
        sa.CheckConstraint("source_kind IN ('PREDICT_JOB','BATCH_RUN','VALUES','OPT_DESIGN')",
                           name="ck_fem_verifications_source_kind"),
        sa.CheckConstraint("assem_kind IN ('PREDICT_INPUT','TRAIN_DOE','CUSTOM')", name="ck_fem_verifications_assem_kind"),
        sa.CheckConstraint("input_mode IN ('reuse','rebuild')", name="ck_fem_verifications_input_mode"),
        sa.CheckConstraint("status IN ('WAITING_PREDICT','RUNNING','DONE','FAILED','CANCELED')",
                           name="ck_fem_verifications_status"),
    )
    op.create_index("ix_fem_verifications_study_created", "fem_verifications", ["study_id", sa.text("created_at DESC")])
    op.create_index("ix_fem_verifications_predict_job", "fem_verifications", ["predict_job_id"])
    op.drop_constraint("ck_notifications_event", "notifications", type_="check")
    op.create_check_constraint("ck_notifications_event", "notifications", f"event IN ({NOTIFICATION_EVENTS})")
    op.drop_index("ux_jobs_study_type_active", table_name="jobs")
    op.create_index("ux_jobs_study_type_active", "jobs", ["study_id", "job_type"], unique=True,
                    postgresql_where=sa.text(ACTIVE_WHERE_NEW))


def downgrade() -> None:
    raise RuntimeError("PhysicsAI migration은 downgrade를 지원하지 않습니다(데이터 보호)")
