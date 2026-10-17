"""GP(ordinary Kriging) 대리모델(phase3 §18.5): 상수 평균 + Matérn 5/2 ARD + nugget.

입력 X는 [0,1]로 정규화한 자유 변수(n×d), y는 표준화 값(n). 하이퍼파라미터(log 길이척도 d개 ∈ [log 0.01, log 10],
log nugget ∈ [log 1e-8, log 1e-1])는 집중 로그우도(평균·분산을 닫힌 식으로 뺀 것)를 L-BFGS-B(해석 기울기)로,
시작점 `restarts`개(시드 LHS). Cholesky 실패는 jitter(0 → 1e-8 → 1e-7 → 1e-6, 10배씩 3회) 후 `GPFitError`.
LOO는 증강 행렬 A = [[R, 1], [1ᵀ, 0]]의 역으로 닫힌 식(eᵢ = cᵢ/[A⁻¹]ᵢᵢ — 평균을 다시 추정하는 하나 빼기 적합과 정확히 같다).
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy.linalg import LinAlgError, cho_factor, cho_solve
from scipy.optimize import minimize

SQRT5 = math.sqrt(5.0)
LOG_LS_BOUNDS = (math.log(0.01), math.log(10.0))
LOG_NUG_BOUNDS = (math.log(1e-8), math.log(1e-1))
JITTERS = (0.0, 1e-8, 1e-7, 1e-6)
BAD_NLL = 1e10


class GPFitError(RuntimeError):
    """모든 jitter에서 Cholesky 실패 — 호출부가 RBF로 바꾼다(GP_FALLBACK_RBF)."""


def _sqdiff(X1: np.ndarray, X2: np.ndarray, ls: np.ndarray) -> np.ndarray:
    """(d, n1, n2) 축별 ((x1−x2)/ℓ)²."""
    D = (X1.T[:, :, None] - X2.T[:, None, :]) / ls[:, None, None]
    return D * D


def matern52(X1: np.ndarray, X2: np.ndarray, ls: np.ndarray) -> np.ndarray:
    r = np.sqrt(np.maximum(_sqdiff(X1, X2, ls).sum(axis=0), 0.0))
    return (1.0 + SQRT5 * r + (5.0 / 3.0) * r * r) * np.exp(-SQRT5 * r)


def _chol(R: np.ndarray) -> tuple[Any, float]:
    n = R.shape[0]
    last: Exception | None = None
    for j in JITTERS:
        try:
            c = cho_factor(R + j * np.eye(n), lower=True, check_finite=True)
            if np.all(np.diag(c[0]) > 0):
                return c, j
        except (LinAlgError, ValueError) as exc:
            last = exc
    raise GPFitError(f"Cholesky 실패: {last}")


def nll_and_grad(theta: np.ndarray, X: np.ndarray, y: np.ndarray) -> tuple[float, np.ndarray]:
    """집중 음의 로그우도와 기울기. theta = [log ℓ_1..d, log nugget]."""
    n, d = X.shape
    ls = np.exp(theta[:d])
    nug = math.exp(theta[d])
    S = _sqdiff(X, X, ls)
    r = np.sqrt(np.maximum(S.sum(axis=0), 0.0))
    e = np.exp(-SQRT5 * r)
    K = (1.0 + SQRT5 * r + (5.0 / 3.0) * r * r) * e
    R = K + nug * np.eye(n)
    try:
        c = cho_factor(R, lower=True, check_finite=True)
    except (LinAlgError, ValueError):
        return BAD_NLL, np.zeros(d + 1)
    diag = np.diag(c[0])
    if not np.all(diag > 0):
        return BAD_NLL, np.zeros(d + 1)
    one = np.ones(n)
    Ri1 = cho_solve(c, one)
    Riy = cho_solve(c, y)
    mu = float(one @ Riy) / float(one @ Ri1)
    alpha = Riy - mu * Ri1
    res = y - mu
    s2 = float(res @ alpha) / n
    if not math.isfinite(s2) or s2 <= 1e-300:
        return BAD_NLL, np.zeros(d + 1)
    nll = 0.5 * n * math.log(s2) + float(np.sum(np.log(diag)))
    Rinv = cho_solve(c, np.eye(n))
    W = (Rinv - np.outer(alpha, alpha) / s2) * ((5.0 / 3.0) * (1.0 + SQRT5 * r) * e)
    g = np.empty(d + 1)
    g[:d] = 0.5 * np.einsum("ij,kij->k", W, S)
    g[d] = 0.5 * nug * (float(np.trace(Rinv)) - float(alpha @ alpha) / s2)
    if not math.isfinite(nll) or not np.all(np.isfinite(g)):
        return BAD_NLL, np.zeros(d + 1)
    return nll, g


def lhs_unit(rng: np.random.Generator, n: int, d: int) -> np.ndarray:
    """[0,1]^d 층화 LHS n점."""
    out = np.empty((n, d))
    for j in range(d):
        out[:, j] = (rng.permutation(n) + rng.random(n)) / n
    return out


@dataclass
class GPModel:
    X: np.ndarray
    y: np.ndarray
    log_ls: np.ndarray
    log_nugget: float
    jitter: float = 0.0
    nll: float = float("nan")
    _c: Any = field(default=None, repr=False)

    def __post_init__(self) -> None:
        n = self.X.shape[0]
        self.ls = np.exp(self.log_ls)
        self.nugget = math.exp(self.log_nugget)
        R = matern52(self.X, self.X, self.ls) + self.nugget * np.eye(n)
        self._c, self.jitter = _chol(R)
        self.R = R + self.jitter * np.eye(n)
        one = np.ones(n)
        self.Ri1 = cho_solve(self._c, one)
        Riy = cho_solve(self._c, self.y)
        self.s1 = float(one @ self.Ri1)
        self.mu = float(one @ Riy) / self.s1
        self.alpha = Riy - self.mu * self.Ri1
        self.sigma2 = max(float((self.y - self.mu) @ self.alpha) / n, 1e-12)

    kind = "gp"

    def predict(self, Xs: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """(평균, 표준편차) — 표준화 단위, 잠재 함수(nugget 제외)."""
        Xs = np.atleast_2d(Xs)
        k = matern52(Xs, self.X, self.ls)
        mean = self.mu + k @ self.alpha
        v = cho_solve(self._c, k.T)
        u = 1.0 - k @ self.Ri1
        var = self.sigma2 * (1.0 - np.sum(k * v.T, axis=1) + u * u / self.s1)
        return mean, np.sqrt(np.maximum(var, 1e-12 * self.sigma2))

    def loo(self) -> tuple[np.ndarray, np.ndarray]:
        """하나 빼기 예측 (평균, 분산) — 같은 하이퍼파라미터, 평균 재추정. 표준화 단위."""
        n = self.X.shape[0]
        A = np.zeros((n + 1, n + 1))
        A[:n, :n] = self.R
        A[:n, n] = 1.0
        A[n, :n] = 1.0
        Ainv = np.linalg.inv(A)
        c = Ainv @ np.concatenate([self.y, [0.0]])
        dii = np.diag(Ainv)[:n]
        return self.y - c[:n] / dii, self.sigma2 / dii

    def with_points(self, Xn: np.ndarray, yn: np.ndarray) -> GPModel:
        """kriging believer: 같은 하이퍼파라미터로 점을 더한 모델."""
        return GPModel(np.vstack([self.X, np.atleast_2d(Xn)]), np.concatenate([self.y, np.atleast_1d(yn)]),
                       self.log_ls.copy(), self.log_nugget)

    def to_json(self) -> dict[str, Any]:
        return {"kind": "gp", "length_scales": [float(v) for v in self.ls], "nugget": self.nugget, "jitter": self.jitter,
                "mu": self.mu, "sigma2": self.sigma2, "nll": None if not math.isfinite(self.nll) else self.nll}


def fit_gp(X: np.ndarray, y: np.ndarray, *, restarts: int, seed: int,
           progress: Callable[[int, int], None] | None = None,
           checkpoint: Callable[[], None] | None = None, maxiter: int = 200) -> GPModel:
    """다중 시작 L-BFGS-B. 모든 시작점이 실패하거나 최종 Cholesky가 실패하면 GPFitError."""
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=float)
    n, d = X.shape
    rng = np.random.default_rng(seed)
    lo = np.array([LOG_LS_BOUNDS[0]] * d + [LOG_NUG_BOUNDS[0]])
    hi = np.array([LOG_LS_BOUNDS[1]] * d + [LOG_NUG_BOUNDS[1]])
    starts = lo + lhs_unit(rng, max(1, restarts), d + 1) * (hi - lo)
    bounds = list(zip(lo, hi))
    best: tuple[float, np.ndarray] | None = None
    for i, x0 in enumerate(starts, 1):
        if checkpoint is not None:
            checkpoint()
        if progress is not None:
            progress(i, len(starts))
        try:
            r = minimize(nll_and_grad, x0, args=(X, y), jac=True, method="L-BFGS-B", bounds=bounds,
                         options={"maxiter": maxiter})
        except (LinAlgError, ValueError, FloatingPointError):
            continue
        f = float(r.fun)
        if math.isfinite(f) and f < BAD_NLL and (best is None or f < best[0]):
            best = (f, np.asarray(r.x, dtype=float))
    if best is None:
        raise GPFitError("우도 최적화가 모든 시작점에서 실패했습니다")
    m = GPModel(X, y, best[1][:d], float(best[1][d]))
    m.nll = best[0]
    return m
