"""④ 일괄 예측(DOE) 조합 계산(phase3 §14.5 S9) — 미리보기·작업 생성·워커가 같은 결과를 쓴다(순수 함수, I/O 없음).

source.kind:
- `lhs`: `count`(2~max_runs)·`seed`(정수, 기본 1)·`ranges{name:[lo,hi]}`(생략 = 세트 min·max). `random.Random(seed)`로
  파라미터마다(세트 순서) ① 층 순열 `perm = shuffle(range(n))` ② run i마다 `u = random()` →
  값 = `lo + (perm[i] + u)/n·(hi−lo)`. 층마다 정확히 1개. 학습 범위 밖 허용(`out_of_range`).
- `table`: 붙여넣기·CSV 텍스트. 구분자 탭(첫 줄에 탭이 있으면)/쉼표 자동, BOM 허용, 첫 줄 헤더 = 파라미터 이름 전부(순서 무관,
  선택 열 `doe`는 무시), 데이터 행 1~max_runs, doe_no = 행 순서 1..
- `train_doe`: ① DOE `samples.csv` 행(`doe_samples.read_samples_csv` 결과). 파라미터 이름 집합 = 템플릿 이름 집합,
  doe_no = run 번호(`run__00014` → 14), run_key = ① run 이름 그대로.

S15(phase3 §20, D3-63) 새 kind 7개 — 순서·알고리즘은 `physicsai_core/sampling/`(결정적):
- `lhs_opt`(count·seed·ranges·criterion maximin|corr), `sobol`(count=2^m·seed·ranges·continue_from), `fullfact`(levels·ranges),
  `fracfact`(resolution 4|5·ranges), `pb`(ranges), `bbd`(ranges), `ccd`(alpha face|inscribed·ranges).
  고정 변수(세트 min = max)는 설계에서 빼고 고정값을 쓴다. 막지 않는 안내는 `BatchMatrix.notes`({code,message}).

반영값(`applied_values`) = `predict.integer_rounding`으로 tpl 정수 형식 파라미터만 반올림(`nearest.applied_values`).
문제는 예외 대신 `BatchMatrix.problems`({code,message,row?})로 모은다 — code ∈ PROBLEM_CODES.
모양 오류(kind 모름·필드 형식)는 `BatchShapeError`(API 422 INVALID_PARAMS).
"""

from __future__ import annotations

import csv
import io
import math
import random
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from ..sampling import designs, fractional, qmc
from ..sampling.registry import SOURCE_KINDS  # API kind → DB source_kind (10개)
from . import nearest

PROBLEM_CODES = (
    "TABLE_HEADER", "TABLE_VALUE", "TEXT_TOO_LARGE", "TOO_MANY_ROWS", "TOO_FEW_ROWS", "RANGE_INVALID", "DOE_PARAM_MISMATCH",
    "COUNT_NOT_POW2", "CONTINUE_INVALID", "SEQUENCE_MISMATCH", "LEVELS_INVALID", "DESIGN_UNSUPPORTED", "GENERATOR_UNAVAILABLE",
)
NOTE_CODES = ("FIXED_EXCLUDED", "FULL_FACTORIAL_USED", "BBD_PAIRWISE", "DUPLICATE_ROWS", "SEQUENCE_CONTINUED", "INFLUENCE_TOO_FEW")
NEW_KINDS = ("lhs_opt", "sobol", "fullfact", "fracfact", "pb", "bbd", "ccd")
MAX_PROBLEMS = 100  # 행 오류는 이 개수까지만 모은다(화면 회색 줄)
DOE_COLUMN = "doe"  # 표의 선택 열(무시)
RUN_KEY_RE = re.compile(r"run__([0-9]+)")  # fullmatch 전용, ASCII 숫자만(D3-53)


class BatchShapeError(ValueError):
    """source 모양 오류(kind·필드 형식). API는 422 INVALID_PARAMS로 바꾼다."""


@dataclass(frozen=True)
class BatchRow:
    """조합 1행 — predict_batch_runs 행·미리보기 행과 같은 모양."""

    doe_no: int
    run_key: str
    values: dict[str, float]
    applied_values: dict[str, float]
    out_of_range: list[str]

    def as_dict(self) -> dict[str, Any]:
        """미리보기 응답·batch.json 행."""
        return {"doe_no": self.doe_no, "run_key": self.run_key, "values": dict(self.values),
                "applied_values": dict(self.applied_values), "out_of_range": list(self.out_of_range)}


@dataclass
class BatchMatrix:
    """조합 계산 결과. problems가 있으면 작업 생성은 422 BATCH_SOURCE_INVALID."""

    source_kind: str  # LHS | LHS_OPT | SOBOL | FULLFACT | FRACFACT | PB | BBD | CCD | TABLE | TRAIN_DOE
    rows: list[BatchRow] = field(default_factory=list)
    problems: list[dict[str, Any]] = field(default_factory=list)
    source_meta: dict[str, Any] = field(default_factory=dict)
    notes: list[dict[str, str]] = field(default_factory=list)  # 막지 않는 안내({code, message}, §20.9)

    @property
    def ok(self) -> bool:
        """문제 없음 + 행 1개 이상."""
        return not self.problems and bool(self.rows)


def run_key_for(doe_no: int) -> str:
    """doe_no → run 폴더 이름 `run__00001`(① hstbatch와 같은 5자리)."""
    return f"run__{int(doe_no):05d}"


def doe_no_of(run_key: str) -> int | None:
    """`run__00014` → 14. 형식이 다르면 None."""
    m = RUN_KEY_RE.fullmatch(run_key) if isinstance(run_key, str) else None
    return int(m.group(1)) if m and int(m.group(1)) >= 1 else None


def batch_label(batch_no: int) -> str:
    """batch_no → 표시·폴더 이름 `B-003`."""
    return f"B-{int(batch_no):03d}"


def batch_dir_rel(dir_name: str, batch_no: int) -> str:
    """Study 기준 배치 폴더 `04_batch/B-003`(predict_batch.dir_name)."""
    return f"{dir_name}/{batch_label(batch_no)}"


def input_rel_for(run_key: str, input_kind: str, simlab_mesh_name: str) -> str:
    """배치 폴더 기준 하위 예측 입력: assembly `run__N/m_3`, mesh_only `run__N/m_1/<simlab_mesh_name>`."""
    return f"{run_key}/m_3" if input_kind == "assembly" else f"{run_key}/m_1/{simlab_mesh_name}"


def _problem(out: list[dict[str, Any]], code: str, message: str, row: int | None = None) -> None:
    if len(out) >= MAX_PROBLEMS:
        return
    p: dict[str, Any] = {"code": code, "message": message}
    if row is not None:
        p["row"] = row
    out.append(p)


def _finite(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        f = float(v)
    elif isinstance(v, str):
        try:
            f = float(v.strip())
        except ValueError:
            return None
    else:
        return None
    return f if math.isfinite(f) else None


def _make_row(doe_no: int, run_key: str, values: dict[str, float], parameters: Sequence[Mapping[str, Any]],
              tpl_params: Sequence[Mapping[str, Any]], rounding: str) -> BatchRow:
    applied = nearest.applied_values(list(tpl_params), values, rounding)  # type: ignore[arg-type]
    oor = [o["name"] for o in nearest.out_of_range(list(parameters), values)]  # type: ignore[arg-type]
    return BatchRow(doe_no, run_key, dict(values), applied, oor)


# ---- LHS ---------------------------------------------------------------------------------------


def lhs_values(names: Sequence[str], bounds: Mapping[str, tuple[float, float]], count: int, seed: int) -> list[dict[str, float]]:
    """층화 LHS 값 count개(파라미터 순서 = names). 같은 (names, bounds, count, seed)면 항상 같은 값."""
    rng = random.Random(seed)
    cols: dict[str, list[float]] = {}
    for name in names:
        lo, hi = bounds[name]
        perm = list(range(count))
        rng.shuffle(perm)
        cols[name] = [lo + (perm[i] + rng.random()) / count * (hi - lo) for i in range(count)]
    return [{n: cols[n][i] for n in names} for i in range(count)]


def _lhs(source: Mapping[str, Any], parameters: Sequence[Mapping[str, Any]], max_runs: int,
         problems: list[dict[str, Any]]) -> tuple[list[tuple[int, str, dict[str, float]]], dict[str, Any]]:
    count, seed, ranges = source.get("count"), source.get("seed", 1), source.get("ranges") or {}
    if isinstance(count, bool) or not isinstance(count, int):
        raise BatchShapeError("source.count는 정수여야 합니다")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise BatchShapeError("source.seed는 정수여야 합니다")
    if not isinstance(ranges, Mapping):
        raise BatchShapeError("source.ranges는 {이름: [최소, 최대]} 형식이어야 합니다")
    if count < 2:
        _problem(problems, "TOO_FEW_ROWS", "조합 수는 2개 이상이어야 합니다")
    elif count > max_runs:
        _problem(problems, "TOO_MANY_ROWS", f"조합 수는 최대 {max_runs}개입니다")
    names = [str(p["name"]) for p in parameters]
    for k in ranges:
        if k not in names:
            _problem(problems, "RANGE_INVALID", f"'{k}'는 템플릿 파라미터가 아닙니다")
    bounds: dict[str, tuple[float, float]] = {}
    for p in parameters:
        name = str(p["name"])
        if name in ranges:
            r = ranges[name]
            lo = _finite(r[0]) if isinstance(r, (list, tuple)) and len(r) == 2 else None
            hi = _finite(r[1]) if isinstance(r, (list, tuple)) and len(r) == 2 else None
            if lo is None or hi is None or not lo < hi:
                _problem(problems, "RANGE_INVALID", f"'{name}' 범위는 유한한 [최소, 최대]이고 최소 < 최대여야 합니다")
                continue
            bounds[name] = (lo, hi)
        else:
            bounds[name] = (float(p["min"]), float(p["max"]))  # 세트 min = max면 고정값
    meta = {"count": count, "seed": seed, "ranges": {n: [b[0], b[1]] for n, b in bounds.items()}}
    if problems:
        return [], meta
    rows = [(i, run_key_for(i), v) for i, v in enumerate(lhs_values(names, bounds, count, seed), start=1)]
    return rows, meta


# ---- 표(붙여넣기·CSV) -----------------------------------------------------------------------------


def _table(source: Mapping[str, Any], names: Sequence[str], max_runs: int, max_bytes: int,
           problems: list[dict[str, Any]]) -> tuple[list[tuple[int, str, dict[str, float]]], dict[str, Any]]:
    text = source.get("text")
    if not isinstance(text, str):
        raise BatchShapeError("source.text는 문자열이어야 합니다")
    if len(text.encode("utf-8")) > max_bytes:
        _problem(problems, "TEXT_TOO_LARGE", f"표 내용이 {max_bytes} 바이트를 넘습니다")
        return [], {"row_count": 0}
    text = text.lstrip("﻿")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        _problem(problems, "TABLE_HEADER", "첫 줄에 파라미터 이름 헤더가 필요합니다")
        return [], {"row_count": 0}
    delim = "\t" if "\t" in lines[0] else ","
    parsed = list(csv.reader(io.StringIO("\n".join(lines)), delimiter=delim))
    header = [h.strip() for h in parsed[0]]
    want = set(names)
    seen: set[str] = set()
    cols: list[str | None] = []
    for h in header:
        if h.casefold() == DOE_COLUMN:
            cols.append(None)
            continue
        if h not in want:
            _problem(problems, "TABLE_HEADER", f"'{h}'는 템플릿 파라미터가 아닙니다")
        elif h in seen:
            _problem(problems, "TABLE_HEADER", f"'{h}' 열이 중복됩니다")
        seen.add(h)
        cols.append(h)
    missing = [n for n in names if n not in seen]
    if missing:
        _problem(problems, "TABLE_HEADER", f"파라미터 열이 없습니다: {', '.join(missing)}")
    if problems:
        return [], {"row_count": max(len(parsed) - 1, 0)}
    data = parsed[1:]
    if not data:
        _problem(problems, "TOO_FEW_ROWS", "데이터 행이 1개 이상 필요합니다")
    elif len(data) > max_runs:
        _problem(problems, "TOO_MANY_ROWS", f"행은 최대 {max_runs}개입니다(현재 {len(data)}개)")
    if problems:
        return [], {"row_count": len(data)}
    rows: list[tuple[int, str, dict[str, float]]] = []
    for i, cells in enumerate(data, start=1):
        if len(cells) != len(header):
            _problem(problems, "TABLE_VALUE", f"{i}행 열 수({len(cells)})가 헤더({len(header)})와 다릅니다", i)
            continue
        vals: dict[str, float] = {}
        bad = [c for c, cell in zip(cols, cells) if c is not None and _finite(cell) is None]
        if bad:
            _problem(problems, "TABLE_VALUE", f"{i}행 값이 유한한 숫자가 아닙니다: {', '.join(bad)}", i)
            continue
        for c, cell in zip(cols, cells):
            if c is not None:
                vals[c] = _finite(cell)  # type: ignore[assignment]
        rows.append((i, run_key_for(i), {n: vals[n] for n in names}))
    return rows, {"row_count": len(data)}


# ---- ① 학습 DOE ---------------------------------------------------------------------------------


def _train_doe(source: Mapping[str, Any], names: Sequence[str], samples_header: Sequence[str] | None,
               samples: Sequence[Mapping[str, Any]] | None, max_runs: int,
               problems: list[dict[str, Any]]) -> tuple[list[tuple[int, str, dict[str, float]]], dict[str, Any]]:
    doe_id = source.get("doe_id")
    if not isinstance(doe_id, str) or not doe_id:
        raise BatchShapeError("source.doe_id가 필요합니다")
    meta = {"doe_id": doe_id}
    if samples is None:
        raise BatchShapeError("train_doe는 DOE samples.csv 행이 필요합니다(호출부가 읽어 넘긴다)")
    cols = [h for h in (samples_header or [])[1:] if not h.startswith("resp:")]
    if set(cols) != set(names):
        extra, miss = sorted(set(cols) - set(names)), [n for n in names if n not in set(cols)]
        detail = "; ".join(x for x in (f"DOE에만 있음: {', '.join(extra)}" if extra else "",
                                         f"DOE에 없음: {', '.join(miss)}" if miss else "") if x)
        _problem(problems, "DOE_PARAM_MISMATCH", f"DOE 파라미터가 템플릿 파라미터와 다릅니다({detail})")
        return [], meta
    rows: list[tuple[int, str, dict[str, float]]] = []
    used: set[int] = set()
    for s in samples:
        rk = str(s.get("run_key") or "")
        no = doe_no_of(rk)
        vals = s.get("values") or {}
        if no is None or no in used:
            _problem(problems, "TABLE_VALUE", f"run 이름 '{rk}'가 형식(run__숫자)에 맞지 않거나 중복됩니다")
            continue
        if any(_finite(vals.get(n)) is None for n in names):
            _problem(problems, "TABLE_VALUE", f"{rk} 값이 비어 있거나 숫자가 아닙니다", no)
            continue
        used.add(no)
        rows.append((no, rk, {n: float(vals[n]) for n in names}))
    rows.sort(key=lambda r: r[0])
    if not rows and not problems:
        _problem(problems, "TOO_FEW_ROWS", "DOE 샘플 표에 행이 없습니다")
    elif len(rows) > max_runs:
        _problem(problems, "TOO_MANY_ROWS", f"DOE run이 {len(rows)}개로 일괄 예측 상한 {max_runs}개를 넘습니다")
    return rows, meta


# ---- S15 새 kind 7개(phase3 §20.5, D3-63) -----------------------------------------------------------------

_RawRows = list[tuple[int, str, dict[str, float]]]
SOBOL_MAX_SEED = 4_294_967_295
LEVEL_MIN, LEVEL_MAX = 2, 10
SEQUENCE_TOL = 1e-9  # 이어서 추가 대조: |차| ≤ 1e-9·(hi−lo)


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


def _is_pow2_count(n: int, max_runs: int) -> bool:
    return n >= 4 and n & (n - 1) == 0 and n <= max_runs


def _span(r: Any) -> bool:
    lo = _finite(r[0]) if isinstance(r, (list, tuple)) and len(r) == 2 else None
    hi = _finite(r[1]) if isinstance(r, (list, tuple)) and len(r) == 2 else None
    return lo is not None and hi is not None and lo < hi


def _continue_check(cb: Mapping[str, Any] | None, source: Mapping[str, Any], param_set_id: str | None,
                    parameters: Sequence[Mapping[str, Any]]) -> tuple[str | None, Mapping[str, Any] | None]:
    """이어서 추가 조건(§20.5.3) → (문제 문구 또는 None, 이전 배치 meta)."""
    if not cb or cb.get("missing"):
        return "이어서 추가할 이전 배치를 찾을 수 없습니다", None
    if cb.get("source_kind") != "SOBOL":
        return "Sobol 배치가 아닙니다", None
    if param_set_id is None or cb.get("param_set_id") != param_set_id:
        return "다른 템플릿의 배치입니다", None
    meta = cb.get("source_meta") or {}
    prev_active, prev_ranges = meta.get("active"), meta.get("ranges")
    names = [str(p["name"]) for p in parameters]
    if (not isinstance(prev_active, list) or not isinstance(prev_ranges, Mapping)
            or [n for n in names if n in prev_ranges and _span(prev_ranges[n])] != prev_active):
        return "변수 구성이 다릅니다", None
    if source.get("seed") is not None or source.get("ranges") not in (None, {}):
        return "이어서 추가는 이전 배치의 시드·범위를 그대로 씁니다", None
    return None, meta


def _matches_previous(dsn: _Design, old_u: Sequence[Sequence[float]], runs: Sequence[Mapping[str, Any]], count: int) -> bool:
    """이전 배치 구간을 다시 만든 값이 저장된 run 값과 |차| ≤ 1e-9·(hi−lo)인지."""
    by_no = {int(r["doe_no"]): r.get("values") or {} for r in runs if "doe_no" in r}
    if len(old_u) != count or len(by_no) != count:
        return False
    for i, row in enumerate(old_u, start=1):
        stored = by_no.get(i)
        if not stored:
            return False
        for j, n in enumerate(dsn.active):
            lo, hi = dsn.bounds[n]
            v = _finite(stored.get(n))
            if v is None or abs(v - designs.unit_to_value(row[j], lo, hi)) > SEQUENCE_TOL * (hi - lo):
                return False
    return True


def _sobol(source: Mapping[str, Any], parameters: Sequence[Mapping[str, Any]], max_runs: int,
           problems: list[dict[str, Any]], continue_batch: Mapping[str, Any] | None, param_set_id: str | None
           ) -> tuple[_RawRows, dict[str, Any], list[dict[str, str]], _Design]:
    count = _int_arg(source, "count")
    if count is None:
        raise BatchShapeError("source.count는 정수여야 합니다")
    cont = source.get("continue_from")
    if cont is not None and (not isinstance(cont, str) or not cont or len(cont) > 64):
        raise BatchShapeError("source.continue_from은 배치 id(64자 이하) 또는 null이어야 합니다")
    seed = _int_arg(source, "seed")
    if seed is not None and not 0 <= seed <= SOBOL_MAX_SEED:
        raise BatchShapeError(f"source.seed는 0~{SOBOL_MAX_SEED}입니다")
    pow2 = _is_pow2_count(count, max_runs)
    if not pow2:
        _problem(problems, "COUNT_NOT_POW2", "Sobol은 run 수가 2의 거듭제곱이어야 합니다(4·8·16·32·64·128)")
    prev: Mapping[str, Any] | None = None
    if cont is not None:
        why, prev = _continue_check(continue_batch, source, param_set_id, parameters)
        if why:
            _problem(problems, "CONTINUE_INVALID", why)
            return [], {"count": count, "continue_from": None}, [], _design_vars(None, parameters, [])
        ranges = {n: prev["ranges"][n] for n in prev["active"]}  # type: ignore[index]
        seed = int(prev.get("seed", 1))  # type: ignore[union-attr]
    else:
        ranges = source.get("ranges")
        seed = 1 if seed is None else seed
    dsn = _design_vars(ranges, parameters, problems)
    meta: dict[str, Any] = {"count": count, "seed": seed, "scramble": True, "offset": 0, "continue_from": None,
                            **dsn.base_meta()}
    if pow2:
        meta["m"] = count.bit_length() - 1
    if dsn.k == 0 and not problems:
        _unsupported(problems, "범위가 있는 변수가 없습니다")
    if problems:
        return [], meta, [], dsn
    notes: list[dict[str, str]] = []
    offset = 0
    try:
        if prev is not None and continue_batch is not None:
            p_off, p_cnt = int(prev.get("offset", 0)), int(prev.get("count", 0))
            offset = p_off + p_cnt
            if offset % count != 0:
                _problem(problems, "CONTINUE_INVALID",
                         f"이어서 추가할 run 수는 {offset}을 나누어떨어지게 하는 2의 거듭제곱이어야 합니다(권장 {offset & -offset})")
                return [], meta, [], dsn
            old_u, _gen = qmc.sobol_unit(dsn.k, p_cnt, seed, p_off)
            if not _matches_previous(dsn, old_u, continue_batch.get("runs") or [], p_cnt):
                _problem(problems, "SEQUENCE_MISMATCH",
                         "이전 배치를 같은 수열로 다시 만들 수 없습니다(계산 라이브러리 버전 차이) — 새 Sobol 배치로 시작하세요")
                return [], meta, [], dsn
            label = str(continue_batch.get("label") or "")
            total = offset + count
            notes.append({"code": "SEQUENCE_CONTINUED",
                          "message": f"{label}과 합치면 {total}개" + ("(균형 유지)" if total & (total - 1) == 0 else "(합계는 균형 아님)")})
            meta["continue_from"] = {"batch_id": continue_batch.get("id"), "label": label}
        u, gen = qmc.sobol_unit(dsn.k, count, seed, offset)
    except qmc.GeneratorUnavailable as exc:
        _problem(problems, "GENERATOR_UNAVAILABLE", str(exc))
        return [], meta, [], dsn
    meta["offset"] = offset
    meta["generator"] = gen
    meta["quality"] = designs.quality(u)
    return _rows_from(dsn, u, designs.unit_to_value), meta, notes, dsn


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


def _new_kind(kind: str, source: Mapping[str, Any], parameters: Sequence[Mapping[str, Any]],
              tpl_params: Sequence[Mapping[str, Any]], max_runs: int, integer_rounding: str,
              problems: list[dict[str, Any]], continue_batch: Mapping[str, Any] | None, param_set_id: str | None
              ) -> tuple[_RawRows, dict[str, Any], list[dict[str, str]], _Design]:
    if kind == "sobol":
        return _sobol(source, parameters, max_runs, problems, continue_batch, param_set_id)
    dsn = _design_vars(source.get("ranges"), parameters, problems)
    if problems:
        return [], dsn.base_meta(), [], dsn
    if dsn.k == 0:
        _unsupported(problems, "범위가 있는 변수가 없습니다")
        return [], dsn.base_meta(), [], dsn
    if kind == "lhs_opt":
        raw, meta, notes = _lhs_opt(source, dsn, max_runs, problems)
    elif kind == "fullfact":
        raw, meta, notes = _fullfact(source, dsn, tpl_params, integer_rounding, max_runs, problems)
    elif kind == "fracfact":
        raw, meta, notes = _fracfact(source, dsn, max_runs, problems)
    elif kind == "pb":
        raw, meta, notes = _pb(dsn, max_runs, problems)
    elif kind == "bbd":
        raw, meta, notes = _bbd(dsn, max_runs, problems)
    else:
        raw, meta, notes = _ccd(source, dsn, max_runs, problems)
    return raw, meta, notes, dsn


def _all_notes(dsn: _Design, kind_notes: list[dict[str, str]], rows: Sequence[BatchRow], names: Sequence[str]
               ) -> list[dict[str, str]]:
    """안내 순서(§20.9): 고정 변수 제외 → 방식별 → 정수 반올림 중복 → 영향도 run 부족."""
    notes: list[dict[str, str]] = []
    if dsn.fixed:
        notes.append({"code": "FIXED_EXCLUDED", "message": f"고정 변수 {'·'.join(dsn.fixed)}는 설계에서 빼고 고정값을 씁니다"})
    notes.extend(kind_notes)
    if rows:
        dups = len(rows) - len({tuple(r.applied_values[n] for n in names) for r in rows})
        if dups:
            notes.append({"code": "DUPLICATE_ROWS", "message": f"정수 반올림 뒤 같은 조합이 {dups}개 있습니다 — 같은 예측이 반복됩니다"})
        need = max(5, len(names) + 2)
        if len(rows) < need:
            notes.append({"code": "INFLUENCE_TOO_FEW", "message": f"run이 {need}개보다 적어 ⑤ 영향도는 계산되지 않습니다"})
    return notes


# ---- 공용 진입점 -----------------------------------------------------------------------------------


def build_matrix(
    source: Mapping[str, Any],
    *,
    parameters: Sequence[Mapping[str, Any]],
    tpl_params: Sequence[Mapping[str, Any]],
    max_runs: int,
    table_max_bytes: int,
    integer_rounding: str = "half_up",
    samples_header: Sequence[str] | None = None,
    samples: Sequence[Mapping[str, Any]] | None = None,
    continue_batch: Mapping[str, Any] | None = None,
    param_set_id: str | None = None,
) -> BatchMatrix:
    """템플릿(param_sets.parameters·tpl_params) + source → 조합 행(doe_no 순). train_doe는 samples(header, rows)를 넘긴다.

    sobol 이어서 추가(`continue_from`)는 호출부가 이전 배치를 읽어 `continue_batch`로 넘긴다:
    `{id, label, source_kind, param_set_id, source_meta, runs:[{doe_no, values}]}`(없거나 다른 Study면 `{"missing": True}`).
    """
    if not isinstance(source, Mapping):
        raise BatchShapeError("source는 객체여야 합니다")
    kind = source.get("kind")
    if kind not in SOURCE_KINDS:
        raise BatchShapeError("source.kind는 " + " | ".join(SOURCE_KINDS) + " 중 하나입니다")
    names = [str(p["name"]) for p in parameters]
    problems: list[dict[str, Any]] = []
    notes: list[dict[str, str]] = []
    dsn: _Design | None = None
    if kind == "lhs":
        raw, meta = _lhs(source, parameters, max_runs, problems)
    elif kind == "table":
        raw, meta = _table(source, names, max_runs, table_max_bytes, problems)
    elif kind == "train_doe":
        raw, meta = _train_doe(source, names, samples_header, samples, max_runs, problems)
    else:
        raw, meta, notes, dsn = _new_kind(kind, source, parameters, tpl_params, max_runs, integer_rounding, problems,
                                          continue_batch, param_set_id)
    rows = [_make_row(no, rk, v, parameters, tpl_params, integer_rounding) for no, rk, v in raw]
    if dsn is not None:
        notes = _all_notes(dsn, notes, rows, names)
    return BatchMatrix(SOURCE_KINDS[kind], rows, problems, meta, notes)


def build_matrix_for(source: Mapping[str, Any], param_set: Mapping[str, Any], settings: Any, *,
                     samples_header: Sequence[str] | None = None,
                     samples: Sequence[Mapping[str, Any]] | None = None,
                     continue_batch: Mapping[str, Any] | None = None) -> BatchMatrix:
    """param_sets 행 + 설정(predict_batch·predict.integer_rounding)으로 build_matrix(미리보기·작업 생성·워커 공용)."""
    return build_matrix(
        source, parameters=param_set["parameters"], tpl_params=param_set.get("tpl_params") or [],
        max_runs=settings.predict_batch.max_runs, table_max_bytes=settings.predict_batch.table_max_bytes,
        integer_rounding=settings.predict.integer_rounding, samples_header=samples_header, samples=samples,
        continue_batch=continue_batch, param_set_id=param_set.get("id"),
    )


def samples_csv_text(names: Sequence[str], rows: Sequence[BatchRow]) -> str:
    """배치 폴더 samples.csv(`doe_no,run_key,<파라미터…>` 반영값) — 폴더 ↔ 번호 ↔ 값(§14.3)."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["doe_no", "run_key", *names])
    for r in rows:
        w.writerow([r.doe_no, r.run_key, *[repr(float(r.applied_values[n])) for n in names]])
    return buf.getvalue()
