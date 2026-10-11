"""API 스키마 — Study 용량·정리(phase3 §5.6). 경로는 Study 기준 '/' 상대경로, 표시용 절대경로는 *_display_path만."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from .common import Resp

__all__ = [
    "CategoryKey", "StorageFolder", "StorageTopFile", "StorageItem", "StorageCategory", "StorageScan",
    "CleanupSkip", "CleanupSummary", "StorageReport",
]

CategoryKey = Literal["PACKAGE_PSDATA", "SCORE_PREDICTIONS", "CURATED_H3D", "PREDICT_INPUT", "PREVIEW_OUTPUT", "JOB_LOGS"]


class StorageFolder(Resp):
    key: str
    bytes: int
    files: int


class StorageTopFile(Resp):
    rel: str
    bytes: int
    modified_at: datetime
    in_backup: bool


class StorageItem(Resp):
    rel: str
    bytes: int
    files: int
    ref_id: str | None = None
    note: str | None = None


class StorageCategory(Resp):
    key: CategoryKey
    label: str
    impact: str
    total_bytes: int
    item_count: int
    truncated: bool
    items: list[StorageItem]


class StorageScan(Resp):
    job_id: str
    started_at: datetime
    finished_at: datetime
    partial: bool
    total_bytes: int
    total_files: int
    skipped_links: int
    errors: int
    backup_bytes: int
    backup_files: int
    folders: list[StorageFolder]
    top_files: list[StorageTopFile]
    categories: list[StorageCategory]


class CleanupSkip(Resp):
    rel: str
    reason: str


class CleanupSummary(Resp):
    job_id: str
    state: str
    finished_at: datetime | None = None
    categories: list[CategoryKey]
    moved_count: int
    moved_bytes: int
    skipped_count: int
    skipped: list[CleanupSkip]
    backup_rel: str | None = None
    backup_display_path: str | None = None


class StorageReport(Resp):
    study_id: str
    scan: StorageScan | None = None
    stale: bool
    stale_reason: str | None = None
    active_scan_job_id: str | None = None
    active_cleanup_job_id: str | None = None
    last_cleanup: CleanupSummary | None = None
    study_display_path: str | None = None
    backup_display_path: str | None = None
