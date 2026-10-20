"""equiv-check.md V-EQ-1: migration 0018_equiv_check up/down(행 있으면 down 거부, 없으면 되돌림)·MIGRATION_HEAD·CHECK(scope·status·verdict·
recipe_source·scope↔study_id)·활성 unique 인덱스에서 EQ_CHECK 제외·알림 EQ_CHECK_DONE. V-EQ-9: 설정 상한(snapshot_max_bytes 64 KiB)."""

from __future__ import annotations

import json
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


def _job(c, sid: str, job_type: str, params: dict, seq: int) -> str:
    jid = str(uuid.uuid4())
    c.execute(text("insert into jobs(id, study_id, project_id, job_type, stage, lane, state, holds_slot, queue_seq, params,"
                   " created_by, created_by_name) values (:i,:s,'p-1',:t,4,'SLOT','QUEUED',false,:q,cast(:p as jsonb),'u','u')"),
              {"i": jid, "s": sid, "t": job_type, "q": seq, "p": json.dumps(params)})
    return jid


def _recipe(c, sid: str | None, **over) -> str:
    v = {"i": str(uuid.uuid4()), "k": str(uuid.uuid4()), "v": 1, "sc": "study" if sid else "global", "s": sid, "n": "r", **over}
    c.execute(text("insert into eq_recipes(id, recipe_key, version, scope, study_id, name, definition, created_by, created_by_name)"
                   " values (:i,:k,:v,:sc,:s,:n,'{}','u','u')"), v)
    return v["i"]


def _check(c, sid: str, no: int, **over) -> None:
    v = {"i": str(uuid.uuid4()), "s": sid, "n": no, "rs": "user", "st": "RUNNING", "vd": None, **over}
    c.execute(text("insert into eq_checks(id, study_id, eq_no, recipe_source, recipe_snapshot, side_a, side_b, pairing, status, verdict,"
                   " dir_rel, created_by, created_by_name) values (:i,:s,:n,:rs,'{}','{}','{}','{}',:st,:vd,'05_equiv/EQ-001','u','u')"), v)


def test_v_eq_1_migration_0018(pg_server):
    from physicsai_core.db import MIGRATION_HEAD

    assert MIGRATION_HEAD == "0018_equiv_check"
    name = f"physicsai_m18_{uuid.uuid4().hex[:8]}"
    with pg_server["admin"].connect() as c:
        c.execute(text(f'CREATE DATABASE "{name}"'))
    base, _, _ = pg_server["admin_url"].rpartition("/")
    url = f"{base}/{name}"
    eng = create_engine(url)
    try:
        _alembic(url, "0017_geom_view")
        sid = str(uuid.uuid4())
        with eng.begin() as c:
            c.execute(text("insert into studies(id, project_id, folder_name, title, ai_root_snapshot, created_by, created_by_name)"
                           " values (:i,'p-1','M18','t','/x','u','u')"), {"i": sid})
            _job(c, sid, "EQ_CHECK", {"eq_id": "e0"}, 1)
        with pytest.raises(IntegrityError), eng.begin() as c:  # 0017에서는 같은 유형 2개 대기 불가
            _job(c, sid, "EQ_CHECK", {"eq_id": "e1"}, 2)
        with eng.begin() as c:
            c.execute(text("delete from jobs where job_type='EQ_CHECK'"))
        _alembic(url, "head")
        with eng.begin() as c:
            assert c.execute(text("select version_num from alembic_version")).scalar() == MIGRATION_HEAD
            _job(c, sid, "EQ_CHECK", {"eq_id": "e1"}, 3)  # 활성 EQ_CHECK 여러 개(서비스 max_active)
            _job(c, sid, "EQ_CHECK", {"eq_id": "e2"}, 4)
            c.execute(text("insert into notifications(user_id, event, title) values ('u','EQ_CHECK_DONE','t')"))
            _recipe(c, sid)
            _recipe(c, None)
            _check(c, sid, 1)
            _check(c, sid, 2, st="DONE", vd="PASS")
        for bad in ({"sc": "team"}, {"sc": "global", "s": sid}, {"sc": "study", "s": None}, {"v": 0}):
            with pytest.raises(IntegrityError), eng.begin() as c:
                _recipe(c, sid, **bad)
        for bad in ({"rs": "x"}, {"st": "QUEUED"}, {"vd": "MAYBE", "st": "DONE"}, {"n": 0}):
            with pytest.raises(IntegrityError), eng.begin() as c:
                _check(c, sid, 9, **bad)
        with pytest.raises(IntegrityError), eng.begin() as c:  # (study_id, eq_no) 유일
            _check(c, sid, 1)
        with pytest.raises(IntegrityError), eng.begin() as c:  # (recipe_key, version) 유일
            k = str(uuid.uuid4())
            _recipe(c, sid, k=k)
            _recipe(c, sid, k=k)
        cols = {r[0] for r in eng.connect().execute(text("select column_name from information_schema.columns where table_name='eq_checks'"))}
        assert {"id", "study_id", "eq_no", "job_id", "recipe_key", "recipe_version", "recipe_source", "modified", "recipe_snapshot", "side_a",
                "side_b", "pairing", "status", "verdict", "summary", "note", "dir_rel", "created_by", "created_at", "finished_at"} <= cols
        idx = dict(eng.connect().execute(text("select indexname, indexdef from pg_indexes where tablename='eq_recipes'")).all())
        assert "ix_eq_recipes_study_name" in idx and "deleted_at IS NULL" in idx["ix_eq_recipes_study_name"]
        active = eng.connect().execute(text("select indexdef from pg_indexes where indexname='ux_jobs_study_type_active'")).scalar()
        assert "EQ_CHECK" in active and "FEM_VERIFY" in active
        with pytest.raises(RuntimeError):  # 행이 있으면 down 거부
            _alembic(url, "0017_geom_view", down=True)
        with eng.begin() as c:
            c.execute(text("delete from eq_checks"))
            c.execute(text("delete from eq_recipes"))
            c.execute(text("delete from notifications where event='EQ_CHECK_DONE'"))
            c.execute(text("delete from jobs where job_type='EQ_CHECK'"))
        _alembic(url, "0017_geom_view", down=True)  # 비어 있으면 되돌림
        with eng.connect() as c:
            assert c.execute(text("select version_num from alembic_version")).scalar() == "0017_geom_view"
            assert not c.execute(text("select to_regclass('eq_checks')")).scalar()
        _alembic(url, "head")
    finally:
        eng.dispose()
        with pg_server["admin"].connect() as c:
            c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


def test_v_eq_1_table_constants_match_migration():
    from physicsai_core.db.tables import notifications
    from physicsai_core.db.tables.equiv_check import EQ_RECIPE_SOURCES, EQ_SCOPES, EQ_STATUSES, EQ_VERDICTS

    mig = (REPO / "migrations" / "versions" / "0018_equiv_check.py").read_text(encoding="utf-8")
    for consts in (EQ_SCOPES, EQ_RECIPE_SOURCES, EQ_STATUSES, EQ_VERDICTS):
        assert "IN (" + ",".join(f"'{v}'" for v in consts) + ")" in mig, consts
    ev = next(str(c.sqltext) for c in notifications.constraints if getattr(c, "name", "") == "ck_notifications_event")
    assert "EQ_CHECK_DONE" in ev and "EQ_CHECK_DONE" in mig
    assert 'down_revision = "0017_geom_view"' in mig


def test_v_eq_9_config_defaults_and_bounds():
    from physicsai_core.config import load_config_dict

    lc = load_config_dict({"storage": {"ai_root": str(REPO)}}, environ={})
    e = lc.settings.equiv_check
    assert (e.dir_name, e.max_pairs, e.max_metrics, e.max_active, e.curve_points, e.snapshot_max_bytes) == ("05_equiv", 200, 20, 2, 1000, 65536)
    assert e.max_extract_copy_bytes == 20 * 1024 ** 3 and e.system_version == 1
    bad = load_config_dict({"storage": {"ai_root": str(REPO)}, "equiv_check": {"dir_name": "04_verify", "max_active": 0, "curve_min_overlap": 1.5,
                                                                             "system_recipe": {"metrics": []}}}, environ={})
    keys = {i.key for i in bad.issues}
    assert {"equiv_check.dir_name", "equiv_check.max_active", "equiv_check.curve_min_overlap", "equiv_check.system_recipe"} <= keys
