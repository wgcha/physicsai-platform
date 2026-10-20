"""내장 최적화 자료(phase3 §18.4 SO_COLLECT·§18.5 정지 판정) — 표준 라이브러리만(API·워커 공용).

설계점 = run 1개의 반영값(applied_values) + 목적·제약 지표 값. 같은 설계(정수 변수 같고 연속 변수 |Δ| ≤ 1e-9·범위)는
평균으로 합치고, 실패·값 없음 run은 "실패 설계"(다시 제안하지 않음)로 둔다. 목적 sense=max는 계산 안에서 부호를 뒤집어
최소화로 통일하고, 보고 값(best_value 등)은 원래 부호로 돌려준다.
S17(§22.4.3): 목적 1~3개(`objectives`, objective = objectives[0] 호환), 관찰 지표(값 없어도 유효), 제약 `range`(lo~hi).
300줄 분할(R-B): 문제·점·설계 모양과 가능해·최선 점은 `dataset_model`, 다목적 HV 계산은 `dataset_mo`, dataset.csv 읽기·쓰기는 `dataset_csv`(여기서 재노출).
"""

from __future__ import annotations

from collections.abc import Sequence
from .dataset_model import (  # noqa: F401 - 기존 경로 재노출
    SAME_TOL, FEAS_TOL, STOP_CONVERGED, STOP_MAX_ITER, STOP_NO_NEW, FAIL_VERIFY_ALL, FAIL_TOO_FEW, FAIL_TIMEOUT,
    Constraint, Objective, Metric, settings_objectives, Problem, Point, Design, finite, same_design, merge, violation,
    is_feasible, best_point,
)
from .dataset_mo import (  # noqa: F401 - 기존 경로 재노출
    signed_objectives, make_hv_frame, front_designs, hv_value, recommend_design, hv_improvement_rel,
)
from .dataset_mb import CAT, cat_spec, cover_spec, covered, canonical_values, run_values, tag_baseline  # noqa: F401 - opt-native §7
from .dataset_csv import CURVE_LABELS, metric_label, dataset_csv, read_dataset_csv  # noqa: F401 - 기존 경로 재노출


def improvement_rel(prev: tuple[float, bool] | None, cur: tuple[float, bool] | None, sense: str) -> float | None:
    """(best_{t−1} − best_t)/max(|best_{t−1}|, 1e-12) 최소화 기준. 불가 → None, 처음 만족 설계가 생기면 1.0."""
    if prev is None or cur is None:
        return None
    if cur[1] and not prev[1]:
        return 1.0
    s = -1.0 if sense == "max" else 1.0
    a, b = s * prev[0], s * cur[0]
    return (a - b) / max(abs(a), 1e-12)


def min_points(d_free: int) -> int:
    return max(5, d_free + 2)


def default_explore_count(d_free: int, max_runs: int) -> int:
    return min(max(10, 4 * d_free), max_runs)


def free_variables(problem: Problem, designs: Sequence[Design] | None = None) -> list[str]:
    """고정 아님 + (자료가 있으면) 자료에서 상수 아님. 템플릿 순서."""
    out = []
    for n in problem.names:
        lo, hi = problem.bounds[n]
        if lo == hi:
            continue
        if designs:
            vals = [d.values[n] for d in designs]
            if max(vals) - min(vals) <= 1e-12 * max(hi - lo, 1.0):
                continue
        out.append(n)
    return out


def stop_reason(*, round_no: int, iterations: int, improvement: float | None, tol_rel: float) -> str | None:
    """SO_COLLECT 정지 판정(r ≥ 2): 개선 < tol → CONVERGED, 반복 다 씀 → MAX_ITER."""
    t = round_no - 1
    if round_no >= 2 and improvement is not None and improvement < tol_rel:
        return STOP_CONVERGED
    if t >= iterations:
        return STOP_MAX_ITER
    return None
