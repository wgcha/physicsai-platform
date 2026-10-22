"""교착(SQLSTATE 40P01) 판별과 짧은 재시도(job-queues.md §5 JQ-C1). 수령 트랜잭션처럼 통째로 다시 해도 결과가 같은 작업에만 쓴다."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar

DEADLOCK_SQLSTATE = "40P01"
DEADLOCK_RETRIES = 3  # 첫 시도 뒤 재시도 최대 횟수
DEADLOCK_BACKOFF_S = 0.02  # 재시도 사이 짧은 대기(시도마다 2배)

T = TypeVar("T")


def is_deadlock(exc: BaseException | None) -> bool:
    """SQLAlchemy가 감싼 DBAPI 오류 포함, 원인 사슬에 SQLSTATE 40P01이 있으면 true."""
    seen = 0
    while exc is not None and seen < 8:
        cur = getattr(exc, "orig", None) or exc
        if getattr(cur, "sqlstate", None) == DEADLOCK_SQLSTATE or getattr(cur, "pgcode", None) == DEADLOCK_SQLSTATE:
            return True
        exc = exc.__cause__ or exc.__context__
        seen += 1
    return False


def retry_deadlock(fn: Callable[[], T], *, retries: int = DEADLOCK_RETRIES, backoff_s: float = DEADLOCK_BACKOFF_S,
                   on_retry: Callable[[int], None] | None = None) -> T:
    """`fn`(트랜잭션 전체)을 부르고 교착이면 최대 `retries`회 다시 부른다. 그 밖의 오류·재시도 소진은 그대로 올린다."""
    for attempt in range(retries + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - 40P01만 다시 시도
            if attempt >= retries or not is_deadlock(exc):
                raise
            if on_retry:
                on_retry(attempt + 1)
            time.sleep(backoff_s * (2**attempt))
    raise AssertionError("unreachable")
