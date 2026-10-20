"""탐색 공간 `Space`(유전자 ↔ 설계 값·대리모델 입력, opt-native §6.2·§7) — `evo_infill`에서 재노출(R-B 300줄 분할, 동작 불변)."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np

from . import evo
from .dataset import Problem, canonical_values, covered, same_design
from .infill import FitResult, SurrogateError


@dataclass
class Space:
    """탐색 공간: 유전자(자유 변수 순서) ↔ 설계 값·대리모델 입력. 범주(baseline)는 B3 확장이 채운다."""

    fit: FitResult
    problem: Problem
    genes: list[evo.Gene]
    names: list[str]  # 유전자 이름(= fit.free, 범주가 있으면 + "baseline")
    to_model: Callable[[np.ndarray], np.ndarray] | None = None  # 원 단위 X → 대리모델 입력(None = fit.normalize)
    to_values: Callable[[np.ndarray], dict[str, Any]] | None = None  # 원 단위 행 → 설계 값(None = 기본)
    from_values: Callable[[dict[str, Any]], np.ndarray | None] | None = None  # 설계 값 → 원 단위 행
    effective: Callable[[np.ndarray], np.ndarray] | None = None  # N/A 마스크(중복·거리)
    extra_cv: Callable[[np.ndarray], np.ndarray] | None = None  # 범위 분할 NO_COVER 벌점
    same: Callable[[dict[str, Any], dict[str, Any]], bool] | None = None  # 같은 설계 판정

    @classmethod
    def basic(cls, fit: FitResult, problem: Problem) -> Space:
        genes = []
        spec = problem.cat_spec
        for n, lo, hi in zip(fit.free, fit.lo, fit.hi):
            if spec is not None and n == spec["cat"]:  # opt-native §7 범주: 수준 인덱스 유전자
                genes.append(evo.Gene(n, "cat", 0.0, float(len(spec["levels"]) - 1), len(spec["levels"])))
                continue
            kind = "int" if n in problem.integer else "real"
            if kind == "int" and math.ceil(lo - 1e-9) > math.floor(hi + 1e-9):
                raise SurrogateError("BOUNDS_INVALID", f"'{n}' 정수 범위가 비어 있습니다")
            genes.append(evo.Gene(n, kind, float(lo), float(hi)))
        if not genes:
            raise SurrogateError("NO_FREE_VARIABLE", "탐색할 변수가 없습니다")
        sp = cls(fit, problem, genes, list(fit.free))
        if spec is not None:
            from . import encoding

            fixed = int(round(fit.fill.get(spec["cat"], 0.0)))
            free = list(fit.free)
            sp.effective = lambda X: encoding.effective(X, free, spec, fixed)
        cov = problem.cover_spec
        if cov is not None:  # 범위 분할: 덮는 baseline이 없는 점은 CV += 1(§6.2)
            def extra(X: np.ndarray, sp: Space = sp, cov: dict[str, Any] = cov) -> np.ndarray:
                return np.array([0.0 if covered(sp.values(x), cov) else 1.0 for x in np.atleast_2d(X)])

            sp.extra_cv = extra
        return sp

    def model_input(self, X: np.ndarray) -> np.ndarray:
        return self.to_model(X) if self.to_model is not None else self.fit.normalize(X)

    def values(self, x: np.ndarray) -> dict[str, Any]:
        if self.to_values is not None:
            return self.to_values(x)
        vals: dict[str, Any] = self.fit.full_values(x)
        for n in self.problem.integer:
            if n in vals:
                vals[n] = float(round(vals[n]))
        return canonical_values(vals, self.problem.cat_spec)

    def row_of(self, vals: dict[str, Any]) -> np.ndarray | None:
        if self.from_values is not None:
            return self.from_values(vals)
        try:
            return np.array([float(vals[n]) for n in self.names])
        except (KeyError, TypeError, ValueError):
            return None

    def is_same(self, a: dict[str, Any], b: dict[str, Any]) -> bool:
        return self.same(a, b) if self.same is not None else same_design(a, b, self.problem)

    def unit(self, X: np.ndarray) -> np.ndarray:
        """거리용: 연속·정수 = 범위 정규화, 범주 = 수준 인덱스(불일치 1은 dist가 처리). N/A는 nan."""
        X = np.atleast_2d(np.asarray(X, dtype=float))
        E = self.effective(X) if self.effective is not None else X
        U = np.array(E, dtype=float, copy=True)
        for j, g in enumerate(self.genes):
            if g.kind != "cat":
                U[:, j] = (E[:, j] - g.lo) / g.span if g.span > 0 else 0.0
        return U

    def dist(self, X: np.ndarray, R: np.ndarray) -> np.ndarray:
        """정규화 거리(§6.5): 연속·정수 차 + 범주 불일치 1, √n_g로 나눔 — X 각 행에서 R 행들까지의 최소."""
        if len(R) == 0:
            return np.full(len(np.atleast_2d(X)), np.inf)
        U, V = self.unit(X), self.unit(R)
        cat = np.array([g.kind == "cat" for g in self.genes])
        D = U[:, None, :] - V[None, :, :]
        both_na = np.isnan(U)[:, None, :] & np.isnan(V)[None, :, :]
        D = np.where(both_na, 0.0, np.where(np.isnan(D), 1.0, D))  # 한쪽만 N/A = 차 1
        D = np.where(cat[None, None, :], (np.abs(D) > 0.5).astype(float), D)
        return np.sqrt((D * D).sum(axis=2)).min(axis=1) / math.sqrt(len(self.genes))
