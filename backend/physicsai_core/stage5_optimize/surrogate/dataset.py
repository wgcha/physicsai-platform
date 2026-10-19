"""내장 최적화 자료(phase3 §18.4 SO_COLLECT·§18.5 정지 판정) — 표준 라이브러리만(API·워커 공용).

설계점 = run 1개의 반영값(applied_values) + 목적·제약 지표 값. 같은 설계(정수 변수 같고 연속 변수 |Δ| ≤ 1e-9·범위)는
평균으로 합치고, 실패·값 없음 run은 "실패 설계"(다시 제안하지 않음)로 둔다. 목적 sense=max는 계산 안에서 부호를 뒤집어
최소화로 통일하고, 보고 값(best_value 등)은 원래 부호로 돌려준다.
S17(§22.4.3): 목적 1~3개(`objectives`, objective = objectives[0] 호환), 관찰 지표(값 없어도 유효), 제약 `range`(lo~hi).
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


def _key(metric: str, series: str | None) -> str:
    return metric if series is None else f"{metric}@{series}"


@dataclass(frozen=True)
class Constraint:
    metric: str
    series: str | None
    op: str  # "<=" | ">=" | "range"
    value: float | None = None
    lo: float | None = None  # range만
    hi: float | None = None

    @property
    def key(self) -> str:
        return _key(self.metric, self.series)

    def bounds(self) -> list[float]:
        return [float(v) for v in ((self.lo, self.hi) if self.op == "range" else (self.value,)) if v is not None]

    def violation(self, v: float) -> float:
        """위반량(원 단위): ≤ max(0, v − c), ≥ max(0, c − v), range max(0, lo − v) + max(0, v − hi)."""
        if self.op == "range":
            return max(0.0, float(self.lo) - v) + max(0.0, v - float(self.hi))  # type: ignore[arg-type]
        return max(0.0, v - float(self.value)) if self.op == "<=" else max(0.0, float(self.value) - v)  # type: ignore[arg-type]

    @classmethod
    def from_dict(cls, c: Mapping[str, Any]) -> Constraint:
        def f(k: str) -> float | None:
            v = c.get(k)
            return None if v is None else float(v)

        return cls(c["metric"], c.get("series"), c["op"], f("value"), f("lo"), f("hi"))


@dataclass(frozen=True)
class Objective:
    metric: str
    series: str | None
    sense: str  # "min" | "max"

    @property
    def key(self) -> str:
        return _key(self.metric, self.series)

    def sign(self) -> float:
        return -1.0 if self.sense == "max" else 1.0


@dataclass(frozen=True)
class Metric:
    """관찰 지표(값만 기록·표시)."""

    metric: str
    series: str | None = None

    @property
    def key(self) -> str:
        return _key(self.metric, self.series)


def settings_objectives(settings: Mapping[str, Any]) -> list[dict[str, Any]]:
    """저장 settings의 목적 목록(0014 이전 행은 `[objective]`)."""
    objs = settings.get("objectives")
    return list(objs) if isinstance(objs, list) and objs else [dict(settings["objective"])]


@dataclass
class Problem:
    """정규화된 최적화 문제(opt.settings에서)."""

    names: list[str]  # 템플릿 파라미터 전부(템플릿 순서)
    integer: set[str]
    bounds: dict[str, tuple[float, float]]  # lo = hi면 고정
    sense: str  # "min" | "max" — objectives[0](단일 경로 호환)
    constraints: list[Constraint] = field(default_factory=list)
    objectives: list[Objective] = field(default_factory=list)
    observe: list[Metric] = field(default_factory=list)
    weights: list[float] = field(default_factory=list)
    performances: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_settings(cls, settings: Mapping[str, Any]) -> Problem:
        b = {k: (float(v[0]), float(v[1])) for k, v in settings["bounds"].items()}
        cons = [Constraint.from_dict(c) for c in settings.get("constraints") or []]
        objs = [Objective(o["metric"], o.get("series"), o.get("sense") or "min") for o in settings_objectives(settings)]
        obs = [Metric(o["metric"], o.get("series")) for o in settings.get("observe") or []]
        w = [float(x) for x in settings.get("weights") or []] or [1.0 / len(objs)] * len(objs)
        return cls(list(settings["names"]), set(settings.get("integer") or []), b, objs[0].sense, cons, objs, obs, w,
                   dict(settings.get("performances") or {}))

    def __post_init__(self) -> None:
        if not self.objectives:
            self.objectives = [Objective("", None, self.sense)]

    @property
    def m(self) -> int:
        return len(self.objectives)

    @property
    def multi(self) -> bool:
        return len(self.objectives) >= 2

    def fixed(self) -> dict[str, float]:
        return {n: lo for n, (lo, hi) in self.bounds.items() if lo == hi}

    def span(self, name: str) -> float:
        lo, hi = self.bounds[name]
        return hi - lo

    def sign(self) -> float:
        return -1.0 if self.sense == "max" else 1.0

    def signs(self) -> list[float]:
        return [o.sign() for o in self.objectives]


@dataclass
class Point:
    """검증된 run 1개(성공 + 모든 목적·제약 값 있음이면 valid, 관찰 값은 없어도 된다)."""

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
    objectives: list[float | None] | None = None  # None이면 [objective]
    observed: dict[str, float | None] = field(default_factory=dict)
    reasons: dict[str, str] = field(default_factory=dict)  # 값 없는 지표 key → 사유
    kind: str | None = None  # 반복 종류(EXPLORE·REUSE·VERIFY·EXTRA)

    def __post_init__(self) -> None:
        if self.objectives is None:
            self.objectives = [self.objective]
        else:
            self.objective = self.objectives[0] if self.objectives else None

    @property
    def valid(self) -> bool:
        return (self.state == "SUCCEEDED" and all(v is not None for v in self.objectives or [None])
                and all(c is not None for c in self.constraints))

    @property
    def key(self) -> str:
        return f"{self.iter_no}:{self.doe_no}"


@dataclass
class Design:
    """같은 설계를 합친 학습 점(평균)."""

    values: dict[str, float]
    objective: float
    constraints: list[float]
    sources: list[Point]
    objectives: list[float] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.objectives:
            self.objectives = [self.objective]


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
        objs = [float(v) for v in p.objectives]  # type: ignore[arg-type,union-attr]
        if hit is None:
            designs.append(Design(dict(p.values), objs[0], [float(c) for c in p.constraints], [p], objs))  # type: ignore[arg-type]
            continue
        hit.sources.append(p)
        k = len(hit.sources)
        hit.objectives = [a + (v - a) / k for a, v in zip(hit.objectives, objs)]
        hit.objective = hit.objectives[0]
        hit.constraints = [c + (float(v) - c) / k for c, v in zip(hit.constraints, p.constraints)]  # type: ignore[arg-type]
    return designs, failed


def violation(values: Sequence[float | None], constraints: Sequence[Constraint]) -> float:
    """제약 위반량 합(원 단위, 값 없음 = 무한)."""
    tot = 0.0
    for v, c in zip(values, constraints):
        if v is None:
            return math.inf
        tot += c.violation(v)
    return tot


def is_feasible(values: Sequence[float | None], constraints: Sequence[Constraint]) -> bool:
    lim = FEAS_TOL * max([1.0, *[abs(b) for c in constraints for b in c.bounds()]])
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


# ---- 다목적(§22.5.1·§22.5.6·§22.6) — 표준 라이브러리(API·워커 공용) ----------------------------------------


def signed_objectives(d: Design, problem: Problem) -> list[float]:
    """부호 통일(최소화) 목적 값."""
    return [s * v for s, v in zip(problem.signs(), d.objectives)]


def make_hv_frame(designs: Sequence[Design], problem: Problem, ref_offset: float) -> dict[str, Any] | None:
    """HV 정규화 틀(§22.5.1): 기준 집합 = 제약 만족 설계가 2개 이상이면 그것들, 아니면 전부. 설계가 없으면 None."""
    from . import pareto

    if not designs:
        return None
    feas = [d for d in designs if is_feasible(d.constraints, problem.constraints)]
    ref = feas if len(feas) >= 2 else list(designs)
    ideal, nadir = pareto.make_frame([signed_objectives(d, problem) for d in ref])
    return {"ideal": ideal, "nadir": nadir, "ref_offset": float(ref_offset), "signs": problem.signs()}


def front_designs(designs: Sequence[Design], problem: Problem) -> list[Design]:
    """검증된 파레토 해: 제약 만족 설계(같은 설계 평균)의 비지배 집합(입력 순서 유지)."""
    from . import pareto

    feas = [d for d in designs if is_feasible(d.constraints, problem.constraints)]
    return [feas[i] for i in pareto.nondominated([signed_objectives(d, problem) for d in feas])]


def hv_value(designs: Sequence[Design], problem: Problem, frame: Mapping[str, Any]) -> tuple[float, int]:
    """(HV, 전선 크기) — 고정 틀로 정규화한 검증 전선의 HV(기준점 1 + ref_offset)."""
    from . import pareto

    front = front_designs(designs, problem)
    pts = [pareto.normalize(signed_objectives(d, problem), frame["ideal"], frame["nadir"]) for d in front]
    ref = [1.0 + float(frame.get("ref_offset", 0.1))] * problem.m
    return pareto.hypervolume(pts, ref) if pts else 0.0, len(front)


def recommend_design(front: Sequence[Design], problem: Problem, weights: Sequence[float] | None
                     ) -> tuple[int, list[float]]:
    """§22.6 가중 추천(front는 (iter_no, doe_no) 순). (인덱스, 점수)."""
    from . import pareto

    return pareto.recommend([d.objectives for d in front], problem.signs(), weights)


def hv_improvement_rel(prev: float | None, cur: float | None) -> float | None:
    """(HV_t − HV_{t−1})/HV_{t−1}, HV_{t−1} ≤ 0·없음이면 None(계속)."""
    if prev is None or cur is None or prev <= 0:
        return None
    return (cur - prev) / prev


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
    """지표 id → 표시 이름: `resp:CornerStress_MAX` → `CornerStress_MAX`, `curve:max` → `커브 최대값(계열)`, `perf:X` → `X`."""
    kind, _, key = metric.partition(":")
    if kind == "curve":
        base = CURVE_LABELS.get(key, metric)
        return f"{base}({series})" if series else base
    return key or metric


def _num(v: Any) -> str:
    f = finite(v)
    return "" if f is None else repr(f)


def _obj_cols(problem: Problem) -> list[str]:
    return ["objective"] if not problem.multi else [f"objective_{i}" for i in range(1, problem.m + 1)]


def _obs_cols(problem: Problem) -> list[str]:
    return [f"obs:{metric_label(o.metric, o.series)}" for o in problem.observe]


def _with_reason(problem: Problem) -> bool:
    return problem.multi or bool(problem.observe)


def dataset_csv(points: Sequence[Point], problem: Problem, *, predicted: Mapping[tuple[int, int], float] | None = None,
                with_feasible: bool = False, bom: bool = False, crlf: bool = False) -> str:
    """iter·batch·doe_no·run_key·<변수>·objective(다목적 objective_1..m)·<제약>·(obs:<관찰>·reason)·(predicted·feasible)·state.
    단일 목적·관찰 없음은 S13 열 그대로(§22.4.3)."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n" if crlf else "\n")
    cons = [c.key for c in problem.constraints]
    head = ["iter", "batch", "doe_no", "run_key", *problem.names, *_obj_cols(problem), *cons, *_obs_cols(problem)]
    if _with_reason(problem):
        head.append("reason")
    if with_feasible:
        head += ["predicted", "feasible"]
    w.writerow([*head, "state"])
    for p in points:
        objs = list(p.objectives or [p.objective])[: problem.m]
        objs += [None] * (problem.m - len(objs))
        row: list[Any] = [p.iter_no, p.batch_label, p.doe_no, p.run_key, *[_num(p.values.get(n)) for n in problem.names],
                          *[_num(v) for v in objs], *[_num(v) for v in p.constraints],
                          *[_num(p.observed.get(o.key)) for o in problem.observe]]
        if _with_reason(problem):
            row.append(next(iter(p.reasons.values()), ""))
        if with_feasible:
            pv = (predicted or {}).get((p.iter_no, p.doe_no))
            feas = "" if not p.valid else ("true" if is_feasible(p.constraints, problem.constraints) else "false")
            row += [_num(pv), feas]
        w.writerow([*row, p.state])
    text = buf.getvalue()
    return ("\ufeff" + text) if bom else text


def read_dataset_csv(text: str, problem: Problem) -> list[Point]:
    """dataset_csv 결과를 다시 Point로(워커 step 사이 전달)."""
    rows = list(csv.reader(io.StringIO(text.lstrip("\ufeff"))))
    head = rows[0]
    idx = {h: i for i, h in enumerate(head)}
    obj_cols = _obj_cols(problem)
    obs_cols = _obs_cols(problem)
    out = []
    for r in rows[1:]:
        if not r:
            continue

        def f(name: str) -> float | None:
            s = r[idx[name]] if name in idx else ""
            return float(s) if s != "" else None

        vals = {n: v for n in problem.names if (v := f(n)) is not None}
        objs = [f(c) for c in obj_cols]
        reason = r[idx["reason"]] if "reason" in idx else ""
        out.append(Point(int(r[idx["iter"]]), r[idx["batch"]], int(r[idx["doe_no"]]), r[idx["run_key"]], vals,
                         objs[0], [f(c.key) for c in problem.constraints], r[idx["state"]], objectives=objs,
                         observed={o.key: f(col) for o, col in zip(problem.observe, obs_cols)},
                         reasons={"": reason} if reason else {}))
    return out
