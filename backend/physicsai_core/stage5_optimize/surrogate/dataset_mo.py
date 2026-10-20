"""⑤ 다목적(§22.5.1·§22.5.6·§22.6) 부호 통일·HV 틀·전선·추천·개선률 — 표준 라이브러리(API·워커 공용), dataset에서 재노출."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .dataset_model import Design, Problem, is_feasible

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
