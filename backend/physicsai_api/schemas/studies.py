"""API 스키마 — Study·경로 확인(§10.3, phase2 §12.4)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field, field_validator

from .common import Req, Resp

__all__ = ["Study", "StudyCreate", "StudyPatch", "PathInspectRequest", "PathProblem", "PathInspectResponse"]


class Study(Resp):
    id: str
    project_id: str
    folder_name: str
    title: str
    status: str
    final_model_id: str | None = None
    created_by: str
    created_by_name: str
    created_at: datetime
    updated_at: datetime
    version: int
    can_execute: bool
    folder_display_path: str | None = None


class StudyCreate(Req):
    project_id: str = Field(min_length=1, max_length=200)
    folder_name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,63}$")
    title: str = Field(min_length=1, max_length=120)

    @field_validator("folder_name")
    @classmethod
    def _not_reserved(cls, v: str) -> str:
        from physicsai_core.paths import windows_reserved_name

        if windows_reserved_name(v):
            raise ValueError("Windows 예약 이름(CON·PRN·AUX·NUL·COM1-9·LPT1-9)은 폴더 이름으로 쓸 수 없습니다")
        return v


class StudyPatch(Req):
    version: int
    title: str = Field(min_length=1, max_length=120)


class PathInspectRequest(Req):
    purpose: Literal["DATASET_INPUT", "MODEL_FOLDER", "PARAM_SET", "CAD_FILE", "RADIOSS_ASSEM", "RESULT_FOLDER",
                     "CURATION_INPUT", "SPDM_IMPORT"]
    path: str = Field(max_length=400)
    doe_id: str | None = None


class PathProblem(Resp):
    code: str
    message: str | None = None
    file: str | None = None


class PathInspectResponse(Resp):
    normalized_path: str
    ok: bool
    problems: list[PathProblem]
    summary: dict[str, Any]
