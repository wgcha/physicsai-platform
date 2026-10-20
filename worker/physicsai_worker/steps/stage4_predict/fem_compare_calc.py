"""④ FEM_VERIFY 공용 계산(순수): 범례 이름·FEM datatype·차이·비교 행·최악·커브 짝 — fem_compare에서 재노출."""

from __future__ import annotations

import math
import re
from typing import Any

from physicsai_core.errors import DomainError, StepFailure
from physicsai_core.stage4_predict import responses as resp_mod

from ...limiter.base import LimiterError

LEGEND = "__FV_LEGEND"
MAX_SUMMARY_NAMES = 20
_CATCH = (StepFailure, DomainError, LimiterError, OSError)
_WS = re.compile(r"\s+")


# ---- 공용 계산(순수) ----------------------------------------------------------------------------------


def legend_name(responses: list[dict[str, Any]]) -> str:
    """예약 이름 `__FV_LEGEND`, 같은 이름의 사용자 응답이 있으면 `__FV_LEGEND2`(…3)."""
    names = {str(r.get("name") or "") for r in responses}
    if LEGEND not in names:
        return LEGEND
    i = 2
    while f"{LEGEND}{i}" in names:
        i += 1
    return f"{LEGEND}{i}"


def fem_datatype(settings: Any, datatype: str, fem: dict[str, Any] | None) -> str:
    f = (fem or {}).get("field")
    if f:
        return str(f)
    return settings.fem_verify.field_map.get(datatype, datatype)


def _diff(pred: float | None, fem: float | None, zero_tol: float) -> tuple[float | None, float | None, str | None]:
    if pred is None or fem is None:
        return None, None, None
    d = pred - fem
    if abs(fem) <= zero_tol:
        return d, None, "기준값 0"
    return d, d / abs(fem) * 100.0, None


def compare_rows(reqs: list[resp_mod.H3dRequest], units: dict[str, str], pred: resp_mod.ParsedResponses | None,
                 fem: resp_mod.ParsedResponses | None, zero_tol: float) -> list[dict[str, Any]]:
    """응답마다 MIN·MAX·판정값(stat) 비교 행 1개(MIN·MAX 차이도 같은 식)."""
    out = []
    empty = resp_mod.ParsedResponses()
    for q in reqs:
        p, f = pred or empty, fem or empty
        pmin, pmax = p.values.get(f"{q.name}_MIN"), p.values.get(f"{q.name}_MAX")
        fmin, fmax = f.values.get(f"{q.name}_MIN"), f.values.get(f"{q.name}_MAX")
        pv, _ = resp_mod.apply_stat(q, p)
        fv, _ = resp_mod.apply_stat(q, f)
        d, dp, note = _diff(pv, fv, zero_tol)
        dmin, dpmin, _n1 = _diff(pmin, fmin, zero_tol)
        dmax, dpmax, _n2 = _diff(pmax, fmax, zero_tol)
        out.append({"name": q.name, "unit": units.get(q.name, ""), "stat": q.stat, "pred_min": pmin, "pred_max": pmax,
                    "fem_min": fmin, "fem_max": fmax, "pred_value": pv, "fem_value": fv, "diff": d, "diff_pct": dp,
                    "min_diff": dmin, "min_diff_pct": dpmin, "max_diff": dmax, "max_diff_pct": dpmax, "note": note})
    return out


def worst_of(rows: list[dict[str, Any]]) -> tuple[float | None, str | None]:
    best: tuple[float | None, str | None] = (None, None)
    for r in rows:
        v = r.get("diff_pct")
        if isinstance(v, (int, float)) and math.isfinite(v) and (best[0] is None or abs(v) > best[0]):
            best = (abs(v), r["name"])
    return best


def legend_union(pred: tuple[float | None, float | None], fem: tuple[float | None, float | None]) -> tuple[float, float] | None:
    vals = [*pred, *fem]
    if any(v is None or not math.isfinite(v) for v in vals):
        return None
    lo, hi = min(pred[0], fem[0]), max(pred[1], fem[1])  # type: ignore[type-var]
    return (lo, hi) if lo < hi else None


def _norm(name: str) -> str:
    return _WS.sub("", name).casefold()


def pair_curves(pred_names: list[str], fem_names: list[str]) -> tuple[list[dict[str, str]], list[str], list[str]]:
    """이름 짝(정확히 같음 → 대소문자·공백 무시). (짝, 짝 없는 예측, 짝 없는 FEM)."""
    pairs: list[dict[str, str]] = []
    left_f = list(fem_names)
    left_p = []
    for p in pred_names:
        if p in left_f:
            pairs.append({"pred": p, "fem": p})
            left_f.remove(p)
        else:
            left_p.append(p)
    still = []
    for p in left_p:
        m = next((f for f in left_f if _norm(f) == _norm(p)), None)
        if m is not None:
            pairs.append({"pred": p, "fem": m})
            left_f.remove(m)
        else:
            still.append(p)
    return pairs, still, left_f
