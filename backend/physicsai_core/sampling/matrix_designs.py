"""S15 설계 변수 규칙(§20.5.1)과 lhs_opt·fullfact·fracfact·pb·bbd·ccd 조합 행(D3-63) — matrix에서 재노출."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ..stage4_predict import nearest
from . import designs, fractional
from .matrix_rows import BatchShapeError, _finite, _problem, run_key_for

# ---- S15 새 kind 7개(phase3 §20.5, D3-63) -----------------------------------------------------------------

_RawRows = list[tuple[int, str, dict[str, float]]]
LEVEL_MIN, LEVEL_MAX = 2, 10


@dataclass
class _Design:
    """설계 변수: 템플릿 순서의 범위·활성(lo < hi)·고정(lo = hi) 변수."""

    names: list[str]
    bounds: dict[str, tuple[float, float]]
    active: list[str]
    fixed: list[str]

    @property
    def k(self) -> int:
        return len(self.active)

    def base_meta(self) -> dict[str, Any]:
        return {"ranges": {n: [self.bounds[n][0], self.bounds[n][1]] for n in self.names if n in self.bounds},
                "active": list(self.active), "fixed": list(self.fixed)}


def _int_arg(source: Mapping[str, Any], key: str, default: Any = None) -> Any:
    v = source.get(key, default)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        raise BatchShapeError(f"source.{key}는 정수여야 합니다")
    return v


def _design_vars(ranges: Any, parameters: Sequence[Mapping[str, Any]], problems: list[dict[str, Any]]) -> _Design:
    """§20.5.1 변수 규칙: ranges[name] 없으면 세트 min·max. 범위 검증은 RANGE_INVALID(유한·lo < hi). 세트 min = max는 고정."""
    if ranges is None:
        ranges = {}
    if not isinstance(ranges, Mapping):
        raise BatchShapeError("source.ranges는 {이름: [최소, 최대]} 형식이어야 합니다")
    names = [str(p["name"]) for p in parameters]
    for key in ranges:
        if key not in names:
            _problem(problems, "RANGE_INVALID", f"'{key}'는 템플릿 파라미터가 아닙니다")
    bounds: dict[str, tuple[float, float]] = {}
    active: list[str] = []
    fixed: list[str] = []
    for p in parameters:
        name = str(p["name"])
        if name in ranges:
            r = ranges[name]
            lo = _finite(r[0]) if isinstance(r, (list, tuple)) and len(r) == 2 else None
            hi = _finite(r[1]) if isinstance(r, (list, tuple)) and len(r) == 2 else None
            if lo is None or hi is None or not lo < hi:
                _problem(problems, "RANGE_INVALID", f"'{name}' 범위는 유한한 [최소, 최대]이고 최소 < 최대여야 합니다")
                continue
        else:
            lo, hi = _finite(p.get("min")), _finite(p.get("max"))
            if lo is None or hi is None or lo > hi:
                _problem(problems, "RANGE_INVALID", f"'{name}' 템플릿 범위가 올바르지 않습니다")
                continue
        bounds[name] = (lo, hi)
        (active if lo < hi else fixed).append(name)
    return _Design(names, bounds, active, fixed)


def _fmt(v: float) -> str:
    return f"{v:g}"


def _rows_from(dsn: _Design, grid: Sequence[Sequence[float]], to_value: Any) -> _RawRows:
    """활성 변수 순서의 격자(코드값·단위 값) → 템플릿 순서 값 행. 고정 변수는 고정값."""
    out: _RawRows = []
    for i, g in enumerate(grid, start=1):
        col = {n: g[j] for j, n in enumerate(dsn.active)}
        vals: dict[str, float] = {}
        for n in dsn.names:
            lo, hi = dsn.bounds[n]
            vals[n] = to_value(col[n], lo, hi) if n in col else lo
        out.append((i, run_key_for(i), vals))
    return out


def _too_many(problems: list[dict[str, Any]], label: str, runs: int, max_runs: int, tail: str = "") -> bool:
    if runs > max_runs:
        _problem(problems, "TOO_MANY_ROWS", f"{label} run 수 {runs}개가 상한 {max_runs}개를 넘습니다{tail}")
        return True
    return False


def _unsupported(problems: list[dict[str, Any]], message: str) -> None:
    _problem(problems, "DESIGN_UNSUPPORTED", message)


def _lhs_opt(source: Mapping[str, Any], dsn: _Design, max_runs: int, problems: list[dict[str, Any]]
             ) -> tuple[_RawRows, dict[str, Any], list[dict[str, str]]]:
    criterion = source.get("criterion") or "maximin"
    if criterion not in ("maximin", "corr"):
        raise BatchShapeError("source.criterion은 maximin | corr 중 하나입니다")
    seed = _int_arg(source, "seed", 1)
    seed = 1 if seed is None else seed
    count = _int_arg(source, "count")
    if count is None:
        raise BatchShapeError("source.count는 정수여야 합니다")
    if count < 2:
        _problem(problems, "TOO_FEW_ROWS", "조합 수는 2개 이상이어야 합니다")
    elif count > max_runs:
        _problem(problems, "TOO_MANY_ROWS", f"조합 수는 최대 {max_runs}개입니다")
    meta = {"count": count, "seed": seed, "criterion": criterion, "candidates": designs.LHS_OPT_CANDIDATES,
            "iterations": designs.LHS_OPT_ITERATIONS, **dsn.base_meta()}
    if problems:
        return [], meta, []
    u, _info = designs.lhs_opt_unit(count, dsn.k, seed, criterion)
    meta["quality"] = designs.quality(u)
    return _rows_from(dsn, u, designs.unit_to_value), meta, []


def _level_values(name: str, lo: float, hi: float, n_levels: int, is_int: bool, rounding: str,
                  problems: list[dict[str, Any]]) -> list[float] | None:
    vals = designs.fullfact_levels(lo, hi, n_levels)
    if not is_int:
        return vals
    ints = [float(nearest.apply_rounding(v, rounding)) for v in vals]
    avail = max(0, math.floor(hi) - math.ceil(lo) + 1)
    if len(set(ints)) != n_levels or any(v < lo or v > hi for v in ints):
        _problem(problems, "LEVELS_INVALID", f"'{name}'은 정수 변수라 {_fmt(lo)}~{_fmt(hi)}에서 최대 {avail}수준입니다")
        return None
    return ints


def _fullfact(source: Mapping[str, Any], dsn: _Design, tpl_params: Sequence[Mapping[str, Any]], rounding: str,
              max_runs: int, problems: list[dict[str, Any]]) -> tuple[_RawRows, dict[str, Any], list[dict[str, str]]]:
    levels_in = source.get("levels")
    if levels_in is None:
        levels_in = {}
    if not isinstance(levels_in, Mapping):
        raise BatchShapeError("source.levels는 {이름: 수준 수} 형식이어야 합니다")
    for v in levels_in.values():
        if isinstance(v, bool) or not isinstance(v, int):
            raise BatchShapeError("source.levels 값은 정수여야 합니다")
    ints = nearest.integer_vars(list(tpl_params))  # type: ignore[arg-type]
    levels: dict[str, int] = {}
    values: dict[str, list[float]] = {}
    for key in levels_in:
        if key not in dsn.active and key not in dsn.fixed:  # 고정 변수는 입력을 무시한다(L = 1)
            _problem(problems, "LEVELS_INVALID", f"'{key}'는 범위가 있는 변수가 아닙니다")
    for n in dsn.active:
        n_levels = int(levels_in.get(n, 2))
        levels[n] = n_levels
        if not LEVEL_MIN <= n_levels <= LEVEL_MAX:
            _problem(problems, "LEVELS_INVALID", f"'{n}' 수준은 {LEVEL_MIN}~{LEVEL_MAX}입니다")
            continue
        lv = _level_values(n, *dsn.bounds[n], n_levels, n in ints, rounding, problems)
        if lv is not None:
            values[n] = lv
    meta = {"levels": levels, **dsn.base_meta()}
    if problems:
        return [], meta, []
    total = 1
    for n_levels in levels.values():
        total *= n_levels
    if _too_many(problems, "전체 요인", total, max_runs, " — 수준 수를 줄이세요"):
        return [], meta, []
    out: _RawRows = []
    for i, idx in enumerate(designs.fullfact_index_rows([levels[n] for n in dsn.active]), start=1):
        col = {n: values[n][idx[j]] for j, n in enumerate(dsn.active)}
        out.append((i, run_key_for(i), {n: col[n] if n in col else dsn.bounds[n][0] for n in dsn.names}))
    return out, meta, []


def _fracfact(source: Mapping[str, Any], dsn: _Design, max_runs: int, problems: list[dict[str, Any]]
              ) -> tuple[_RawRows, dict[str, Any], list[dict[str, str]]]:
    res = _int_arg(source, "resolution", 5)
    res = 5 if res is None else res
    if res not in (4, 5):
        raise BatchShapeError("source.resolution은 4 | 5 중 하나입니다")
    meta: dict[str, Any] = {"resolution": res, **dsn.base_meta()}
    if not fractional.MIN_K <= dsn.k <= fractional.MAX_K:
        _unsupported(problems, "부분 요인은 범위가 있는 변수 2~11개에서만 만들 수 있습니다")
        return [], meta, []
    r, gens, full = fractional.fracfact_plan(dsn.k, res)
    if _too_many(problems, "부분 요인", 1 << r, max_runs):
        return [], meta, []
    letters = fractional.LETTERS[:dsn.k]
    meta.update({"letters": {letters[j]: n for j, n in enumerate(dsn.active)}, "generators": list(gens),
                 "runs": 1 << r, "full": full})
    notes = []
    if full:
        notes.append({"code": "FULL_FACTORIAL_USED",
                      "message": f"변수 {dsn.k}개에서는 부분 요인 대신 전체 2수준 요인(2^{dsn.k})을 씁니다"})
    codes = fractional.two_level_matrix(dsn.k, r, gens)
    return _rows_from(dsn, codes, designs.code_to_value), meta, notes


def _pb(dsn: _Design, max_runs: int, problems: list[dict[str, Any]]) -> tuple[_RawRows, dict[str, Any], list[dict[str, str]]]:
    meta: dict[str, Any] = dict(dsn.base_meta())
    if dsn.k < 2:
        _unsupported(problems, "Plackett–Burman은 범위가 있는 변수가 2개 이상이어야 합니다")
        return [], meta, []
    n_runs = fractional.pb_size(dsn.k)
    if _too_many(problems, "Plackett–Burman", n_runs, max_runs):
        return [], meta, []
    codes, construction = fractional.pb_matrix(n_runs, dsn.k)
    meta = {"runs": n_runs, "construction": construction, **dsn.base_meta()}
    return _rows_from(dsn, codes, designs.code_to_value), meta, []


def _bbd(dsn: _Design, max_runs: int, problems: list[dict[str, Any]]) -> tuple[_RawRows, dict[str, Any], list[dict[str, str]]]:
    meta: dict[str, Any] = {"center": 1, "pairwise": dsn.k >= 6, **dsn.base_meta()}
    if dsn.k < 3:
        _unsupported(problems, "Box–Behnken은 범위가 있는 변수가 3개 이상이어야 합니다")
        return [], meta, []
    if _too_many(problems, "Box–Behnken", 2 * dsn.k * (dsn.k - 1) + 1, max_runs):
        return [], meta, []
    notes = []
    if dsn.k >= 6:
        notes.append({"code": "BBD_PAIRWISE",
                      "message": "변수 6개 이상은 쌍 방식 Box–Behnken입니다(표준 블록 설계보다 run이 많습니다)"})
    return _rows_from(dsn, designs.bbd_codes(dsn.k), designs.code_to_value), meta, notes


def _ccd(source: Mapping[str, Any], dsn: _Design, max_runs: int, problems: list[dict[str, Any]]
         ) -> tuple[_RawRows, dict[str, Any], list[dict[str, str]]]:
    kind = source.get("alpha") or "face"
    if kind not in ("face", "inscribed"):
        raise BatchShapeError("source.alpha는 face | inscribed 중 하나입니다")
    meta: dict[str, Any] = {"alpha_kind": kind, "center": 1, **dsn.base_meta()}
    if not 2 <= dsn.k <= 11:
        _unsupported(problems, "중심 합성은 범위가 있는 변수 2~11개에서만 만들 수 있습니다")
        return [], meta, []
    if dsn.k <= 4:
        r, gens, factorial = dsn.k, (), "full"
    else:
        r, gens, _full = fractional.fracfact_plan(dsn.k, 5)
        factorial = "fracV"
    if _too_many(problems, "중심 합성", (1 << r) + 2 * dsn.k + 1, max_runs):
        return [], meta, []
    fac = fractional.two_level_matrix(dsn.k, r, gens)
    meta.update({"alpha": designs.ccd_alpha(kind, 1 << r), "factorial": factorial, "generators": list(gens)})
    return _rows_from(dsn, designs.ccd_codes(dsn.k, kind, fac), designs.code_to_value), meta, []
