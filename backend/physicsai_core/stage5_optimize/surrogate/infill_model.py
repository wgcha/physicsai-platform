"""⑤ 대리모델 적합 결과 모양(Scaled·FitResult)·표준화·품질(LOO)과 상수 — infill에서 재노출."""

from __future__ import annotations

import inspect
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy.optimize import differential_evolution

from .dataset_model import Design, Problem
from .gp import GPModel
from .rbf import RBFModel

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
    encoding: dict[str, Any] | None = None  # opt-native §7: 범주 baseline 인코딩 spec(학습 입력 규칙과 같은 열)

    def normalize(self, X: np.ndarray) -> np.ndarray:
        if self.encoding is not None:
            from .encoding import transform

            return transform(X, self.free, self.lo, self.hi, self.encoding, int(round(self.fill.get(self.encoding["cat"], 0.0))))
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
        if self.encoding is not None:
            d["encoding"] = self.encoding
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
                   [float(x) for x in d.get("signs") or []], d.get("encoding"))


def design_matrix(designs: Sequence[Design], free: list[str], lo: np.ndarray, hi: np.ndarray, fill: dict[str, float],
                  problem: Problem) -> np.ndarray:
    """학습 입력 행렬: 자유 변수 [0,1] 정규화(기존), 범주 baseline 세트면 학습 입력 규칙 인코딩(opt-native §7)."""
    raw = np.array([[d.values[n] for n in free] for d in designs])
    if problem.cat_spec is None:
        return (raw - lo) / (hi - lo)
    from .encoding import transform

    return transform(raw, free, lo, hi, problem.cat_spec, int(round(fill.get(problem.cat_spec["cat"], 0.0))))


def cat_index(fit: FitResult) -> tuple[int | None, int]:
    """(자유 변수 중 범주 baseline 위치 | None, 수준 수)."""
    enc = fit.encoding
    if enc is None or enc["cat"] not in fit.free:
        return None, 0
    return fit.free.index(enc["cat"]), len(enc["levels"])


def de_levels(de: Callable[..., Any], func: Callable[[np.ndarray], np.ndarray], bounds: list[tuple[float, float]],
              integrality: np.ndarray, cat_j: int, n_levels: int, seeds: Sequence[int], pick: str = "best", **kw: Any) -> Any:
    """opt-native §7 `ego` + 범주: 수준마다 범주를 고정하고 나머지 변수로 DE를 따로 돌려 합친다. pick="best" → 함수 값 최소
    해(동률 = 앞 수준), "all" → 수준별 해 목록(다목적 예측 전선용). de = `_de`(해 1개) — 결과는 원래 차원으로 되돌린다."""
    red_b = [b for j, b in enumerate(bounds) if j != cat_j]
    red_i = np.array([v for j, v in enumerate(integrality) if j != cat_j], dtype=bool)
    outs: list[np.ndarray] = []
    for lv in range(n_levels):
        def f_red(xT: np.ndarray, lv: int = lv) -> np.ndarray:
            xT = np.atleast_2d(xT)
            full = np.insert(xT, cat_j, float(lv), axis=0)
            return func(full)

        if red_b:
            xr = de(f_red, red_b, red_i, seed=seeds[lv], **kw)
            x = np.insert(np.asarray(xr, dtype=float), cat_j, float(lv))
        else:
            x = np.array([float(lv)])
        outs.append(x)
    if pick == "all":
        return outs
    vals = [float(func(x.reshape(-1, 1))[0]) for x in outs]
    return outs[int(np.argmin(vals))]


def level_seeds(seed: int, round_no: int, j: int, n_levels: int) -> list[int]:
    """수준별 DE 시드(§6.2): seed·100000 + r·1000 + 800 + level(+ 10·j — 같은 반복 안 j번째 탐색)."""
    return [seed * 100000 + round_no * 1000 + 800 + lv + 10 * j for lv in range(n_levels)]


def _standardize(v: np.ndarray) -> tuple[np.ndarray, float, float]:
    mean = float(np.mean(v))
    std = float(np.std(v))
    if not math.isfinite(std) or std <= 1e-12 * max(1.0, abs(mean)):
        std = 1.0
    return (v - mean) / std, mean, std


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
