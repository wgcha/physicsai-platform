"""⑥ 최적화 기준(응답·방향·임계값·가중치)은 사용자가 정한다(opt-native ON-C4, 사용자 결정 2026-10-20).

시스템은 목적 응답·최소/최대 방향·제약 임계값·다목적 가중치를 기본값으로 채우거나 추정하지 않는다.
비어 있으면 API는 422 `OPT_CRITERIA_REQUIRED`(+`missing`), 워커는 같은 코드로 작업을 실패시킨다.
여기 함수는 요청 본문(API)과 저장된 settings(워커) 양쪽에 같은 규칙을 적용한다(표준 라이브러리만 — API는 numpy 금지).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

CODE = "OPT_CRITERIA_REQUIRED"
SENSES = ("min", "max")
MESSAGE = "최적화 기준이 비어 있습니다 — 목적 응답·방향(최소/최대)·제약 임계값·다목적 가중치를 직접 정하세요"


def _get(x: Any, k: str) -> Any:
    return x.get(k) if isinstance(x, Mapping) else getattr(x, k, None)


def _finite(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(float(v))


def item_message(path: str) -> str:
    """빈 항목 경로 → 한국어 안내(값 제안 없음)."""
    parts = path.split(".")
    if path == "objectives":
        return "목적으로 쓸 응답을 1개 이상 고르세요"
    if path == "weights":
        return "다목적 가중치를 목적마다 직접 입력하세요(0 이상, 합 > 0)"
    if parts[0] in ("objectives", "objective") and parts[-1] == "sense":
        n = "" if parts[0] == "objective" else f" {int(parts[1]) + 1}"
        return f"목적{n}의 방향(최소/최대)을 고르세요"
    if parts[0] == "constraints":
        n = int(parts[1]) + 1
        what = {"op": "조건(≤·≥·범위)", "value": "임계값", "lo": "범위 하한", "hi": "범위 상한"}.get(parts[-1], parts[-1])
        return f"제약 {n}의 {what}을 입력하세요"
    return f"{path}을(를) 입력하세요"


def missing(objectives: Sequence[Any], constraints: Sequence[Any], weights: Sequence[Any] | None, *,
            max_objectives: int | None = None, obj_prefix: str = "objectives") -> list[str]:
    """비어 있는 기준 항목 경로 목록(순서 고정). 범위 밖(목적 수 초과·하한 ≥ 상한 등)은 여기서 다루지 않는다."""
    out: list[str] = []
    m = len(objectives)
    if m == 0:
        out.append("objectives")
    for i, o in enumerate(objectives):
        if _get(o, "sense") not in SENSES:
            out.append(f"{obj_prefix}.sense" if obj_prefix == "objective" else f"{obj_prefix}.{i}.sense")
    for i, c in enumerate(constraints):
        op = _get(c, "op")
        if op is None:
            out.append(f"constraints.{i}.op")
        elif op == "range":
            out += [f"constraints.{i}.{k}" for k in ("lo", "hi") if _get(c, k) is None]
        elif _get(c, "value") is None:
            out.append(f"constraints.{i}.value")
    if m >= 2 and (max_objectives is None or m <= max_objectives) and weights is None:
        out.append("weights")
    return out


def settings_missing(settings: Mapping[str, Any]) -> list[str]:
    """저장된 settings(워커 실행 직전)의 빈 기준. 0014 이전 단일 목적 행(`objective`만)도 같은 규칙."""
    objs = settings.get("objectives")
    prefix = "objectives"
    if not (isinstance(objs, list) and objs):
        one = settings.get("objective")
        objs, prefix = ([one] if isinstance(one, Mapping) else []), "objective"
    cons = [c for c in settings.get("constraints") or [] if isinstance(c, Mapping)]
    w = settings.get("weights")
    weights = list(w) if isinstance(w, list) and w and all(_finite(x) for x in w) else None
    return missing(objs, cons, weights, obj_prefix=prefix)


def problems_of(paths: Sequence[str]) -> list[dict[str, Any]]:
    """미리보기 problems 행(code·field·message) — 빈 항목마다 1개."""
    return [{"code": CODE, "field": p, "message": item_message(p)} for p in paths]
