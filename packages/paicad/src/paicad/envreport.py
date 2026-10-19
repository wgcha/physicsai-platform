"""Morphing envelope report (contract section 11.2): ``report_envelope.md`` + ``report_envelope.csv``.

Per parameter and direction: last OK step, first failing step and code, and the limiting metric
(the criterion with the smallest margin = value / threshold, at the first failure or, when nothing
failed, at the last OK step). Pure functions of ``envelope.json`` content: deterministic.
"""

from __future__ import annotations

import csv
import io
import math

REPORT_MD = "report_envelope.md"
REPORT_CSV = "report_envelope.csv"
REPORT_COLUMNS = (
    "param",
    "nominal",
    "last_ok_pct_plus",
    "last_ok_pct_minus",
    "first_fail_pct_plus",
    "first_fail_code_plus",
    "first_fail_pct_minus",
    "first_fail_code_minus",
    "limit_metric_plus",
    "limit_margin_plus",
    "limit_metric_minus",
    "limit_margin_minus",
    "feasible_min",
    "feasible_max",
)


def margins(row: dict, opts: dict) -> dict[str, float]:
    """value / threshold (>= 1 passes) for every criterion with a recorded metric."""
    q, dv = opts["quality"], opts["deviation"]
    out: dict[str, float] = {}
    if row.get("inverted_elems") is not None:
        out["inverted"] = 0.0 if row["inverted_elems"] else math.inf
    if row.get("min_stretch") is not None:
        out["min_stretch"] = row["min_stretch"] / float(q["min_stretch"])
    if row.get("max_aspect") is not None:
        out["max_aspect"] = float(q["max_aspect"]) / row["max_aspect"] if row["max_aspect"] > 0 else math.inf
    elif row.get("min_stretch") is not None:  # metrics recorded but aspect not finite: degenerate boundary triangle
        out["max_aspect"] = 0.0
    if row.get("min_edge_ratio") is not None:
        out["min_edge_ratio"] = row["min_edge_ratio"] / float(q["min_edge_ratio"])
    if row.get("dt_ratio") is not None:
        out["dt_ratio"] = row["dt_ratio"] / float(q["dt_ratio_min"])
    if row.get("boundary_dev_max_mm") is not None:
        d = row["boundary_dev_max_mm"]
        out["boundary_dev"] = float(dv["boundary_max_mm"]) / d if d > 0 else math.inf
    err = (row.get("param_remeasure_err") or {}).get("abs")
    if "param_margin" in row and err is not None:
        out["param_remeasure"] = math.inf if row["param_margin"] is None else float(row["param_margin"])
    elif err is not None:
        tol = max(float(dv["param_abs_mm"]), float(dv["param_rel"]) * abs(float(row.get("value") or 0.0)))
        out["param_remeasure"] = tol / err if err > 0 else math.inf
    return out


def limit_metric(rows: list[dict], opts: dict) -> dict:
    """Limiting criterion of one parameter direction (rows in step order)."""
    if not rows:
        return {"metric": None, "margin": None, "at_pct": None, "source": None}
    ff = next((r for r in rows if r["status"] == "FAIL"), None)
    row = ff
    if row is None:
        row = rows[-1]
    m = margins(row, opts)
    if ff is not None and not m:  # CAD / morph failure: no mesh metrics
        return {"metric": ff["fail_code"], "margin": None, "at_pct": ff["pct"], "source": "first_fail"}
    if not m:
        return {"metric": None, "margin": None, "at_pct": row["pct"], "source": "last_ok"}
    name = min(sorted(m), key=lambda k: m[k])
    v = m[name]
    return {"metric": name, "margin": round(v, 4) if math.isfinite(v) else None, "at_pct": row["pct"], "source": "first_fail" if ff is not None else "last_ok"}


def _pct(x) -> str:
    if x is None:
        return "-"
    return str(int(x)) if float(x).is_integer() else repr(float(x))


def _lm(s: dict, d: str) -> tuple[str, str]:
    lm = (s.get("limit_metric") or {}).get(d) or {}
    return lm.get("metric") or "-", "-" if lm.get("margin") is None else repr(lm["margin"])


def render(env: dict) -> tuple[str, str]:
    rows = []
    for s in env["summary"]:
        mp, gp = _lm(s, "+")
        mm, gm = _lm(s, "-")
        rows.append(
            [
                s["param"],
                repr(float(s["nominal"])),
                _pct(s["last_ok_pct"]["+"]),
                _pct(s["last_ok_pct"]["-"]),
                _pct(s["first_fail_pct"]["+"]),
                s["first_fail_code"]["+"] or "-",
                _pct(s["first_fail_pct"]["-"]),
                s["first_fail_code"]["-"] or "-",
                mp,
                gp,
                mm,
                gm,
                repr(s["feasible"]["min"]),
                repr(s["feasible"]["max"]),
            ]
        )
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(REPORT_COLUMNS)
    w.writerows(rows)
    q = env["options"]["quality"]
    steps = ", ".join(_pct(x) for x in env["steps_pct"])
    md = [
        "# Morphing envelope report",
        "",
        f"- engine_version: {env['engine_version']}",
        f"- sweep_id: {env['sweep_id']}",
        f"- steps (% of nominal, each direction): {steps}; stop after {env['stop_after_fail']} consecutive failures",
        f"- quality: min_stretch {q['min_stretch']}, max_aspect {q['max_aspect']}, min_edge_ratio {q['min_edge_ratio']}, "
        f"dt_ratio_min {q['dt_ratio_min']}, min_edge_mm {q['min_edge_mm']}",
        f"- position_ref: {env['options'].get('position_ref')}",
        "- limit = criterion with the smallest margin (value / threshold) at the first failure, else at the last OK step",
        "",
        "| param | nominal | last OK + % | last OK - % | first fail + | first fail - | limit + (margin) | limit - (margin) | feasible |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        ffp = "-" if r[4] == "-" else f"{r[4]} % {r[5]}"
        ffm = "-" if r[6] == "-" else f"{r[6]} % {r[7]}"
        md.append(f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} | {ffp} | {ffm} | {r[8]} ({r[9]}) | {r[10]} ({r[11]}) | {r[12]} .. {r[13]} |")
    return "\n".join(md) + "\n", buf.getvalue()
