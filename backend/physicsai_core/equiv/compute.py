"""지표 계산(equiv-check.md §4.3 EQ_COMPUTE) — 쌍 × 지표 행(`metrics.csv` 모양)과 곡선 보간 데이터. 파일은 읽기만.

워커 EQ_COMPUTE가 쓰고, 시험은 파일 트리를 만들어 직접 부른다. 원본 run 폴더에는 쓰지 않는다(추출본은 extract_root overlay).
"""

from __future__ import annotations

import json
import math
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from ..stage4_predict import performance
from . import metrics as mx
from . import volume as vol
from .plan import RunRead, read_run
from .sides import Run, Side

CSV_HEADER = ("pair_no", "a_run", "b_run", "metric_id", "a", "b", "diff", "rel_pct", "corr", "status", "reason")
_MASS_RE = re.compile(r"TOTAL\s+MASS\s*[:=]?\s*([-+0-9.eE]+)", re.I)


@dataclass
class ComputeOut:
    rows: list[dict[str, Any]] = field(default_factory=list)
    curves: dict[tuple[int, str], dict[str, Any]] = field(default_factory=dict)  # (pair_no, metric_id) → {t, a, b, ...}
    warnings: list[dict[str, Any]] = field(default_factory=list)

    def warn(self, code: str, message: str) -> None:
        if not any(w["code"] == code and w["message"] == message for w in self.warnings):
            self.warnings.append({"code": code, "message": message[:480]})


def _row(pair_no: int, a_run: str, b_run: str, mid: str, **kw: Any) -> dict[str, Any]:
    base = {"pair_no": pair_no, "a_run": a_run, "b_run": b_run, "metric_id": mid, "a": None, "b": None, "diff": None,
            "rel_pct": None, "corr": None, "status": mx.NA, "reason": None}
    base.update(kw)
    return base


def _load_curve(path: str | None, max_bytes: int) -> dict[str, Any] | None:
    if not path:
        return None
    try:
        if os.path.getsize(path) > max_bytes:
            return None
        with open(path, encoding="utf-8-sig") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, Mapping) and isinstance(data.get("series"), list) else None


def _series(curve: Mapping[str, Any] | None, name: str | None) -> tuple[list[Any], list[Any]] | None:
    if curve is None:
        return None
    items = [s for s in curve["series"] if isinstance(s, Mapping) and isinstance(s.get("name"), str)]
    if not items:
        return None
    pick = None
    if name is None:
        pick = items[0]
    else:
        pick = next((s for s in items if s["name"] == name), None)
        if pick is None:  # 대소문자·공백 무시(phase3 §21.3.6 계열 짝짓기)
            key = re.sub(r"\s+", "", name).casefold()
            pick = next((s for s in items if re.sub(r"\s+", "", s["name"]).casefold() == key), None)
    if pick is None or not isinstance(pick.get("x"), list) or not isinstance(pick.get("y"), list):
        return None
    return list(pick["x"]), list(pick["y"])


def _scalar_value(d: Mapping[str, Any] | None, rr: RunRead) -> tuple[float | None, str | None]:
    if d is None:
        return None, "UNBOUND"
    pd = performance.perf_defs([d]).get(d["name"])
    if pd is None:
        return None, "SPEC_INVALID"
    return performance.perf_value(pd, rr.metrics)


def _series_name(metric: Mapping[str, Any], d: Mapping[str, Any] | None) -> str | None:
    src = metric.get("source") or {}
    if isinstance(d, Mapping):
        return (d.get("spec") or {}).get("series")
    return src.get("series")


def _volume(run: Run, src: Mapping[str, Any], settings: Any, out: ComputeOut) -> tuple[float | None, str | None]:
    origin = str(src.get("origin") or "mesh")
    if origin == "mesh":
        cap = settings.fem_verify.include_scan_max_bytes * 16
        if not run.mesh_inc and not run.mesh_tree:
            return None, "MESH_MISSING"
        # 조립 매칭 run(asm-match.md §6.4): 기준본 include 파일 대신 조립 트리 전체에서 읽고, cushion = 매칭된 PART id
        mesh = vol.read_include(run.mesh_inc, max_bytes=cap) if run.mesh_inc else vol.read_tree(str(run.mesh_tree), max_bytes=cap)
        if mesh is None:
            return None, "MESH_MISSING"
        parts = vol.resolve_parts(src.get("parts", "cushion"), None if run.mesh_inc else run.mesh_parts)
        res = vol.part_volume(mesh, parts)
        if res.skipped_kinds:
            out.warn("EQ_VOLUME_ELEM_SKIPPED", f"{run.name}: 지원하지 않는 요소형을 건너뜀 — {', '.join(res.skipped_kinds)}")
        if res.n_elems == 0:
            return None, "VOLUME_ZERO"
        return res.volume, None
    base = os.path.dirname(run.mesh_inc) if run.mesh_inc else (run.mesh_tree or (os.path.dirname(run.result_dir) if run.result_dir else None))
    if origin == "paicad":
        for rel in (("_paicad", "update", "update.json"), ("m_1", "update", "update.json"), ("update", "update.json")):
            p = os.path.join(base, *rel) if base else None
            if p and os.path.isfile(p):
                try:
                    with open(p, encoding="utf-8-sig") as fh:
                        rep = json.load(fh)
                    vs = [float(b["volume"]) for b in rep.get("bodies") or [] if isinstance(b, Mapping) and isinstance(b.get("volume"), (int, float))]
                    if vs:
                        return sum(vs), None
                except (OSError, ValueError, TypeError):
                    pass
        return None, "VOLUME_SOURCE_MISSING"
    if origin == "starter_mass":  # starter 출력(*_0000.out)의 TOTAL MASS — 밀도 같을 때 부피 비와 같다(Q3)
        folders = [f for f in (run.result_dir, base) if f]
        for f in folders:
            for n in sorted(os.listdir(f)) if os.path.isdir(f) else []:
                if n.lower().endswith("_0000.out") or n.lower().endswith("_0000.sty"):
                    try:
                        with open(os.path.join(f, n), encoding="utf-8", errors="replace") as fh:
                            for line in fh:
                                m = _MASS_RE.search(line)
                                if m:
                                    return float(m.group(1)), None
                    except (OSError, ValueError):
                        continue
        return None, "VOLUME_SOURCE_MISSING"
    return None, "SPEC_INVALID"


def compute(defn: Mapping[str, Any], resolved: Mapping[str, Mapping[str, Any]], a: Side, b: Side,
            pairs: Sequence[tuple[str, str]], *, settings: Any, extract_root: str | None) -> ComputeOut:
    out = ComputeOut()
    e = settings.equiv_check
    max_bytes = settings.ui.max_artifact_bytes
    runs_a = {r.name: r for r in a.runs}
    runs_b = {r.name: r for r in b.runs}
    for no, (an, bn) in enumerate(pairs, 1):
        ra, rb = runs_a.get(an), runs_b.get(bn)
        if ra is None or rb is None or not ra.ok or not rb.ok:
            for m in defn["metrics"]:
                out.rows.append(_row(no, an, bn, m["id"], reason="RUN_NOT_SUCCEEDED"))
            continue
        rra = read_run(ra, a, "a", defn, resolved, extract_root=extract_root, max_bytes=max_bytes)
        rrb = read_run(rb, b, "b", defn, resolved, extract_root=extract_root, max_bytes=max_bytes)
        ca = cb = None
        for m in defn["metrics"]:
            mid, kind, tol = m["id"], m["kind"], m.get("tol") or {}
            res = resolved.get(mid) or {}
            if res.get("na") and kind != "mesh_volume":
                out.rows.append(_row(no, an, bn, mid, reason=res["na"]))
                continue
            if kind == "scalar":
                va, wa = _scalar_value(res.get("a"), rra)
                vb, wb = _scalar_value(res.get("b"), rrb)
                j = mx.judge_scalar(va, vb, tol, zero_tol=e.zero_tol)
                reason = j.reason if j.status != mx.NA else (wa or wb or j.reason)
                out.rows.append(_row(no, an, bn, mid, a=j.a, b=j.b, diff=j.diff, rel_pct=j.rel_pct, status=j.status, reason=reason))
            elif kind in ("curve_corr", "curve_nrmse"):
                ca = ca if ca is not None else _load_curve(rra.curve_json, max_bytes)
                cb = cb if cb is not None else _load_curve(rrb.curve_json, max_bytes)
                if ca is None or cb is None:
                    out.rows.append(_row(no, an, bn, mid, reason="NO_CURVE"))
                    continue
                sa, sb = _series(ca, _series_name(m, res.get("a"))), _series(cb, _series_name(m, res.get("b")))
                if sa is None or sb is None:
                    out.rows.append(_row(no, an, bn, mid, reason="SERIES_MISSING"))
                    continue
                rs = mx.resample_common(sa[0], sa[1], sb[0], sb[1], e.curve_points)
                v, status, reason = mx.judge_curve(kind, rs, tol)
                if rs is not None and rs.overlap_ratio < e.curve_min_overlap:
                    out.warn("EQ_CURVE_SHORT_OVERLAP", f"{an} ↔ {bn} {m['label']}: 공통 시간 구간이 짧습니다({rs.overlap_ratio * 100:.0f}%)")
                row = _row(no, an, bn, mid, status=status, reason=reason)
                if kind == "curve_corr":
                    row["corr"] = v
                else:
                    row["a"], row["b"], row["diff"] = (max(rs.a) - min(rs.a)) if rs else None, None, v
                    row["rel_pct"] = v
                out.rows.append(row)
                if rs is not None:
                    out.curves[(no, mid)] = {"pair_no": no, "metric_id": mid, "a_run": an, "b_run": bn, "t": rs.t, "a": rs.a, "b": rs.b,
                                             "corr": mx.pearson(rs.a, rs.b), "nrmse_pct": mx.nrmse_pct(rs.a, rs.b),
                                             "overlap_ratio": rs.overlap_ratio}
            elif kind == "mesh_volume":
                src = m.get("source") or {"type": "mesh_volume", "parts": "cushion", "origin": "mesh"}
                va, wa = _volume(ra, src, settings, out)
                vb, wb = _volume(rb, src, settings, out)
                j = mx.judge_scalar(va, vb, tol, zero_tol=e.zero_tol)
                reason = j.reason if j.status != mx.NA else (wa or wb or j.reason)
                out.rows.append(_row(no, an, bn, mid, a=j.a, b=j.b, diff=j.diff, rel_pct=j.rel_pct, status=j.status, reason=reason))
    return out


def csv_text(rows: Sequence[Mapping[str, Any]]) -> str:
    def cell(v: Any) -> str:
        if v is None:
            return ""
        if isinstance(v, float):
            return repr(v) if math.isfinite(v) else ""
        return str(v)

    lines = [",".join(CSV_HEADER)]
    lines += [",".join(cell(r.get(k)) for k in CSV_HEADER) for r in rows]
    return "\n".join(lines) + "\n"


def parse_csv_text(text: str) -> list[dict[str, Any]]:
    import csv
    import io

    out: list[dict[str, Any]] = []
    for r in csv.DictReader(io.StringIO(text)):
        row: dict[str, Any] = dict(r)
        row["pair_no"] = int(row["pair_no"]) if row.get("pair_no") else None
        for k in ("a", "b", "diff", "rel_pct", "corr"):
            row[k] = float(row[k]) if row.get(k) not in (None, "") else None
        row["reason"] = row.get("reason") or None
        out.append(row)
    return out


def aggregate_all(defn: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """지표별 집계(§4.4) + 종합. 요약 JSON(DB summary) 모양."""
    pr = defn.get("pair_rule") or {"mode": "all"}
    aggs = {m["id"]: mx.aggregate([r for r in rows if r["metric_id"] == m["id"]], pr) for m in defn["metrics"]}
    verdict = mx.overall_verdict(defn["metrics"], aggs)
    return {"metrics": aggs, "verdict": verdict}
