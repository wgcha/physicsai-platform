"""GA·NSGA-II를 대리모델 위 내부 탐색기로 쓰는 후보 선택(opt-native §6.2·§6.5·§6.6) — 워커 전용(numpy·scipy).

- 평가: 집단 전체를 한 번에 대리모델에 넣는다. 단일 = 표준화한 μ(부호 통일), 다목적 = 작업 정규화 μ̃(§22.5.1).
  제약 위반 CV = Σ_c viol_c(μ_c)/s_c(s_c = 제약 자료 표준편차, 하한 1e-12·max(1, |경계|)) + 공간 벌점(범위 분할 NO_COVER).
- 초기 집단 앞에 검증된 설계 중 제약 지배 상위 ⌈0.1·N⌉개를 넣는다.
- GA 후보: c₁ = 최종 최선(role ga), c₂… = 보관 집합 EI×PoF(GP, ga_ei) 또는 평균 오름차순(RBF, ga_div) + 거리 규칙.
- NSGA-II 후보: 예측 전선 P(rank-1 ∧ CV = 0, 없으면 rank-1 중 CV 최소)에서 순차 HVI(role nsga2), P < k면 rank-2부터 crowding 순.
- 난수: 반복 r의 rng 시드 = seed·100000 + r·1000 + 900(§6.2).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from . import evo, pareto
from .algo import ALGO_LABEL
from .dataset import Design, is_feasible
from .infill import RBF_MIN_DIST, RBF_MIN_DIST_FLOOR, _ei
from .evo_eval import _Eval, _existing_rows, _inject, _options, _pick_by_distance, _population_rows
from .evo_space import Space  # noqa: F401 - 300줄 분할(R-B): 탐색 공간, 기존 경로 재노출
from .mo_infill import MoCandidate, c1_order, signed, work_frame

SEED_OFFSET = 900
MAX_PREDICTED_FRONT = 28


def algo_seed(seed: int, round_no: int) -> int:
    return seed * 100000 + round_no * 1000 + SEED_OFFSET


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
