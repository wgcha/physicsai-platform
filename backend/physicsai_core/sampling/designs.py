"""표본 설계 계산(phase3 §20.5, D3-63) — 최적화 LHS·전체 요인·Box–Behnken·CCD·공통 코드값 변환·품질 지표.

순수 Python(`random.Random`). 입력·출력은 단위 좌표(0~1) 또는 코드값(−1/0/+1)이고 실제 값 변환은 `code_to_value`·`unit_to_value`.
300줄 분할(R-B): 품질 지표·최적화 LHS(maximin·corr 교환)는 `designs_lhs`(여기서 재노출)."""

from __future__ import annotations

from collections.abc import Sequence
from itertools import product
from .designs_lhs import (  # noqa: F401 - 기존 경로 재노출
    LHS_OPT_CANDIDATES, LHS_OPT_ITERATIONS, LHS_OPT_RECOMPUTE, MAXIMIN_POWER, min_dist, max_abs_corr, quality,
    maximin_score, corr_score, lhs_opt_score, _candidate, lhs_opt_unit,
)


# ---- 값 변환 -----------------------------------------------------------------------------------------


def code_to_value(c: float, lo: float, hi: float) -> float:
    """코드값 → 값: −1 → lo, +1 → hi, 0 → (lo+hi)/2(정확히 이 식), 그 밖 → (lo+hi)/2 + c·(hi−lo)/2."""
    if c == -1:
        return lo
    if c == 1:
        return hi
    mid = (lo + hi) / 2
    if c == 0:
        return mid
    return mid + c * (hi - lo) / 2


def unit_to_value(u: float, lo: float, hi: float) -> float:
    """단위 값 u ∈ [0,1] → lo + u·(hi−lo)."""
    return lo + u * (hi - lo)


# ---- 전체 요인 / BBD / CCD ----------------------------------------------------------------------------


def fullfact_levels(lo: float, hi: float, n_levels: int) -> list[float]:
    """수준 값 lo + t·(hi−lo), t = i/(L−1) (i = 0 → lo, i = L−1 → hi 정확)."""
    out = []
    for i in range(n_levels):
        if i == 0:
            out.append(lo)
        elif i == n_levels - 1:
            out.append(hi)
        else:
            out.append(lo + (i / (n_levels - 1)) * (hi - lo))
    return out


def fullfact_index_rows(levels: Sequence[int]) -> list[tuple[int, ...]]:
    """수준 번호 사전식 곱(마지막 변수가 가장 빨리 바뀜)."""
    return list(product(*[range(n) for n in levels]))


def bbd_codes(k: int) -> list[list[int]]:
    """쌍 방식 Box–Behnken: 쌍 (i<j) 사전식 × (−,−)(+,−)(−,+)(+,+) 4행, 마지막에 중심 1행. run = 2k(k−1)+1."""
    rows: list[list[int]] = []
    for i in range(k - 1):
        for j in range(i + 1, k):
            for ci, cj in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
                row = [0] * k
                row[i], row[j] = ci, cj
                rows.append(row)
    rows.append([0] * k)
    return rows


def ccd_alpha(alpha_kind: str, factorial_runs: int) -> float:
    return 1.0 if alpha_kind == "face" else factorial_runs ** 0.25


def ccd_codes(k: int, alpha_kind: str, factorial: Sequence[Sequence[int]]) -> list[list[float]]:
    """요인부(Yates; 내접은 ±1/α) → 축점(변수 순서대로 −1, +1) → 중심 1행."""
    f = len(factorial)
    alpha = ccd_alpha(alpha_kind, f)
    scale = 1.0 if alpha_kind == "face" else 1.0 / alpha
    rows: list[list[float]] = [[c * scale if scale != 1.0 else float(c) for c in r] for r in factorial]
    for j in range(k):
        for c in (-1.0, 1.0):
            row = [0.0] * k
            row[j] = c
            rows.append(row)
    rows.append([0.0] * k)
    return rows
