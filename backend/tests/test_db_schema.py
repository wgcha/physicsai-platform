"""V-DB-1, V-DB-2, V-DB-4: migration·CHECK 제약·본문 컬럼 없음."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from physicsai_core.db import MIGRATION_HEAD
from physicsai_test_support import REPO


def test_upgrade_head_creates_all_tables(engine):
    names = set(inspect(engine).get_table_names())
    for t in ("studies", "datasets", "models", "param_sets", "jobs", "job_steps", "artifacts", "notifications",
              "worker_slot", "worker_heartbeats", "hpc_jobs", "audit_events", "alembic_version"):
        assert t in names
    with engine.connect() as c:
        assert c.execute(text("select version_num from alembic_version")).scalar() == MIGRATION_HEAD
        assert c.execute(text("select count(*) from worker_slot")).scalar() == 1
        assert c.execute(text("select nextval('job_queue_seq')")).scalar() >= 1


def test_downgrade_raises(db_url):
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(REPO / "migrations" / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO / "migrations"))
    cfg.attributes["url"] = db_url
    with pytest.raises(RuntimeError):
        command.downgrade(cfg, "base")


def _study(c):
    sid = str(uuid.uuid4())
    c.execute(text("insert into studies(id, project_id, folder_name, title, ai_root_snapshot, created_by, created_by_name)"
                   " values (:i,'p-1',:f,'t','/x','u','u')"), {"i": sid, "f": "S" + sid[:8]})
    return sid


def _job(c, sid, **kw):
    vals = dict(id=str(uuid.uuid4()), study_id=sid, project_id="p-1", job_type="EVALUATE", stage=3, lane="SLOT",
                state="QUEUED", holds_slot=False, queue_seq=1, params="{}", created_by="u", created_by_name="u")
    vals.update(kw)
    cols = ",".join(vals)
    ph = ",".join(f":{k}" for k in vals)
    c.execute(text(f"insert into jobs({cols}) values ({ph})"), vals)


@pytest.mark.parametrize(
    "kw",
    [
        dict(state="RUNNING", holds_slot=False, queue_seq=None),
        dict(state="QUEUED", queue_seq=None),
        dict(state="RUNNING", holds_slot=True, queue_seq=None, lease_token="t"),
        dict(state="WAITING_HPC", queue_seq=None, lease_owner_id="w", lease_token="t",
             lease_acquired_at="2026-01-01", lease_expires_at="2026-01-02"),
        dict(state="RUNNING", holds_slot=True, queue_seq=None, lease_owner_id="w", lease_token="t",
             lease_acquired_at="2026-01-02", lease_expires_at="2026-01-01"),
    ],
    ids=["holds_slot", "queue_seq", "lease_identity", "lease_state", "lease_order"],
)
def test_jobs_check_constraints(engine, kw):
    with engine.connect() as c:
        sid = _study(c)
        with pytest.raises(IntegrityError):
            _job(c, sid, **kw)


def test_valid_job_row_accepted(engine):
    with engine.connect() as c:
        sid = _study(c)
        _job(c, sid)


def test_worker_slot_single_row(engine):
    with engine.connect() as c:
        with pytest.raises(IntegrityError):
            c.execute(text("insert into worker_slot(id) values (2)"))


def test_no_file_body_columns(engine):
    insp = inspect(engine)
    for t in insp.get_table_names():
        for col in insp.get_columns(t):
            assert col["name"] not in ("log_text", "content", "body_text", "file_content", "yaml", "raw")
