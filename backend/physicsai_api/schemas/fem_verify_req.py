"""API 스키마 — ④ 조립 FEM 검증 요청(출처 4종·조립·FEM·HPC·생성) — fem_verify에서 재노출."""

from __future__ import annotations

import math
from typing import Annotated, Literal, Union

from pydantic import Field, field_validator, model_validator

from physicsai_core.stage4_predict.contour_capture import MAX_COMPS, text_problem

from .common import HpcVersion, Req
from .contour_capture import CaptureDisplay


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
    version: HpcVersion = None  # D3-68: SCX Radioss 버전(null = hpc.scx.version, command 모드는 무시)


class FemVerifyCreate(Req):
    source: FvSource
    assembly: FvAssembly | None = None  # null = 기본(예측 입력이 조립 상태면 predict_input, 아니면 최신 READY DOE)
    fem: FvFem | None = None
    display: CaptureDisplay | None = None
    hpc: FvHpc | None = None
