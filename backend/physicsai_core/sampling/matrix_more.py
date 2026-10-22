"""DM-C3 새 표본 방식 halton·random 조합 행(doe-methods.md §4.1) — matrix에서 재노출. 공통 규칙(활성 변수·고정 변수·코드값→값)은
`matrix_designs`(S15 §20.5.1)와 같다. 문제는 예외 대신 `problems`, 모양 오류는 `BatchShapeError`."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from . import designs, qmc
from .matrix_designs import _Design, _int_arg, _RawRows, _rows_from
from .matrix_rows import BatchShapeError, _problem

HALTON_MAX_SEED = 4_294_967_295  # numpy default_rng 시드 범위(Sobol과 같음)


def _count_seed(source: Mapping[str, Any], max_runs: int, problems: list[dict[str, Any]], seed_max: int | None) -> tuple[int, int]:
    count = _int_arg(source, "count")
    if count is None:
        raise BatchShapeError("source.count는 정수여야 합니다")
    seed = _int_arg(source, "seed", 1)
    seed = 1 if seed is None else seed
    if seed < 0 or (seed_max is not None and seed > seed_max):
        raise BatchShapeError("source.seed는 0 이상의 정수입니다" if seed_max is None else f"source.seed는 0~{seed_max}입니다")
    if count < 2:
        _problem(problems, "TOO_FEW_ROWS", "조합 수는 2개 이상이어야 합니다")
    elif count > max_runs:
        _problem(problems, "TOO_MANY_ROWS", f"조합 수는 최대 {max_runs}개입니다")
    return count, seed


def _halton(source: Mapping[str, Any], dsn: _Design, max_runs: int, problems: list[dict[str, Any]]
            ) -> tuple[_RawRows, dict[str, Any], list[dict[str, str]]]:
    count, seed = _count_seed(source, max_runs, problems, HALTON_MAX_SEED)
    meta: dict[str, Any] = {"count": count, "seed": seed, "scramble": True, **dsn.base_meta()}
    if problems:
        return [], meta, []
    try:
        u, gen = qmc.halton_unit(dsn.k, count, seed)
    except qmc.GeneratorUnavailable as exc:
        _problem(problems, "GENERATOR_UNAVAILABLE", str(exc))
        return [], meta, []
    meta["generator"] = gen
    meta["quality"] = designs.quality(u)
    return _rows_from(dsn, u, designs.unit_to_value), meta, []


def _random(source: Mapping[str, Any], dsn: _Design, max_runs: int, problems: list[dict[str, Any]]
            ) -> tuple[_RawRows, dict[str, Any], list[dict[str, str]]]:
    count, seed = _count_seed(source, max_runs, problems, None)
    meta: dict[str, Any] = {"count": count, "seed": seed, **dsn.base_meta()}
    if problems:
        return [], meta, []
    u = designs.random_unit(count, dsn.k, seed)
    meta["quality"] = designs.quality(u)
    return _rows_from(dsn, u, designs.unit_to_value), meta, []
