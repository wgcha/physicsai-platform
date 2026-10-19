"""``paicad extract`` (contract sections 4.3, 6.2)."""

from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

from . import cadload, features, options
from .common import (
    EXIT_EXTRACT_EMPTY,
    EXIT_OK,
    OutDir,
    Reporter,
    dumps,
    envelope,
    rnd,
    vec,
)
from .mesh.radioss import read_renum_csv

XML_NAME = "parameter_extracted.xml"
JSON_NAME = "parameter_features.json"


def render_xml(model_name: str, params: list[tuple[str, float]]) -> str:
    lines = ['<?xml version="1.0" encoding="utf-8"?>', "<Root>", f'  <Model Name="{escape(model_name, {chr(34): "&quot;"})}">']
    for name, value in params:
        lines.append(f"    <Parameter><Name>{escape(name)}</Name><Value>{float(value)!r} mm</Value></Parameter>")
    lines += ["  </Model>", "</Root>", ""]
    return "\n".join(lines)


def run(args, rep: Reporter) -> int:
    opts = options.load(args.options)
    out = OutDir(args.out_dir, [XML_NAME, JSON_NAME])
    out.prepare()
    rep.progress(5, "loading CAD")
    cad = cadload.load(args.cad)
    renum = read_renum_csv(args.renum_csv) if args.renum_csv else None
    pairs = cadload.correspond(cad, renum, args.body_map)
    bodies_json = []
    per_body = []
    tol_of = {}
    for k, (body, part, row) in enumerate(pairs):
        rep.progress(10 + int(70 * k / max(1, len(pairs))), f"recognizing features: {body.name}")
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
        per_body.append((body.name, part, body, features.recognize_body(body, opts)))
    rep.progress(85, "naming features and symmetry groups")
    feats, groups, warnings = features.finalize(per_body, opts, tol_of)
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
                "draft_deg": ft.draft_deg,
                "ref": ft.ref,
                "measure": {"method": features.MEASURE[ft.type], "faces": [f"F{i}" for i in ft.faces]}
                | ({"axis": "xyz"[ft.axis]} if ft.axis is not None else {}),
                "group": ft.group,
                "png": None,
            }
        )
    if feats and not args.no_png:
        warnings.append({"code": "PNG_RENDER_FAILED", "feature": None, "message": "feature highlight rendering is not available in this version"})
    body_map_mode = "body_map" if args.body_map else ("xde" if cad.mode == "single" else "file_stem")
    doc = envelope(
        unit_system="mm-ton-s",
        cad={"mode": cad.mode, "files": cad.files, "body_map": body_map_mode},
        bodies=bodies_json,
        features=feat_json,
        groups=groups,
        warnings=warnings,
    )
    if not feats:
        out.write_text(JSON_NAME, dumps(doc))
        out.commit([JSON_NAME])
        rep.result("FAIL", "GEOM_EXTRACT_EMPTY", JSON_NAME)
        return EXIT_EXTRACT_EMPTY
    grouped = {g["parameter"] for g in groups}
    members = {m for g in groups for m in g["members"]}
    params = [(ft.name, ft.nominal) for ft in feats if ft.name in grouped or ft.name not in members]
    model_name = Path(args.cad).name
    out.write_text(JSON_NAME, dumps(doc))
    out.write_text(XML_NAME, render_xml(model_name, params))
    out.commit([JSON_NAME, XML_NAME])
    rep.progress(100, f"extract done: {len(feats)} features, {len(params)} parameters")
    rep.result("OK", None, JSON_NAME)
    return EXIT_OK
