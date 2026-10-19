"""API 스키마 — ⑤ 플랫폼 내장 최적화(phase3 §18.6 S13): 생성·미리보기 요청, 목록·상세, 이어서 실행 결과."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal, Union

from pydantic import Field

from .common import Req, Resp

__all__ = [
    "SoExploreNew", "SoExploreReuse", "SoExplore", "SoObjective", "SoConstraint", "SurrogateOptCreate", "SoProblem",
    "SurrogateOptPreview", "SurrogateOptSummary", "SoBatchRef", "SoFit", "SoCandidate", "SoIteration", "SoBest", "SoRun",
    "SurrogateOpt", "SurrogateOptResume", "SoFinalRun", "SoFinal", "SoParameter", "SoObserve", "SoPerformance",
    "SoObjectiveDef", "SoConstraintDef", "SoObserveDef", "SoFrontPoint", "SoPredictedPoint", "SoPareto", "SoHvPoint",
    "SoVerifyPoint", "SurrogateOptVerify", "SurrogateOptVerifyResult", "SoFitObjective",
]

METRIC_PATTERN = (r"^(curve:(max|min|absmax)|resp:[A-Za-z][A-Za-z0-9_]{0,63}_(MIN|MAX)|tbl:[A-Za-z][A-Za-z0-9_]{0,63}"
                  r"|perf:[A-Za-z][A-Za-z0-9_]{0,63})$")


class SoExploreNew(Req):
    """새 DOE(LHS): count 생략 = max(10, 4·자유 변수 수)(상한 predict_batch.max_runs)."""

    kind: Literal["new"]
    count: int | None = None
    seed: int = 1


class SoExploreReuse(Req):
    """완료된 배치 재사용(같은 Study·같은 템플릿·같은 모델·DONE)."""

    kind: Literal["reuse"]
    batch_id: str = Field(max_length=64)


SoExplore = Annotated[Union[SoExploreNew, SoExploreReuse], Field(discriminator="kind")]


class SoObjective(Req):
    metric: str = Field(max_length=200)
    series: str | None = Field(default=None, max_length=400)
    sense: Literal["min", "max"] = "min"


class SoConstraint(Req):
    """제약: `<=`·`>=`는 value, `range`(S17 §22.4.1)는 lo < hi(유한)."""

    metric: str = Field(max_length=200)
    series: str | None = Field(default=None, max_length=400)
    op: Literal["<=", ">=", "range"]
    value: float | None = None
    lo: float | None = None
    hi: float | None = None


class SoObserve(Req):
    """관찰 지표(값만 기록·표시, S17)."""

    metric: str = Field(max_length=200)
    series: str | None = Field(default=None, max_length=400)


class SurrogateOptCreate(Req):
    """생성·미리보기 공용 본문(phase3 §18.6 + S17 §22.4.1). bounds 생략 = 템플릿 min·max, lo = hi는 고정.
    목적은 `objectives`(1~3개) 또는 단수 `objective`(호환) 중 하나."""

    param_set_id: str | None = None
    model_id: str | None = None
    explore: SoExplore
    objective: SoObjective | None = None
    objectives: list[SoObjective] | None = Field(default=None, max_length=10)
    constraints: list[SoConstraint] = Field(default_factory=list, max_length=20)
    observe: list[SoObserve] = Field(default_factory=list, max_length=50)
    weights: list[float] | None = Field(default=None, max_length=10)
    bounds: dict[str, list[float]] | None = None
    surrogate: Literal["gp", "rbf"] | None = None
    iterations: int | None = None
    candidates: int | None = None
    tol_rel: float | None = None
    seed: int = 1
    multi_execution: int = Field(default=1, ge=1, le=64)
    capture: bool = False


class SoProblem(Resp):
    code: str
    field: str | None = None
    message: str
    action: str | None = None  # S17: PERF_MISSING_IN_BATCH → "extract"(화면 "성능 다시 추출")
    batch_id: str | None = None
    performance: str | None = None


class SoPerformance(Resp):
    """미리보기 성능 목록(S17 §22.4.2): available·total·spec_changed는 재사용일 때만."""

    id: str
    name: str
    unit: str = ""
    source: str
    stat: str
    label: str
    available: int | None = None
    total: int | None = None
    spec_changed: int | None = None


class SurrogateOptPreview(Resp):
    mode: str = "single"
    performances: list[SoPerformance] = Field(default_factory=list)
    free_variables: list[str]
    integer_variables: list[str]
    fixed: dict[str, float]
    explore_count: int
    max_total_runs: int
    estimate_min: float | None = None
    objective_available: bool
    problems: list[SoProblem]


class SurrogateOptSummary(Resp):
    id: str
    label: str
    status: str
    objective: dict[str, Any]
    best_value: float | None = None
    iter_no: int
    iterations: int
    created_at: datetime
    created_by_name: str


class SoBatchRef(Resp):
    id: str
    label: str
    status: str
    gen: dict[str, int]
    predict: dict[str, int]


class SoFitObjective(Resp):
    metric: str
    kind: str
    n_train: int
    loo_rmse: float | None = None
    loo_nrmse: float | None = None
    q2: float | None = None
    pred_vs_verified_mae: float | None = None


class SoFit(Resp):
    kind: str
    n_train: int
    d_free: int
    loo_rmse: float | None = None
    loo_nrmse: float | None = None
    q2: float | None = None
    pred_vs_verified_mae: float | None = None
    per_objective: list[SoFitObjective] | None = None  # S17 다목적: 목적별 품질


class SoCandidate(Resp):
    doe_no: int
    values: dict[str, float]
    predicted: float | None = None
    ei: float | None = None
    constraints_pred: list[float] = Field(default_factory=list)
    verified: float | None = None
    state: str | None = None
    role: str | None = None  # S17: hvi | parego | rbf
    weight: list[float] | None = None
    predicted_objectives: list[float] | None = None
    predicted_std: list[float] | None = None
    acq: float | None = None
    verified_objectives: list[float | None] | None = None


class SoIteration(Resp):
    iter_no: int
    kind: str
    batch: SoBatchRef | None = None
    fit: SoFit | None = None
    candidates: list[SoCandidate] | None = None
    best_value: float | None = None
    best_feasible: bool | None = None
    improvement_rel: float | None = None
    hv: float | None = None  # S17 다목적
    front_size: int | None = None


class SoBest(Resp):
    iter_no: int
    batch_id: str | None = None
    batch_label: str
    doe_no: int
    run_key: str
    job_id: str | None = None
    values: dict[str, float]
    objective: float | None = None
    constraints: dict[str, float | None] = Field(default_factory=dict)
    feasible: bool
    objectives: dict[str, float | None] | None = None  # S17 다목적 추천점
    weights: list[float] | None = None
    score: float | None = None


class SoRun(Resp):
    """검증 run 1행(탐색 포함): 수렴 그래프 점·검증 run 표."""

    iter_no: int
    batch_id: str
    batch_label: str
    doe_no: int
    run_key: str
    job_id: str | None = None
    values: dict[str, float]
    objective: float | None = None
    constraints: list[float | None] = Field(default_factory=list)
    predicted: float | None = None
    feasible: bool | None = None
    state: str
    objectives: list[float | None] = Field(default_factory=list)  # S17
    observed: dict[str, float | None] = Field(default_factory=dict)
    reason: str | None = None
    on_front: bool = False
    kind: str | None = None  # EXPLORE | REUSE | VERIFY | EXTRA


class SoFinalRun(Resp):
    """D3-61 마무리 캡처 run(doe 1 = 기준안, 2 = 최적안): 값·목적·제약 확인, 컨투어는 GET /jobs/{job_id}/media."""

    doe_no: int
    job_id: str | None = None
    values: dict[str, float]
    objective: float | None = None
    constraints: list[float | None] = Field(default_factory=list)
    state: str


class SoFinal(Resp):
    status: str | None = None  # PENDING | DONE | FAILED | CANCELED | SKIPPED
    reason: str | None = None
    legend: dict[str, float] | None = None
    legend_note: str | None = None  # 같은 범례 근거 또는 "이미지마다 자동 범례" 사유
    baseline_values: dict[str, float] | None = None
    baseline_predicted: float | None = None
    batch: SoBatchRef | None = None
    baseline: SoFinalRun | None = None
    best: SoFinalRun | None = None


class SoParameter(Resp):
    name: str
    nominal: float | None = None
    min: float
    max: float
    unit: str = ""


class SoObjectiveDef(Resp):
    metric: str
    series: str | None = None
    sense: str
    label: str
    unit: str = ""


class SoConstraintDef(Resp):
    metric: str
    series: str | None = None
    op: str
    value: float | None = None
    lo: float | None = None
    hi: float | None = None
    label: str
    unit: str = ""


class SoObserveDef(Resp):
    metric: str
    series: str | None = None
    label: str
    unit: str = ""


class SoFrontPoint(Resp):
    """검증된 파레토 해 1개(같은 설계 평균, key = 첫 run `"<iter_no>:<doe_no>"`)."""

    key: str
    iter_no: int
    doe_no: int
    run_key: str
    job_id: str | None = None
    batch_label: str
    values: dict[str, float]
    objectives: list[float]
    constraints: dict[str, float | None] = Field(default_factory=dict)
    observed: dict[str, float | None] = Field(default_factory=dict)


class SoPredictedPoint(Resp):
    """대리모델 예측 전선 점(미검증)."""

    values: dict[str, float]
    mean: list[float]
    std: list[float]
    pof: float


class SoPareto(Resp):
    hv: float | None = None
    frame: dict[str, Any] | None = None
    front: list[SoFrontPoint] = Field(default_factory=list)
    recommended_key: str | None = None
    predicted_iter: int | None = None
    predicted: list[SoPredictedPoint] = Field(default_factory=list)


class SoHvPoint(Resp):
    iter_no: int
    hv: float | None = None
    front_size: int | None = None
    improvement_rel: float | None = None


class SurrogateOpt(Resp):
    id: str
    label: str
    status: str
    dir: str
    param_set: dict[str, Any]
    model: dict[str, Any]
    settings: dict[str, Any]
    iter_no: int
    progress_text: str
    iterations: list[SoIteration]
    runs: list[SoRun] = Field(default_factory=list)
    best: SoBest | None = None
    stop_reason: str | None = None
    can_cancel: bool
    can_resume: bool
    warnings: list[dict[str, str]] = Field(default_factory=list)
    current_job_id: str | None = None
    created_at: datetime
    created_by_name: str
    finished_at: datetime | None = None
    final: SoFinal | None = None
    parameters: list[SoParameter] = Field(default_factory=list)
    # S17 §22.10
    mode: str = "single"
    objectives: list[SoObjectiveDef] = Field(default_factory=list)
    constraints_def: list[SoConstraintDef] = Field(default_factory=list)
    observe: list[SoObserveDef] = Field(default_factory=list)
    weights: list[float] = Field(default_factory=list)
    pareto: SoPareto | None = None
    hv_history: list[SoHvPoint] | None = None
    can_verify_more: bool = False


class SurrogateOptResume(Resp):
    job_id: str | None = None
    batch_retry: dict[str, Any] | None = None


class SoVerifyPoint(Req):
    values: dict[str, float]


class SurrogateOptVerify(Req):
    """추가 검증(S17 §22.7): 고른 해(검증·예측 전선 점) 1~max_extra_points개를 최적화 소유 배치(iters EXTRA)로 예측 검증."""

    points: list[SoVerifyPoint] = Field(min_length=1, max_length=50)
    capture: bool = False


class SurrogateOptVerifyResult(Resp):
    batch_id: str
    batch_label: str
    job_id: str
    iter_no: int
