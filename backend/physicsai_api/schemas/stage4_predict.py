"""API 스키마 — ④ 파라미터 세트·샘플·예측 입력 확인, ①→④(§10.4, phase2 §6.13)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, Field, model_serializer

from physicsai_core.naming import label_problem

from .common import Req, Resp
from .geometry import BaselineInfo, NativeInfo


def _check_label(v: str | None) -> str | None:
    """표시 이름 공통 검증(D3-50): 제어·양방향 제어 문자 → 422(INVALID_PARAMS). 서비스 `_label`도 같은 함수로 다시 본다."""
    if v is not None:
        why = label_problem(v)
        if why:
            raise ValueError(why)
    return v


Label = Annotated[str | None, AfterValidator(_check_label)]

__all__ = [
    "ParamSetCreate", "Parameter", "ParamSetParameter", "ResponseDef", "TplParam", "ParamSet", "SampleRow", "SamplesPage",
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
    label: Label = Field(default=None, max_length=120)
    # geometry-engine.md §7.4: native면 202 {job_id}. 생략 = geometry.engine 기본값(mode=discover일 때만 native 가능)
    engine: Literal["altair", "native"] | None = None
    geom_options: dict[str, Any] | None = None
    # geometry-engine.md §11.1 단계 3S: native 쉘 두께 전용 세트(STEP 불필요, tag·update·morph·check 생략). choice.cad 무시
    shell_only: bool = False


class ParamSetPatch(Req):
    label: Label = Field(default=None, max_length=120)
    geom_options: dict[str, Any] | None = None  # native 세트 전용(altair는 422). 전체 덮어쓰기, tag 절이 바뀌면 prep_status STALE


class ParamSetDiscoverRequest(Req):
    path: str = Field(max_length=400)
    tpl: str | None = Field(default=None, max_length=400)
    engine: Literal["altair", "native"] | None = None  # 생략 = geometry.engine 기본값


class DiscoverTpl(Resp):
    rel: str
    name: str
    parameter_count: int
    cad_ref: str | None = None


class DiscoverCad(Resp):
    rel: str
    name: str
    kind: Literal["file", "parts"] | None = None  # native: STEP 파일 | component별 STEP이 든 parts 폴더(altair 응답에는 키 없음)

    @model_serializer(mode="wrap")
    def _drop_empty_kind(self, handler: Any) -> dict[str, Any]:
        d = handler(self)
        if d.get("kind") is None:
            d.pop("kind", None)
        return d


class DiscoverAssem(Resp):
    rel: str
    starter: str
    has_eps_mesh: bool
    has_renum_csv: bool
    file_count: int
    has_baseline_inc: bool | None = None  # native: 기준 메시 존재(없으면 후보에서 제외됨)


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


class ParamSetParameter(Parameter):
    """세트 파라미터 표 행. geometry-engine.md §11.1(3S): 쉘 두께 행 source="prop"·prop_id(형상 행은 null),
    §7.3.8(4B): 확정 공통 변수의 baseline별 대응 {id: {param, nominal, min, max, feasible}|null}."""

    source: Literal["prop"] | None = None
    prop_id: int | None = None
    baselines: dict[str, Any] | None = None


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
    parameters: list[ParamSetParameter]
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
    display: dict[str, Any] | None = None  # phase3 §15 S10 컨투어 표시 설정(PUT /param-sets/{id}/display)
    # geometry-engine.md §7.4: 형상 엔진·세트 덮어쓰기·유효 옵션·paicad 버전·준비본 상태(native만 native 채움)
    engine: Literal["altair", "native"] = "altair"
    geom_options: dict[str, Any] | None = None
    geom_options_effective: dict[str, Any] | None = None
    engine_version: str | None = None
    native: NativeInfo | None = None
    # geometry-engine.md §7.3.8(4B): 다중 baseline 세트만(단일은 null). 첫 항목 = base(세트 자신)
    baselines: list[BaselineInfo] | None = None
    param_map_status: Literal["draft", "confirmed"] | None = None


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
    engine: Literal["altair", "native"] = "altair"
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
