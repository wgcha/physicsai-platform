"""RBF 대리모델(phase3 §18.5): cubic φ(r) = r³ + 1차 다항 꼬리, 평활 1e-10. LOO = Rippa 식(증강 행렬 역의 대각).

입력 X는 [0,1] 정규화(n×d), y는 표준화 값. 불확실성이 없으므로 후보는 평균 최소 + 거리 규칙(infill).
"""

from __future__ import annotations

from typing import Any

import numpy as np

SMOOTHING = 1e-10


class RBFFitError(RuntimeError):
    pass


def _dist(X1: np.ndarray, X2: np.ndarray) -> np.ndarray:
    diff = X1[:, None, :] - X2[None, :, :]
    return np.sqrt(np.maximum((diff * diff).sum(axis=2), 0.0))


def _poly(X: np.ndarray) -> np.ndarray:
    return np.hstack([np.ones((X.shape[0], 1)), X])


class RBFModel:
    kind = "rbf"

    def __init__(self, X: np.ndarray, y: np.ndarray, smoothing: float = SMOOTHING) -> None:
        self.X = np.asarray(X, dtype=float)
        self.y = np.asarray(y, dtype=float)
        self.smoothing = smoothing
        n, d = self.X.shape
        P = _poly(self.X)
        A = np.zeros((n + d + 1, n + d + 1))
        A[:n, :n] = _dist(self.X, self.X) ** 3 + smoothing * np.eye(n)
        A[:n, n:] = P
        A[n:, :n] = P.T
        self.A = A
        try:
            sol = np.linalg.solve(A, np.concatenate([self.y, np.zeros(d + 1)]))
        except np.linalg.LinAlgError as exc:
            raise RBFFitError(f"RBF 연립방정식을 풀 수 없습니다(점이 너무 적거나 겹침): {exc}") from None
        if not np.all(np.isfinite(sol)):
            raise RBFFitError("RBF 계수가 유한하지 않습니다")
        self.w, self.c = sol[:n], sol[n:]

    def predict(self, Xs: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """(평균, 0) — 표준화 단위."""
        Xs = np.atleast_2d(Xs)
        mean = (_dist(Xs, self.X) ** 3) @ self.w + _poly(Xs) @ self.c
        return mean, np.zeros(Xs.shape[0])

    def loo(self) -> tuple[np.ndarray, np.ndarray]:
        n = self.X.shape[0]
        Ainv = np.linalg.inv(self.A)
        coef = Ainv @ np.concatenate([self.y, np.zeros(self.A.shape[0] - n)])
        e = coef[:n] / np.diag(Ainv)[:n]
        return self.y - e, np.zeros(n)

    def with_points(self, Xn: np.ndarray, yn: np.ndarray) -> RBFModel:
        return RBFModel(np.vstack([self.X, np.atleast_2d(Xn)]), np.concatenate([self.y, np.atleast_1d(yn)]), self.smoothing)

    def to_json(self) -> dict[str, Any]:
        return {"kind": "rbf", "kernel": "cubic", "tail": "linear", "smoothing": self.smoothing}


def fit_rbf(X: np.ndarray, y: np.ndarray) -> RBFModel:
    return RBFModel(X, y)
