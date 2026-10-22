"""API 스키마 — ④ 단일 예측 실행 목록·상세(phase3 §21.2 S16 V1). 라우터(routers/jobs.py)가 직접 import한다."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from .common import InputKind, Resp

__all__ = ["PredictRunTemplate", "PredictRunModel", "PredictRunResponse", "PredictRunCapture", "PredictRunFailure",
           "PredictRunVerify", "PredictRunSummary", "PredictRunNearest", "PredictRunTableRow", "PredictRunPaths",
           "PredictRunDetail", "PredictRunInputInfo", "PredictRunNote"]


class PredictRunTemplate(Resp):
    id: str
    label: str | None = None
    input_kind: str  # mesh_only | assembly


class PredictRunModel(Resp):
    id: str
    name: str
    version: int


class PredictRunResponse(Resp):
    name: str | None = None
    unit: str = ""
    predicted: float | None = None


class PredictRunCapture(Resp):
    status: str | None = None  # OK | PARTIAL | FAILED | SKIPPED
    views: list[str] = []


class PredictRunFailure(Resp):
    code: str
    message: str = ""


class PredictRunVerify(Resp):
    """기존 PREDICT_VERIFY 요약(이 예측을 가리키는 최신 1건)."""

    job_id: str
    state: str


class PredictRunSummary(Resp):
    job_id: str  # 재시도 묶음의 최신 시도
    root_job_id: str  # 폴더 04_predict/<root>
    attempts: int  # 재시도 사슬 길이(최대 50)
    state: str
    origin: Literal["manual", "fem_verify"]
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_s: int | None = None
    created_by_name: str
    input_mode: Literal["template", "prepared"]
    input: InputKind = "assembly"  # input-kind.md IK-10: 이 실행의 입력 종류(prepared = starter가 eps_mesh면 cushion)
    template: PredictRunTemplate | None = None  # prepared + 세트 없음 = null
    model: PredictRunModel | None = None
    values: dict[str, float] = {}
    applied_values: dict[str, float] = {}
    out_of_range: list[str] = []
    input_path: str | None = None  # prepared 입력 경로
    starter: str | None = None
    responses: list[PredictRunResponse] = []  # 응답 표 앞쪽 최대 5개
    capture: PredictRunCapture | None = None  # 캡처 없음 = null
    has_curve: bool = False
    warnings_count: int = 0
    failure: PredictRunFailure | None = None  # 실패·취소·중단 시
    verify: PredictRunVerify | None = None  # 기존 PREDICT_VERIFY만(FEM 검증은 별도 API)


class PredictRunNearest(Resp):
    run_key: str | None = None
    distance: float | None = None


class PredictRunTableRow(Resp):
    name: str | None = None
    unit: str | None = None
    predicted: float | None = None
    nearest_measured: float | None = None
    diff_pct: float | None = None


class PredictRunPaths(Resp):
    """표시용 절대경로(OS 표기). 폴더·파일이 없으면(정리로 _backup에 옮겨짐 등) null."""

    dir: str | None = None
    input_dir: str | None = None
    result_dir: str | None = None
    pred_h3d: str | None = None
    media_dir: str | None = None
    geom_dir: str | None = None


class PredictRunInputInfo(Resp):
    """예측에 넣은 입력 요약(워커 `result.predict_input`, 수치만): 쿠션 = 파일 1개."""

    input: InputKind | None = None
    starter: str | None = None
    bytes: int | None = None
    files: int | None = None


class PredictRunNote(Resp):
    code: str
    message: str


class PredictRunDetail(PredictRunSummary):
    nearest: PredictRunNearest | None = None
    response_table: list[PredictRunTableRow] = []
    paths: PredictRunPaths
    display: dict | None = None  # result.capture.display(결정된 표시 설정)
    predict_input: PredictRunInputInfo | None = None  # input-kind.md §4.1: P/INPUT 요약(워커가 기록한 때만)
    input_warnings: list[PredictRunNote] = []  # 쿠션 입력에서 값이 없는 응답만(INPUT_CUSHION_RESPONSES, 차단 없음)
