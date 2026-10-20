"""S19 GPU 조회 실패 대응(phase3 §24.3, V3-S19-2·3): 제한 시간 설정, GpuMonitor 전이 로그·간격 늘리기, 하트비트 캐시,
가짜 nvidia-smi hang."""

from __future__ import annotations

import logging
import time
from types import SimpleNamespace

import pytest

from physicsai_core.config.schema import WorkerCfg
from physicsai_worker import env_check, resources
from physicsai_worker.gpu_monitor import GpuMonitor, backoff_interval
from physicsai_worker.resources import GpuResult

GPU = [{"name": "RTX A6000", "util_pct": 1.0, "mem_used_mb": 1000.0, "mem_total_mb": 49140.0}]


def _settings(base: float = 10, after: int = 3, max_s: float = 300, timeout: float = 15):
    return SimpleNamespace(
        worker=SimpleNamespace(resource_sample_interval_s=base, gpu_backoff_after=after, gpu_backoff_max_s=max_s,
                               gpu_query_timeout_s=timeout, gpu_query=None),
        resources=SimpleNamespace(gpu_query_candidates=[]))


class Seq:
    """조회 결과 열(OK·ERR·NF)과 시계를 주입."""

    def __init__(self, seq: list[str]) -> None:
        self.seq = list(seq)
        self.t = 1000.0

    def query(self, s, env) -> GpuResult:
        k = self.seq.pop(0)
        if k == "OK":
            return GpuResult([dict(g) for g in GPU], "OK", "/usr/bin/nvidia-smi", "/usr/bin/nvidia-smi")
        if k == "NF":
            return GpuResult([], "NOT_FOUND", "nvidia-smi를 찾지 못했습니다(시도: x)", None)
        return GpuResult([], "ERROR", "nvidia-smi 종료코드 9: boom", "/usr/bin/nvidia-smi")

    def clock(self) -> float:
        return self.t


def _records(caplog):
    return [(r.levelname, r.getMessage()) for r in caplog.records if r.name == "physicsai_worker"]


# ---- V3-S19-2 제한 시간 ---------------------------------------------------------------------------------------


def test_v3_s19_2_timeout_from_settings(fake_tools, monkeypatch):
    monkeypatch.setenv("FAKE_TOOL_MODE_NVIDIA", "hang")
    exe = fake_tools["fake_nvidia_smi"]
    t0 = time.monotonic()
    g = resources.query_gpu_status([exe], [], None, timeout_s=1)
    assert time.monotonic() - t0 < 5
    assert g.status == "ERROR" and g.message == f"nvidia-smi 응답 시간 초과(1초): {exe}"
    # 기본값 = 스키마 한 곳(worker.gpu_query_timeout_s 15), 상수는 함수 기본값으로만
    assert resources.GPU_TIMEOUT_S == WorkerCfg().gpu_query_timeout_s == 15
    # 환경 점검 gpu.detect도 같은 설정
    s = SimpleNamespace(worker=SimpleNamespace(gpu_query=[exe], gpu_query_timeout_s=1),
                        resources=SimpleNamespace(gpu_query_candidates=[]))
    t0 = time.monotonic()
    it = env_check.gpu_item(s, None)
    assert time.monotonic() - t0 < 5
    assert it["status"] == "WARN" and "응답 시간 초과(1초)" in it["message"]


def test_v3_s19_2_monitor_and_heartbeat_pass_setting(monkeypatch):
    seen: list[float | None] = []

    def fake(gq, cands, env=None, lookup_env=None, *, timeout_s=None):
        seen.append(timeout_s)
        return GpuResult([], "ERROR", "x", "x")

    monkeypatch.setattr(resources, "query_gpu_status", fake)
    GpuMonitor(lambda: _settings(timeout=7)).poll_once()
    assert seen == [7]


# ---- V3-S19-3 GpuMonitor ---------------------------------------------------------------------------------------


def test_v3_s19_3_transition_logs_and_backoff(caplog):
    caplog.set_level(logging.DEBUG, logger="physicsai_worker")
    q = Seq(["OK", "ERR", "ERR", "ERR", "ERR", "ERR", "OK"])
    m = GpuMonitor(lambda: _settings(), query=q.query, clock=q.clock)
    ivs = []
    for _ in range(7):
        m.poll_once()
        ivs.append(m.interval())
        q.t += ivs[-1]
    recs = _records(caplog)
    warns = [x for lv, x in recs if lv == "WARNING"]
    infos = [x for lv, x in recs if lv == "INFO"]
    assert warns == ["GPU 조회 실패(ERROR): nvidia-smi 종료코드 9: boom — 회복될 때까지 같은 실패는 기록하지 않습니다",
                     "GPU 조회 연속 3회 실패 — 조회 간격을 늘립니다(최대 300초)"]
    assert len(infos) == 1 and infos[0].startswith("GPU 조회 회복: RTX A6000 1개(실패 5회, ")
    assert ivs == [10, 10, 10, 20, 40, 80, 10]                     # 실패 1·2회 base, 3회부터 두 배, 회복하면 base
    snap = m.snapshot()
    assert snap["status"] == "OK" and snap["fail_streak"] == 0 and snap["next_query_at"] is None


def test_v3_s19_3_interval_sequence_and_next_query():
    assert [backoff_interval(10, k, 3, 300) for k in range(1, 10)] == [10, 10, 20, 40, 80, 160, 300, 300, 300]
    assert [backoff_interval(10, k, 3, 0) for k in range(1, 8)] == [10] * 7          # max 0 = 늘리지 않음
    q = Seq(["ERR"] * 4)
    m = GpuMonitor(lambda: _settings(), query=q.query, clock=q.clock)
    m.poll_once()
    m.poll_once()
    assert m.snapshot()["next_query_at"] is None                                       # 지연 전에는 null
    m.poll_once()
    snap = m.snapshot()
    assert snap["fail_streak"] == 3 and snap["next_query_at"] == q.t + 20 and snap["sampled_at"] == q.t
    q2 = Seq(["ERR"] * 5)
    m2 = GpuMonitor(lambda: _settings(max_s=0), query=q2.query, clock=q2.clock)
    for _ in range(5):
        m2.poll_once()
    assert m2.interval() == 10 and m2.snapshot()["next_query_at"] is None


def test_v3_s19_3_not_found_then_error_and_repeats(caplog):
    caplog.set_level(logging.DEBUG, logger="physicsai_worker")
    q = Seq(["NF", "NF", "ERR", "ERR"])
    m = GpuMonitor(lambda: _settings(after=10), query=q.query, clock=q.clock)
    for _ in range(4):
        m.poll_once()
    assert _records(caplog) == [
        ("INFO", "GPU 조회 불가(NOT_FOUND): nvidia-smi를 찾지 못했습니다(시도: x)"),
        ("WARNING", "GPU 조회 상태 변경(NOT_FOUND → ERROR): nvidia-smi 종료코드 9: boom"),
    ]


def test_v3_s19_3_due_uses_injected_clock():
    q = Seq(["ERR", "ERR", "ERR"])
    m = GpuMonitor(lambda: _settings(), query=q.query, clock=q.clock)
    assert m._due()
    m.poll_once()
    assert not m._due()
    q.t += 10
    assert m._due()


def test_v3_s19_3_heartbeat_uses_cache_while_hang(worker_factory, monkeypatch):
    from sqlalchemy import text

    monkeypatch.setenv("FAKE_TOOL_MODE_NVIDIA", "hang")
    w = worker_factory()
    w.config.settings.worker.gpu_query_timeout_s = 5
    w.gpu_monitor.start()
    time.sleep(0.3)                                                                     # 스레드가 nvidia-smi에서 막힘
    t0 = time.monotonic()
    w.heartbeat_once()
    assert time.monotonic() - t0 < 1.0
    with w.engine.connect() as c:
        res = c.execute(text("select resources from worker_heartbeats where worker_id=:w"), {"w": w.worker_id}).scalar_one()
    assert set(res) >= {"gpu", "gpu_status", "gpu_message", "gpu_fail_streak", "gpu_sampled_at", "gpu_next_query_at"}
    w.gpu_monitor.stop()
