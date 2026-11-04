"""data-health.md §6.1: migration 0026_data_health — 열·CHECK, 기존 행 보존, downgrade(점검 기록이 있으면 거부·없으면 되돌림, 0014·0025 선례)."""

from __future__ import annotations

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


@pytest.fixture()
def fresh_db(pg_server):
    name = f"physicsai_dh_{uuid.uuid4().hex[:8]}"
    with pg_server["admin"].connect() as c:
        c.execute(text(f'CREATE DATABASE "{name}"'))
    base, _, _ = pg_server["admin_url"].rpartition("/")
    url = f"{base}/{name}"
    eng = create_engine(url)
    try:
        yield url, eng
    finally:
        eng.dispose()
        with pg_server["admin"].connect() as c:
            c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


def _study(c) -> str:
    sid = str(uuid.uuid4())
    c.execute(text("insert into studies(id, project_id, folder_name, title, ai_root_snapshot, created_by, created_by_name)"
                   " values (:i,'p-1','DH','t','/x','u','u')"), {"i": sid})
    return sid


def _dataset(c, sid: str, **extra) -> str:
    jid, did = str(uuid.uuid4()), str(uuid.uuid4())
    c.execute(text("insert into jobs(id, study_id, project_id, job_type, stage, lane, state, holds_slot, params, created_by, created_by_name)"
                   " values (:i,:s,'p-1','DATASET_CREATE',3,'CPU','SUCCEEDED',false,'{}','u','u')"), {"i": jid, "s": sid})
    c.execute(text("insert into datasets(id, study_id, job_id, status, source_path, holdout_ratio, seed, split_group, options_json,"
                   " created_by, created_by_name) values (:i,:s,:j,'READY','/x',0.2,1,'file',cast('{}' as jsonb),'u','u')"),
              {"i": did, "s": sid, "j": jid})
    if extra:
        c.execute(text("update datasets set " + ",".join(f"{k}=:{k}" for k in extra) + " where id=:i"), {**extra, "i": did})
    return jid


def test_migration_0026_downgrade_when_empty_then_up_again(fresh_db):
    url, eng = fresh_db
    _alembic(url, "head")
    with eng.begin() as c:
        sid = _study(c)
        _dataset(c, sid)
        assert c.execute(text("select excluded_count from datasets")).scalar() == 0  # 기존 행 기본값 0
        kind = c.execute(text("select pg_get_constraintdef(oid) from pg_constraint where conname='ck_artifacts_kind'")).scalar()
        assert "DATA_HEALTH_REPORT" in kind and "DATA_HEALTH_CSV" in kind
    _alembic(url, "0025_doe_preview", down=True)
    with eng.begin() as c:
        cols = {r[0] for r in c.execute(text("select column_name from information_schema.columns where table_name='datasets'"))}
        assert "excluded_count" not in cols and "health_job_id" not in cols
        assert "DATA_HEALTH_REPORT" not in c.execute(text("select pg_get_constraintdef(oid) from pg_constraint where conname='ck_artifacts_kind'")).scalar()
    _alembic(url, "head")


@pytest.mark.parametrize("what", ["artifact", "excluded_count", "health_job_id"])
def test_migration_0026_downgrade_blocked_and_data_kept(fresh_db, what):
    url, eng = fresh_db
    _alembic(url, "head")
    with eng.begin() as c:
        sid = _study(c)
        if what == "artifact":
            c.execute(text("insert into artifacts(id, study_id, kind, rel_path, size, content_type) values (:u,:s,'DATA_HEALTH_REPORT','x',1,'application/json')"),
                      {"u": str(uuid.uuid4()), "s": sid})
        elif what == "excluded_count":
            _dataset(c, sid, excluded_count=2)
        else:
            _dataset(c, sid, health_job_id=_dataset(c, sid))
    with pytest.raises(RuntimeError, match="데이터 보호"):
        _alembic(url, "0025_doe_preview", down=True)
    with eng.begin() as c:  # 거부했으므로 행은 그대로
        if what == "artifact":
            assert c.execute(text("select count(*) from artifacts where kind='DATA_HEALTH_REPORT'")).scalar() == 1
        else:
            assert c.execute(text("select count(*) from datasets where excluded_count<>0 or health_job_id is not null")).scalar() == 1
