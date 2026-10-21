"""geometry-engine.md §7.5 / V-GE-8: migration 0016_geometry_engine(Revises S18 0015_doe_platform_gen) — 기존 행 altair/NULL, native 제약, FEATURE_PNG, downgrade 거부."""

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


_PS = ("insert into param_sets(id, study_id, source_path, stored_rel, parameters, responses, sample_count, sample_has_measured,"
       " cad_file_name, {tpl}assem_rel, starter_name, tpl_params, registered_by, registered_by_name{extra}) values"
       " (:i,:s,'/x','04_params/x',cast('[]' as jsonb),cast('[]' as jsonb),0,false,'a.step',{tplv}'a','s.rad',cast('[]' as jsonb),'u','u'{extrav})")


def _ps(c, sid: str, *, tpl: bool = True, engine: str | None = None, input_kind: str | None = None) -> None:
    extra = (", engine" if engine else "") + (", input_kind" if input_kind else "")
    extrav = (f", '{engine}'" if engine else "") + (f", '{input_kind}'" if input_kind else "")
    c.execute(text(_PS.format(tpl="tpl_rel, " if tpl else "", tplv="'t.tpl', " if tpl else "", extra=extra, extrav=extrav)),
              {"i": str(uuid.uuid4()), "s": sid})


def test_migration_0016_roundtrip(pg_server):
    from physicsai_core.db import MIGRATION_HEAD

    assert MIGRATION_HEAD == "0020_mcp"  # geometry-view.md §6.7: 0017이 0016 다음 — 0016까지만 올려 확인
    name = f"physicsai_m12_{uuid.uuid4().hex[:8]}"
    with pg_server["admin"].connect() as c:
        c.execute(text(f'CREATE DATABASE "{name}"'))
    base, _, _ = pg_server["admin_url"].rpartition("/")
    url = f"{base}/{name}"
    eng = create_engine(url)
    try:
        _alembic(url, "0015_doe_platform_gen")
        sid = str(uuid.uuid4())
        with eng.begin() as c:
            c.execute(text("insert into studies(id, project_id, folder_name, title, ai_root_snapshot, created_by, created_by_name)"
                           " values (:i,'p-1','M12','t','/x','u','u')"), {"i": sid})
            _ps(c, sid)  # 0015 시점 세트(altair 템플릿)
        _alembic(url, "0016_geometry_engine")
        with eng.begin() as c:
            assert c.execute(text("select version_num from alembic_version")).scalar() == "0016_geometry_engine"
            row = c.execute(text("select engine, geom_options, engine_version, tpl_rel from param_sets")).one()
            assert tuple(row) == ("altair", None, None, "t.tpl")  # 기존 행 보존
            _ps(c, sid, tpl=False, engine="native")  # native: tpl_rel NULL 허용
        for bad in (dict(tpl=False),  # altair인데 tpl 없음
                    dict(tpl=False, engine="native", input_kind="mesh_only"),  # native는 assembly만
                    dict(engine="x")):
            with pytest.raises(IntegrityError):
                with eng.begin() as c:
                    _ps(c, sid, **bad)
        cols = lambda t: {r[0]: r[1:] for r in eng.connect().execute(text(  # noqa: E731
            "select column_name, is_nullable, column_default from information_schema.columns where table_name=:t"), {"t": t})}
        for t in ("train_setups", "train_does"):
            assert cols(t)["engine"][0] == "NO" and "altair" in cols(t)["engine"][1]
        assert {"features_rel"} <= set(cols("train_setups")) and {"geom_options", "engine_version"} <= set(cols("train_does"))
        for t in ("datasets", "models"):
            assert cols(t)["engine"][0] == "YES" and cols(t)["engine"][1] is None  # 기존 행 = 모름
        assert "engine_version" in cols("datasets") and "engine_version" in cols("predict_batch_runs")
        defs = dict(eng.connect().execute(text(
            "select conname, pg_get_constraintdef(oid) from pg_constraint where conname in ('ck_artifacts_kind','ck_datasets_engine')")).all())
        assert "FEATURE_PNG" in defs["ck_artifacts_kind"] and "native" in defs["ck_datasets_engine"]
        with pytest.raises(RuntimeError):
            _alembic(url, "0015_doe_platform_gen", down=True)
    finally:
        eng.dispose()
        with pg_server["admin"].connect() as c:
            c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
