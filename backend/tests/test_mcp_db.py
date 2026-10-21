"""mcp.md §14: migration 0020_mcp up/down(행 있으면 down 거부, 없으면 되돌림)·제약(scope·유효 이름 유일)·평문 열 없음."""

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


def _token(c, name: str, scope: str = "read", revoked: bool = False) -> None:
    c.execute(text("insert into api_tokens(id, user_id, username, display_name, name, scope, token_prefix, token_hash,"
                   " principal_snapshot, snapshot_at, expires_at, revoked_at) values (:i,'u','u','u',:n,:s,:p,:h,'{}',now(),"
                   " now() + interval '1 day', :r)"),
              {"i": str(uuid.uuid4()), "n": name, "s": scope, "p": "pai_" + uuid.uuid4().hex[:8], "h": uuid.uuid4().hex * 2,
               "r": None if not revoked else "2026-01-01"})


def test_migration_0020(pg_server):
    from physicsai_core.db import MIGRATION_HEAD

    assert MIGRATION_HEAD == "0021_uploads"
    name = f"physicsai_m20_{uuid.uuid4().hex[:8]}"
    with pg_server["admin"].connect() as c:
        c.execute(text(f'CREATE DATABASE "{name}"'))
    base, _, _ = pg_server["admin_url"].rpartition("/")
    url = f"{base}/{name}"
    eng = create_engine(url)
    try:
        _alembic(url, "head")
        with eng.begin() as c:
            assert c.execute(text("select version_num from alembic_version")).scalar() == MIGRATION_HEAD
            _token(c, "a")
            _token(c, "a", revoked=True)  # 폐기된 같은 이름은 허용
        with pytest.raises(IntegrityError), eng.begin() as c:
            _token(c, "a")  # 유효 토큰끼리 이름 유일
        with pytest.raises(IntegrityError), eng.begin() as c:
            _token(c, "b", scope="root")
        cols = {(r[0], r[1]) for r in eng.connect().execute(text(
            "select table_name, column_name from information_schema.columns where table_name in ('api_tokens','mcp_plans','api_audit')"))}
        assert not any(col in ("token", "plain", "secret", "body", "params", "confirm_token", "query") for _t, col in cols)
        assert ("jobs", "api_token_id") in {(r[0], r[1]) for r in eng.connect().execute(text(
            "select table_name, column_name from information_schema.columns where table_name = 'jobs'"))}
        with pytest.raises(RuntimeError):
            _alembic(url, "0019_extract_filter", down=True)
        with eng.begin() as c:
            c.execute(text("delete from api_tokens"))
        _alembic(url, "0019_extract_filter", down=True)
        names = {r[0] for r in eng.connect().execute(text("select tablename from pg_tables where schemaname='public'"))}
        assert not names & {"api_tokens", "mcp_plans", "api_audit"}
        _alembic(url, "head")
    finally:
        eng.dispose()
        with pg_server["admin"].connect() as c:
            c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
