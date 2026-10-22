"""lease(V-LS-1~3): 만료 → INTERRUPTED, 리퍼, 동시 claim 단일 승자, 갱신 실패 시 쓰기 없이 중단."""

from __future__ import annotations

import threading
import time

import psutil
from sqlalchemy import text

from helpers_queue import _dataset_job, _state, _to_lane
from physicsai_test_support import wait_for


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
    _to_lane(engine, j["id"], "GPU")  # GPU 슬롯(worker_slot) 회수 시험 — CPU 구간은 슬롯 행이 없다
    _to_lane(engine, j2["id"], "GPU")
    dead = Worker(lc, engine)
    assert dead.claim_only()["id"] == j["id"]
    time.sleep(1.3)
    # 다른 워커의 claim이 만료 슬롯을 회수하고 다음 작업을 잡는다
    other = Worker(lc, engine)
    with engine.begin() as c:
        from physicsai_core.db.repositories import job_lease as lease_repo

        nxt = lease_repo.claim_gpu(c, other.worker_id, 30)
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
    _to_lane(engine, j["id"], "GPU")
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
        _to_lane(engine, _dataset_job(client, ai, f"CC{i}")[1]["id"], "GPU")
    eng2 = make_engine(str(engine.url.render_as_string(hide_password=False)))
    results: list = []
    barrier = threading.Barrier(2)

    def go(e, wid):
        barrier.wait()
        try:
            with e.begin() as c:
                results.append(lease_repo.claim_gpu(c, wid, 30))
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
    t.join(timeout=20)
    assert out["r"] is None
    for p in pids:
        assert not psutil.pid_exists(p) or psutil.Process(p).status() == psutil.STATUS_ZOMBIE
    st = _state(engine, j["id"])
    assert st["state"] == "RUNNING" and st["lease_token"] == "stolen"
    with engine.connect() as c:
        step = c.execute(text("select state from job_steps where job_id=:i and step_key='EDSPY_DATASET_TRAIN'"), {"i": j["id"]}).scalar()
    assert step == "RUNNING"
