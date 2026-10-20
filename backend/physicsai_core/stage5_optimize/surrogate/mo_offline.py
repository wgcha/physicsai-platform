"""다목적·GA·NSGA-II 시험 전용 오프라인 루프(V3-S17-7·V-ON-8) — mo_infill에서 재노출(R-B 300줄 분할, 동작 불변).

`run_offline`: 해석 함수를 평가기로 쓰는 루프. `fit_mo`·`propose_mo`는 시험이 `mo_infill.fit_gp`를 바꿔 끼우므로 mo_infill에
남기고, 여기서는 호출 시점에 가져온다(순환 import 회피)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

import numpy as np

from . import pareto
from .dataset import Point, Problem, merge
from .gp import lhs_unit
from .mo_frame import MoCfg, signed



def run_offline(func: Callable[[np.ndarray], Sequence[float]], d: int, m: int, *, n0: int, iterations: int, k: int, seed: int,
                kind: str = "gp", cfg: MoCfg | None = None, restarts: int = 4, lhs_only: bool = False,
                algorithm: str = "ego", algo_options: dict[str, Any] | None = None,
                constraints: Sequence[dict[str, Any]] = (), stall: int = 30, archive_max: int = 5000) -> dict[str, Any]:
    """[0,1]^d 위 해석 함수(최소화 m목적)를 평가기로 쓰는 루프: LHS n0 → (적합·후보 k)×iterations. lhs_only면 같은 예산의
    LHS만. 반환 {X, F(n×m), iter, candidates}. 실제 작업·DB 없음.
    opt-native V-ON-8: algorithm ga(m = 1)·nsga2(m ≥ 2)면 GA·NSGA-II 내부 탐색기(algo_options = 사용값 — 생략 = 기본).
    constraints = 제약 정의(settings 형식) — func는 목적 m개 뒤에 제약 값을 이어서 돌려준다."""
    from .mo_infill import fit_mo, propose_mo

    cfg = cfg or MoCfg()
    names = [f"x{i}" for i in range(d)]
    settings = {"names": names, "integer": [], "bounds": {n: [0.0, 1.0] for n in names},
                "objectives": [{"metric": f"f{i}", "series": None, "sense": "min"} for i in range(m)],
                "objective": {"metric": "f0", "series": None, "sense": "min"}, "constraints": list(constraints)}
    problem = Problem.from_settings(settings)
    nc = len(problem.constraints)
    rng = np.random.default_rng(seed)
    X0 = lhs_unit(rng, n0 + iterations * k if lhs_only else n0, d)  # LHS만: 같은 예산 전부 LHS
    pts: list[Point] = []
    cand_log: list[dict[str, Any]] = []

    def add(x: np.ndarray, it: int, no: int) -> None:
        out = [float(v) for v in func(np.asarray(x, dtype=float))]
        f, cv = out[:m], out[m:m + nc]
        pts.append(Point(it, "B", no, f"run_{no}", {n: float(v) for n, v in zip(names, x)}, f[0], list(cv), "SUCCEEDED",
                         objectives=f))

    for i, x in enumerate(X0, 1):
        add(x, 0, i)
    if lhs_only:
        return _offline_out(pts)
    designs, _ = merge(pts, problem)
    Fs = signed(designs, problem.signs())
    ideal, nadir = pareto.make_frame(Fs.tolist())
    frame = {"ideal": ideal, "nadir": nadir, "ref_offset": cfg.ref_offset, "signs": problem.signs()}
    used: list[int] = []
    no = len(pts)
    if algorithm != "ego":
        from . import algo as so_algo
        from . import evo_infill
        from .infill import fit_all

        n_g = d
        from ...config.schema_stages import SurrogateOptCfg

        base = so_algo.resolve_options(algorithm, None, n_g, SurrogateOptCfg(), problem.m)
        opts = {**base, **(algo_options or {})}
    for r in range(1, iterations + 1):
        designs, failed = merge(pts, problem)
        if algorithm == "ga":
            fit = fit_all(designs, problem, kind=kind, restarts=restarts, seed=seed * 1000 + r)
            ep = evo_infill.propose_ga(evo_infill.Space.basic(fit, problem), designs, failed, k=k, seed=seed, round_no=r,
                                       options=opts, stall=stall, archive_max=archive_max)
            vals = [c["values"] for c in ep.candidates]
            cand_log += [{**c, "round": r} for c in ep.candidates]
        elif algorithm == "nsga2":
            fit = fit_mo(designs, problem, kind=kind, restarts=restarts, seed=seed * 1000 + r)
            ep = evo_infill.propose_nsga2(evo_infill.Space.basic(fit, problem), designs, failed, k=k, seed=seed, round_no=r,
                                          options=opts, stall=stall, hv_frame=frame, ref_offset=cfg.ref_offset)
            vals = [c["values"] for c in ep.candidates]
            cand_log += [{**c, "round": r} for c in ep.candidates]
        else:
            fit = fit_mo(designs, problem, kind=kind, restarts=restarts, seed=seed * 1000 + r)
            prop = propose_mo(fit, problem, designs, failed, k=k, seed=seed, round_no=r, cfg=cfg, hv_frame=frame,
                              used_weights=used)
            used = prop.used_weights
            vals = [c.values for c in prop.candidates]
        if not vals:
            break
        for v in vals:
            no += 1
            add(np.array([v[n] for n in names]), r, no)
    out = _offline_out(pts)
    out["candidates"] = cand_log
    return out


def _offline_out(pts: Sequence[Point]) -> dict[str, Any]:
    return {"X": np.array([[p.values[n] for n in sorted(p.values, key=lambda s: int(s[1:]))] for p in pts]),
            "F": np.array([list(p.objectives or []) for p in pts], dtype=float), "iter": [p.iter_no for p in pts]}
