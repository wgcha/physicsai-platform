"""API 스키마 — ④ 파라미터 세트·샘플·예측 입력 확인, ①→④(§10.4, phase2 §6.13)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from .common import Req, Resp

__all__ = [
    "ParamSetCreate", "Parameter", "ResponseDef", "TplParam", "ParamSet", "SampleRow", "SamplesPage",
    "PredictCheckRequest", "OutOfRange", "Rounded", "Nearest", "PredictCheckResponse", "ParamSetFromTrain",
    "ParamSetDiscoverChoice", "ParamSetDiscoverRequest", "DiscoverTpl", "DiscoverCad", "DiscoverAssem", "DiscoverProblem",
    "ParamSetDiscoverResponse", "ParamSetPatch", "ParamSetResponsesUpdate",
]


class ParamSetDiscoverChoice(Req):
    """phase3 §13 S8: discover가 돌려준 후보 중 사용자가 고른 것(상대경로). 후보가 1개면 생략 가능.
    phase3 §14.4: `radioss_assem`을 명시적 null로 주면 조립 폴더 없이 메시 단독(mesh_only) 템플릿으로 등록."""

    tpl: str | None = Field(default=None, max_length=400)
    cad: str | None = Field(default=None, max_length=400)
    radioss_assem: str | None = Field(default=None, max_length=400)


class ParamSetCreate(Req):
    path: str = Field(max_length=400)
    # 생략 = 기존 §15.4 폴더 등록(호환). "discover" = 프로젝트 폴더에서 자동 구성(phase3 §13 S8)
    mode: Literal["folder", "discover"] | None = None
    choice: ParamSetDiscoverChoice | None = None
    label: str | None = Field(default=None, max_length=120)


class ParamSetPatch(Req):
    label: str | None = Field(default=None, max_length=120)


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
    # phase3 §14.6: ⑤ OPTIMIZE.responses H3D 형식 {source:"H3D", subcase, datatype, component, layer, stat}. null = 추출 정의 없음
    spec: dict[str, Any] | None = None


class ParamSetResponsesUpdate(Req):
    """phase3 §14.6 `PUT /param-sets/{id}/responses` — 행 `{name, unit, spec|null}`. 검증 실패는 422 RESPONSE_INVALID + problems."""

    responses: list[dict[str, Any]]


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
    starter_name: str | None = None  # mesh_only면 null(phase3 §14.4)
    tpl_params: list[TplParam]
    is_current: bool
    registered_by_name: str
    registered_at: datetime
    origin: str = "FOLDER"
    train_doe_id: str | None = None
    label: str | None = None
    # phase3 §14.4 S9 템플릿 입력 종류: assembly(조립 폴더 포함) | mesh_only(m1 메시 그대로 예측)
    input_kind: Literal["assembly", "mesh_only"] = "assembly"
    assem_rel: str | None = None  # Study 기준 조립 폴더 사본(04_params/<id>/radioss_assem/), mesh_only면 null
    warnings: list[DiscoverProblem] = []  # 등록 응답에만(SIMLAB_EXPORT_NAME 등), 조회는 []


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
    label: str | None = Field(default=None, max_length=120)


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
