"""유전 알고리즘 GA(단일 목적)·NSGA-II(다목적) — opt-native §6(ON-3·ON-5·ON-6·ON-7). numpy만 쓴다.

대리모델을 모른다: 평가 함수 `evaluate(X) -> (F, CV)`를 받는다(X = 원 단위 값 n×n_g, 범주는 수준 인덱스).
- 유전자: 연속·정수는 범위로 [0,1] 정규화, 범주는 수준 인덱스 {0..L−1}. 정수는 변이 뒤 원 단위에서 반올림하고
  [⌈lo⌉, ⌊hi⌋]로 자른다(항상 정수).
- 제약 지배(Deb 2000): 실행 가능(CV ≤ 1e-9) 우선 → CV 작은 쪽 → 둘 다 실행 가능하면 목적 지배.
- 변이 연산자: 이진 토너먼트 → 쌍마다 p_c로 교차(연속·정수 유전자마다 0.5 확률 경계 SBX, 범주 균등 교환) →
  유전자마다 p_m 변이(연속·정수 경계 다항 변이, 범주 다른 수준으로 균등 교체).
- 생존: GA (μ+λ) 엘리트, NSGA-II 빠른 비지배 정렬(제약 지배) + crowding distance.
- 난수: `np.random.default_rng(seed)` 하나에서 고정 순서로 뽑는다(같은 입력·시드 → 같은 집단·history).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from . import pareto
from .algo import default_pop_size  # noqa: F401 - §6.7 기본 집단 크기(재노출)

FEAS_CV = 1e-9
GA_STALL_TOL = 1e-9
NSGA2_STALL_TOL = 1e-6
STOP_MAX_GEN = "MAX_GEN"
STOP_STALL = "STALL"

Evaluate = Callable[[np.ndarray], tuple[np.ndarray, np.ndarray]]


@dataclass(frozen=True)
class Gene:
    """유전자 1개: kind = real | int | cat. 연속·정수는 원 단위 범위 lo~hi, 범주는 수준 수 levels."""

    name: str
    kind: str
    lo: float = 0.0
    hi: float = 1.0
    levels: int = 0

    @property
    def span(self) -> float:
        return self.hi - self.lo


@dataclass(frozen=True)
class EvoOptions:
    pop_size: int
    generations: int
    crossover_prob: float = 0.9
    mutation_prob: float | None = None  # None = 1/n_g
    eta_c: float = 15.0
    eta_m: float = 20.0
    stall_generations: int = 30
    archive_max: int = 5000


@dataclass
class EvoResult:
    X: np.ndarray  # 최종 집단(원 단위, 정렬된 생존 순서)
    F: np.ndarray  # n×m
    CV: np.ndarray
    rank: np.ndarray | None  # NSGA-II만
    crowding: np.ndarray | None
    history: list[dict[str, Any]]
    generations_run: int
    evals: int
    stop: str
    archive: np.ndarray | None = None  # GA만(원 단위, 늦은 세대 우선)
    seed: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


# ---- 유전자 변환 -----------------------------------------------------------------------------------


def _int_bounds(g: Gene) -> tuple[float, float]:
    return float(math.ceil(g.lo - 1e-9)), float(math.floor(g.hi + 1e-9))


def decode(G: np.ndarray, genes: Sequence[Gene]) -> np.ndarray:
    """유전자 행렬(정규화) → 원 단위(정수 반올림·범주 인덱스)."""
    X = np.array(G, dtype=float, copy=True)
    for j, g in enumerate(genes):
        if g.kind == "cat":
            X[:, j] = np.clip(np.round(G[:, j]), 0, max(g.levels - 1, 0))
        else:
            X[:, j] = g.lo + G[:, j] * g.span
            if g.kind == "int":
                a, b = _int_bounds(g)
                X[:, j] = np.clip(np.round(X[:, j]), a, b)
    return X


def encode(X: np.ndarray, genes: Sequence[Gene]) -> np.ndarray:
    """원 단위 → 유전자 행렬(범위 밖은 자른다)."""
    G = np.array(np.atleast_2d(X), dtype=float, copy=True)
    for j, g in enumerate(genes):
        if g.kind == "cat":
            G[:, j] = np.clip(np.round(G[:, j]), 0, max(g.levels - 1, 0))
        else:
            G[:, j] = np.clip((G[:, j] - g.lo) / g.span if g.span > 0 else 0.0, 0.0, 1.0)
    return _snap(G, genes)


def _snap(G: np.ndarray, genes: Sequence[Gene]) -> np.ndarray:
    """정수 유전자를 원 단위 정수에 맞춰 다시 정규화(§6.2 반올림·자르기)."""
    for j, g in enumerate(genes):
        if g.kind == "int" and g.span > 0:
            a, b = _int_bounds(g)
            x = np.clip(np.round(g.lo + G[:, j] * g.span), a, b)
            G[:, j] = (x - g.lo) / g.span
    return G


def lhs_unit(rng: np.random.Generator, n: int, d: int) -> np.ndarray:
    """[0,1]^d 층화 LHS n점(gp.lhs_unit과 같은 식 — evo는 scipy를 불러오지 않는다)."""
    out = np.empty((n, d))
    for j in range(d):
        out[:, j] = (rng.permutation(n) + rng.random(n)) / n
    return out


def initial_population(rng: np.random.Generator, n: int, genes: Sequence[Gene], inject: np.ndarray | None = None,
                       effective: Callable[[np.ndarray], np.ndarray] | None = None) -> np.ndarray:
    """초기 집단(유전자): 연속·정수 LHS, 범주 i mod L 층화 후 섞기, 앞에 주입 설계(⌈0.1·N⌉개, 같은 설계 1개)."""
    num = [j for j, g in enumerate(genes) if g.kind != "cat"]
    G = np.zeros((n, len(genes)))
    if num:
        G[:, num] = lhs_unit(rng, n, len(num))
    for j, g in enumerate(genes):
        if g.kind == "cat":
            G[:, j] = rng.permutation(np.arange(n) % max(g.levels, 1)).astype(float)
    G = _snap(G, genes)
    if inject is not None and len(inject):
        k = int(math.ceil(0.1 * n))
        Gi = encode(np.asarray(inject, dtype=float), genes)
        keep = unique_first(decode(Gi, genes), effective)[:k]
        Gi = Gi[keep]
        G = np.vstack([Gi, G])[:n]
    return G


def unique_first(X: np.ndarray, effective: Callable[[np.ndarray], np.ndarray] | None = None) -> np.ndarray:
    """유효값이 같은 행은 앞 것만 — 남는 인덱스(오름차순)."""
    E = effective(X) if effective is not None else X
    E = np.where(np.isnan(E), np.inf, E) + 0.0  # −0.0 → 0.0, N/A = inf
    _u, idx = np.unique(np.ascontiguousarray(E), axis=0, return_index=True)
    return np.sort(idx)


# ---- 연산자 ----------------------------------------------------------------------------------------


def sbx_pair(y1: np.ndarray, y2: np.ndarray, u: np.ndarray, swap: np.ndarray, eta: float) -> tuple[np.ndarray, np.ndarray]:
    """경계 SBX(Deb–Agrawal, [0,1] 정규화 유전자, 벡터). u·swap ∈ [0,1) 같은 모양. |y1 − y2| ≤ 1e-14면 그대로."""
    a = np.minimum(y1, y2)
    b = np.maximum(y1, y2)
    diff = b - a
    ok = diff > 1e-14
    d = np.where(ok, diff, 1.0)
    e1 = 1.0 / (eta + 1.0)

    def betaq(beta: np.ndarray) -> np.ndarray:
        alpha = 2.0 - np.power(beta, -(eta + 1.0))
        ua = u * alpha
        lo = np.power(np.maximum(ua, 0.0), e1)
        hi = np.power(1.0 / np.maximum(2.0 - ua, 1e-300), e1)
        return np.where(u <= 1.0 / alpha, lo, hi)

    c1 = 0.5 * ((a + b) - betaq(1.0 + 2.0 * a / d) * diff)
    c2 = 0.5 * ((a + b) + betaq(1.0 + 2.0 * (1.0 - b) / d) * diff)
    c1 = np.clip(c1, 0.0, 1.0)
    c2 = np.clip(c2, 0.0, 1.0)
    s = swap < 0.5
    o1 = np.where(s, c2, c1)
    o2 = np.where(s, c1, c2)
    return np.where(ok, o1, y1), np.where(ok, o2, y2)


def poly_mutation(y: np.ndarray, u: np.ndarray, eta: float) -> np.ndarray:
    """경계 다항 변이(Deb, [0,1] 정규화 유전자, 벡터)."""
    d1 = y
    d2 = 1.0 - y
    p = 1.0 / (eta + 1.0)
    low = u <= 0.5
    v1 = 2.0 * u + (1.0 - 2.0 * u) * np.power(np.maximum(1.0 - d1, 0.0), eta + 1.0)
    v2 = 2.0 * (1.0 - u) + 2.0 * (u - 0.5) * np.power(np.maximum(1.0 - d2, 0.0), eta + 1.0)
    dq = np.where(low, np.power(np.maximum(v1, 0.0), p) - 1.0, 1.0 - np.power(np.maximum(v2, 0.0), p))
    return np.clip(y + dq, 0.0, 1.0)


def variation(rng: np.random.Generator, P: np.ndarray, parents: np.ndarray, genes: Sequence[Gene], opt: EvoOptions
              ) -> np.ndarray:
    """부모 인덱스(짝수 개) → 자식 유전자. 난수는 매번 같은 모양으로 고정 순서로 뽑는다."""
    n, ng = len(parents), len(genes)
    half = n // 2
    cat = np.array([g.kind == "cat" for g in genes])
    L = np.array([max(g.levels, 1) for g in genes], dtype=float)
    u_pair = rng.random(half)
    u_gene = rng.random((half, ng))
    u_sbx = rng.random((half, ng))
    u_swap = rng.random((half, ng))
    u_mut = rng.random((n, ng))
    u_poly = rng.random((n, ng))
    u_lvl = rng.random((n, ng))
    A = P[parents[0::2]].copy()
    B = P[parents[1::2]].copy()
    do = (u_pair < opt.crossover_prob)[:, None]
    num = do & ~cat[None, :] & (u_gene < 0.5)
    zc = cat[None, :]  # 범주 열은 0으로 바꿔 계산(결과는 버린다)
    with np.errstate(all="ignore"):
        c1, c2 = sbx_pair(np.where(zc, 0.0, A), np.where(zc, 0.0, B), u_sbx, u_swap, opt.eta_c)
    A2 = np.where(num, c1, A)
    B2 = np.where(num, c2, B)
    cx = do & cat[None, :] & (u_gene < 0.5)  # 범주: 0.5 확률 교환
    A3 = np.where(cx, B, A2)
    B3 = np.where(cx, A, B2)
    C = np.empty((n, ng))
    C[0::2] = A3
    C[1::2] = B3
    pm = opt.mutation_prob if opt.mutation_prob is not None else 1.0 / max(ng, 1)
    mut = u_mut < pm
    with np.errstate(all="ignore"):
        Cm = poly_mutation(np.where(cat[None, :], 0.0, C), u_poly, opt.eta_m)
    C = np.where(mut & ~cat[None, :], Cm, C)
    off = 1.0 + np.floor(u_lvl * (L[None, :] - 1.0))
    newlvl = np.mod(np.round(C) + off, L[None, :])
    C = np.where(mut & cat[None, :] & (L[None, :] > 1), newlvl, C)
    return _snap(C, genes)


# ---- 제약 지배·정렬 --------------------------------------------------------------------------------


def feasible(cv: np.ndarray) -> np.ndarray:
    return np.asarray(cv) <= FEAS_CV


def cdominates(fa: Sequence[float], cva: float, fb: Sequence[float], cvb: float) -> bool:
    """제약 지배 a ≺ b(§6.2): (a 실행 가능 ∧ b 불가) ∨ (둘 다 불가 ∧ CV_a < CV_b) ∨ (둘 다 가능 ∧ 목적 지배)."""
    a_ok, b_ok = cva <= FEAS_CV, cvb <= FEAS_CV
    if a_ok and not b_ok:
        return True
    if not a_ok and not b_ok:
        return cva < cvb
    if not a_ok:
        return False
    return pareto.dominates(list(np.atleast_1d(fa)), list(np.atleast_1d(fb)))


def dom_matrix(F: np.ndarray, CV: np.ndarray) -> np.ndarray:
    """D[i, j] = i ≺ j(제약 지배, 벡터)."""
    F = np.atleast_2d(F.T).T if F.ndim == 1 else F
    ok = feasible(CV)
    le = np.all(F[:, None, :] <= F[None, :, :], axis=2)
    lt = np.any(F[:, None, :] < F[None, :, :], axis=2)
    objdom = le & lt
    both_ok = ok[:, None] & ok[None, :]
    i_ok_j_bad = ok[:, None] & ~ok[None, :]
    both_bad = ~ok[:, None] & ~ok[None, :]
    cvlt = CV[:, None] < CV[None, :]
    return (both_ok & objdom) | i_ok_j_bad | (both_bad & cvlt)


def nondominated_sort(F: np.ndarray, CV: np.ndarray) -> list[np.ndarray]:
    """빠른 비지배 정렬(Deb 2002, 제약 지배) — front 목록(각 front 인덱스 오름차순)."""
    n = len(CV)
    if n == 0:
        return []
    D = dom_matrix(F, CV)
    count = D.sum(axis=0).astype(int)  # 나를 지배하는 수
    fronts: list[np.ndarray] = []
    cur = np.flatnonzero(count == 0)
    assigned = np.zeros(n, dtype=bool)
    while cur.size:
        fronts.append(cur)
        assigned[cur] = True
        count = count - D[cur].sum(axis=0)
        cur = np.flatnonzero((count == 0) & ~assigned)
    return fronts


def ranks_of(fronts: Sequence[np.ndarray], n: int) -> np.ndarray:
    r = np.zeros(n, dtype=int)
    for k, fr in enumerate(fronts):
        r[fr] = k + 1
    return r


def crowding_distance(F: np.ndarray) -> np.ndarray:
    """front 안 crowding distance: 목적별 min–max 정규화, 경계 = ∞(동률 정렬은 인덱스)."""
    n, m = F.shape
    d = np.zeros(n)
    if n <= 2:
        return np.full(n, np.inf)
    for i in range(m):
        order = np.argsort(F[:, i], kind="stable")
        f = F[order, i]
        span = f[-1] - f[0]
        d[order[0]] = np.inf
        d[order[-1]] = np.inf
        if span > 0:
            inner = (f[2:] - f[:-2]) / span
            d[order[1:-1]] = d[order[1:-1]] + inner
    return d


def _ga_key(F: np.ndarray, CV: np.ndarray) -> np.ndarray:
    """GA 정렬 순서(실행 가능 우선, CV, f, 인덱스)."""
    ok = feasible(CV)
    f = F.reshape(len(CV), -1)[:, 0]
    return np.lexsort((np.arange(len(CV)), np.where(ok, f, 0.0), np.where(ok, 0.0, CV), ~ok))


def nsga2_order(F: np.ndarray, CV: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(전체 정렬 순서, rank, crowding) — rank 오름차순, front 안 crowding 내림차순, 인덱스."""
    n = len(CV)
    fronts = nondominated_sort(F, CV)
    rank = ranks_of(fronts, n)
    crowd = np.zeros(n)
    for fr in fronts:
        crowd[fr] = crowding_distance(F[fr])
    order = np.lexsort((np.arange(n), -crowd, rank))
    return order, rank, crowd


def rank_order(F: np.ndarray, CV: np.ndarray) -> np.ndarray:
    """제약 지배 상위 순서(시드 주입용): 단일 = GA 순서, 다목적 = NSGA-II 순서."""
    F2 = F.reshape(len(CV), -1)
    return _ga_key(F2, CV) if F2.shape[1] == 1 else nsga2_order(F2, CV)[0]


# ---- 메인 루프 --------------------------------------------------------------------------------------


def _eval(evaluate: Evaluate, X: np.ndarray, m: int) -> tuple[np.ndarray, np.ndarray]:
    F, CV = evaluate(X)
    F = np.asarray(F, dtype=float).reshape(len(X), m)
    CV = np.maximum(np.asarray(CV, dtype=float).reshape(len(X)), 0.0)
    F = np.where(np.isfinite(F), F, 1e300)
    CV = np.where(np.isfinite(CV), CV, 1e300)
    return F, CV


def _tournament(rng: np.random.Generator, n: int, better: Callable[[np.ndarray, np.ndarray], np.ndarray]) -> np.ndarray:
    pairs = rng.integers(0, n, size=(n, 2))
    a, b = pairs[:, 0], pairs[:, 1]
    return np.where(better(a, b), a, b)


def _hv(F: np.ndarray, ref: Sequence[float]) -> float:
    if len(F) == 0:
        return 0.0
    return float(pareto.hypervolume(F.tolist(), list(ref)))


def run(evaluate: Evaluate, genes: Sequence[Gene], *, m: int, options: EvoOptions, seed: int,
        inject: np.ndarray | None = None, hv_ref: Sequence[float] | None = None,
        effective: Callable[[np.ndarray], np.ndarray] | None = None,
        progress: Callable[[int, int], None] | None = None, checkpoint: Callable[[], None] | None = None) -> EvoResult:
    """m = 1 → GA, m ≥ 2 → NSGA-II. inject = 주입 설계(원 단위, 제약 지배 순으로 정렬된 것). hv_ref = NSGA-II 정체 판정
    HV 기준점(None = [1.1]·m). effective = 유효값(N/A 마스크, 중복 판정)."""
    if not genes:
        raise ValueError("유전자가 없습니다")
    N = int(options.pop_size)
    if N < 2 or N % 2:
        raise ValueError("집단 크기는 2 이상 짝수여야 합니다")
    multi = m >= 2
    ref = list(hv_ref) if hv_ref is not None else [1.1] * m
    rng = np.random.default_rng(seed)
    G = initial_population(rng, N, genes, inject, effective)
    X = decode(G, genes)
    F, CV = _eval(evaluate, X, m)
    evals = N
    history: list[dict[str, Any]] = []
    archive_gens: list[np.ndarray] = []
    stall = 0
    stop = STOP_MAX_GEN
    gen_run = 0
    rank = crowd = None
    if multi:
        order, rank, crowd = nsga2_order(F, CV)
    prev_best: tuple[bool, float, float] | None = None
    prev_hv: float | None = None

    def ga_best(F_: np.ndarray, CV_: np.ndarray) -> tuple[bool, float, float]:
        i = int(_ga_key(F_, CV_)[0])
        return bool(feasible(CV_[i:i + 1])[0]), float(CV_[i]), float(F_[i, 0])

    def record(gen: int) -> None:
        nonlocal prev_best, prev_hv, stall
        okm = feasible(CV)
        if multi:
            r1 = (rank == 1) & okm  # type: ignore[operator]
            hv = _hv(F[r1], ref)
            history.append({"gen": gen, "evals": evals, "n_feasible": int(okm.sum()), "front_size": int(r1.sum()),
                            "hv_pred": hv})
            if gen > 0:
                if prev_hv is not None and prev_hv > 0 and (hv - prev_hv) / prev_hv < NSGA2_STALL_TOL:
                    stall += 1
                else:
                    stall = 0
            prev_hv = hv
        else:
            b = ga_best(F, CV)
            history.append({"gen": gen, "evals": evals, "n_feasible": int(okm.sum()),
                            "best_pred": b[2] if b[0] else None, "mean_pred": float(np.mean(F[:, 0]))})
            if gen > 0 and prev_best is not None:
                if b[0] and not prev_best[0]:
                    imp = 1.0
                elif not b[0]:
                    imp = (prev_best[1] - b[1]) / max(abs(prev_best[1]), 1e-12)
                else:
                    imp = (prev_best[2] - b[2]) / max(abs(prev_best[2]), 1e-12)
                stall = stall + 1 if imp < GA_STALL_TOL else 0
            prev_best = b

    if not multi:
        o = _ga_key(F, CV)
        G, X, F, CV = G[o], X[o], F[o], CV[o]
    else:
        G, X, F, CV, rank, crowd = G[order], X[order], F[order], CV[order], rank[order], crowd[order]
    archive_gens.append(X.copy())
    record(0)
    for gen in range(1, options.generations + 1):
        if checkpoint is not None:
            checkpoint()
        if multi:
            rk, cd = rank, crowd

            def better(a: np.ndarray, b: np.ndarray, rk: np.ndarray = rk, cd: np.ndarray = cd) -> np.ndarray:  # type: ignore[assignment]
                return (rk[a] < rk[b]) | ((rk[a] == rk[b]) & ((cd[a] > cd[b]) | ((cd[a] == cd[b]) & (a <= b))))
        else:
            # 집단은 GA 순서로 정렬돼 있다 — 앞 인덱스가 제약 지배상 같거나 낫다
            def better(a: np.ndarray, b: np.ndarray) -> np.ndarray:  # type: ignore[misc]
                return a <= b
        parents = _tournament(rng, N, better)
        C = variation(rng, G, parents, genes, options)
        Xc = decode(C, genes)
        Fc, CVc = _eval(evaluate, Xc, m)
        evals += N
        GA_ = np.vstack([G, C])
        XA = np.vstack([X, Xc])
        FA = np.vstack([F, Fc])
        CVA = np.concatenate([CV, CVc])
        keep = unique_first(XA, effective)
        dropped = np.setdiff1d(np.arange(len(XA)), keep)
        if multi:
            o, rk2, cd2 = nsga2_order(FA[keep], CVA[keep])
            sel = keep[o][:N]
            if len(sel) < N:
                sel = np.concatenate([sel, dropped[: N - len(sel)]])
            # 생존 집단의 rank·crowding은 생존 집합 기준으로 다시 계산(다음 토너먼트·출력)
            G, X, F, CV = GA_[sel], XA[sel], FA[sel], CVA[sel]
            o2, rank, crowd = nsga2_order(F, CV)
            G, X, F, CV, rank, crowd = G[o2], X[o2], F[o2], CV[o2], rank[o2], crowd[o2]
        else:
            o = _ga_key(FA[keep], CVA[keep])
            sel = keep[o][:N]
            if len(sel) < N:
                sel = np.concatenate([sel, dropped[: N - len(sel)]])
            G, X, F, CV = GA_[sel], XA[sel], FA[sel], CVA[sel]
            o2 = _ga_key(F, CV)
            G, X, F, CV = G[o2], X[o2], F[o2], CV[o2]
        archive_gens.append(X.copy())
        gen_run = gen
        record(gen)
        if progress is not None:
            progress(gen, options.generations)
        if stall >= options.stall_generations:
            stop = STOP_STALL
            break
    archive = None
    if not multi:
        rows: list[np.ndarray] = []
        seen: set[bytes] = set()
        for Xg in reversed(archive_gens):
            Eg = effective(Xg) if effective is not None else Xg
            Eg = np.where(np.isnan(Eg), np.inf, Eg) + 0.0
            for x, e in zip(Xg, Eg):
                key = np.ascontiguousarray(e).tobytes()
                if key in seen:
                    continue
                seen.add(key)
                rows.append(x)
                if len(rows) >= options.archive_max:
                    break
            if len(rows) >= options.archive_max:
                break
        archive = np.array(rows) if rows else np.zeros((0, len(genes)))
    return EvoResult(X, F, CV, rank if multi else None, crowd if multi else None, history, gen_run, evals, stop,
                     archive, seed)


# ---- 기록 -----------------------------------------------------------------------------------------


def history_csv_rows(history: Sequence[dict[str, Any]], multi: bool) -> tuple[list[str], list[list[str]]]:
    """algo_history.csv 머리·행(§6.6). 값은 repr(재현 가능)."""
    head = ["gen", "evals", "n_feasible", *(["front_size", "hv_pred"] if multi else ["best_pred", "mean_pred"])]

    def s(v: Any) -> str:
        return "" if v is None else (repr(float(v)) if isinstance(v, float) else str(v))

    return head, [[s(h.get(k)) for k in head] for h in history]
