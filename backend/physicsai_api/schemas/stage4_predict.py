"""API 스키마 — ④ 파라미터 세트·샘플·예측 입력 확인, ①→④(§10.4, phase2 §6.13)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from .common import Req, Resp

__all__ = [
    "ParamSetCreate", "Parameter", "ResponseDef", "TplParam", "ParamSet", "SampleRow", "SamplesPage",
    "PredictCheckRequest", "OutOfRange", "Rounded", "Nearest", "PredictCheckResponse", "ParamSetFromTrain",
]


class ParamSetCreate(Req):
    path: str = Field(max_length=400)


class Parameter(Resp):
    name: str
    nominal: float
    min: float
    max: float
    unit: str = ""


class ResponseDef(Resp):
    name: str
    unit: str = ""


class TplParam(Resp):
    var: str
    name: str
    format: str


class ParamSet(Resp):
    id: str
    study_id: str
    source_path: str
    unit_system: str
    parameters: list[Parameter]
    responses: list[ResponseDef]
    sample_count: int
    sample_has_measured: bool
    cad_file_name: str
    starter_name: str
    tpl_params: list[TplParam]
    is_current: bool
    registered_by_name: str
    registered_at: datetime
    origin: str = "FOLDER"
    train_doe_id: str | None = None


class SampleRow(Resp):
    run_key: str
    values: dict[str, float]
    measured: dict[str, float | None]


class SamplesPage(Resp):
    columns: list[str]
    rows: list[SampleRow]
    next_cursor: str | None = None


class PredictCheckRequest(Req):
    param_set_id: str | None = None
    values: dict[str, float]


class OutOfRange(Resp):
    name: str
    value: float
    min: float
    max: float


class Rounded(Resp):
    name: str
    value: float
    applied: float


class Nearest(Resp):
    run_key: str
    distance: float
    values: dict[str, float]
    measured: dict[str, float | None] | None = None


class PredictCheckResponse(Resp):
    out_of_range: list[OutOfRange]
    rounded: list[Rounded]
    nearest: Nearest | None = None


class ParamSetFromTrain(Req):
    doe_id: str
    runs: Literal["collected", "all"] = "collected"
    unit_system: str | None = Field(default=None, max_length=40)
