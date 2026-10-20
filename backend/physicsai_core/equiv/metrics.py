"""지표 수학(equiv-check.md §4.3·§4.4) — 순수 함수(numpy 없이, 1e-9 골든 시험 V-EQ-6).

- 판정은 A(기준) 기준: diff = B − A, rel_pct = diff/|A|×100(|A| ≤ zero_tol → null "기준값 0").
- scalar·mesh_volume: (rel_pct ≤ tol.rel_pct) 또는 (|diff| ≤ tol.abs) 중 주어진 것 하나라도 만족이면 PASS.
- curve_corr / curve_nrmse: 공통 시간 구간을 n점 균일 격자로 선형 보간 → Pearson r / NRMSE = RMS(B−A)/(max A − min A)×100.
- 집계: pair_rule all | min_ratio. 종합 required_all: 필수 FAIL 있으면 FAIL, 필수 전부 PASS면 PASS, 그 밖 INCOMPLETE.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

PASS, FAIL, NA = "PASS", "FAIL", "NA"
INCOMPLETE = "INCOMPLETE"

# 사유 코드(한국어 문구 — 기존 REASON_TEXT에 더함)
REASON_TEXT: dict[str, str] = {
    "RUN_NOT_SUCCEEDED": "run이 성공 상태가 아님",
    "PERF_UNDEFINED": "성능 정의 없음",
    "NOT_EXTRACTED": "값이 추출되지 않음",
    "NO_VALUE": "값 없음",
    "NO_CURVE": "곡선 파일 없음",
    "SERIES_MISSING": "계열 없음",
    "SPEC_CHANGED": "추출 요청이 정의와 다름",
    "SPEC_INVALID": "정의 형식 오류",
    "MESH_MISSING": "메시 파일 없음",
    "FLAT_CURVE": "평탄 곡선(분산 0)",
    "REF_ZERO": "기준값 0",
    "NO_OVERLAP": "공통 시간 구간 없음",
    "EXTRACT_UNAVAILABLE": "추출 도구 없음",
    "EXTRACT_FAILED": "추출 실패",
    "VOLUME_ZERO": "부피 0(대상 part 요소 없음)",
    "UNBOUND": "원천 미연결",
}


def reason_text(code: str | None) -> str | None:
    if code is None:
        return None
    return REASON_TEXT.get(code, code)


def _finite(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return None
    return float(v)


@dataclass(frozen=True)
class ScalarJudge:
    a: float | None
    b: float | None
    diff: float | None
    rel_pct: float | None
    status: str
    reason: str | None


def judge_scalar(a: Any, b: Any, tol: Mapping[str, Any], *, zero_tol: float) -> ScalarJudge:
    """scalar·mesh_volume 판정(§4.3). 둘 중 하나라도 값이 없으면 NA(사유는 호출자가 보강)."""
    fa, fb = _finite(a), _finite(b)
    if fa is None or fb is None:
        return ScalarJudge(fa, fb, None, None, NA, "NO_VALUE")
    diff = fb - fa
    rel = None if abs(fa) <= zero_tol else diff / abs(fa) * 100.0
    rel_tol, abs_tol = _finite(tol.get("rel_pct")), _finite(tol.get("abs"))
    checks: list[bool] = []
    if rel_tol is not None and rel is not None:
        checks.append(abs(rel) <= rel_tol + 1e-12)
    if abs_tol is not None:
        checks.append(abs(diff) <= abs_tol + 1e-12)
    if not checks:  # rel만 주어졌는데 기준값 0 → 판정 불가
        return ScalarJudge(fa, fb, diff, rel, NA, "REF_ZERO")
    return ScalarJudge(fa, fb, diff, rel, PASS if any(checks) else FAIL, None)


# ---- 곡선 ------------------------------------------------------------------------------------------


def _interp(xs: Sequence[float], ys: Sequence[float], t: float) -> float:
    """단조 증가 xs에서 선형 보간(양 끝은 끝값). 호출자가 xs가 정렬·유한임을 보장."""
    n = len(xs)
    if t <= xs[0]:
        return ys[0]
    if t >= xs[-1]:
        return ys[-1]
    lo, hi = 0, n - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if xs[mid] <= t:
            lo = mid
        else:
            hi = mid
    x0, x1 = xs[lo], xs[hi]
    if x1 == x0:
        return ys[lo]
    w = (t - x0) / (x1 - x0)
    return ys[lo] + w * (ys[hi] - ys[lo])


def _clean(xs: Sequence[Any], ys: Sequence[Any]) -> tuple[list[float], list[float]] | None:
    pts: list[tuple[float, float]] = []
    for x, y in zip(xs, ys):
        fx, fy = _finite(x), _finite(y)
        if fx is None or fy is None:
            continue
        pts.append((fx, fy))
    if len(pts) < 2:
        return None
    pts.sort(key=lambda p: p[0])
    out_x: list[float] = []
    out_y: list[float] = []
    for x, y in pts:  # 같은 x는 마지막 값
        if out_x and out_x[-1] == x:
            out_y[-1] = y
        else:
            out_x.append(x)
            out_y.append(y)
    return (out_x, out_y) if len(out_x) >= 2 else None


@dataclass(frozen=True)
class Resampled:
    t: list[float]
    a: list[float]
    b: list[float]
    overlap_ratio: float  # 공통 구간 길이 / 짧은 곡선 길이


def resample_common(xa: Sequence[Any], ya: Sequence[Any], xb: Sequence[Any], yb: Sequence[Any], n: int) -> Resampled | None:
    """두 곡선의 공통 구간 [max(t0), min(t_end)]을 n점 균일 격자로 보간. 공통 구간이 없거나 점이 모자라면 None."""
    ca, cb = _clean(xa, ya), _clean(xb, yb)
    if ca is None or cb is None or n < 2:
        return None
    t0, t1 = max(ca[0][0], cb[0][0]), min(ca[0][-1], cb[0][-1])
    if not t1 > t0:
        return None
    short = min(ca[0][-1] - ca[0][0], cb[0][-1] - cb[0][0])
    ratio = (t1 - t0) / short if short > 0 else 1.0
    t = [t0 + (t1 - t0) * i / (n - 1) for i in range(n)]
    return Resampled(t, [_interp(ca[0], ca[1], v) for v in t], [_interp(cb[0], cb[1], v) for v in t], min(1.0, ratio))


def pearson(a: Sequence[float], b: Sequence[float]) -> float | None:
    """Pearson r. 길이 다름·2점 미만·어느 한쪽 분산 0 → None(평탄 곡선)."""
    n = len(a)
    if n != len(b) or n < 2:
        return None
    ma, mb = sum(a) / n, sum(b) / n
    sab = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    saa = sum((x - ma) ** 2 for x in a)
    sbb = sum((y - mb) ** 2 for y in b)
    if saa <= 0 or sbb <= 0:
        return None
    r = sab / math.sqrt(saa * sbb)
    return max(-1.0, min(1.0, r))


def nrmse_pct(a: Sequence[float], b: Sequence[float]) -> float | None:
    """NRMSE% = RMS(B−A)/(max A − min A)×100. 기준 A의 범위가 0이면 None."""
    n = len(a)
    if n != len(b) or n < 1:
        return None
    rng = max(a) - min(a)
    if rng <= 0:
        return None
    rms = math.sqrt(sum((y - x) ** 2 for x, y in zip(a, b)) / n)
    return rms / rng * 100.0


def judge_curve(kind: str, rs: Resampled | None, tol: Mapping[str, Any]) -> tuple[float | None, str, str | None]:
    """(값, 상태, 사유). kind = curve_corr → r, curve_nrmse → NRMSE%."""
    if rs is None:
        return None, NA, "NO_OVERLAP"
    if kind == "curve_corr":
        r = pearson(rs.a, rs.b)
        if r is None:
            return None, NA, "FLAT_CURVE"
        cmin = _finite(tol.get("corr_min"))
        return r, (PASS if cmin is None or r >= cmin - 1e-12 else FAIL), None
    v = nrmse_pct(rs.a, rs.b)
    if v is None:
        return None, NA, "FLAT_CURVE"
    nmax = _finite(tol.get("nrmse_max_pct"))
    return v, (PASS if nmax is None or v <= nmax + 1e-12 else FAIL), None


# ---- 집계·종합 ---------------------------------------------------------------------------------------


def aggregate(rows: Sequence[Mapping[str, Any]], pair_rule: Mapping[str, Any]) -> dict[str, Any]:
    """지표 1개의 쌍별 행(§5.2 metrics.csv 모양: a,b,diff,rel_pct,corr,status,a_run,b_run) → 집계 수치(§4.4)."""
    n = len(rows)
    n_pass = sum(1 for r in rows if r.get("status") == PASS)
    n_fail = sum(1 for r in rows if r.get("status") == FAIL)
    n_na = n - n_pass - n_fail
    judged = n_pass + n_fail
    mode = pair_rule.get("mode", "all")
    if judged == 0:
        status = NA
    elif mode == "min_ratio":
        status = PASS if n_pass / judged >= float(pair_rule.get("ratio", 1.0)) - 1e-12 else FAIL
    else:
        status = PASS if n_fail == 0 else FAIL

    def mean(key: str) -> float | None:
        vs = [_finite(r.get(key)) for r in rows]
        vs = [v for v in vs if v is not None]
        return sum(vs) / len(vs) if vs else None

    def worst(key: str, pick_max: bool) -> tuple[float | None, str | None]:
        best: tuple[float, str] | None = None
        for r in rows:
            v = _finite(r.get(key))
            if v is None:
                continue
            m = abs(v) if key != "corr" else v
            if best is None or (m > best[0] if pick_max else m < best[0]):
                best = (m, f"{r.get('a_run')} ↔ {r.get('b_run')}")
        return (best[0], best[1]) if best else (None, None)

    mx_rel, w_rel = worst("rel_pct", True)
    mx_abs, w_abs = worst("diff", True)
    mn_corr, w_corr = worst("corr", False)
    worst_pair = w_rel or w_abs or w_corr
    return {"status": status, "n_pairs": n, "n_pass": n_pass, "n_fail": n_fail, "n_na": n_na,
            "a_mean": mean("a"), "b_mean": mean("b"), "max_abs_rel_pct": mx_rel, "max_abs_diff": mx_abs,
            "min_corr": mn_corr, "worst_pair": worst_pair, "partial": bool(judged and n_na)}


def overall_verdict(metrics: Sequence[Mapping[str, Any]], aggs: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """required_all(§4.4): 필수 FAIL → FAIL, 필수 전부 PASS → PASS, 그 밖(필수 NA) → INCOMPLETE. 참고 지표는 영향 없음."""
    req = [m for m in metrics if m.get("required", True)]
    ref = [m for m in metrics if not m.get("required", True)]
    st = {m["id"]: (aggs.get(m["id"]) or {}).get("status", NA) for m in metrics}
    req_fail = sum(1 for m in req if st[m["id"]] == FAIL)
    req_pass = sum(1 for m in req if st[m["id"]] == PASS)
    ref_fail = sum(1 for m in ref if st[m["id"]] == FAIL)
    if req_fail:
        verdict = FAIL
    elif req and req_pass == len(req):
        verdict = PASS
    elif not req:
        verdict = INCOMPLETE  # 필수 지표가 없으면 종합할 근거가 없다
    else:
        verdict = INCOMPLETE
    return {"verdict": verdict, "required_total": len(req), "required_pass": req_pass, "required_fail": req_fail,
            "reference_total": len(ref), "reference_fail": ref_fail}


VERDICT_TEXT = {PASS: "통과", FAIL: "미달", INCOMPLETE: "판정 불가"}
