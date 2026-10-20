"""다목적 대리모델·후보(phase3 §22.5 S17) — numpy·scipy(워커 전용, API는 import하지 않는다).

- `fit_mo`: 목적마다 GP 1개(부호 통일 = 최소화) + 제약마다 1개(§18.5와 같은 Matérn 5/2 ARD). GP 실패는 그 모델만 RBF + 경고.
- `propose_mo`: ① 예측 전선 = Das–Dennis 격자 가중치마다 증강 Chebyshev(작업 정규화 μ̃) + 제약 벌점을 DE로 최소화 →
  예측 만족(PoF ≥ 0.5)·μ 비지배 점 ② 후보 c₁ = 검증 전선 대비 HVI 최대(0이면 목적 공간 거리 최대) ③ c₂… = ParEGO
  (반복마다 순열로 배정한 가중치의 스칼라화 GP, EI × Π PoF) — RBF면 s_w(RBF) 최소 + 거리 규칙.
- `run_offline`: 해석 함수를 평가기로 쓰는 루프(시험 전용, V3-S17-7).
시드 식은 §22.5.7. 같은 자료·설정·시드면 같은 후보(같은 numpy/scipy 기준).
300줄 분할(R-B): 격자·스칼라화는 `mo_frame`, 후보 모양·배정·DE 문맥은 `mo_propose`(여기서 재노출).
`fit_gp`를 부르는 적합·제안(`mo_infill.fit_gp` 조회)과 오프라인 루프는 이 파일.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from typing import Any

import numpy as np

from . import pareto
from .dataset import Design, Point, Problem, free_variables, is_feasible, merge, same_design
from .gp import GPFitError, fit_gp, lhs_unit
from .infill import (
    PENALTY, RBF_MIN_DIST, RBF_MIN_DIST_FLOOR, FitResult, Scaled, SurrogateError, _ei, _standardize, quality,
)
from .rbf import RBFFitError, fit_rbf
from .mo_frame import HVI_ZERO, MoCfg, lattice, chebyshev, work_frame, signed  # noqa: F401 - 기존 경로 재노출
from .mo_propose import MoCandidate, MoProposal, assign_weights, c1_order, _de_full, _Ctx  # noqa: F401 - 기존 경로 재노출


# ---- 적합(SO_FIT) --------------------------------------------------------------------------------


def _one(kind: str, X: np.ndarray, y: np.ndarray, *, restarts: int, seed: int, label: str, warnings: list[dict[str, str]],
         progress: Callable[[int, int], None] | None, checkpoint: Callable[[], None] | None) -> Scaled:
    ys, mean, std = _standardize(y)
    if kind == "gp" and float(np.ptp(y)) <= 1e-12 * max(1.0, float(np.max(np.abs(y)))):
        warnings.append({"code": "OBJECTIVE_CONSTANT", "message": f"{label} 값이 모든 run에서 같습니다 — 지표·탐색 범위를 확인하세요(RBF로 계속)"})
        kind = "rbf"
    if kind == "gp":
        try:
            return Scaled(fit_gp(X, ys, restarts=restarts, seed=seed, progress=progress, checkpoint=checkpoint), mean, std)
        except GPFitError as exc:
            warnings.append({"code": "GP_FALLBACK_RBF", "message": f"{label} GP 적합에 실패해 RBF로 바꿨습니다({exc})"})
    try:
        return Scaled(fit_rbf(X, ys), mean, std)
    except RBFFitError as exc:
        raise SurrogateError("SURROGATE_FIT_FAILED", f"{label}: {exc}") from None


def fit_mo(designs: Sequence[Design], problem: Problem, *, kind: str, restarts: int, seed: int,
           progress: Callable[[str], None] | None = None, checkpoint: Callable[[], None] | None = None) -> FitResult:
    """목적별·제약별 모델. 목적 i 시드 = seed + 17·i, 제약 c 시드 = seed + 31·(c+1)(§22.5.7)."""
    free = free_variables(problem, designs)
    if not free:
        raise SurrogateError("NO_FREE_VARIABLE", "자료에서 바뀌는 자유 변수가 없습니다")
    fill = {n: (problem.bounds[n][0] if problem.bounds[n][0] == problem.bounds[n][1] else designs[0].values[n])
            for n in problem.names if n not in free}
    lo = np.array([problem.bounds[n][0] for n in free])
    hi = np.array([problem.bounds[n][1] for n in free])
    X = (np.array([[d.values[n] for n in free] for d in designs]) - lo) / (hi - lo)
    signs = problem.signs()
    m = problem.m
    warnings: list[dict[str, str]] = []

    def prog(label: str) -> Callable[[int, int], None]:
        def f(i: int, total: int) -> None:
            if progress is not None:
                progress(f"대리모델 학습({kind.upper()}) · {label} · 재시작 {i}/{total}")
        return f

    F = signed(designs, signs)
    objs = []
    for i, o in enumerate(problem.objectives):
        name = f"목적 {i + 1}({o.metric})"
        objs.append(_one(kind, X, F[:, i], restarts=restarts, seed=seed + 17 * i, label=name, warnings=warnings,
                         progress=prog(f"목적 {i + 1}/{m}"), checkpoint=checkpoint))
    cons = []
    nc = len(problem.constraints)
    for j, c in enumerate(problem.constraints):
        y = np.array([d.constraints[j] for d in designs], dtype=float)
        cons.append(_one("gp" if kind == "gp" else "rbf", X, y, restarts=restarts, seed=seed + 31 * (j + 1),
                         label=f"제약 {j + 1}({c.metric})", warnings=warnings,
                         progress=prog(f"제약 {j + 1}/{nc}"), checkpoint=checkpoint))
    fit = FitResult(kind, free, lo, hi, fill, signs[0], objs[0], cons, warnings, seed=seed, objectives=objs, signs=signs)
    per = []
    loo_rows: list[list[Any]] = []
    for i, (o, s) in enumerate(zip(problem.objectives, objs)):
        q = quality(s)
        per.append({"metric": o.metric, "kind": s.model.kind, "n_train": len(designs), "loo_rmse": q["loo_rmse"],
                    "loo_nrmse": q["loo_nrmse"], "q2": q["q2"], "pred_vs_verified_mae": None})
        mean, var = s.model.loo()
        for r, (yv, mv, vv) in enumerate(zip(s.model.y, mean, var)):
            loo_rows.append([f"objective_{i + 1}", r, signs[i] * float(yv * s.std + s.mean), signs[i] * float(mv * s.std + s.mean),
                             float(math.sqrt(max(float(vv), 0.0)) * s.std)])
    for j, s in enumerate(cons):
        mean, var = s.model.loo()
        for r, (yv, mv, vv) in enumerate(zip(s.model.y, mean, var)):
            loo_rows.append([f"constraint_{j + 1}", r, float(yv * s.std + s.mean), float(mv * s.std + s.mean),
                             float(math.sqrt(max(float(vv), 0.0)) * s.std)])
    first = per[0]
    fit.quality = {"kind": kind if all(s.model.kind == kind for s in objs) else "mixed", "n_train": len(designs),
                   "d_free": len(free), "loo_rmse": first["loo_rmse"], "loo_nrmse": first["loo_nrmse"], "q2": first["q2"],
                   "per_objective": per, "loo_rows": loo_rows}
    return fit


def propose_mo(fit: FitResult, problem: Problem, designs: Sequence[Design], failed: Sequence[dict[str, float]], *, k: int,
               seed: int, round_no: int, cfg: MoCfg, hv_frame: dict[str, Any], used_weights: Sequence[int] = (),
               progress: Callable[[int, int, str], None] | None = None,
               checkpoint: Callable[[], None] | None = None) -> MoProposal:
    """예측 전선 + 후보 최대 k개(§22.5.3·§22.5.4)."""
    st = _Ctx(fit, problem, designs, failed)
    m = problem.m
    W = lattice(m, cfg.h2 if m == 2 else cfg.h3)
    F = signed(designs, st.signs.tolist())
    ideal, delta = work_frame(F)
    frame_ideal, frame_nadir = hv_frame["ideal"], hv_frame["nadir"]
    R = [1.0 + float(hv_frame.get("ref_offset", cfg.ref_offset))] * m
    base = seed * 100000 + round_no * 1000
    warnings: list[dict[str, str]] = []

    def mu_tilde(Xn: np.ndarray) -> np.ndarray:
        return (st.mu(Xn)[0] - ideal) / delta

    # ① 예측 전선
    pool: list[np.ndarray] = []
    for j, w in enumerate(W):
        if progress is not None:
            progress(j + 1, len(W), f"예측 전선 {j + 1}/{len(W)}")

        def f_w(xT: np.ndarray, w: tuple[float, ...] = w) -> np.ndarray:
            Xn = fit.normalize(np.atleast_2d(xT.T))
            v = chebyshev(mu_tilde(Xn), w, cfg.rho)
            return v + PENALTY * st.penalty(Xn) if st.cons else v

        x = st.round_x(_de_full(f_w, st.bounds, st.ints, seed=base + j, maxiter=cfg.de_maxiter, popsize=cfg.de_popsize,
                                checkpoint=checkpoint)[0])
        if not any(same_design(st.values(x), st.values(q), problem) for q in pool):
            pool.append(x)
    Xp = fit.normalize(np.array(pool))
    mu_p, sd_p = st.mu(Xp)
    pof_each = st.pof(Xp, each=True)
    ok = [i for i in range(len(pool)) if np.all(pof_each[i] >= 0.5)]
    nd = [ok[i] for i in pareto.nondominated([mu_p[i].tolist() for i in ok])]
    front_rows = [{"values": st.values(pool[i]), "mean": [float(s * v) for s, v in zip(st.signs, mu_p[i])],
                   "std": [float(v) for v in sd_p[i]], "pof": float(np.prod(pof_each[i]))} for i in nd]

    # ② c₁ — 전선 확장 활용(HVI)
    feas = [d for d in designs if is_feasible(d.constraints, problem.constraints)]
    Fv = [pareto.normalize((st.signs * np.asarray(d.objectives)).tolist(), frame_ideal, frame_nadir) for d in feas]
    Fv = [Fv[i] for i in pareto.nondominated(Fv)]
    cand_idx = nd or list(range(len(pool)))
    pred_n = [pareto.normalize(mu_p[i].tolist(), frame_ideal, frame_nadir) for i in cand_idx]
    n_hvi = max(1, math.ceil(k * cfg.hvi_share_m3)) if m == 3 and cfg.hvi_share_m3 > 0 else 1
    taken: set[int] = set()
    Fb = list(Fv)
    while len(st.picked) < min(n_hvi, k):
        if progress is not None:
            progress(len(st.picked) + 1, k, f"후보 {len(st.picked) + 1}/{k}")
        got = False
        for pos, hvi in c1_order(pred_n, Fb, R):
            if pos in taken:
                continue
            taken.add(pos)
            c = st.make(pool[cand_idx[pos]], "hvi", None, float(hvi))
            if not st.is_dup(c.values):
                st.picked.append(c)
                Fb.append(pred_n[pos])  # 다음 HVI 후보는 고른 점을 전선에 더한 뒤(서로 다른 점)
                got = True
                break
        if not got:
            break
    prox = cfg.front_prox_m3 if m == 3 else 0.0
    Xfront = Xp[nd] if prox > 0 and nd else None

    # ③ c₂… — ParEGO(GP) 또는 RBF 거리 규칙
    chosen, used = assign_weights(len(W), k - len(st.picked), seed=seed, round_no=round_no, used=used_weights)
    Ft = (F - ideal) / delta
    valid_feas = np.array([is_feasible(d.constraints, problem.constraints) for d in designs])
    Xd = fit.normalize(np.array([[d.values[n] for n in fit.free] for d in designs]))
    dmin = RBF_MIN_DIST
    for n_done, j in enumerate(chosen):
        if len(st.picked) >= k:
            break
        if progress is not None:
            progress(len(st.picked) + 1, k, f"후보 {len(st.picked) + 1}/{k}")
        w = W[j]
        if fit.kind == "gp":
            y = chebyshev(Ft, w, cfg.rho)
            ys, ym, ysd = _standardize(y)
            try:
                gpw = fit_gp(Xd, ys, restarts=cfg.gp_restarts, seed=base + 500 + j, checkpoint=checkpoint)
            except GPFitError as exc:
                warnings.append({"code": "GP_FALLBACK_RBF", "message": f"ParEGO 가중 {list(w)} GP 적합 실패 — 건너뜀({exc})"})
                continue
            ref_y = y[valid_feas] if np.any(valid_feas) else y
            fmin = float((np.min(ref_y) - ym) / ysd)

            def acq(xT: np.ndarray, gpw: Any = gpw, fmin: float = fmin) -> np.ndarray:
                Xn = fit.normalize(np.atleast_2d(xT.T))
                mm, ss = gpw.predict(Xn)
                a = _ei(mm, ss, fmin) * st.pof(Xn)
                if Xfront is not None:
                    dist = np.sqrt(((Xn[:, None, :] - Xfront[None, :, :]) ** 2).sum(axis=2)).min(axis=1)
                    a = a * np.exp(-prox * dist / math.sqrt(Xn.shape[1]))
                return -a

            pop = _de_full(acq, st.bounds, st.ints, seed=base + 700 + j, maxiter=cfg.de_maxiter, popsize=cfg.de_popsize,
                           checkpoint=checkpoint)
            for x in pop:
                x = st.round_x(x)
                c = st.make(x, "parego", list(w), float(-acq(x.reshape(-1, 1))[0] * ysd))
                if not st.is_dup(c.values):
                    st.picked.append(c)
                    break
        else:
            while dmin >= RBF_MIN_DIST_FLOOR:
                ref = np.array([fit.normalize(np.array([e[n] for n in fit.free]))[0]
                                for e in st.existing + [c.values for c in st.picked]])
                dd = len(fit.free)

                def f_rbf(xT: np.ndarray, ref: np.ndarray = ref, dmin: float = dmin, w: tuple[float, ...] = w) -> np.ndarray:
                    Xn = fit.normalize(np.atleast_2d(xT.T))
                    v = chebyshev(mu_tilde(Xn), w, cfg.rho)
                    if st.cons:
                        v = v + PENALTY * st.penalty(Xn)
                    dist = np.sqrt(((Xn[:, None, :] - ref[None, :, :]) ** 2).sum(axis=2)).min(axis=1) / math.sqrt(dd)
                    return v + 1e6 * np.maximum(0.0, dmin - dist)

                x = st.round_x(_de_full(f_rbf, st.bounds, st.ints, seed=base + 700 + j, maxiter=cfg.de_maxiter,
                                        popsize=cfg.de_popsize, checkpoint=checkpoint)[0])
                xn = fit.normalize(x)[0]
                dist = float(np.sqrt(((ref - xn) ** 2).sum(axis=1)).min() / math.sqrt(dd)) if len(ref) else math.inf
                c = st.make(x, "rbf", list(w), None)
                if dist + 1e-12 >= dmin and not st.is_dup(c.values):
                    st.picked.append(c)
                    break
                dmin /= 2.0
    seeds = {"front_de": [base + j for j in range(len(W))], "perm": seed * 1000 + round_no,
             "parego_gp": [base + 500 + j for j in chosen], "parego_de": [base + 700 + j for j in chosen]}
    return MoProposal(st.picked[:k], front_rows, used, seeds, warnings)


# ---- 시험 전용 오프라인 루프(V3-S17-7) -------------------------------------------------------------


def run_offline(func: Callable[[np.ndarray], Sequence[float]], d: int, m: int, *, n0: int, iterations: int, k: int, seed: int,
                kind: str = "gp", cfg: MoCfg | None = None, restarts: int = 4, lhs_only: bool = False) -> dict[str, Any]:
    """[0,1]^d 위 해석 함수(최소화 m목적)를 평가기로 쓰는 루프: LHS n0 → (적합·후보 k)×iterations. lhs_only면 같은 예산의
    LHS만. 반환 {X, F(n×m), iter}. 실제 작업·DB 없음."""
    cfg = cfg or MoCfg()
    names = [f"x{i}" for i in range(d)]
    settings = {"names": names, "integer": [], "bounds": {n: [0.0, 1.0] for n in names},
                "objectives": [{"metric": f"f{i}", "series": None, "sense": "min"} for i in range(m)],
                "objective": {"metric": "f0", "series": None, "sense": "min"}, "constraints": []}
    problem = Problem.from_settings(settings)
    rng = np.random.default_rng(seed)
    X0 = lhs_unit(rng, n0 + iterations * k if lhs_only else n0, d)  # LHS만: 같은 예산 전부 LHS
    pts: list[Point] = []

    def add(x: np.ndarray, it: int, no: int) -> None:
        f = [float(v) for v in func(np.asarray(x, dtype=float))]
        pts.append(Point(it, "B", no, f"run_{no}", {n: float(v) for n, v in zip(names, x)}, f[0], [], "SUCCEEDED", objectives=f))

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
    for r in range(1, iterations + 1):
        designs, failed = merge(pts, problem)
        fit = fit_mo(designs, problem, kind=kind, restarts=restarts, seed=seed * 1000 + r)
        prop = propose_mo(fit, problem, designs, failed, k=k, seed=seed, round_no=r, cfg=cfg, hv_frame=frame, used_weights=used)
        used = prop.used_weights
        if not prop.candidates:
            break
        for c in prop.candidates:
            no += 1
            add(np.array([c.values[n] for n in names]), r, no)
    return _offline_out(pts)


def _offline_out(pts: Sequence[Point]) -> dict[str, Any]:
    return {"X": np.array([[p.values[n] for n in sorted(p.values, key=lambda s: int(s[1:]))] for p in pts]),
            "F": np.array([list(p.objectives or []) for p in pts], dtype=float), "iter": [p.iter_no for p in pts]}
