"""⑤ 해석 등가성 판정 테이블(equiv-check.md §5.1, migration 0018_equiv_check).

eq_recipes: 레시피 버전마다 1행(같은 recipe_key, version 증가 — 이전 버전 행 불변, 소프트 삭제는 key 단위).
eq_checks: 판정 이력(추가만). 레시피 스냅숏·대상·쌍 요약·종합 판정·지표별 집계 수치만 — 쌍×지표 값·곡선은 파일(§5.2)."""

from __future__ import annotations

from sqlalchemy import Boolean, CheckConstraint, Column, ForeignKey, Index, Integer, String, Table, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB

from ._base import ID, TS, metadata

EQ_SCOPES = ("study", "global")
EQ_RECIPE_SOURCES = ("system", "user", "adhoc")
EQ_STATUSES = ("RUNNING", "DONE", "FAILED", "CANCELED")
EQ_ACTIVE = ("RUNNING",)
EQ_VERDICTS = ("PASS", "FAIL", "INCOMPLETE")


def _in(col: str, vals: tuple[str, ...]) -> str:
    return f"{col} IN (" + ",".join(f"'{v}'" for v in vals) + ")"


eq_recipes = Table(
    "eq_recipes",
    metadata,
    Column("id", ID, primary_key=True),
    Column("recipe_key", ID, nullable=False),
    Column("version", Integer, nullable=False),
    Column("scope", String(8), nullable=False),
    Column("study_id", ID, ForeignKey("studies.id"), nullable=True),
    Column("name", String(60), nullable=False),
    Column("description", String(500), nullable=False, server_default=""),
    Column("definition", JSONB, nullable=False),
    Column("parent_key", ID, nullable=True),
    Column("parent_version", Integer, nullable=True),
    Column("created_by", String, nullable=False),
    Column("created_by_name", String, nullable=False),
    Column("created_at", TS, nullable=False, server_default=func.now()),
    Column("deleted_at", TS, nullable=True),
    Column("deleted_by", String, nullable=True),
    UniqueConstraint("recipe_key", "version", name="uq_eq_recipes_key_version"),
    CheckConstraint("version >= 1", name="ck_eq_recipes_version"),
    CheckConstraint(_in("scope", EQ_SCOPES), name="ck_eq_recipes_scope"),
    CheckConstraint("(scope = 'study') = (study_id IS NOT NULL)", name="ck_eq_recipes_scope_study"),
)
Index("ix_eq_recipes_study_name", eq_recipes.c.scope, eq_recipes.c.study_id, func.lower(eq_recipes.c.name),
      postgresql_where=text("deleted_at IS NULL"))
Index("ix_eq_recipes_key", eq_recipes.c.recipe_key, eq_recipes.c.version.desc())

eq_checks = Table(
    "eq_checks",
    metadata,
    Column("id", ID, primary_key=True),
    Column("study_id", ID, ForeignKey("studies.id"), nullable=False),
    Column("eq_no", Integer, nullable=False),
    Column("job_id", ID, ForeignKey("jobs.id"), nullable=True),
    Column("recipe_key", ID, nullable=True),
    Column("recipe_version", Integer, nullable=True),
    Column("recipe_source", String(8), nullable=False),
    Column("modified", Boolean, nullable=False, server_default=text("false")),
    Column("recipe_snapshot", JSONB, nullable=False),
    Column("side_a", JSONB, nullable=False),
    Column("side_b", JSONB, nullable=False),
    Column("pairing", JSONB, nullable=False),
    Column("status", String(10), nullable=False),
    Column("verdict", String(12), nullable=True),
    Column("summary", JSONB, nullable=True),
    Column("failure_code", String(32), nullable=True),
    Column("failure_message", String(500), nullable=True),
    Column("note", String(500), nullable=True),
    Column("dir_rel", String, nullable=False),
    Column("created_by", String, nullable=False),
    Column("created_by_name", String, nullable=False),
    Column("created_at", TS, nullable=False, server_default=func.now()),
    Column("finished_at", TS, nullable=True),
    UniqueConstraint("study_id", "eq_no", name="uq_eq_checks_study_no"),
    CheckConstraint("eq_no >= 1", name="ck_eq_checks_eq_no"),
    CheckConstraint(_in("recipe_source", EQ_RECIPE_SOURCES), name="ck_eq_checks_recipe_source"),
    CheckConstraint(_in("status", EQ_STATUSES), name="ck_eq_checks_status"),
    CheckConstraint(f"verdict IS NULL OR {_in('verdict', EQ_VERDICTS)}", name="ck_eq_checks_verdict"),
)
Index("ix_eq_checks_study_created", eq_checks.c.study_id, eq_checks.c.created_at.desc())
Index("ix_eq_checks_job", eq_checks.c.job_id)
Index("ix_eq_checks_recipe", eq_checks.c.recipe_key)
