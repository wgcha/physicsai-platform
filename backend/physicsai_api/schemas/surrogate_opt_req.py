"""API 스키마 — ⑤ 플랫폼 내장 최적화 요청(생성·탐색·목적·제약·관찰·검증 요청) — surrogate_opt에서 재노출."""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import Field

from .common import InputKind, Req
from .native_vars import VarsEdit

METRIC_PATTERN = (r"^(curve:(max|min|absmax)|resp:[A-Za-z][A-Za-z0-9_]{0,63}_(MIN|MAX)|tbl:[A-Za-z][A-Za-z0-9_]{0,63}"
                  r"|perf:[A-Za-z][A-Za-z0-9_]{0,63})$")


class SoExploreNew(Req):
    """새 DOE(LHS): count 생략 = max(10, 4·자유 변수 수)(상한 predict_batch.max_runs)."""

    kind: Literal["new"]
    count: int | None = None
    seed: int = 1


class SoExploreReuse(Req):
    """완료된 배치 재사용(같은 Study·같은 템플릿·같은 모델·DONE)."""

    kind: Literal["reuse"]
    batch_id: str = Field(max_length=64)


SoExplore = Annotated[Union[SoExploreNew, SoExploreReuse], Field(discriminator="kind")]


class SoObjective(Req):
    metric: str = Field(max_length=200)
    series: str | None = Field(default=None, max_length=400)
    # opt-native ON-C4: 방향은 사용자가 고른다(기본값 없음 — 비면 422 OPT_CRITERIA_REQUIRED)
    sense: Literal["min", "max"] | None = Field(default=None, description="min | max — 필수(생략 시 422 OPT_CRITERIA_REQUIRED)")


class SoConstraint(Req):
    """제약: `<=`·`>=`는 value, `range`(S17 §22.4.1)는 lo < hi(유한)."""

    metric: str = Field(max_length=200)
    series: str | None = Field(default=None, max_length=400)
    op: Literal["<=", ">=", "range"]
    value: float | None = None
    lo: float | None = None
    hi: float | None = None


class SoObserve(Req):
    """관찰 지표(값만 기록·표시, S17)."""

    metric: str = Field(max_length=200)
    series: str | None = Field(default=None, max_length=400)


class SurrogateOptCreate(Req):
    """생성·미리보기 공용 본문(phase3 §18.6 + S17 §22.4.1). bounds 생략 = 템플릿 min·max, lo = hi는 고정.
    목적은 `objectives`(1~3개) 또는 단수 `objective`(호환) 중 하나."""

    param_set_id: str | None = None
    model_id: str | None = None
    explore: SoExplore
    objective: SoObjective | None = None
    objectives: list[SoObjective] | None = Field(default=None, max_length=10)
    constraints: list[SoConstraint] = Field(default_factory=list, max_length=20)
    observe: list[SoObserve] = Field(default_factory=list, max_length=50)
    weights: list[float] | None = Field(default=None, max_length=10,
                                        description="목적 2개 이상이면 필수(사용자 입력, 생략 시 422 OPT_CRITERIA_REQUIRED)")
    bounds: dict[str, list[float]] | None = None
    surrogate: Literal["gp", "rbf"] | None = None
    iterations: int | None = None
    candidates: int | None = None
    tol_rel: float | None = None
    seed: int = 1
    multi_execution: int = Field(default=1, ge=1, le=64)
    capture: bool = False
    # opt-native §8: 알고리즘·고급 옵션·검증 방식·범주 수준(모두 선택 — 생략 = ego·기본·loop)
    algorithm: str | None = Field(default=None, max_length=16, description="ego(기본) | ga(단일 목적) | nsga2(다목적)")
    algo_options: dict[str, Any] | None = Field(
        default=None, description="GA·NSGA-II 고급 옵션 {pop_size, generations, crossover_prob, mutation_prob, eta_c, eta_m}"
                                  "(null·생략 = 기본). ego면 비워야 한다")
    verification: str | None = Field(default=None, max_length=16, description="loop(기본, 반복 검증) | none(대리모델만)")
    levels: dict[str, list[str]] | None = Field(default=None, description="범주 수준 제한 {\"baseline\": [id…]}(다중 baseline 위상 세트만)")
    vars: VarsEdit | None = Field(default=None, description="템플릿 변수 그 자리 편집 {add, exclude}(이 실행에만 적용, 세트 정의는 안 바뀜). Native와 Altair 전체 tpl 템플릿, Altair 부분 tpl은 422 TPL_SCOPE_PARTIAL")
    input: InputKind | None = Field(default=None, description="예측 입력 종류 assembly(조립) | cushion(쿠션 rad만 — GPU 메모리 적음). 생략 = 템플릿이 조립 가능하면 assembly, 쿠션만 가능하면 cushion. 능력 밖이면 422 INPUT_KIND_UNSUPPORTED")


class SoVerifyPoint(Req):
    values: dict[str, float]


class SurrogateOptVerify(Req):
    """추가 검증(S17 §22.7): 고른 해(검증·예측 전선 점) 1~max_extra_points개를 최적화 소유 배치(iters EXTRA)로 예측 검증."""

    points: list[SoVerifyPoint] = Field(min_length=1, max_length=50)
    capture: bool = False
