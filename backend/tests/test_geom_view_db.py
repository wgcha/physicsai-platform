"""geometry-view.md §6.7: migration 0017_geom_view(Revises 0016_geometry_engine) — 레인 PREVIEW, artifacts kind 8종, 활성 unique 제외,
geom_previews·contour3d_cache(부분 unique cache_key), 기존 행 보존, downgrade(데이터 있으면 거부·없으면 되돌림), 메타데이터 = 마이그레이션."""

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


def _job(c, sid: str, jt: str, lane: str, state: str = "QUEUED") -> str:
    jid = str(uuid.uuid4())
    c.execute(text("insert into jobs(id, study_id, project_id, job_type, stage, lane, state, holds_slot, queue_seq, params,"
                   " created_by, created_by_name) values (:i,:s,'p-1',:t,4,:l,:st,false,:q,'{}','u','u')"),
              {"i": jid, "s": sid, "t": jt, "l": lane, "st": state, "q": 1 if state == "QUEUED" else None})
    return jid


def _ps(c, sid: str) -> str:
    pid = str(uuid.uuid4())
    c.execute(text("insert into param_sets(id, study_id, source_path, stored_rel, parameters, responses, sample_count, sample_has_measured,"
                   " cad_file_name, assem_rel, starter_name, tpl_params, registered_by, registered_by_name, engine, input_kind)"
                   " values (:i,:s,'/x','04_params/x','[]','[]',0,false,'a.step','a','s.rad','[]','u','u','native','assembly')"),
              {"i": pid, "s": sid})
    return pid


@pytest.fixture()
def fresh_db(pg_server):
    name = f"physicsai_gv_{uuid.uuid4().hex[:8]}"
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


def test_migration_0017_upgrade_constraints_and_rows_preserved(fresh_db):
    from physicsai_core.db import MIGRATION_HEAD

    url, eng = fresh_db
    assert MIGRATION_HEAD == "0021_uploads"
    _alembic(url, "0016_geometry_engine")
    sid = str(uuid.uuid4())
    with eng.begin() as c:
        c.execute(text("insert into studies(id, project_id, folder_name, title, ai_root_snapshot, created_by, created_by_name)"
                       " values (:i,'p-1','GV','t','/x','u','u')"), {"i": sid})
        old_job = _job(c, sid, "PREDICT", "SLOT")
        with pytest.raises(IntegrityError), c.begin_nested():
            _job(c, sid, "GEOM_PREVIEW", "PREVIEW")  # 0016: PREVIEW 레인 없음
    _alembic(url, "head")
    with eng.begin() as c:
        assert c.execute(text("select version_num from alembic_version")).scalar() == MIGRATION_HEAD
        assert c.execute(text("select state from jobs where id=:i"), {"i": old_job}).scalar() == "QUEUED"  # 기존 행 보존
        _job(c, sid, "GEOM_PREVIEW", "PREVIEW")
        _job(c, sid, "GEOM_PREVIEW", "PREVIEW")  # 활성 unique 제외(같은 Study·유형 여러 개 대기)
        _job(c, sid, "CONTOUR_3D", "LIGHT")
        _job(c, sid, "CONTOUR_3D", "LIGHT")
        for k in ("GEOM_VIEW_GLB", "GEOM_VIEW_MANIFEST", "GEOM_PREVIEW_GLB", "GEOM_PREVIEW_FE_GLB", "GEOM_PREVIEW_MANIFEST",
                  "CONTOUR3D_GLB", "CONTOUR3D_FRAMES", "CONTOUR3D_MANIFEST"):
            c.execute(text("insert into artifacts(id, study_id, kind, rel_path, size, content_type) values (:u,:s,:k,'x',1,'model/gltf-binary')"),
                      {"u": str(uuid.uuid4()), "s": sid, "k": k})
        with pytest.raises(IntegrityError), c.begin_nested():
            _job(c, sid, "PREDICT", "BOGUS")
        with pytest.raises(IntegrityError), c.begin_nested():
            _job(c, sid, "PREDICT", "SLOT")  # 일반 작업의 활성 unique는 그대로
        pid = _ps(c, sid)
        q = text("insert into geom_previews(id, study_id, param_set_id, cache_key, created_by, status, fe, values)"
                 " values (:i,:s,:p,:k,'u',:st,'off','{}')")
        c.execute(q, {"i": str(uuid.uuid4()), "s": sid, "p": pid, "k": "k" * 64, "st": "DONE"})
        c.execute(q, {"i": str(uuid.uuid4()), "s": sid, "p": pid, "k": "k" * 64, "st": "EXPIRED"})  # 종료 행은 같은 키 허용
        with pytest.raises(IntegrityError), c.begin_nested():
            c.execute(q, {"i": str(uuid.uuid4()), "s": sid, "p": pid, "k": "k" * 64, "st": "QUEUED"})  # 살아 있는 행은 키당 1개
        with pytest.raises(IntegrityError), c.begin_nested():
            c.execute(q, {"i": str(uuid.uuid4()), "s": sid, "p": pid, "k": "z" * 64, "st": "BOGUS"})
        cq = text("insert into contour3d_cache(id, study_id, cache_key, created_by, status, source_kind, source_ref)"
                  " values (:i,:s,:k,'u',:st,:sk,'{}')")
        c.execute(cq, {"i": str(uuid.uuid4()), "s": sid, "k": "c" * 64, "st": "RUNNING", "sk": "PREDICT_H3D"})
        with pytest.raises(IntegrityError), c.begin_nested():
            c.execute(cq, {"i": str(uuid.uuid4()), "s": sid, "k": "c" * 64, "st": "DONE", "sk": "PREDICT_H3D"})
        with pytest.raises(IntegrityError), c.begin_nested():
            c.execute(cq, {"i": str(uuid.uuid4()), "s": sid, "k": "d" * 64, "st": "DONE", "sk": "OTHER"})
    with pytest.raises(RuntimeError, match="데이터 보호"):  # 미리보기·컨투어 데이터가 있으면 되돌리지 않는다
        _alembic(url, "0016_geometry_engine", down=True)


def test_migration_0017_downgrade_when_empty(fresh_db):
    url, eng = fresh_db
    _alembic(url, "head")
    _alembic(url, "0016_geometry_engine", down=True)
    with eng.begin() as c:
        assert c.execute(text("select version_num from alembic_version")).scalar() == "0016_geometry_engine"
        tables = {r[0] for r in c.execute(text("select table_name from information_schema.tables where table_schema='public'"))}
        assert "geom_previews" not in tables and "contour3d_cache" not in tables
        lane = c.execute(text("select pg_get_constraintdef(oid) from pg_constraint where conname='ck_jobs_lane'")).scalar()
        assert "PREVIEW" not in lane
    _alembic(url, "head")  # 다시 올릴 수 있다


def test_metadata_matches_migration_constants():
    from physicsai_core.db.tables import artifacts, contour3d_cache, geom_previews, jobs
    from physicsai_core.geometry.view import NEW_ARTIFACT_KINDS

    src = (REPO / "migrations" / "versions" / "0017_geom_view.py").read_text(encoding="utf-8")
    for k in NEW_ARTIFACT_KINDS:
        assert f"'{k}'" in src and k in str([c.sqltext for c in artifacts.constraints if getattr(c, "name", "") == "ck_artifacts_kind"][0])
    assert "PREVIEW" in str([c.sqltext for c in jobs.constraints if getattr(c, "name", "") == "ck_jobs_lane"][0])
    assert {c.name for c in geom_previews.c} >= {"cache_key", "values", "last_access_at", "glb_artifact_id", "fe_glb_artifact_id"}
    assert {c.name for c in contour3d_cache.c} >= {"cache_key", "source_kind", "frames_artifact_id", "last_access_at"}
