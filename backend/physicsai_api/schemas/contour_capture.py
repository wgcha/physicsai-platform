"""API 스키마 — ④ 컨투어 캡처(phase3 §15 S10): 표시 설정·방향별 이미지·동영상 목록·재캡처."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from physicsai_core.stage4_predict.contour_capture import validate_display

from .common import Req, Resp

__all__ = [
    "CaptureView", "CaptureLegend", "CaptureDisplay", "CaptureLegendOut", "CaptureDisplayOut", "ParamSetDisplayUpdate",
    "RecaptureRequest", "BatchCaptureOptions", "MediaFile", "MediaItem", "MediaRecapture", "JobMedia",
]

CaptureView = Literal["iso", "front", "back", "top", "bottom", "left", "right"]


class CaptureLegend(Req):
    mode: Literal["auto", "fixed"] = "auto"
    min: float | None = None
    max: float | None = None


class CaptureDisplay(Req):
    """표시 설정(모든 키 선택 — null = 상위 설정을 따름: config → 응답 정의 첫 항목 → 템플릿 → 작업)."""

    field: str | None = Field(default=None, max_length=64)  # HyperView 결과 필드(예 "Von Mises", "Stress")
    component: str | None = Field(default=None, max_length=64)  # 성분(예 "vonMises", "Mag"), '' = 없음
    avgmode: Literal["", "simple", "maximum", "minimum", "difference"] | None = None
    comps: list[str] | None = Field(default=None, max_length=50)  # 표시할 부품 이름(없으면 전체)
    legend: CaptureLegend | None = None  # fixed = 범례 최소·최대 고정(B 일괄 예측 비교용)
    views: list[CaptureView] | None = Field(default=None, min_length=1, max_length=7)

    @model_validator(mode="after")
    def _semantic(self) -> CaptureDisplay:
        errs = validate_display(self.model_dump(exclude_none=True), loc=())
        if errs:
            e = errs[0]
            where = ".".join(str(x) for x in e["loc"])
            raise ValueError(f"{where}: {e['msg']}" if where else e["msg"])
        return self


class CaptureLegendOut(Resp):
    mode: Literal["auto", "fixed"]
    min: float | None = None
    max: float | None = None


class CaptureDisplayOut(Resp):
    """결정된(최종) 표시 설정."""

    field: str
    component: str = ""
    avgmode: str = ""
    comps: list[str] = []
    legend: CaptureLegendOut
    views: list[str]


class ParamSetDisplayUpdate(Req):
    display: CaptureDisplay | None = None  # null = 템플릿 표시 설정 지움(응답 정의·config 기본을 따름)


class RecaptureRequest(Req):
    views: list[CaptureView] | None = Field(default=None, min_length=1, max_length=7)
    display: CaptureDisplay | None = None

    @model_validator(mode="after")
    def _unique(self) -> RecaptureRequest:
        if self.views and len(set(self.views)) != len(self.views):
            raise ValueError("views: 같은 방향이 두 번 있습니다")
        return self


class BatchCaptureOptions(Req):
    """일괄 예측 캡처 옵션(D3-53) — 하위 PREDICT의 CONTOUR_CAPTURE가 따른다(enabled false → SKIPPED)."""

    enabled: bool = True
    views: list[CaptureView] | None = Field(default=None, min_length=1, max_length=7)  # null = 템플릿 display.views → config
    video: bool | None = None  # null = config capture.video

    @model_validator(mode="after")
    def _unique(self) -> BatchCaptureOptions:
        if self.views and len(set(self.views)) != len(self.views):
            raise ValueError("views: 같은 방향이 두 번 있습니다")
        return self


class MediaFile(Resp):
    artifact_id: str
    content_type: str  # image/png | video/mp4 | video/x-msvideo | image/gif
    size: int
    url: str  # 브라우저 표시용(<img>·<video>, Range 지원)
    download_url: str  # 내려받기(Content-Disposition: attachment)


class MediaItem(Resp):
    view: str
    label: str  # 등각·정면·…
    job_id: str  # 이 파일을 만든 작업(예측 또는 재캡처)
    image: MediaFile
    video: MediaFile | None = None


class MediaRecapture(Resp):
    job_id: str
    state: str
    active: bool


class JobMedia(Resp):
    job_id: str
    # NONE(아직 캡처 전·캡처 step 없음) | SKIPPED(미구성) | OK | PARTIAL | FAILED
    status: str
    message: str | None = None
    display: CaptureDisplayOut | None = None
    field_source: str | None = None  # config | response | template | params
    video_ext: str | None = None
    items: list[MediaItem]
    recapture: MediaRecapture | None = None
    capture_enabled: bool  # /status features.contour_capture와 같은 판정
    can_recapture: bool  # power 이상 + 성공한 PREDICT + 기능 켜짐 + 진행 중 재캡처 없음
