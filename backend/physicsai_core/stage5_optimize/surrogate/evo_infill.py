"""GA·NSGA-II를 대리모델 위 내부 탐색기로 쓰는 후보 선택(opt-native §6.2·§6.5·§6.6) — 워커 전용(numpy·scipy).

- 평가: 집단 전체를 한 번에 대리모델에 넣는다. 단일 = 표준화한 μ(부호 통일), 다목적 = 작업 정규화 μ̃(§22.5.1).
  제약 위반 CV = Σ_c viol_c(μ_c)/s_c(s_c = 제약 자료 표준편차, 하한 1e-12·max(1, |경계|)) + 공간 벌점(범위 분할 NO_COVER).
- 초기 집단 앞에 검증된 설계 중 제약 지배 상위 ⌈0.1·N⌉개를 넣는다.
- GA 후보: c₁ = 최종 최선(role ga), c₂… = 보관 집합 EI×PoF(GP, ga_ei) 또는 평균 오름차순(RBF, ga_div) + 거리 규칙.
- NSGA-II 후보: 예측 전선 P(rank-1 ∧ CV = 0, 없으면 rank-1 중 CV 최소)에서 순차 HVI(role nsga2), P < k면 rank-2부터 crowding 순.
- 난수: 반복 r의 rng 시드 = seed·100000 + r·1000 + 900(§6.2).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from . import evo, pareto
from .algo import ALGO_LABEL
from .dataset import Design, Problem, is_feasible, same_design
from .infill import RBF_MIN_DIST, RBF_MIN_DIST_FLOOR, FitResult, SurrogateError, _ei, cons_pof, cons_violation
from .mo_infill import MoCandidate, c1_order, signed, work_frame

SEED_OFFSET = 900
MAX_PREDICTED_FRONT = 28


def algo_seed(seed: int, round_no: int) -> int:
    return seed * 100000 + round_no * 1000 + SEED_OFFSET


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
        for n, lo, hi in zip(fit.free, fit.lo, fit.hi):
            kind = "int" if n in problem.integer else "real"
            if kind == "int" and math.ceil(lo - 1e-9) > math.floor(hi + 1e-9):
                raise SurrogateError("BOUNDS_INVALID", f"'{n}' 정수 범위가 비어 있습니다")
            genes.append(evo.Gene(n, kind, float(lo), float(hi)))
        if not genes:
            raise SurrogateError("NO_FREE_VARIABLE", "탐색할 변수가 없습니다")
        return cls(fit, problem, genes, list(fit.free))

    def model_input(self, X: np.ndarray) -> np.ndarray:
        return self.to_model(X) if self.to_model is not None else self.fit.normalize(X)

    def values(self, x: np.ndarray) -> dict[str, Any]:
        if self.to_values is not None:
            return self.to_values(x)
        vals: dict[str, Any] = self.fit.full_values(x)
        for n in self.problem.integer:
            if n in vals:
                vals[n] = float(round(vals[n]))
        return vals

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


@dataclass
class EvoProposal:
    candidates: list[dict[str, Any]]
    optimum: dict[str, Any] | None
    predicted_front: list[dict[str, Any]]  # 다목적: P 전부(DB에는 reduce_front로 28점)
    result: evo.EvoResult
    algo: dict[str, Any]
    population_rows: list[list[Any]] = field(default_factory=list)
    population_head: list[str] = field(default_factory=list)
    warnings: list[dict[str, str]] = field(default_factory=list)


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


def propose_ga(space: Space, designs: Sequence[Design], failed: Sequence[dict[str, float]], *, k: int, seed: int, round_no: int,
               options: dict[str, Any], stall: int, archive_max: int,
               progress: Callable[[int, int], None] | None = None,
               checkpoint: Callable[[], None] | None = None) -> EvoProposal:
    """GA(단일 목적) 후보 최대 k개(§6.3·§6.5)."""
    fit, problem = space.fit, space.problem
    ev = _Eval(space)
    obj = fit.objective

    def evaluate(X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        Xn = space.model_input(X)
        m, _s = obj.model.predict(Xn)
        return m, ev.cv_raw(Xn, X)

    rs = algo_seed(seed, round_no)
    eo = _options(options, stall, archive_max)
    res = evo.run(evaluate, space.genes, m=1, options=eo, seed=rs, inject=_inject(space, designs, problem, ev, False),
                  effective=space.effective, progress=progress, checkpoint=checkpoint)
    existing = [dict(d.values) for d in designs] + [dict(f) for f in failed]
    picked: list[dict[str, Any]] = []
    rows_out: list[dict[str, Any]] = []
    ref = _existing_rows(space, existing)

    def make(x: np.ndarray, role: str, acq: float | None) -> dict[str, Any]:
        Xn = space.model_input(x.reshape(1, -1))
        mm, ss = obj.raw(Xn)
        pred = float(fit.sign * mm[0])
        return {"values": space.values(x), "predicted": pred, "ei": acq if role == "ga_ei" else None,
                "constraints_pred": ev.cons_pred(Xn), "role": role, "weight": None, "predicted_objectives": [pred],
                "predicted_std": [float(ss[0])], "acq": acq, "pof": float(ev.pof(Xn)[0]),
                "cv": float(ev.cv_raw(Xn, x.reshape(1, -1))[0])}

    best = make(res.X[0], "ga", None)
    if not (any(space.is_same(best["values"], e) for e in existing)):
        picked.append(best["values"])
        rows_out.append(best)
        ref.append(res.X[0])
    A = res.archive if res.archive is not None and len(res.archive) else res.X
    An = space.model_input(A)
    mA, sA = obj.model.predict(An)
    if fit.kind == "gp":
        valid_obj = np.array([fit.sign * d.objective for d in designs])
        feas = [i for i, d in enumerate(designs) if is_feasible(d.constraints, problem.constraints)]
        pool = valid_obj[feas] if feas else valid_obj
        fmin = float((np.min(pool) - obj.mean) / obj.std)
        acq = _ei(mA, sA, fmin) * ev.pof(An)
        order = [int(i) for i in np.lexsort((np.arange(len(A)), -acq))]
        role = "ga_ei"
    else:
        acq = None
        order = [int(i) for i in np.lexsort((np.arange(len(A)), mA + 1e6 * ev.cv_raw(An, A)))]
        role = "ga_div"

    def on_pick(i: int) -> None:
        c = make(A[i], role, float(acq[i] * obj.std) if acq is not None else None)
        picked.append(c["values"])
        rows_out.append(c)

    _pick_by_distance(space, A, order, ref, picked, existing, k, on_pick)
    head, prow = _population_rows(space, ev, res, 1)
    best_pred = best["predicted"] if evo.feasible(res.CV[:1])[0] else None
    algo = {"name": "ga", "pop_size": eo.pop_size, "generations": eo.generations, "generations_run": res.generations_run,
            "evals": res.evals, "stop": res.stop, "seed": rs, "best_pred": best_pred, "hv_pred": None,
            "surrogate_optimum": {"values": best["values"], "predicted": best["predicted"]}}
    return EvoProposal(rows_out[:k], best, [], res, algo, prow, head)


def reduce_front(F: np.ndarray, n: int = MAX_PREDICTED_FRONT) -> list[int]:
    """예측 전선 축약(§6.6): 목적별 극점 먼저(동률 = 앞 인덱스), 나머지는 μ̃ 공간 탐욕 max-min 거리(동률 = 앞 인덱스)."""
    F = np.atleast_2d(F)
    if len(F) <= n:
        return list(range(len(F)))
    chosen: list[int] = []
    for i in range(F.shape[1]):
        j = int(np.lexsort((np.arange(len(F)), F[:, i]))[0])
        if j not in chosen:
            chosen.append(j)
    while len(chosen) < n:
        D = np.sqrt(((F[:, None, :] - F[None, chosen, :]) ** 2).sum(axis=2)).min(axis=1)
        D[chosen] = -1.0
        chosen.append(int(np.lexsort((np.arange(len(F)), -D))[0]))
    return chosen[:n]


def propose_nsga2(space: Space, designs: Sequence[Design], failed: Sequence[dict[str, float]], *, k: int, seed: int,
                  round_no: int, options: dict[str, Any], stall: int, hv_frame: dict[str, Any], ref_offset: float,
                  progress: Callable[[int, int], None] | None = None,
                  checkpoint: Callable[[], None] | None = None) -> EvoProposal:
    """NSGA-II(다목적) 예측 전선 + 후보 최대 k개(§6.4·§6.5)."""
    problem = space.problem
    ev = _Eval(space)
    m = problem.m
    Fd = signed(designs, list(ev.signs))
    ideal, delta = work_frame(Fd)

    def evaluate(X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        Xn = space.model_input(X)
        mu, _sd = ev.mu(Xn)
        return (mu - ideal) / delta, ev.cv_raw(Xn, X)

    rs = algo_seed(seed, round_no)
    eo = _options(options, stall, 1)
    R = [1.0 + float(ref_offset)] * m
    res = evo.run(evaluate, space.genes, m=m, options=eo, seed=rs, inject=_inject(space, designs, problem, ev, True), hv_ref=R,
                  effective=space.effective, progress=progress, checkpoint=checkpoint)
    rank, CV = res.rank, res.CV
    assert rank is not None
    uniq = set(int(i) for i in evo.unique_first(res.X, space.effective))
    r1 = [i for i in range(len(res.X)) if rank[i] == 1 and i in uniq]
    feas = [i for i in r1 if CV[i] <= evo.FEAS_CV]
    if feas:
        P = feas
    else:
        cmin = min(float(CV[i]) for i in r1)
        P = [i for i in r1 if CV[i] <= cmin + 1e-12]
    Xn_all = space.model_input(res.X)
    mu_all, sd_all = ev.mu(Xn_all)
    pof_all = ev.pof(Xn_all)
    front_rows = [{"values": space.values(res.X[i]), "mean": [float(s * v) for s, v in zip(ev.signs, mu_all[i])],
                   "std": [float(v) for v in sd_all[i]], "pof": float(pof_all[i])} for i in P]
    mu_tilde_P = res.F[P]
    # 후보: 순차 HVI(HV 틀 f̂), 대체 규칙(모두 ≤ 1e-12면 F까지 최소 거리 최대) + 거리 규칙
    fi, fn = hv_frame["ideal"], hv_frame["nadir"]
    Rf = [1.0 + float(hv_frame.get("ref_offset", ref_offset))] * m
    feas_d = [d for d in designs if is_feasible(d.constraints, problem.constraints)]
    Fv = [pareto.normalize((ev.signs * np.asarray(d.objectives)).tolist(), fi, fn) for d in feas_d]
    Fb = [Fv[i] for i in pareto.nondominated(Fv)] if Fv else []
    pred_n = {i: pareto.normalize(mu_all[i].tolist(), fi, fn) for i in range(len(res.X))}
    existing = [dict(d.values) for d in designs] + [dict(f) for f in failed]
    ref = _existing_rows(space, existing)
    picked_vals: list[dict[str, Any]] = []
    cands: list[MoCandidate] = []
    cand_idx: list[int] = []

    def make(i: int, hvi: float | None) -> MoCandidate:
        Xn = Xn_all[i:i + 1]
        cand_idx.append(i)
        return MoCandidate(space.values(res.X[i]), "nsga2", None, [float(s * v) for s, v in zip(ev.signs, mu_all[i])],
                           [float(v) for v in sd_all[i]], hvi, ev.cons_pred(Xn))

    dmin = RBF_MIN_DIST
    remaining = list(P)
    dead: set[int] = set()
    while len(cands) < k and remaining and dmin >= RBF_MIN_DIST_FLOOR - 1e-15:
        if checkpoint is not None:
            checkpoint()
        order = c1_order([pred_n[i] for i in remaining], Fb, Rf)
        got = False
        for pos, hvi in order:
            i = remaining[pos]
            if i in dead:
                continue
            vals = space.values(res.X[i])
            if any(space.is_same(vals, e) for e in existing) or any(space.is_same(vals, c) for c in picked_vals):
                dead.add(i)
                continue
            Rr = np.array(ref) if ref else np.zeros((0, len(space.genes)))
            if float(space.dist(res.X[i:i + 1], Rr)[0]) + 1e-12 < dmin:
                continue
            cands.append(make(i, float(hvi)))
            picked_vals.append(vals)
            ref.append(res.X[i])
            Fb.append(pred_n[i])
            remaining.remove(i)
            got = True
            break
        remaining = [i for i in remaining if i not in dead]
        if not got:
            dmin /= 2.0
    if len(cands) < k:  # P가 모자라면 rank-2부터 crowding 순(집단은 rank ↑·crowding ↓ 순으로 정렬돼 있다)
        rest = [i for i in range(len(res.X)) if rank[i] >= 2 and i in uniq]

        def on_pick(i: int) -> None:
            cands.append(make(i, None))

        _pick_by_distance(space, res.X, rest, ref, picked_vals, existing, k, on_pick)
    head, prow = _population_rows(space, ev, res, m)
    hv_pred = res.history[-1].get("hv_pred") if res.history else None
    algo = {"name": "nsga2", "pop_size": eo.pop_size, "generations": eo.generations, "generations_run": res.generations_run,
            "evals": res.evals, "stop": res.stop, "seed": rs, "best_pred": None, "hv_pred": hv_pred, "surrogate_optimum": None}
    pos = {id(c): i for i, c in zip(cand_idx, cands)}
    rows = [{**c.as_dict(), "pof": float(pof_all[pos[id(c)]]), "cv": float(CV[pos[id(c)]])} for c in cands[:k]]
    prop = EvoProposal(rows, None, front_rows, res, algo, prow, head)
    prop.algo["front_reduce"] = reduce_front(mu_tilde_P) if len(P) > MAX_PREDICTED_FRONT else None
    return prop


def progress_label(algorithm: str, gen: int, total: int) -> str:
    return f"후보 탐색({ALGO_LABEL.get(algorithm, algorithm)} 세대 {gen}/{total})"
