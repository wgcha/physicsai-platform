"""다목적 대리모델·후보(phase3 §22.5 S17) — numpy·scipy(워커 전용, API는 import하지 않는다).

- `fit_mo`: 목적마다 GP 1개(부호 통일 = 최소화) + 제약마다 1개(§18.5와 같은 Matérn 5/2 ARD). GP 실패는 그 모델만 RBF + 경고.
- `propose_mo`: ① 예측 전선 = Das–Dennis 격자 가중치마다 증강 Chebyshev(작업 정규화 μ̃) + 제약 벌점을 DE로 최소화 →
  예측 만족(PoF ≥ 0.5)·μ 비지배 점 ② 후보 c₁ = 검증 전선 대비 HVI 최대(0이면 목적 공간 거리 최대) ③ c₂… = ParEGO
  (반복마다 순열로 배정한 가중치의 스칼라화 GP, EI × Π PoF) — RBF면 s_w(RBF) 최소 + 거리 규칙.
- `run_offline`: 해석 함수를 평가기로 쓰는 루프(시험 전용, V3-S17-7).
시드 식은 §22.5.7. 같은 자료·설정·시드면 같은 후보(같은 numpy/scipy 기준).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy.optimize import differential_evolution

from . import pareto
from .dataset import Design, Point, Problem, free_variables, is_feasible, merge, same_design
from .gp import GPFitError, fit_gp, lhs_unit
from .infill import (
    _DE_PARAMS,
    PENALTY,
    RBF_MIN_DIST,
    RBF_MIN_DIST_FLOOR,
    FitResult,
    Scaled,
    SurrogateError,
    _ei,
    _standardize,
    cons_pof,
    cons_violation,
    quality,
)
from .rbf import RBFFitError, fit_rbf

HVI_ZERO = 1e-12


@dataclass(frozen=True)
class MoCfg:
    h2: int = 10
    h3: int = 6
    de_maxiter: int = 100
    de_popsize: int = 15
    rho: float = 0.05
    ref_offset: float = 0.1
    gp_restarts: int = 4

    @classmethod
    def from_settings(cls, so: Any) -> MoCfg:
        return cls(so.mo_lattice_h2, so.mo_lattice_h3, so.mo_de_maxiter, so.de_popsize, so.mo_rho, so.mo_ref_offset,
                   so.mo_gp_restarts)


# ---- 격자·스칼라화 -------------------------------------------------------------------------------


def lattice(m: int, h: int) -> list[tuple[float, ...]]:
    """Das–Dennis 단체 격자(합 1, 간격 1/h), 사전순. m=2·h=10 → 11점, m=3·h=6 → 28점."""
    out: list[tuple[int, ...]] = []

    def rec(prefix: tuple[int, ...], left: int, k: int) -> None:
        if k == 1:
            out.append((*prefix, left))
            return
        for a in range(left + 1):
            rec((*prefix, a), left - a, k - 1)

    rec((), h, m)
    return [tuple(a / h for a in t) for t in sorted(out)]


def chebyshev(F: np.ndarray, w: Sequence[float], rho: float) -> np.ndarray:
    """증강 Chebyshev s_w = max_i w_i·f_i + ρ·Σ_i w_i·f_i (F: n×m, 정규화 값)."""
    wf = np.atleast_2d(F) * np.asarray(w, dtype=float)[None, :]
    return wf.max(axis=1) + rho * wf.sum(axis=1)


def work_frame(F: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """작업 정규화(§22.5.1): (ideal, Δ) — 유효 설계 부호 통일 값의 최소·범위(평평하면 pareto.frame_delta 규칙)."""
    ideal = F.min(axis=0)
    nadir = F.max(axis=0)
    return ideal, np.asarray(pareto.frame_delta(ideal.tolist(), nadir.tolist()))


def signed(designs: Sequence[Design], signs: Sequence[float]) -> np.ndarray:
    return np.array([[s * v for s, v in zip(signs, d.objectives)] for d in designs], dtype=float)


# ---- 적합(SO_FIT) --------------------------------------------------------------------------------


def _one(kind: str, X: np.ndarray, y: np.ndarray, *, restarts: int, seed: int, label: str, warnings: list[dict[str, str]],
         progress: Callable[[int, int], None] | None, checkpoint: Callable[[], None] | None) -> Scaled:
    ys, mean, std = _standardize(y)
    if kind == "gp" and float(np.ptp(y)) <= 1e-12 * max(1.0, float(np.max(np.abs(y)))):
        warnings.append({"code": "OBJECTIVE_CONSTANT", "message": f"{label} 값이 모든 run에서 같습니다 — 지표·탐색 범위를 확인하세요(RBF로 계속)"})
        kind = "rbf"
    if kind == "gp":
        try:
            return Scaled(fit_gp(X, ys, restarts=restarts, seed=seed, progress=progress, checkpoint=checkpoint), mean, std)
        except GPFitError as exc:
            warnings.append({"code": "GP_FALLBACK_RBF", "message": f"{label} GP 적합에 실패해 RBF로 바꿨습니다({exc})"})
    try:
        return Scaled(fit_rbf(X, ys), mean, std)
    except RBFFitError as exc:
        raise SurrogateError("SURROGATE_FIT_FAILED", f"{label}: {exc}") from None


def fit_mo(designs: Sequence[Design], problem: Problem, *, kind: str, restarts: int, seed: int,
           progress: Callable[[str], None] | None = None, checkpoint: Callable[[], None] | None = None) -> FitResult:
    """목적별·제약별 모델. 목적 i 시드 = seed + 17·i, 제약 c 시드 = seed + 31·(c+1)(§22.5.7)."""
    free = free_variables(problem, designs)
    if not free:
        raise SurrogateError("NO_FREE_VARIABLE", "자료에서 바뀌는 자유 변수가 없습니다")
    fill = {n: (problem.bounds[n][0] if problem.bounds[n][0] == problem.bounds[n][1] else designs[0].values[n])
            for n in problem.names if n not in free}
    lo = np.array([problem.bounds[n][0] for n in free])
    hi = np.array([problem.bounds[n][1] for n in free])
    X = (np.array([[d.values[n] for n in free] for d in designs]) - lo) / (hi - lo)
    signs = problem.signs()
    m = problem.m
    warnings: list[dict[str, str]] = []

    def prog(label: str) -> Callable[[int, int], None]:
        def f(i: int, total: int) -> None:
            if progress is not None:
                progress(f"대리모델 학습({kind.upper()}) · {label} · 재시작 {i}/{total}")
        return f

    F = signed(designs, signs)
    objs = []
    for i, o in enumerate(problem.objectives):
        name = f"목적 {i + 1}({o.metric})"
        objs.append(_one(kind, X, F[:, i], restarts=restarts, seed=seed + 17 * i, label=name, warnings=warnings,
                         progress=prog(f"목적 {i + 1}/{m}"), checkpoint=checkpoint))
    cons = []
    nc = len(problem.constraints)
    for j, c in enumerate(problem.constraints):
        y = np.array([d.constraints[j] for d in designs], dtype=float)
        cons.append(_one("gp" if kind == "gp" else "rbf", X, y, restarts=restarts, seed=seed + 31 * (j + 1),
                         label=f"제약 {j + 1}({c.metric})", warnings=warnings,
                         progress=prog(f"제약 {j + 1}/{nc}"), checkpoint=checkpoint))
    fit = FitResult(kind, free, lo, hi, fill, signs[0], objs[0], cons, warnings, seed=seed, objectives=objs, signs=signs)
    per = []
    loo_rows: list[list[Any]] = []
    for i, (o, s) in enumerate(zip(problem.objectives, objs)):
        q = quality(s)
        per.append({"metric": o.metric, "kind": s.model.kind, "n_train": len(designs), "loo_rmse": q["loo_rmse"],
                    "loo_nrmse": q["loo_nrmse"], "q2": q["q2"], "pred_vs_verified_mae": None})
        mean, var = s.model.loo()
        for r, (yv, mv, vv) in enumerate(zip(s.model.y, mean, var)):
            loo_rows.append([f"objective_{i + 1}", r, signs[i] * float(yv * s.std + s.mean), signs[i] * float(mv * s.std + s.mean),
                             float(math.sqrt(max(float(vv), 0.0)) * s.std)])
    for j, s in enumerate(cons):
        mean, var = s.model.loo()
        for r, (yv, mv, vv) in enumerate(zip(s.model.y, mean, var)):
            loo_rows.append([f"constraint_{j + 1}", r, float(yv * s.std + s.mean), float(mv * s.std + s.mean),
                             float(math.sqrt(max(float(vv), 0.0)) * s.std)])
    first = per[0]
    fit.quality = {"kind": kind if all(s.model.kind == kind for s in objs) else "mixed", "n_train": len(designs),
                   "d_free": len(free), "loo_rmse": first["loo_rmse"], "loo_nrmse": first["loo_nrmse"], "q2": first["q2"],
                   "per_objective": per, "loo_rows": loo_rows}
    return fit


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
        return vals

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


def propose_mo(fit: FitResult, problem: Problem, designs: Sequence[Design], failed: Sequence[dict[str, float]], *, k: int,
               seed: int, round_no: int, cfg: MoCfg, hv_frame: dict[str, Any], used_weights: Sequence[int] = (),
               progress: Callable[[int, int, str], None] | None = None,
               checkpoint: Callable[[], None] | None = None) -> MoProposal:
    """예측 전선 + 후보 최대 k개(§22.5.3·§22.5.4)."""
    st = _Ctx(fit, problem, designs, failed)
    m = problem.m
    W = lattice(m, cfg.h2 if m == 2 else cfg.h3)
    F = signed(designs, st.signs.tolist())
    ideal, delta = work_frame(F)
    frame_ideal, frame_nadir = hv_frame["ideal"], hv_frame["nadir"]
    R = [1.0 + float(hv_frame.get("ref_offset", cfg.ref_offset))] * m
    base = seed * 100000 + round_no * 1000
    warnings: list[dict[str, str]] = []

    def mu_tilde(Xn: np.ndarray) -> np.ndarray:
        return (st.mu(Xn)[0] - ideal) / delta

    # ① 예측 전선
    pool: list[np.ndarray] = []
    for j, w in enumerate(W):
        if progress is not None:
            progress(j + 1, len(W), f"예측 전선 {j + 1}/{len(W)}")

        def f_w(xT: np.ndarray, w: tuple[float, ...] = w) -> np.ndarray:
            Xn = fit.normalize(np.atleast_2d(xT.T))
            v = chebyshev(mu_tilde(Xn), w, cfg.rho)
            return v + PENALTY * st.penalty(Xn) if st.cons else v

        x = st.round_x(_de_full(f_w, st.bounds, st.ints, seed=base + j, maxiter=cfg.de_maxiter, popsize=cfg.de_popsize,
                                checkpoint=checkpoint)[0])
        if not any(same_design(st.values(x), st.values(q), problem) for q in pool):
            pool.append(x)
    Xp = fit.normalize(np.array(pool))
    mu_p, sd_p = st.mu(Xp)
    pof_each = st.pof(Xp, each=True)
    ok = [i for i in range(len(pool)) if np.all(pof_each[i] >= 0.5)]
    nd = [ok[i] for i in pareto.nondominated([mu_p[i].tolist() for i in ok])]
    front_rows = [{"values": st.values(pool[i]), "mean": [float(s * v) for s, v in zip(st.signs, mu_p[i])],
                   "std": [float(v) for v in sd_p[i]], "pof": float(np.prod(pof_each[i]))} for i in nd]

    # ② c₁ — 전선 확장 활용(HVI)
    feas = [d for d in designs if is_feasible(d.constraints, problem.constraints)]
    Fv = [pareto.normalize((st.signs * np.asarray(d.objectives)).tolist(), frame_ideal, frame_nadir) for d in feas]
    Fv = [Fv[i] for i in pareto.nondominated(Fv)]
    cand_idx = nd or list(range(len(pool)))
    order = c1_order([pareto.normalize(mu_p[i].tolist(), frame_ideal, frame_nadir) for i in cand_idx], Fv, R)
    if progress is not None:
        progress(1, k, f"후보 1/{k}")
    for pos, hvi in order:
        i = cand_idx[pos]
        c = st.make(pool[i], "hvi", None, float(hvi))
        if not st.is_dup(c.values):
            st.picked.append(c)
            break

    # ③ c₂… — ParEGO(GP) 또는 RBF 거리 규칙
    chosen, used = assign_weights(len(W), k - len(st.picked), seed=seed, round_no=round_no, used=used_weights)
    Ft = (F - ideal) / delta
    valid_feas = np.array([is_feasible(d.constraints, problem.constraints) for d in designs])
    Xd = fit.normalize(np.array([[d.values[n] for n in fit.free] for d in designs]))
    dmin = RBF_MIN_DIST
    for n_done, j in enumerate(chosen):
        if len(st.picked) >= k:
            break
        if progress is not None:
            progress(len(st.picked) + 1, k, f"후보 {len(st.picked) + 1}/{k}")
        w = W[j]
        if fit.kind == "gp":
            y = chebyshev(Ft, w, cfg.rho)
            ys, ym, ysd = _standardize(y)
            try:
                gpw = fit_gp(Xd, ys, restarts=cfg.gp_restarts, seed=base + 500 + j, checkpoint=checkpoint)
            except GPFitError as exc:
                warnings.append({"code": "GP_FALLBACK_RBF", "message": f"ParEGO 가중 {list(w)} GP 적합 실패 — 건너뜀({exc})"})
                continue
            ref_y = y[valid_feas] if np.any(valid_feas) else y
            fmin = float((np.min(ref_y) - ym) / ysd)

            def acq(xT: np.ndarray, gpw: Any = gpw, fmin: float = fmin) -> np.ndarray:
                Xn = fit.normalize(np.atleast_2d(xT.T))
                mm, ss = gpw.predict(Xn)
                return -(_ei(mm, ss, fmin) * st.pof(Xn))

            pop = _de_full(acq, st.bounds, st.ints, seed=base + 700 + j, maxiter=cfg.de_maxiter, popsize=cfg.de_popsize,
                           checkpoint=checkpoint)
            for x in pop:
                x = st.round_x(x)
                c = st.make(x, "parego", list(w), float(-acq(x.reshape(-1, 1))[0] * ysd))
                if not st.is_dup(c.values):
                    st.picked.append(c)
                    break
        else:
            while dmin >= RBF_MIN_DIST_FLOOR:
                ref = np.array([fit.normalize(np.array([e[n] for n in fit.free]))[0]
                                for e in st.existing + [c.values for c in st.picked]])
                dd = len(fit.free)

                def f_rbf(xT: np.ndarray, ref: np.ndarray = ref, dmin: float = dmin, w: tuple[float, ...] = w) -> np.ndarray:
                    Xn = fit.normalize(np.atleast_2d(xT.T))
                    v = chebyshev(mu_tilde(Xn), w, cfg.rho)
                    if st.cons:
                        v = v + PENALTY * st.penalty(Xn)
                    dist = np.sqrt(((Xn[:, None, :] - ref[None, :, :]) ** 2).sum(axis=2)).min(axis=1) / math.sqrt(dd)
                    return v + 1e6 * np.maximum(0.0, dmin - dist)

                x = st.round_x(_de_full(f_rbf, st.bounds, st.ints, seed=base + 700 + j, maxiter=cfg.de_maxiter,
                                        popsize=cfg.de_popsize, checkpoint=checkpoint)[0])
                xn = fit.normalize(x)[0]
                dist = float(np.sqrt(((ref - xn) ** 2).sum(axis=1)).min() / math.sqrt(dd)) if len(ref) else math.inf
                c = st.make(x, "rbf", list(w), None)
                if dist + 1e-12 >= dmin and not st.is_dup(c.values):
                    st.picked.append(c)
                    break
                dmin /= 2.0
    seeds = {"front_de": [base + j for j in range(len(W))], "perm": seed * 1000 + round_no,
             "parego_gp": [base + 500 + j for j in chosen], "parego_de": [base + 700 + j for j in chosen]}
    return MoProposal(st.picked[:k], front_rows, used, seeds, warnings)


# ---- 시험 전용 오프라인 루프(V3-S17-7) -------------------------------------------------------------


def run_offline(func: Callable[[np.ndarray], Sequence[float]], d: int, m: int, *, n0: int, iterations: int, k: int, seed: int,
                kind: str = "gp", cfg: MoCfg | None = None, restarts: int = 4, lhs_only: bool = False) -> dict[str, Any]:
    """[0,1]^d 위 해석 함수(최소화 m목적)를 평가기로 쓰는 루프: LHS n0 → (적합·후보 k)×iterations. lhs_only면 같은 예산의
    LHS만. 반환 {X, F(n×m), iter}. 실제 작업·DB 없음."""
    cfg = cfg or MoCfg()
    names = [f"x{i}" for i in range(d)]
    settings = {"names": names, "integer": [], "bounds": {n: [0.0, 1.0] for n in names},
                "objectives": [{"metric": f"f{i}", "series": None, "sense": "min"} for i in range(m)],
                "objective": {"metric": "f0", "series": None, "sense": "min"}, "constraints": []}
    problem = Problem.from_settings(settings)
    rng = np.random.default_rng(seed)
    X0 = lhs_unit(rng, n0 + iterations * k if lhs_only else n0, d)  # LHS만: 같은 예산 전부 LHS
    pts: list[Point] = []

    def add(x: np.ndarray, it: int, no: int) -> None:
        f = [float(v) for v in func(np.asarray(x, dtype=float))]
        pts.append(Point(it, "B", no, f"run_{no}", {n: float(v) for n, v in zip(names, x)}, f[0], [], "SUCCEEDED", objectives=f))

    for i, x in enumerate(X0, 1):
        add(x, 0, i)
    if lhs_only:
        return _offline_out(pts)
    designs, _ = merge(pts, problem)
    Fs = signed(designs, problem.signs())
    ideal, nadir = pareto.make_frame(Fs.tolist())
    frame = {"ideal": ideal, "nadir": nadir, "ref_offset": cfg.ref_offset, "signs": problem.signs()}
    used: list[int] = []
    no = len(pts)
    for r in range(1, iterations + 1):
        designs, failed = merge(pts, problem)
        fit = fit_mo(designs, problem, kind=kind, restarts=restarts, seed=seed * 1000 + r)
        prop = propose_mo(fit, problem, designs, failed, k=k, seed=seed, round_no=r, cfg=cfg, hv_frame=frame, used_weights=used)
        used = prop.used_weights
        if not prop.candidates:
            break
        for c in prop.candidates:
            no += 1
            add(np.array([c.values[n] for n in names]), r, no)
    return _offline_out(pts)


def _offline_out(pts: Sequence[Point]) -> dict[str, Any]:
    return {"X": np.array([[p.values[n] for n in sorted(p.values, key=lambda s: int(s[1:]))] for p in pts]),
            "F": np.array([list(p.objectives or []) for p in pts], dtype=float), "iter": [p.iter_no for p in pts]}
