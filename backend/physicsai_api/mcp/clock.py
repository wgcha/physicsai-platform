"""MCP 시각 원천(UTC). 시험은 `now`를 바꿔 끼워 만료·stale·confirm TTL을 확인한다(V-MCP-2·4)."""

from __future__ import annotations

import time
from datetime import datetime, timezone


def now() -> datetime:
    return datetime.now(timezone.utc)


def monotonic() -> float:
    return time.monotonic()
