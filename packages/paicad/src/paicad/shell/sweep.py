"""``paicad shell morph --sweep`` - shell morphing envelope (shell-morph section 7.1, GE section 11.2).

Per parameter and direction: update -> morph -> check (fixed, param, deviation, quality) in memory, depth /
width in % of the nominal value (``--steps``, depth rows also carry ``delta_mm``), positions in mm
(``--pos-steps``), stop after ``--stop-after-fail`` consecutive failures. A first failure
SHELL_FIXED_REGION_VIOLATION marks the summary ``limited_by: "fixed"``. The nominal sheet is the
``sample.brep`` of ``--update-dir`` (all values nominal). Outputs (deterministic, no timestamps):
``envelope.json`` (schema_version 2, ``kind: shell``), ``envelope.csv``, ``report_envelope.md`` / ``.csv`` and a
``shell_features.json`` copy with ``feasible`` from the envelope.
"""

from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
import math
from pathlib import Path

import numpy as np

from .. import __version__
from ..common import CODE_CATEGORY, EXIT_CAD, EXIT_OK, OutDir, PaicadError, Reporter, dumps, rnd, sha256_file
from ..envreport import REPORT_CSV, REPORT_MD, _lab, _pct
from ..sweep import _steps, step_label
from . import opts as shopts
from .check import check_core
from .common import POSITION_TYPES, nominal_of, param_keys, shell_envelope
from .morph import MorphFailed, load_inputs, morph_core
from .update import SAMPLE_BREP, update_core

ENVELOPE_JSON = "envelope.json"
ENVELOPE_CSV = "envelope.csv"
FEATURES_JSON = "shell_features.json"
ENVELOPE_SCHEMA_VERSION = 2
CSV_COLUMNS = ("param", "direction", "step", "unit", "pct", "value", "delta_mm", "status", "fail_code", "max_warpage_deg", "max_skew_deg", "max_aspect",
               "min_jacobian", "edge_ratio", "dt_ratio", "boundary_dev_max_mm", "param_remeasure_err_abs", "param_remeasure_err_rel", "inverted_elems")
REPORT_COLUMNS = ("param", "nominal", "unit", "last_ok_plus", "last_ok_minus", "first_fail_plus", "first_fail_code_plus", "first_fail_minus", "first_fail_code_minus",
                  "limited_by_plus", "limited_by_minus", "limit_metric_plus", "limit_margin_plus", "limit_metric_minus", "limit_margin_minus", "feasible_min", "feasible_max")


def margins(row: dict, o: dict) -> dict[str, float]:
    q, dv = o["quality"], o["deviation"]
    out: dict[str, float] = {}
    if row.get("inverted_elems") is not None:
        out["inverted"] = 0.0 if row["inverted_elems"] else math.inf
    qm = row.get("quality_margins") or {}
    for k, mk in (("max_warpage_deg", "warpage"), ("max_skew_deg", "skew"), ("max_aspect", "aspect"), ("min_jacobian", "jacobian")):
        if row.get(k) is not None:
            out[k] = math.inf if qm.get(mk) is None else float(qm[mk])  # per-element margin (relative limits for baseline-bad elements)
    for k, lim, kind in (("edge_ratio", q["min_edge_ratio"], "min"), ("dt_ratio", q["dt_ratio_min"], "min")):
        v = row.get(k)
        if v is None:
            continue
        out[k] = (float(lim) / v if v > 0 else math.inf) if kind == "max" else v / float(lim)
    d = row.get("boundary_dev_max_mm")
    if d is not None:
        out["boundary_dev"] = float(dv["boundary_max_mm"]) / d if d > 0 else math.inf
    if (row.get("param_remeasure_err") or {}).get("abs") is not None:
        out["param_remeasure"] = math.inf if row.get("param_margin") is None else float(row["param_margin"])
    return out


def limit_metric(rows: list[dict], o: dict) -> dict:
    if not rows:
        return {"metric": None, "margin": None, "at": None, "unit": None, "source": None}
    ff = next((r for r in rows if r["status"] == "FAIL"), None)
    row = ff or rows[-1]
    m = margins(row, o)
    at = {"at": row["step"], "unit": row["unit"]}
    if ff is not None and (not m or ff["fail_code"] in ("SHELL_FIXED_REGION_VIOLATION", "GEOM_FEATURE_COLLISION", "GEOM_CAD_FAILED", "GEOM_TOPOLOGY_CHANGED", "GEOM_MORPH_FAILED")):
        return {"metric": ff["fail_code"], "margin": None, **at, "source": "first_fail"}
    if not m:
        return {"metric": None, "margin": None, **at, "source": "last_ok"}
    name = min(sorted(m), key=lambda k: m[k])
    v = m[name]
    return {"metric": name, "margin": round(v, 4) if math.isfinite(v) else None, **at, "source": "first_fail" if ff is not None else "last_ok"}


def _row(p, d, st, unit, value, delta):
    return {"param": p, "direction": d, "step": st, "unit": unit, "pct": st if unit == "%" else None, "value": rnd(value, 9), "delta_mm": None if delta is None else rnd(delta, 9),
            "status": "OK", "fail_code": None, "max_warpage_deg": None, "max_skew_deg": None, "max_aspect": None, "min_jacobian": None, "edge_ratio": None, "dt_ratio": None,
            "boundary_dev_max_mm": None, "param_remeasure_err": {"abs": None, "rel": None}, "param_margin": None, "quality_margins": None, "inverted_elems": None}


def run(args, rep: Reporter) -> int:
    o = shopts.load(args.options)
    out = OutDir(args.out_dir, [ENVELOPE_JSON, ENVELOPE_CSV, FEATURES_JSON, REPORT_MD, REPORT_CSV] + (["sweep"] if args.keep_steps else []))
    out.prepare()
    steps = _steps(args.steps)
    pos_steps = _steps(args.pos_steps, "--pos-steps")
    if args.stop_after_fail < 1:
        raise PaicadError("GEOM_INPUT_INVALID", "--stop-after-fail must be >= 1")
    rep.progress(2, "reading inputs")
    doc, tag_doc, fixed, asm, u, samples, meshes = load_inputs(args, o)
    keys = param_keys(doc, o)
    params = [x.strip() for x in args.params.split(",") if x.strip()] if args.params else list(keys)
    unknown = [x for x in params if x not in keys]
    if unknown:
        raise PaicadError("GEOM_INPUT_INVALID", f"--params: unknown parameter names: {', '.join(unknown[:10])}")
    nominal = {k: nominal_of(doc, k) for k in keys}
    given = u.get("values") or {}
    if any(abs(float(given.get(k, nominal[k])) - nominal[k]) > 0 for k in keys):
        raise PaicadError("GEOM_INPUT_INVALID", "--update-dir must hold the nominal shell update (all values nominal) for --sweep")
    type_of = {f["name"]: f["type"] for f in doc["features"]}
    unit_of = {k: "mm" if type_of[k] in POSITION_TYPES else "%" for k in params}
    bodies = [samples[p["body"]] for p in doc["parts"]]
    tag_dist = {m.index: np.zeros(len(m.node_ids)) for m in meshes}
    sweep_id = _sweep_id(args, o, steps, pos_steps, params)
    rows: list[dict] = []
    keep: list[str] = []
    total = max(1, sum(2 * len(pos_steps if unit_of[p] == "mm" else steps) for p in params))
    done = 0
    for p in params:
        nom = nominal[p]
        unit = unit_of[p]
        for sign, dl in ((1, "+"), (-1, "-")):
            fails = 0
            for st in pos_steps if unit == "mm" else steps:
                done += 1
                value = nom + sign * st if unit == "mm" else nom * (1.0 + sign * st / 100.0)
                rep.progress(5 + int(90 * done / total), f"sweep {p} {dl}{step_label(st, unit)}")
                vals = dict(nominal)
                vals[p] = value
                row = _row(p, dl, st, unit, value, value - nom if type_of[p] == "BEAD_DEPTH" else None)
                _step(row, vals, bodies, doc, o, fixed, meshes, samples, asm, tag_dist, args.check == "on", out, keep, f"sweep/{p}/{dl}{_pct(st)}{'mm' if unit == 'mm' else ''}" if args.keep_steps else None)
                rows.append(row)
                if row["status"] == "FAIL":
                    fails += 1
                    if fails >= args.stop_after_fail:
                        break
                else:
                    fails = 0
    summary = _summary(params, rows, nominal, unit_of)
    for s in summary:
        s["limit_metric"] = {d: limit_metric([r for r in rows if r["param"] == s["param"] and r["direction"] == d], o) for d in ("+", "-")}
    env = shell_envelope(
        schema_version=ENVELOPE_SCHEMA_VERSION, sweep_id=sweep_id,
        inputs={"features_sha256": sha256_file(args.features), "assem_digest": asm.digest(), "nominal_brep_sha256": sha256_file(Path(args.update_dir) / SAMPLE_BREP)},
        steps_pct=steps, pos_steps_mm=pos_steps, stop_after_fail=args.stop_after_fail, check=args.check == "on", options=shopts.used(o), rows=rows, summary=summary,
    )
    out.write_text(ENVELOPE_JSON, dumps(env))
    out.write_text(ENVELOPE_CSV, _csv(rows))
    out.write_text(FEATURES_JSON, dumps(_features_with_envelope(doc, summary, sweep_id, o)))
    md, rcsv = render(env)
    out.write_text(REPORT_MD, md)
    out.write_text(REPORT_CSV, rcsv)
    out.commit(keep + [FEATURES_JSON, REPORT_CSV, REPORT_MD, ENVELOPE_CSV, ENVELOPE_JSON])
    rep.progress(100, f"shell sweep done: {len(rows)} steps, {sum(1 for r in rows if r['status'] == 'FAIL')} failed")
    rep.result("OK", None, ENVELOPE_JSON)
    return EXIT_OK


def _step(row, vals, bodies, doc, o, fixed, meshes, samples, asm, tag_dist, check_on, out: OutDir, keep, sub) -> None:
    try:
        res = update_core(bodies, doc, vals, o, fixed)
    except PaicadError as e:
        if e.exit_code != EXIT_CAD:
            raise
        row.update(status="FAIL", fail_code=e.code)
        if sub:
            out.write_text(f"{sub}/shell_update.json", dumps(shell_envelope(status="FAIL", code=e.code, category=CODE_CATEGORY.get(e.code), message=e.message, values=vals, **(e.detail or {}))))
            keep.append(f"{sub}/shell_update.json")
        return
    sample = {b.name: b for b in res.bodies}
    udoc = {"changed": res.changed, "beads": res.beads}
    try:
        m = morph_core(meshes, sample, udoc, o)
    except MorphFailed as e:
        row.update(status="FAIL", fail_code=e.code)
        return
    if sub:
        out.write_text(f"{sub}/shell_morph.json", dumps(shell_envelope(status="OK", code=None, category=None, message=None, max_disp_mm=rnd(m.max_disp), parts=m.parts)))
        keep.append(f"{sub}/shell_morph.json")
    if not check_on:
        return
    c = check_core(meshes, m.xyz, sample, doc, vals, res.expected, res.changed, o, None, {}, {"dist_of": tag_dist}, None, full=False)
    s = c.summary
    row.update(status="OK" if c.status == "PASS" else "FAIL", fail_code=c.code, max_warpage_deg=s["max_warpage_deg"], max_skew_deg=s["max_skew_deg"], max_aspect=s["max_aspect"],
               min_jacobian=s["min_jacobian"], edge_ratio=s["edge_ratio"], dt_ratio=s["dt_ratio"], boundary_dev_max_mm=s["boundary_dev_max_mm"],
               param_remeasure_err=s["param_remeasure_err"], param_margin=s["param_margin"], quality_margins=s["quality_margins"], inverted_elems=s["inverted_elems"])
    if sub:
        out.write_text(f"{sub}/shell_check.json", dumps(shell_envelope(status=c.status, code=c.code, category=CODE_CATEGORY.get(c.code) if c.code else None, message=c.message, checks=c.checks)))
        keep.append(f"{sub}/shell_check.json")


def _sweep_id(args, o, steps, pos_steps, params) -> str:
    h = hashlib.sha256()
    for path in (args.features, Path(args.update_dir) / SAMPLE_BREP, Path(args.tag_dir) / "shell_tag.json", Path(args.fixed_dir) / "shell_scan.json"):
        h.update(sha256_file(path).encode())
    h.update(json.dumps({"opts": o, "steps": steps, "pos_steps_mm": pos_steps, "params": params, "stop": args.stop_after_fail, "check": args.check}, sort_keys=True).encode())
    return "S-" + h.hexdigest()[:12]


def _summary(params, rows, nominal, unit_of) -> list[dict]:
    out = []
    for p in params:
        unit = unit_of[p]
        s = {"param": p, "nominal": nominal[p], "unit": unit, "last_ok": {}, "first_fail": {}, "first_fail_code": {}, "last_ok_label": {}, "first_fail_label": {}, "limited_by": {}}
        for d in ("+", "-"):
            rr = [r for r in rows if r["param"] == p and r["direction"] == d]
            last, ff, fc = 0.0, None, None
            for r in rr:
                if r["status"] == "FAIL":
                    ff, fc = r["step"], r["fail_code"]
                    break
                last = r["step"]
            s["last_ok"][d], s["first_fail"][d], s["first_fail_code"][d] = last, ff, fc
            s["last_ok_label"][d], s["first_fail_label"][d] = step_label(last, unit), step_label(ff, unit)
            s["limited_by"][d] = "fixed" if fc == "SHELL_FIXED_REGION_VIOLATION" else None
        pct = unit == "%"
        s["last_ok_pct"] = dict(s["last_ok"]) if pct else {"+": None, "-": None}
        s["first_fail_pct"] = dict(s["first_fail"]) if pct else {"+": None, "-": None}
        a, b = _bounds(nominal[p], s)
        s["feasible"] = {"min": rnd(min(a, b)), "max": rnd(max(a, b))}
        out.append(s)
    return out


def _bounds(nom, s):
    if s["unit"] == "mm":
        return nom + s["last_ok"]["+"], nom - s["last_ok"]["-"]
    return nom * (1 + s["last_ok"]["+"] / 100.0), nom * (1 - s["last_ok"]["-"] / 100.0)


def _features_with_envelope(doc, summary, sweep_id, o) -> dict:
    new = copy.deepcopy(doc)
    split = set(o.get("symmetry_split") or [])
    rep_of = {}
    for g in new.get("groups") or []:
        if g["id"] not in split:
            for m in g["members"]:
                rep_of[m] = g["parameter"]
    by = {s["param"]: s for s in summary}
    for f in new["features"]:
        s = by.get(rep_of.get(f["name"], f["name"]))
        if s is None:
            fe = dict(f.get("feasible") or {})
            fe["source"] = "estimate"
            f["feasible"] = fe
            continue
        a, b = _bounds(float(f["nominal"]), s)
        lim = "fixed" if "fixed" in s["limited_by"].values() else None
        f["feasible"] = {"min": rnd(min(a, b)), "max": rnd(max(a, b)), "limited_by": lim, "first_fail_code": dict(s["first_fail_code"]), "source": "envelope", "sweep_id": sweep_id}
    new["engine_version"] = __version__
    return new


def _c(x) -> str:
    return "" if x is None else repr(x)


def _csv(rows) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(CSV_COLUMNS)
    for r in rows:
        e = r["param_remeasure_err"] or {}
        w.writerow([r["param"], r["direction"], _pct(r["step"]), r["unit"], "" if r["pct"] is None else _pct(r["pct"]), repr(r["value"]), _c(r["delta_mm"]), r["status"], r["fail_code"] or "",
                    _c(r["max_warpage_deg"]), _c(r["max_skew_deg"]), _c(r["max_aspect"]), _c(r["min_jacobian"]), _c(r["edge_ratio"]), _c(r["dt_ratio"]),
                    _c(r["boundary_dev_max_mm"]), _c(e.get("abs")), _c(e.get("rel")), "" if r["inverted_elems"] is None else r["inverted_elems"]])
    return buf.getvalue()


def render(env: dict) -> tuple[str, str]:
    rows = []
    for s in env["summary"]:
        u = s["unit"]
        lm = s.get("limit_metric") or {}

        def mm(d):
            x = lm.get(d) or {}
            return x.get("metric") or "-", "-" if x.get("margin") is None else repr(x["margin"])

        mp, gp = mm("+")
        mn, gn = mm("-")
        rows.append([s["param"], repr(float(s["nominal"])), u, _lab(s["last_ok"]["+"], u), _lab(s["last_ok"]["-"], u), _lab(s["first_fail"]["+"], u), s["first_fail_code"]["+"] or "-",
                     _lab(s["first_fail"]["-"], u), s["first_fail_code"]["-"] or "-", s["limited_by"]["+"] or "-", s["limited_by"]["-"] or "-", mp, gp, mn, gn,
                     repr(s["feasible"]["min"]), repr(s["feasible"]["max"])])
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(REPORT_COLUMNS)
    w.writerows(rows)
    q = env["options"]["quality"]
    md = [
        "# Shell morphing envelope report",
        "",
        f"- schema_version: {env.get('schema_version')}",
        f"- engine_version: {env['engine_version']}",
        f"- sweep_id: {env['sweep_id']}",
        f"- steps, depth / width (% of nominal, each direction): {', '.join(_pct(x) for x in env['steps_pct'])}",
        f"- steps, position (mm from nominal, each direction): {', '.join(_pct(x) for x in env['pos_steps_mm'])}",
        f"- stop a direction after {env['stop_after_fail']} consecutive failures",
        f"- quality: max_warpage_deg {q['max_warpage_deg']}, max_skew_deg {q['max_skew_deg']}, max_aspect {q['max_aspect']}, min_jacobian {q['min_jacobian']}, "
        f"min_edge_ratio {q['min_edge_ratio']}, dt_ratio_min {q['dt_ratio_min']}, relative_to_baseline {q['relative_to_baseline']}",
        f"- bead: depth_mode {env['options']['bead']['depth_mode']}, position_ref {env['options']['bead']['position_ref']}; fixed transition_mm {env['options']['fixed']['transition_mm']}",
        "- limit = criterion with the smallest margin (value / threshold) at the first failure, else at the last OK step; limited by 'fixed' = first failure SHELL_FIXED_REGION_VIOLATION",
        "",
        "| param | nominal | unit | last OK + | last OK - | first fail + | first fail - | limit + (margin) | limit - (margin) | feasible |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        ffp = "-" if r[5] == "-" else f"{r[5]} {r[6]}"
        ffm = "-" if r[7] == "-" else f"{r[7]} {r[8]}"
        md.append(f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} | {r[4]} | {ffp} | {ffm} | {r[11]} ({r[12]}) | {r[13]} ({r[14]}) | {r[15]} .. {r[16]} |")
    return "\n".join(md) + "\n", buf.getvalue()
