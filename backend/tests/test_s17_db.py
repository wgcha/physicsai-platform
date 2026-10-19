"""V3-S17-1: migration 0014_multiobj — iters kind EXTRA·hv·front_size·predicted_front, opts hv_frame, 기존 행 보존,
MIGRATION_HEAD, 테이블 상수 = CHECK, EXTRA 행이 있으면 downgrade 실패(없으면 되돌림)."""

from __future__ import annotations

import importlib.util
import json
import re
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from physicsai_test_support import REPO

M14 = REPO / "migrations" / "versions" / "0014_multiobj.py"


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


def _fixture(c) -> dict:
    """study + param_set + model + 부모 작업 + 배치 + opt + 반복 0(EXPLORE)."""
    sid, ps, mid, jid, bid, oid = (str(uuid.uuid4()) for _ in range(6))
    c.execute(text("insert into studies(id, project_id, folder_name, title, ai_root_snapshot, created_by, created_by_name)"
                   " values (:i,'p-1',:f,'t','/x','u','u')"), {"i": sid, "f": "S17" + sid[:8]})
    c.execute(text("insert into param_sets(id, study_id, source_path, stored_rel, parameters, responses, sample_count,"
                   " sample_has_measured, cad_file_name, tpl_rel, assem_rel, starter_name, tpl_params, registered_by,"
                   " registered_by_name) values (:i,:s,'/x','r/','[]','[]',0,false,'c','t','a/','s_0000.rad','[]','u','u')"),
              {"i": ps, "s": sid})
    c.execute(text("insert into models(id, study_id, name, version, source_path, stored_rel, psmdl_rel, psmdl_sha256, psmdl_size,"
                   " log_status, registered_by, registered_by_name) values (:i,:s,'m',1,'/x','r','r/a.psmdl',:h,1,'MISSING','u','u')"),
              {"i": mid, "s": sid, "h": "0" * 64})
    c.execute(text("insert into jobs(id, study_id, project_id, job_type, stage, lane, state, holds_slot, queue_seq, params,"
                   " created_by, created_by_name) values (:i,:s,'p-1','PREDICT_BATCH',4,'SLOT','SUCCEEDED',false,null,"
                   " cast(:p as jsonb),'u','u')"), {"i": jid, "s": sid, "p": json.dumps({})})
    c.execute(text("insert into predict_batches(id, study_id, batch_no, job_id, param_set_id, model_id, input_kind, source_kind,"
                   " source_meta, run_count, dir_rel, created_by, created_by_name) values (:b,:s,1,:j,:p,:m,'assembly','TABLE',"
                   " '{}',2,'04_batch/B-001','u','u')"), {"b": bid, "s": sid, "j": jid, "p": ps, "m": mid})
    c.execute(text("insert into surrogate_opts(id, study_id, opt_no, param_set_id, model_id, input_kind, settings, status,"
                   " dir_rel, created_by, created_by_name) values (:o,:s,1,:p,:m,'assembly',cast(:st as jsonb),'DONE',"
                   " '05_opt/surrogate/SO-001','u','u')"),
              {"o": oid, "s": sid, "p": ps, "m": mid, "st": json.dumps({"objective": {"metric": "curve:max"}})})
    c.execute(text("insert into surrogate_opt_iters(opt_id, iter_no, kind, batch_id, best_value) values (:o,0,'EXPLORE',:b,1.5)"),
              {"o": oid, "b": bid})
    return {"s": sid, "o": oid, "b": bid}


def test_v3_s17_1_migration_0014_roundtrip(pg_server):
    from physicsai_core.db import MIGRATION_HEAD

    assert MIGRATION_HEAD == "0016_geometry_engine"  # S18 0015 → native 0016
    name = f"physicsai_m14_{uuid.uuid4().hex[:8]}"
    with pg_server["admin"].connect() as c:
        c.execute(text(f'CREATE DATABASE "{name}"'))
    base, _, _ = pg_server["admin_url"].rpartition("/")
    url = f"{base}/{name}"
    eng = create_engine(url)
    try:
        spec = importlib.util.spec_from_file_location("m0014", M14)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        prev = mod.down_revision
        _up(url, prev)
        with eng.begin() as c:
            fx = _fixture(c)
        with pytest.raises(IntegrityError), eng.begin() as c:  # 0014 전에는 EXTRA 거부
            c.execute(text("insert into surrogate_opt_iters(opt_id, iter_no, kind, batch_id) values (:o,1,'EXTRA',:b)"),
                      {"o": fx["o"], "b": fx["b"]})
        _up(url, mod.revision)  # head ≠ 0014(S18 0015·native 0016) — 0014까지만 올려 왕복 확인
        with eng.begin() as c:
            assert c.execute(text("select version_num from alembic_version")).scalar() == mod.revision
            row = c.execute(text("select kind, best_value, hv, front_size, predicted_front from surrogate_opt_iters"
                                 " where opt_id=:o"), {"o": fx["o"]}).one()
            assert tuple(row) == ("EXPLORE", 1.5, None, None, None)  # 기존 행 보존, 새 열 NULL
            assert c.execute(text("select hv_frame from surrogate_opts where id=:o"), {"o": fx["o"]}).scalar() is None
            c.execute(text("update surrogate_opts set hv_frame=cast(:f as jsonb) where id=:o"),
                      {"o": fx["o"], "f": json.dumps({"ideal": [1, 2], "nadir": [3, 4], "ref_offset": 0.1, "signs": [1, -1]})})
            c.execute(text("insert into surrogate_opt_iters(opt_id, iter_no, kind, batch_id, hv, front_size, predicted_front)"
                           " values (:o,1,'EXTRA',:b,0.5,3,cast(:pf as jsonb))"),
                      {"o": fx["o"], "b": fx["b"], "pf": json.dumps([{"values": {"A": 1}, "mean": [1, 2], "std": [0, 0], "pof": 1}])})
        with pytest.raises(IntegrityError), eng.begin() as c:
            c.execute(text("insert into surrogate_opt_iters(opt_id, iter_no, kind, batch_id) values (:o,2,'FOO',:b)"),
                      {"o": fx["o"], "b": fx["b"]})
        with pytest.raises(RuntimeError, match="EXTRA"):  # 데이터 보존
            _down(url, "-1")
        with eng.begin() as c:
            assert c.execute(text("select version_num from alembic_version")).scalar() == mod.revision
            c.execute(text("delete from surrogate_opt_iters where kind='EXTRA'"))
        _down(url, "-1")
        with eng.begin() as c:
            assert c.execute(text("select version_num from alembic_version")).scalar() == prev
            cols = {r[0] for r in c.execute(text("select column_name from information_schema.columns"
                                                 " where table_name in ('surrogate_opt_iters','surrogate_opts')"))}
            assert not {"hv", "front_size", "predicted_front", "hv_frame"} & cols
            assert c.execute(text("select best_value from surrogate_opt_iters where opt_id=:o"), {"o": fx["o"]}).scalar() == 1.5
        with pytest.raises(IntegrityError), eng.begin() as c:
            c.execute(text("insert into surrogate_opt_iters(opt_id, iter_no, kind, batch_id) values (:o,1,'EXTRA',:b)"),
                      {"o": fx["o"], "b": fx["b"]})
        _up(url, "head")
    finally:
        eng.dispose()
        with pg_server["admin"].connect() as c:
            c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


def test_v3_s17_1_table_constants_match_migration():
    from physicsai_core.db.tables.surrogate_opt import SO_ITER_KINDS, surrogate_opt_iters, surrogate_opts

    assert SO_ITER_KINDS == ("EXPLORE", "REUSE", "VERIFY", "FINAL", "EXTRA")
    ck = next(c for c in surrogate_opt_iters.constraints if getattr(c, "name", "") == "ck_surrogate_opt_iters_kind")
    assert set(re.findall(r"'([A-Z_]+)'", str(ck.sqltext))) == set(SO_ITER_KINDS)
    assert {"hv", "front_size", "predicted_front"} <= set(surrogate_opt_iters.c.keys())
    assert "hv_frame" in surrogate_opts.c.keys()
    src = M14.read_text(encoding="utf-8")
    assert set(re.findall(r"'([A-Z_]+)'", src.split("def upgrade")[1].split("def downgrade")[0])) == set(SO_ITER_KINDS)
