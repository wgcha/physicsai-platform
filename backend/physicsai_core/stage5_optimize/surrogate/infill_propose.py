"""⑤ 후보 제안(EI × PoF, DE, RBF 거리 규칙)과 제약 판정 — infill에서 재노출."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.optimize import differential_evolution
from scipy.stats import norm

from .dataset import Constraint, Design, Problem, canonical_values, same_design
from .infill_model import (
    _DE_PARAMS, PENALTY, RBF_MIN_DIST, RBF_MIN_DIST_FLOOR, FitResult, Scaled, SurrogateError, cat_index, de_levels, level_seeds,
)

# ---- 후보 ----------------------------------------------------------------------------------------


@dataclass
class Candidate:
    values: dict[str, float]
    predicted: float
    ei: float | None
    constraints_pred: list[float]

    def as_dict(self, doe_no: int | None = None) -> dict[str, Any]:
        d: dict[str, Any] = {"values": self.values, "predicted": self.predicted, "ei": self.ei,
                             "constraints_pred": self.constraints_pred}
        if doe_no is not None:
            d = {"doe_no": doe_no, **d}
        return d


def _de(func: Callable[[np.ndarray], np.ndarray], bounds: list[tuple[float, float]], integrality: np.ndarray, *, seed: int,
        maxiter: int, popsize: int, checkpoint: Callable[[], None] | None) -> np.ndarray:
    kw: dict[str, Any] = {"rng": seed} if "rng" in _DE_PARAMS else {"seed": seed}

    def cb(*_a: Any, **_k: Any) -> None:
        if checkpoint is not None:
            checkpoint()

    has_int = bool(np.any(integrality))
    r = differential_evolution(func, bounds, maxiter=maxiter, popsize=popsize, vectorized=True, updating="deferred",
                               polish=not has_int, integrality=integrality if has_int else None, callback=cb, tol=1e-8,
                               **kw)
    return np.asarray(r.x, dtype=float)


def cons_violation(c: Constraint, m: np.ndarray) -> np.ndarray:
    """예측 위반량(원 단위, 벡터) — dataset.Constraint.violation과 같은 식(range 포함)."""
    if c.op == "range":
        return np.maximum(0.0, float(c.lo) - m) + np.maximum(0.0, m - float(c.hi))  # type: ignore[arg-type]
    return np.maximum(0.0, m - float(c.value)) if c.op == "<=" else np.maximum(0.0, float(c.value) - m)  # type: ignore[arg-type]


def cons_pof(c: Constraint, m: np.ndarray, s: np.ndarray) -> np.ndarray:
    """만족 확률: ≤ Φ((c−μ)/σ), ≥ 1 − Φ((c−μ)/σ), range Φ((hi−μ)/σ) − Φ((lo−μ)/σ)."""
    s = np.maximum(s, 1e-12)
    if c.op == "range":
        return np.maximum(0.0, norm.cdf((float(c.hi) - m) / s) - norm.cdf((float(c.lo) - m) / s))  # type: ignore[arg-type]
    z = (float(c.value) - m) / s  # type: ignore[arg-type]
    return norm.cdf(z) if c.op == "<=" else norm.sf(z)


def cons_ok(c: Constraint, v: float) -> bool:
    """예측 평균이 제약을 만족하는지(kriging believer의 fmin 갱신용)."""
    return c.violation(v) <= 0.0


def _ei(mean: np.ndarray, std: np.ndarray, fmin: float) -> np.ndarray:
    s = np.maximum(std, 1e-12)
    z = (fmin - mean) / s
    return (fmin - mean) * norm.cdf(z) + s * norm.pdf(z)


def propose(fit: FitResult, problem: Problem, designs: Sequence[Design], failed: Sequence[dict[str, float]], *, k: int,
            seed: int, round_no: int, de_maxiter: int, de_popsize: int,
            progress: Callable[[int, int], None] | None = None,
            checkpoint: Callable[[], None] | None = None) -> tuple[list[Candidate], Candidate | None]:
    """후보 최대 k개와 대리모델 최적(활용 후보, 중복이어도 참고로 돌려줌)."""
    free = fit.free
    d = len(free)
    ints = np.array([n in problem.integer for n in free])
    bounds: list[tuple[float, float]] = []
    for n, lo, hi, isint in zip(free, fit.lo, fit.hi, ints):
        b = (float(math.ceil(lo - 1e-9)), float(math.floor(hi + 1e-9))) if isint else (float(lo), float(hi))
        if b[0] > b[1]:
            raise SurrogateError("BOUNDS_INVALID", f"'{n}' 정수 범위가 비어 있습니다")
        bounds.append(b)
    span = np.array([b[1] - b[0] for b in bounds])
    if np.all(span <= 0):
        raise SurrogateError("NO_FREE_VARIABLE", "탐색할 변수가 없습니다")
    existing = [dict(x.values) for x in designs] + [dict(f) for f in failed]
    cons = problem.constraints
    obj = fit.objective
    cmods = list(fit.constraints)
    picked: list[Candidate] = []
    base_seed = seed * 1000 + round_no

    def cons_raw(models: list[Scaled], Xn: np.ndarray) -> list[tuple[np.ndarray, np.ndarray]]:
        return [m.raw(Xn) for m in models]

    def penalty(cr: list[tuple[np.ndarray, np.ndarray]], models: list[Scaled]) -> np.ndarray:
        p = np.zeros(cr[0][0].shape if cr else 1)
        for (m, _s), c, sm in zip(cr, cons, models):
            p = p + cons_violation(c, m) / max(sm.std, 1e-12)
        return p

    def round_x(x: np.ndarray) -> np.ndarray:
        x = np.array(x, dtype=float)
        x[ints] = np.round(x[ints])
        return np.clip(x, [b[0] for b in bounds], [b[1] for b in bounds])

    def make(x: np.ndarray, models_o: Scaled, models_c: list[Scaled], ei: float | None) -> Candidate:
        Xn = fit.normalize(x)
        m, _ = models_o.raw(Xn)
        cr = cons_raw(models_c, Xn)
        vals = fit.full_values(x)
        for n in problem.integer:
            if n in vals:
                vals[n] = float(round(vals[n]))
        vals = canonical_values(vals, problem.cat_spec)
        return Candidate(vals, float(fit.sign * m[0]), ei, [float(c[0][0]) for c in cr])

    def is_dup(vals: dict[str, float]) -> bool:
        return any(same_design(vals, e, problem) for e in existing) or any(same_design(vals, c.values, problem) for c in picked)

    def step(j: int) -> None:
        if progress is not None:
            progress(min(len(picked) + 1, k), k)
        if checkpoint is not None:
            checkpoint()

    # ① 활용
    step(0)

    def f_exploit(xT: np.ndarray) -> np.ndarray:
        Xn = fit.normalize(np.atleast_2d(xT.T))
        m, _ = obj.model.predict(Xn)
        if not cons:
            return m
        return m + PENALTY * penalty(cons_raw(cmods, Xn), cmods)

    cj, nl = cat_index(fit)

    def run_de(func: Callable[[np.ndarray], np.ndarray], seed_: int, j_: int) -> np.ndarray:
        if cj is None:
            return _de(func, bounds, ints, seed=seed_, maxiter=de_maxiter, popsize=de_popsize, checkpoint=checkpoint)
        return de_levels(_de, func, bounds, ints, cj, nl, level_seeds(seed, round_no, j_, nl), maxiter=de_maxiter,
                         popsize=de_popsize, checkpoint=checkpoint)

    x_opt = round_x(run_de(f_exploit, base_seed, 0))
    optimum = make(x_opt, obj, cmods, None)
    if not is_dup(optimum.values):
        picked.append(optimum)
    attempts = 0
    j = 1
    if fit.kind == "gp":
        valid_obj = np.array([fit.sign * x.objective for x in designs])
        feas = [i for i, x in enumerate(designs) if all(
            c.violation(v) <= 1e-9 * max([1.0, *[abs(b) for b in c.bounds()]]) for v, c in zip(x.constraints, cons))]
        fmin_std = float((np.min(valid_obj[feas]) - obj.mean) / obj.std) if feas else None
        om, cms = obj, list(cmods)

        def believe(xn: np.ndarray) -> None:
            """가짜 관측(예측 평균)을 더하고, 예측상 제약을 만족하면 현재 최선(fmin)도 그 값으로 갱신."""
            nonlocal om, cms, fmin_std
            mo = om.model.predict(xn)[0]
            ok = all(cons_ok(c, float(m)) for c, m in zip(cons, [cm.raw(xn)[0][0] for cm in cms]))
            om = Scaled(om.model.with_points(xn, mo), om.mean, om.std)
            cms = [Scaled(cm.model.with_points(xn, cm.model.predict(xn)[0]), cm.mean, cm.std) for cm in cms]
            if ok:
                fmin_std = float(mo[0]) if fmin_std is None else min(fmin_std, float(mo[0]))

        for c in picked:  # 활용 후보도 believer로 더한다
            believe(fit.normalize(np.array([c.values[n] for n in free])))
        while len(picked) < k and attempts < 3 * k:
            attempts += 1
            step(j)
            om_, cms_, fmin_ = om, cms, fmin_std

            def acq(xT: np.ndarray, om_: Scaled = om_, cms_: list[Scaled] = cms_, fmin_: float | None = fmin_) -> np.ndarray:
                Xn = fit.normalize(np.atleast_2d(xT.T))
                m, s = om_.model.predict(Xn)
                pof = np.ones(Xn.shape[0])
                for c, cm in zip(cons, cms_):
                    mc, sc = cm.raw(Xn)
                    pof = pof * cons_pof(c, mc, sc)
                a = pof if fmin_ is None else _ei(m, s, fmin_) * pof
                return -a

            x = round_x(run_de(acq, base_seed + 100 * j, j))
            j += 1
            ei_val = float(-acq(x.reshape(-1, 1))[0])
            cand = make(x, om, cms, ei_val * obj.std if fmin_ is not None else ei_val)
            believe(fit.normalize(x))
            if not is_dup(cand.values):
                picked.append(cand)
    else:
        dmin = RBF_MIN_DIST
        while len(picked) < k and dmin >= RBF_MIN_DIST_FLOOR and attempts < 4 * k + 8:
            attempts += 1
            step(j)
            ref = np.array([fit.normalize(np.array([e[n] for n in free]))[0] for e in existing + [c.values for c in picked]
                            if all(n in e for n in free)])

            def f_rbf(xT: np.ndarray, ref: np.ndarray = ref, dmin: float = dmin) -> np.ndarray:
                Xn = fit.normalize(np.atleast_2d(xT.T))
                m, _ = obj.model.predict(Xn)
                if cons:
                    m = m + PENALTY * penalty(cons_raw(cmods, Xn), cmods)
                dist = np.sqrt(((Xn[:, None, :] - ref[None, :, :]) ** 2).sum(axis=2)).min(axis=1) / math.sqrt(d)
                return m + 1e6 * np.maximum(0.0, dmin - dist)

            x = round_x(run_de(f_rbf, base_seed + 100 * j, j))
            j += 1
            xn = fit.normalize(x)[0]
            dist = float(np.sqrt(((ref - xn) ** 2).sum(axis=1)).min() / math.sqrt(d)) if len(ref) else math.inf
            cand = make(x, obj, cmods, None)
            if dist + 1e-12 >= dmin and not is_dup(cand.values):
                picked.append(cand)
            else:
                dmin /= 2.0
    return picked[:k], optimum
