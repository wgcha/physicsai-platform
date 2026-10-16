"""V3-DB-2: 0005_pscfg_optional — models.pscfg_rel·pscfg_sha256 NULL 허용(phase3 D3-43), 기존 행 보존, downgrade 거부."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from physicsai_test_support import REPO


def _alembic(url: str, rev: str) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(REPO / "migrations" / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO / "migrations"))
    cfg.attributes["url"] = url
    command.upgrade(cfg, rev)


def _model(c, sid, mid, pscfg):
    c.execute(text(
        "insert into models(id, study_id, name, version, source_path, stored_rel, psmdl_rel, psmdl_sha256, psmdl_size,"
        " pscfg_rel, pscfg_sha256, log_status, registered_by, registered_by_name)"
        " values (:i,:s,'M',:v,'/x','r/','r/M.psmdl',:h,1,:p,:ph,'MISSING','u','u')"),
        {"i": mid, "s": sid, "v": abs(hash(mid)) % 100000, "h": "0" * 64,
         "p": "r/s.pscfg" if pscfg else None, "ph": "1" * 64 if pscfg else None})


def test_upgrade_keeps_existing_pscfg_and_allows_null(pg_server):
    from physicsai_core.db import MIGRATION_HEAD

    assert MIGRATION_HEAD >= "0005_pscfg_optional"
    name = f"physicsai_m5_{uuid.uuid4().hex[:8]}"
    with pg_server["admin"].connect() as c:
        c.execute(text(f'CREATE DATABASE "{name}"'))
    base, _, _ = pg_server["admin_url"].rpartition("/")
    url = f"{base}/{name}"
    eng = create_engine(url)
    try:
        _alembic(url, "0004_study_manage")
        sid, old = str(uuid.uuid4()), str(uuid.uuid4())
        with eng.begin() as c:
            c.execute(text("insert into studies(id, project_id, folder_name, title, ai_root_snapshot, created_by, created_by_name)"
                           " values (:i,'p-1',:f,'t','/x','u','u')"), {"i": sid, "f": "M" + sid[:8]})
            _model(c, sid, old, pscfg=True)
        with pytest.raises(IntegrityError), eng.begin() as c:       # 0004: NOT NULL
            _model(c, sid, str(uuid.uuid4()), pscfg=False)
        _alembic(url, "head")
        with eng.begin() as c:
            assert c.execute(text("select version_num from alembic_version")).scalar() == MIGRATION_HEAD
            row = c.execute(text("select pscfg_rel, pscfg_sha256 from models where id=:i"), {"i": old}).one()
            assert tuple(row) == ("r/s.pscfg", "1" * 64)               # 기존 데이터 보존
            new = str(uuid.uuid4())
            _model(c, sid, new, pscfg=False)
            assert c.execute(text("select pscfg_rel from models where id=:i"), {"i": new}).scalar() is None
    finally:
        eng.dispose()
        with pg_server["admin"].connect() as c:
            c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


def test_downgrade_refused():
    import importlib.util

    spec = importlib.util.spec_from_file_location("m0005", REPO / "migrations" / "versions" / "0005_pscfg_optional.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    assert mod.down_revision == "0004_study_manage"
    with pytest.raises(RuntimeError):
        mod.downgrade()
