"""API 스키마 — ④ 일괄 예측(DOE)(phase3 §14.5·§14.7 S9): 조합 출처·미리보기·배치 목록·상세·커브·실패만 다시."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Union

from pydantic import Field

from .common import Req, Resp

__all__ = [
    "BatchSourceLhs", "BatchSourceTable", "BatchSourceTrainDoe", "BatchSource", "PredictBatchPreviewRequest",
    "BatchProblem", "BatchPreviewRow", "PredictBatchPreview", "PredictBatchSummary", "BatchRef", "BatchModelRef",
    "BatchGenCounts", "BatchPredictCounts", "BatchResponseName", "BatchRunRow", "PredictBatch", "BatchRetryFailed",
    "BatchCurveSeries", "BatchCurves",
]

TABLE_TEXT_MAX_CHARS = 16_777_216  # 모양 상한(요청 크기 방어). 실제 상한은 predict_batch.table_max_bytes(TEXT_TOO_LARGE)


class BatchSourceLhs(Req):
    """범위·개수 LHS: count 2~predict_batch.max_runs, seed 정수(기본 1), ranges {이름: [최소, 최대]}(생략 = 세트 min·max)."""

    kind: Literal["lhs"]
    count: int
    seed: int = 1
    ranges: dict[str, list[float]] | None = None


class BatchSourceTable(Req):
    """표 붙여넣기·CSV 내용(탭/쉼표 자동, BOM 허용, 첫 줄 헤더 = 파라미터 이름 전부, 선택 열 doe 무시)."""

    kind: Literal["table"]
    text: str = Field(max_length=TABLE_TEXT_MAX_CHARS)


class BatchSourceTrainDoe(Req):
    """① 학습 DOE(같은 Study, READY, sample_status PARSED/PARTIAL)의 samples.csv 행 전부."""

    kind: Literal["train_doe"]
    doe_id: str = Field(max_length=64)


BatchSource = Annotated[Union[BatchSourceLhs, BatchSourceTable, BatchSourceTrainDoe], Field(discriminator="kind")]


class PredictBatchPreviewRequest(Req):
    param_set_id: str | None = None  # 생략 = 현재 세트
    source: BatchSource


class BatchProblem(Resp):
    code: str  # TABLE_HEADER·TABLE_VALUE·TEXT_TOO_LARGE·TOO_MANY_ROWS·TOO_FEW_ROWS·RANGE_INVALID·DOE_PARAM_MISMATCH
    message: str
    row: int | None = None


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


class PredictBatchSummary(Resp):
    id: str
    label: str  # B-003
    status: str  # GENERATING | PREDICTING | DONE | FAILED | CANCELED
    run_count: int
    created_at: datetime
    created_by_name: str


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
    job_id: str | None = None
    responses: dict[str, float | None] | None = None
    media_views: list[str] = []  # phase3 §15 S10: 컨투어 이미지가 있는 방향(GET /jobs/{job_id}/media)


class PredictBatch(Resp):
    id: str
    label: str
    status: str
    dir: str
    input_kind: Literal["assembly", "mesh_only"]
    source_kind: str  # LHS | TABLE | TRAIN_DOE
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
