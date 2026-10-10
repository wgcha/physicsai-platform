"""API 스키마 — 작업·step·로그·산출물·HPC(§10.2, §10.6)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from .common import Req, Resp

__all__ = [
    "HpcSummary", "JobSummary", "JobStep", "Job", "JobType", "JobCreate", "RetryRequest", "LogChunk", "Artifact",
    "HpcJob",
]


class HpcSummary(Resp):
    total: int
    queued: int
    running: int
    succeeded: int
    failed: int
    collected: int


class JobSummary(Resp):
    id: str
    study_id: str
    project_id: str
    study_title: str | None = None
    job_type: str
    stage: int
    lane: str
    state: str
    created_by: str
    created_by_name: str
    queue_position: int | None = None
    progress_pct: float | None = None
    progress_label: str | None = None
    cancel_requested: bool
    created_at: datetime
    started_at: datetime | None = None
    stage_label: str | None = None
    current_step_key: str | None = None
    current_step_label: str | None = None
    hpc_summary: HpcSummary | None = None
    attention_code: str | None = None


class JobStep(Resp):
    step_no: int
    step_key: str
    kind: str
    state: str
    progress_pct: float | None = None
    progress_label: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    exit_code: int | None = None
    failure_code: str | None = None
    failure_message: str | None = None
    command: dict[str, Any] | None = None


class Job(JobSummary):
    params: dict[str, Any]
    result: dict[str, Any] | None = None
    warnings: list[dict[str, Any]]
    steps: list[JobStep]
    failure_code: str | None = None
    failure_message: str | None = None
    finished_at: datetime | None = None
    retry_of_job_id: str | None = None
    version: int
    can_cancel: bool
    can_retry: bool
    can_download_error_bundle: bool = False
    input_display_path: str | None = None


JobType = Literal[
    "DATASET_CREATE", "PACKAGE_EXPORT", "MODEL_REGISTER", "EVALUATE", "PREDICT", "PREDICT_VERIFY",
    "TD_EXTRACT_PARAMS", "TD_DOE_GEN", "TD_SOLVE", "TD_RESULT_IMPORT", "TD_RESP_EXTRACT", "CU_H3D_PREVIEW", "CU_H3D_CURATE",
    "CU_T01_PREVIEW", "CU_T01_CURVES", "SPDM_IMPORT", "OPTIMIZE",
]


class JobCreate(Req):
    job_type: JobType
    params: dict[str, Any] = Field(default_factory=dict)


class RetryRequest(Req):
    from_step: int | None = Field(default=None, ge=1)


class LogChunk(Resp):
    text: str
    next_cursor: int
    eof: bool
    size: int


class Artifact(Resp):
    id: str
    study_id: str
    job_id: str | None = None
    kind: str
    file_name: str
    size: int
    sha256: str | None = None
    content_type: str
    created_at: datetime


class HpcJob(Resp):
    id: str
    run_key: str
    attempt_no: int
    external_job_id: str | None = None
    state: str
    external_state_raw: str | None = None
    submitted_at: datetime | None = None
    elapsed_s: float | None = None
    collect_state: str
