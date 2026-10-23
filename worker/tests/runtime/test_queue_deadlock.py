"""job-queues.md V-JQ-17: GPU 수령과 CPU 수령을 병렬로 반복해도 교착(40P01)이 없다(운영 경로 — advisory lock 우회 없음).

원인: `notifications.recompute_my_turn`이 수령 때마다 두 대기열 1번 작업 행을 갱신한다. GPU 수령(슬롯 행 잠금)과 CPU 수령(advisory lock)은
서로 직렬화되지 않아, 각자 쥔 수령 대상 행과 상대가 갱신하려는 앞 순번 행의 잠금 순서가 엇갈릴 수 있다.
수정: 갱신 대상을 id 오름차순 한 문장으로 `FOR UPDATE SKIP LOCKED` 잠근다(이미 다른 트랜잭션이 바꾸는 중인 행은 그 트랜잭션이 다시 계산한다 —
기다리지 않으므로 순환 대기가 없다). 그래도 40P01이면 수령 트랜잭션을 다시 시도한다(최대 3회).
측정: 서버 카운터 `pg_stat_database.deadlocks`의 증가량(재시도로 가려진 교착도 센다)과 수령 스레드 예외.
"""

from __future__ import annotations

import time
from typing import Any

import pytest
from sqlalchemy import text

from physicsai_test_support import API  # noqa: F401 - 시험 환경 fixture 로드 관례
from queue_support import Pool, add_job, patch_handlers, wait_all_terminal

N_GPU, N_CPU = 40, 40
STEP_EDSPY = 6  # PREDICT 6번째 step = EDSPY_PREDICT(GPU)
STEP_POST = 7  # CONTOUR_PREVIEW(CPU)


@pytest.fixture()
def big_engine(db_url):
    from physicsai_core.db.engine import make_engine

    eng = make_engine(db_url, pool_size=40)
    yield eng
    eng.dispose()


def _deadlocks(engine: Any) -> int:
    with engine.connect() as c:
        c.execute(text("select pg_stat_clear_snapshot()"))
        return int(c.execute(text("select deadlocks from pg_stat_database where datname = current_database()")).scalar() or 0)


def _workers(big_engine, settings_dict, n: int = 2) -> list[Any]:
    from physicsai_core.config import load_config_dict
    from physicsai_worker.runtime import Worker

    d = dict(settings_dict)
    d["worker"] = {**d["worker"], "claim_interval_s": 0.05, "lease_ttl_s": 5,
                   "queues": {"cpu": {"max_concurrent": 2, "min_free_memory_gb": 0}}}
    lc = load_config_dict(d, environ={})
    assert lc.ok, lc.issues
    return [Worker(lc, big_engine) for _ in range(n)]


def test_v_jq_17_parallel_gpu_and_cpu_claims_have_no_deadlock(big_engine, settings_dict, monkeypatch):
    patch_handlers(monkeypatch, {"EDSPY_PREDICT": 0.02, "CONTOUR_PREVIEW": 0.02})
    from physicsai_core.db.repositories import job_lease as lease_repo

    orig_pick = lease_repo._pick_target

    def slow_pick(conn, lane):  # 수령 대상 행을 잠근 뒤 알림 갱신까지의 창을 넓힌다(경합 확률을 올릴 뿐 운영 규칙은 그대로)
        r = orig_pick(conn, lane)
        time.sleep(0.01)
        return r

    monkeypatch.setattr(lease_repo, "_pick_target", slow_pick)
    ws = _workers(big_engine, settings_dict)
    gpu_ids = [add_job(big_engine, "PREDICT", resume_from_step=STEP_EDSPY)["id"] for _ in range(N_GPU)]
    cpu_ids = [add_job(big_engine, "PREDICT", resume_from_step=STEP_POST)["id"] for _ in range(N_CPU)]
    before = _deadlocks(big_engine)
    pool = Pool()
    for w in ws:
        pool.spawn(4, w.run_once_gpu, "gpu")
        pool.spawn(4, w.run_once_cpu, "cpu")
    try:
        states = wait_all_terminal(big_engine, gpu_ids + cpu_ids, timeout=120)
    finally:
        pool.stop()
        for w in ws:
            w.stop()
    time.sleep(1.5)  # 서버 통계 반영
    assert set(states.values()) == {"SUCCEEDED"}
    assert _deadlocks(big_engine) - before == 0  # 서버가 교착을 감지한 적 없음(재시도로 가려진 것 포함)
    assert not pool.errors


def test_v_jq_17_overlapping_claims_without_serialization_have_no_deadlock(big_engine, monkeypatch):
    """직렬화가 없는 겹침(CPU advisory lock 우회 — 수정 전에는 서로의 앞 순번 행을 기다리며 40P01이 재현되던 경로)에서도
    알림 갱신이 기다리지 않으므로 교착이 없다. 상한 초과는 이 우회 경로의 알려진 성질이라 여기서 판정하지 않는다
    (알림 자체의 정확성은 test_job_queues_flow·test_queue_lease의 MY_TURN_NEXT 시험이 본다)."""
    import threading

    from physicsai_core.db.repositories import job_lease as lease_repo

    for _ in range(12):
        add_job(big_engine, "PREDICT", resume_from_step=STEP_POST)
    with big_engine.begin() as c:  # CPU 2건이 이미 실행 중 — 겹친 수령이 각자 "가득"으로 보는 조건
        for (i,) in c.execute(text("select id from jobs where state='QUEUED' and lane='CPU' order by queue_seq limit 2")).all():
            c.execute(text("update jobs set state='RUNNING', queue_seq=NULL, started_at=now(), next_notified_at=now() where id=:i"), {"i": i})
    orig = lease_repo._pick_target

    def slow(conn, lane):
        r = orig(conn, lane)
        time.sleep(0.15)
        return r

    monkeypatch.setattr(lease_repo, "_pick_target", slow)
    monkeypatch.setattr(lease_repo, "CPU_LOCK_ENABLED", False)
    before = _deadlocks(big_engine)
    barrier = threading.Barrier(4)
    errs: list[BaseException] = []

    def go() -> None:
        barrier.wait()
        try:
            with big_engine.begin() as c:
                lease_repo.claim_cpu(c, "w-overlap", 30, 6)
        except lease_repo.ClaimRace:
            pass
        except BaseException as exc:  # noqa: BLE001
            errs.append(exc)

    ts = [threading.Thread(target=go) for _ in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    time.sleep(1.5)
    assert not errs, errs
    assert _deadlocks(big_engine) - before == 0


def _deadlock_error() -> BaseException:
    import psycopg.errors
    from sqlalchemy.exc import OperationalError

    return OperationalError("update jobs", {}, psycopg.errors.DeadlockDetected("deadlock detected"))


def test_claim_retries_deadlock_up_to_three_times(big_engine, settings_dict, monkeypatch):
    from physicsai_core.db.retry import DEADLOCK_RETRIES

    (w,) = _workers(big_engine, settings_dict, 1)
    monkeypatch.setattr("physicsai_core.db.retry.time.sleep", lambda _s: None)
    calls: list[int] = []

    def flaky(n_fail: int):
        def fn(_conn: Any) -> dict[str, Any]:
            calls.append(1)
            if len(calls) <= n_fail:
                raise _deadlock_error()
            return {"id": "J-ok"}

        return fn

    assert DEADLOCK_RETRIES == 3
    assert w._claim(flaky(3)) == {"id": "J-ok"} and len(calls) == 4  # 교착 3번 뒤 4번째에 성공 — 수령 결과 동일
    calls.clear()
    with pytest.raises(Exception) as ei:  # 4번 연속이면 포기(예외 그대로)
        w._claim(flaky(4))
    assert len(calls) == 4
    from physicsai_core.db.retry import is_deadlock

    assert is_deadlock(ei.value)
    calls.clear()

    def other(_conn: Any) -> None:
        calls.append(1)
        raise RuntimeError("교착 아님")

    with pytest.raises(RuntimeError):
        w._claim(other)
    assert len(calls) == 1  # 다른 오류는 재시도 안 함
    w.stop()


# ---- v0.2.10 C3F-18 / V-C3F-16: 잠금 순서 통일(worker_slot을 쥔 채 jobs 행을 기다리지 않는다) ---------------------------------------

def _gpu_holder_expired(engine: Any) -> tuple[dict[str, Any], str]:
    """GPU 슬롯을 쥔 RUNNING 작업 J(lease 방금 만료) + 대기 중 GPU 작업 K. 반환 = (J 행, K id)."""
    from physicsai_core.db.repositories import job_lease as lease_repo

    j = add_job(engine, "PREDICT", resume_from_step=STEP_EDSPY)
    k = add_job(engine, "PREDICT", resume_from_step=STEP_EDSPY)
    with engine.begin() as c:
        row = lease_repo.claim_gpu(c, "w-hold", 30)
    assert row is not None and row["id"] == j["id"] and row["holds_slot"] is True
    with engine.begin() as c:
        c.execute(text("update worker_slot set lease_acquired_at = now() - interval '10 second', lease_expires_at = now() - interval '1 second'"
                       " where id = 1"))
        c.execute(text("update jobs set lease_acquired_at = now() - interval '10 second', lease_expires_at = now() - interval '1 second'"
                       " where id = :i"), {"i": j["id"]})
    return row, k["id"]


def test_v_c3f_16_claim_gpu_skips_when_holder_row_locked_by_release(big_engine):
    """release가 holder 작업 행을 잠근 동안 만료 슬롯의 claim_gpu는 기다리지 않고 None(슬롯은 그대로) — 40P01·대기 0.
    release가 커밋된 뒤에는 수령에 성공한다."""
    import threading

    from physicsai_core.db.repositories import job_lease as lease_repo

    before = _deadlocks(big_engine)
    jrow, kid = _gpu_holder_expired(big_engine)
    token = jrow["lease_token"]
    locked, go, done = threading.Event(), threading.Event(), threading.Event()
    errs: list[BaseException] = []

    def releaser() -> None:
        try:
            with big_engine.begin() as c:
                lease_repo.assert_lease(c, jrow["id"], token)  # release의 첫 단계 — jobs 행 FOR UPDATE
                locked.set()
                assert go.wait(20)
                lease_repo.release(c, jrow["id"], token, "SUCCEEDED")  # 같은 트랜잭션에서 이어서 해제(슬롯 UPDATE는 마지막)
        except BaseException as exc:  # noqa: BLE001
            errs.append(exc)
        finally:
            done.set()

    t = threading.Thread(target=releaser)
    t.start()
    assert locked.wait(20)
    t0 = time.monotonic()
    with big_engine.begin() as c:
        c.execute(text("set local lock_timeout = '5s'"))  # 기다리면 이 시간 뒤 오류(수정 전 동작) — 수정 후에는 즉시 None
        got = lease_repo.claim_gpu(c, "w-new", 30)
    assert got is None and time.monotonic() - t0 < 2.0
    with big_engine.connect() as c:  # 슬롯은 그대로(holder가 곧 release·리퍼로 비운다)
        assert c.execute(text("select holder_job_id from worker_slot where id=1")).scalar() == jrow["id"]
    go.set()
    assert done.wait(20) and not errs, errs
    t.join()
    with big_engine.begin() as c:
        got = lease_repo.claim_gpu(c, "w-new", 30)
    assert got is not None and got["id"] == kid and got["holds_slot"] is True  # 커밋 뒤 수령 성공(GPU 동시 1 유지)
    time.sleep(1.5)
    assert _deadlocks(big_engine) - before == 0


def test_v_c3f_16_claim_gpu_interrupts_unlocked_expired_holder_as_before(big_engine):
    """holder 행이 잠겨 있지 않으면 지금까지처럼 INTERRUPTED(WORKER_LOST) 처리 후 다음 작업을 수령한다(수령 결과·순번 불변)."""
    from physicsai_core.db.repositories import job_lease as lease_repo

    jrow, kid = _gpu_holder_expired(big_engine)
    with big_engine.begin() as c:
        got = lease_repo.claim_gpu(c, "w-new", 30)
    assert got is not None and got["id"] == kid
    with big_engine.connect() as c:
        st = c.execute(text("select state, failure_code from jobs where id=:i"), {"i": jrow["id"]}).one()
        assert tuple(st) == ("INTERRUPTED", "WORKER_LOST")
        assert c.execute(text("select holder_job_id from worker_slot where id=1")).scalar() == kid


def test_v_c3f_16_static_lock_order_rules():
    """정적: claim_gpu의 holder 잠금은 skip_locked, release·_interrupt에서 worker_slot UPDATE는 jobs를 만지는 부수 효과 뒤에 온다."""
    import inspect

    from physicsai_core.db.repositories import job_lease as lease_repo
    from physicsai_core.db.repositories import job_lease_end as end_repo

    src = inspect.getsource(lease_repo.claim_gpu)
    assert "with_for_update(skip_locked=True)" in src.split("_interrupt(conn, holder)")[0]
    assert "get_job(conn, slot.holder_job_id, for_update=True)" not in src  # 기다리는 holder 잠금 제거
    rel = inspect.getsource(end_repo.release)
    assert rel.index("_side_effects_on_end") < rel.index("update(worker_slot)") < rel.index("recompute_my_turn")
    intr = inspect.getsource(end_repo._interrupt)
    assert intr.index("_side_effects_on_end") < intr.index("update(worker_slot)")


def test_v_c3f_16_release_touches_worker_slot_last_among_jobs_statements(big_engine):
    """동적: release가 실행한 SQL 중 worker_slot UPDATE 뒤에는 jobs·job_steps 쓰기나 기다리는 행 잠금이 없다(알림 계산의 SKIP LOCKED만)."""
    from sqlalchemy import event

    from physicsai_core.db.repositories import job_lease as lease_repo

    jrow, _kid = _gpu_holder_expired(big_engine)
    with big_engine.begin() as c:
        c.execute(text("update jobs set lease_expires_at = now() + interval '60 second' where id=:i"), {"i": jrow["id"]})
        c.execute(text("update worker_slot set lease_expires_at = now() + interval '60 second' where id=1"))
    stmts: list[str] = []

    def rec(_conn, _cur, statement, *_a):
        stmts.append(" ".join(statement.split()))

    event.listen(big_engine, "before_cursor_execute", rec)
    try:
        with big_engine.begin() as c:
            lease_repo.release(c, jrow["id"], jrow["lease_token"], "SUCCEEDED")
    finally:
        event.remove(big_engine, "before_cursor_execute", rec)
    idx = [n for n, s in enumerate(stmts) if s.startswith("UPDATE worker_slot")]
    assert len(idx) == 1, stmts
    for s in stmts[idx[0] + 1:]:
        assert not s.startswith(("UPDATE jobs", "UPDATE job_steps", "INSERT INTO job_steps"))
        assert "FOR UPDATE" not in s or "SKIP LOCKED" in s, s
