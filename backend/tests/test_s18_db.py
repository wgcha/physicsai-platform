"""V3-S18-3: migration 0015_doe_platform_gen — train_does.generator(기본 HYPERSTUDY·CHECK)·sampling, 새 train_doe_points
(PK·UNIQUE·CHECK), 기존 행 보존, MIGRATION_HEAD, PLATFORM 행이 있으면 downgrade 실패(없으면 되돌림), 메타데이터 = 마이그레이션."""

from __future__ import annotations

import importlib.util
import json
import re
import uuid

import pytest
from sqlalchemy import create_engine, text

from lane_compat import LANE_SQL
from sqlalchemy.exc import IntegrityError

from physicsai_test_support import REPO

M15 = REPO / "migrations" / "versions" / "0015_doe_platform_gen.py"


def _cfg(url: str):
    from alembic.config import Config

    cfg = Config(str(REPO / "migrations" / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO / "migrations"))
    cfg.attributes["url"] = url
    return cfg


def _up(url: str, rev: str) -> None:
    from alembic import command

    command.upgrade(_cfg(url), rev)


def _down(url: str, rev: str) -> None:
    from alembic import command

    command.downgrade(_cfg(url), rev)


def _doe(c, sid: str, jid: str, did: str, **extra: str) -> None:
    cols = ", ".join(["id", "study_id", "job_id", "doe_label", "doe_type", "radioss_assem_source_path", "dir_rel", "assem_rel",
                      "created_by", "created_by_name", *extra])
    vals = ", ".join([":i", ":s", ":j", "'L'", "'TYPE_LATINHYPERCUBE'", "'/a'", "'d/'", "'a/'", "'u'", "'u'",
                      *[f":{k}" for k in extra]])
    c.execute(text(f"insert into train_does({cols}) values ({vals})"), {"i": did, "s": sid, "j": jid, **extra})


def _fixture(c) -> dict:
    sid, jid, did = (str(uuid.uuid4()) for _ in range(3))
    c.execute(text("insert into studies(id, project_id, folder_name, title, ai_root_snapshot, created_by, created_by_name)"
                   " values (:i,'p-1',:f,'t','/x','u','u')"), {"i": sid, "f": "S18" + sid[:8]})
    c.execute(text("insert into jobs(id, study_id, project_id, job_type, stage, lane, state, holds_slot, queue_seq, params,"
                   " created_by, created_by_name) values (:i,:s,'p-1','TD_DOE_GEN',1,"+LANE_SQL+",'SUCCEEDED',false,null,"
                   " cast(:p as jsonb),'u','u')"), {"i": jid, "s": sid, "p": json.dumps({})})
    _doe(c, sid, jid, did)
    return {"s": sid, "j": jid, "d": did}


def test_v3_s18_3_migration_0015_roundtrip(pg_server):
    from physicsai_core.db import MIGRATION_HEAD

    assert MIGRATION_HEAD == "0024_contour3d_field"  # native 0016이 0015 다음 — 0015까지만 올려 왕복 확인
    name = f"physicsai_m15_{uuid.uuid4().hex[:8]}"
    with pg_server["admin"].connect() as c:
        c.execute(text(f'CREATE DATABASE "{name}"'))
    base, _, _ = pg_server["admin_url"].rpartition("/")
    url = f"{base}/{name}"
    eng = create_engine(url)
    try:
        spec = importlib.util.spec_from_file_location("m0015", M15)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        assert mod.revision == "0015_doe_platform_gen" and mod.down_revision == "0014_multiobj"
        _up(url, mod.down_revision)
        with eng.begin() as c:
            fx = _fixture(c)
        _up(url, mod.revision)
        with eng.begin() as c:
            assert c.execute(text("select version_num from alembic_version")).scalar() == mod.revision
            row = c.execute(text("select generator, sampling, doe_type from train_does where id=:d"), {"d": fx["d"]}).one()
            assert tuple(row) == ("HYPERSTUDY", None, "TYPE_LATINHYPERCUBE")  # 기존 행 보존·기본값
            did2 = str(uuid.uuid4())
            _doe(c, fx["s"], fx["j"], did2, generator="PLATFORM")
            c.execute(text("update train_does set sampling=cast(:sp as jsonb) where id=:d"),
                      {"d": did2, "sp": json.dumps({"kind": "lhs_opt", "input": {"count": 4}, "meta": None})})
            c.execute(text("insert into train_doe_points(doe_id, doe_no, run_key, values, applied_values)"
                           " values (:d,1,'run__00001','{\"A\": 1.5}','{\"A\": 2}')"), {"d": did2})
            assert c.execute(text("select gen_state, gen_code, updated_at is not null from train_doe_points")).one() == \
                ("PENDING", None, True)
        for bad in ("update train_does set generator='FOO' where id=:d",
                    "insert into train_doe_points(doe_id, doe_no, run_key, values, applied_values)"
                    " values (:d,1,'run__00009','{}','{}')",                                    # PK(doe_id, doe_no)
                    "insert into train_doe_points(doe_id, doe_no, run_key, values, applied_values)"
                    " values (:d,2,'run__00001','{}','{}')",                                    # UNIQUE(doe_id, run_key)
                    "insert into train_doe_points(doe_id, doe_no, run_key, values, applied_values, gen_state)"
                    " values (:d,3,'run__00003','{}','{}','BOGUS')"):                           # CHECK gen_state
            with pytest.raises(IntegrityError), eng.begin() as c:
                c.execute(text(bad), {"d": did2})
        with pytest.raises(RuntimeError, match="플랫폼"):  # 데이터 보존
            _down(url, mod.down_revision)
        with eng.begin() as c:
            assert c.execute(text("select version_num from alembic_version")).scalar() == mod.revision
            c.execute(text("delete from train_doe_points"))
            c.execute(text("delete from train_does where id=:d"), {"d": did2})
        _down(url, mod.down_revision)
        with eng.begin() as c:
            assert c.execute(text("select version_num from alembic_version")).scalar() == "0014_multiobj"
            cols = {r[0] for r in c.execute(text("select column_name from information_schema.columns"
                                                 " where table_name = 'train_does'"))}
            assert not {"generator", "sampling"} & cols
            assert c.execute(text("select to_regclass('train_doe_points')")).scalar() is None
            assert c.execute(text("select doe_type from train_does where id=:d"), {"d": fx["d"]}).scalar() == "TYPE_LATINHYPERCUBE"
        _up(url, "head")
    finally:
        eng.dispose()
        with pg_server["admin"].connect() as c:
            c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


def test_v3_s18_3_table_constants_match_migration():
    from physicsai_core.db.repositories.train import GENERATORS, POINT_STATES
    from physicsai_core.db.tables import train_doe_points, train_does

    src = M15.read_text(encoding="utf-8").split("def upgrade")[1].split("def downgrade")[0]
    ck = next(c for c in train_does.constraints if getattr(c, "name", "") == "ck_train_does_generator")
    assert set(re.findall(r"'([A-Z_]+)'", str(ck.sqltext))) == set(GENERATORS) == {"HYPERSTUDY", "PLATFORM"}
    ck = next(c for c in train_doe_points.constraints if getattr(c, "name", "") == "ck_train_doe_points_gen_state")
    assert set(re.findall(r"'([A-Z_]+)'", str(ck.sqltext))) == set(POINT_STATES)
    assert set(POINT_STATES) <= set(re.findall(r"'([A-Z_]+)'", src)) and set(GENERATORS) <= set(re.findall(r"'([A-Z_]+)'", src))
    assert [c.name for c in train_doe_points.primary_key.columns] == ["doe_id", "doe_no"]
    assert {"values", "applied_values", "gen_state", "gen_code", "gen_message", "updated_at"} <= set(train_doe_points.c.keys())


def test_v3_s18_7_job_end_hook_resets_running_points(engine):
    """종료 훅(§23.5): 워커가 못 쓴 lease 상실·리퍼 경로 — TD_DOE_GEN 비성공 종료 시 RUNNING 점 → PENDING, DOE FAILED."""
    from physicsai_core.db.repositories import job_end
    from physicsai_core.db.repositories import train as train_repo

    with engine.begin() as c:
        fx = _fixture(c)
        c.execute(text("update train_does set status='BUILDING', generator='PLATFORM' where id=:d"), {"d": fx["d"]})
        train_repo.insert_points(c, fx["d"], [{"doe_no": i, "run_key": f"run__{i:05d}", "values": {"A": i},
                                               "applied_values": {"A": i}} for i in (1, 2, 3)])
        train_repo.set_point(c, fx["d"], 1, gen_state="DONE")
        train_repo.set_point(c, fx["d"], 2, gen_state="RUNNING")
        assert train_repo.point_counts(c, fx["d"]) == {"total": 3, "pending": 1, "running": 1, "done": 1, "failed": 0}
        job_end._side_effects_on_end(c, {"id": fx["j"], "job_type": "TD_DOE_GEN", "params": {"doe_id": fx["d"]}, "result": {}},
                                     "INTERRUPTED")
        assert [p["gen_state"] for p in train_repo.points(c, fx["d"])] == ["DONE", "PENDING", "PENDING"]
        assert c.execute(text("select status from train_does where id=:d"), {"d": fx["d"]}).scalar() == "FAILED"
