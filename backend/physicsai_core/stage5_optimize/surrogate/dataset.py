"""내장 최적화 자료(phase3 §18.4 SO_COLLECT·§18.5 정지 판정) — 표준 라이브러리만(API·워커 공용).

설계점 = run 1개의 반영값(applied_values) + 목적·제약 지표 값. 같은 설계(정수 변수 같고 연속 변수 |Δ| ≤ 1e-9·범위)는
평균으로 합치고, 실패·값 없음 run은 "실패 설계"(다시 제안하지 않음)로 둔다. 목적 sense=max는 계산 안에서 부호를 뒤집어
최소화로 통일하고, 보고 값(best_value 등)은 원래 부호로 돌려준다.
"""

from __future__ import annotations

import csv
import io
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

SAME_TOL = 1e-9
FEAS_TOL = 1e-9
STOP_CONVERGED = "CONVERGED"
STOP_MAX_ITER = "MAX_ITER"
STOP_NO_NEW = "NO_NEW_CANDIDATE"
FAIL_VERIFY_ALL = "VERIFY_ALL_FAILED"
FAIL_TOO_FEW = "TOO_FEW_POINTS"
FAIL_TIMEOUT = "SURROGATE_TIMEOUT"


@dataclass(frozen=True)
class Constraint:
    metric: str
    series: str | None
    op: str  # "<=" | ">="
    value: float

    @property
    def key(self) -> str:
        return self.metric if self.series is None else f"{self.metric}@{self.series}"


@dataclass
class Problem:
    """정규화된 최적화 문제(opt.settings에서)."""

    names: list[str]  # 템플릿 파라미터 전부(템플릿 순서)
    integer: set[str]
    bounds: dict[str, tuple[float, float]]  # lo = hi면 고정
    sense: str  # "min" | "max"
    constraints: list[Constraint] = field(default_factory=list)

    @classmethod
    def from_settings(cls, settings: Mapping[str, Any]) -> Problem:
        b = {k: (float(v[0]), float(v[1])) for k, v in settings["bounds"].items()}
        cons = [Constraint(c["metric"], c.get("series"), c["op"], float(c["value"])) for c in settings.get("constraints") or []]
        return cls(list(settings["names"]), set(settings.get("integer") or []), b, settings["objective"]["sense"], cons)

    def fixed(self) -> dict[str, float]:
        return {n: lo for n, (lo, hi) in self.bounds.items() if lo == hi}

    def span(self, name: str) -> float:
        lo, hi = self.bounds[name]
        return hi - lo

    def sign(self) -> float:
        return -1.0 if self.sense == "max" else 1.0


@dataclass
class Point:
    """검증된 run 1개(성공 + 목적 값 있음이면 valid)."""

    iter_no: int
    batch_label: str
    doe_no: int
    run_key: str
    values: dict[str, float]
    objective: float | None
    constraints: list[float | None]
    state: str
    job_id: str | None = None
    batch_id: str | None = None

    @property
    def valid(self) -> bool:
        return self.state == "SUCCEEDED" and self.objective is not None and all(c is not None for c in self.constraints)


@dataclass
class Design:
    """같은 설계를 합친 학습 점(평균)."""

    values: dict[str, float]
    objective: float
    constraints: list[float]
    sources: list[Point]


def finite(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return None
    return float(v)


def same_design(a: Mapping[str, float], b: Mapping[str, float], problem: Problem) -> bool:
    for n in problem.names:
        x, y = a.get(n), b.get(n)
        if x is None or y is None:
            return False
        if n in problem.integer:
            if round(x) != round(y):
                return False
        elif abs(x - y) > SAME_TOL * max(problem.span(n), 1.0):
            return False
    return True


def merge(points: Sequence[Point], problem: Problem) -> tuple[list[Design], list[dict[str, float]]]:
    """(학습 설계 — 중복 평균, 실패 설계 값 목록)."""
    designs: list[Design] = []
    failed: list[dict[str, float]] = []
    for p in points:
        if not p.valid:
            failed.append(dict(p.values))
            continue
        hit = next((d for d in designs if same_design(d.values, p.values, problem)), None)
        if hit is None:
            designs.append(Design(dict(p.values), float(p.objective), [float(c) for c in p.constraints], [p]))  # type: ignore[arg-type]
            continue
        hit.sources.append(p)
        k = len(hit.sources)
        hit.objective += (float(p.objective) - hit.objective) / k  # type: ignore[arg-type]
        hit.constraints = [c + (float(v) - c) / k for c, v in zip(hit.constraints, p.constraints)]  # type: ignore[arg-type]
    return designs, failed


def violation(values: Sequence[float | None], constraints: Sequence[Constraint]) -> float:
    """제약 위반량 합(원 단위, 값 없음 = 무한)."""
    tot = 0.0
    for v, c in zip(values, constraints):
        if v is None:
            return math.inf
        tot += max(0.0, v - c.value) if c.op == "<=" else max(0.0, c.value - v)
    return tot


def is_feasible(values: Sequence[float | None], constraints: Sequence[Constraint]) -> bool:
    lim = FEAS_TOL * max([1.0, *[abs(c.value) for c in constraints]])
    return violation(values, constraints) <= lim


def best_point(points: Sequence[Point], problem: Problem) -> tuple[Point, bool] | None:
    """검증된 최선(제약 만족 우선, 없으면 위반량 최소). (점, feasible). 동률이면 먼저 나온 점."""
    valid = [p for p in points if p.valid]
    if not valid:
        return None
    feas = [p for p in valid if is_feasible(p.constraints, problem.constraints)]
    s = problem.sign()
    if feas:
        return min(feas, key=lambda p: s * float(p.objective)), True  # type: ignore[arg-type]
    return min(valid, key=lambda p: (violation(p.constraints, problem.constraints), s * float(p.objective))), False  # type: ignore[arg-type]


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


CURVE_LABELS = {"max": "커브 최대값", "min": "커브 최소값", "absmax": "커브 |최대|"}


def metric_label(metric: str, series: str | None = None) -> str:
    """지표 id → 표시 이름: `resp:CornerStress_MAX` → `CornerStress_MAX`, `curve:max` → `커브 최대값(계열)`."""
    kind, _, key = metric.partition(":")
    if kind == "curve":
        base = CURVE_LABELS.get(key, metric)
        return f"{base}({series})" if series else base
    return key or metric


def _num(v: Any) -> str:
    f = finite(v)
    return "" if f is None else repr(f)


def dataset_csv(points: Sequence[Point], problem: Problem, *, predicted: Mapping[tuple[int, int], float] | None = None,
                with_feasible: bool = False, bom: bool = False, crlf: bool = False) -> str:
    """iter·batch·doe_no·run_key·<변수>·objective·<제약>·(predicted·feasible)·state."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n" if crlf else "\n")
    cons = [c.key for c in problem.constraints]
    head = ["iter", "batch", "doe_no", "run_key", *problem.names, "objective", *cons]
    if with_feasible:
        head += ["predicted", "feasible"]
    w.writerow([*head, "state"])
    for p in points:
        row: list[Any] = [p.iter_no, p.batch_label, p.doe_no, p.run_key, *[_num(p.values.get(n)) for n in problem.names],
                          _num(p.objective), *[_num(v) for v in p.constraints]]
        if with_feasible:
            pv = (predicted or {}).get((p.iter_no, p.doe_no))
            feas = "" if not p.valid else ("true" if is_feasible(p.constraints, problem.constraints) else "false")
            row += [_num(pv), feas]
        w.writerow([*row, p.state])
    text = buf.getvalue()
    return ("﻿" + text) if bom else text


def read_dataset_csv(text: str, problem: Problem) -> list[Point]:
    """dataset_csv 결과를 다시 Point로(워커 step 사이 전달)."""
    rows = list(csv.reader(io.StringIO(text.lstrip("﻿"))))
    head = rows[0]
    idx = {h: i for i, h in enumerate(head)}
    out = []
    for r in rows[1:]:
        if not r:
            continue

        def f(name: str) -> float | None:
            s = r[idx[name]]
            return float(s) if s != "" else None

        vals = {n: v for n in problem.names if (v := f(n)) is not None}
        out.append(Point(int(r[idx["iter"]]), r[idx["batch"]], int(r[idx["doe_no"]]), r[idx["run_key"]], vals,
                         f("objective"), [f(c.key) for c in problem.constraints], r[idx["state"]]))
    return out
