"""0018_equiv_check — ⑤ 해석 등가성 판정(equiv-check.md §5.1). 명시적 DDL(B14).

- 새 테이블 eq_recipes(레시피 버전 행, 소프트 삭제)·eq_checks(판정 이력 — 스냅숏·대상·요약 수치만, 쌍별 값은 파일)
- ux_jobs_study_type_active: EQ_CHECK 제외(Study당 동시 equiv_check.max_active는 서비스가 검사)
- notifications.event CHECK에 EQ_CHECK_DONE 추가
- 다운그레이드: 두 테이블에 행이 하나라도 있으면 거부(데이터 보존, S17 0014 선례), 없으면 되돌림

Revision ID: 0018_equiv_check
Revises: 0017_geom_view
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP

revision = "0018_equiv_check"
down_revision = "0017_geom_view"
branch_labels = None
depends_on = None

TS = TIMESTAMP(timezone=True)
ID = sa.String(36)

OLD_EVENTS = (
    "'JOB_STARTED','JOB_SUCCEEDED','JOB_FAILED','JOB_CANCELED','JOB_INTERRUPTED','MY_TURN_NEXT','HPC_COLLECTED',"
    "'HPC_PARTIAL_FAILED','ENV_CHECK_DONE','HPC_CANCEL_FAILED','PREDICT_BATCH_DONE','HPC_SUBMISSION_UNKNOWN',"
    "'SURROGATE_OPT_DONE','FEM_VERIFY_DONE'"
)
NEW_EVENTS = OLD_EVENTS + ",'EQ_CHECK_DONE'"
ACTIVE_WHERE_OLD = ("state NOT IN ('SUCCEEDED','FAILED','CANCELED','INTERRUPTED') AND (params -> 'batch_run') IS NULL"
                    " AND job_type <> 'CONTOUR_RECAPTURE'"
                    " AND NOT (job_type = 'PREDICT_BATCH' AND (params -> 'surrogate_opt') IS NOT NULL)"
                    " AND job_type <> 'FEM_VERIFY'"
                    " AND NOT (job_type = 'PREDICT' AND (params -> 'fem_verify_id') IS NOT NULL)"
                    " AND job_type NOT IN ('GEOM_PREVIEW','CONTOUR_3D')")
ACTIVE_WHERE_NEW = ACTIVE_WHERE_OLD + " AND job_type <> 'EQ_CHECK'"


def upgrade() -> None:
    op.create_table(
        "eq_recipes",
        sa.Column("id", ID, primary_key=True),
        sa.Column("recipe_key", ID, nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("scope", sa.String(8), nullable=False),
        sa.Column("study_id", ID, sa.ForeignKey("studies.id"), nullable=True),
        sa.Column("name", sa.String(60), nullable=False),
        sa.Column("description", sa.String(500), nullable=False, server_default=""),
        sa.Column("definition", JSONB(), nullable=False),
        sa.Column("parent_key", ID, nullable=True),
        sa.Column("parent_version", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("created_by_name", sa.String(), nullable=False),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", TS, nullable=True),
        sa.Column("deleted_by", sa.String(), nullable=True),
        sa.UniqueConstraint("recipe_key", "version", name="uq_eq_recipes_key_version"),
        sa.CheckConstraint("version >= 1", name="ck_eq_recipes_version"),
        sa.CheckConstraint("scope IN ('study','global')", name="ck_eq_recipes_scope"),
        sa.CheckConstraint("(scope = 'study') = (study_id IS NOT NULL)", name="ck_eq_recipes_scope_study"),
    )
    op.create_index("ix_eq_recipes_study_name", "eq_recipes", ["scope", "study_id", sa.text("lower(name)")],
                    postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_index("ix_eq_recipes_key", "eq_recipes", ["recipe_key", sa.text("version DESC")])
    op.create_table(
        "eq_checks",
        sa.Column("id", ID, primary_key=True),
        sa.Column("study_id", ID, sa.ForeignKey("studies.id"), nullable=False),
        sa.Column("eq_no", sa.Integer(), nullable=False),
        sa.Column("job_id", ID, sa.ForeignKey("jobs.id"), nullable=True),
        sa.Column("recipe_key", ID, nullable=True),
        sa.Column("recipe_version", sa.Integer(), nullable=True),
        sa.Column("recipe_source", sa.String(8), nullable=False),
        sa.Column("modified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("recipe_snapshot", JSONB(), nullable=False),
        sa.Column("side_a", JSONB(), nullable=False),
        sa.Column("side_b", JSONB(), nullable=False),
        sa.Column("pairing", JSONB(), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("verdict", sa.String(12), nullable=True),
        sa.Column("summary", JSONB(), nullable=True),
        sa.Column("failure_code", sa.String(32), nullable=True),
        sa.Column("failure_message", sa.String(500), nullable=True),
        sa.Column("note", sa.String(500), nullable=True),
        sa.Column("dir_rel", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("created_by_name", sa.String(), nullable=False),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", TS, nullable=True),
        sa.UniqueConstraint("study_id", "eq_no", name="uq_eq_checks_study_no"),
        sa.CheckConstraint("eq_no >= 1", name="ck_eq_checks_eq_no"),
        sa.CheckConstraint("recipe_source IN ('system','user','adhoc')", name="ck_eq_checks_recipe_source"),
        sa.CheckConstraint("status IN ('RUNNING','DONE','FAILED','CANCELED')", name="ck_eq_checks_status"),
        sa.CheckConstraint("verdict IS NULL OR verdict IN ('PASS','FAIL','INCOMPLETE')", name="ck_eq_checks_verdict"),
    )
    op.create_index("ix_eq_checks_study_created", "eq_checks", ["study_id", sa.text("created_at DESC")])
    op.create_index("ix_eq_checks_job", "eq_checks", ["job_id"])
    op.create_index("ix_eq_checks_recipe", "eq_checks", ["recipe_key"])
    op.drop_constraint("ck_notifications_event", "notifications", type_="check")
    op.create_check_constraint("ck_notifications_event", "notifications", f"event IN ({NEW_EVENTS})")
    op.drop_index("ux_jobs_study_type_active", table_name="jobs")
    op.create_index("ux_jobs_study_type_active", "jobs", ["study_id", "job_type"], unique=True,
                    postgresql_where=sa.text(ACTIVE_WHERE_NEW))


def downgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT (SELECT count(*) FROM eq_recipes) + (SELECT count(*) FROM eq_checks)")).scalar()
    jobs = bind.execute(sa.text("SELECT count(*) FROM jobs WHERE job_type = 'EQ_CHECK'")).scalar()
    notes = bind.execute(sa.text("SELECT count(*) FROM notifications WHERE event = 'EQ_CHECK_DONE'")).scalar()
    if rows or jobs or notes:
        raise RuntimeError(f"등가성 판정 레시피·이력 {rows}행·작업 {jobs}개·알림 {notes}건이 있어 0018을 되돌릴 수 없습니다(데이터 보호)")
    op.drop_index("ux_jobs_study_type_active", table_name="jobs")
    op.create_index("ux_jobs_study_type_active", "jobs", ["study_id", "job_type"], unique=True,
                    postgresql_where=sa.text(ACTIVE_WHERE_OLD))
    op.drop_constraint("ck_notifications_event", "notifications", type_="check")
    op.create_check_constraint("ck_notifications_event", "notifications", f"event IN ({OLD_EVENTS})")
    op.drop_table("eq_checks")
    op.drop_table("eq_recipes")
