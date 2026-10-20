"""⑤ 대리모델 적합 결과 모양(Scaled·FitResult)·표준화·품질(LOO)과 상수 — infill에서 재노출."""

from __future__ import annotations

import inspect
import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy.optimize import differential_evolution

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
