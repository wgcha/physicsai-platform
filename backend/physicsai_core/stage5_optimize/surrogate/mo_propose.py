"""다목적 후보 모양(MoCandidate·MoProposal)·ParEGO 가중치 배정·c₁ 순서·DE 문맥(§22.5) — mo_infill에서 재노출."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy.optimize import differential_evolution

from . import pareto
from .dataset import Design, Problem, canonical_values, same_design
from .infill import (
    _DE_PARAMS,
    FitResult,
    SurrogateError,
    cons_pof,
    cons_violation,
)
from .mo_frame import HVI_ZERO

# ---- 후보(SO_PROPOSE) ----------------------------------------------------------------------------


@dataclass
class MoCandidate:
    values: dict[str, float]
    role: str  # hvi | parego | rbf
    weight: list[float] | None
    mean: list[float]  # 원 단위·원 부호
    std: list[float]
    acq: float | None
    constraints_pred: list[float]

    def as_dict(self, doe_no: int | None = None) -> dict[str, Any]:
        d: dict[str, Any] = {"values": self.values, "predicted": self.mean[0], "ei": self.acq if self.role == "parego" else None,
                             "constraints_pred": self.constraints_pred, "role": self.role, "weight": self.weight,
                             "predicted_objectives": self.mean, "predicted_std": self.std, "acq": self.acq}
        return {"doe_no": doe_no, **d} if doe_no is not None else d


@dataclass
class MoProposal:
    candidates: list[MoCandidate]
    predicted_front: list[dict[str, Any]]
    used_weights: list[int]
    seeds: dict[str, Any] = field(default_factory=dict)
    warnings: list[dict[str, str]] = field(default_factory=list)


def assign_weights(n_w: int, k: int, *, seed: int, round_no: int, used: Sequence[int]) -> tuple[list[int], list[int]]:
    """ParEGO 가중치 배정(§22.5.4 ②): 순열 π_r = default_rng(seed·1000 + r).permutation(n_w)에서 used를 건너뛰고 k개.
    다 쓰면 used를 비우고 다시. (고른 인덱스, 갱신된 used)."""
    perm = [int(x) for x in np.random.default_rng(seed * 1000 + round_no).permutation(n_w)]
    used_l = [int(u) for u in used if 0 <= int(u) < n_w]
    chosen: list[int] = []
    while len(chosen) < min(k, n_w):
        free = [j for j in perm if j not in used_l and j not in chosen]
        if not free:
            used_l = []
            free = [j for j in perm if j not in chosen]
            if not free:
                break
        chosen.append(free[0])
        used_l.append(free[0])
    return chosen, used_l


def c1_order(pred: Sequence[Sequence[float]], front: Sequence[Sequence[float]], ref: Sequence[float]
             ) -> list[tuple[int, float]]:
    """c₁ 순위(§22.5.4 ①): 예측 점(HV 틀 f̂)마다 HVI = HV(F ∪ {p}) − HV(F). 최대 HVI 순, 모든 HVI ≤ 1e-12면 F까지
    최소 거리가 큰 순(동률은 앞 인덱스). [(인덱스, HVI)]."""
    scored = []
    for i, p in enumerate(pred):
        hvi = pareto.hv_improvement(front, p, ref)
        dist = min((math.dist(p, q) for q in front), default=math.inf)
        scored.append((hvi, dist, i))
    if scored and max(s[0] for s in scored) > HVI_ZERO:
        order = sorted(scored, key=lambda t: (-t[0], t[2]))
    else:
        order = sorted(scored, key=lambda t: (-t[1], t[2]))
    return [(i, hvi) for hvi, _d, i in order]


def _de_full(func: Callable[[np.ndarray], np.ndarray], bounds: list[tuple[float, float]], ints: np.ndarray, *, seed: int,
             maxiter: int, popsize: int, checkpoint: Callable[[], None] | None) -> list[np.ndarray]:
    """DE(§18.5 `_de`와 같은 설정) → 최종 집단을 에너지 오름차순으로(첫째 = 최적)."""
    kw: dict[str, Any] = {"rng": seed} if "rng" in _DE_PARAMS else {"seed": seed}

    def cb(*_a: Any, **_k: Any) -> None:
        if checkpoint is not None:
            checkpoint()

    has_int = bool(np.any(ints))
    r = differential_evolution(func, bounds, maxiter=maxiter, popsize=popsize, vectorized=True, updating="deferred",
                               polish=not has_int, integrality=ints if has_int else None, callback=cb, tol=1e-8, **kw)
    out = [np.asarray(r.x, dtype=float)]
    pop = getattr(r, "population", None)
    en = getattr(r, "population_energies", None)
    if pop is not None and en is not None:
        out += [np.asarray(pop[i], dtype=float) for i in np.argsort(en, kind="stable")]
    return out


class _Ctx:
    """후보 탐색 공용 상태: 경계·정수·정규화·예측."""

    def __init__(self, fit: FitResult, problem: Problem, designs: Sequence[Design], failed: Sequence[dict[str, float]]) -> None:
        self.fit, self.problem = fit, problem
        free = fit.free
        self.ints = np.array([n in problem.integer for n in free])
        self.bounds: list[tuple[float, float]] = []
        for n, lo, hi, isint in zip(free, fit.lo, fit.hi, self.ints):
            b = (float(math.ceil(lo - 1e-9)), float(math.floor(hi + 1e-9))) if isint else (float(lo), float(hi))
            if b[0] > b[1]:
                raise SurrogateError("BOUNDS_INVALID", f"'{n}' 정수 범위가 비어 있습니다")
            self.bounds.append(b)
        if all(b[1] - b[0] <= 0 for b in self.bounds):
            raise SurrogateError("NO_FREE_VARIABLE", "탐색할 변수가 없습니다")
        self.existing = [dict(x.values) for x in designs] + [dict(f) for f in failed]
        self.picked: list[MoCandidate] = []
        self.objs = fit.objectives or [fit.objective]
        self.signs = np.asarray(fit.signs or [fit.sign])
        self.cons = problem.constraints

    def round_x(self, x: np.ndarray) -> np.ndarray:
        x = np.array(x, dtype=float)
        x[self.ints] = np.round(x[self.ints])
        return np.clip(x, [b[0] for b in self.bounds], [b[1] for b in self.bounds])

    def values(self, x: np.ndarray) -> dict[str, float]:
        vals = self.fit.full_values(x)
        for n in self.problem.integer:
            if n in vals:
                vals[n] = float(round(vals[n]))
        return canonical_values(vals, self.problem.cat_spec)

    def is_dup(self, vals: dict[str, float]) -> bool:
        return any(same_design(vals, e, self.problem) for e in self.existing) or \
            any(same_design(vals, c.values, self.problem) for c in self.picked)

    def mu(self, Xn: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """(평균, 표준편차) n×m — 부호 통일(최소화) 원 단위."""
        ms, ss = zip(*[o.raw(Xn) for o in self.objs])
        return np.stack(ms, axis=1), np.stack(ss, axis=1)

    def penalty(self, Xn: np.ndarray) -> np.ndarray:
        p = np.zeros(Xn.shape[0])
        for c, cm in zip(self.cons, self.fit.constraints):
            m, _s = cm.raw(Xn)
            p = p + cons_violation(c, m) / max(cm.std, 1e-12)
        return p

    def pof(self, Xn: np.ndarray, each: bool = False) -> np.ndarray:
        out = np.ones((Xn.shape[0], max(1, len(self.cons))))
        for j, (c, cm) in enumerate(zip(self.cons, self.fit.constraints)):
            m, s = cm.raw(Xn)
            out[:, j] = cons_pof(c, m, s)
        return out if each else out.prod(axis=1)

    def make(self, x: np.ndarray, role: str, weight: list[float] | None, acq: float | None) -> MoCandidate:
        Xn = self.fit.normalize(x)
        mu, sd = self.mu(Xn)
        cp = [float(cm.raw(Xn)[0][0]) for cm in self.fit.constraints]
        return MoCandidate(self.values(x), role, weight, [float(s * v) for s, v in zip(self.signs, mu[0])],
                           [float(v) for v in sd[0]], acq, cp)
