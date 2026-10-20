"""API 스키마 — ⑤ 플랫폼 내장 최적화(phase3 §18.6 S13): 생성·미리보기 요청, 목록·상세, 이어서 실행 결과.
300줄 분할(R-B): 요청은 `surrogate_opt_req`, 반복·적합·후보·최선·최종 결과는 `surrogate_opt_iter`(여기서 재노출, `__all__` 불변)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from .common import Resp
from .surrogate_opt_req import (  # noqa: F401 - 기존 경로 재노출
    METRIC_PATTERN, SoExploreNew, SoExploreReuse, SoExplore, SoObjective, SoConstraint, SoObserve, SurrogateOptCreate,
    SoVerifyPoint, SurrogateOptVerify,
)
from .surrogate_opt_iter import (  # noqa: F401 - 기존 경로 재노출
    SoProblem, SoPerformance, SurrogateOptPreview, SurrogateOptSummary, SoBatchRef, SoFitObjective, SoFit, SoCandidate,
    SoIteration, SoBest, SoRun, SoFinalRun, SoFinal,
)

__all__ = [
    "SoExploreNew", "SoExploreReuse", "SoExplore", "SoObjective", "SoConstraint", "SurrogateOptCreate", "SoProblem",
    "SurrogateOptPreview", "SurrogateOptSummary", "SoBatchRef", "SoFit", "SoCandidate", "SoIteration", "SoBest", "SoRun",
    "SurrogateOpt", "SurrogateOptResume", "SoFinalRun", "SoFinal", "SoParameter", "SoObserve", "SoPerformance",
    "SoObjectiveDef", "SoConstraintDef", "SoObserveDef", "SoFrontPoint", "SoPredictedPoint", "SoPareto", "SoHvPoint",
    "SoVerifyPoint", "SurrogateOptVerify", "SurrogateOptVerifyResult", "SoFitObjective",
]


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
    baseline: str | None = None  # opt-native §7
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


class SurrogateOptVerifyResult(Resp):
    batch_id: str
    batch_label: str
    job_id: str
    iter_no: int
