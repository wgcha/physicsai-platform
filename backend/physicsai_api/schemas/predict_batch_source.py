"""API 스키마 — ④ 일괄 예측 조합 출처(S9 3종 + S15 표본 방식 7종)·미리보기 요청 — predict_batch에서 재노출."""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import Field

from .common import Req
from .native_vars import VarsEdit

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


# ---- S15 표본 방식 7종(phase3 §20.6, D3-63) — ranges는 {이름: [최소, 최대]}(생략 = 세트 min·max)


class BatchSourceLhsOpt(Req):
    """최적화 LHS: count 2~predict_batch.max_runs, seed 0 이상(기본 1), criterion maximin(최소 거리, 기본) | corr(상관 최소)."""

    kind: Literal["lhs_opt"]
    count: int
    seed: int = Field(default=1, ge=0)
    ranges: dict[str, list[float]] | None = None
    criterion: Literal["maximin", "corr"] = "maximin"


class BatchSourceSobol(Req):
    """Sobol(스크램블): count = 2^m(4~max_runs), seed 0~4294967295(생략 = 1), continue_from = 이전 Sobol 배치 id(이어서 추가 —
    seed·ranges는 생략하고 이전 값을 쓴다)."""

    kind: Literal["sobol"]
    count: int
    seed: int | None = Field(default=None, ge=0, le=4294967295)
    ranges: dict[str, list[float]] | None = None
    continue_from: str | None = Field(default=None, max_length=64)


class BatchSourceFullfact(Req):
    """전체 요인: levels {변수: 수준 수 1~10}(생략한 활성 변수 = 2; 2~10 검사와 정수 변수 검사는 problems)."""

    kind: Literal["fullfact"]
    levels: dict[str, Annotated[int, Field(ge=1, le=10)]] | None = None
    ranges: dict[str, list[float]] | None = None


class BatchSourceFracfact(Req):
    """부분 요인 2수준: resolution 4 | 5(기본 5)."""

    kind: Literal["fracfact"]
    resolution: Literal[4, 5] = 5
    ranges: dict[str, list[float]] | None = None


class BatchSourcePb(Req):
    """Plackett–Burman(2수준 선별)."""

    kind: Literal["pb"]
    ranges: dict[str, list[float]] | None = None


class BatchSourceBbd(Req):
    """Box–Behnken(변수 3개 이상, 중심점 1개)."""

    kind: Literal["bbd"]
    ranges: dict[str, list[float]] | None = None


class BatchSourceCcd(Req):
    """중심 합성: alpha face(면중심, 기본) | inscribed(내접). 중심점 1개."""

    kind: Literal["ccd"]
    alpha: Literal["face", "inscribed"] = "face"
    ranges: dict[str, list[float]] | None = None


BatchSource = Annotated[
    Union[BatchSourceLhs, BatchSourceLhsOpt, BatchSourceSobol, BatchSourceFullfact, BatchSourceFracfact, BatchSourcePb,
          BatchSourceBbd, BatchSourceCcd, BatchSourceTable, BatchSourceTrainDoe],
    Field(discriminator="kind")]


class PredictBatchPreviewRequest(Req):
    param_set_id: str | None = None  # 생략 = 현재 세트
    source: BatchSource
    # native-vars.md §6.3: 학습 범위(경고·out_of_range)는 이 모델 기준(생략 = Final 모델), vars = Native 변수 그 자리 편집
    model_id: str | None = None
    vars: VarsEdit | None = None
