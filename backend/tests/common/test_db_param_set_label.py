"""0006_param_set_label — param_sets.label(NULL 허용) 추가(phase3 §13 S8), 기존 행 보존, downgrade 거부."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine, text

from physicsai_test_support import REPO


def _alembic(url: str, rev: str) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(REPO / "migrations" / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO / "migrations"))
    cfg.attributes["url"] = url
    command.upgrade(cfg, rev)


def test_upgrade_adds_nullable_label(pg_server):
    from physicsai_core.db import MIGRATION_HEAD

    assert MIGRATION_HEAD == "0006_param_set_label"
    name = f"physicsai_m6_{uuid.uuid4().hex[:8]}"
    with pg_server["admin"].connect() as c:
        c.execute(text(f'CREATE DATABASE "{name}"'))
    base, _, _ = pg_server["admin_url"].rpartition("/")
    url = f"{base}/{name}"
    eng = create_engine(url)
    try:
        _alembic(url, "0005_pscfg_optional")
        sid, ps = str(uuid.uuid4()), str(uuid.uuid4())
        with eng.begin() as c:
            c.execute(text("insert into studies(id, project_id, folder_name, title, ai_root_snapshot, created_by, created_by_name)"
                           " values (:i,'p-1',:f,'t','/x','u','u')"), {"i": sid, "f": "L" + sid[:8]})
            c.execute(text(
                "insert into param_sets(id, study_id, source_path, stored_rel, parameters, responses, sample_count,"
                " sample_has_measured, cad_file_name, tpl_rel, assem_rel, starter_name, tpl_params, registered_by,"
                " registered_by_name) values (:i,:s,'/x','r/','[]','[]',0,false,'c','t','a/','s_0000.rad','[]','u','u')"),
                {"i": ps, "s": sid})
        _alembic(url, "head")
        with eng.begin() as c:
            assert c.execute(text("select label from param_sets where id=:i"), {"i": ps}).scalar() is None
            c.execute(text("update param_sets set label='쿠션 v1' where id=:i"), {"i": ps})
            assert c.execute(text("select source_path from param_sets where id=:i"), {"i": ps}).scalar() == "/x"
    finally:
        eng.dispose()
        with pg_server["admin"].connect() as c:
            c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


def test_downgrade_refused():
    import importlib.util

    spec = importlib.util.spec_from_file_location("m0006", REPO / "migrations" / "versions" / "0006_param_set_label.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    assert mod.down_revision == "0005_pscfg_optional"
    with pytest.raises(RuntimeError):
        mod.downgrade()
