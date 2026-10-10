"""①-3 DOE 샘플 표 추출기(플러그형, phase2 §6.4.1, U18).

- paramitem(기본): run 폴더의 렌더링된 tpl 파일에서 <paramitem Name=… NewValue=…> 값을 읽는다.
- csv: DOE 폴더의 CSV(헤더에 run 열과 파라미터 이름 또는 var_i 열).
- none: 추출 안 함(MISSING).
"""

from __future__ import annotations

import csv
import glob
import math
import os
import re
from dataclasses import dataclass, field
from typing import Any

from ..paths import is_link_or_reparse


@dataclass
class SamplesResult:
    status: str  # PARSED | PARTIAL | MISSING
    rows: list[dict[str, Any]] = field(default_factory=list)  # [{run_key, values:{name: float}}]
    missing_runs: list[str] = field(default_factory=list)
    source: str | None = None


def _num(v: str) -> float | None:
    try:
        f = float(v.strip())
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _iter_candidate_files(run_dir: str, pattern: str, exts: list[str], max_bytes: int) -> list[str]:
    out = []
    for p in sorted(glob.glob(os.path.join(run_dir, pattern), recursive=True)):
        if not os.path.isfile(p) or is_link_or_reparse(p):
            continue
        ext = os.path.splitext(p)[1].lower()
        if ext not in [e.lower() for e in exts]:
            continue
        try:
            if os.path.getsize(p) > max_bytes:
                continue
        except OSError:
            continue
        out.append(p)
    return out


def paramitem_values(run_dir: str, names: list[str], td: Any) -> tuple[dict[str, float] | None, str | None]:
    """사용 파라미터 이름이 모두 숫자 값으로 나오는 첫 파일의 값. NewValue에 '{var_'가 남으면 미렌더로 건너뜀."""
    rx = re.compile(td.paramitem_regex)
    for p in _iter_candidate_files(run_dir, td.rendered_tpl_glob, td.rendered_tpl_exts, td.samples_scan_max_bytes):
        try:
            with open(p, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            continue
        found: dict[str, float] = {}
        unrendered = False
        for m in rx.finditer(text):
            name, value = m.group("name"), m.group("value")
            if "{var_" in value:
                unrendered = True
                break
            if name in names:
                v = _num(value)
                if v is not None:
                    found[name] = v
        if unrendered:
            continue
        if all(n in found for n in names):
            return {n: found[n] for n in names}, os.path.relpath(p, run_dir).replace(os.sep, "/")
    return None, None


def extract(doe_dir: str, runs: list[dict[str, str]], names: list[str], td: Any) -> SamplesResult:
    """runs = [{run_key, run_dir(절대)}]."""
    mode = td.samples_extractor
    if mode == "none" or not names:
        return SamplesResult("MISSING", missing_runs=[r["run_key"] for r in runs])
    if mode == "csv":
        return _extract_csv(doe_dir, runs, names, td)
    rows, missing = [], []
    for r in runs:
        vals, _src = paramitem_values(r["run_dir"], names, td)
        if vals is None:
            missing.append(r["run_key"])
        else:
            rows.append({"run_key": r["run_key"], "values": vals})
    if not rows:
        return SamplesResult("MISSING", missing_runs=missing, source="paramitem")
    return SamplesResult("PARTIAL" if missing else "PARSED", rows, missing, "paramitem")


def _extract_csv(doe_dir: str, runs: list[dict[str, str]], names: list[str], td: Any) -> SamplesResult:
    keys = [r["run_key"] for r in runs]
    if not td.samples_csv_glob:
        return SamplesResult("MISSING", missing_runs=keys, source="csv")
    files = sorted(p for p in glob.glob(os.path.join(doe_dir, td.samples_csv_glob), recursive=True) if os.path.isfile(p))
    if not files:
        return SamplesResult("MISSING", missing_runs=keys, source="csv")
    path = files[0]
    var_map = {f"var_{i}": n for i, n in enumerate(names, start=1)}
    by_run: dict[str, dict[str, float]] = {}
    with open(path, encoding="utf-8-sig", newline="") as fh:
        rd = csv.DictReader(fh)
        for row in rd:
            rk = (row.get(td.samples_csv_run_column) or "").strip()
            vals: dict[str, float] = {}
            for col, raw in row.items():
                if col is None:
                    continue
                name = col.strip()
                name = var_map.get(name, name)
                if name in names:
                    v = _num(raw or "")
                    if v is not None:
                        vals[name] = v
            if rk and all(n in vals for n in names):
                by_run[rk] = {n: vals[n] for n in names}
    rows = [{"run_key": k, "values": by_run[k]} for k in keys if k in by_run]
    missing = [k for k in keys if k not in by_run]
    if not rows:
        return SamplesResult("MISSING", missing_runs=missing, source="csv")
    return SamplesResult("PARTIAL" if missing else "PARSED", rows, missing, "csv")


def write_samples_csv(path: str, names: list[str], rows: list[dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["run_key", *names])
        for r in rows:
            w.writerow([r["run_key"], *[repr(float(r["values"][n])) for n in names]])


def read_samples_csv(path: str) -> tuple[list[str], list[dict[str, Any]]]:
    """samples.csv(run_key,<이름…>[,resp:…]) → (헤더, [{run_key, values, measured}])."""
    if not os.path.isfile(path):
        return [], []
    out = []
    with open(path, encoding="utf-8-sig", newline="") as fh:
        rd = csv.reader(fh)
        header = next(rd, [])
        for row in rd:
            if not row:
                continue
            values, measured = {}, {}
            for h, c in zip(header[1:], row[1:]):
                if h.startswith("resp:"):
                    measured[h[5:]] = _num(c) if c.strip() else None
                else:
                    v = _num(c)
                    if v is not None:
                        values[h] = v
            out.append({"run_key": row[0], "values": values, "measured": measured})
    return header, out
