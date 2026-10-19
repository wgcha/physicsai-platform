"""단계 3S 쉘 두께 파라미터(geometry-engine.md §11.1) — 순수 함수(파일 쓰기는 호출자).

- `S/native/props/props.json` = `paicad props scan` 출력(조립 폴더의 /PROP/TYPE1 목록). 플랫폼은 읽기만 한다.
- 파라미터 표(`parameters.json`·`param_sets.parameters`)에 선택한 PROP을 `source: "prop"`, `prop_id` 행으로 합친다
  (형상 행은 `source` 없음 = 형상). 범위 기본 = props.json `range`(±`extract.range_ratio`), 사용자가 min·max 편집.
- run 값은 형상 값(→ paicad update `values.json`)과 쉘 두께 값(→ `props apply` `values.json`)으로 나눈다.
- 형상 행이 하나도 없으면(쉘 두께 전용) tag·update·morph·check를 생략하고 기준 메시를 그대로 조립한다.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

PROP_SOURCE = "prop"
PROPS_DIR = "native/props"
PROPS_JSON = "native/props/props.json"
APPLY_DIR = "props"  # run 작업 폴더 안 props apply 출력(`P/geom/props`, `R/m_3_props`)
SHELL_ONLY_KEY = "shell_only"  # prep.json 표시(쉘 두께 전용 세트: cad·extract·tag 없음)


class ShellError(ValueError):
    """선택 검증 실패(API 422 PROP_SELECTION_INVALID). problems = [{code, message, parameter?}]."""

    def __init__(self, problems: list[dict[str, Any]]):
        super().__init__("; ".join(p["message"] for p in problems))
        self.problems = problems


def is_prop_row(row: Mapping[str, Any]) -> bool:
    return row.get("source") == PROP_SOURCE


def geometry_rows(parameters: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [dict(r) for r in parameters if not is_prop_row(r)]


def prop_rows(parameters: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [dict(r) for r in parameters if is_prop_row(r)]


def prop_names(parameters: Iterable[Mapping[str, Any]]) -> set[str]:
    return {str(r["name"]) for r in parameters if is_prop_row(r)}


def split_values(parameters: Sequence[Mapping[str, Any]], values: Mapping[str, float]) -> tuple[dict[str, float], dict[str, float]]:
    """run 값 → (형상 값, 쉘 두께 값). 표에 없는 이름은 형상 쪽(기존 동작 — paicad가 검사)."""
    pn = prop_names(parameters)
    geo = {k: float(v) for k, v in values.items() if k not in pn}
    shell = {k: float(v) for k, v in values.items() if k in pn}
    return geo, shell


def has_geometry(parameters: Iterable[Mapping[str, Any]]) -> bool:
    return any(not is_prop_row(r) for r in parameters)


def props_rows(doc: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    rows = (doc or {}).get("props")
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def selectable(doc: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    """선택 가능한 PROP(파라미터 이름 → props.json 행): TYPE1·두께 > 0·요소·PART 덮어쓰기 없음(`selectable`)."""
    out: dict[str, dict[str, Any]] = {}
    for r in props_rows(doc):
        if r.get("selectable") and isinstance(r.get("parameter"), str) and isinstance(r.get("thickness"), (int, float)):
            out[r["parameter"]] = r
    return out


def _finite(x: Any) -> float | None:
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    return float(x) if math.isfinite(float(x)) else None


def default_row(r: Mapping[str, Any]) -> dict[str, Any]:
    """props.json 행 → 파라미터 표 행(범위 = props.json range, 없으면 공칭 ±0)."""
    t = float(r["thickness"])
    rg = r.get("range") if isinstance(r.get("range"), dict) else {}
    lo, hi = _finite(rg.get("min")), _finite(rg.get("max"))
    return {"name": r["parameter"], "nominal": t, "min": lo if lo is not None else t, "max": hi if hi is not None else t,
            "unit": "mm", "source": PROP_SOURCE, "prop_id": int(r["id"])}


def selection_rows(doc: Mapping[str, Any] | None, selection: Sequence[Mapping[str, Any]], *,
                   geometry_names: Iterable[str] = ()) -> list[dict[str, Any]]:
    """사용자 선택 [{name, min?, max?}] → 파라미터 표 prop 행(선택 순서). 검증 실패는 ShellError."""
    sel = selectable(doc)
    rows_by_name = {r.get("parameter"): r for r in props_rows(doc) if r.get("parameter")}
    geo = set(geometry_names)
    probs: list[dict[str, Any]] = []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in selection:
        name = str(item.get("name") or "")
        if name in seen:
            probs.append({"code": "PROP_SELECTION_DUPLICATE", "parameter": name, "message": f"{name}: 중복 선택입니다"})
            continue
        seen.add(name)
        if name in geo:
            probs.append({"code": "PARAM_NAME_CONFLICT", "parameter": name, "message": f"{name}: 형상 파라미터와 이름이 같습니다"})
            continue
        if name not in sel:
            row = rows_by_name.get(name)
            why = "PROP 목록에 없습니다(스캔을 다시 하세요)" if row is None else _unselectable_reason(row)
            probs.append({"code": _unselectable_code(row), "parameter": name, "message": f"{name}: {why}"})
            continue
        r = default_row(sel[name])
        lo, hi = item.get("min"), item.get("max")
        if lo is not None:
            r["min"] = _finite(lo)
        if hi is not None:
            r["max"] = _finite(hi)
        if r["min"] is None or r["max"] is None:
            probs.append({"code": "PROP_THICKNESS_INVALID", "parameter": name, "message": f"{name}: min·max는 유한한 숫자여야 합니다"})
            continue
        if not (0 < r["min"] <= r["nominal"] <= r["max"]):
            probs.append({"code": "PROP_THICKNESS_INVALID", "parameter": name,
                          "message": f"{name}: 0 < min ≤ 공칭({r['nominal']:g}) ≤ max 이어야 합니다"})
            continue
        out.append(r)
    if probs:
        raise ShellError(probs)
    return out


def _unselectable_code(row: Mapping[str, Any] | None) -> str:
    if row is None:
        return "PROP_NOT_FOUND"
    if not row.get("supported", True):
        return "PROP_UNSUPPORTED_TYPE"
    if row.get("element_overrides"):
        return "PROP_OVERRIDDEN_BY_ELEMENT"
    if row.get("part_overrides"):
        return "PROP_OVERRIDDEN_BY_PART"
    return "PROP_THICKNESS_INVALID"


def _unselectable_reason(row: Mapping[str, Any]) -> str:
    return {
        "PROP_UNSUPPORTED_TYPE": "지원하지 않는 PROP 형식입니다(/PROP/TYPE1만)",
        "PROP_OVERRIDDEN_BY_ELEMENT": "요소별 두께가 PROP 두께를 덮어써 바꿀 수 없습니다",
        "PROP_OVERRIDDEN_BY_PART": "/PART 카드 두께가 PROP 두께를 덮어써 바꿀 수 없습니다",
        "PROP_THICKNESS_INVALID": "두께가 0 이하이거나 두께 카드를 찾지 못했습니다",
    }.get(_unselectable_code(row), "선택할 수 없습니다")


def merge_rows(geometry: Sequence[Mapping[str, Any]], props: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """하나의 파라미터 표 = 형상 행(순서 유지) + 쉘 두께 행."""
    return [dict(r) for r in geometry] + [dict(r) for r in props]


def summary(doc: Mapping[str, Any] | None, parameters: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """API 응답(PROP 목록 + 현재 선택). PROP 행은 props.json 키를 표시용으로 고른다."""
    chosen = {r["name"]: r for r in prop_rows(parameters)}
    props = []
    for r in props_rows(doc):
        name = r.get("parameter")
        c = chosen.get(name) if isinstance(name, str) else None
        props.append({
            "id": r.get("id"), "title": r.get("title") or "", "type": r.get("type") or "", "keyword": r.get("keyword") or "",
            "supported": bool(r.get("supported")), "parameter": name, "thickness": _finite(r.get("thickness")),
            "range": r.get("range") if isinstance(r.get("range"), dict) else None,
            "parts": [p for p in (r.get("parts") or []) if isinstance(p, dict)],
            "part_overrides": [p for p in (r.get("part_overrides") or []) if isinstance(p, dict)],
            "element_overrides": int(r.get("element_overrides") or 0), "file": r.get("file"),
            "selectable": bool(r.get("selectable")), "reason_code": None if r.get("selectable") else _unselectable_code(r),
            "selected": c is not None, "min": c["min"] if c else None, "max": c["max"] if c else None,
        })
    warnings = [w for w in ((doc or {}).get("warnings") or []) if isinstance(w, dict)]
    return {"engine_version": (doc or {}).get("engine_version"), "props": props,
            "warnings": [{"code": str(w.get("code") or ""), "prop": w.get("prop"), "parts": w.get("parts") or [],
                          "message": str(w.get("message") or "")} for w in warnings]}


def apply_values_document(values: Mapping[str, float], engine_version: str | None) -> dict[str, Any]:
    """`props apply --values` 입력({schema_version, values}) — 값은 반올림하지 않는다(GE-9)."""
    return {"schema_version": 1, "engine": "native", "engine_version": engine_version,
            "values": {k: float(v) for k, v in values.items()}}
