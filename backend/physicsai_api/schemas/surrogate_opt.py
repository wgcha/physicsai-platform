"""API 스키마 — ⑤ 플랫폼 내장 최적화(phase3 §18.6 S13): 생성·미리보기 요청, 목록·상세, 이어서 실행 결과."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal, Union

from pydantic import Field

from .common import Req, Resp

__all__ = [
    "SoExploreNew", "SoExploreReuse", "SoExplore", "SoObjective", "SoConstraint", "SurrogateOptCreate", "SoProblem",
    "SurrogateOptPreview", "SurrogateOptSummary", "SoBatchRef", "SoFit", "SoCandidate", "SoIteration", "SoBest", "SoRun",
    "SurrogateOpt", "SurrogateOptResume",
]

METRIC_PATTERN = r"^(curve:(max|min|absmax)|resp:[A-Za-z][A-Za-z0-9_]{0,63}_(MIN|MAX)|tbl:[A-Za-z][A-Za-z0-9_]{0,63})$"


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
    metric: str = Field(max_length=200)
    series: str | None = Field(default=None, max_length=400)
    op: Literal["<=", ">="]
    value: float


class SurrogateOptCreate(Req):
    """생성·미리보기 공용 본문(phase3 §18.6). bounds 생략 = 템플릿 min·max, lo = hi는 고정."""

    param_set_id: str | None = None
    model_id: str | None = None
    explore: SoExplore
    objective: SoObjective
    constraints: list[SoConstraint] = Field(default_factory=list)
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


class SurrogateOptPreview(Resp):
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


class SoFit(Resp):
    kind: str
    n_train: int
    d_free: int
    loo_rmse: float | None = None
    loo_nrmse: float | None = None
    q2: float | None = None
    pred_vs_verified_mae: float | None = None


class SoCandidate(Resp):
    doe_no: int
    values: dict[str, float]
    predicted: float | None = None
    ei: float | None = None
    constraints_pred: list[float] = Field(default_factory=list)
    verified: float | None = None
    state: str | None = None


class SoIteration(Resp):
    iter_no: int
    kind: str
    batch: SoBatchRef | None = None
    fit: SoFit | None = None
    candidates: list[SoCandidate] | None = None
    best_value: float | None = None
    best_feasible: bool | None = None
    improvement_rel: float | None = None


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


class SurrogateOptResume(Resp):
    job_id: str | None = None
    batch_retry: dict[str, Any] | None = None
