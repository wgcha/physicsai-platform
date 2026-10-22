"""V3-S15-9: migration 0012_sampling_kinds — predict_batches.source_kind CHECK 확장(새 kind 7개 + 기존 3개 허용, 'FOO' 거부),
기존 행 보존, MIGRATION_HEAD, 테이블 상수 = CHECK, downgrade 거부."""

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

NEW_KINDS = ("LHS_OPT", "SOBOL", "FULLFACT", "FRACFACT", "PB", "BBD", "CCD")
ALL_KINDS = ("LHS", *NEW_KINDS, "TABLE", "TRAIN_DOE")


def _alembic(url: str, rev: str) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(REPO / "migrations" / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO / "migrations"))
    cfg.attributes["url"] = url
    command.upgrade(cfg, rev)


def _batch_fixture(c) -> dict:
    """study + param_set + model + 부모 작업 (배치 행의 FK)."""
    sid, ps, mid, jid = (str(uuid.uuid4()) for _ in range(4))
    c.execute(text("insert into studies(id, project_id, folder_name, title, ai_root_snapshot, created_by, created_by_name)"
                   " values (:i,'p-1',:f,'t','/x','u','u')"), {"i": sid, "f": "S15" + sid[:8]})
    c.execute(text("insert into param_sets(id, study_id, source_path, stored_rel, parameters, responses, sample_count,"
                   " sample_has_measured, cad_file_name, tpl_rel, assem_rel, starter_name, tpl_params, registered_by,"
                   " registered_by_name) values (:i,:s,'/x','r/','[]','[]',0,false,'c','t','a/','s_0000.rad','[]','u','u')"),
              {"i": ps, "s": sid})
    c.execute(text("insert into models(id, study_id, name, version, source_path, stored_rel, psmdl_rel, psmdl_sha256, psmdl_size,"
                   " log_status, registered_by, registered_by_name) values (:i,:s,'m',1,'/x','r','r/a.psmdl',:h,1,'MISSING','u','u')"),
              {"i": mid, "s": sid, "h": "0" * 64})
    c.execute(text("insert into jobs(id, study_id, project_id, job_type, stage, lane, state, holds_slot, queue_seq, params,"
                   " created_by, created_by_name) values (:i,:s,'p-1','PREDICT_BATCH',4,"+LANE_SQL+",'QUEUED',false,1,"
                   " cast(:p as jsonb),'u','u')"), {"i": jid, "s": sid, "p": json.dumps({})})
    return {"s": sid, "p": ps, "m": mid, "j": jid}


def _insert_batch(c, fx: dict, bid: str, no: int, kind: str) -> None:
    c.execute(text("insert into predict_batches(id, study_id, batch_no, job_id, param_set_id, model_id, input_kind, source_kind,"
                   " source_meta, run_count, dir_rel, created_by, created_by_name) values (:b,:s,:n,:j,:p,:m,'assembly',:k,"
                   " cast(:meta as jsonb),2,:d,'u','u')"),
              {**fx, "b": bid, "n": no, "k": kind, "meta": json.dumps({"count": 2}), "d": f"04_batch/B-{no:03d}"})


def test_v3_s15_9_check_allows_ten_kinds_rejects_foo(engine):
    with engine.begin() as c:
        fx = _batch_fixture(c)
        for no, kind in enumerate(ALL_KINDS, start=1):
            _insert_batch(c, fx, f"b-{kind}", no, kind)
        got = {r[0] for r in c.execute(text("select source_kind from predict_batches where study_id=:s"), {"s": fx["s"]})}
        assert got == set(ALL_KINDS)
        assert c.execute(text("select source_meta->>'count' from predict_batches where id='b-SOBOL'")).scalar() == "2"
    for bad in ("FOO", "lhs", "CSV", "LHS_OPTIMIZED_X", ""):
        with pytest.raises(IntegrityError), engine.begin() as c:
            _insert_batch(c, fx, f"bad-{bad or 'empty'}", 99, bad)


def test_v3_s15_9_migration_0012_keeps_existing_rows(pg_server):
    from physicsai_core.db import MIGRATION_HEAD

    assert MIGRATION_HEAD == "0022_job_queues"  # geometry-engine.md §7.5: native 0016이 S18 0015 다음
    name = f"physicsai_m12_{uuid.uuid4().hex[:8]}"
    with pg_server["admin"].connect() as c:
        c.execute(text(f'CREATE DATABASE "{name}"'))
    base, _, _ = pg_server["admin_url"].rpartition("/")
    url = f"{base}/{name}"
    eng = create_engine(url)
    try:
        _alembic(url, "0011_surrogate_final")
        with eng.begin() as c:
            fx = _batch_fixture(c)
            for no, kind in enumerate(("LHS", "TABLE", "TRAIN_DOE"), start=1):
                _insert_batch(c, fx, f"old-{kind}", no, kind)
        with pytest.raises(IntegrityError), eng.begin() as c:  # 0011에서는 새 kind 거부
            _insert_batch(c, fx, "new-before", 4, "SOBOL")
        _alembic(url, "head")
        with eng.begin() as c:
            assert c.execute(text("select version_num from alembic_version")).scalar() == MIGRATION_HEAD
            rows = c.execute(text("select id, source_kind, source_meta, run_count from predict_batches order by batch_no")).all()
            assert [(r[0], r[1], r[2], r[3]) for r in rows] == [
                ("old-LHS", "LHS", {"count": 2}, 2), ("old-TABLE", "TABLE", {"count": 2}, 2),
                ("old-TRAIN_DOE", "TRAIN_DOE", {"count": 2}, 2)]
            for no, kind in enumerate(NEW_KINDS, start=10):
                _insert_batch(c, fx, f"new-{kind}", no, kind)
            width = c.execute(text("select character_maximum_length from information_schema.columns"
                                   " where table_name='predict_batches' and column_name='source_kind'")).scalar()
            assert width == 16
            defn = c.execute(text("select pg_get_constraintdef(oid) from pg_constraint"
                                  " where conname='ck_predict_batches_source_kind'")).scalar()
            assert all(f"'{k}'" in defn for k in ALL_KINDS)
        with pytest.raises(IntegrityError), eng.begin() as c:
            _insert_batch(c, fx, "foo", 40, "FOO")
    finally:
        eng.dispose()
        with pg_server["admin"].connect() as c:
            c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


def test_v3_s15_9_table_constants_match_migration_and_registry():
    from physicsai_core.db.tables.predict_batch import BATCH_SOURCE_KINDS, predict_batches
    from physicsai_core.sampling import registry

    assert set(BATCH_SOURCE_KINDS) == set(ALL_KINDS) == set(registry.SOURCE_KINDS.values()) and len(BATCH_SOURCE_KINDS) == 10
    ck = next(c for c in predict_batches.constraints if getattr(c, "name", "") == "ck_predict_batches_source_kind")
    assert set(re.findall(r"'([A-Z_]+)'", str(ck.sqltext))) == set(ALL_KINDS)
    spec = importlib.util.spec_from_file_location("m0012", REPO / "migrations" / "versions" / "0012_sampling_kinds.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    assert (mod.revision, mod.down_revision) == ("0012_sampling_kinds", "0011_surrogate_final")
    assert set(re.findall(r"'([A-Z_]+)'", open(REPO / "migrations" / "versions" / "0012_sampling_kinds.py", encoding="utf-8").read().split("def upgrade")[1])) == set(ALL_KINDS)
    with pytest.raises(RuntimeError):
        mod.downgrade()
