"""API 스키마 — native 형상 엔진(geometry-engine.md §7.4~§7.6): 세트 준비 상태·피처 목록·202 응답."""

from __future__ import annotations

from typing import Any, Literal

from .common import Resp

__all__ = ["NativeAccepted", "NativeInfo", "NativeFeature", "NativeGroup", "NativeWarning", "NativeFeatures"]


class NativeAccepted(Resp):
    """native 세트 등록·다시 준비 202 본문 — 진행은 job으로 본다."""

    job_id: str


class NativeInfo(Resp):
    prep_status: Literal["READY", "STALE", "MISSING"]
    prep_reason: str | None = None  # 한국어(STALE·MISSING 사유)
    feature_count: int = 0


class NativeFeature(Resp):
    name: str
    type: str = ""
    body: str = ""
    nominal: float | None = None
    min: float | None = None
    max: float | None = None
    unit: str = "mm"
    group: str | None = None
    ref_provisional: bool = False
    ref_locked: bool = False
    feasible: dict[str, Any] | None = None
    png_artifact_id: str | None = None


class NativeGroup(Resp):
    id: str | None = None
    kind: str | None = None
    parameter: str | None = None
    members: list[str] = []


class NativeWarning(Resp):
    code: str
    message: str = ""
    feature: str | None = None


class NativeFeatures(Resp):
    engine_version: str | None = None
    features: list[NativeFeature]
    groups: list[NativeGroup]
    warnings: list[NativeWarning]
