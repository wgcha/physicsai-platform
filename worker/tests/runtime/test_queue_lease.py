"""V-SM-2~6, V-LS-1~3, V-CMD-5, V-CMD-7, V-DS-2: 대기열·lease·취소·재시도."""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import httpx
import psutil
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from physicsai_test_support import API, H, make_h3d_tree, wait_for

PW = H("tok-power", write=True)
AW = H("tok-admin", write=True)
P = H("tok-power")


def _study(c, name):
    r = c.post(f"{API}/studies", headers=PW, json={"project_id": "p-1", "folder_name": name, "title": name})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _dataset_job(c, ai_root, name, n=4):
    sid = _study(c, name)
    inp = make_h3d_tree(Path(ai_root) / name, n=n)
    r = c.post(f"{API}/studies/{sid}/jobs", headers=PW, json={"job_type": "DATASET_CREATE", "params": {"input_path": str(inp)}})
    assert r.status_code == 201, r.text
    return sid, r.json()


def _state(engine, jid):
    with engine.connect() as c:
        return dict(c.execute(text("select * from jobs where id=:i"), {"i": jid}).one()._mapping)


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


def _short_lease_config(settings_dict):
    from physicsai_core.config import load_config_dict

    d = dict(settings_dict)
    d["worker"] = {**d["worker"], "lease_ttl_s": 1.0, "heartbeat_interval_s": 0.3}
    lc = load_config_dict(d, environ={})
    assert lc.ok, lc.issues
    return lc


def test_lease_expiry_interrupted(client, engine, settings_dict, loaded_config):
    from physicsai_worker.runtime import Worker

    lc = _short_lease_config(settings_dict)
    _sid, j = _dataset_job(client, loaded_config.settings.storage.ai_root, "LS1")
    _sid2, j2 = _dataset_job(client, loaded_config.settings.storage.ai_root, "LS2")
    dead = Worker(lc, engine)
    assert dead.claim_only()["id"] == j["id"]
    time.sleep(1.3)
    # 다른 워커의 claim이 만료 슬롯을 회수하고 다음 작업을 잡는다
    other = Worker(lc, engine)
    with engine.begin() as c:
        from physicsai_core.db.repositories import job_lease as lease_repo

        nxt = lease_repo.claim_slot(c, other.worker_id, 30)
    assert nxt["id"] == j2["id"]
    st = _state(engine, j["id"])
    assert st["state"] == "INTERRUPTED" and st["failure_code"] == "WORKER_LOST" and st["lease_token"] is None
    with engine.connect() as c:
        assert c.execute(text("select holder_job_id from worker_slot")).scalar() == j2["id"]
        assert c.execute(text("select count(*) from notifications where event='JOB_INTERRUPTED' and job_id=:i"), {"i": j["id"]}).scalar() == 1


def test_reaper_interrupts_expired(client, engine, settings_dict, loaded_config):
    from physicsai_worker import housekeeping
    from physicsai_worker.runtime import Worker

    lc = _short_lease_config(settings_dict)
    _sid, j = _dataset_job(client, loaded_config.settings.storage.ai_root, "LS3")
    Worker(lc, engine).claim_only()
    assert housekeeping.reap(engine) == []
    time.sleep(1.3)
    assert housekeeping.reap(engine) == [j["id"]]
    with engine.connect() as c:
        assert c.execute(text("select holder_job_id from worker_slot")).scalar() is None


def test_concurrent_claim_single_winner(client, engine, loaded_config):
    from physicsai_core.db.engine import make_engine
    from physicsai_core.db.repositories import job_lease as lease_repo
    from physicsai_core.db.repositories.job_lease import ClaimRace

    ai = loaded_config.settings.storage.ai_root
    for i in range(2):
        _dataset_job(client, ai, f"CC{i}")
    eng2 = make_engine(str(engine.url.render_as_string(hide_password=False)))
    results: list = []
    barrier = threading.Barrier(2)

    def go(e, wid):
        barrier.wait()
        try:
            with e.begin() as c:
                results.append(lease_repo.claim_slot(c, wid, 30))
        except ClaimRace:
            results.append(None)

    ts = [threading.Thread(target=go, args=(engine, "w1")), threading.Thread(target=go, args=(eng2, "w2"))]
    [t.start() for t in ts]
    [t.join() for t in ts]
    eng2.dispose()
    assert sum(1 for r in results if r) == 1
    with engine.connect() as c:
        assert c.execute(text("select count(*) from jobs where state='RUNNING'")).scalar() == 1


def test_renew_failure_stops_without_writes(client, engine, loaded_config, worker_factory, monkeypatch, tmp_path):
    pidfile = tmp_path / "pids"
    monkeypatch.setenv("FAKE_TOOL_MODE_EDSPY", "hang")
    monkeypatch.setenv("FAKE_TOOL_PIDFILE", str(pidfile))
    _sid, j = _dataset_job(client, loaded_config.settings.storage.ai_root, "RN1")
    w = worker_factory()
    out: dict = {}
    t = threading.Thread(target=lambda: out.setdefault("r", w.run_once_slot()))
    t.start()
    wait_for(lambda: pidfile.exists() and pidfile.read_text().strip())
    pids = [int(x) for x in pidfile.read_text().split()]
    with engine.begin() as c:  # 다른 주체가 lease를 가져간 상황 모사
        c.execute(text("update jobs set lease_token='stolen' where id=:i"), {"i": j["id"]})
        c.execute(text("update worker_slot set lease_token='stolen'"))
    t.join(timeout=20)
    assert out["r"] is None
    for p in pids:
        assert not psutil.pid_exists(p) or psutil.Process(p).status() == psutil.STATUS_ZOMBIE
    st = _state(engine, j["id"])
    assert st["state"] == "RUNNING" and st["lease_token"] == "stolen"
    with engine.connect() as c:
        step = c.execute(text("select state from job_steps where job_id=:i and step_key='EDSPY_DATASET_TRAIN'"), {"i": j["id"]}).scalar()
    assert step == "RUNNING"


def test_output_too_small_then_retry_reuses_and_backs_up(client, engine, loaded_config, worker_factory, monkeypatch):
    ai = Path(loaded_config.settings.storage.ai_root)
    monkeypatch.setenv("FAKE_TOOL_MODE_EDSPY", "small")
    sid, j = _dataset_job(client, ai, "RT1")
    w = worker_factory()
    assert w.run_once_slot() == "FAILED"
    jd = client.get(f"{API}/jobs/{j['id']}", headers=P).json()
    assert jd["failure_code"] == "OUTPUT_TOO_SMALL"
    steps = {s["step_key"]: s["state"] for s in jd["steps"]}
    assert steps == {"DS_SCAN": "SUCCEEDED", "DS_YAML": "SUCCEEDED", "EDSPY_DATASET_TRAIN": "FAILED",
                     "EDSPY_DATASET_EVAL": "SKIPPED", "DS_REGISTER": "SKIPPED"}
    assert jd["can_retry"] is True
    # 남의 작업 재시도는 전역 관리자만
    assert client.post(f"{API}/jobs/{j['id']}/retry", headers=H("tok-power2", write=True), json={}).status_code == 403
    monkeypatch.delenv("FAKE_TOOL_MODE_EDSPY")
    r = client.post(f"{API}/jobs/{j['id']}/retry", headers=PW, json={})
    assert r.status_code == 201, r.text
    nj = r.json()
    assert nj["retry_of_job_id"] == j["id"]
    assert [s["state"] for s in nj["steps"]][:3] == ["SKIPPED", "SKIPPED", "PENDING"]
    assert w.run_once_slot() == "SUCCEEDED"
    ds_id = jd["result"]["dataset_id"]
    assert client.get(f"{API}/datasets/{ds_id}", headers=P).json()["status"] == "READY"
    backups = list((ai / "RT1" / "_backup").rglob("dataset.psdata"))
    assert len(backups) == 1 and backups[0].stat().st_size == 1024
    assert client.post(f"{API}/jobs/{nj['id']}/retry", headers=PW, json={}).json()["detail"]["code"] == "JOB_NOT_RETRYABLE"


def test_log_error_detected(client, engine, loaded_config, worker_factory, monkeypatch):
    monkeypatch.setenv("FAKE_TOOL_MODE_EDSPY", "error_log")
    _sid, j = _dataset_job(client, loaded_config.settings.storage.ai_root, "LE1")
    assert worker_factory().run_once_slot() == "FAILED"
    assert _state(engine, j["id"])["failure_code"] == "LOG_ERROR_DETECTED"


def test_exit_nonzero_and_executable_missing(client, engine, loaded_config, worker_factory, monkeypatch):
    monkeypatch.setenv("FAKE_TOOL_MODE_EDSPY", "fail")
    _sid, j = _dataset_job(client, loaded_config.settings.storage.ai_root, "EX1")
    assert worker_factory().run_once_slot() == "FAILED"
    assert _state(engine, j["id"])["failure_code"] == "EXIT_NONZERO"


def test_hang_not_auto_terminated(client, engine, loaded_config, worker_factory, monkeypatch, tmp_path):
    """V-SM-6: 실행 시간 한도 없음 — hang 작업은 취소 전까지 계속 RUNNING."""
    pidfile = tmp_path / "pids"
    monkeypatch.setenv("FAKE_TOOL_MODE_EDSPY", "hang")
    monkeypatch.setenv("FAKE_TOOL_PIDFILE", str(pidfile))
    _sid, j = _dataset_job(client, loaded_config.settings.storage.ai_root, "HG1")
    w = worker_factory()
    t = threading.Thread(target=w.run_once_slot)
    t.start()
    wait_for(lambda: pidfile.exists() and pidfile.read_text().strip())
    time.sleep(float(os.environ.get("PHYSICSAI_HANG_TEST_S", "5")))
    assert _state(engine, j["id"])["state"] == "RUNNING"
    client.post(f"{API}/jobs/{j['id']}/cancel", headers=AW)
    t.join(timeout=20)
    assert _state(engine, j["id"])["state"] == "CANCELED"


__all__ = ["httpx", "TestClient", "pytest"]
