"""extract-filter.md §6.4 / V-EF-7: migration 0019_extract_filter up/down(기존 행 NULL, 조건이 기록된 행이 있으면 down 거부, 없으면 되돌림)·
MIGRATION_HEAD·테이블 정의 일치."""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import create_engine, text

from physicsai_test_support import REPO


def _alembic(url: str, rev: str, down: bool = False) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(REPO / "migrations" / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO / "migrations"))
    cfg.attributes["url"] = url
    (command.downgrade if down else command.upgrade)(cfg, rev)


def test_migration_0019_roundtrip(pg_server):
    from physicsai_core.db import MIGRATION_HEAD

    assert MIGRATION_HEAD == "0025_doe_preview"
    name = f"physicsai_m19_{uuid.uuid4().hex[:8]}"
    with pg_server["admin"].connect() as c:
        c.execute(text(f'CREATE DATABASE "{name}"'))
    base, _, _ = pg_server["admin_url"].rpartition("/")
    url = f"{base}/{name}"
    eng = create_engine(url)
    try:
        _alembic(url, "0018_equiv_check")
        sid = str(uuid.uuid4())
        with eng.begin() as c:
            c.execute(text("insert into studies(id, project_id, folder_name, title, ai_root_snapshot, created_by, created_by_name)"
                           " values (:i,'p-1','M19','t','/x','u','u')"), {"i": sid})
            c.execute(text("insert into train_setups(id, study_id) values (:i,:s)"), {"i": str(uuid.uuid4()), "s": sid})  # 0018 시점 행
        _alembic(url, "head")
        with eng.begin() as c:
            assert c.execute(text("select version_num from alembic_version")).scalar() == MIGRATION_HEAD
            assert c.execute(text("select extract_filter from train_setups")).scalar() is None  # 기존 행 = 조건 없음
            col = c.execute(text("select data_type, is_nullable from information_schema.columns"
                                 " where table_name='train_setups' and column_name='extract_filter'")).one()
            assert tuple(col) == ("jsonb", "YES")
            flt = {"groups": ["thickness"], "conditions": {"thickness_mm": {"min": 2.0, "max": None}}, "draft_max_deg": None}
            c.execute(text("update train_setups set extract_filter = cast(:f as jsonb)"), {"f": json.dumps(flt)})
            assert c.execute(text("select extract_filter from train_setups")).scalar() == flt
        with pytest.raises(RuntimeError, match="추출 조건"):  # 조건이 기록된 행이 있으면 down 거부
            _alembic(url, "0018_equiv_check", down=True)
        with eng.begin() as c:
            c.execute(text("update train_setups set extract_filter = NULL"))
        _alembic(url, "0018_equiv_check", down=True)  # 모두 NULL이면 되돌림
        with eng.connect() as c:
            assert c.execute(text("select version_num from alembic_version")).scalar() == "0018_equiv_check"
            assert not c.execute(text("select 1 from information_schema.columns where table_name='train_setups'"
                                      " and column_name='extract_filter'")).first()
        _alembic(url, "head")
    finally:
        eng.dispose()
        with pg_server["admin"].connect() as c:
            c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


def test_table_definition_matches_migration():
    from physicsai_core.db.tables import train_setups

    col = train_setups.c.extract_filter
    assert col.nullable and type(col.type).__name__ == "JSONB"
    mig = (REPO / "migrations" / "versions" / "0019_extract_filter.py").read_text(encoding="utf-8")
    assert 'down_revision = "0018_equiv_check"' in mig and "extract_filter" in mig
