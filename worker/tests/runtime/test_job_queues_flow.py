"""job-queues.md V-JQ-3~10·12·13: GPU 동시 1·CPU 상한·구간 전환(T17)·순번·크래시 복구·취소·메모리 문.

step 핸들러를 가짜(지연 + 기록)로 바꿔 구간 전환·동시성만 시험한다(queue_support). 실제 DB 락·lease·executor는 그대로.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest
from sqlalchemy import text

from helpers_queue import AW, PW
from physicsai_test_support import API
from queue_support import Pool, Sampler, add_job, job_row, new_study, patch_handlers, wait_all_terminal

PREDICT_KEYS = ["PR_PREP", "TPL_RENDER", "GEOM_UPDATE", "MESH", "RAD_ASSEMBLE", "EDSPY_PREDICT", "CONTOUR_PREVIEW", "CURVE_PICK",
                "RESPONSE_EXTRACT", "RESPONSE_TABLE", "CONTOUR_CAPTURE"]
STEP_EDSPY = PREDICT_KEYS.index("EDSPY_PREDICT") + 1  # 6
STEP_POST = PREDICT_KEYS.index("CONTOUR_PREVIEW") + 1  # 7


@pytest.fixture()
def big_engine(db_url):
    from physicsai_core.db.engine import make_engine

    eng = make_engine(db_url, pool_size=40)
    yield eng
    eng.dispose()


def make_config(settings_dict, *, cpu: int = 4, **worker: Any):
    from physicsai_core.config import load_config_dict

    d = dict(settings_dict)
    d["worker"] = {**d["worker"], "claim_interval_s": 0.05, "lease_ttl_s": 5, **worker,
                   "queues": {"cpu": {"max_concurrent": cpu, "min_free_memory_gb": 0}}}
    lc = load_config_dict(d, environ={})
    assert lc.ok, lc.issues
    return lc


@pytest.fixture()
def mk_worker(big_engine, settings_dict):
    from physicsai_worker.runtime import Worker

    made: list[Any] = []

    def make(cpu: int = 4, **worker: Any) -> Any:
        w = Worker(make_config(settings_dict, cpu=cpu, **worker), big_engine)
        made.append(w)
        return w

    yield make
    for w in made:
        w.stop()


# ---- V-JQ-3 GPU 동시성 ---------------------------------------------------------------------------------


def test_v_jq_3_gpu_never_more_than_one_across_workers_and_threads(big_engine, mk_worker, monkeypatch):
    rec = patch_handlers(monkeypatch, {"EDSPY_PREDICT": 0.2})
    w1, w2 = mk_worker(), mk_worker()  # 같은 DB를 보는 워커 2개(InstanceLock은 __main__에서만 — 우회)
    ids = [add_job(big_engine, "PREDICT", resume_from_step=STEP_EDSPY)["id"] for _ in range(40)]
    assert {job_row(big_engine, i)["lane"] for i in ids} == {"GPU"}
    smp = Sampler(big_engine)
    smp.start()
    pool = Pool()
    for w in (w1, w2):
        pool.spawn(8, w.run_once_gpu, "gpu")  # 워커당 수령 스레드 8개
        pool.spawn(2, w.run_once_cpu, "cpu")  # 추론 뒤 후처리 CPU 구간
    try:
        states = wait_all_terminal(big_engine, ids, timeout=90)
    finally:
        pool.stop()
        smp.stop()
    assert set(states.values()) == {"SUCCEEDED"}
    assert smp.samples > 20
    assert smp.max_gpu == 1 and smp.gpu_mismatch == 0  # RUNNING AND lane='GPU'는 항상 ≤ 1, worker_slot 보유자와 일치
    assert rec.max_active["GPU"] == 1  # 가짜 edspy가 동시에 2개 돈 적 없음
    with big_engine.connect() as c:
        assert c.execute(text("select holder_job_id from worker_slot")).scalar() is None
        assert c.execute(text("select count(*) from jobs where holds_slot")).scalar() == 0


# ---- V-JQ-4 CPU 상한 -----------------------------------------------------------------------------------


def test_v_jq_4_cpu_cap_respected_and_reached(big_engine, mk_worker, monkeypatch):
    rec = patch_handlers(monkeypatch, {"CONTOUR_PREVIEW": 0.3})
    w = mk_worker(cpu=3)
    ids = [add_job(big_engine, "PREDICT", resume_from_step=STEP_POST)["id"] for _ in range(12)]
    assert {job_row(big_engine, i)["lane"] for i in ids} == {"CPU"}
    smp = Sampler(big_engine)
    smp.start()
    pool = Pool()
    pool.spawn(6, w.run_once_cpu, "cpu")  # 상한(3)보다 많은 수령 스레드가 동시에 경쟁
    try:
        states = wait_all_terminal(big_engine, ids, timeout=60)
    finally:
        pool.stop()
        smp.stop()
    assert set(states.values()) == {"SUCCEEDED"}
    assert smp.max_cpu <= 3 and rec.max_active["CPU"] <= 3
    assert smp.max_cpu == 3 and rec.max_active["CPU"] == 3  # 최소 한 번은 상한에 도달


def _race_claims(engine, n_threads: int, limit: int, monkeypatch, *, locked: bool) -> int:
    """대기 CPU 작업이 충분할 때 n_threads개가 동시에 claim_cpu — 성공 수. 질의 사이에 지연을 넣어 경합 창을 넓힌다."""
    from physicsai_core.db.repositories import job_lease as lease_repo

    orig = lease_repo._pick_target

    def slow(conn, lane):
        time.sleep(0.15)
        return orig(conn, lane)

    monkeypatch.setattr(lease_repo, "_pick_target", slow)
    monkeypatch.setattr(lease_repo, "CPU_LOCK_ENABLED", locked)
    barrier = threading.Barrier(n_threads)
    got: list[Any] = []

    def go() -> None:
        barrier.wait()
        try:
            with engine.begin() as c:
                got.append(lease_repo.claim_cpu(c, "w-race", 30, limit))
        except lease_repo.ClaimRace:
            got.append(None)

    ts = [threading.Thread(target=go) for _ in range(n_threads)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    with engine.connect() as c:
        return c.execute(text("select count(*) from jobs where state='RUNNING' and lane='CPU'")).scalar()


def test_v_jq_4_control_without_advisory_lock_overshoots(big_engine, monkeypatch):
    for _ in range(12):
        add_job(big_engine, "PREDICT", resume_from_step=STEP_POST)
    assert _race_claims(big_engine, 6, 3, monkeypatch, locked=False) > 3  # 대조군: 잠금 없이는 상한 초과가 재현된다


def test_v_jq_4_advisory_lock_caps_exactly(big_engine, monkeypatch):
    for _ in range(12):
        add_job(big_engine, "PREDICT", resume_from_step=STEP_POST)
    assert _race_claims(big_engine, 6, 3, monkeypatch, locked=True) == 3


# ---- V-JQ-5 CPU는 GPU를 기다리지 않음 --------------------------------------------------------------------


def test_v_jq_5_cpu_jobs_start_while_gpu_is_busy(big_engine, mk_worker, monkeypatch):
    rec = patch_handlers(monkeypatch, {"EDSPY_PREDICT": 4.0})
    w = mk_worker()
    gpu_ids = [add_job(big_engine, "PREDICT", resume_from_step=STEP_EDSPY)["id"] for _ in range(6)]  # 1건 실행 + 5건 대기
    pool = Pool()
    pool.spawn(1, w.run_once_gpu, "gpu")
    pool.spawn(4, w.run_once_cpu, "cpu")
    try:
        deadline = time.time() + 10
        while time.time() < deadline and not [j for j in gpu_ids if job_row(big_engine, j)["state"] == "RUNNING"]:
            time.sleep(0.02)
        assert [j for j in gpu_ids if job_row(big_engine, j)["state"] == "RUNNING"]
        t0 = time.time()
        doe = add_job(big_engine, "TD_DOE_GEN")["id"]
        ext = add_job(big_engine, "TD_EXTRACT_PARAMS")["id"]
        started: dict[str, float] = {}
        while time.time() - t0 < 3.0 and len(started) < 2:
            for j in (doe, ext):
                if j not in started and job_row(big_engine, j)["started_at"] is not None:
                    started[j] = time.time() - t0
            time.sleep(0.02)
        assert set(started) == {doe, ext}, started
        assert max(started.values()) < 1.0  # claim_interval_s(0.05) 몇 번 안 — GPU 5초 가까이 대기하지 않았다
        # 그 시점에도 GPU 작업은 아직 끝나지 않았고 대기 GPU 작업이 남아 있다
        assert sum(1 for j in gpu_ids if job_row(big_engine, j)["state"] == "QUEUED") >= 4
    finally:
        pool.stop()
    assert rec.max_active["GPU"] == 1


# ---- V-JQ-6 구간 전환 -----------------------------------------------------------------------------------


def test_v_jq_6_segment_transitions_cpu_gpu_cpu(big_engine, mk_worker, monkeypatch):
    rec = patch_handlers(monkeypatch)
    w = mk_worker()
    a = add_job(big_engine, "PREDICT")["id"]
    row0 = job_row(big_engine, a)
    assert row0["lane"] == "CPU" and row0["queue_origin_seq"] == row0["queue_seq"]

    assert w.run_once_cpu() == "QUEUED"  # T17: CPU 구간 끝 → GPU 대기열
    r1 = job_row(big_engine, a)
    assert r1["state"] == "QUEUED" and r1["lane"] == "GPU" and not r1["holds_slot"] and r1["lease_token"] is None
    assert r1["queue_seq"] == row0["queue_origin_seq"] and r1["started_at"] is not None and r1["progress_pct"] > 0
    with big_engine.connect() as c:
        assert c.execute(text("select state from job_steps where job_id=:i and step_key='EDSPY_PREDICT'"), {"i": a}).scalar() == "PENDING"
        assert c.execute(text("select holder_job_id from worker_slot")).scalar() is None
    # 다음 GPU 작업(뒤에 등록)이 대기 중이어도 재진입 작업이 원래 순번으로 앞선다
    b = add_job(big_engine, "EVALUATE")["id"]
    assert job_row(big_engine, b)["lane"] == "GPU" and job_row(big_engine, b)["queue_seq"] > r1["queue_seq"]

    assert w.run_once_gpu() == "QUEUED"  # T17: 추론 끝 → CPU 대기열(후처리)
    r2 = job_row(big_engine, a)
    assert r2["state"] == "QUEUED" and r2["lane"] == "CPU" and not r2["holds_slot"] and r2["lease_token"] is None
    from physicsai_core.db.repositories import job_lease as lease_repo

    with big_engine.begin() as c:  # EDSPY 종료 직후 슬롯이 비어 다음 GPU 작업을 즉시 수령
        nxt = lease_repo.claim_gpu(c, "other-worker", 30)
    assert nxt is not None and nxt["id"] == b
    with big_engine.begin() as c:
        lease_repo.release(c, b, nxt["lease_token"], "SUCCEEDED")

    assert w.run_once_cpu() == "SUCCEEDED"
    fin = job_row(big_engine, a)
    assert fin["state"] == "SUCCEEDED" and fin["progress_pct"] == 100 and fin["lease_token"] is None and not fin["holds_slot"]
    assert rec.lanes(a) == ["CPU", "GPU", "CPU"]
    with big_engine.connect() as c:
        steps = c.execute(text("select step_key, state from job_steps where job_id=:i order by step_no"), {"i": a}).all()
        started = c.execute(text("select count(*) from notifications where event='JOB_STARTED' and job_id=:i"), {"i": a}).scalar()
    assert [s for s, _ in steps] == PREDICT_KEYS and {st for _, st in steps} == {"SUCCEEDED"}
    assert started == 1  # JQ-14: T17 재진입은 JOB_STARTED 없음
    order = [(t, k) for t, j, k, ph, _l in rec.events if j == a and ph == "start"]
    assert [k for _t, k in order] == PREDICT_KEYS  # step 실행 순서는 전환 없는 실행과 같다


def test_v_jq_6_run_once_slot_follows_the_job_to_the_end(big_engine, mk_worker, monkeypatch):
    rec = patch_handlers(monkeypatch)
    w = mk_worker()
    a = add_job(big_engine, "PREDICT")["id"]
    assert w.run_once_slot() == "SUCCEEDED"  # 시험·개발용 구동기는 전환마다 이어서 수령
    assert rec.lanes(a) == ["CPU", "GPU", "CPU"]


def test_v_jq_6_prepared_predict_skips_without_transition_and_light_never_switches(big_engine, mk_worker, monkeypatch):
    rec = patch_handlers(monkeypatch)
    w = mk_worker()
    # prepared 입력 PREDICT를 GPU 대기열에서 시작시켜도(재개 등) GEOM_UPDATE·MESH는 건너뛰기 대상이라 전환하지 않는다
    a = add_job(big_engine, "PREDICT", params={"input_mode": "prepared"})["id"]
    with big_engine.begin() as c:
        c.execute(text("update jobs set lane='GPU' where id=:i"), {"i": a})
    assert w.run_once_gpu() == "QUEUED"
    assert [k for _t, j, k, ph, _l in rec.events if j == a and ph == "start"][:4] == ["PR_PREP", "TPL_RENDER", "GEOM_UPDATE", "MESH"]
    assert rec.lanes(a) == ["GPU"]  # GEOM_UPDATE·MESH(건너뛰기 대상)에서 전환 없이 추론까지 GPU 슬롯, 그다음 CPU로
    assert job_row(big_engine, a)["lane"] == "CPU"
    # LIGHT 레인은 구간 전환이 없다
    study = new_study(big_engine)
    from physicsai_core.db.repositories import jobs as jobs_repo
    from physicsai_core.db.repositories import studies as studies_repo

    with big_engine.begin() as c:
        job = jobs_repo.insert_job(c, study=studies_repo.require(c, study), job_type="PACKAGE_EXPORT", params={}, user_id="u", user_name="u")
    assert job["lane"] == "LIGHT" and w.run_once_light() == "SUCCEEDED"


# ---- V-JQ-7 슬롯 ≤ 1·교착 없음 ---------------------------------------------------------------------------


def test_v_jq_7_no_deadlock_with_single_cpu_slot(big_engine, mk_worker, monkeypatch):
    rec = patch_handlers(monkeypatch, {"EDSPY_PREDICT": 0.15, "EDSPY_SCORE": 0.15, "CONTOUR_PREVIEW": 0.1, "HST_GEN_RADIOSS": 0.1})
    w = mk_worker(cpu=1)
    ids = [add_job(big_engine, "PREDICT")["id"] for _ in range(4)]
    ids.append(add_job(big_engine, "TD_DOE_GEN")["id"])
    ids.append(add_job(big_engine, "EVALUATE")["id"])
    smp = Sampler(big_engine)
    smp.start()
    pool = Pool()
    pool.spawn(1, w.run_once_gpu, "gpu")
    pool.spawn(1, w.run_once_cpu, "cpu")
    double: list[str] = []

    def watch() -> None:
        while not pool.stop_evt.is_set():
            with w._exec_lock:
                held = list(w.executors)
            if len(held) != len(set(held)):
                double.append("dup")
            with big_engine.connect() as c:  # 한 작업이 GPU 슬롯과 CPU 슬롯을 함께 쥔 적 없음(행 1개 = 레인 1개)
                n = c.execute(text("select count(*) from (select id from jobs where state='RUNNING' and lane in ('CPU','GPU')"
                                   " group by id having count(distinct lane) > 1) x")).scalar()
            if n:
                double.append("two-lanes")
            time.sleep(0.01)

    wt = threading.Thread(target=watch, daemon=True)
    wt.start()
    try:
        states = wait_all_terminal(big_engine, ids, timeout=60)  # 교착이면 제한 시간 안에 안 끝난다
    finally:
        pool.stop()
        smp.stop()
        wt.join(timeout=5)
    assert set(states.values()) == {"SUCCEEDED"}, states
    assert smp.max_cpu <= 1 and smp.max_gpu <= 1 and not double
    # PREDICT는 CPU → GPU → CPU, EVALUATE는 GPU 한 구간
    assert all(rec.lanes(i) == ["CPU", "GPU", "CPU"] for i in ids[:4])
    assert rec.lanes(ids[5]) == ["GPU"] and rec.lanes(ids[4]) == ["CPU"]


# ---- V-JQ-8 순번 -----------------------------------------------------------------------------------------


def test_v_jq_8_reentry_keeps_original_place_and_t14_goes_last(big_engine, mk_worker, monkeypatch, client):
    patch_handlers(monkeypatch)
    w = mk_worker()
    a = add_job(big_engine, "PREDICT")["id"]  # 먼저 등록
    b = add_job(big_engine, "EVALUATE")["id"]  # 나중에 GPU 대기열에 등록
    assert w.run_once_cpu() == "QUEUED"  # a: CPU 구간 → GPU 대기열 재진입
    with big_engine.connect() as c:
        order = [r[0] for r in c.execute(text("select id from jobs where state='QUEUED' and lane='GPU' order by queue_seq"))]
    assert order == [a, b]  # 재진입 작업이 뒤에 등록된 작업보다 앞
    # T14(PBS 회수 후)는 맨 뒤 — 회귀
    from physicsai_core.db.repositories import job_lease as lease_repo

    x = add_job(big_engine, "TD_SOLVE")["id"]
    z = add_job(big_engine, "TD_DOE_GEN")["id"]  # x보다 나중에 등록
    with big_engine.begin() as c:
        jx = lease_repo.claim_cpu(c, "w", 30, 4)
    assert jx["id"] == x
    with big_engine.begin() as c:
        c.execute(text("update job_steps set state='SUCCEEDED' where job_id=:i and step_key in ('TS_PREP','HPC_SUBMIT')"), {"i": x})
        lease_repo.release(c, x, jx["lease_token"], "WAITING_HPC")
        c.execute(text("update jobs set state='COLLECTING' where id=:i"), {"i": x})
        c.execute(text("update job_steps set state='SUCCEEDED' where job_id=:i and step_key in ('HPC_WAIT','COLLECT')"), {"i": x})
        col = lease_repo.claim_collecting(c, "w", 30)
        lease_repo.release(c, x, col["lease_token"], "QUEUED", next_lane="CPU")
    with big_engine.connect() as c:
        rows = {r[0]: r for r in c.execute(text("select id, queue_seq, queue_origin_seq, lane from jobs where id in (:x,:z)"), {"x": x, "z": z})}
    assert rows[x][1] > rows[z][1] and rows[x][1] == rows[x][2] and rows[x][3] == "CPU"


def test_v_jq_8_move_within_queue_keeps_order_on_reentry_and_rejects_others(big_engine, client, monkeypatch):
    g = [add_job(big_engine, "EVALUATE")["id"] for _ in range(3)]  # GPU 대기열
    c1 = add_job(big_engine, "TD_DOE_GEN")["id"]  # CPU 대기열
    light_study = new_study(big_engine)
    from physicsai_core.db.repositories import jobs as jobs_repo
    from physicsai_core.db.repositories import studies as studies_repo

    with big_engine.begin() as c:
        light = jobs_repo.insert_job(c, study=studies_repo.require(c, light_study), job_type="PACKAGE_EXPORT", params={},
                                     user_id="u", user_name="u")["id"]
    # 같은 대기열 안 이동: GPU 3번 → 1번. CPU 대기열은 그대로
    r = client.post(f"{API}/queue/{g[2]}/move", headers=AW, json={"position": 1})
    assert r.status_code == 200
    body = r.json()
    assert [x["id"] for x in body["gpu"]["queued"]] == [g[2], g[0], g[1]] and [x["queue_position"] for x in body["gpu"]["queued"]] == [1, 2, 3]
    assert [x["id"] for x in body["cpu"]["queued"]] == [c1]
    with big_engine.connect() as c:
        rows = c.execute(text("select queue_seq, queue_origin_seq from jobs where lane='GPU' and state='QUEUED'")).all()
    assert all(a == b for a, b in rows)  # 이후 T17 재진입에도 바뀐 순서 유지
    # LIGHT·실행 중은 409 JOB_NOT_QUEUED
    for jid in (light,):
        r = client.post(f"{API}/queue/{jid}/move", headers=AW, json={"position": 1})
        assert r.status_code == 409 and r.json()["detail"]["code"] == "JOB_NOT_QUEUED"
    from physicsai_core.db.repositories import job_lease as lease_repo

    with big_engine.begin() as c:
        run = lease_repo.claim_gpu(c, "w", 30)
    assert run["id"] == g[2]
    r = client.post(f"{API}/queue/{g[2]}/move", headers=AW, json={"position": 1})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "JOB_NOT_QUEUED"
    assert "GPU·CPU" in r.json()["detail"]["message"] if isinstance(r.json()["detail"], dict) and "message" in r.json()["detail"] else True
    assert client.post(f"{API}/queue/{g[0]}/move", headers=PW, json={"position": 1}).status_code == 403


# ---- V-JQ-10 크래시 복구 ---------------------------------------------------------------------------------


def _lease_config(settings_dict, **kw):
    return make_config(settings_dict, lease_ttl_s=1.0, heartbeat_interval_s=0.3, **kw)


def test_v_jq_10_gpu_segment_worker_death(big_engine, settings_dict, monkeypatch):
    from physicsai_worker import housekeeping
    from physicsai_worker.runtime import Worker

    patch_handlers(monkeypatch)
    lc = _lease_config(settings_dict)
    a = add_job(big_engine, "EVALUATE")["id"]
    b = add_job(big_engine, "EVALUATE")["id"]
    dead = Worker(lc, big_engine)
    claimed = dead.claim_only()
    assert claimed["id"] == a and claimed["lane"] == "GPU" and claimed["holds_slot"]
    time.sleep(1.4)
    assert housekeeping.reap(big_engine) == [a]
    ra = job_row(big_engine, a)
    assert ra["state"] == "INTERRUPTED" and ra["failure_code"] == "WORKER_LOST" and ra["lease_token"] is None
    with big_engine.connect() as c:
        assert c.execute(text("select holder_job_id from worker_slot")).scalar() is None
    alive = Worker(lc, big_engine)
    assert alive.run_once_gpu() == "SUCCEEDED" and job_row(big_engine, b)["state"] == "SUCCEEDED"


def test_v_jq_10_cpu_segment_worker_death_restores_count(big_engine, settings_dict, monkeypatch):
    from physicsai_worker import housekeeping
    from physicsai_worker.runtime import Worker

    patch_handlers(monkeypatch)
    lc = _lease_config(settings_dict, cpu=1)
    a = add_job(big_engine, "TD_DOE_GEN")["id"]
    b = add_job(big_engine, "TD_DOE_GEN")["id"]
    dead = Worker(lc, big_engine)
    assert dead.claim_only()["id"] == a
    alive = Worker(lc, big_engine)
    assert alive.run_once_cpu() is None  # 상한 1 — a가 쥐고 있는 동안 b는 대기
    time.sleep(1.4)
    housekeeping.reap(big_engine)
    assert job_row(big_engine, a)["state"] == "INTERRUPTED"  # RUNNING 행 수가 줄어 자동 회복
    assert alive.run_once_cpu() == "SUCCEEDED" and job_row(big_engine, b)["state"] == "SUCCEEDED"


def test_v_jq_10_death_right_after_t17_resumes_after_restart(big_engine, settings_dict, monkeypatch):
    from physicsai_worker.runtime import Worker

    rec = patch_handlers(monkeypatch)
    lc = _lease_config(settings_dict)
    a = add_job(big_engine, "PREDICT")["id"]
    first = Worker(lc, big_engine)
    assert first.run_once_cpu() == "QUEUED"
    first.stop()  # 워커 사망 모사: T17 직후 — 작업은 GPU 대기열에 영속
    r = job_row(big_engine, a)
    assert r["state"] == "QUEUED" and r["lane"] == "GPU"
    second = Worker(lc, big_engine)  # 재시작
    assert second.run_once_slot() == "SUCCEEDED"
    assert rec.lanes(a) == ["CPU", "GPU", "CPU"]


# ---- V-JQ-12 재진입 대기 중 취소·알림 1회 -----------------------------------------------------------------


def test_v_jq_12_cancel_while_waiting_between_segments(big_engine, mk_worker, monkeypatch, client):
    patch_handlers(monkeypatch)
    w = mk_worker()
    a = add_job(big_engine, "PREDICT")["id"]
    other = add_job(big_engine, "EVALUATE")["id"]  # GPU 대기열 앞/뒤 알림 경쟁
    assert w.run_once_cpu() == "QUEUED"
    assert job_row(big_engine, a)["lane"] == "GPU"
    r = client.post(f"{API}/jobs/{a}/cancel", headers=AW)
    assert r.status_code == 202 and r.json()["state"] == "CANCELED"
    with big_engine.connect() as c:
        steps = dict(c.execute(text("select step_key, state from job_steps where job_id=:i"), {"i": a}).all())
        ev = [e for (e,) in c.execute(text("select event from notifications where job_id=:i"), {"i": a})]
    assert steps["EDSPY_PREDICT"] == "CANCELED" and steps["CONTOUR_CAPTURE"] == "CANCELED" and steps["PR_PREP"] == "SUCCEEDED"
    assert ev.count("JOB_STARTED") == 1 and ev.count("JOB_CANCELED") == 1 and ev.count("MY_TURN_NEXT") <= 1
    assert job_row(big_engine, other)["state"] == "QUEUED"


def test_v_jq_12_notifications_once_per_job_across_segments(big_engine, mk_worker, monkeypatch):
    patch_handlers(monkeypatch)
    w = mk_worker()
    jobs = [add_job(big_engine, "PREDICT")["id"] for _ in range(3)]
    for _ in range(40):
        if w.run_once_slot() is None:
            break
    with big_engine.connect() as c:
        for j in jobs:
            ev = [e for (e,) in c.execute(text("select event from notifications where job_id=:i"), {"i": j})]
            assert ev.count("JOB_STARTED") == 1 and ev.count("MY_TURN_NEXT") <= 1 and ev.count("JOB_SUCCEEDED") == 1, (j, ev)


def test_v_jq_12_my_turn_next_for_gpu_and_cpu_when_full(big_engine, mk_worker, monkeypatch):
    patch_handlers(monkeypatch)
    w = mk_worker(cpu=1)
    w.heartbeat_once(with_resources=False)  # 알림 저장소는 하트비트의 유효 CPU 상한(1)을 읽는다
    g1, g2 = add_job(big_engine, "EVALUATE")["id"], add_job(big_engine, "EVALUATE")["id"]
    c1, c2 = add_job(big_engine, "TD_DOE_GEN")["id"], add_job(big_engine, "TD_DOE_GEN")["id"]
    assert w.claim_only()["id"] in (g1, c1)
    assert w.claim_only()["id"] in (g1, c1)
    with big_engine.connect() as c:
        notified = {j for (j,) in c.execute(text("select job_id from notifications where event='MY_TURN_NEXT'"))}
    assert notified == {g2, c2}  # GPU 보유 중·CPU 상한 도달 — 각 대기열 1번에 1회


# ---- V-JQ-13 메모리 문 ----------------------------------------------------------------------------------


def test_v_jq_13_memory_gate_blocks_cpu_not_gpu_and_shows_in_queue(big_engine, settings_dict, client, db_url, monkeypatch):
    from physicsai_core.config import load_config_dict
    from physicsai_worker.runtime import Worker

    patch_handlers(monkeypatch)
    d = dict(settings_dict)
    d["worker"] = {**d["worker"], "queues": {"cpu": {"max_concurrent": 2, "min_free_memory_gb": 4}}}
    w = Worker(load_config_dict(d, environ={}), big_engine)
    w.available_memory_gb = lambda: 1.0  # 가짜 여유 메모리 < min_free_memory_gb
    cpu = add_job(big_engine, "TD_DOE_GEN")["id"]
    gpu = add_job(big_engine, "EVALUATE")["id"]
    assert w.run_once_cpu() is None and job_row(big_engine, cpu)["state"] == "QUEUED"
    assert w.run_once_gpu() == "SUCCEEDED"  # GPU 수령에는 적용 안 함
    w.heartbeat_once(with_resources=False)
    q = client.get(f"{API}/queue", headers=PW).json()
    assert q["cpu"]["memory_gate"] == "low" and q["cpu"]["min_free_memory_gb"] == 8 and q["cpu"]["limit"] == 4  # 한도 값은 API 설정에서
    w.available_memory_gb = lambda: 64.0
    assert w.run_once_cpu() == "SUCCEEDED"
    w.heartbeat_once(with_resources=False)
    assert client.get(f"{API}/queue", headers=PW).json()["cpu"]["memory_gate"] == "ok"
    assert job_row(big_engine, gpu)["state"] == "SUCCEEDED"


# ---- 설정 변경·스레드·회계 --------------------------------------------------------------------------------


def test_cpu_threads_follow_setting_and_stop_pauses_all_keepers(big_engine, mk_worker, monkeypatch):
    w = mk_worker(cpu=3)
    w.start()
    try:
        names = sorted(t.name for t in w._threads)
        assert "gpu-slot" in names and [n for n in names if n.startswith("cpu-slot")] == ["cpu-slot0", "cpu-slot1", "cpu-slot2"]
        assert "slot" not in names
        # 상한이 커지면 스레드를 더 띄우고, 작아져도 줄이지 않는다(수령 문이 걸러냄)
        w.settings.worker.queues.cpu.max_concurrent = 5
        w._ensure_cpu_threads()
        assert len([t for t in w._threads if t.name.startswith("cpu-slot")]) == 5
        w.settings.worker.queues.cpu.max_concurrent = 2
        w._ensure_cpu_threads()
        assert len([t for t in w._threads if t.name.startswith("cpu-slot")]) == 5
    finally:
        w.stop()


def test_job_limits_share_vs_nested(mk_worker):
    w = mk_worker(cpu=3)
    assert w.cap_mode == "share" and w.job_limits().memory_gb == pytest.approx(w.limits.memory_gb / 4, abs=0.01)  # POSIX: 작업당 몫(CPU 3 + GPU 1)
    assert w.job_limits().cores == max(1, w.limits.cores // 4)
    w.cap_mode = "nested"
    assert w.job_limits() == w.limits  # 부모 Job이 합계를 막으므로 작업은 전체 한도


# ---- 부모 Job Object(JQ-7, V-JQ-16 현장 전 Linux 단위 시험) ----------------------------------------------


class _Kernel:
    def __init__(self, assign_ok=True, raise_on_create=False):
        self.calls: list[Any] = []
        self.assign_ok, self.raise_on_create = assign_ok, raise_on_create

    def CreateJobObjectW(self, *_):
        if self.raise_on_create:
            raise OSError("정책으로 거부")
        self.calls.append("Create")
        return 777

    def SetInformationJobObject(self, *_):
        return 1

    def GetCurrentProcess(self):
        self.calls.append("Self")
        return -1

    def AssignProcessToJobObject(self, job, handle):
        self.calls.append(("Assign", job, handle))
        return 1 if self.assign_ok else 0

    def CloseHandle(self, h):
        self.calls.append(("Close", h))
        return 1


def test_parent_job_nested_share_fallback_and_posix_null():
    from physicsai_core.limits import compute_limits
    from physicsai_worker.limiter.null import NullLimiter
    from physicsai_worker.limiter.posix import PosixLimiter
    from physicsai_worker.limiter.windows_job import WindowsJobLimiter

    lim = compute_limits(32, 64, "below_normal", False, 0.7, 64, 128)
    k = _Kernel()
    w = WindowsJobLimiter(kernel32=k)
    assert w.attach_parent(lim) == "nested" and ("Assign", 777, -1) in k.calls and w.parent_job == 777
    assert w.attach_parent(lim) == "nested" and k.calls.count("Create") == 1  # 두 번째 호출은 새 Job을 만들지 않는다
    k2 = _Kernel(assign_ok=False)
    w2 = WindowsJobLimiter(kernel32=k2)
    assert w2.attach_parent(lim) == "share" and ("Close", 777) in k2.calls and w2.parent_job is None  # 거부 → 작업당 몫 폴백
    w3 = WindowsJobLimiter(kernel32=_Kernel(raise_on_create=True))
    assert w3.attach_parent(lim) == "share"
    assert PosixLimiter().attach_parent(lim) == "share" and NullLimiter().attach_parent(lim) == "off"


def test_share_limits_formula():
    from physicsai_core.limits import compute_limits, share_limits

    lim = compute_limits(32, 64, "below_normal", False, 0.7, 64, 128)  # 코어 32·메모리 64
    s = share_limits(lim, 5)  # CPU 4 + GPU 1
    assert s.cores == 6 and s.memory_gb == pytest.approx(12.8) and s.cpu_rate == int(6 / 64 * 10000)
    tiny = share_limits(compute_limits(2, 4, "below_normal", False, 0.7, 8, 16), 17)
    assert tiny.cores == 1 and tiny.cpu_rate >= 100


def test_worker_total_cap_modes_and_env_check_item(mk_worker, settings_dict, big_engine):
    from physicsai_core.config import load_config_dict
    from physicsai_worker import env_check
    from physicsai_worker.runtime import Worker

    w = mk_worker()
    it = env_check._job_nesting_item(w)
    assert it["key"] == "worker.job_nesting" and it["status"] == "SKIP" and it["detail"]["total_cap"] == "share"  # Linux
    d = dict(settings_dict)
    d["worker"] = {**d["worker"], "queues": {"total_cap": False}}
    w2 = Worker(load_config_dict(d, environ={}), big_engine)
    assert w2.cap_mode == "share"
    d["worker"] = {**d["worker"], "limiter": "null"}
    w3 = Worker(load_config_dict(d, environ={}), big_engine)
    assert w3.cap_mode == "off" and w3.job_limits() == w3.limits
    # Windows 가정: 중첩 실패는 WARN, 성공은 OK
    w.cap_mode = "share"
    monkey = pytest.MonkeyPatch()
    try:
        monkey.setattr(env_check, "_is_windows", lambda: True)
        assert env_check._job_nesting_item(w)["status"] == "WARN"
        w.cap_mode = "nested"
        assert env_check._job_nesting_item(w)["status"] == "OK"
    finally:
        monkey.undo()
