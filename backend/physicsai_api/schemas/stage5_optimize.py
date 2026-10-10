"""API 스키마 — ⑤ 최적화·응답 후보(phase2 §12.11)."""

from __future__ import annotations

from datetime import datetime
from typing import Any


from .common import Resp

__all__ = ["Optimization", "CandidateDatatype", "CandidateSubcase", "CandidateH3d", "CandidateXy", "ResponseCandidates"]


class Optimization(Resp):
    id: str
    study_id: str
    job_id: str
    status: str
    approach: str
    opt_method: str
    max_designs: int
    model_id: str
    model_name: str | None = None
    param_set_id: str
    study_folder: str
    runs_started: int | None = None
    responses: list[dict[str, Any]]
    summary_status: str
    summary_meta: dict[str, Any] | None = None
    summary_artifact_id: str | None = None
    file_count: int | None = None
    file_list_artifact_id: str | None = None
    folder_display_path: str | None = None
    created_by_name: str
    created_at: datetime


class CandidateDatatype(Resp):
    name: str
    components: list[str]
    layers: list[str]
    format: Any = None


class CandidateSubcase(Resp):
    id: int
    label: str
    datatypes: list[CandidateDatatype]


class CandidateH3d(Resp):
    subcases: list[CandidateSubcase]


class CandidateXy(Resp):
    requests: dict[str, list[str]]


class ResponseCandidates(Resp):
    source_job_id: str | None = None
    h3d: CandidateH3d | None = None
    xydata: CandidateXy | None = None
