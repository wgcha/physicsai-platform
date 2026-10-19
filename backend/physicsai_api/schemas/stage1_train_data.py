"""API 스키마 — ① 학습데이터 생성: 파라미터 표·tpl·DOE·run(phase2 §12.5~§12.7)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal, Union

from pydantic import Field

from .common import Req, Resp
from .stage4_predict import TplParam

__all__ = [
    "TrainParamOut", "TrainParamUpdate", "TrainParamsPut", "VersionBody", "TrainCad", "TrainTpl", "TrainSetup",
    "DoeField", "DoeType", "RunStateCounts", "TrainDoe", "TrainRunHpc", "TrainRunResult", "TrainRun",
    "DoeResultParameter", "DoeResultResponse", "DoeResultMeta", "DoeResultRow", "DoeResultCounts", "DoeResultSampling", "DoeResultTable",
    "TrainSampling", "TrainDoeSampling", "TrainDoeGenCounts",
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
    engine: Literal["altair", "native"] = "altair"  # geometry-engine.md §7.3.1
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
    desc_id: str | None = None  # S15 설명 id(hs_lhs·hs_sobol·hs_fullfact·hs_fracfact, 그 밖 null = 일반 문구)
    recommended: bool = False  # value == train_data.recommended_doe_type인 항목 하나
    influence_class: Literal["formal", "reference"] = "reference"  # ⑤ 영향도 등급(§20.7)


class RunStateCounts(Resp):
    GENERATED: int = 0
    SUBMITTED: int = 0
    SOLVED: int = 0
    SOLVE_FAILED: int = 0
    COLLECTED: int = 0
    COLLECT_FAILED: int = 0


# ---- S18 ① 플랫폼 DOE 표본(phase3 §23.4) — 범위는 ①-2 표(ranges·continue_from 없음), 추가 키 금지 ----------------------


class TrainSamplingLhs(Req):
    kind: Literal["lhs"]
    count: int = Field(ge=2)
    seed: int = Field(default=1, ge=0)


class TrainSamplingLhsOpt(Req):
    kind: Literal["lhs_opt"]
    count: int = Field(ge=2)
    seed: int = Field(default=1, ge=0)
    criterion: Literal["maximin", "corr"] = "maximin"


class TrainSamplingSobol(Req):
    kind: Literal["sobol"]
    count: int = Field(ge=4)
    seed: int = Field(default=1, ge=0, le=4294967295)


class TrainSamplingFullfact(Req):
    """levels {변수: 수준 수 1~10}(생략한 변수 = 2)."""

    kind: Literal["fullfact"]
    levels: dict[str, Annotated[int, Field(ge=1, le=10)]] = Field(default_factory=dict)


class TrainSamplingFracfact(Req):
    kind: Literal["fracfact"]
    resolution: Literal[4, 5] = 5


class TrainSamplingPb(Req):
    kind: Literal["pb"]


class TrainSamplingBbd(Req):
    kind: Literal["bbd"]


class TrainSamplingCcd(Req):
    kind: Literal["ccd"]
    alpha: Literal["face", "inscribed"] = "face"


TrainSampling = Annotated[
    Union[TrainSamplingLhs, TrainSamplingLhsOpt, TrainSamplingSobol, TrainSamplingFullfact, TrainSamplingFracfact,
          TrainSamplingPb, TrainSamplingBbd, TrainSamplingCcd],
    Field(discriminator="kind")]


class TrainDoeSampling(Resp):
    """플랫폼 DOE 표본 방식(§23.4): kind·표시 이름·설명 id(td_<kind>)·meta(DG_PREP 전 null)."""

    kind: str
    label: str
    desc_id: str
    meta: dict[str, Any] | None = None


class TrainDoeGenCounts(Resp):
    """플랫폼 DOE run별 입력 생성 상태 집계(train_doe_points)."""

    total: int
    pending: int
    running: int
    done: int
    failed: int


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
    engine: Literal["altair", "native"] = "altair"
    engine_version: str | None = None
    collected_count: int
    solve_failed_count: int
    has_run_responses: bool
    dir_display_path: str | None = None
    results_display_path: str | None = None
    created_by_name: str
    created_at: datetime
    run_state_counts: RunStateCounts
    generator: Literal["platform", "hyperstudy"] = "hyperstudy"  # S18 생성 방식(§23.4)
    sampling: TrainDoeSampling | None = None  # platform만
    gen: TrainDoeGenCounts | None = None  # platform만(run별 생성 상태 집계)


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


class DoeResultParameter(Resp):
    name: str
    integer: bool
    min: float | None = None
    max: float | None = None
    unit: str | None = None


class DoeResultResponse(Resp):
    name: str
    unit: str | None = None


class DoeResultMeta(Resp):
    engine_version: str | None = None
    baseline_id: str | None = None
    scene: str | None = None


class DoeResultRow(Resp):
    run_id: str
    no: int
    state: str  # train_runs.state 그대로(GENERATED·SUBMITTED·SOLVED·SOLVE_FAILED·COLLECTED·COLLECT_FAILED)
    params: dict[str, float | None]
    responses: dict[str, float | None]


class DoeResultCounts(Resp):
    total: int
    usable: int
    no_response: int


class DoeResultSampling(Resp):
    """① DOE 표본 방식(S15 §20.6): 정의 파일 유형 value·라벨·설명 id·옵션(RESOLUTION 등)."""

    method: str
    label: str
    desc_id: str | None = None
    options: dict[str, Any] = {}


class DoeResultTable(Resp):
    """⑤ 결과분석 입력(s14_analysis.md §19.5): 해석 DOE의 run별 파라미터 + 응답. 읽기 전용."""

    doe_id: str
    label: str
    study_id: str
    type: str
    parameters: list[DoeResultParameter]
    responses: list[DoeResultResponse]
    meta: DoeResultMeta
    rows: list[DoeResultRow]
    counts: DoeResultCounts
    sampling: DoeResultSampling
    influence_class: Literal["formal", "reference", "off"]  # §20.7: 서버가 정함
    influence_note: str | None = None  # reference·off 문구(formal은 null)
    influence_ok: bool  # = influence_class != "off"
    notes: list[str]
