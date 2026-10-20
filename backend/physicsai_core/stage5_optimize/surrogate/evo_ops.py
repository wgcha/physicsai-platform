"""GA·NSGA-II 유전자·연산자(opt-native §6.2~§6.4) — `evo`에서 재노출(R-B 300줄 분할, 동작 불변). numpy만 쓴다.

유전자 정의(`Gene`)·옵션(`EvoOptions`)·정규화 변환(`decode`·`encode`)·초기 집단(LHS·주입)·SBX·다항 변이·`variation`."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np


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
