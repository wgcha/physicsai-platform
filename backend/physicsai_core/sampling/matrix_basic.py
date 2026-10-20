"""S9 source.kind 3개(lhs·table·train_doe) 조합 행 계산 — matrix에서 재노출."""

from __future__ import annotations

import csv
import io
import random
from collections.abc import Mapping, Sequence
from typing import Any

from .matrix_rows import (
    DOE_COLUMN,
    BatchShapeError,
    _finite,
    _problem,
    doe_no_of,
    run_key_for,
)

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
