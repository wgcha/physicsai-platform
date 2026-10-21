"""API 스키마 — ⑤ 플랫폼 내장 최적화 응답 중 문제·성능·미리보기·목록·반복(적합·후보)·최선·run·최종 결과 — surrogate_opt에서 재노출."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from .common import Resp
from .native_vars import VarNote, VarRow


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
    # opt-native §8
    algorithm: str = "ego"
    algo_options: dict[str, Any] = Field(default_factory=dict)
    verification: str = "loop"
    variables_kind: dict[str, str] = Field(default_factory=dict)
    levels: dict[str, list[str]] | None = None
    # native-vars.md §6.2: Native 템플릿만 채워진다(Altair는 빈 목록). var_notes = 경고({code,name,message})·안내(name 없음)
    var_notes: list[VarNote] = Field(default_factory=list)
    var_rows: list[VarRow] = Field(default_factory=list)
    excluded: list[str] = Field(default_factory=list)


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
    algo: dict[str, Any] | None = None  # opt-native §6.6 {name, pop_size, generations, generations_run, evals, stop, seed, …}


class SoCandidate(Resp):
    doe_no: int
    values: dict[str, float]
    baseline: str | None = None  # opt-native §7: 다중 baseline 위상 세트의 범주 수준(baseline id), N/A 변수는 values에서 빠짐
    predicted: float | None = None
    ei: float | None = None
    constraints_pred: list[float] = Field(default_factory=list)
    verified: float | None = None
    state: str | None = None
    role: str | None = None  # S17: hvi | parego | rbf, opt-native: ga | ga_ei | ga_div | nsga2
    weight: list[float] | None = None
    predicted_objectives: list[float] | None = None
    predicted_std: list[float] | None = None
    acq: float | None = None
    verified_objectives: list[float | None] | None = None
    pof: float | None = None  # opt-native V-ON-8: GA·NSGA-II 후보 예측 만족 확률·위반량(정규화)
    cv: float | None = None


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
