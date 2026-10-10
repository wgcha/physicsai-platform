"""API 스키마 — ① 학습데이터 생성: 파라미터 표·tpl·DOE·run(phase2 §12.5~§12.7)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from .common import Req, Resp
from .stage4_predict import TplParam

__all__ = [
    "TrainParamOut", "TrainParamUpdate", "TrainParamsPut", "VersionBody", "TrainCad", "TrainTpl", "TrainSetup",
    "DoeField", "DoeType", "RunStateCounts", "TrainDoe", "TrainRunHpc", "TrainRunResult", "TrainRun",
]


class TrainParamOut(Resp):
    name: str
    raw_nominal: str = ""
    nominal: float | None = None
    min: float | None = None
    max: float | None = None
    use: bool
    format: str
    unit: str = ""
    valid: bool
    problems: list[str]


class TrainParamUpdate(Req):
    name: str
    min: float | None = None
    max: float | None = None
    use: bool
    format: str | None = Field(default=None, max_length=16)
    unit: str | None = Field(default=None, max_length=16)


class TrainParamsPut(Req):
    version: int
    parameters: list[TrainParamUpdate]


class VersionBody(Req):
    version: int


class TrainCad(Resp):
    source_path: str | None = None
    file_name: str | None = None
    sha256: str | None = None
    display_path: str | None = None


class TrainTpl(Resp):
    generated_at: datetime | None = None
    sha256: str | None = None
    display_path: str | None = None
    params: list[TplParam]
    warnings: list[dict[str, str]]
    stale: bool


class TrainSetup(Resp):
    study_id: str
    cad: TrainCad | None = None
    extract_job_id: str | None = None
    parameters: list[TrainParamOut]
    used_count: int
    tpl: TrainTpl | None = None
    version: int
    updated_by_name: str | None = None
    updated_at: datetime | None = None


class DoeField(Resp):
    key: str
    label: str
    type: Literal["combo", "int", "bool"]
    items: list[str] | None = None
    default: Any = None
    min: int | None = None
    max: int | None = None


class DoeType(Resp):
    label: str
    value: str
    default_runs: int
    runs_editable: bool
    fields: list[DoeField]


class RunStateCounts(Resp):
    GENERATED: int = 0
    SUBMITTED: int = 0
    SOLVED: int = 0
    SOLVE_FAILED: int = 0
    COLLECTED: int = 0
    COLLECT_FAILED: int = 0


class TrainDoe(Resp):
    id: str
    study_id: str
    job_id: str
    status: str
    doe_label: str
    doe_type: str
    num_runs_requested: int | None = None
    options: dict[str, Any]
    multi_execution: int
    radioss_assem_source_path: str
    run_count: int | None = None
    sample_status: str
    collected_count: int
    solve_failed_count: int
    has_run_responses: bool
    dir_display_path: str | None = None
    results_display_path: str | None = None
    created_by_name: str
    created_at: datetime
    run_state_counts: RunStateCounts


class TrainRunHpc(Resp):
    external_job_id: str | None = None
    state: str
    attempt_no: int


class TrainRunResult(Resp):
    h3d: int = 0
    t01: int = 0
    files: int = 0
    total_bytes: int = 0


class TrainRun(Resp):
    run_key: str
    state: str
    starter_name: str
    input_display_path: str | None = None
    hpc: TrainRunHpc | None = None
    result: TrainRunResult | None = None
    updated_at: datetime
