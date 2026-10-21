"""토큰별 호출 제한(mcp.md §11): 분당 요청·분당 plan, 고정 창 60초. 프로세스 메모리(단일 uvicorn 프로세스 전제).

재기동 시 초기화는 허용. 다중 프로세스로 바꾸면 DB 카운터로 옮긴다(리스크 표).
"""

from __future__ import annotations

import math
import threading
from collections.abc import Callable

from physicsai_core.errors import DomainError

from . import clock

WINDOW_S = 60.0


class RateLimited(DomainError):
    """429 + Retry-After 헤더(main의 DomainError 처리기가 `headers`를 붙인다)."""

    def __init__(self, code: str, message: str, retry_after: int, **extra: object) -> None:
        super().__init__(code, message, status=429, retry_after_s=retry_after, **extra)
        self.headers = {"Retry-After": str(retry_after)}


class FixedWindowLimiter:
    def __init__(self, now: Callable[[], float] | None = None) -> None:
        self._now = now or clock.monotonic
        self._lock = threading.Lock()
        self._win: dict[tuple[str, str], tuple[float, int]] = {}

    def hit(self, token_id: str, bucket: str, limit: int) -> None:
        """한 번 세고, 창 안에서 limit을 넘으면 RateLimited(Retry-After = 창이 끝날 때까지 초)."""
        t = self._now()
        key = (token_id, bucket)
        with self._lock:
            start, n = self._win.get(key, (t, 0))
            if t - start >= WINDOW_S:
                start, n = t, 0
            n += 1
            self._win[key] = (start, n)
            if len(self._win) > 10000:  # 오래된 창 정리
                for k in [k for k, (s, _) in self._win.items() if t - s >= WINDOW_S]:
                    self._win.pop(k, None)
        if n > limit:
            retry = max(1, math.ceil(WINDOW_S - (t - start)))
            label = "plan_job 호출" if bucket == "plan" else "요청"
            raise RateLimited("RATE_LIMITED", f"토큰의 분당 {label} 상한({limit})을 넘었습니다 — {retry}초 뒤 다시 시도하세요", retry)

    def reset(self) -> None:
        with self._lock:
            self._win.clear()
