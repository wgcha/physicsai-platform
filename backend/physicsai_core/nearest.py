"""④ 입력 확인(§8.8): 학습 범위 밖, 정수 반영, 최근접 run."""

from __future__ import annotations

import math
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
