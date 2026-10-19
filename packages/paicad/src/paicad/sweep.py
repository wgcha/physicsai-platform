"""``paicad morph --sweep`` - morphing envelope (contract sections 5.3, 11.2).

For every parameter (values.json key; others nominal) and each direction, the steps run
update -> morph -> check (a)(b)(c) in memory, stopping a direction after ``--stop-after-fail``
consecutive failures. Dimension parameters step in % of the nominal value (``--steps``, default
5,10,20,30,40,50); position parameters (HOLE_POS_U/V) step in absolute mm (``--pos-steps``, default
1,2,3,5,8,10). Every row / summary carries its ``unit`` ("%" or "mm"). The nominal geometry is the
``sample.brep`` of ``--update-dir``, which must be an update run with all values nominal.

Outputs (``--out-dir``): ``envelope.json``, ``envelope.csv``, ``report_envelope.md``/``.csv`` (per-parameter
last_ok / first_fail and the limiting metric) and ``parameter_features.json`` (copy of
the input with ``feasible`` from the envelope: ``source: envelope`` + ``sweep_id``; unswept features
keep the extract estimate with ``source: estimate``). Per-step files only with ``--keep-steps``.
Output is deterministic (no timestamps): the same inputs give byte-identical files.
"""

from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
import math
from pathlib import Path

from . import envreport, options
from .features import POSITION_TYPES
from .check import check_core
from .common import CODE_CATEGORY, EXIT_CAD, EXIT_OK, OutDir, PaicadError, Reporter, dumps, envelope, rnd, sha256_file
from .kernel import CadInputError, load_brep, save_brep
from .meshdata import components_from_tag, load_tag
from .morph import MORPH_JSON, MORPHED_INC, MorphFailed, SampleSet, morph_core, read_baseline, write_morphed
from .update import FACE_MAP_JSON, SAMPLE_BREP, UPDATE_JSON, _nominal, contacts_from_tag, load_features, param_keys, read_json, update_core

ENVELOPE_JSON = "envelope.json"
ENVELOPE_CSV = "envelope.csv"
FEATURES_JSON = "parameter_features.json"
# envelope.json format version (0.5.0: row key min_edge_ratio -> edge_ratio, same name as check.json)
ENVELOPE_SCHEMA_VERSION = 2
CSV_COLUMNS = (
    "param",
    "direction",
    "step",
    "unit",
    "pct",
    "value",
    "status",
    "fail_code",
    "min_stretch",
    "max_aspect",
    "edge_ratio",
    "dt_ratio",
    "boundary_dev_max_mm",
    "param_remeasure_err_abs",
    "param_remeasure_err_rel",
    "inverted_elems",
)


DEFAULT_POS_STEPS_MM = "1,2,3,5,8,10"


def _steps(text: str, arg: str = "--steps") -> list[float]:
    try:
        vals = sorted({float(x) for x in str(text).split(",") if x.strip()})
    except ValueError:
        raise PaicadError("GEOM_INPUT_INVALID", f"{arg} must be comma-separated numbers: {text!r}") from None
    if not vals or any(not (v > 0 and math.isfinite(v)) for v in vals):
        raise PaicadError("GEOM_INPUT_INVALID", f"{arg} must be positive numbers")
    return vals


def step_label(step: float, unit: str) -> str:
    """'20 %' / '3 mm' (None -> '-')."""
    if step is None:
        return "-"
    return f"{_pct_label(step)} {unit}"


def _pct_label(p: float) -> str:
    return str(int(p)) if float(p).is_integer() else repr(float(p))


def run(args, rep: Reporter) -> int:
    opts = options.load(args.options)
    outs = [ENVELOPE_JSON, ENVELOPE_CSV, FEATURES_JSON, envreport.REPORT_MD, envreport.REPORT_CSV]
    out = OutDir(args.out_dir, outs + (["sweep"] if args.keep_steps else []))
    out.prepare()
    doc = load_features(args.features)
    steps = _steps(args.steps)
    pos_steps = _steps(getattr(args, "pos_steps", None) or DEFAULT_POS_STEPS_MM, "--pos-steps")
    if args.stop_after_fail < 1:
        raise PaicadError("GEOM_INPUT_INVALID", "--stop-after-fail must be >= 1")
    keys = param_keys(doc, opts)
    params = [p.strip() for p in args.params.split(",") if p.strip()] if args.params else list(keys)
    unknown = [p for p in params if p not in keys]
    if unknown:
        raise PaicadError("GEOM_INPUT_INVALID", f"--params: unknown parameter names: {', '.join(unknown[:10])}")
    nominal_vals = {k: _nominal(doc, k) for k in keys}
    type_of = {f["name"]: f["type"] for f in doc["features"]}
    unit_of = {k: "mm" if type_of.get(k) in POSITION_TYPES else "%" for k in params}
    rep.progress(2, "reading baseline, tag and nominal B-rep")
    base_bytes, mesh = read_baseline(args.baseline_inc)
    tag = load_tag(args.tag_dir)
    comps = components_from_tag(mesh, tag)
    contacts = contacts_from_tag(args.tag_dir, doc)
    ud = Path(args.update_dir)
    u = read_json(ud / UPDATE_JSON, "update.json")
    if u.get("status") != "OK":
        raise PaicadError("GEOM_INPUT_INVALID", "update.json status is not OK")
    given = u.get("values") or {}
    if any(abs(float(given.get(k, nominal_vals[k])) - nominal_vals[k]) > 0 for k in keys):
        raise PaicadError("GEOM_INPUT_INVALID", "--update-dir must hold the nominal update (all values nominal) for --sweep")
    names = [b["body"] for b in doc["bodies"]]
    try:
        nominal = load_brep(ud / SAMPLE_BREP, names)
    except CadInputError as e:
        raise PaicadError(e.code, e.message) from None
    sweep_id = _sweep_id(args, opts, steps, params, pos_steps)
    check_on = args.check == "on"
    rows: list[dict] = []
    keep: list[str] = []
    total = max(1, sum(2 * len(pos_steps if unit_of[p] == "mm" else steps) for p in params))
    done = 0
    for p in params:
        nom = nominal_vals[p]
        unit = unit_of[p]
        for sign, dlabel in ((1, "+"), (-1, "-")):
            consecutive = 0
            for st in pos_steps if unit == "mm" else steps:
                done += 1
                value = nom + sign * st if unit == "mm" else nom * (1.0 + sign * st / 100.0)
                rep.progress(5 + int(90 * done / total), f"sweep {p} {dlabel}{step_label(st, unit)}")
                vals = dict(nominal_vals)
                vals[p] = value
                sub = f"sweep/{p}/{dlabel}{_pct_label(st)}{'mm' if unit == 'mm' else ''}" if args.keep_steps else None
                row = _step(p, dlabel, st, unit, value, vals, nominal, doc, contacts, opts, mesh, base_bytes, comps, Path(args.baseline_inc), check_on, out, sub, keep)
                rows.append(row)
                if row["status"] == "FAIL":
                    consecutive += 1
                    if consecutive >= args.stop_after_fail:
                        break
                else:
                    consecutive = 0
    summary = _summary(params, rows, nominal_vals, unit_of)
    for srow in summary:
        srow["limit_metric"] = {d: envreport.limit_metric([r for r in rows if r["param"] == srow["param"] and r["direction"] == d], opts) for d in ("+", "-")}
    env = envelope(
        schema_version=ENVELOPE_SCHEMA_VERSION,
        sweep_id=sweep_id,
        inputs={
            "features_sha256": sha256_file(args.features),
            "baseline_sha256": sha256_file(args.baseline_inc),
            "nominal_brep_sha256": sha256_file(ud / SAMPLE_BREP),
        },
        steps_pct=steps,
        pos_steps_mm=pos_steps,
        stop_after_fail=args.stop_after_fail,
        check=check_on,
        options={k: v for k, v in opts.items() if k != "schema_version"},
        rows=rows,
        summary=summary,
    )
    out.write_text(ENVELOPE_JSON, dumps(env))
    out.write_text(ENVELOPE_CSV, _csv(rows))
    out.write_text(FEATURES_JSON, dumps(_features_with_envelope(doc, summary, sweep_id, opts)))
    md, rcsv = envreport.render(env)
    out.write_text(envreport.REPORT_MD, md)
    out.write_text(envreport.REPORT_CSV, rcsv)
    out.commit(keep + [FEATURES_JSON, envreport.REPORT_CSV, envreport.REPORT_MD, ENVELOPE_CSV, ENVELOPE_JSON])
    nfail = sum(1 for r in rows if r["status"] == "FAIL")
    rep.progress(100, f"sweep done: {len(rows)} steps, {nfail} failed")
    rep.result("OK", None, ENVELOPE_JSON)
    return EXIT_OK


def _sweep_id(args, opts: dict, steps: list[float], params: list[str], pos_steps: list[float]) -> str:
    h = hashlib.sha256()
    for path in (args.features, args.baseline_inc, Path(args.update_dir) / SAMPLE_BREP, Path(args.tag_dir) / "tag.json"):
        h.update(sha256_file(path).encode())
    h.update(json.dumps({"opts": opts, "steps": steps, "pos_steps_mm": pos_steps, "params": params, "stop": args.stop_after_fail, "check": args.check}, sort_keys=True).encode())
    return "S-" + h.hexdigest()[:12]


def _step(p, dlabel, st, unit, value, vals, nominal, doc, contacts, opts, mesh, base_bytes, comps, baseline_path, check_on, out: OutDir, sub, keep) -> dict:
    row = {
        "param": p,
        "direction": dlabel,
        "step": st,
        "unit": unit,
        "pct": st if unit == "%" else None,
        "value": rnd(value, 9),
        "status": "OK",
        "fail_code": None,
        "min_stretch": None,
        "max_aspect": None,
        "edge_ratio": None,
        "dt_ratio": None,
        "boundary_dev_max_mm": None,
        "param_remeasure_err": {"abs": None, "rel": None},
        "param_margin": None,
        "inverted_elems": None,
    }
    try:
        res = update_core(nominal, doc, vals, contacts, opts)
    except PaicadError as e:
        if e.exit_code != EXIT_CAD:
            raise
        row.update(status="FAIL", fail_code=e.code)
        if sub:
            _keep(out, keep, f"{sub}/{UPDATE_JSON}", dumps(envelope(status="FAIL", code=e.code, category=CODE_CATEGORY.get(e.code), message=e.message, values=vals, **(e.detail or {}))))
        return row
    uvf = {b: set(m.get("uv_fallback", [])) for b, m in res.face_map.items()}
    sample = SampleSet({b["body"]: x for b, x in zip(doc["bodies"], res.bodies)}, res.face_map, uvf)
    if sub:
        save_brep(res.bodies, out.tmp_path(f"{sub}/{SAMPLE_BREP}"))
        keep.append(f"{sub}/{SAMPLE_BREP}")
        _keep(out, keep, f"{sub}/{FACE_MAP_JSON}", dumps(res.face_map))
        _keep(out, keep, f"{sub}/{UPDATE_JSON}", dumps(envelope(status="OK", code=None, category=None, message=None, values=vals, applied=res.applied, topology=res.topology, positions=res.positions, warnings=res.warnings)))
    try:
        m = morph_core(mesh, comps, sample, opts)
    except MorphFailed as e:
        row.update(status="FAIL", fail_code=e.code)
        if sub:
            _keep(out, keep, f"{sub}/{MORPH_JSON}", dumps(envelope(status="FAIL", code=e.code, category=CODE_CATEGORY.get(e.code), message=e.message)))
        return row
    if sub:
        with open(out.tmp_path(f"{sub}/{MORPHED_INC}"), "wb") as f:
            f.write(write_morphed(base_bytes, mesh, m.moved))
        keep.append(f"{sub}/{MORPHED_INC}")
        _keep(out, keep, f"{sub}/{MORPH_JSON}", dumps(envelope(status="OK", code=None, category=None, message=None, max_disp_mm=rnd(m.max_disp), parts=m.parts)))
    if not check_on:
        return row
    expected = {e["name"]: float(e["expected_measured"]) for e in res.positions}
    c = check_core(mesh, m.xyz, comps, sample, doc, vals, opts, None, baseline_path, full=False, expected=expected)
    s = c.summary
    row.update(
        status="OK" if c.status == "PASS" else "FAIL",
        fail_code=c.code,
        min_stretch=s["min_stretch"],
        max_aspect=s["max_aspect"],
        edge_ratio=s["edge_ratio"],
        dt_ratio=s["dt_ratio"],
        boundary_dev_max_mm=s["boundary_dev_max_mm"],
        param_remeasure_err=s["param_remeasure_err"],
        param_margin=s["param_margin"],
        inverted_elems=s["inverted_elems"],
    )
    if sub:
        _keep(out, keep, f"{sub}/check.json", dumps(envelope(status=c.status, code=c.code, category=CODE_CATEGORY.get(c.code) if c.code else None, message=c.message, checks=c.checks, warnings=c.warnings)))
    return row


def _keep(out: OutDir, keep: list[str], rel: str, text: str) -> None:
    out.write_text(rel, text)
    keep.append(rel)


def _summary(params: list[str], rows: list[dict], nominal: dict[str, float], unit_of: dict[str, str]) -> list[dict]:
    """Per parameter: ``unit``, ``last_ok`` / ``first_fail`` (+/-, in that unit) with labels such as '3 mm'.

    ``last_ok_pct`` / ``first_fail_pct`` keep their 0.3.0 meaning for % parameters and are null for mm ones.
    """
    out = []
    for p in params:
        unit = unit_of[p]
        s = {"param": p, "nominal": nominal[p], "unit": unit, "last_ok": {}, "first_fail": {}, "first_fail_code": {}, "last_ok_label": {}, "first_fail_label": {}}
        for d in ("+", "-"):
            rr = [r for r in rows if r["param"] == p and r["direction"] == d]
            last_ok, ff, fc = 0.0, None, None
            for r in rr:
                if r["status"] == "FAIL":
                    ff, fc = r["step"], r["fail_code"]
                    break
                last_ok = r["step"]
            s["last_ok"][d] = last_ok
            s["first_fail"][d] = ff
            s["first_fail_code"][d] = fc
            s["last_ok_label"][d] = step_label(last_ok, unit)
            s["first_fail_label"][d] = step_label(ff, unit)
        pct = unit == "%"
        s["last_ok_pct"] = dict(s["last_ok"]) if pct else {"+": None, "-": None}
        s["first_fail_pct"] = dict(s["first_fail"]) if pct else {"+": None, "-": None}
        a, b = _bounds(nominal[p], s)
        s["feasible"] = {"min": rnd(min(a, b)), "max": rnd(max(a, b))}
        out.append(s)
    return out


def _bounds(nom: float, s: dict) -> tuple[float, float]:
    if s["unit"] == "mm":
        return nom + s["last_ok"]["+"], nom - s["last_ok"]["-"]
    return nom * (1.0 + s["last_ok"]["+"] / 100.0), nom * (1.0 - s["last_ok"]["-"] / 100.0)


def _features_with_envelope(doc: dict, summary: list[dict], sweep_id: str, opts: dict) -> dict:
    """Copy of parameter_features.json with feasible from the envelope (group members follow their representative)."""
    new = copy.deepcopy(doc)
    split = set(opts.get("symmetry_split") or [])
    rep_of = {}
    for g in new.get("groups") or []:
        if g["id"] not in split:
            for m in g["members"]:
                rep_of[m] = g["parameter"]
    by_param = {s["param"]: s for s in summary}
    for f in new["features"]:
        key = rep_of.get(f["name"], f["name"])
        s = by_param.get(key)
        old = dict(f.get("feasible") or {})
        if s is None:
            old["source"] = "estimate"
            f["feasible"] = old
            continue
        a, b = _bounds(float(f["nominal"]), s)
        f["feasible"] = {
            "min": rnd(min(a, b)),
            "max": rnd(max(a, b)),
            "limited_by": None,
            "first_fail_code": dict(s["first_fail_code"]),
            "source": "envelope",
            "sweep_id": sweep_id,
        }
    new["engine"] = "native"
    from . import __version__

    new["engine_version"] = __version__
    return new


def _csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(CSV_COLUMNS)
    for r in rows:
        e = r["param_remeasure_err"] or {}
        w.writerow(
            [
                r["param"],
                r["direction"],
                _pct_label(r["step"]),
                r["unit"],
                "" if r["pct"] is None else _pct_label(r["pct"]),
                repr(r["value"]),
                r["status"],
                r["fail_code"] or "",
                _c(r["min_stretch"]),
                _c(r["max_aspect"]),
                _c(r["edge_ratio"]),
                _c(r["dt_ratio"]),
                _c(r["boundary_dev_max_mm"]),
                _c(e.get("abs")),
                _c(e.get("rel")),
                "" if r["inverted_elems"] is None else r["inverted_elems"],
            ]
        )
    return buf.getvalue()


def _c(x) -> str:
    return "" if x is None else repr(x)
