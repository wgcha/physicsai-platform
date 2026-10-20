"""표본 방식 품질 지표(최소 거리·최대 상관)와 최적화 LHS(phase3 §20, D3-63: 후보 LHS·maximin/corr 점수·교환 탐색) — designs에서 재노출."""

from __future__ import annotations

import math
import random
from collections.abc import Sequence

LHS_OPT_CANDIDATES = 5  # 후보 수 C
LHS_OPT_ITERATIONS = 2000  # 열 내 교환 횟수 T
LHS_OPT_RECOMPUTE = 500  # 증분 점수를 전체 재계산하는 주기
MAXIMIN_POWER = -15  # S = Σ d^(−15)
_PW = MAXIMIN_POWER / 2.0  # d2^(−7.5)


# ---- 품질 지표 -----------------------------------------------------------------------------------------


def _pearson(x: Sequence[float], y: Sequence[float]) -> float:
    n = len(x)
    mx, my = sum(x) / n, sum(y) / n
    sxx = sum((a - mx) ** 2 for a in x)
    syy = sum((b - my) ** 2 for b in y)
    if sxx <= 0 or syy <= 0:
        return 0.0
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / math.sqrt(sxx * syy)


def min_dist(points: Sequence[Sequence[float]]) -> float:
    """단위 좌표 점 사이 최소 유클리드 거리 / √k (점 1개 이하면 0)."""
    n = len(points)
    if n < 2:
        return 0.0
    k = len(points[0])
    best = math.inf
    for i in range(n - 1):
        pi = points[i]
        for l in range(i + 1, n):
            pl = points[l]
            d2 = 0.0
            for a, b in zip(pi, pl):
                d2 += (a - b) * (a - b)
            if d2 < best:
                best = d2
    return math.sqrt(best) / math.sqrt(k) if k else 0.0


def max_abs_corr(points: Sequence[Sequence[float]]) -> float:
    """활성 변수 쌍 Pearson 상관 절댓값 최대(k < 2면 0)."""
    if not points:
        return 0.0
    k = len(points[0])
    if k < 2:
        return 0.0
    cols = [[p[j] for p in points] for j in range(k)]
    return max(abs(_pearson(cols[a], cols[b])) for a in range(k) for b in range(a + 1, k))


def quality(points: Sequence[Sequence[float]]) -> dict[str, float]:
    """`source_meta.quality` = {min_dist, max_abs_corr}, 소수 4자리."""
    return {"min_dist": round(min_dist(points), 4), "max_abs_corr": round(max_abs_corr(points), 4)}


# ---- 최적화 LHS ----------------------------------------------------------------------------------------


def _pw(d2: float) -> float:
    return math.inf if d2 <= 1e-300 else d2 ** _PW


def maximin_score(u: Sequence[Sequence[float]]) -> float:
    """S = Σ_{i<l} d_il^(−15) (d = 0이 있으면 +inf)."""
    n = len(u)
    s = 0.0
    for i in range(n - 1):
        for l in range(i + 1, n):
            d2 = 0.0
            for a, b in zip(u[i], u[l]):
                d2 += (a - b) * (a - b)
            s += _pw(d2)
    return s


def corr_score(u: Sequence[Sequence[float]]) -> float:
    """S = Σ_{j<m} r_jm² (활성 열 Pearson)."""
    k = len(u[0]) if u else 0
    cols = [[row[j] for row in u] for j in range(k)]
    return sum(_pearson(cols[a], cols[b]) ** 2 for a in range(k) for b in range(a + 1, k))


def lhs_opt_score(u: Sequence[Sequence[float]], criterion: str) -> float:
    return corr_score(u) if criterion == "corr" else maximin_score(u)


def _candidate(rng: random.Random, n: int, k: int) -> list[list[float]]:
    """층화 LHS 후보 1개 — 변수(열)마다 perm shuffle 뒤 i마다 random() (기존 `lhs_values`와 같은 소비 순서)."""
    u = [[0.0] * k for _ in range(n)]
    for j in range(k):
        perm = list(range(n))
        rng.shuffle(perm)
        for i in range(n):
            u[i][j] = (perm[i] + rng.random()) / n
    return u


def _d2_tables(u: list[list[float]]) -> tuple[list[list[float]], list[list[float]], float]:
    n = len(u)
    d2 = [[0.0] * n for _ in range(n)]
    pw = [[0.0] * n for _ in range(n)]
    s = 0.0
    for i in range(n - 1):
        for l in range(i + 1, n):
            v = 0.0
            for a, b in zip(u[i], u[l]):
                v += (a - b) * (a - b)
            p = _pw(v)
            d2[i][l] = d2[l][i] = v
            pw[i][l] = pw[l][i] = p
            s += p
    return d2, pw, s


def _swap_maximin(u: list[list[float]], n: int, k: int, rng: random.Random, iterations: int) -> float:
    d2, pw, s = _d2_tables(u)
    for t in range(1, iterations + 1):
        j = rng.randrange(k)
        a = rng.randrange(n)
        b = rng.randrange(n - 1)
        if b >= a:
            b += 1
        ua, ub = u[a][j], u[b][j]
        old = new = 0.0
        upd: list[tuple[int, float, float, float, float]] = []
        da, db = d2[a], d2[b]
        for x in range(n):
            if x == a or x == b:
                continue
            ux = u[x][j]
            na = da[x] - (ua - ux) * (ua - ux) + (ub - ux) * (ub - ux)
            nb = db[x] - (ub - ux) * (ub - ux) + (ua - ux) * (ua - ux)
            pa, pb = _pw(na), _pw(nb)
            old += pw[a][x] + pw[b][x]
            new += pa + pb
            upd.append((x, na, nb, pa, pb))
        if math.isinf(s) or math.isinf(old) or math.isinf(new):  # 드문 경로: 전체 재계산으로 비교
            u[a][j], u[b][j] = ub, ua
            d2n, pwn, sn = _d2_tables(u)
            if sn < s:
                d2, pw, s = d2n, pwn, sn
            else:
                u[a][j], u[b][j] = ua, ub
        else:
            sn = s - old + new
            if sn < s:
                u[a][j], u[b][j] = ub, ua
                for x, na, nb, pa, pb in upd:
                    d2[a][x] = d2[x][a] = na
                    d2[b][x] = d2[x][b] = nb
                    pw[a][x] = pw[x][a] = pa
                    pw[b][x] = pw[x][b] = pb
                s = sn
        if t % LHS_OPT_RECOMPUTE == 0:
            d2, pw, s = _d2_tables(u)
    return s


def _swap_corr(u: list[list[float]], n: int, k: int, rng: random.Random, iterations: int) -> float:
    cols = [[row[j] for row in u] for j in range(k)]
    mu = [sum(c) / n for c in cols]
    sd = [math.sqrt(sum((v - mu[j]) ** 2 for v in cols[j]) / n) for j in range(k)]

    def full() -> tuple[list[list[float]], list[list[float]], float]:
        cp = [[0.0] * k for _ in range(k)]
        r = [[0.0] * k for _ in range(k)]
        s = 0.0
        for a in range(k):
            for m in range(a + 1, k):
                c = sum(x * y for x, y in zip((row[a] for row in u), (row[m] for row in u)))
                cp[a][m] = cp[m][a] = c
                rv = (c / n - mu[a] * mu[m]) / (sd[a] * sd[m]) if sd[a] > 0 and sd[m] > 0 else 0.0
                r[a][m] = r[m][a] = rv
                s += rv * rv
        return cp, r, s

    cp, r, s = full()
    for t in range(1, iterations + 1):
        j = rng.randrange(k)
        a = rng.randrange(n)
        b = rng.randrange(n - 1)
        if b >= a:
            b += 1
        delta = u[b][j] - u[a][j]
        old = new = 0.0
        upd: list[tuple[int, float, float]] = []
        for m in range(k):
            if m == j:
                continue
            c = cp[j][m] + delta * (u[a][m] - u[b][m])
            rv = (c / n - mu[j] * mu[m]) / (sd[j] * sd[m]) if sd[j] > 0 and sd[m] > 0 else 0.0
            old += r[j][m] * r[j][m]
            new += rv * rv
            upd.append((m, c, rv))
        sn = s - old + new
        if sn < s:
            u[a][j], u[b][j] = u[b][j], u[a][j]
            for m, c, rv in upd:
                cp[j][m] = cp[m][j] = c
                r[j][m] = r[m][j] = rv
            s = sn
        if t % LHS_OPT_RECOMPUTE == 0:
            cp, r, s = full()
    return s


def lhs_opt_unit(n: int, k: int, seed: int, criterion: str = "maximin") -> tuple[list[list[float]], dict[str, float]]:
    """최적화 LHS 단위 점 n×k와 {candidate_score(후보 최선), final_score}. 같은 (n, k, seed, criterion)이면 항상 같은 값.

    후보 5개 → S가 엄격히 더 작은 후보 선택 → 열 내 교환 2000회(k ≤ 1이면 0회, 층 유지).
    """
    rng = random.Random(seed)
    best: list[list[float]] | None = None
    best_s = math.inf
    for _ in range(LHS_OPT_CANDIDATES):
        cand = _candidate(rng, n, k)
        sc = lhs_opt_score(cand, criterion)
        if best is None or sc < best_s:
            best, best_s = cand, sc
    assert best is not None
    u = best
    iterations = LHS_OPT_ITERATIONS if k > 1 else 0
    if iterations:
        _swap_corr(u, n, k, rng, iterations) if criterion == "corr" else _swap_maximin(u, n, k, rng, iterations)
    return u, {"candidate_score": best_s, "final_score": lhs_opt_score(u, criterion)}
