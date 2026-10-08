"""프로세스 제한기(§11.5)."""

from __future__ import annotations

import os
from typing import Any

from .base import Accounting, LimitedProcess, LimiterError, ProcessLimiter


def select_limiter(worker_cfg: Any, profile: str) -> ProcessLimiter:
    name = worker_cfg.limiter
    if name == "auto":
        name = "windows_job" if os.name == "nt" else "posix"
    if name == "windows_job":
        from .windows_job import WindowsJobLimiter

        return WindowsJobLimiter()
    if name == "null":
        if profile != "dev":
            raise LimiterError("CONFIG_INVALID", "null 제한기는 dev에서만 허용됩니다")
        from .null import NullLimiter

        return NullLimiter()
    from .posix import PosixLimiter

    return PosixLimiter(rlimit_as=bool(worker_cfg.posix_rlimit_as))


__all__ = ["select_limiter", "ProcessLimiter", "LimitedProcess", "Accounting", "LimiterError"]
