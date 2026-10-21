"""API 스키마 — ④ 일괄 예측(DOE)(phase3 §14.5·§14.7 S9): 조합 출처·미리보기·배치 목록·상세·커브·실패만 다시·설계공간 지도(§17.4 S12).
300줄 분할(R-B): 조합 출처·미리보기 요청은 `predict_batch_source`, 설계공간 지도는 `design_map`(여기서 재노출, `__all__` 불변)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from .common import Resp
from .native_vars import VarRow
from .predict_batch_source import (  # noqa: F401 - 기존 경로 재노출
    TABLE_TEXT_MAX_CHARS, BatchSourceLhs, BatchSourceTable, BatchSourceTrainDoe, BatchSourceLhsOpt, BatchSourceSobol,
    BatchSourceFullfact, BatchSourceFracfact, BatchSourcePb, BatchSourceBbd, BatchSourceCcd, BatchSource,
    PredictBatchPreviewRequest,
)
from .design_map import (  # noqa: F401 - 기존 경로 재노출
    DesignMapParameter, DesignMapMetric, DesignMapCurveStats, DesignMapRun, DesignMapCounts, DesignMap,
)

__all__ = [
    "BatchSourceLhs", "BatchSourceTable", "BatchSourceTrainDoe", "BatchSourceLhsOpt", "BatchSourceSobol",
    "BatchSourceFullfact", "BatchSourceFracfact", "BatchSourcePb", "BatchSourceBbd", "BatchSourceCcd", "BatchSource",
    "PredictBatchPreviewRequest", "BatchProblem", "BatchNote", "SamplingInfo", "SamplingSummary", "BatchPreviewRow", "PredictBatchPreview", "PredictBatchSummary", "BatchRef", "BatchModelRef",
    "BatchGenCounts", "BatchPredictCounts", "BatchResponseName", "BatchRunRow", "PredictBatch", "BatchRetryFailed",
    "BatchCurveSeries", "BatchCurves", "DesignMapParameter", "DesignMapMetric", "DesignMapCurveStats", "DesignMapRun",
    "DesignMapCounts", "DesignMap",
]


class BatchProblem(Resp):
    # TABLE_HEADER·TABLE_VALUE·TEXT_TOO_LARGE·TOO_MANY_ROWS·TOO_FEW_ROWS·RANGE_INVALID·DOE_PARAM_MISMATCH
    # + S15: COUNT_NOT_POW2·CONTINUE_INVALID·SEQUENCE_MISMATCH·LEVELS_INVALID·DESIGN_UNSUPPORTED·GENERATOR_UNAVAILABLE
    code: str
    message: str
    row: int | None = None


class BatchNote(Resp):
    """막지 않는 안내(S15 §20.9): FIXED_EXCLUDED·FULL_FACTORIAL_USED·BBD_PAIRWISE·DUPLICATE_ROWS·SEQUENCE_CONTINUED·INFLUENCE_TOO_FEW."""

    code: str
    message: str


class SamplingInfo(Resp):
    """표본 방식 요약(미리보기·배치 상세). 등급은 서버가 정한다(§20.7) — formal | reference(off는 ①만)."""

    kind: str  # lhs_opt | sobol | lhs | fullfact | fracfact | pb | bbd | ccd | table | train_doe
    method: str  # DB source_kind (LHS_OPT …)
    desc_id: str
    label: str
    influence_class: Literal["formal", "reference"]
    influence_note: str | None = None
    recommended_count: int | None = None  # 미리보기만(상세는 null)
    meta: dict[str, Any]  # source_meta(§20.5 각 meta)


class SamplingSummary(Resp):
    """배치 목록 한 줄용(Sobol 이어서 추가 후보·⑤ 출처 라벨)."""

    kind: str
    method: str
    label: str
    count: int
    seed: int | None = None
    offset: int | None = None


class BatchPreviewRow(Resp):
    doe_no: int
    run_key: str
    values: dict[str, float]
    applied_values: dict[str, float]
    out_of_range: list[str]


class PredictBatchPreview(Resp):
    input_kind: Literal["assembly", "mesh_only"]
    count: int
    estimate_min: float | None = None  # 최근 성공 PREDICT 5개 소요 중앙값 × N(분), 없으면 null
    rows: list[BatchPreviewRow]
    problems: list[BatchProblem]
    notes: list[BatchNote] = []  # S15: 막지 않는 안내 + native-vars.md §6.3 경고(VAR_*)·학습 범위 안내
    sampling: SamplingInfo | None = None
    var_rows: list[VarRow] = []  # native-vars.md §6.3: Native 변수 표 초기화(유효 변수, Altair는 빈 목록)
    excluded: list[str] = []


class BatchRef(Resp):
    id: str
    label: str | None = None


class BatchModelRef(Resp):
    id: str
    name: str


class BatchGenCounts(Resp):
    total: int
    done: int
    failed: int
    running: int
    waiting: int


class BatchPredictCounts(Resp):
    running: int
    queued: int
    succeeded: int
    failed: int
    canceled: int


class PredictBatchSummary(Resp):
    id: str
    label: str  # B-003
    status: str  # GENERATING | PREDICTING | DONE | FAILED | CANCELED
    run_count: int
    created_at: datetime
    created_by_name: str
    # D3-53: "실행 목록" 탭 — 템플릿·입력 생성·예측 집계
    param_set: BatchRef | None = None
    gen: BatchGenCounts | None = None
    predict: BatchPredictCounts | None = None
    response_summary: BatchResponseSummary | None = None  # 첫 응답의 완료 run 최소~최대(값 없으면 null)
    sampling: SamplingSummary | None = None  # S15 표본 방식(알 수 없는 kind면 null)


class BatchResponseSummary(Resp):
    name: str
    unit: str = ""
    min: float
    max: float
    count: int  # 값이 있는 완료 run 수


class BatchResponseName(Resp):
    name: str
    unit: str = ""


class BatchRunRow(Resp):
    doe_no: int
    run_key: str
    folder: str
    values: dict[str, float]
    applied_values: dict[str, float]
    out_of_range: list[str]
    # GEN_PENDING | GENERATING | GEN_FAILED | QUEUED | RUNNING | SUCCEEDED | FAILED | CANCELED
    state: str
    code: str | None = None
    message: str | None = None
    gen_category: str | None = None  # geometry-engine.md §7.6: code가 GEOM_*면 §6.5 category(CAD_FAILED·QUALITY 등)
    job_id: str | None = None
    responses: dict[str, float | None] | None = None
    media_views: list[str] = []  # phase3 §15 S10: 컨투어 이미지가 있는 방향(GET /jobs/{job_id}/media)


class PredictBatch(Resp):
    id: str
    label: str
    status: str
    dir: str
    input_kind: Literal["assembly", "mesh_only"]
    source_kind: str  # LHS | LHS_OPT | SOBOL | FULLFACT | FRACFACT | PB | BBD | CCD | TABLE | TRAIN_DOE
    sampling: SamplingInfo | None = None  # S15: 방식·등급(§20.7)·meta
    param_set: BatchRef
    model: BatchModelRef
    job_id: str
    multi_execution: int
    gen: BatchGenCounts
    predict: BatchPredictCounts
    parameters: list[str]
    responses: list[BatchResponseName]
    rows: list[BatchRunRow]
    created_at: datetime
    created_by_name: str
    finished_at: datetime | None = None
    can_cancel: bool = False
    can_retry_failed: bool = False
    vars: dict[str, Any] | None = None  # native-vars.md §6.3: 이 배치가 쓴 Native 변수 정의 스냅숏(없으면 null)


class BatchRetryFailed(Resp):
    parent_job_id: str | None = None
    retried_job_ids: list[str]


class BatchCurveSeries(Resp):
    doe_no: int
    run_key: str
    x: list[float]
    y: list[float]


class BatchCurves(Resp):
    names: list[str]
    name: str | None = None
    truncated: bool
    downsampled: bool
    series: list[BatchCurveSeries]
