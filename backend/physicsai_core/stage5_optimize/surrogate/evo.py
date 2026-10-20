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

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from . import pareto
from .algo import default_pop_size  # noqa: F401 - §6.7 기본 집단 크기(재노출)
from .evo_ops import (  # noqa: F401 - 300줄 분할(R-B): 유전자·연산자, 기존 경로 재노출
    EvoOptions, Gene, _int_bounds, _snap, decode, encode, initial_population, lhs_unit, poly_mutation, sbx_pair, unique_first,
    variation,
)
from .evo_sort import (  # noqa: F401 - 300줄 분할(R-B): 제약 지배·정렬, 기존 경로 재노출
    FEAS_CV, _ga_key, cdominates, crowding_distance, dom_matrix, feasible, nondominated_sort, nsga2_order, rank_order, ranks_of,
)

GA_STALL_TOL = 1e-9
NSGA2_STALL_TOL = 1e-6
STOP_MAX_GEN = "MAX_GEN"
STOP_STALL = "STALL"

Evaluate = Callable[[np.ndarray], tuple[np.ndarray, np.ndarray]]


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
