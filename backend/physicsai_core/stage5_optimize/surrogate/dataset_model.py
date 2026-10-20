"""⑤ 대리모델 최적화 자료 모양: 상수·제약·목적·지표·문제(Problem)·점(Point)·설계(Design)와 같은 설계·병합·가능해·최선 점 — dataset에서 재노출."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .dataset_mb import cat_spec, cover_spec

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
    cat_spec: dict[str, Any] | None = None  # opt-native §7 범주 baseline(위상 변형) — encoding spec
    cover_spec: dict[str, Any] | None = None  # opt-native §7 범위 분할 — NO_COVER 판정 spec

    @classmethod
    def from_settings(cls, settings: Mapping[str, Any]) -> Problem:
        b = {k: (float(v[0]), float(v[1])) for k, v in settings["bounds"].items()}
        cons = [Constraint.from_dict(c) for c in settings.get("constraints") or []]
        # ON-C4: 방향·가중치는 저장된 사용자 값만 쓴다(기본 min·균등 가중치로 채우지 않음 — 실행 전 criteria가 막는다)
        objs = [Objective(o["metric"], o.get("series"), o.get("sense")) for o in settings_objectives(settings)]
        obs = [Metric(o["metric"], o.get("series")) for o in settings.get("observe") or []]
        w = [float(x) for x in settings.get("weights") or []] or ([1.0] if len(objs) == 1 else [])
        return cls(list(settings["names"]), set(settings.get("integer") or []), b, objs[0].sense, cons, objs, obs, w,
                   dict(settings.get("performances") or {}), cat_spec(settings), cover_spec(settings))

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
