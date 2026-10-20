"""대리모델 적합 묶음과 후보 탐색(phase3 §18.5).

- `fit_all`: 자유 변수 정규화([0,1] = 최적화 범위), 목적(sense=max는 부호 반전) 표준화, 목적 모델 1개 + 제약마다 같은 종류 1개.
  GP가 Cholesky로 실패하면 RBF로 바꾸고 경고 GP_FALLBACK_RBF. 품질 = LOO RMSE(목적 단위)·NRMSE·Q².
- `propose`: 후보 k개 — ① 활용(평균 최소 + 제약 예측 위반 벌점 1e3) ② GP: EI × PoF 최대(kriging believer),
  RBF: 평균 최소 + 기존·선택 점과 정규화 거리 ≥ 0.1(못 찾으면 반으로, 0.0125까지).
  탐색기 = scipy differential_evolution(seed = seed·1000 + r + 100·j, integrality, vectorized, updating="deferred",
  polish = 정수 변수 없을 때만). 고정·자료 상수 변수는 탐색 벡터에서 빼고 그 값으로 채운다. 같은 설계(기존 성공·실패·이미 고른
  후보)는 버리고 다음.
300줄 분할(R-B): 적합 결과 모양·품질은 `infill_model`, 후보(EI·DE·거리 규칙)는 `infill_propose`(여기서 재노출).
`fit_gp`를 부르는 적합(`infill.fit_gp` 조회)은 이 파일.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

import numpy as np

from .dataset import Design, Problem, free_variables
from .gp import GPFitError, fit_gp
from .rbf import RBFFitError, fit_rbf
from .infill_model import (  # noqa: F401 - 기존 경로 재노출
    PENALTY, RBF_MIN_DIST, RBF_MIN_DIST_FLOOR, _DE_PARAMS, SurrogateError, Scaled, FitResult, _standardize, quality,
    design_matrix, cat_index, de_levels, level_seeds,  # opt-native §7 범주 baseline
)
from .infill_propose import Candidate, cons_violation, cons_pof, cons_ok, _de, _ei, propose  # noqa: F401 - 기존 경로 재노출


def _fit_one(kind: str, X: np.ndarray, y: np.ndarray, *, restarts: int, seed: int,
             progress: Callable[[int, int], None] | None, checkpoint: Callable[[], None] | None) -> Any:
    if kind == "gp":
        return fit_gp(X, y, restarts=restarts, seed=seed, progress=progress, checkpoint=checkpoint)
    try:
        return fit_rbf(X, y)
    except RBFFitError as exc:
        raise SurrogateError("SURROGATE_FIT_FAILED", str(exc)) from None


def fit_all(designs: Sequence[Design], problem: Problem, *, kind: str, restarts: int, seed: int,
            progress: Callable[[str], None] | None = None, checkpoint: Callable[[], None] | None = None) -> FitResult:
    free = free_variables(problem, designs)
    if not free:
        raise SurrogateError("NO_FREE_VARIABLE", "자료에서 바뀌는 자유 변수가 없습니다")
    fill = {n: (problem.bounds[n][0] if problem.bounds[n][0] == problem.bounds[n][1] else designs[0].values[n])
            for n in problem.names if n not in free}
    lo = np.array([problem.bounds[n][0] for n in free])
    hi = np.array([problem.bounds[n][1] for n in free])
    X = design_matrix(designs, free, lo, hi, fill, problem)
    sign = problem.sign()
    warnings: list[dict[str, str]] = []
    n_models = 1 + len(problem.constraints)

    def prog(label: str) -> Callable[[int, int], None]:
        def f(i: int, total: int) -> None:
            if progress is not None:
                progress(f"대리모델 학습({kind.upper()}) · {label}재시작 {i}/{total}")
        return f

    def build(k: str) -> tuple[Scaled, list[Scaled]]:
        yo, mo, so = _standardize(np.array([sign * d.objective for d in designs]))
        obj = Scaled(_fit_one(k, X, yo, restarts=restarts, seed=seed, progress=prog("목적 " if n_models > 1 else ""),
                              checkpoint=checkpoint), mo, so)
        cons = []
        for j in range(len(problem.constraints)):
            yc, mc, sc = _standardize(np.array([d.constraints[j] for d in designs]))
            cons.append(Scaled(_fit_one(k, X, yc, restarts=restarts, seed=seed + j + 1, progress=prog(f"제약 {j + 1} "),
                                        checkpoint=checkpoint), mc, sc))
        return obj, cons

    used = kind
    objs = np.array([d.objective for d in designs])
    if kind == "gp" and float(np.ptp(objs)) <= 1e-12 * max(1.0, float(np.max(np.abs(objs)))):
        # 목적 값이 모두 같으면 GP 우도가 정의되지 않는다 — "GP 실패"가 아니라 자료 문제로 알리고 RBF(평평한 면)로 계속
        warnings.append({"code": "OBJECTIVE_CONSTANT",
                         "message": "목적 값이 모든 run에서 같습니다 — 지표·탐색 범위를 확인하세요(RBF로 계속)"})
        kind = used = "rbf"
    try:
        obj, cons = build(kind)
    except GPFitError as exc:
        warnings.append({"code": "GP_FALLBACK_RBF", "message": f"GP 적합에 실패해 RBF로 바꿨습니다({exc})"})
        used = "rbf"
        obj, cons = build("rbf")
    fit = FitResult(used, free, lo, hi, fill, sign, obj, cons, warnings, seed=seed, encoding=problem.cat_spec)
    q = quality(obj)
    # 목적 단위 보고: sign이 -1이면 LOO 예측 부호도 되돌린다
    q["loo_pred"] = [sign * v for v in q["loo_pred"]]
    fit.quality = {"kind": used, "n_train": len(designs), "d_free": len(free), **q}
    return fit
