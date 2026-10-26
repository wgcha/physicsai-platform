"""``paicad selftest`` - site acceptance kit, minimal version (contract section 9 stage 0 (b)).

Runs on the real nominal CAD + baseline include + assembly folder: extract -> tag -> nominal update ->
morph -> check -> short envelope, each into ``<out-dir>/work/<stage>/`` (site-local working files),
and writes ``selftest_report.json`` / ``selftest_report.md`` with **numbers only**: no CAD or mesh
content, no coordinates, no node or element ids (the report is what the user sends back).

Report sections: tag unclassified (unmatched) boundary nodes and match ratio, unchanged round trip
byte identity (writer and nominal morph), nominal check metrics, short envelope summary, and with
``--nx-samples <dir>`` the NX change sample comparison: per sample ``<name>.json`` (values.json, original
parameter names) + ``<name>.step`` (NX geometry with those values) -> update + morph (+ check) with the
values, then distance of the morphed boundary nodes to the NX STEP surface, distance of the native sample
B-rep to the NX surface, body volume difference and the parameter re-measurement error (numbers only).
Exit code 0 when the report is written (stage failures are recorded in it).
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from .common import (
    EXIT_OK,
    OutDir,
    PaicadError,
    Reporter,
    StageReporter,
    dumps,
    envelope,
    rnd,
    sha256_file,
)

REPORT_JSON = "selftest_report.json"
REPORT_MD = "selftest_report.md"
WORK = "work"


def _sha_input(p: Path) -> str | None:
    if p.is_file():
        return sha256_file(p)
    if p.is_dir():
        import hashlib

        h = hashlib.sha256()
        for f in sorted(x for x in p.rglob("*") if x.is_file()):
            h.update(f.relative_to(p).as_posix().encode())
            h.update(sha256_file(f).encode())
        return h.hexdigest()
    return None


def _read(p: Path) -> dict | None:
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def run(args, rep: Reporter) -> int:
    from .cli import guarded, versions
    from .mesh.radioss import rewrite_nodes

    t0 = time.monotonic()
    out = OutDir(args.out_dir, [REPORT_JSON, REPORT_MD, WORK])
    out.prepare()
    root = Path(args.out_dir)
    work = root / WORK
    work.mkdir(parents=True, exist_ok=True)
    common = dict(options=args.options, threads=args.threads, body_map=args.body_map, _nested=True)
    asm = bool(getattr(args, "asm_match", None))  # assembly match (asm-match.md AM-9): method M stage arguments
    msrc = dict(baseline_inc=args.baseline_inc, asm_match=getattr(args, "asm_match", None), cache_dir=getattr(args, "cache_dir", None))
    stages: dict[str, dict] = {}

    def stage(name: str, ns: argparse.Namespace, lo: int, hi: int, report: str | None, store: dict | None = None) -> dict | None:
        srep = StageReporter(Path(ns.out_dir), rep, name, lo, hi)
        try:
            code, err, _msg = guarded(ns, srep)
        finally:
            srep.close()
        d = _read(Path(ns.out_dir) / report) if report else None
        (stages if store is None else store)[name] = {"exit_code": code, "status": (d or {}).get("status") or ("OK" if code == 0 else "FAIL"), "code": (d or {}).get("code") or err}
        return d

    ex, tg = work / "extract", work / "tag"
    feats = ex / "parameter_features.json"
    stage("extract", argparse.Namespace(cmd="extract", cad=args.cad, out_dir=str(ex), renum_csv=args.renum_csv, asm_match=msrc["asm_match"], no_png=True, **common), 0, 15, None)
    fdoc = _read(feats) if stages["extract"]["exit_code"] == 0 else None
    tdoc = None
    if fdoc:
        tdoc = stage(
            "tag",
            argparse.Namespace(
                cmd="tag", cad=args.cad, features=str(feats), renum_csv=args.renum_csv, assem_dir=args.assem_dir, out_dir=str(tg), **msrc, **common
            ),
            15,
            35,
            "tag.json",
        )
    ok_tag = stages.get("tag", {}).get("exit_code") == 0
    if asm:
        node_files = _asm_node_files(args)
        base_bytes = b""
        roundtrip = {"writer_byte_identical": all(rewrite_nodes(d, {}) == d for d in node_files), "nominal_morph_byte_identical": None}
    else:
        base_bytes = Path(args.baseline_inc).read_bytes()
        roundtrip = {"writer_byte_identical": rewrite_nodes(base_bytes, {}) == base_bytes, "nominal_morph_byte_identical": None}
    cdoc = env = None
    if ok_tag:
        vals = work / "values_nominal.json"
        vals.write_text(json.dumps({"schema_version": 1, "values": {}}), encoding="utf-8")
        upd, mor, chk = work / "update_nominal", work / "morph_nominal", work / "check_nominal"
        stage("update", argparse.Namespace(cmd="update", cad=args.cad, features=str(feats), values=str(vals), out_dir=str(upd), tag_dir=str(tg), **common), 35, 45, "update.json")
        if stages["update"]["exit_code"] == 0:
            stage(
                "morph",
                argparse.Namespace(cmd="morph", assem_dir=args.assem_dir, tag_dir=str(tg), features=str(feats), update_dir=str(upd), out_dir=str(mor), solver=None, sweep=False, **msrc, **common),
                45,
                60,
                "morph.json",
            )
        if stages.get("morph", {}).get("exit_code") == 0:
            roundtrip["nominal_morph_byte_identical"] = _nominal_identical(args, mor) if asm else (mor / "morphed.inc").read_bytes() == base_bytes
            cdoc = stage(
                "check",
                argparse.Namespace(
                    cmd="check",
                    morph_dir=str(mor),
                    update_dir=str(upd),
                    tag_dir=str(tg),
                    features=str(feats),
                    values=str(vals),
                    assem_dir=args.assem_dir,
                    renum_csv=args.renum_csv,
                    out_dir=str(chk),
                    out_inc=None if asm else str(work / "check_nominal_out" / Path(args.baseline_inc).name),
                    out_patch=str(work / "check_nominal_out" / "node_patch.npz") if asm else None,
                    **msrc,
                    **common,
                ),
                60,
                70,
                "check.json",
            )
        if not args.no_envelope and stages["update"]["exit_code"] == 0:
            envd = work / "envelope"
            ns = argparse.Namespace(
                cmd="morph",
                assem_dir=args.assem_dir,
                tag_dir=str(tg),
                features=str(feats),
                update_dir=str(upd),
                out_dir=str(envd),
                solver=None,
                sweep=True,
                steps=args.envelope_steps,
                pos_steps=getattr(args, "envelope_pos_steps", None) or "1,3",
                params=args.envelope_params,
                stop_after_fail=args.stop_after_fail,
                check="on",
                keep_steps=False,
                **msrc,
                **common,
            )
            env = stage("envelope", ns, 70, 90, "envelope.json")
    nx = None
    if getattr(args, "nx_samples", None):
        nx = _nx_samples(args, work, feats, tg, common, stage, rep) if ok_tag else {"count": 0, "samples": [], "skipped": "tag failed"}
    v = versions()
    report = envelope(
        status="OK",
        kind="selftest",
        versions={k: v.get(k) for k in ("paicad", "ocp", "numpy", "scipy", "python")},
        inputs={
            "cad_sha256": _sha_input(Path(args.cad)),
            "baseline_sha256": sha256_file(args.asm_match if asm else args.baseline_inc),
            "baseline_bytes": None if asm else len(base_bytes),
            "renum_sha256": sha256_file(args.renum_csv) if args.renum_csv and Path(args.renum_csv).is_file() else None,
        },
        stages=stages,
        extract=_extract_summary(fdoc, _read(ex / "extract_stats.json")),
        tag=_tag_summary(tdoc),
        roundtrip=roundtrip,
        nominal_check=_check_summary(cdoc),
        envelope=_envelope_summary(env),
        **({"nx_samples": nx} if nx is not None else {}),
        elapsed_s=rnd(time.monotonic() - t0, 3),
    )
    out.write_text(REPORT_JSON, dumps(report))
    out.write_text(REPORT_MD, render_md(report))
    out.commit([REPORT_JSON, REPORT_MD])
    rep.progress(100, "selftest report written")
    rep.result("OK", None, REPORT_JSON)
    return EXIT_OK


def _asm_node_files(args) -> list[bytes]:
    """Bytes of the include-tree files that define nodes of the matched PARTs (method M round trip)."""
    from .meshsrc import open_source

    src = open_source(args)
    rows = src.index.lookup(src.mesh.node_ids)
    return [src.index.files[int(k)].path.read_bytes() for k in sorted(set(src.index.node_file[rows].tolist()))]


def _nominal_identical(args, mor: Path) -> bool:
    import numpy as np

    from .meshsrc import NODE_XYZ, load_xyz, open_source

    mesh = open_source(args).mesh
    ids, xyz = load_xyz(mor / NODE_XYZ, "morph node coordinates")
    return bool(np.array_equal(ids, mesh.node_ids) and np.array_equal(xyz, mesh.xyz))


NX_TESS_DEFLECTION_MM = 0.002  # NX surface tessellation chord error (distance error bound on curved faces)
NX_CUTOFF_MM = 5.0  # points farther than this from the tessellation fall back to the exact B-rep distance


def _stats(d) -> dict:
    import numpy as np

    d = np.asarray(d, dtype=float)
    if d.size == 0:
        return {"n": 0, "max": None, "mean": None, "p95": None}
    return {"n": int(d.size), "max": rnd(float(d.max())), "mean": rnd(float(d.mean())), "p95": rnd(float(np.percentile(d, 95)))}


def _nx_distance(nx_body, tset, pts):
    """Distance of points to the NX body surface: tessellation (exact on planes, <= deflection on curved
    faces), exact B-rep distance for the points beyond the cutoff."""
    d, _ = tset.distance(pts, NX_CUTOFF_MM)
    far = ~(d < float("inf"))
    if far.any():
        d[far] = nx_body.distance(pts[far])
    return d


def _nx_samples(args, work: Path, feats: Path, tg: Path, common: dict, stage, rep: Reporter) -> dict:
    """NX change sample comparison (section 9 stage 0 (b), section 10 (1)); numbers only."""
    import numpy as np

    from . import bodymap, cadload
    from .mesh.radioss import parse_text
    from .meshdata import KIND_FACE, components_from_tag, load_tag
    from .meshgeom import TriangleSet
    from .morph import MORPHED_INC, load_sample, read_baseline
    from .update import load_features

    folder = Path(args.nx_samples)
    if not folder.is_dir():
        return {"count": 0, "samples": [], "skipped": "nx samples folder not found"}
    doc = load_features(feats)
    names = [b["body"] for b in doc["bodies"]]
    asm = bool(getattr(args, "asm_match", None))
    msrc = dict(baseline_inc=args.baseline_inc, asm_match=getattr(args, "asm_match", None), cache_dir=getattr(args, "cache_dir", None))
    if asm:
        from .meshsrc import NODE_XYZ, load_xyz, open_source

        mesh = open_source(args).mesh
    else:
        _, mesh = read_baseline(args.baseline_inc)
    tag = load_tag(tg)
    comps = components_from_tag(mesh, tag)
    samples = []
    jsons = sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".json")
    for k, vp in enumerate(jsons):
        stem = vp.stem
        step = next((vp.with_suffix(e) for e in (".step", ".stp", ".STEP", ".STP") if vp.with_suffix(e).is_file()), None)
        entry: dict = {"sample": stem, "stages": {}}
        samples.append(entry)
        if step is None:
            entry["error"] = "NX STEP file missing"
            continue
        sd = work / "nx" / f"{k + 1:03d}"
        upd, mor, chk = sd / "update", sd / "morph", sd / "check"
        lo = 90 + int(8 * k / max(1, len(jsons)))
        st = entry["stages"]
        stage("nx update", argparse.Namespace(cmd="update", cad=args.cad, features=str(feats), values=str(vp), out_dir=str(upd), tag_dir=str(tg), **common), lo, lo, "update.json", st)
        if st["nx update"]["exit_code"] != 0:
            continue
        stage(
            "nx morph",
            argparse.Namespace(cmd="morph", assem_dir=args.assem_dir, tag_dir=str(tg), features=str(feats), update_dir=str(upd), out_dir=str(mor), solver=None, sweep=False, **msrc, **common),
            lo,
            lo,
            "morph.json",
            st,
        )
        if st["nx morph"]["exit_code"] != 0:
            continue
        cdoc = stage(
            "nx check",
            argparse.Namespace(
                cmd="check", morph_dir=str(mor), update_dir=str(upd), tag_dir=str(tg), features=str(feats), values=str(vp),
                assem_dir=args.assem_dir, renum_csv=args.renum_csv, out_dir=str(chk),
                out_inc=None if asm else str(sd / "check_out" / Path(args.baseline_inc).name), out_patch=str(sd / "check_out" / "node_patch.npz") if asm else None, **msrc, **common,
            ),
            lo,
            lo,
            "check.json",
            st,
        )
        items = (((cdoc or {}).get("checks") or {}).get("param") or {}).get("items") or []
        errs = [it["err"] for it in items if it.get("err") is not None]
        rels = [it["err"] / abs(it.get("expected", it["input"])) for it in items if it.get("err") is not None and it.get("expected", it["input"])]
        entry["param_remeasure"] = {"n_params": len(items), "unmeasured": sum(1 for it in items if it.get("err") is None), "max_abs_mm": rnd(max(errs)) if errs else None, "max_rel": rnd(max(rels)) if rels else None}
        entry["check_boundary_dev_max_mm"] = (((cdoc or {}).get("checks") or {}).get("deviation") or {}).get("max_mm")
        try:
            nx = cadload.load(step)
            m = bodymap.match([b.name for b in nx.bodies], names)
        except PaicadError as e:
            entry["error"] = e.code
            continue
        nx_of = {m_body: b for b in nx.bodies for m_body in [m.get(b.name)] if m_body is not None}
        Xm = load_xyz(mor / NODE_XYZ, "morph node coordinates")[1] if asm else parse_text((mor / MORPHED_INC).read_bytes().decode("latin-1")).xyz
        sample = load_sample(upd, doc)
        node_d, brep_d, bodies = [], [], []
        for c in comps:
            nb = nx_of.get(c.body)
            if nb is None:
                continue
            tset = TriangleSet(np.concatenate([p[t] for _, p, t in nb.triangulate(NX_TESS_DEFLECTION_MM, 5.0)]))
            own = (c.owner == c.index) & (c.kind >= KIND_FACE)
            dn = _nx_distance(nb, tset, Xm[c.gidx[own]])
            sb = sample.bodies[c.body]
            pts = np.concatenate([sb.sample_face(f.id, 6) for f in sb.topology().faces] or [np.zeros((0, 3))])
            db = _nx_distance(nb, tset, pts)
            v_nx, v_s = nb.summary().volume, sb.summary().volume
            bodies.append({"body_index": len(bodies) + 1, "boundary_nodes_mm": _stats(dn), "brep_mm": _stats(db), "volume_rel_diff": rnd((v_s - v_nx) / v_nx) if v_nx else None})
            node_d.append(dn)
            brep_d.append(db)
        entry["boundary_vs_nx_mm"] = _stats(np.concatenate(node_d) if node_d else [])
        entry["brep_vs_nx_mm"] = _stats(np.concatenate(brep_d) if brep_d else [])
        entry["volume_rel_diff_max"] = max((abs(b["volume_rel_diff"]) for b in bodies if b["volume_rel_diff"] is not None), default=None)
        entry["bodies"] = bodies
    worst = [s["boundary_vs_nx_mm"]["max"] for s in samples if (s.get("boundary_vs_nx_mm") or {}).get("max") is not None]
    rem = [s["param_remeasure"]["max_abs_mm"] for s in samples if (s.get("param_remeasure") or {}).get("max_abs_mm") is not None]
    return {
        "count": len(samples),
        "compared": len(worst),
        "tess_deflection_mm": NX_TESS_DEFLECTION_MM,
        "boundary_vs_nx_max_mm": max(worst) if worst else None,
        "param_remeasure_max_abs_mm": max(rem) if rem else None,
        "samples": samples,
    }


def _extract_summary(d: dict | None, stats: dict | None = None) -> dict | None:
    """``rib_rejects``: per body, first reason counts of rejected rib cap candidates (extract_stats.json,
    extract-filter.md section 7.1 - field diagnosis of 'no rib parameter')."""
    if not d:
        return None
    by_type: dict[str, int] = {}
    for f in d.get("features") or []:
        by_type[f["type"]] = by_type.get(f["type"], 0) + 1
    grouped = {m for g in d.get("groups") or [] for m in g["members"]}
    reps = {g["parameter"] for g in d.get("groups") or []}
    params = sum(1 for f in d.get("features") or [] if f["name"] in reps or f["name"] not in grouped)
    out = {"bodies": len(d.get("bodies") or []), "features": len(d.get("features") or []), "parameters": params, "groups": len(d.get("groups") or []), "by_type": dict(sorted(by_type.items()))}
    if isinstance(d.get("rib_rows"), list):  # rib-gap.md section 9 R1: rib rows found (RIB_PITCH selected)
        out["rib_rows"] = len(d["rib_rows"])
    if stats and isinstance(stats.get("bodies"), list):
        out["rib_rejects"] = {str(b.get("body")): dict(b.get("rib_rejects") or {}) for b in stats["bodies"]}
    return out


def _tag_summary(d: dict | None) -> dict | None:
    if not d:
        return None
    parts = []
    for p in d.get("parts") or []:
        c = p.get("classified") or {}
        parts.append(
            {
                "part": p.get("part"),
                "nodes": p.get("nodes"),
                "boundary_nodes": p.get("boundary_nodes"),
                "unclassified": c.get("unmatched"),
                "vertex": c.get("vertex"),
                "edge": c.get("edge"),
                "face": c.get("face"),
                "dist_max_mm": (p.get("dist_mm") or {}).get("max"),
            }
        )
    return {
        "status": d.get("status"),
        "match_ratio": d.get("match_ratio"),
        "unclassified_total": sum(int(p["unclassified"] or 0) for p in parts),
        "contacts": len(d.get("contacts") or []),
        "parts": parts,
    }


QUALITY_KEYS = (
    "inverted",
    "min_stretch",
    "baseline_min_stretch",
    "max_aspect",
    "baseline_max_aspect",
    "min_edge_mm",
    "baseline_min_edge_mm",
    "edge_ratio",
    "dt_ratio",
    "baseline_status",
)


def _check_summary(d: dict | None) -> dict | None:
    if not d:
        return None
    ch = d.get("checks") or {}
    items = (ch.get("param") or {}).get("items") or []
    errs = [it["err"] for it in items if it.get("err") is not None]
    q = ch.get("quality") or {}
    return {
        "status": d.get("status"),
        "code": d.get("code"),
        "param_items": len(items),
        "param_unmeasured": sum(1 for it in items if it.get("err") is None),
        "param_max_err_mm": max(errs) if errs else None,
        "deviation_max_mm": (ch.get("deviation") or {}).get("max_mm"),
        "quality": {k: q.get(k) for k in QUALITY_KEYS},
        "interference": (ch.get("interference") or {}).get("status"),
        "tie": (ch.get("tie") or {}).get("status"),
        "warnings": sorted({w.get("code") for w in d.get("warnings") or [] if w.get("code")}),
    }


def _envelope_summary(d: dict | None) -> dict | None:
    if not d:
        return None
    out = []
    for s in d.get("summary") or []:
        lm = s.get("limit_metric") or {}
        out.append(
            {
                "param": s["param"],
                "unit": s.get("unit", "%"),
                "last_ok": s.get("last_ok", s.get("last_ok_pct")),
                "first_fail": s.get("first_fail", s.get("first_fail_pct")),
                "first_fail_code": s["first_fail_code"],
                "limit_metric": {k: (lm.get(k) or {}).get("metric") for k in ("+", "-")},
            }
        )
    rows = d.get("rows") or []
    return {"steps_pct": d.get("steps_pct"), "pos_steps_mm": d.get("pos_steps_mm"), "steps_run": len(rows), "steps_failed": sum(1 for r in rows if r["status"] == "FAIL"), "params": out}


def _v(x) -> str:
    return "-" if x is None else str(x)


def render_md(r: dict) -> str:
    L = [
        "# paicad selftest report (numbers only)",
        "",
        f"- engine_version: {r['engine_version']}; ocp {r['versions'].get('ocp')}; python {r['versions'].get('python')}",
        f"- elapsed_s: {r['elapsed_s']}",
        "",
        "## Stages",
        "",
        "| stage | exit | status | code |",
        "|---|---|---|---|",
    ]
    for k, s in r["stages"].items():
        L.append(f"| {k} | {s['exit_code']} | {_v(s['status'])} | {_v(s['code'])} |")
    e = r.get("extract")
    if e:
        L += ["", "## Extract", "", f"- bodies {e['bodies']}, features {e['features']}, parameters {e['parameters']}, groups {e['groups']}"]
        L.append("- by type: " + ", ".join(f"{k} {v}" for k, v in e["by_type"].items()))
        for b, rr in (e.get("rib_rejects") or {}).items():
            if rr:
                L.append(f"- rib candidates rejected ({b}): " + ", ".join(f"{k} {v}" for k, v in rr.items()))
    t = r.get("tag")
    if t:
        L += ["", "## Tag", "", f"- match_ratio {t['match_ratio']}, unclassified boundary nodes {t['unclassified_total']}, contact faces {t['contacts']}", ""]
        L += ["| part | nodes | boundary | unclassified | max dist mm |", "|---|---|---|---|---|"]
        for p in t["parts"]:
            L.append(f"| {p['part']} | {p['nodes']} | {p['boundary_nodes']} | {p['unclassified']} | {p['dist_max_mm']} |")
    rt = r["roundtrip"]
    L += ["", "## Unchanged round trip", "", f"- writer byte identical: {rt['writer_byte_identical']}", f"- nominal morph byte identical: {_v(rt['nominal_morph_byte_identical'])}"]
    c = r.get("nominal_check")
    if c:
        q = c["quality"]
        L += [
            "",
            "## Nominal check",
            "",
            f"- status {c['status']} ({_v(c['code'])}); parameter max error {_v(c['param_max_err_mm'])} mm ({c['param_unmeasured']} unmeasured of {c['param_items']}); boundary deviation {_v(c['deviation_max_mm'])} mm",
            f"- quality: min stretch {q['min_stretch']} (baseline {q['baseline_min_stretch']}), max aspect {q['max_aspect']} (baseline {q['baseline_max_aspect']}), "
            f"min edge {q['min_edge_mm']} mm (baseline {q['baseline_min_edge_mm']}), edge ratio {q['edge_ratio']}, dt ratio {q['dt_ratio']}, inverted {q['inverted']}, baseline_status {q['baseline_status']}",
            f"- interference {c['interference']}, tie {c['tie']}, warnings {', '.join(c['warnings']) or '-'}",
        ]
    en = r.get("envelope")
    if en:
        L += ["", "## Short envelope", "", f"- steps {en['steps_pct']} % (position parameters {en.get('pos_steps_mm')} mm), {en['steps_run']} run, {en['steps_failed']} failed", ""]
        L += ["| param | unit | last OK + | last OK - | first fail + | first fail - | limit + | limit - |", "|---|---|---|---|---|---|---|---|"]
        for p in en["params"]:
            u = p["unit"]
            ff = {d: "-" if p["first_fail"][d] is None else f"{p['first_fail'][d]} {u} {p['first_fail_code'][d]}" for d in ("+", "-")}
            L.append(f"| {p['param']} | {u} | {p['last_ok']['+']} {u} | {p['last_ok']['-']} {u} | {ff['+']} | {ff['-']} | {_v(p['limit_metric']['+'])} | {_v(p['limit_metric']['-'])} |")
    nx = r.get("nx_samples")
    if nx is not None:
        L += ["", "## NX change samples", "", f"- samples {nx['count']}, compared {nx.get('compared', 0)}; worst boundary node distance to NX {_v(nx.get('boundary_vs_nx_max_mm'))} mm; worst re-measurement error {_v(nx.get('param_remeasure_max_abs_mm'))} mm (NX tessellation chord {nx.get('tess_deflection_mm')} mm)", ""]
        L += ["| sample | update | morph | check | boundary vs NX max / p95 mm | B-rep vs NX max mm | volume rel diff | re-measure max mm |", "|---|---|---|---|---|---|---|---|"]
        for s in nx["samples"]:
            st = s.get("stages") or {}
            stt = {k: _v((st.get(f"nx {k}") or {}).get("code") or (st.get(f"nx {k}") or {}).get("status")) for k in ("update", "morph", "check")}
            b = s.get("boundary_vs_nx_mm") or {}
            br = s.get("brep_vs_nx_mm") or {}
            L.append(
                f"| {s['sample']} | {stt['update']} | {stt['morph']} | {stt['check']} | {_v(b.get('max'))} / {_v(b.get('p95'))} | {_v(br.get('max'))} | "
                f"{_v(s.get('volume_rel_diff_max'))} | {_v((s.get('param_remeasure') or {}).get('max_abs_mm'))} |" + (f" {s['error']}" if s.get("error") else "")
            )
    return "\n".join(L) + "\n"
