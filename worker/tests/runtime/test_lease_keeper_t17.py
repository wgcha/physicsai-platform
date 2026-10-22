"""T17 직후 재수령이 옛 LeaseKeeper의 진행 중 renew에 막히지 않는다(job-queues.md §5 규칙 1, V-JQ-5·10 보강).

배경: release가 jobs 행 잠금을 쥔 동안 keeper의 `UPDATE ... WHERE lease_token=<옛 토큰>`이 대기하다가 release 커밋 뒤 0행으로 끝나도,
PostgreSQL(READ COMMITTED)은 그 트랜잭션이 끝날 때까지 갱신된 행 버전에 잠금을 남긴다. 그 사이 `FOR UPDATE SKIP LOCKED`로 같은 작업을
다시 고르는 claim은 행을 건너뛰어 None이 된다(전체 시험 부하에서만 드러난 "QUEUED로 끝남" 간헐 실패의 원인).
`_release`는 keeper를 먼저 멈추고 release 뒤 keeper 스레드가 끝나기를 기다려, 호출이 돌아온 시점에 keeper의 열린 트랜잭션이 없게 한다.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import pytest

from queue_support import add_job, job_row, patch_handlers

STALL_S = 0.25  # 옛 토큰 renew(0행)가 트랜잭션을 연 채 머무는 시간 — 경합 창을 시험에서 결정적으로 넓힌다
RELEASE_HOLD_S = 0.1  # release 트랜잭션이 jobs 행 잠금을 쥐고 있는 시간(keeper의 UPDATE가 그 안에 들어오게 한다)


@pytest.fixture()
def fast_hb_worker(db_url, settings_dict):
    from physicsai_core.config import load_config_dict
    from physicsai_core.db.engine import make_engine
    from physicsai_worker.runtime import Worker

    d = dict(settings_dict)
    d["worker"] = {**d["worker"], "claim_interval_s": 0.05, "lease_ttl_s": 5, "heartbeat_interval_s": 0.005,
                   "queues": {"cpu": {"max_concurrent": 2, "min_free_memory_gb": 0}}}
    lc = load_config_dict(d, environ={})
    assert lc.ok, lc.issues
    eng = make_engine(db_url, pool_size=20)
    w = Worker(lc, eng)
    yield w, eng
    w.stop()
    eng.dispose()


def _widen_race(monkeypatch) -> None:
    """keeper의 renew가 실패(0행)하면 트랜잭션을 연 채 STALL_S 머문다 + release 안(행 잠금 보유 중)에서 RELEASE_HOLD_S 지연."""
    from physicsai_core.db.repositories import job_lease as lease_repo
    from physicsai_core.db.repositories import notifications as notif_repo

    orig_renew = lease_repo.renew

    def renew(conn: Any, *a: Any, **k: Any) -> bool:
        ok = orig_renew(conn, *a, **k)
        if not ok:
            time.sleep(STALL_S)
        return ok

    orig_turn = notif_repo.recompute_my_turn
    orig_release = lease_repo.release
    in_release = threading.local()

    def turn(conn: Any) -> Any:  # release 안의 마지막 단계(커밋 직전) — 행 잠금을 쥔 채 머문다
        if getattr(in_release, "on", False):
            time.sleep(RELEASE_HOLD_S)
        return orig_turn(conn)

    def release(*a: Any, **k: Any) -> Any:
        in_release.on = True
        try:
            return orig_release(*a, **k)
        finally:
            in_release.on = False

    monkeypatch.setattr(lease_repo, "renew", renew)
    monkeypatch.setattr(lease_repo, "release", release)
    monkeypatch.setattr(notif_repo, "recompute_my_turn", turn)


def test_t17_reclaim_not_skipped_by_stale_keeper(fast_hb_worker, monkeypatch):
    """CPU→GPU→CPU 전환마다 즉시 재수령이 성공한다(keeper 주기 5ms + 옛 토큰 renew 정체로 경합 극대화, 여러 번 반복)."""
    w, eng = fast_hb_worker
    rec = patch_handlers(monkeypatch, default=0.02)
    _widen_race(monkeypatch)
    for _ in range(3):
        a = add_job(eng, "PREDICT")["id"]
        assert w.run_once_slot() == "SUCCEEDED", job_row(eng, a)
        assert rec.lanes(a) == ["CPU", "GPU", "CPU"]


def test_release_joins_keeper_and_normal_release_is_not_lease_loss(fast_hb_worker, monkeypatch, caplog):
    """정상 종료·T17 뒤 keeper 스레드는 이미 끝났고 "lease 소유권 상실" 경고가 남지 않는다(경고는 진짜 상실에만)."""
    w, eng = fast_hb_worker
    patch_handlers(monkeypatch, default=0.05)
    from physicsai_worker.executor import Executor

    made: list[Executor] = []
    orig_init = Executor.__init__

    def init(self: Executor, *a: Any, **k: Any) -> None:
        orig_init(self, *a, **k)
        made.append(self)

    monkeypatch.setattr(Executor, "__init__", init)
    a = add_job(eng, "PREDICT")["id"]
    with caplog.at_level(logging.WARNING, logger="physicsai_worker.executor"):
        assert w.run_once_slot() == "SUCCEEDED", job_row(eng, a)
    assert len(made) == 3  # CPU·GPU·CPU 3구간
    assert all(ex.keeper is not None and not ex.keeper.is_alive() for ex in made)
    assert not [r for r in caplog.records if "lease 소유권 상실" in r.getMessage()]
