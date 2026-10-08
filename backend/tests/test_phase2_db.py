"""V2-DB-1~3: 0002_phase2 migration, MIGRATION_HEAD, 새 CHECK·unique, JSONB 컬럼(본문 컬럼 없음)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from physicsai_test_support import REPO


def test_migration_head_constant_matches_script():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    from physicsai_core.db import MIGRATION_HEAD

    cfg = Config(str(REPO / "migrations" / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO / "migrations"))
    assert ScriptDirectory.from_config(cfg).get_current_head() == MIGRATION_HEAD == "0002_phase2"


def test_upgrade_head_and_metadata_in_sync(engine):
    """빈 PG에 0001→0002 적용 결과가 tables.py 메타데이터와 같다(명시적 DDL 누락 방지)."""
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from physicsai_core.db import MIGRATION_HEAD
    from physicsai_core.db.tables import metadata

    with engine.connect() as c:
        assert c.execute(text("select version_num from alembic_version")).scalar() == MIGRATION_HEAD
        mc = MigrationContext.configure(c, opts={"compare_type": True, "compare_server_default": False})
        diff = [d for d in compare_metadata(mc, metadata) if not (isinstance(d, tuple) and d[0] == "remove_table" and d[1].name == "alembic_version")]
    assert diff == [], diff
    names = set(inspect(engine).get_table_names())
    for t in ("train_setups", "train_does", "train_runs", "curations", "spdm_imports", "optimizations", "env_checks"):
        assert t in names


def test_schema_0001_is_phase1_only():
    from physicsai_core.db import schema_0001

    assert "train_does" not in schema_0001.metadata.tables
    assert "origin" not in schema_0001.param_sets.c


def _study(c):
    sid = str(uuid.uuid4())
    c.execute(text("insert into studies(id, project_id, folder_name, title, ai_root_snapshot, created_by, created_by_name)"
                   " values (:i,'p-1',:f,'t','/x','u','u')"), {"i": sid, "f": "S" + sid[:8]})
    return sid


def _job(c, sid):
    jid = str(uuid.uuid4())
    c.execute(text("insert into jobs(id, study_id, project_id, job_type, stage, lane, state, holds_slot, queue_seq, params,"
                   " created_by, created_by_name) values (:i,:s,'p-1','TD_DOE_GEN',1,'SLOT','QUEUED',false,1,'{}','u','u')"),
              {"i": jid, "s": sid})
    return jid


def _doe(c, sid, jid):
    did = str(uuid.uuid4())
    c.execute(text("insert into train_does(id, study_id, job_id, doe_label, doe_type, radioss_assem_source_path, dir_rel,"
                   " assem_rel, created_by, created_by_name) values (:i,:s,:j,'LHS','TYPE_LATINHYPERCUBE','/x','d','a','u','u')"),
              {"i": did, "s": sid, "j": jid})
    return did


@pytest.mark.parametrize("sql", [
    "insert into artifacts(id, study_id, kind, rel_path, size, content_type) values (:u,:s,'BOGUS','x',1,'text/plain')",
    "insert into notifications(user_id, event, title) values ('u','BOGUS','t')",
    "update param_sets set origin='SPDM'",
])
def test_new_check_constraints_reject(engine, sql):
    with engine.connect() as c:
        sid = _study(c)
        if "param_sets" in sql:
            c.execute(text("insert into param_sets(id, study_id, source_path, stored_rel, parameters, responses, sample_count,"
                           " sample_has_measured, cad_file_name, tpl_rel, assem_rel, starter_name, tpl_params, registered_by,"
                           " registered_by_name) values (:u,:s,'x','x','[]','[]',0,false,'c','t','a','s','[]','u','u')"),
                      {"u": str(uuid.uuid4()), "s": sid})
        with pytest.raises(IntegrityError):
            c.execute(text(sql), {"u": str(uuid.uuid4()), "s": sid})


def test_new_kinds_and_events_accepted(engine):
    with engine.begin() as c:
        sid = _study(c)
        for k in ("CURATION_CFG", "FILE_LIST", "DOE_SAMPLES", "RUN_CONFIG", "OPT_SUMMARY", "OPT_FILE"):
            c.execute(text("insert into artifacts(id, study_id, kind, rel_path, size, content_type) values (:u,:s,:k,'x',1,'text/plain')"),
                      {"u": str(uuid.uuid4()), "s": sid, "k": k})
        for e in ("HPC_PARTIAL_FAILED", "ENV_CHECK_DONE"):
            c.execute(text("insert into notifications(user_id, event, title) values ('u',:e,'t')"), {"e": e})


def test_env_checks_single_active(engine):
    with engine.connect() as c:
        c.execute(text("insert into env_checks(id, requested_by, requested_by_name, expires_at) values ('a','u','u', now() + interval '1 hour')"))
        c.execute(text("insert into env_checks(id, state, requested_by, requested_by_name, expires_at) values ('b','DONE','u','u', now())"))
        with pytest.raises(IntegrityError):
            c.execute(text("insert into env_checks(id, state, requested_by, requested_by_name, expires_at) values ('c','RUNNING','u','u', now())"))


def test_train_runs_unique_and_state(engine):
    with engine.connect() as c:
        sid = _study(c)
        did = _doe(c, sid, _job(c, sid))
        q = text("insert into train_runs(id, doe_id, run_key, input_rel, starter_name, state) values (:i,:d,:r,'x','s',:st)")
        c.execute(q, {"i": str(uuid.uuid4()), "d": did, "r": "run__00001", "st": "GENERATED"})
        sp = c.begin_nested()
        with pytest.raises(IntegrityError):
            c.execute(q, {"i": str(uuid.uuid4()), "d": did, "r": "run__00001", "st": "GENERATED"})
        sp.rollback()
        with pytest.raises(IntegrityError):
            c.execute(q, {"i": str(uuid.uuid4()), "d": did, "r": "run__00002", "st": "DONE"})


def test_jsonb_columns_and_no_body_columns(engine):
    """V2-DB-3: §5 JSONB 컬럼이 있고, 샘플 값·로그 본문 컬럼이 없다."""
    insp = inspect(engine)
    jsonb = {(t, c["name"]) for t in insp.get_table_names() for c in insp.get_columns(t) if str(c["type"]) == "JSONB"}
    for t, c in [("train_setups", "parameters"), ("train_setups", "tpl_params"), ("train_setups", "tpl_warnings"),
                 ("train_does", "options"), ("train_does", "parameters_snapshot"), ("train_runs", "result_summary"),
                 ("curations", "source"), ("curations", "selection"), ("curations", "missing_runs"),
                 ("optimizations", "responses"), ("optimizations", "summary_meta"), ("env_checks", "api_items"),
                 ("env_checks", "worker_items"), ("env_checks", "summary")]:
        assert (t, c) in jsonb
    for t in insp.get_table_names():
        for col in insp.get_columns(t):
            assert col["name"] not in ("samples", "sample_values", "log_text", "content", "file_content", "rows",
                                       "summary_rows", "report", "output_tail")
