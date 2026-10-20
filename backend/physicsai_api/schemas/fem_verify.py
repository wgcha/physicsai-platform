"""API 스키마 — ④ 조립 FEM 검증(phase3 §21.3.8 S16). 라우터(routers/fem_verify.py)가 직접 import한다.
300줄 분할(R-B): 요청(출처·조립·FEM·HPC·생성)은 `fem_verify_req`(여기서 재노출, `__all__` 불변)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from .common import Resp
from .contour_capture import MediaFile
from .jobs import JobSummary
from .fem_verify_req import (  # noqa: F401 - 기존 경로 재노출
    FvOrigin, FvSourcePredictJob, FvSourceBatchRun, FvSourceValues, FvSourceOptDesign, FvSource, FvAssembly, FvFem,
    FvHpc, FemVerifyCreate,
)

__all__ = ["FvOrigin", "FvSourcePredictJob", "FvSourceBatchRun", "FvSourceValues", "FvSourceOptDesign", "FvAssembly",
           "FvFem", "FvHpc", "FemVerifyCreate", "FvProblem", "FvPreview", "FemVerifyListItem", "FemVerification",
           "FvMediaSide", "FvMediaItem", "FvMedia", "FvCurveSeries", "FvCurves"]


class FvProblem(Resp):
    code: str
    message: str


class FvParamSetRef(Resp):
    id: str
    label: str | None = None
    input_kind: str


class FvModelRef(Resp):
    id: str
    name: str
    version: int


class FvDesign(Resp):
    param_set: FvParamSetRef | None = None
    model: FvModelRef | None = None
    values: dict[str, float] = {}
    applied_values: dict[str, float] = {}
    out_of_range: list[str] = []


class FvPredictRef(Resp):
    job_id: str | None = None
    state: str | None = None
    reuse: bool = False
    will_run: bool = False
    companion: bool = False


class FvMeshRef(Resp):
    path: str | None = None
    available: bool = False


class FvAssemblyOut(Resp):
    kind: str
    label: str | None = None
    path: str | None = None
    snapshot_dir: str | None = None
    starter: str | None = None
    rad: list[str] = []
    inc_count: int | None = None
    renum_csv: bool | None = None
    include_baseline: bool | None = None
    include_referenced: bool | None = None
    file_count: int | None = None
    total_bytes: int | None = None


class FvPreview(Resp):
    source_label: str
    design: FvDesign
    predict: FvPredictRef
    input_mode: Literal["reuse", "rebuild"] | None = None
    mesh: FvMeshRef
    assembly: FvAssemblyOut | None = None
    fem_field: str | None = None
    comps_auto: list[str] = []
    hpc_mode: str
    problems: list[FvProblem] = []
    warnings: list[FvProblem] = []


class FvLinks(Resp):
    predict_job_id: str | None = None
    batch_id: str | None = None
    doe_no: int | None = None
    opt_id: str | None = None


class FvSourceOut(Resp):
    kind: str
    label: str


class FemVerifyListItem(Resp):
    id: str
    label: str  # FV-003
    status: str  # WAITING_PREDICT | RUNNING | DONE | FAILED | CANCELED
    source_label: str
    source_kind: str
    links: FvLinks
    values: dict[str, float] = {}
    max_abs_diff_pct: float | None = None
    worst: str | None = None
    created_at: datetime
    created_by_name: str
    finished_at: datetime | None = None


class FvPaths(Resp):
    input_dir: str | None = None
    result_dir: str | None = None
    starter: str | None = None
    remote_dir: str | None = None
    collected: list[str] = []


class FvCompareRow(Resp):
    name: str
    unit: str = ""
    stat: str | None = None
    pred_min: float | None = None
    pred_max: float | None = None
    fem_min: float | None = None
    fem_max: float | None = None
    pred_value: float | None = None
    fem_value: float | None = None
    diff: float | None = None
    diff_pct: float | None = None
    # MIN·MAX 행 각각의 차이(§21.3.6 "MIN·MAX 행 각각도 같은 식") — 화면 구분 MIN/MAX 행용
    min_diff: float | None = None
    min_diff_pct: float | None = None
    max_diff: float | None = None
    max_diff_pct: float | None = None
    note: str | None = None


class FvLegend(Resp):
    mode: str
    min: float | None = None
    max: float | None = None
    source: str | None = None
    note: str | None = None


class FvCurveSummary(Resp):
    status: str
    message: str | None = None
    names: list[str] = []
    unmatched_pred: list[str] = []
    unmatched_fem: list[str] = []


class FvCompare(Resp):
    responses: list[FvCompareRow] = []
    max_abs_diff_pct: float | None = None
    worst: str | None = None
    legend: FvLegend | None = None
    curve: FvCurveSummary | None = None
    media: dict[str, Any] | None = None


class FemVerification(Resp):
    id: str
    label: str
    status: str
    status_text: str
    source: FvSourceOut
    links: FvLinks
    design: FvDesign
    predict: FvPredictRef
    assembly: FvAssemblyOut
    input_mode: str
    attempt_no: int
    dir: str | None = None
    paths: FvPaths
    job: JobSummary | None = None
    compare: FvCompare | None = None
    warnings: list[FvProblem] = []
    failure: FvProblem | None = None
    can_cancel: bool
    can_rerun: bool
    created_at: datetime
    created_by_name: str
    finished_at: datetime | None = None


class FvMediaSide(Resp):
    image: MediaFile
    video: MediaFile | None = None
    video_error: str | None = None


class FvMediaItem(Resp):
    view: str
    label: str
    pred: FvMediaSide | None = None
    fem: FvMediaSide | None = None


class FvMedia(Resp):
    status: str
    display: dict[str, Any] | None = None
    legend: FvLegend | None = None
    items: list[FvMediaItem] = []


class FvCurveSeries(Resp):
    x: list[float]
    y: list[float]


class FvCurves(Resp):
    names: list[str] = []
    name: str | None = None
    pred: FvCurveSeries | None = None
    fem: FvCurveSeries | None = None
    downsampled: bool = False
