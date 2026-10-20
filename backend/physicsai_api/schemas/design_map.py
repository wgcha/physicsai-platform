"""API 스키마 — S12 설계공간 지도(phase3 §17.4, D3-59) — predict_batch에서 재노출."""

from __future__ import annotations

from typing import ClassVar

from pydantic import SerializerFunctionWrapHandler, model_serializer

from .common import Resp

# ---- S12 설계공간 지도(phase3 §17.4, D3-59) ----------------------------------------------------------


class DesignMapParameter(Resp):
    name: str
    integer: bool  # tpl 형식 %Ni/%Nd
    min: float  # 템플릿 범위
    max: float


class _OmitUnset(Resp):
    """`OMIT_UNSET` 필드는 서비스가 넣지 않았으면 응답에서 뺀다(S19 §24.5 — 기존 응답 키·값 불변, 없음 = 기본값)."""

    OMIT_UNSET: ClassVar[tuple[str, ...]] = ()

    @model_serializer(mode="wrap")
    def _omit_unset(self, handler: SerializerFunctionWrapHandler):  # 반환 주석 없음 = OpenAPI 모양 유지
        d = handler(self)
        if isinstance(d, dict):
            for k in self.OMIT_UNSET:
                if k not in self.model_fields_set:
                    d.pop(k, None)
        return d


class DesignMapMetric(_OmitUnset):
    id: str  # §17.2 지표 id(curve:max|min|absmax, resp:<NAME>_MIN|_MAX, tbl:<name>, perf:<NAME>)
    label: str
    unit: str | None = None
    needs_series: bool
    spec_changed: int | None = None  # perf 지표만: 성공 run 중 SPEC_CHANGED 수(S19 §24.5)

    OMIT_UNSET: ClassVar[tuple[str, ...]] = ("spec_changed",)


class DesignMapCurveStats(Resp):
    max: float
    min: float
    absmax: float
    x_at_max: float
    x_at_min: float
    n: int


class DesignMapRun(Resp):
    doe_no: int
    run_key: str
    state: str  # §14.7 결과 표 상태 그대로
    values: dict[str, float]  # 반영값(applied_values)
    curve: dict[str, DesignMapCurveStats] | None = None  # 성공 run만(curve.json 없음·너무 큼 = null)
    resp: dict[str, float] | None = None  # 성공 run만(RESPONSES.txt 없음 = null)
    tbl: dict[str, float | None] | None = None  # 성공 run만(결과 표 값)
    perf: dict[str, float | None] | None = None  # 성공 run만: 성능 값(`performance.perf_value`, S19 §24.5)
    perf_reason: dict[str, str] | None = None  # 성공 run만: 값 null인 성능의 사유 코드(reason_text 키)


class DesignMapCounts(_OmitUnset):
    total: int
    succeeded: int
    no_curve: int  # 성공 run 중 커브 없음
    no_resp: int  # 성공 run 중 RESPONSES.txt 없음
    spec_changed: int = 0  # SPEC_CHANGED 성능이 1개 이상인 성공 run 수(perf 지표가 있거나 > 0일 때만 응답에 있음)

    OMIT_UNSET: ClassVar[tuple[str, ...]] = ("spec_changed",)


class DesignMap(Resp):
    batch_id: str
    label: str
    status: str
    parameters: list[DesignMapParameter]
    series: list[str]
    metrics: list[DesignMapMetric]
    runs: list[DesignMapRun]
    counts: DesignMapCounts
    reason_text: dict[str, str] = {}  # 응답에 나온 사유 코드 → 한국어(`responses.REASON_TEXT`, S19 §24.5)
