"""④ 입력 확인(§8.8): 학습 범위 밖, 정수 반영, 최근접 run."""

from __future__ import annotations

import math
from collections.abc import Mapping
from decimal import ROUND_HALF_UP, Decimal
from typing import Any


def apply_rounding(value: float, mode: str) -> int:
    if mode == "truncate":
        return int(value)
    return int(Decimal(repr(float(value))).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def out_of_range(parameters: list[dict[str, Any]], values: dict[str, float]) -> list[dict[str, Any]]:
    out = []
    for p in parameters:
        v = values.get(p["name"])
        if v is None:
            continue
        if v < p["min"] or v > p["max"]:
            out.append({"name": p["name"], "value": v, "min": p["min"], "max": p["max"]})
    return out


def integer_vars(tpl_params: list[dict[str, Any]]) -> dict[str, str]:
    """파라미터 이름 → 정수 형식(%Ni/%Nd)이면 형식 문자열."""
    out = {}
    for t in tpl_params:
        fmt = t.get("format") or ""
        if fmt[-1:] in ("i", "d"):
            out[t["name"]] = fmt
    return out


INT_RANGE_CODE = "VAR_RANGE_INVALID"
INT_RANGE_MESSAGE = "정수 파라미터는 정수 범위여야 합니다"


def is_integer_range(lo: float, hi: float) -> bool:
    """정수(%i·%d) 파라미터의 하한·상한이 모두 정수값인가(altair-vars.md §5.1 — PUT variables·④ 일괄·⑥ 공용 검사). 유한 수만 넘길 것."""
    return lo == math.floor(lo) and hi == math.floor(hi)


def integer_range_violations(ranges: Mapping[str, Any], tpl_params: list[dict[str, Any]]) -> list[str]:
    """`{이름: [하한, 상한]}` 중 정수 형식 파라미터인데 비정수 범위인 이름(입력 순서). 모양이 틀렸거나 유한하지 않은 항목은 건너뛴다(다른 검사 몫)."""
    ints = integer_vars(tpl_params)
    out: list[str] = []
    for name, r in ranges.items():
        if name not in ints or not isinstance(r, (list, tuple)) or len(r) != 2:
            continue
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in r):
            continue
        if not is_integer_range(float(r[0]), float(r[1])):
            out.append(str(name))
    return out


def rounded(tpl_params: list[dict[str, Any]], values: dict[str, float], mode: str) -> list[dict[str, Any]]:
    res = []
    for name in integer_vars(tpl_params):
        if name in values:
            applied = apply_rounding(values[name], mode)
            res.append({"name": name, "value": values[name], "applied": applied})
    return res


def applied_values(tpl_params: list[dict[str, Any]], values: dict[str, float], mode: str) -> dict[str, float]:
    av: dict[str, float] = dict(values)
    for r in rounded(tpl_params, values, mode):
        av[r["name"]] = r["applied"]
    return av


def nearest_run(
    parameters: list[dict[str, Any]], samples: list[dict[str, Any]], values: dict[str, float]
) -> dict[str, Any] | None:
    """d = sqrt(Σ((x_i − y_i)/(max_i − min_i))²) 최소(max=min 제외). 동률이면 run_key 사전순."""
    if not samples:
        return None
    best: tuple[float, str, dict[str, Any]] | None = None
    for s in samples:
        acc = 0.0
        for p in parameters:
            span = p["max"] - p["min"]
            if span == 0:
                continue
            x = values.get(p["name"])
            y = s["values"].get(p["name"])
            if x is None or y is None:
                continue
            acc += ((x - y) / span) ** 2
        d = math.sqrt(acc)
        key = (d, s["run_key"])
        if best is None or key < (best[0], best[1]):
            best = (d, s["run_key"], s)
    assert best is not None
    s = best[2]
    return {
        "run_key": s["run_key"],
        "distance": round(best[0], 12),
        "values": s["values"],
        "measured": s.get("measured") or None,
    }
