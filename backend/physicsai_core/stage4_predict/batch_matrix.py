"""④ 일괄 예측(DOE) 조합 계산(phase3 §14.5 S9) — 미리보기·작업 생성·워커가 같은 결과를 쓴다(순수 함수, I/O 없음).

source.kind:
- `lhs`: `count`(2~max_runs)·`seed`(정수, 기본 1)·`ranges{name:[lo,hi]}`(생략 = 세트 min·max). `random.Random(seed)`로
  파라미터마다(세트 순서) ① 층 순열 `perm = shuffle(range(n))` ② run i마다 `u = random()` →
  값 = `lo + (perm[i] + u)/n·(hi−lo)`. 층마다 정확히 1개. 학습 범위 밖 허용(`out_of_range`).
- `table`: 붙여넣기·CSV 텍스트. 구분자 탭(첫 줄에 탭이 있으면)/쉼표 자동, BOM 허용, 첫 줄 헤더 = 파라미터 이름 전부(순서 무관,
  선택 열 `doe`는 무시), 데이터 행 1~max_runs, doe_no = 행 순서 1..
- `train_doe`: ① DOE `samples.csv` 행(`doe_samples.read_samples_csv` 결과). 파라미터 이름 집합 = 템플릿 이름 집합,
  doe_no = run 번호(`run__00014` → 14), run_key = ① run 이름 그대로.

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

from . import nearest

SOURCE_KINDS = {"lhs": "LHS", "table": "TABLE", "train_doe": "TRAIN_DOE"}  # API kind → DB source_kind
PROBLEM_CODES = (
    "TABLE_HEADER", "TABLE_VALUE", "TEXT_TOO_LARGE", "TOO_MANY_ROWS", "TOO_FEW_ROWS", "RANGE_INVALID", "DOE_PARAM_MISMATCH",
)
MAX_PROBLEMS = 100  # 행 오류는 이 개수까지만 모은다(화면 회색 줄)
DOE_COLUMN = "doe"  # 표의 선택 열(무시)
RUN_KEY_RE = re.compile(r"^run__(\d+)$")


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

    source_kind: str  # LHS | TABLE | TRAIN_DOE
    rows: list[BatchRow] = field(default_factory=list)
    problems: list[dict[str, Any]] = field(default_factory=list)
    source_meta: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """문제 없음 + 행 1개 이상."""
        return not self.problems and bool(self.rows)


def run_key_for(doe_no: int) -> str:
    """doe_no → run 폴더 이름 `run__00001`(① hstbatch와 같은 5자리)."""
    return f"run__{int(doe_no):05d}"


def doe_no_of(run_key: str) -> int | None:
    """`run__00014` → 14. 형식이 다르면 None."""
    m = RUN_KEY_RE.match(run_key or "")
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
) -> BatchMatrix:
    """템플릿(param_sets.parameters·tpl_params) + source → 조합 행(doe_no 순). train_doe는 samples(header, rows)를 넘긴다."""
    if not isinstance(source, Mapping):
        raise BatchShapeError("source는 객체여야 합니다")
    kind = source.get("kind")
    if kind not in SOURCE_KINDS:
        raise BatchShapeError("source.kind는 lhs | table | train_doe 중 하나입니다")
    names = [str(p["name"]) for p in parameters]
    problems: list[dict[str, Any]] = []
    if kind == "lhs":
        raw, meta = _lhs(source, parameters, max_runs, problems)
    elif kind == "table":
        raw, meta = _table(source, names, max_runs, table_max_bytes, problems)
    else:
        raw, meta = _train_doe(source, names, samples_header, samples, max_runs, problems)
    rows = [_make_row(no, rk, v, parameters, tpl_params, integer_rounding) for no, rk, v in raw]
    return BatchMatrix(SOURCE_KINDS[kind], rows, problems, meta)


def build_matrix_for(source: Mapping[str, Any], param_set: Mapping[str, Any], settings: Any, *,
                     samples_header: Sequence[str] | None = None,
                     samples: Sequence[Mapping[str, Any]] | None = None) -> BatchMatrix:
    """param_sets 행 + 설정(predict_batch·predict.integer_rounding)으로 build_matrix(미리보기·작업 생성·워커 공용)."""
    return build_matrix(
        source, parameters=param_set["parameters"], tpl_params=param_set.get("tpl_params") or [],
        max_runs=settings.predict_batch.max_runs, table_max_bytes=settings.predict_batch.table_max_bytes,
        integer_rounding=settings.predict.integer_rounding, samples_header=samples_header, samples=samples,
    )


def samples_csv_text(names: Sequence[str], rows: Sequence[BatchRow]) -> str:
    """배치 폴더 samples.csv(`doe_no,run_key,<파라미터…>` 반영값) — 폴더 ↔ 번호 ↔ 값(§14.3)."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["doe_no", "run_key", *names])
    for r in rows:
        w.writerow([r.doe_no, r.run_key, *[repr(float(r.applied_values[n])) for n in names]])
    return buf.getvalue()
