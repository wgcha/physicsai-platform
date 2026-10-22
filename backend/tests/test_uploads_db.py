"""upload-report.md §6.2 / V-UP-15: migration 0021_uploads up/down(행 있으면 down 거부), 제약, down_revision 0020_mcp, 본문 열 없음."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from physicsai_test_support import REPO


def _alembic(url: str, rev: str, down: bool = False) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(REPO / "migrations" / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO / "migrations"))
    cfg.attributes["url"] = url
    (command.downgrade if down else command.upgrade)(cfg, rev)


def _study(c) -> str:
    sid = str(uuid.uuid4())
    c.execute(text("insert into studies(id, project_id, folder_name, title, ai_root_snapshot, created_by, created_by_name)"
                   " values (:i,'p-1',:f,'t','/x','u','u')"), {"i": sid, "f": "S" + sid[:8]})
    return sid


def _upload(c, sid: str, state: str = "OPEN", total: int = 0, files: str = "[]") -> str:
    uid = str(uuid.uuid4())
    c.execute(text("insert into uploads(id, study_id, project_id, user_id, username, purpose, name, dir_rel, state, files, total_bytes)"
                   " values (:i,:s,'p-1','u','u','MODEL_FOLDER','n','uploads/u/x',:st, cast(:f as jsonb), :t)"),
              {"i": uid, "s": sid, "st": state, "f": files, "t": total})
    return uid


def test_v_up_15_migration_chain_and_head():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    from physicsai_core.db import MIGRATION_HEAD

    cfg = Config(str(REPO / "migrations" / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO / "migrations"))
    sd = ScriptDirectory.from_config(cfg)
    assert sd.get_current_head() == MIGRATION_HEAD == "0023_doe_methods"
    assert sd.get_revision("0021_uploads").down_revision == "0020_mcp"


def test_v_up_15_migration_0021_up_down(pg_server):
    name = f"physicsai_m21_{uuid.uuid4().hex[:8]}"
    with pg_server["admin"].connect() as c:
        c.execute(text(f'CREATE DATABASE "{name}"'))
    base, _, _ = pg_server["admin_url"].rpartition("/")
    url = f"{base}/{name}"
    eng = create_engine(url)
    try:
        _alembic(url, "head")
        with eng.begin() as c:
            assert c.execute(text("select version_num from alembic_version")).scalar() == "0023_doe_methods"
            sid = _study(c)
            ok = _upload(c, sid, total=5, files='[{"rel":"a","size":5,"done":false}]')
            assert c.execute(text("select state, inspect, backup_rel, completed_at from uploads where id=:i"), {"i": ok}).one() == ("OPEN", None, None, None)
        for kw in ({"state": "BOGUS"}, {"total": -1}, {"files": '{"a":1}'}):
            with pytest.raises(IntegrityError), eng.begin() as c:
                _upload(c, sid, **kw)
        for st in ("COMPLETED", "CANCELED", "STALE"):
            with eng.begin() as c:
                _upload(c, sid, state=st)
        with pytest.raises(IntegrityError), eng.begin() as c:  # study FK
            _upload(c, str(uuid.uuid4()))
        cols = {r[0] for r in eng.connect().execute(text("select column_name from information_schema.columns where table_name='uploads'"))}
        assert cols == {"id", "study_id", "project_id", "user_id", "username", "purpose", "engine", "name", "dir_rel", "state", "files",
                        "total_bytes", "inspect", "backup_rel", "created_at", "updated_at", "completed_at"}  # 파일 본문·토큰 열 없음
        idx = {r[0] for r in eng.connect().execute(text("select indexname from pg_indexes where tablename='uploads'"))}
        assert {"ix_uploads_user_state", "ix_uploads_state_updated", "ix_uploads_study_created"} <= idx
        with pytest.raises(RuntimeError):
            _alembic(url, "0020_mcp", down=True)  # 행이 있으면 거부
        with eng.begin() as c:
            c.execute(text("delete from uploads"))
        _alembic(url, "0020_mcp", down=True)
        names = {r[0] for r in eng.connect().execute(text("select tablename from pg_tables where schemaname='public'"))}
        assert "uploads" not in names and "api_tokens" in names
        _alembic(url, "head")
    finally:
        eng.dispose()
        with pg_server["admin"].connect() as c:
            c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
