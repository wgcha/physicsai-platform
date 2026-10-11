"""V-SM-2~4: 대기열 순서·LIGHT 병행·순서 이동·내 차례 알림·취소. lease는 test_lease, 실패·재시도는 test_step_failures."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import httpx
import psutil
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from helpers_queue import AW, PW, P, _dataset_job, _state
from physicsai_test_support import API, wait_for


def test_fifo_positions_and_claim_order(client, engine, loaded_config, worker_factory):
    from physicsai_core.db.repositories import job_lease as lease_repo

    ai = loaded_config.settings.storage.ai_root
    ids = [_dataset_job(client, ai, f"F{i}")[1]["id"] for i in range(3)]
    q = client.get(f"{API}/queue", headers=P).json()
    assert [x["id"] for x in q["queued"]] == ids and [x["queue_position"] for x in q["queued"]] == [1, 2, 3]
    order = []
    for _ in range(3):
        with engine.begin() as c:
            j = lease_repo.claim_slot(c, "w-test", 30)
        order.append(j["id"])
        # 슬롯 보유 중에는 다음 claim 없음
        with engine.begin() as c:
            assert lease_repo.claim_slot(c, "w-test", 30) is None
        with engine.begin() as c:
            lease_repo.release(c, j["id"], j["lease_token"], "SUCCEEDED")
    assert order == ids


def test_light_runs_while_slot_busy(client, engine, loaded_config, worker_factory):
    ai = loaded_config.settings.storage.ai_root
    sid, j = _dataset_job(client, ai, "L1")
    w = worker_factory()
    held = w.claim_only()
    assert held["id"] == j["id"] and held["holds_slot"]
    # LIGHT 작업(모델 등록)은 슬롯과 무관하게 실행
    from physicsai_test_support import make_model_folder

    mf = make_model_folder(Path(ai) / "L1" / "00_inbox")
    r = client.post(f"{API}/studies/{sid}/jobs", headers=PW, json={"job_type": "MODEL_REGISTER", "params": {"model_path": str(mf)}})
    assert r.status_code == 201
    assert w.run_once_light() == "SUCCEEDED"
    assert _state(engine, j["id"])["state"] == "RUNNING"


def test_admin_move_changes_claim_order(client, engine, loaded_config):
    from physicsai_core.db.repositories import job_lease as lease_repo

    ai = loaded_config.settings.storage.ai_root
    ids = [_dataset_job(client, ai, f"M{i}")[1]["id"] for i in range(3)]
    assert client.post(f"{API}/queue/{ids[2]}/move", headers=PW, json={"position": 1}).status_code == 403
    r = client.post(f"{API}/queue/{ids[2]}/move", headers=AW, json={"position": 1})
    assert r.status_code == 200
    assert [x["id"] for x in r.json()["queued"]] == [ids[2], ids[0], ids[1]]
    with engine.begin() as c:
        j = lease_repo.claim_slot(c, "w", 30)
    assert j["id"] == ids[2]
    r = client.post(f"{API}/queue/{ids[2]}/move", headers=AW, json={"position": 1})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "JOB_NOT_QUEUED"
    with engine.connect() as c:
        actions = [a for (a,) in c.execute(text("select action from audit_events"))]
    assert "QUEUE_MOVE" in actions


def test_my_turn_next_once(client, engine, loaded_config, worker_factory):
    ai = loaded_config.settings.storage.ai_root
    _s1, j1 = _dataset_job(client, ai, "N1")
    _s2, j2 = _dataset_job(client, ai, "N2")
    w = worker_factory()
    w.claim_only()
    with engine.connect() as c:
        rows = c.execute(text("select event, job_id from notifications order by seq")).all()
    assert ("JOB_STARTED", j1["id"]) in [tuple(r) for r in rows]
    assert [tuple(r) for r in rows].count(("MY_TURN_NEXT", j2["id"])) == 1
    _s3, _j3 = _dataset_job(client, ai, "N3")
    with engine.connect() as c:
        assert c.execute(text("select count(*) from notifications where event='MY_TURN_NEXT'")).scalar() == 1


def test_cancel_queued_immediately(client, engine, loaded_config):
    _sid, j = _dataset_job(client, loaded_config.settings.storage.ai_root, "C1")
    r = client.post(f"{API}/jobs/{j['id']}/cancel", headers=PW)
    assert r.status_code == 403 and r.json()["detail"]["required"] == "global_admin"
    r = client.post(f"{API}/jobs/{j['id']}/cancel", headers=AW)
    assert r.status_code == 202 and r.json()["state"] == "CANCELED"
    st = _state(engine, j["id"])
    assert st["queue_seq"] is None
    r = client.post(f"{API}/jobs/{j['id']}/cancel", headers=AW)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "JOB_TERMINAL"
    with engine.connect() as c:
        assert c.execute(text("select status from datasets")).scalar() == "FAILED"
        assert c.execute(text("select count(*) from notifications where event='JOB_CANCELED'")).scalar() == 1


def test_cancel_running_kills_process_tree(client, engine, loaded_config, worker_factory, monkeypatch, tmp_path, fake_record):
    pidfile = tmp_path / "pids"
    monkeypatch.setenv("FAKE_TOOL_MODE_EDSPY", "hang")
    monkeypatch.setenv("FAKE_TOOL_PIDFILE", str(pidfile))
    _sid, j = _dataset_job(client, loaded_config.settings.storage.ai_root, "C2")
    w = worker_factory()
    out: dict = {}
    t = threading.Thread(target=lambda: out.setdefault("r", w.run_once_slot()))
    t.start()
    wait_for(lambda: pidfile.exists() and pidfile.read_text().strip())
    pids = [int(x) for x in pidfile.read_text().split()]
    assert all(psutil.pid_exists(p) for p in pids)
    t0 = time.time()
    r = client.post(f"{API}/jobs/{j['id']}/cancel", headers=AW)
    assert r.status_code == 202 and r.json()["cancel_requested"] is True
    t.join(timeout=20)
    assert out["r"] == "CANCELED"
    assert time.time() - t0 < 10
    for p in pids:
        assert not psutil.pid_exists(p) or psutil.Process(p).status() == psutil.STATUS_ZOMBIE
    st = _state(engine, j["id"])
    assert st["state"] == "CANCELED" and st["lease_token"] is None and not st["holds_slot"]
    with engine.connect() as c:
        assert c.execute(text("select holder_job_id from worker_slot")).scalar() is None
        steps = dict(c.execute(text("select step_key, state from job_steps where job_id=:i"), {"i": j["id"]}).all())
    assert steps["EDSPY_DATASET_TRAIN"] == "CANCELED" and steps["DS_REGISTER"] == "CANCELED"


__all__ = ["httpx", "TestClient", "pytest"]
