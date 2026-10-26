"""doe-preview.md §6.7·V-DP-13: migration 0025_doe_preview(Revises 0024_contour3d_field) — artifacts kind GEOM_THUMB_PNG, 활성 unique 제외(DOE_PREVIEW),
doe_previews·doe_preview_cells(제약·인덱스), 기존 행 보존, downgrade(데이터 있으면 거부·없으면 되돌림), 메타데이터 = 마이그레이션, 번호 1개."""

from __future__ import annotations

import re
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


def _job(c, sid: str, jt: str, lane: str = "CPU", state: str = "QUEUED") -> str:
    jid = str(uuid.uuid4())
    c.execute(text("insert into jobs(id, study_id, project_id, job_type, stage, lane, state, holds_slot, queue_seq, params,"
                   " created_by, created_by_name) values (:i,:s,'p-1',:t,1,:l,:st,false,:q,'{}','u','u')"),
              {"i": jid, "s": sid, "t": jt, "l": lane, "st": state, "q": 1 if state == "QUEUED" else None})
    return jid


@pytest.fixture()
def fresh_db(pg_server):
    name = f"physicsai_dp_{uuid.uuid4().hex[:8]}"
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
                   " values (:i,'p-1','DP','t','/x','u','u')"), {"i": sid})
    return sid


def test_v_dp_13_migration_0025_up_constraints_and_rows_preserved(fresh_db):
    from physicsai_core.db import MIGRATION_HEAD

    url, eng = fresh_db
    assert MIGRATION_HEAD == "0025_doe_preview"
    _alembic(url, "0024_contour3d_field")
    ins = text("insert into artifacts(id, study_id, kind, rel_path, size, content_type) values (:u,:s,:k,'x',1,'image/png')")
    with eng.begin() as c:
        sid = _study(c)
        old_job = _job(c, sid, "PREDICT", "CPU")
        c.execute(ins, {"u": str(uuid.uuid4()), "s": sid, "k": "CONTOUR3D_GLB"})
        with pytest.raises(IntegrityError), c.begin_nested():
            c.execute(ins, {"u": str(uuid.uuid4()), "s": sid, "k": "GEOM_THUMB_PNG"})  # 0024: 새 kind 없음
    _alembic(url, "head")
    with eng.begin() as c:
        assert c.execute(text("select version_num from alembic_version")).scalar() == MIGRATION_HEAD
        assert c.execute(text("select state from jobs where id=:i"), {"i": old_job}).scalar() == "QUEUED"  # 기존 행 보존
        c.execute(ins, {"u": str(uuid.uuid4()), "s": sid, "k": "GEOM_THUMB_PNG"})
        _job(c, sid, "DOE_PREVIEW")
        _job(c, sid, "DOE_PREVIEW")  # 활성 unique 제외(같은 Study 여러 미리보기 대기 — 동시 제한은 서비스 규칙)
        with pytest.raises(IntegrityError), c.begin_nested():
            _job(c, sid, "PREDICT", "CPU")  # 일반 작업의 활성 unique는 그대로
        for k in ("PREVIEW_JSON", "GEOM_PREVIEW_GLB", "CONTOUR3D_LOD"):  # 기존 kind 유지
            c.execute(ins, {"u": str(uuid.uuid4()), "s": sid, "k": k})
        with pytest.raises(IntegrityError), c.begin_nested():
            c.execute(ins, {"u": str(uuid.uuid4()), "s": sid, "k": "BOGUS"})
        q = text("insert into doe_previews(id, study_id, created_by, grid_key, source_kind, source_ref, \"select\", status)"
                 " values (:i,:s,'u',:g,:sk,'{}','{}',:st)")
        c.execute(q, {"i": str(uuid.uuid4()), "s": sid, "g": "g" * 64, "sk": "train", "st": "QUEUED"})
        c.execute(q, {"i": str(uuid.uuid4()), "s": sid, "g": "g" * 64, "sk": "param_set", "st": "DONE"})  # grid_key는 유일하지 않다(인덱스만)
        for sk, st in (("bogus", "DONE"), ("train", "EXPIRED")):
            with pytest.raises(IntegrityError), c.begin_nested():
                c.execute(q, {"i": str(uuid.uuid4()), "s": sid, "g": "h" * 64, "sk": sk, "st": st})
        cq = text("insert into doe_preview_cells(cache_key, study_id, status, values) values (:k,:s,:st,'{}')")
        c.execute(cq, {"k": "a" * 64, "s": sid, "st": "DONE"})
        with pytest.raises(IntegrityError), c.begin_nested():
            c.execute(cq, {"k": "a" * 64, "s": sid, "st": "DONE"})  # 셀 키는 PK
        with pytest.raises(IntegrityError), c.begin_nested():
            c.execute(cq, {"k": "b" * 64, "s": sid, "st": "QUEUED"})
        idx = {r[0] for r in c.execute(text("select indexname from pg_indexes where tablename in ('doe_previews','doe_preview_cells')"))}
        assert {"ix_doe_previews_creator_status", "ix_doe_previews_grid_key", "ix_doe_preview_cells_last_access"} <= idx
    with pytest.raises(RuntimeError, match="데이터 보호"):  # 미리보기·셀·썸네일 데이터가 있으면 되돌리지 않는다
        _alembic(url, "0024_contour3d_field", down=True)


def test_v_dp_13_migration_0025_downgrade_when_empty(fresh_db):
    url, eng = fresh_db
    _alembic(url, "head")
    _alembic(url, "0024_contour3d_field", down=True)
    with eng.begin() as c:
        assert c.execute(text("select version_num from alembic_version")).scalar() == "0024_contour3d_field"
        tables = {r[0] for r in c.execute(text("select table_name from information_schema.tables where table_schema='public'"))}
        assert "doe_previews" not in tables and "doe_preview_cells" not in tables
        kind = c.execute(text("select pg_get_constraintdef(oid) from pg_constraint where conname='ck_artifacts_kind'")).scalar()
        assert "GEOM_THUMB_PNG" not in kind and "CONTOUR3D_LOD" in kind
        sid = _study(c)
        _job(c, sid, "PREDICT", "CPU")
        with pytest.raises(IntegrityError), c.begin_nested():
            _job(c, sid, "PREDICT", "CPU")  # 되돌린 뒤 활성 unique가 DOE_PREVIEW 제외 없이 그대로
    _alembic(url, "head")  # 다시 올릴 수 있다


def test_v_dp_13_downgrade_blocked_by_each_kind_of_data(fresh_db):
    """DOE_PREVIEW 작업 하나만 있어도, 썸네일 산출물 하나만 있어도 되돌리지 않는다(0017·0024 선례)."""
    url, eng = fresh_db
    _alembic(url, "head")
    with eng.begin() as c:
        sid = _study(c)
        _job(c, sid, "DOE_PREVIEW")
    with pytest.raises(RuntimeError, match="데이터 보호"):
        _alembic(url, "0024_contour3d_field", down=True)
    with eng.begin() as c:
        c.execute(text("delete from jobs"))
        c.execute(text("insert into artifacts(id, study_id, kind, rel_path, size, content_type) select :u, id, 'GEOM_THUMB_PNG', 'x', 1,"
                       " 'image/png' from studies limit 1"), {"u": str(uuid.uuid4())})
    with pytest.raises(RuntimeError, match="데이터 보호"):
        _alembic(url, "0024_contour3d_field", down=True)


def test_v_dp_13_metadata_matches_migration_and_single_migration():
    from physicsai_core.db.tables import artifacts, doe_preview_cells, doe_previews, jobs
    from physicsai_core.geometry.view import MEDIA_KINDS, THUMB_KIND

    src = (REPO / "migrations" / "versions" / "0025_doe_preview.py").read_text(encoding="utf-8")
    assert re.search(r'^revision = "0025_doe_preview"', src, re.M) and re.search(r'^down_revision = "0024_contour3d_field"', src, re.M)
    assert THUMB_KIND == "GEOM_THUMB_PNG" and THUMB_KIND in MEDIA_KINDS and f"'{THUMB_KIND}'" in src
    assert THUMB_KIND in str([c.sqltext for c in artifacts.constraints if getattr(c, "name", "") == "ck_artifacts_kind"][0])
    assert {c.name for c in doe_previews.c} >= {"grid_key", "source_kind", "source_ref", "matrix_key", "select", "status", "cell_keys", "n_total",
                                               "n_ok", "n_fail", "n_error", "timing", "job_id", "finished_at"}
    assert {c.name for c in doe_preview_cells.c} >= {"cache_key", "result_status", "code", "category", "max_disp_mm", "clipped", "values",
                                                     "png_artifact_id", "glb_artifact_id", "manifest_artifact_id", "bytes", "last_access_at"}
    ux = [i for i in jobs.indexes if i.name == "ux_jobs_study_type_active"][0]
    assert "DOE_PREVIEW" in str(ux.dialect_options["postgresql"]["where"])
    versions = sorted(p.name for p in (REPO / "migrations" / "versions").glob("00*.py"))
    assert versions[-1] == "0025_doe_preview.py" and sum(1 for v in versions if v.startswith("0025")) == 1  # 새 migration은 1개
