"""제약 지배(Deb 2000)·빠른 비지배 정렬·crowding distance·생존 순서(opt-native §6.3) — `evo`에서 재노출(R-B 300줄 분할).
numpy·`pareto`만 쓴다. `FEAS_CV`(실행 가능 판정 CV 허용)는 여기가 원본, `evo.FEAS_CV`로 재노출한다."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from . import pareto

FEAS_CV = 1e-9


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
