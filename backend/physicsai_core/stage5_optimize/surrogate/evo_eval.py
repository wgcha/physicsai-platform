"""GA·NSGA-II 후보 선택 보조(평가기 `_Eval`·시드 주입·옵션 변환·집단 표·거리 규칙 선택) — `evo_infill`에서 사용(R-B 300줄 분할,
동작 불변). `evo_infill`을 import하지 않는다."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from typing import Any

import numpy as np

from . import evo
from .dataset import Design, Problem
from .evo_space import Space
from .infill import RBF_MIN_DIST, RBF_MIN_DIST_FLOOR, cons_pof, cons_violation
from .mo_frame import signed


class _Eval:
    """대리모델 평가기(원 단위 X → F, CV)."""

    def __init__(self, space: Space) -> None:
        self.space = space
        self.fit = space.fit
        self.problem = space.problem
        self.cons = space.problem.constraints
        self.s = [max(cm.std, 1e-12 * max([1.0, *[abs(b) for b in c.bounds()]])) for c, cm in zip(self.cons, self.fit.constraints)]
        self.objs = self.fit.objectives or [self.fit.objective]
        self.signs = np.asarray(self.fit.signs or [self.fit.sign])

    def cv_raw(self, Xn: np.ndarray, X: np.ndarray) -> np.ndarray:
        cv = np.zeros(Xn.shape[0])
        for c, cm, s in zip(self.cons, self.fit.constraints, self.s):
            m, _sd = cm.raw(Xn)
            cv = cv + cons_violation(c, m) / s
        if self.space.extra_cv is not None:
            cv = cv + self.space.extra_cv(X)
        return cv

    def mu(self, Xn: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """부호 통일 원 단위 (평균, 표준편차) n×m."""
        ms, ss = zip(*[o.raw(Xn) for o in self.objs])
        return np.stack(ms, axis=1), np.stack(ss, axis=1)

    def pof(self, Xn: np.ndarray) -> np.ndarray:
        p = np.ones(Xn.shape[0])
        for c, cm in zip(self.cons, self.fit.constraints):
            m, s = cm.raw(Xn)
            p = p * cons_pof(c, m, s)
        return p

    def cons_pred(self, Xn: np.ndarray) -> list[float]:
        return [float(cm.raw(Xn)[0][0]) for cm in self.fit.constraints]


def _verified(designs: Sequence[Design], problem: Problem, ev: _Eval, multi: bool) -> tuple[np.ndarray, np.ndarray]:
    """검증 설계의 (부호 통일 목적, 정규화 위반량 CV) — 시드 주입 순서용."""
    F = signed(designs, list(ev.signs)) if multi else np.array([[problem.sign() * d.objective] for d in designs])
    CV = np.array([sum(c.violation(v) / s for v, c, s in zip(d.constraints, problem.constraints, ev.s)) for d in designs])
    return F.reshape(len(designs), -1), CV


def _inject(space: Space, designs: Sequence[Design], problem: Problem, ev: _Eval, multi: bool) -> np.ndarray | None:
    rows, keep = [], []
    for i, d in enumerate(designs):
        x = space.row_of(dict(d.values))
        if x is not None:
            rows.append(x)
            keep.append(i)
    if not rows:
        return None
    F, CV = _verified([designs[i] for i in keep], problem, ev, multi)
    order = evo.rank_order(F, np.where(CV <= evo.FEAS_CV, 0.0, CV))
    return np.array(rows)[order]


def _options(options: dict[str, Any], stall: int, archive_max: int) -> evo.EvoOptions:
    return evo.EvoOptions(int(options["pop_size"]), int(options["generations"]), float(options["crossover_prob"]),
                          None if options.get("mutation_prob") is None else float(options["mutation_prob"]),
                          float(options["eta_c"]), float(options["eta_m"]), int(stall), int(archive_max))


def _population_rows(space: Space, ev: _Eval, res: evo.EvoResult, m: int) -> tuple[list[str], list[list[Any]]]:
    names = space.problem.names + (["baseline"] if "baseline" in space.names and "baseline" not in space.problem.names else [])
    head = [*names, *[f"mu_{i}" for i in range(1, m + 1)], *[f"sd_{i}" for i in range(1, m + 1)], "cv", "rank", "crowding"]
    Xn = space.model_input(res.X)
    mu, sd = ev.mu(Xn)
    rows = []
    for i, x in enumerate(res.X):
        vals = space.values(x)
        rows.append([*[_cell(vals.get(n)) for n in names], *[repr(float(s * v)) for s, v in zip(ev.signs, mu[i])],
                     *[repr(float(v)) for v in sd[i]], repr(float(res.CV[i])),
                     "" if res.rank is None else str(int(res.rank[i])),
                     "" if res.crowding is None else ("inf" if math.isinf(res.crowding[i]) else repr(float(res.crowding[i])))])
    return head, rows


def _cell(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    return repr(float(v))


def _pick_by_distance(space: Space, X: np.ndarray, order: Sequence[int], ref: list[np.ndarray], picked_vals: list[dict[str, Any]],
                      existing: list[dict[str, Any]], k: int, on_pick: Callable[[int], None]) -> None:
    """order 순서로 거리 규칙(≥ 0.1, 못 채우면 반씩 0.0125까지)·중복 제외를 지키며 k개가 될 때까지 on_pick."""
    dmin = RBF_MIN_DIST
    used: set[int] = set()
    while len(picked_vals) < k and dmin >= RBF_MIN_DIST_FLOOR - 1e-15:
        for i in order:
            if len(picked_vals) >= k:
                break
            if i in used:
                continue
            vals = space.values(X[i])
            if any(space.is_same(vals, e) for e in existing) or any(space.is_same(vals, c) for c in picked_vals):
                used.add(i)
                continue
            R = np.array(ref) if ref else np.zeros((0, len(space.genes)))
            if float(space.dist(X[i:i + 1], R)[0]) + 1e-12 < dmin:
                continue
            used.add(i)
            ref.append(X[i])
            on_pick(i)
        if len(picked_vals) >= k:
            break
        dmin /= 2.0


def _existing_rows(space: Space, existing: list[dict[str, Any]]) -> list[np.ndarray]:
    out = []
    for e in existing:
        x = space.row_of(e)
        if x is not None:
            out.append(x)
    return out
