"""GPU 조회 스레드 `GpuMonitor`(phase3 §24.3 S19).

- nvidia-smi 요약 조회(제한 시간 `worker.gpu_query_timeout_s`, 제한기 밖, shell=False)를 이 스레드만 한다. 하트비트·
  환경 점검(직접 조회, 같은 제한 시간)은 막히지 않는다.
- 간격: `worker.resource_sample_interval_s`(= base). 연속 실패 k회는 k < after면 base, 아니면
  min(max, base × 2^(k − after + 1)). max = 0이면 늘리지 않음. 성공하면 k = 0.
- 진단 로그(워커 로그 `physicsai_worker`)는 상태 전이 때만 1줄. 같은 상태 반복은 기록하지 않는다.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from . import resources
from .resources import GpuResult

log = logging.getLogger("physicsai_worker")

OK = "OK"


def _dur(sec: float) -> str:
    s = max(0, int(round(sec)))
    if s < 60:
        return f"{s}초"
    if s < 3600:
        return f"{s // 60}분 {s % 60}초"
    return f"{s // 3600}시간 {s % 3600 // 60}분"


def backoff_interval(base: float, streak: int, after: int, max_s: float) -> float:
    """연속 실패 streak회 뒤 다음 조회까지 간격(초)."""
    if streak < after or max_s <= 0:
        return base
    return min(max_s, base * 2 ** (streak - after + 1))


class GpuMonitor:
    """GPU 표본 캐시. settings_fn·env_fn은 호출 시점 값(설정 변경 반영). query·clock은 시험 주입용."""

    def __init__(
        self,
        settings_fn: Callable[[], Any],
        env_fn: Callable[[], dict[str, str]] | None = None,
        *,
        query: Callable[[Any, dict[str, str] | None], GpuResult] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.settings_fn = settings_fn
        self.env_fn = env_fn or (lambda: None)  # type: ignore[assignment,return-value]
        self.query = query or self._default_query
        self.clock = clock
        self._lock = threading.Lock()
        self._poll_lock = threading.Lock()
        self._cache: dict[str, Any] = {"gpus": [], "status": None, "message": None, "exe": None, "sampled_at": None,
                                       "fail_streak": 0, "next_query_at": None}
        self._fail_since: float | None = None
        self._last_poll: float | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ---- 조회 ----
    @staticmethod
    def _default_query(s: Any, env: dict[str, str] | None) -> GpuResult:
        return resources.query_gpu_status(s.worker.gpu_query, s.resources.gpu_query_candidates, env,
                                          timeout_s=s.worker.gpu_query_timeout_s)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            snap = dict(self._cache)
            snap["gpus"] = [dict(g) for g in snap["gpus"]]
            return snap

    def interval(self) -> float:
        """다음 조회까지 간격(초) — 현재 상태·설정으로 계산."""
        s = self.settings_fn()
        base = float(s.worker.resource_sample_interval_s)
        with self._lock:
            status, k = self._cache["status"], int(self._cache["fail_streak"])
        if status == OK or status is None:
            return base
        return backoff_interval(base, k, int(s.worker.gpu_backoff_after), float(s.worker.gpu_backoff_max_s))

    def poll_once(self) -> dict[str, Any]:
        """요약 조회 1회 → 캐시 갱신·전이 로그 → 스냅숏."""
        with self._poll_lock:
            s = self.settings_fn()
            g = self.query(s, self.env_fn())
            now = self.clock()
            self._last_poll = now
            self._update(s, g, now)
            return self.snapshot()

    def _update(self, s: Any, g: GpuResult, now: float) -> None:
        after, max_s = int(s.worker.gpu_backoff_after), float(s.worker.gpu_backoff_max_s)
        base = float(s.worker.resource_sample_interval_s)
        with self._lock:
            prev, k = self._cache["status"], int(self._cache["fail_streak"])
            if g.status == OK:
                if prev is not None and prev != OK:
                    name = g.gpus[0].get("name") if g.gpus else "GPU"
                    since = self._fail_since if self._fail_since is not None else now
                    log.info("GPU 조회 회복: %s %d개(실패 %d회, %s)", name, len(g.gpus), k, _dur(now - since))
                k = 0
                self._fail_since = None
            else:
                k += 1
                if prev is None and g.status == "NOT_FOUND":
                    log.info("GPU 조회 불가(NOT_FOUND): %s", g.message)
                elif prev is None or prev == OK:
                    log.warning("GPU 조회 실패(%s): %s — 회복될 때까지 같은 실패는 기록하지 않습니다", g.status, g.message)
                elif prev != g.status:
                    log.warning("GPU 조회 상태 변경(%s → %s): %s", prev, g.status, g.message)
                if self._fail_since is None:
                    self._fail_since = now
                if k == after and max_s > 0:
                    log.warning("GPU 조회 연속 %d회 실패 — 조회 간격을 늘립니다(최대 %s초)", k, f"{max_s:g}")
            nxt = None
            if g.status != OK:
                iv = backoff_interval(base, k, after, max_s)
                if iv > base:
                    nxt = now + iv
            self._cache = {"gpus": list(g.gpus), "status": g.status, "message": g.message, "exe": g.exe, "sampled_at": now,
                           "fail_streak": k, "next_query_at": nxt}

    # ---- 스레드 ----
    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _due(self) -> bool:
        return self._last_poll is None or self.clock() - self._last_poll >= self.interval()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                if self._due():
                    self.poll_once()
            except Exception:  # noqa: BLE001
                log.exception("GPU 조회 루프 오류")
            self._stop.wait(0.1)

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="gpu", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
