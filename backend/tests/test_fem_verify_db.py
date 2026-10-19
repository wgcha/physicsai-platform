"""V3-S16-4: migration 0013_fem_verify — fem_verifications 테이블·CHECK 4종·인덱스, 활성 유일 인덱스에서 FEM_VERIFY·동반 PREDICT 제외
(일반 PREDICT 2개는 여전히 거부), 알림 FEM_VERIFY_DONE, MIGRATION_HEAD, downgrade 거부, 메타데이터 = 마이그레이션."""

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


def _fv(c, sid: str, no: int, **over) -> None:
    v = {"i": str(uuid.uuid4()), "s": sid, "n": no, "sk": "VALUES", "ak": "TRAIN_DOE", "im": "rebuild", "st": "RUNNING", **over}
    c.execute(text("insert into fem_verifications(id, study_id, fv_no, source_kind, source_ref, assem_kind, input_mode, status,"
                   " dir_rel, created_by, created_by_name) values (:i,:s,:n,:sk,'{}',:ak,:im,:st,'04_verify/FV-001','u','u')"), v)


def test_v3_s16_4_migration_0013(pg_server):
    from physicsai_core.db import MIGRATION_HEAD

    assert MIGRATION_HEAD == "0014_multiobj"
    name = f"physicsai_m13_{uuid.uuid4().hex[:8]}"
    with pg_server["admin"].connect() as c:
        c.execute(text(f'CREATE DATABASE "{name}"'))
    base, _, _ = pg_server["admin_url"].rpartition("/")
    url = f"{base}/{name}"
    eng = create_engine(url)
    try:
        _alembic(url, "0012_sampling_kinds")
        sid = str(uuid.uuid4())
        with eng.begin() as c:
            c.execute(text("insert into studies(id, project_id, folder_name, title, ai_root_snapshot, created_by, created_by_name)"
                           " values (:i,'p-1','M13','t','/x','u','u')"), {"i": sid})
            j_old = _job(c, sid, "PREDICT", {"values": {}}, 1)  # 0012 시점 일반 예측(대기) — 보존
        with pytest.raises(IntegrityError), eng.begin() as c:  # 0012에서는 동반 예측도 같은 유형으로 막힘
            _job(c, sid, "PREDICT", {"fem_verify_id": "f0"}, 2)
        _alembic(url, "head")
        with eng.begin() as c:
            assert c.execute(text("select version_num from alembic_version")).scalar() == MIGRATION_HEAD
            assert c.execute(text("select state from jobs where id=:i"), {"i": j_old}).scalar() == "QUEUED"
            _job(c, sid, "PREDICT", {"fem_verify_id": "f1"}, 3)             # 동반 예측 2개 + 일반 1개 동시 대기
            _job(c, sid, "PREDICT", {"fem_verify_id": "f2"}, 4)
            _job(c, sid, "FEM_VERIFY", {"fem_verify_id": "f1"}, 5)          # FEM_VERIFY 여러 개
            _job(c, sid, "FEM_VERIFY", {"fem_verify_id": "f2"}, 6)
            c.execute(text("insert into notifications(user_id, event, title) values ('u','FEM_VERIFY_DONE','t')"))
            _fv(c, sid, 1)
        with pytest.raises(IntegrityError), eng.begin() as c:              # 일반 PREDICT 2개는 여전히 거부
            _job(c, sid, "PREDICT", {"values": {}}, 7)
        for bad in ({"sk": "FOO"}, {"ak": "SPDM"}, {"im": "copy"}, {"st": "DONE2"}, {"n": 0}):
            with pytest.raises(IntegrityError), eng.begin() as c:
                _fv(c, sid, 9, **bad)
        with pytest.raises(IntegrityError), eng.begin() as c:              # (study_id, fv_no) 유일
            _fv(c, sid, 1)
        with pytest.raises(IntegrityError), eng.begin() as c:
            c.execute(text("insert into notifications(user_id, event, title) values ('u','NOPE','t')"))
        cols = {r[0] for r in eng.connect().execute(text(
            "select column_name from information_schema.columns where table_name='fem_verifications'"))}
        assert {"id", "study_id", "fv_no", "source_kind", "source_ref", "predict_job_id", "companion", "param_set_id", "model_id",
                "template_kind", "assem_kind", "assem_ref", "input_mode", "options", "job_id", "attempt_no", "status", "summary",
                "failure_code", "failure_message", "dir_rel", "created_by", "created_by_name", "created_at", "finished_at"} == cols
        idx = dict(eng.connect().execute(text("select indexname, indexdef from pg_indexes where tablename='fem_verifications'")).all())
        assert "ix_fem_verifications_study_created" in idx and "DESC" in idx["ix_fem_verifications_study_created"]
        assert "ix_fem_verifications_predict_job" in idx and "uq_fem_verifications_study_no" in idx
        active = eng.connect().execute(text("select indexdef from pg_indexes where indexname='ux_jobs_study_type_active'")).scalar()
        assert "FEM_VERIFY" in active and "fem_verify_id" in active and "surrogate_opt" in active and "CONTOUR_RECAPTURE" in active
        with pytest.raises(RuntimeError):
            _alembic(url, "0012_sampling_kinds", down=True)
    finally:
        eng.dispose()
        with pg_server["admin"].connect() as c:
            c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


def test_v3_s16_4_table_constants_match_migration():
    import re

    from physicsai_core.db.tables import fem_verifications, notifications
    from physicsai_core.db.tables.fem_verify import FV_ASSEM_KINDS, FV_INPUT_MODES, FV_SOURCE_KINDS, FV_STATUSES

    mig = (REPO / "migrations" / "versions" / "0013_fem_verify.py").read_text(encoding="utf-8")
    for consts in (FV_SOURCE_KINDS, FV_ASSEM_KINDS, FV_INPUT_MODES, FV_STATUSES):
        assert "IN (" + ",".join(f"'{v}'" for v in consts) + ")" in mig, consts
    ev = next(str(c.sqltext) for c in notifications.constraints if getattr(c, "name", "") == "ck_notifications_event")
    assert "FEM_VERIFY_DONE" in ev and "FEM_VERIFY_DONE" in mig
    assert {c.name for c in fem_verifications.columns} >= {"fv_no", "summary", "options"}
    assert re.search(r'down_revision = "0012_sampling_kinds"', mig)
