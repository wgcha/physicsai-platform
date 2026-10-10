"""API 스키마 — 운영: 환경 점검(phase2 §12.2)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal


from .common import Resp

__all__ = ["EnvCheckItem", "EnvCheckCounts", "EnvCheckSummary", "EnvCheck"]


class EnvCheckItem(Resp):
    key: str
    category: Literal["CONFIG", "DATABASE", "AUTH", "HPC", "WORKER", "EXECUTABLE", "RESOURCE", "STORAGE", "GPU"]
    label: str
    status: Literal["OK", "WARN", "FAIL", "SKIP", "PENDING"]
    message: str
    source: Literal["API", "WORKER"]
    detail: Any = None


class EnvCheckCounts(Resp):
    ok: int = 0
    warn: int = 0
    fail: int = 0
    skip: int = 0


class EnvCheckSummary(Resp):
    id: str
    state: str
    requested_by_name: str
    created_at: datetime
    finished_at: datetime | None = None
    summary: EnvCheckCounts


class EnvCheck(EnvCheckSummary):
    started_at: datetime | None = None
    expires_at: datetime
    worker_id: str | None = None
    items: list[EnvCheckItem]
    failure_message: str | None = None
    report_display_path: str | None = None
