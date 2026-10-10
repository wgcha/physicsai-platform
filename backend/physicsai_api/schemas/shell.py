"""API 스키마 — 셸: 상태·대기열·자원·알림·관리 설정(§10.5, §10.7, §10.8, phase2 §12.1)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from .common import Req, Resp
from .jobs import JobSummary

__all__ = [
    "StatusConfig", "StatusWorker", "StatusHpc", "KeyOk", "TemplateConfigured", "StatusLimits", "ResourceStatus",
    "FeatureState", "StatusFeatures", "StatusEnvCheck", "StatusResponse", "QueueSlot", "QueueLight",
    "QueueResponse", "MoveRequest", "GpuInfo", "ResourceJob", "ResourceLimits", "ResourcesResponse",
    "Notification", "NotificationList", "UnreadCount", "ReadRequest", "ReadResponse", "AdminConfig",
]


class StatusConfig(Resp):
    ok: bool
    errors: list[str]
    warnings: list[str] = Field(default_factory=list, description="기동은 막지 않는 설정 안내 키(누락 → 기능 비활성, 예약 키)")


class StatusWorker(Resp):
    online: bool
    worker_id: str | None = None
    last_seen_at: datetime | None = None
    limiter: str | None = None


class StatusHpc(Resp):
    mode: str
    configured: bool
    message: str
    collect_mode: str = "in_place"


class KeyOk(Resp):
    key: str
    ok: bool


class TemplateConfigured(Resp):
    key: str
    configured: bool


class StatusLimits(Resp):
    configured: dict[str, Any]
    detected: dict[str, Any] | None = None
    effective: dict[str, Any] | None = None


class ResourceStatus(Resp):
    key: str
    configured: bool
    ok: bool


class FeatureState(Resp):
    enabled: bool
    missing: list[str]


class StatusFeatures(Resp):
    train_extract: FeatureState
    train_tpl: FeatureState
    train_doe: FeatureState
    train_solve: FeatureState
    train_import: FeatureState
    train_resp: FeatureState
    curation_h3d: FeatureState
    curation_t01: FeatureState
    spdm_import: FeatureState
    optimize: FeatureState
    dataset_create: FeatureState | None = None
    evaluate: FeatureState | None = None
    predict: FeatureState | None = None


class StatusEnvCheck(Resp):
    latest_id: str | None = None
    latest_state: str | None = None
    finished_at: datetime | None = None
    fail: int | None = None
    warn: int | None = None


class StatusResponse(Resp):
    config: StatusConfig
    worker: StatusWorker
    hpc: StatusHpc
    altair: list[KeyOk]
    templates: list[TemplateConfigured]
    limits: StatusLimits
    ui: dict[str, int]
    auth: dict[str, str]
    resources: list[ResourceStatus] = Field(default_factory=list)
    features: StatusFeatures | None = None
    env_check: StatusEnvCheck | None = None
    demo: bool = Field(False, description="시연 모드(fake tools 배포판) 여부 — true면 화면 상단에 '시연 모드' 배지")


class QueueSlot(Resp):
    holder_job_id: str | None = None
    since: datetime | None = None


class QueueLight(Resp):
    running: JobSummary | None = None
    queued: list[JobSummary]


class QueueResponse(Resp):
    slot: QueueSlot
    running: JobSummary | None = None
    queued: list[JobSummary]
    light: QueueLight
    waiting_hpc: list[JobSummary]
    collecting: list[JobSummary]


class MoveRequest(Req):
    position: int = Field(ge=1)


class GpuInfo(Resp):
    name: str
    util_pct: float | None = None
    mem_used_mb: float | None = None
    mem_total_mb: float | None = None


class ResourceJob(Resp):
    job_id: str
    cpu_time_s: float | None = None
    peak_memory_gb: float | None = None


class ResourceLimits(Resp):
    cores: int | None = None
    cpu_rate: int | None = None
    memory_gb: float | None = None
    priority: str | None = None
    cpu_cap_enforced: bool = False


class ResourcesResponse(Resp):
    sampled_at: datetime | str | None = None
    cpu_pct: float | None = None
    ram_used_gb: float | None = None
    ram_total_gb: float | None = None
    gpu: list[GpuInfo]
    job: ResourceJob | None = None
    limits: ResourceLimits


class Notification(Resp):
    seq: int
    event: str
    job_id: str | None = None
    study_id: str | None = None
    project_id: str | None = None
    title: str
    body: str
    created_at: datetime
    read_at: datetime | None = None


class NotificationList(Resp):
    items: list[Notification]
    max_seq: int
    unread_count: int


class UnreadCount(Resp):
    unread_count: int
    max_seq: int


class ReadRequest(Req):
    seqs: list[int] | None = None
    all: bool = False


class ReadResponse(Resp):
    unread_count: int


class AdminConfig(Resp):
    path: str | None = None
    sha256: str | None = None
    ok: bool
    issues: list[dict[str, str]]
    settings: dict[str, Any]
    templates: dict[str, Any]
