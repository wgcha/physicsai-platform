"""다목적 격자 가중치(Das–Dennis)·증강 Chebyshev·작업 정규화 틀(§22.5) — mo_infill에서 재노출."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from . import pareto
from .dataset import Design

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
    hvi_share_m3: float = 0.5  # 3목적: HVI 활용 후보 = ⌈k·share⌉(0 = 계약 원안 1개), 고른 점을 전선에 더하며 서로 다른 점
    front_prox_m3: float = 6.0  # 3목적: ParEGO 획득값 × exp(−prox·(예측 전선 점까지 정규화 거리))(0 = 끔)

    @classmethod
    def from_settings(cls, so: Any) -> MoCfg:
        return cls(so.mo_lattice_h2, so.mo_lattice_h3, so.mo_de_maxiter, so.de_popsize, so.mo_rho, so.mo_ref_offset,
                   so.mo_gp_restarts, so.mo_hvi_share_m3, so.mo_front_prox_m3)


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
