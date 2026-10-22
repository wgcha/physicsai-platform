"""다중 baseline 층화의 층 안 생성기(doe-methods.md DM-C4): `lhs`·`lhs_opt`·`halton`·`random`.

`geometry.baselines_table.stratified_lhs`가 baseline(층)마다 `gen(names, bounds, count, seed + 층 번호)`를 부른다. 함수 모양은
`matrix_basic.lhs_values`와 같고 `lhs`는 그 함수 자체라 결과가 바뀌지 않는다(DM-C8). 범위가 한 점(lo = hi)인 변수는 설계에서 빼고
고정값을 쓴다(단일 baseline 규칙 §20.5.1과 같음). halton은 scipy가 없으면 `qmc.GeneratorUnavailable`을 그대로 올린다.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from . import designs, qmc
from .matrix_basic import lhs_values

LayerGen = Callable[[Sequence[str], Mapping[str, tuple[float, float]], int, int], list[dict[str, float]]]
LAYER_KINDS = ("lhs_opt", "halton", "lhs", "random")


def _unit(kind: str, count: int, k: int, seed: int, criterion: str) -> list[list[float]]:
    if kind == "halton":
        return qmc.halton_unit(k, count, seed)[0]
    if kind == "random":
        return designs.random_unit(count, k, seed)
    return designs.lhs_opt_unit(count, k, seed, criterion)[0]


def layer_generator(kind: str, criterion: str = "maximin") -> LayerGen:
    """층 안 생성기. `lhs`는 기존 `lhs_values` 그대로. 모르는 kind는 ValueError."""
    if kind == "lhs":
        return lhs_values
    if kind not in LAYER_KINDS:
        raise ValueError(f"층 안 생성기를 알 수 없습니다: {kind}")

    def gen(names: Sequence[str], bounds: Mapping[str, tuple[float, float]], count: int, seed: int) -> list[dict[str, float]]:
        active = [n for n in names if bounds[n][0] < bounds[n][1]]
        if count < 2 and kind == "lhs_opt":  # 점 1개 층: 교환 탐색 대상이 없어 층화 LHS(= 무작위 1점)와 같다
            return lhs_values(names, bounds, count, seed)
        u = _unit(kind, count, len(active), seed, criterion) if active else [[] for _ in range(count)]
        out: list[dict[str, float]] = []
        for row in u:
            col = dict(zip(active, row))
            out.append({n: (designs.unit_to_value(col[n], *bounds[n]) if n in col else bounds[n][0]) for n in names})
        return out

    return gen
