"""``paicad shell selftest`` - site acceptance kit of the shell path (shell-morph section 5.2, GE section 5.3.1).

Runs on the real mid-surface STEP + assembly folder: extract -> fixed-scan -> tag -> nominal update / morph /
check -> (optional) variant update compared with ``--variant-cad`` -> short envelope, each into
``<out-dir>/work/<stage>/``, and writes ``selftest_report.json`` / ``.md`` with numbers only (counts,
ratios, distances, quality values): no CAD or mesh content, no coordinates, no node or element ids.
Exit code 0 when the report is written (stage failures are recorded in it).
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from pathlib import Path

import numpy as np

from ..common import EXIT_OK, OutDir, Reporter, StageReporter, dumps, rnd
from ..mesh.radioss import rewrite_nodes
from .common import shell_envelope

REPORT_JSON = "selftest_report.json"
REPORT_MD = "selftest_report.md"
WORK = "work"


def _read(p: Path) -> dict | None:
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def run(args, rep: Reporter) -> int:
    from ..cli import guarded, versions

    t0 = time.monotonic()
    out = OutDir(args.out_dir, [REPORT_JSON, REPORT_MD, WORK])
    out.prepare()
    work = Path(args.out_dir) / WORK
    work.mkdir(parents=True, exist_ok=True)
    common = dict(cmd="shell", options=args.options, threads=args.threads, _nested=True)
    stages: dict[str, dict] = {}

    def stage(name, verb, lo, hi, report, **kw):
        ns = argparse.Namespace(shell_cmd=verb, **common, **kw)
        srep = StageReporter(Path(ns.out_dir), rep, name, lo, hi)
        try:
            code, err, _ = guarded(ns, srep)
        finally:
            srep.close()
        d = _read(Path(ns.out_dir) / report) if report else None
        stages[name] = {"exit_code": code, "status": (d or {}).get("status") or ("OK" if code == 0 else "FAIL"), "code": (d or {}).get("code") or err}
        return d

    ex, fx, tg = work / "extract", work / "fixed", work / "tag"
    feats = ex / "shell_features.json"
    stage("extract", "extract", 0, 15, None, cad=args.cad, out_dir=str(ex), assem_dir=args.assem_dir, body_map=args.body_map, no_png=True)
    fdoc = _read(feats) if stages["extract"]["exit_code"] == 0 else None
    sdoc = tdoc = cdoc = env = None
    variant = None
    if fdoc:
        sdoc = stage("fixed_scan", "fixed-scan", 15, 22, "shell_scan.json", assem_dir=args.assem_dir, out_dir=str(fx), parts=None, features=str(feats))
    if stages.get("fixed_scan", {}).get("exit_code") == 0:
        tdoc = stage("tag", "tag", 22, 40, "shell_tag.json", cad=args.cad, features=str(feats), assem_dir=args.assem_dir, fixed_dir=str(fx), out_dir=str(tg), body_map=args.body_map)
    roundtrip = {"writer_byte_identical": None, "nominal_files_written": None}
    if fdoc:
        from .assem import read_assembly

        asm = read_assembly(args.assem_dir)
        ok = True
        for rel in asm.rels:
            data = (asm.root / rel).read_bytes()
            ok &= rewrite_nodes(data, {}) == data
        roundtrip["writer_byte_identical"] = bool(ok)
    if stages.get("tag", {}).get("exit_code") == 0:
        vals = work / "values_nominal.json"
        vals.write_text(json.dumps({"schema_version": 1, "values": {}}), encoding="utf-8")
        upd, mor, chk = work / "update_nominal", work / "morph_nominal", work / "check_nominal"
        stage("update", "update", 40, 48, "shell_update.json", cad=args.cad, features=str(feats), values=str(vals), out_dir=str(upd), fixed_dir=str(fx), body_map=args.body_map)
        if stages["update"]["exit_code"] == 0:
            md = stage("morph", "morph", 48, 56, "shell_morph.json", assem_dir=args.assem_dir, tag_dir=str(tg), fixed_dir=str(fx), features=str(feats), update_dir=str(upd),
                       out_dir=str(mor), solver=None, sweep=False)
            if md:
                roundtrip["nominal_files_written"] = len(md.get("files") or [])
        if stages.get("morph", {}).get("exit_code") == 0:
            cdoc = stage("check", "check", 56, 64, "shell_check.json", assem_dir=args.assem_dir, morph_dir=str(mor), update_dir=str(upd), tag_dir=str(tg), fixed_dir=str(fx),
                         features=str(feats), values=str(vals), out_dir=str(chk), out_files_dir=str(work / "check_nominal_files"), thickness=None)
        if args.variant_cad and args.variant_values and stages["update"]["exit_code"] == 0:
            variant = _variant(args, work, feats, fx, stage)
        if not args.no_envelope and stages.get("check", {}).get("exit_code") == 0:
            sw = work / "envelope"
            stage("envelope", "morph", 72, 98, None, assem_dir=args.assem_dir, tag_dir=str(tg), fixed_dir=str(fx), features=str(feats), update_dir=str(upd), out_dir=str(sw),
                  solver=None, sweep=True, steps=args.envelope_steps, pos_steps=args.envelope_pos_steps, params=args.envelope_params, stop_after_fail=args.stop_after_fail,
                  check="on", keep_steps=False)
            env = _read(sw / "envelope.json")
    report = shell_envelope(
        status="OK", versions=versions(), stages=stages,
        extract=_extract_summary(fdoc), fixed=_fixed_summary(sdoc), tag=_tag_summary(tdoc), roundtrip=roundtrip,
        nominal_check=_check_summary(cdoc), variant=variant, envelope=_envelope_summary(env), elapsed_s=rnd(time.monotonic() - t0, 3),
    )
    out.write_text(REPORT_JSON, dumps(report))
    out.write_text(REPORT_MD, render_md(report))
    out.commit([REPORT_JSON, REPORT_MD])
    rep.progress(100, "shell selftest report written")
    rep.result("OK", None, REPORT_JSON)
    return EXIT_OK


def _variant(args, work: Path, feats: Path, fx: Path, stage) -> dict:
    """update with the site values, then distances sample B-rep <-> site variant STEP on the changed faces."""
    from ..update import read_json
    from .cad import load, load_sample

    upd = work / "update_variant"
    d = stage("variant_update", "update", 64, 72, "shell_update.json", cad=args.cad, features=str(feats), values=args.variant_values, out_dir=str(upd), fixed_dir=None, body_map=args.body_map)
    out = {"update_status": (d or {}).get("status"), "update_code": (d or {}).get("code")}
    if not d or d.get("status") != "OK":
        return out
    try:
        var = load(args.variant_cad)
        fdoc = read_json(feats, "features")
        names = [p["body"] for p in fdoc["parts"]]
        sample = {b.name: b for b in load_sample(upd / "sample.brep", names)}
        faces = []
        for body, ch in (d.get("changed") or {}).items():
            vb = var.by_name().get(body)
            sb = sample.get(body)
            if vb is None or sb is None:
                out["error"] = "variant body names differ"
                return out
            if vb.summary().n_faces != sb.summary().n_faces:
                out["error"] = "variant topology differs (face count)"
                return out
            for fid in sorted({int(x[1:]) for x in ch.get("geometry", []) + ch.get("boundary_only", [])}):
                pts = sb.sample_face(fid, 10)
                dist, _, _, _ = vb.project_to_face(fid, pts) if len(pts) else (np.zeros(0), None, None, None)
                a0, a1 = sb.topology().face(fid).area, vb.topology().face(fid).area
                faces.append({"max_mm": rnd(float(dist.max()) if len(dist) else 0.0), "area_rel": rnd(abs(a0 - a1) / a1 if a1 else 0.0)})
        out["faces"] = len(faces)
        out["max_distance_mm"] = max((f["max_mm"] for f in faces), default=0.0)
        out["max_area_rel"] = max((f["area_rel"] for f in faces), default=0.0)
    except Exception as ex:  # noqa: BLE001 - recorded, never fails the report
        out["error"] = f"{ex.__class__.__name__}: {ex}"
    return out


def _extract_summary(d):
    if not d:
        return None
    return {"parts": len(d.get("parts") or []), "beads": len(d.get("beads") or []), "features": len(d.get("features") or []),
            "shapes": dict(Counter(b["shape"] for b in d.get("beads") or [])), "senses": dict(Counter(b["sense"] for b in d.get("beads") or [])),
            "fixed_overlap": dict(Counter(b["fixed_overlap"] for b in d.get("beads") or [])), "warnings": dict(Counter(w.get("code") for w in d.get("warnings") or []))}


def _fixed_summary(d):
    if not d or not d.get("fixed"):
        return None
    f = d["fixed"]
    return {"status": d.get("status"), "total": f.get("total"), "by_kind": f.get("by_kind"), "clusters": len(f.get("clusters") or []), "warnings": dict(Counter(w.get("code") for w in d.get("warnings") or []))}


def _tag_summary(d):
    if not d:
        return None
    parts = d.get("parts") or []
    return {"status": d.get("status"), "match_ratio": d.get("match_ratio"), "nodes": sum(p.get("nodes", 0) for p in parts),
            "elements": {"quad": sum(p["elements"]["quad"] for p in parts), "tri": sum(p["elements"]["tri"] for p in parts)} if parts else None,
            "unmatched": sum(p["classified"]["unmatched"] for p in parts), "fixed": sum(p.get("fixed", 0) for p in parts),
            "dist_max_mm": max((p["dist_mm"]["max"] for p in parts), default=None), "warnings": dict(Counter(w.get("code") for w in d.get("warnings") or []))}


def _check_summary(d):
    if not d:
        return None
    c = d.get("checks") or {}
    q = c.get("quality") or {}
    return {"status": d.get("status"), "code": d.get("code"), "out_files": len(d.get("out_files") or []), "deviation_max_mm": (c.get("deviation") or {}).get("max_mm"),
            "quality": {k: q.get(k) for k in ("baseline_status", "baseline_max_warpage_deg", "baseline_max_skew_deg", "baseline_max_aspect", "baseline_min_jacobian", "baseline_min_edge_mm")},
            "tie": (c.get("tie") or {}).get("status"), "warnings": dict(Counter(w.get("code") for w in d.get("warnings") or []))}


def _envelope_summary(env):
    if not env:
        return None
    return [{"param": s["param"], "unit": s["unit"], "last_ok": s["last_ok"], "first_fail_code": s["first_fail_code"], "limited_by": s.get("limited_by")} for s in env.get("summary") or []]


def render_md(r: dict) -> str:
    def v(x):
        return "-" if x is None else str(x)

    lines = ["# paicad shell selftest", "", f"- engine_version: {r['engine_version']}", ""]
    lines += ["## Stages", "", "| stage | status | code |", "|---|---|---|"]
    for k, s in r["stages"].items():
        lines.append(f"| {k} | {s['status']} | {v(s['code'])} |")
    for key, title in (("extract", "Extract"), ("fixed", "Fixed set"), ("tag", "Tag"), ("roundtrip", "Unchanged round trip"), ("nominal_check", "Nominal check"), ("variant", "Variant comparison")):
        lines += ["", f"## {title}", ""]
        d = r.get(key)
        if not d:
            lines.append("- not evaluated")
            continue
        for k, x in d.items():
            lines.append(f"- {k}: {v(x)}")
    lines += ["", "## Envelope", ""]
    if not r.get("envelope"):
        lines.append("- not evaluated")
    else:
        lines += ["| param | unit | last OK + | last OK - | first fail + | first fail - |", "|---|---|---|---|---|---|"]
        for s in r["envelope"]:
            lines.append(f"| {s['param']} | {s['unit']} | {s['last_ok']['+']} | {s['last_ok']['-']} | {v(s['first_fail_code']['+'])} | {v(s['first_fail_code']['-'])} |")
    return "\n".join(lines) + "\n"
