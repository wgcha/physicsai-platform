"""V3-DB-1: 0004_study_manage — jobs.stage 0 허용(phase3 §5.10, R3-1), downgrade 거부."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from physicsai_test_support import REPO


def _insert(c, sid, stage):
    c.execute(text("insert into jobs(id, study_id, project_id, job_type, stage, lane, state, holds_slot, queue_seq, params,"
                   " created_by, created_by_name) values (:i,:s,'p-1','STUDY_STORAGE_SCAN',:st,'LIGHT','QUEUED',false,1,'{}',"
                   "'u','u')"), {"i": str(uuid.uuid4()), "s": sid, "st": stage})


def test_stage_zero_allowed_and_range_checked(engine):
    from physicsai_core.db import MIGRATION_HEAD

    assert MIGRATION_HEAD == "0010_surrogate_opt"
    sid = str(uuid.uuid4())
    with engine.begin() as c:
        assert c.execute(text("select version_num from alembic_version")).scalar() == MIGRATION_HEAD
        c.execute(text("insert into studies(id, project_id, folder_name, title, ai_root_snapshot, created_by, created_by_name)"
                       " values (:i,'p-1',:f,'t','/x','u','u')"), {"i": sid, "f": "D" + sid[:8]})
        _insert(c, sid, 0)
    for bad in (-1, 6):
        with pytest.raises(IntegrityError), engine.begin() as c:
            _insert(c, sid, bad)


def test_downgrade_refused():
    import importlib.util

    spec = importlib.util.spec_from_file_location("m0004", REPO / "migrations" / "versions" / "0004_study_manage.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    assert mod.down_revision == "0003_hpc_cancel_failed"
    with pytest.raises(RuntimeError):
        mod.downgrade()
