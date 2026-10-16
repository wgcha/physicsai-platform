"""API 스키마 — ④ 파라미터 세트·샘플·예측 입력 확인, ①→④(§10.4, phase2 §6.13)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, Field

from physicsai_core.naming import label_problem

from .common import Req, Resp


def _check_label(v: str | None) -> str | None:
    """표시 이름 공통 검증(D3-50): 제어·양방향 제어 문자 → 422(INVALID_PARAMS). 서비스 `_label`도 같은 함수로 다시 본다."""
    if v is not None:
        why = label_problem(v)
        if why:
            raise ValueError(why)
    return v


Label = Annotated[str | None, AfterValidator(_check_label)]

__all__ = [
    "ParamSetCreate", "Parameter", "ResponseDef", "TplParam", "ParamSet", "SampleRow", "SamplesPage",
    "PredictCheckRequest", "OutOfRange", "Rounded", "Nearest", "PredictCheckResponse", "ParamSetFromTrain",
    "ParamSetDiscoverChoice", "ParamSetDiscoverRequest", "DiscoverTpl", "DiscoverCad", "DiscoverAssem", "DiscoverProblem",
    "ParamSetDiscoverResponse", "ParamSetPatch",
]


class ParamSetDiscoverChoice(Req):
    """phase3 §13 S8: discover가 돌려준 후보 중 사용자가 고른 것(상대경로). 후보가 1개면 생략 가능."""

    tpl: str | None = Field(default=None, max_length=400)
    cad: str | None = Field(default=None, max_length=400)
    radioss_assem: str | None = Field(default=None, max_length=400)


class ParamSetCreate(Req):
    path: str = Field(max_length=400)
    # 생략 = 기존 §15.4 폴더 등록(호환). "discover" = 프로젝트 폴더에서 자동 구성(phase3 §13 S8)
    mode: Literal["folder", "discover"] | None = None
    choice: ParamSetDiscoverChoice | None = None
    label: Label = Field(default=None, max_length=120)


class ParamSetPatch(Req):
    label: Label = Field(default=None, max_length=120)


class ParamSetDiscoverRequest(Req):
    path: str = Field(max_length=400)
    tpl: str | None = Field(default=None, max_length=400)


class DiscoverTpl(Resp):
    rel: str
    name: str
    parameter_count: int
    cad_ref: str | None = None


class DiscoverCad(Resp):
    rel: str
    name: str


class DiscoverAssem(Resp):
    rel: str
    starter: str
    has_eps_mesh: bool
    has_renum_csv: bool
    file_count: int


class DiscoverProblem(Resp):
    code: str
    message: str
    file: str | None = None


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
    label: str | None = None


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
    label: Label = Field(default=None, max_length=120)


class ParamSetDiscoverResponse(Resp):
    path: str
    tpl: list[DiscoverTpl]
    selected_tpl: str | None = None
    cad: list[DiscoverCad]
    radioss_assem: list[DiscoverAssem]
    parameters_source: Literal["file", "tpl"] | None = None
    parameters_file: str | None = None
    parameters: list[Parameter]
    samples: str | None = None
    responses: str | None = None
    problems: list[DiscoverProblem]
    notes: list[DiscoverProblem]
    truncated: bool
    scanned: int
