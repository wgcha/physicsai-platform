"""대리모델 적합 묶음과 후보 탐색(phase3 §18.5).

- `fit_all`: 자유 변수 정규화([0,1] = 최적화 범위), 목적(sense=max는 부호 반전) 표준화, 목적 모델 1개 + 제약마다 같은 종류 1개.
  GP가 Cholesky로 실패하면 RBF로 바꾸고 경고 GP_FALLBACK_RBF. 품질 = LOO RMSE(목적 단위)·NRMSE·Q².
- `propose`: 후보 k개 — ① 활용(평균 최소 + 제약 예측 위반 벌점 1e3) ② GP: EI × PoF 최대(kriging believer),
  RBF: 평균 최소 + 기존·선택 점과 정규화 거리 ≥ 0.1(못 찾으면 반으로, 0.0125까지).
  탐색기 = scipy differential_evolution(seed = seed·1000 + r + 100·j, integrality, vectorized, updating="deferred",
  polish = 정수 변수 없을 때만). 고정·자료 상수 변수는 탐색 벡터에서 빼고 그 값으로 채운다. 같은 설계(기존 성공·실패·이미 고른
  후보)는 버리고 다음.
"""

from __future__ import annotations

import inspect
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy.optimize import differential_evolution
from scipy.stats import norm

from .dataset import Constraint, Design, Problem, free_variables, same_design
from .gp import GPFitError, GPModel, fit_gp
from .rbf import RBFFitError, RBFModel, fit_rbf

PENALTY = 1e3
RBF_MIN_DIST = 0.1
RBF_MIN_DIST_FLOOR = 0.0125
_DE_PARAMS = inspect.signature(differential_evolution).parameters


class SurrogateError(RuntimeError):
    """적합 불가(점 부족·연립방정식 실패). code는 사용자 문구용."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class Scaled:
    """표준화한 모델 1개(값 = model·std + mean, 목적은 그 뒤 sign 곱)."""

    model: Any
    mean: float
    std: float

    def raw(self, Xn: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        m, s = self.model.predict(Xn)
        return m * self.std + self.mean, s * self.std


@dataclass
class FitResult:
    kind: str
    free: list[str]
    lo: np.ndarray
    hi: np.ndarray
    fill: dict[str, float]
    sign: float
    objective: Scaled
    constraints: list[Scaled]
    warnings: list[dict[str, str]] = field(default_factory=list)
    quality: dict[str, Any] = field(default_factory=dict)
    seed: int = 1
    objectives: list[Scaled] = field(default_factory=list)  # S17 다목적: 목적별 모델(부호 통일 값), objective = [0]
    signs: list[float] = field(default_factory=list)

    def normalize(self, X: np.ndarray) -> np.ndarray:
        return (np.atleast_2d(X) - self.lo) / (self.hi - self.lo)

    def full_values(self, x: np.ndarray) -> dict[str, float]:
        out = dict(self.fill)
        for n, v in zip(self.free, x):
            out[n] = float(v)
        return out

    def to_json(self) -> dict[str, Any]:
        def one(s: Scaled) -> dict[str, Any]:
            m = s.model
            d: dict[str, Any] = {"mean": s.mean, "std": s.std, "X": m.X.tolist(), "y": m.y.tolist(), **m.to_json()}
            if isinstance(m, GPModel):
                d["log_ls"] = [float(v) for v in m.log_ls]
                d["log_nugget"] = float(m.log_nugget)
            return d

        d = {"kind": self.kind, "free": self.free, "lo": self.lo.tolist(), "hi": self.hi.tolist(), "fill": self.fill,
             "sign": self.sign, "seed": self.seed, "objective": one(self.objective),
             "constraints": [one(c) for c in self.constraints], "warnings": self.warnings, "quality": self.quality}
        if self.objectives:
            d["objectives"] = [one(o) for o in self.objectives]
            d["signs"] = list(self.signs)
        return d

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> FitResult:
        def one(x: dict[str, Any]) -> Scaled:
            X, y = np.asarray(x["X"], dtype=float), np.asarray(x["y"], dtype=float)
            m: Any = GPModel(X, y, np.asarray(x["log_ls"], dtype=float), float(x["log_nugget"])) if x["kind"] == "gp" \
                else RBFModel(X, y, float(x.get("smoothing", 1e-10)))
            return Scaled(m, float(x["mean"]), float(x["std"]))

        return cls(d["kind"], list(d["free"]), np.asarray(d["lo"], dtype=float), np.asarray(d["hi"], dtype=float),
                   {k: float(v) for k, v in d["fill"].items()}, float(d["sign"]), one(d["objective"]),
                   [one(c) for c in d["constraints"]], list(d.get("warnings") or []), dict(d.get("quality") or {}),
                   int(d.get("seed", 1)), [one(o) for o in d.get("objectives") or []],
                   [float(x) for x in d.get("signs") or []])


def _standardize(v: np.ndarray) -> tuple[np.ndarray, float, float]:
    mean = float(np.mean(v))
    std = float(np.std(v))
    if not math.isfinite(std) or std <= 1e-12 * max(1.0, abs(mean)):
        std = 1.0
    return (v - mean) / std, mean, std


def _fit_one(kind: str, X: np.ndarray, y: np.ndarray, *, restarts: int, seed: int,
             progress: Callable[[int, int], None] | None, checkpoint: Callable[[], None] | None) -> Any:
    if kind == "gp":
        return fit_gp(X, y, restarts=restarts, seed=seed, progress=progress, checkpoint=checkpoint)
    try:
        return fit_rbf(X, y)
    except RBFFitError as exc:
        raise SurrogateError("SURROGATE_FIT_FAILED", str(exc)) from None


def quality(s: Scaled) -> dict[str, Any]:
    """LOO RMSE(목적 단위 — 표준화 역변환), NRMSE(= RMSE / 표준편차), Q²(= 1 − PRESS/SS)."""
    y = s.model.y * s.std + s.mean
    pred, _ = s.model.loo()
    err = (s.model.y - pred) * s.std
    rmse = float(np.sqrt(np.mean(err * err)))
    ss = float(np.sum((y - np.mean(y)) ** 2))
    sd = float(np.std(y))
    return {"loo_rmse": rmse, "loo_nrmse": (rmse / sd) if sd > 0 else None,
            "q2": (1.0 - float(np.sum(err * err)) / ss) if ss > 0 else None, "loo_pred": (pred * s.std + s.mean).tolist()}


def fit_all(designs: Sequence[Design], problem: Problem, *, kind: str, restarts: int, seed: int,
            progress: Callable[[str], None] | None = None, checkpoint: Callable[[], None] | None = None) -> FitResult:
    free = free_variables(problem, designs)
    if not free:
        raise SurrogateError("NO_FREE_VARIABLE", "자료에서 바뀌는 자유 변수가 없습니다")
    fill = {n: (problem.bounds[n][0] if problem.bounds[n][0] == problem.bounds[n][1] else designs[0].values[n])
            for n in problem.names if n not in free}
    lo = np.array([problem.bounds[n][0] for n in free])
    hi = np.array([problem.bounds[n][1] for n in free])
    X = (np.array([[d.values[n] for n in free] for d in designs]) - lo) / (hi - lo)
    sign = problem.sign()
    warnings: list[dict[str, str]] = []
    n_models = 1 + len(problem.constraints)

    def prog(label: str) -> Callable[[int, int], None]:
        def f(i: int, total: int) -> None:
            if progress is not None:
                progress(f"대리모델 학습({kind.upper()}) · {label}재시작 {i}/{total}")
        return f

    def build(k: str) -> tuple[Scaled, list[Scaled]]:
        yo, mo, so = _standardize(np.array([sign * d.objective for d in designs]))
        obj = Scaled(_fit_one(k, X, yo, restarts=restarts, seed=seed, progress=prog("목적 " if n_models > 1 else ""),
                              checkpoint=checkpoint), mo, so)
        cons = []
        for j in range(len(problem.constraints)):
            yc, mc, sc = _standardize(np.array([d.constraints[j] for d in designs]))
            cons.append(Scaled(_fit_one(k, X, yc, restarts=restarts, seed=seed + j + 1, progress=prog(f"제약 {j + 1} "),
                                        checkpoint=checkpoint), mc, sc))
        return obj, cons

    used = kind
    objs = np.array([d.objective for d in designs])
    if kind == "gp" and float(np.ptp(objs)) <= 1e-12 * max(1.0, float(np.max(np.abs(objs)))):
        # 목적 값이 모두 같으면 GP 우도가 정의되지 않는다 — "GP 실패"가 아니라 자료 문제로 알리고 RBF(평평한 면)로 계속
        warnings.append({"code": "OBJECTIVE_CONSTANT",
                         "message": "목적 값이 모든 run에서 같습니다 — 지표·탐색 범위를 확인하세요(RBF로 계속)"})
        kind = used = "rbf"
    try:
        obj, cons = build(kind)
    except GPFitError as exc:
        warnings.append({"code": "GP_FALLBACK_RBF", "message": f"GP 적합에 실패해 RBF로 바꿨습니다({exc})"})
        used = "rbf"
        obj, cons = build("rbf")
    fit = FitResult(used, free, lo, hi, fill, sign, obj, cons, warnings, seed=seed)
    q = quality(obj)
    # 목적 단위 보고: sign이 -1이면 LOO 예측 부호도 되돌린다
    q["loo_pred"] = [sign * v for v in q["loo_pred"]]
    fit.quality = {"kind": used, "n_train": len(designs), "d_free": len(free), **q}
    return fit


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

    x_opt = round_x(_de(f_exploit, bounds, ints, seed=base_seed, maxiter=de_maxiter, popsize=de_popsize,
                        checkpoint=checkpoint))
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

            x = round_x(_de(acq, bounds, ints, seed=base_seed + 100 * j, maxiter=de_maxiter, popsize=de_popsize,
                            checkpoint=checkpoint))
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
            ref = np.array([fit.normalize(np.array([e[n] for n in free]))[0] for e in existing + [c.values for c in picked]])

            def f_rbf(xT: np.ndarray, ref: np.ndarray = ref, dmin: float = dmin) -> np.ndarray:
                Xn = fit.normalize(np.atleast_2d(xT.T))
                m, _ = obj.model.predict(Xn)
                if cons:
                    m = m + PENALTY * penalty(cons_raw(cmods, Xn), cmods)
                dist = np.sqrt(((Xn[:, None, :] - ref[None, :, :]) ** 2).sum(axis=2)).min(axis=1) / math.sqrt(d)
                return m + 1e6 * np.maximum(0.0, dmin - dist)

            x = round_x(_de(f_rbf, bounds, ints, seed=base_seed + 100 * j, maxiter=de_maxiter, popsize=de_popsize,
                            checkpoint=checkpoint))
            j += 1
            xn = fit.normalize(x)[0]
            dist = float(np.sqrt(((ref - xn) ** 2).sum(axis=1)).min() / math.sqrt(d)) if len(ref) else math.inf
            cand = make(x, obj, cmods, None)
            if dist + 1e-12 >= dmin and not is_dup(cand.values):
                picked.append(cand)
            else:
                dmin /= 2.0
    return picked[:k], optimum
