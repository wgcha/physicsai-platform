"""API 스키마 — ④ 조립 FEM 검증(phase3 §21.3.8 S16). 라우터(routers/fem_verify.py)가 직접 import한다."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Annotated, Any, Literal, Union

from pydantic import Field, field_validator, model_validator

from physicsai_core.stage4_predict.contour_capture import MAX_COMPS, text_problem

from .common import Req, Resp
from .contour_capture import CaptureDisplay, MediaFile
from .jobs import JobSummary

__all__ = ["FvOrigin", "FvSourcePredictJob", "FvSourceBatchRun", "FvSourceValues", "FvSourceOptDesign", "FvAssembly",
           "FvFem", "FvHpc", "FemVerifyCreate", "FvProblem", "FvPreview", "FemVerifyListItem", "FemVerification",
           "FvMediaSide", "FvMediaItem", "FvMedia", "FvCurveSeries", "FvCurves"]


class FvOrigin(Req):
    kind: Literal["optimize"]
    job_id: str | None = None


class FvSourcePredictJob(Req):
    kind: Literal["predict_job"]
    job_id: str


class FvSourceBatchRun(Req):
    kind: Literal["batch_run"]
    batch_id: str
    doe_no: int = Field(ge=1)


class FvSourceValues(Req):
    kind: Literal["values"]
    param_set_id: str
    model_id: str | None = None
    values: dict[str, float]
    reuse_existing: bool = True
    origin: FvOrigin | None = None

    @field_validator("values")
    @classmethod
    def _finite(cls, v: dict[str, float]) -> dict[str, float]:
        for k, x in v.items():
            if not math.isfinite(x):
                raise ValueError(f"{k} 값은 유한해야 합니다")
        return v


class FvSourceOptDesign(Req):
    kind: Literal["opt_design"]
    opt_id: str
    pick: Literal["best", "final_optimum", "surrogate_optimum", "run"]
    iter_no: int | None = Field(default=None, ge=0)
    doe_no: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _run_fields(self) -> FvSourceOptDesign:
        if self.pick == "run" and (self.iter_no is None or self.doe_no is None):
            raise ValueError("pick=run이면 iter_no·doe_no가 필요합니다")
        return self


FvSource = Annotated[Union[FvSourcePredictJob, FvSourceBatchRun, FvSourceValues, FvSourceOptDesign],
                     Field(discriminator="kind")]


class FvAssembly(Req):
    kind: Literal["predict_input", "train_doe", "custom"]
    doe_id: str | None = None
    path: str | None = Field(default=None, max_length=400)

    @model_validator(mode="after")
    def _fields(self) -> FvAssembly:
        if self.kind == "train_doe" and not self.doe_id:
            raise ValueError("train_doe는 doe_id가 필요합니다")
        if self.kind == "custom" and not self.path:
            raise ValueError("custom은 path가 필요합니다")
        return self


def _text_ok(v: str | None, where: str, allow_empty: bool = False) -> None:
    if v is None:
        return
    if (not v.strip() and not (allow_empty and v == "")) or len(v) > 64 or text_problem(v):
        raise ValueError(f"{where}: 1~64자, 따옴표·괄호·$·\\·;·|·제어문자 없음")


class FvFem(Req):
    field: str | None = None  # FEM h3d 결과 이름(없으면 fem_verify.field_map → 예측 필드)
    component: str | None = None
    comps: list[str] | None = Field(default=None, max_length=MAX_COMPS)

    @model_validator(mode="after")
    def _chars(self) -> FvFem:
        _text_ok(self.field, "field")
        _text_ok(self.component, "component", allow_empty=True)
        for i, c in enumerate(self.comps or []):
            _text_ok(c, f"comps.{i}")
        return self


class FvHpc(Req):
    queue: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_.\-@]{1,64}$")
    ncpus: int | None = Field(default=None, ge=1, le=4096)
    walltime: str | None = Field(default=None, pattern=r"^\d{1,4}:\d{2}:\d{2}$")


class FemVerifyCreate(Req):
    source: FvSource
    assembly: FvAssembly | None = None  # null = 기본(예측 입력이 조립 상태면 predict_input, 아니면 최신 READY DOE)
    fem: FvFem | None = None
    display: CaptureDisplay | None = None
    hpc: FvHpc | None = None


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
