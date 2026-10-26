"""API 스키마 — DOE 표본 형상 그리드 미리보기(doe-preview.md §6.6). `POST /studies/{id}/doe-previews`·`GET`·`POST …/cancel`."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from .common import Req, Resp
from .stage1_train_data import TrainSampling

__all__ = ["DoePreviewSource", "DoePreviewSelect", "DoePreviewReq", "DoePreviewQueue", "DoePreviewTopChange", "DoePreviewGen",
           "DoePreviewCell", "DoePreviewTiming", "DoePreview"]


class DoePreviewSource(Req):
    """표본 행 출처(§5.1). train = ①-3 Native(학습 설정 기준), param_set = 세트 기준(단일 baseline), train_doe = 생성 후 갤러리(doe_id 필수)."""

    kind: Literal["train", "param_set", "train_doe"]
    param_set_id: str | None = Field(default=None, max_length=64)
    doe_id: str | None = Field(default=None, max_length=64)


class DoePreviewSelect(Req):
    """페이지 선택(§5.2). order: change(변화 큰 순, 기본) | doe(doe_no 순) | var(`var` 값 순, desc로 내림). offset은 page_size 배수, limit 생략 = page_size."""

    order: Literal["change", "doe", "var"] = "change"
    var: str | None = Field(default=None, max_length=120)
    desc: bool = False
    offset: int = Field(default=0, ge=0)
    limit: int | None = Field(default=None, ge=1, le=200)


class DoePreviewReq(Req):
    """`TD_DOE_GEN` native params의 표본 부분과 같은 모양(sampling). train_doe 출처는 sampling을 생략(쓰지 않는다)."""

    source: DoePreviewSource
    sampling: TrainSampling | None = None
    select: DoePreviewSelect = Field(default_factory=DoePreviewSelect)


class DoePreviewQueue(Resp):
    lane: str
    position: int | None = None


class DoePreviewTopChange(Resp):
    name: str
    value: float
    rel: float  # (v − nominal)/(max − min)


class DoePreviewGen(Resp):
    """생성 후 갤러리(train_doe)의 실제 생성 결과 — run 폴더 SKIPPED.json·starter 유무로 판정."""

    status: Literal["OK", "SKIPPED", "PENDING"]
    code: str | None = None
    step: str | None = None


class DoePreviewCell(Resp):
    doe_no: int | None = None  # 공칭 셀은 null
    nominal: bool = False
    status: Literal["PENDING", "OK", "FAIL", "ERROR"]
    values: dict[str, float] = Field(default_factory=dict)
    top_changes: list[DoePreviewTopChange] = Field(default_factory=list)  # |rel| 큰 순 3개
    code: str | None = None
    category: str | None = None
    message_ko: str | None = None
    max_disp_mm: float | None = None
    clipped: bool = False
    png_artifact_id: str | None = None
    glb_artifact_id: str | None = None
    manifest_artifact_id: str | None = None
    gen: DoePreviewGen | None = None


class DoePreviewTiming(Resp):
    total_s: float | None = None
    matrix_s: float | None = None
    render_s: float | None = None


class DoePreview(Resp):
    """미리보기 1건(페이지 1개). 200 = 전부 캐시(cache_hit, 작업 없음), 202 = QUEUED·RUNNING(job_id) — 화면은 `GET /doe-previews/{id}`를 1초 간격으로.
    `cells`는 렌더가 끝난 만큼 채워지고(청크마다 갱신) 나머지는 PENDING. `order` = 정렬된 전체 doe_no(행렬 계산 후, 최대 2000개)."""

    id: str
    job_id: str | None = None
    status: Literal["QUEUED", "RUNNING", "DONE", "FAILED", "CANCELED"]
    cache_hit: bool = False
    source: DoePreviewSource | None = None
    select: DoePreviewSelect | None = None
    queue: DoePreviewQueue | None = None  # 대기 중일 때만
    n_total: int | None = None
    n_ok: int | None = None
    n_fail: int | None = None
    n_error: int | None = None
    order: list[int] = Field(default_factory=list)
    tag_state: Literal["none", "tagged"] = "none"
    disp_range_mm: list[float] | None = None
    colormap: str = "turbo16"
    cells: list[DoePreviewCell] = Field(default_factory=list)
    code: str | None = None  # FAILED일 때 첫 실패 코드
    message_ko: str | None = None
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    timing: DoePreviewTiming | None = None
    created_at: Any = None
    finished_at: Any = None
