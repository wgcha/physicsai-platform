"""API 스키마 — Native 템플릿 변수 정의(선택·범위)(native-vars.md §6): 세트 정의 조회·저장, 실행 그 자리 편집 `vars`, 미리보기 표·경고."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from .common import Req, Resp

__all__ = ["VarsEdit", "NativeVarItem", "NativeVarsUpdate", "VarRange", "VarFeasible", "VarNote", "NativeVarPoolRow",
           "NativeVarHistory", "NativeVars", "VarRow"]

MAX_VARS = 300  # 풀 크기 상한(실물 수십~백여 개) — 요청 본문 크기 방어


class VarsEdit(Req):
    """⑥ 내장 최적화·④ 일괄 예측 요청의 선택 필드 `vars`: 그 실행에만 적용(세트 정의는 안 바뀜).
    유효 변수 = (세트 정의 − exclude) + add. Native 템플릿(단일 baseline)만 — Altair는 422 NATIVE_VARS_UNSUPPORTED."""

    add: list[str] | None = Field(default=None, max_length=MAX_VARS, description="세트 정의에 없는 풀 변수를 이 실행에 추가(범위 = 피처 기본 범위)")
    exclude: list[str] | None = Field(default=None, max_length=MAX_VARS, description="세트 정의 변수를 이 실행에서 제외(공칭 유지, 결과 표에 없음)")


class NativeVarItem(Req):
    name: str = Field(max_length=64)
    min: float
    max: float


class NativeVarsUpdate(Req):
    """PUT /param-sets/{id}/variables: 형상 행 전체 교체. base_revision = 불러온 시점의 리비전(다르면 409)."""

    base_revision: int = Field(ge=0)
    variables: list[NativeVarItem] = Field(max_length=MAX_VARS)


class VarRange(Resp):
    min: float
    max: float


class VarFeasible(Resp):
    min: float | None = None
    max: float | None = None
    source: str | None = None  # estimate | envelope


class VarNote(Resp):
    """경고·안내: 경고는 name 있음(VAR_*), 안내(TRAIN_RANGE_*·VARS_FROM_DOE)는 name 없음."""

    code: str
    name: str | None = None
    message: str


class NativeVarPoolRow(Resp):
    name: str
    type: str = ""
    body: str = ""
    nominal: float
    unit: str = "mm"
    position: bool = False
    default_range: VarRange
    feasible: VarFeasible | None = None
    ref_locked: bool = False
    group: str | None = None
    train: VarRange | None = None  # model_id를 줬고 학습 범위를 알 때만


class NativeVarHistory(Resp):
    revision: int
    saved_at: str | None = None
    saved_by_name: str | None = None
    count: int = 0


class NativeVars(Resp):
    """세트 변수 정의(현재 리비전). `variables` = 선택한 형상 행(풀 순서), `pool` = 고를 수 있는 전체 변수. PUT 응답은 `warnings`가 채워진다."""

    revision: int
    features_sha256: str | None = None
    editable: bool
    reason: str | None = None
    variables: list[NativeVarItem]
    pool: list[NativeVarPoolRow]
    stale_names: list[str] = Field(default_factory=list)
    train_source: dict[str, Any] | None = None
    notes: list[VarNote] = Field(default_factory=list)
    warnings: list[VarNote] = Field(default_factory=list)
    history: list[NativeVarHistory] = Field(default_factory=list)


class VarRow(Resp):
    """미리보기 표 초기화 행(⑥ `var_rows`·④ 일괄 `var_rows`): 유효 변수 1개의 기준 범위·학습 범위·모핑 가능 범위."""

    name: str
    origin: str  # set | added
    nominal: float | None = None
    base: VarRange  # 기준 범위(세트 정의, 추가 변수는 피처 기본 범위)
    train: VarRange | None = None
    feasible: VarFeasible | None = None
    unit: str = ""
    position: bool = False
