"""API 스키마 — native 추출 조건(extract-filter.md §6.1). 값 검사(범위·그룹 0개·min>max)는 서버가 `extract_filter.normalize`로
하고 422 `EXTRACT_FILTER_INVALID`(problems[{key, message}])로 돌려준다 — 여기서는 모양(모르는 키 거부)만 본다."""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict

from .common import Req

__all__ = ["ExtractRange", "ExtractConditions", "ExtractFilter"]


class _Strict(Req):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class ExtractRange(_Strict):
    min: float | None = None
    max: float | None = None


class ExtractConditions(_Strict):
    """조건 키(§4.2) 전부 선택. null·생략 = 미사용."""

    thickness_mm: ExtractRange | None = None
    face_area_min_mm2: float | None = None
    height_mm: ExtractRange | None = None
    position_min_size_mm: float | None = None
    hole_radius_min_mm: float | None = None
    fillet_radius_min_mm: float | None = None


class ExtractFilter(_Strict):
    """찾을 종류(그룹)와 조건. `groups`: thickness·height·position·rib_pitch·hole_radius·fillet 중 1개 이상·중복 없음(서버 검사).
    `draft_max_deg`: null 또는 0 초과 45 미만(null = 설정·paicad 기본). 응답에 나올 때는 서버 정규화본(선택 안 한 그룹의 조건 제거)."""

    groups: list[Literal["thickness", "height", "position", "rib_pitch", "hole_radius", "fillet"]]
    conditions: ExtractConditions = ExtractConditions()
    draft_max_deg: float | None = None
