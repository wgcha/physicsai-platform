"""``paicad extract`` (contract sections 4.3, 6.2)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from xml.sax.saxutils import escape

from . import cadload, features, options
from .common import (
    EXIT_EXTRACT_EMPTY,
    EXIT_OK,
    OutDir,
    PaicadError,
    Reporter,
    dumps,
    envelope,
    rnd,
    vec,
)
from .mesh.radioss import read_renum_csv

XML_NAME = "parameter_extracted.xml"
JSON_NAME = "parameter_features.json"
STATS_NAME = "extract_stats.json"  # extract-filter.md section 7.1 (always written, not a success marker)
PNG_DIR = "features"


def render_xml(model_name: str, params: list[tuple[str, float]]) -> str:
    lines = ['<?xml version="1.0" encoding="utf-8"?>', "<Root>", f'  <Model Name="{escape(model_name, {chr(34): "&quot;"})}">']
    for name, value in params:
        lines.append(f"    <Parameter><Name>{escape(name)}</Name><Value>{float(value)!r} mm</Value></Parameter>")
    lines += ["  </Model>", "</Root>", ""]
    return "\n".join(lines)


def _render_pngs(feat_json: list[dict], bodies: dict, out: OutDir, warnings: list[dict], log=None, timing: dict | None = None, bbox_of: dict | None = None) -> list[str]:
    """features/<NAME>.png per feature (section 4.3); a failure only drops that PNG (PNG_RENDER_FAILED)."""
    from . import render

    meshes: dict[str, object] = {}
    written: list[str] = []
    timing = {} if timing is None else timing
    timing.setdefault("png_tessellate_s", 0.0)
    timing.setdefault("png_render_s", 0.0)
    timing.setdefault("png_write_s", 0.0)
    total = len(feat_json)
    step = max(1, total // 10)
    t0 = last = time.perf_counter()
    for k, f in enumerate(feat_json, 1):
        now = time.perf_counter()
        if log is not None and k > 1 and ((k - 1) % step == 0 and now - last >= 1.0):
            log(f"PNG {k - 1}/{total} {now - t0:.1f}s")
            last = now
        rel = f"{PNG_DIR}/{f['name']}.png"
        try:
            mesh = meshes.get(f["body"])
            if mesh is None:
                ta = time.perf_counter()
                mesh = meshes[f["body"]] = render.BodyMesh(bodies[f["body"]].triangulate())
                timing["png_tessellate_s"] += time.perf_counter() - ta
            moving, fixed = ([int(x[1:]) for x in f["faces"][key]] for key in ("moving", "fixed"))
            ta = time.perf_counter()
            img = render.render_feature(mesh, moving, fixed, render.dimension_points(f, (bbox_of or {}).get(f["body"])))
            tb = time.perf_counter()
            render.write_png(out.tmp_path(rel), img)
            timing["png_render_s"] += tb - ta
            timing["png_write_s"] += time.perf_counter() - tb
        except Exception as ex:  # noqa: BLE001 - rendering never fails extract (section 4.3)
            warnings.append({"code": "PNG_RENDER_FAILED", "feature": f["name"], "message": f"feature highlight rendering failed: {ex.__class__.__name__}: {ex}"})
            continue
        f["png"] = rel
        written.append(rel)
    timing["png_triangles"] = int(sum(len(m.tris) for m in meshes.values()))
    if log is not None and total:
        log(f"PNG {total}/{total} {time.perf_counter() - t0:.1f}s")
    return written


def _stats_doc(filter_applied: bool, bodies: list[dict], pngs: list[str], timing: dict, t_start: float) -> dict:
    """``extract_stats.json`` (extract-filter.md section 7.1). Only the ``elapsed_s`` fields are non-deterministic."""
    r2 = lambda x: round(float(x), 2)  # noqa: E731
    for b in bodies:
        for t in b.get("types", {}).values():
            if "elapsed_s" in t:
                t["elapsed_s"] = r2(t["elapsed_s"])
    return envelope(
        filter_applied=filter_applied,
        bodies=bodies,
        png={"rendered": len(pngs), "elapsed_s": r2(timing.get("png_s", 0.0))},
        elapsed_s={
            "load": r2(timing.get("load_s", 0.0)),
            "recognize": r2(timing.get("recognize_s", 0.0)),
            "finalize": r2(timing.get("finalize_s", 0.0)),
            "png": r2(timing.get("png_s", 0.0)),
            "total": r2(time.perf_counter() - t_start),
        },
    )


def _timing_summary(timing: dict) -> dict:
    """Numbers only (seconds rounded to 0.01 s, counts as int)."""
    out = {}
    for k, v in timing.items():
        if isinstance(v, dict):
            out[k] = _timing_summary(v)
        elif isinstance(v, float):
            out[k] = round(v, 2)
        else:
            out[k] = v
    return out


def _log_timing(rep: Reporter, timing: dict, t_start: float) -> None:
    """Stage timing summary: one ``EXTRACT_TIMING <json>`` line in paicad.log + a stderr line. Kept out of
    parameter_features.json so that file stays byte-deterministic (section 5.2)."""
    timing["total_s"] = time.perf_counter() - t_start
    summary = _timing_summary(timing)
    rep.log("EXTRACT_TIMING " + json.dumps(summary, ensure_ascii=False, sort_keys=True))
    rep.info(f"[extract] total {summary['total_s']}s")


def run(args, rep: Reporter) -> int:
    t_start = time.perf_counter()
    timing: dict = {"bodies": {}}

    def info(msg: str) -> None:
        rep.info(f"[extract] {msg}")

    opts = options.load(args.options, keep_filter=True)
    flt = opts["extract"].get("filter")
    out = OutDir(args.out_dir, [XML_NAME, JSON_NAME, STATS_NAME] + ([] if args.no_png else [PNG_DIR]))
    out.prepare()
    rep.progress(5, "loading CAD")
    cad = cadload.load(args.cad)
    match = None
    if getattr(args, "asm_match", None):  # assembly match (asm-match.md section 6.1): order / correspondence check only
        from .meshsrc import load_match

        if args.renum_csv:
            raise PaicadError("GEOM_INPUT_INVALID", "give --renum-csv or --asm-match, not both")
        match = load_match(args.asm_match)
    renum = read_renum_csv(args.renum_csv) if args.renum_csv else None
    pairs = cadload.correspond(cad, renum, None if match is not None else args.body_map)
    if match is not None:
        names = {b.name for b, _, _ in pairs}
        listed = {r["body"] for r in match.rows} | set(match.excluded)
        if names != listed:
            raise PaicadError(
                "GEOM_BODY_MAP_FAILED",
                f"unmatched bodies: [{', '.join(sorted(names - listed)[:10])}]; assembly match bodies without a CAD body: [{', '.join(sorted(listed - names)[:10])}]",
            )
    timing["load_s"] = time.perf_counter() - t_start
    info(f"CAD loaded: {len(pairs)} bodies {timing['load_s']:.1f}s")
    bodies_json = []
    per_body = []
    tol_of = {}
    stats_bodies = []
    for k, (body, part, row) in enumerate(pairs):
        pct = 10 + int(70 * k / max(1, len(pairs)))
        rep.progress(pct, f"recognizing features: {body.name}")
        s = body.summary()
        tol_of[body.name] = options.body_tol(opts, s.bbox)
        bodies_json.append(
            {
                "body": body.name,
                "part": part,
                "renum_row": row,
                "volume": rnd(s.volume),
                "bbox": vec(s.bbox),
                "faces": s.n_faces,
                "edges": s.n_edges,
                "vertices": s.n_vertices,
            }
        )
        bt: dict = {}
        timing["bodies"][body.name or f"#{k + 1}"] = bt
        bs: dict = {}
        found = features.recognize_body(
            body, opts, log=lambda m, b=body.name: info(f"{b}: {m}"), timing=bt, stats=bs, progress=lambda m, b=body.name, p=pct: rep.progress(p, f"{b} {m}")
        )
        per_body.append((body.name, part, body, found))
        stats_bodies.append({"body": body.name, **bs})
        info(f"{body.name}: {bt['features']} features {bt['recognize_s']:.1f}s")
    timing["recognize_s"] = time.perf_counter() - t_start - timing["load_s"]
    rep.progress(85, "naming features and symmetry groups")
    t_fin = time.perf_counter()
    fin: dict = {}
    feats, groups, warnings = features.finalize(per_body, opts, tol_of, timing=fin)
    if match is not None and args.body_map:
        warnings.append({"code": "BODY_MAP_IGNORED", "message": "body map ignored: the assembly match is the only body/component correspondence"})
    timing["finalize_s"] = time.perf_counter() - t_fin
    timing.update(fin)
    info(f"naming/feasible/symmetry: {len(feats)} features, {len(groups)} groups {timing['finalize_s']:.1f}s")
    topo_of = {b.name: b.topology() for b, _, _ in pairs}
    feat_json = []
    for ft in feats:
        topo = topo_of[ft.body]
        sig_faces = sorted(set(ft.faces) | set(ft.moving) | set(ft.fixed))
        if ft.ref and ft.ref.get("warning"):
            warnings.append({"code": ft.ref["warning"], "feature": ft.name, "message": "both faces are contact faces"})
        feat_json.append(
            {
                "name": ft.name,
                "type": ft.type,
                "body": ft.body,
                "nominal": ft.nominal,
                "unit": "mm",
                "range": ft.range,
                "feasible": ft.feasible,
                "faces": {"moving": [f"F{i}" for i in ft.moving], "fixed": [f"F{i}" for i in ft.fixed]},
                "face_signatures": {f"F{i}": features.face_signature(topo.face(i)) for i in sig_faces},
                "adjacent_surfaces": features.adjacent_surfaces(topo, sig_faces),
                "draft_deg": ft.draft_deg,
                "ref": ft.ref,
                "measure": {"method": features.MEASURE[ft.type], "faces": [f"F{i}" for i in ft.faces]}
                | ({"axis": "xyz"[ft.axis]} if ft.axis is not None else {}),
                "group": ft.group,
                "png": None,
            }
        )
    pngs: list[str] = []
    if feats and not args.no_png:
        rep.progress(90, "rendering feature highlights")
        t_png = time.perf_counter()
        bbox_of = {b["body"]: b["bbox"] for b in bodies_json}
        pngs = _render_pngs(feat_json, {b.name: b for b, _, _ in pairs}, out, warnings, log=info, timing=timing, bbox_of=bbox_of)
        timing["png_s"] = time.perf_counter() - t_png
        timing["pngs"] = len(pngs)
        info(f"feature PNGs: {len(pngs)} {timing['png_s']:.1f}s")
    body_map_mode = "body_map" if args.body_map else ("xde" if cad.mode == "single" else "file_stem")
    doc = envelope(
        unit_system="mm-ton-s",
        cad={"mode": cad.mode, "files": cad.files, "body_map": body_map_mode},
        **({"filter": dict(flt, draft_max_deg=opts["extract"]["draft_max_deg"])} if flt is not None else {}),
        bodies=bodies_json,
        features=feat_json,
        groups=groups,
        warnings=warnings,
    )
    stats_doc = _stats_doc(flt is not None, stats_bodies, pngs, timing, t_start)
    if not feats:
        out.write_text(JSON_NAME, dumps(doc))
        out.write_text(STATS_NAME, dumps(stats_doc))
        out.commit([JSON_NAME, STATS_NAME])
        _log_timing(rep, timing, t_start)
        rep.result("FAIL", "GEOM_EXTRACT_EMPTY", JSON_NAME)
        return EXIT_EXTRACT_EMPTY
    grouped = {g["parameter"] for g in groups}
    members = {m for g in groups for m in g["members"]}
    params = [(ft.name, ft.nominal) for ft in feats if ft.name in grouped or ft.name not in members]
    model_name = Path(args.cad).name
    out.write_text(JSON_NAME, dumps(doc))
    out.write_text(XML_NAME, render_xml(model_name, params))
    out.write_text(STATS_NAME, dumps(stats_doc))
    out.commit([JSON_NAME, XML_NAME, STATS_NAME] + pngs)
    _log_timing(rep, timing, t_start)
    rep.progress(100, f"extract done: {len(feats)} features, {len(params)} parameters")
    rep.result("OK", None, JSON_NAME)
    return EXIT_OK
