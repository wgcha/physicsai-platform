"""API 스키마 — ② 데이터 정리·SPDM 가져오기(phase2 §12.8, §12.10)."""

from __future__ import annotations

from datetime import datetime
from typing import Any


from .common import Resp

__all__ = ["SourceRef", "CurationSource", "Curation", "CurationFile", "CurationFilesPage", "SpdmImport"]


class SourceRef(Resp):
    kind: str
    doe_id: str | None = None
    import_id: str | None = None
    path: str | None = None


class CurationSource(Resp):
    kind: str
    ref_id: str
    label: str
    display_path: str | None = None
    h3d_count: int
    t01_count: int
    runs_expected: int | None = None
    created_at: datetime


class Curation(Resp):
    id: str
    study_id: str
    job_id: str
    kind: str
    status: str
    source: SourceRef
    source_label: str
    preview_job_id: str | None = None
    selection: dict[str, Any]
    target_count: int | None = None
    ok_count: int | None = None
    failed_count: int | None = None
    missing_runs: list[str]
    output_display_path: str | None = None
    used_by_dataset_ids: list[str]
    created_by_name: str
    created_at: datetime


class CurationFile(Resp):
    run_folder: str
    run_key: str | None = None
    input_name: str
    output_name: str | None = None
    size: int | None = None
    ok: bool
    exit_code: int | None = None


class CurationFilesPage(Resp):
    items: list[CurationFile]
    next_cursor: str | None = None


class SpdmImport(Resp):
    id: str
    study_id: str
    job_id: str
    status: str
    spdm_path: str
    file_count: int | None = None
    total_bytes: int | None = None
    renamed_count: int | None = None
    dest_display_path: str | None = None
    created_by_name: str
    created_at: datetime
