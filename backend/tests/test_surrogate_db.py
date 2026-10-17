"""V3-S13-1: migration 0010_surrogate_opt 왕복 — 두 테이블, Study당 진행 중 1개, 알림 이벤트, jobs 활성 인덱스
(최적화 배치 + 수동 배치 동시 QUEUED 허용, 수동 2개 거부), MIGRATION_HEAD, downgrade 거부."""

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


def _job(c, sid: str, params: dict, seq: int) -> str:
    jid = str(uuid.uuid4())
    c.execute(text("insert into jobs(id, study_id, project_id, job_type, stage, lane, state, holds_slot, queue_seq, params,"
                   " created_by, created_by_name) values (:i,:s,'p-1','PREDICT_BATCH',4,'SLOT','QUEUED',false,:q,"
                   " cast(:p as jsonb),'u','u')"), {"i": jid, "s": sid, "q": seq, "p": json.dumps(params)})
    return jid


def test_migration_0010_roundtrip(pg_server):
    from physicsai_core.db import MIGRATION_HEAD

    assert MIGRATION_HEAD == "0011_surrogate_final"
    name = f"physicsai_m10_{uuid.uuid4().hex[:8]}"
    with pg_server["admin"].connect() as c:
        c.execute(text(f'CREATE DATABASE "{name}"'))
    base, _, _ = pg_server["admin_url"].rpartition("/")
    url = f"{base}/{name}"
    eng = create_engine(url)
    try:
        _alembic(url, "0009_scx_gateway")
        sid = str(uuid.uuid4())
        with eng.begin() as c:
            c.execute(text("insert into studies(id, project_id, folder_name, title, ai_root_snapshot, created_by, created_by_name)"
                           " values (:i,'p-1','M10','t','/x','u','u')"), {"i": sid})
            j_old = _job(c, sid, {"batch_id": "b0"}, 1)  # 0009 시점 수동 배치(대기) — 보존
        _alembic(url, "0010_surrogate_opt")
        _alembic(url, "0011_surrogate_final")  # D3-61 마무리 캡처(FINALIZING·FINAL·final 열)
        with eng.begin() as c:
            assert c.execute(text("select version_num from alembic_version")).scalar() == MIGRATION_HEAD
            assert c.execute(text("select state from jobs where id=:i"), {"i": j_old}).scalar() == "QUEUED"
            # 최적화 소유 배치는 수동 배치와 함께 대기 가능
            _job(c, sid, {"batch_id": "b1", "surrogate_opt": {"id": "o", "opt_no": 1, "iter_no": 0}}, 2)
            c.execute(text("insert into notifications(user_id, event, title) values ('u','SURROGATE_OPT_DONE','t')"))
        with pytest.raises(IntegrityError):  # 수동 2개 거부
            with eng.begin() as c:
                _job(c, sid, {"batch_id": "b2"}, 3)
        cols = {r[0] for r in eng.connect().execute(text(
            "select column_name from information_schema.columns where table_name='surrogate_opts'"))}
        assert {"final", "opt_no", "settings", "status", "iter_no", "current_job_id", "best", "stop_reason", "dir_rel"} <= cols
        icols = {r[0] for r in eng.connect().execute(text(
            "select column_name from information_schema.columns where table_name='surrogate_opt_iters'"))}
        assert {"opt_id", "iter_no", "kind", "batch_id", "round_job_id", "fit", "candidates", "best_value",
                "best_feasible", "improvement_rel"} <= icols
        idx = eng.connect().execute(text("select indexdef from pg_indexes where indexname='ux_surrogate_opts_active'")).scalar()
        assert "UNIQUE" in idx and "EXPLORING" in idx and "VERIFYING" in idx and "FINALIZING" in idx
        assert "final" in cols
        with pytest.raises(IntegrityError):
            with eng.begin() as c:
                c.execute(text("insert into notifications(user_id, event, title) values ('u','NOPE','t')"))
        with pytest.raises(RuntimeError):
            _alembic(url, "0009_scx_gateway", down=True)
    finally:
        eng.dispose()
        with pg_server["admin"].connect() as c:
            c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


def test_one_active_opt_per_study(engine):
    """부분 유일 인덱스: 같은 Study에 진행 중 opt 2개 거부, 종료 opt는 여러 개."""
    from physicsai_core.db.repositories import surrogate_opts as so_repo

    with engine.begin() as c:
        sid = str(uuid.uuid4())
        c.execute(text("insert into studies(id, project_id, folder_name, title, ai_root_snapshot, created_by, created_by_name)"
                       " values (:i,'p-1',:f,'t','/x','u','u')"), {"i": sid, "f": f"S{uuid.uuid4().hex[:6]}"})
        mid, psid = str(uuid.uuid4()), str(uuid.uuid4())
        c.execute(text("alter table surrogate_opts drop constraint surrogate_opts_param_set_id_fkey"))
        c.execute(text("alter table surrogate_opts drop constraint surrogate_opts_model_id_fkey"))

        def mk(no: int, status: str) -> None:
            so_repo.create_opt(c, id=str(uuid.uuid4()), study_id=sid, opt_no=no, param_set_id=psid, model_id=mid,
                               input_kind="mesh_only", settings={}, status=status, dir_rel="x", created_by="u",
                               created_by_name="u")

        mk(1, "DONE")
        mk(2, "CANCELED")
        mk(3, "EXPLORING")
        assert so_repo.active_for_study(c, sid)["opt_no"] == 3 and so_repo.next_opt_no(c, sid) == 4
        sp = c.begin_nested()
        with pytest.raises(IntegrityError):
            mk(4, "FITTING")
        sp.rollback()
        assert so_repo.opt_label(3) == "SO-003" and so_repo.opt_dir_rel("05_opt/surrogate", 3) == "05_opt/surrogate/SO-003"
        c.rollback()
