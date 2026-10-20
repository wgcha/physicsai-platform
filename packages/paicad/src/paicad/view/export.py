"""``paicad view export`` - nominal B-rep -> ``view.glb`` + ``view_manifest.json`` (geometry-view.md sections 4.1, 4.2, 5).

Failure of the view itself (VIEW_TESSELLATION_FAILED, VIEW_TOO_LARGE) writes a FAIL manifest without
GLB and exits 14; input errors keep the usual codes (exit 3).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np

from .. import options
from ..common import CODE_CATEGORY, EXIT_OK, EXIT_VIEW, OutDir, PaicadError, Reporter, dumps, envelope, rnd, sha256_file
from ..update import load_features, nominal_cad
from . import VIEW_GLB, VIEW_MANIFEST, BodyTess, body_items, generator, glb_with_lod, load_view_options
from . import gltf
from . import manifest as mf

ROOT_EXTRAS = {"unit": "mm", "up_axis": "Z"}


def bbox_union(bbs: list[np.ndarray]) -> list[float]:
    a = np.asarray(bbs, dtype=float).reshape(-1, 6)
    return [rnd(x) for x in np.concatenate([a[:, :3].min(axis=0), a[:, 3:].max(axis=0)])]


def body_rows(tbs: list[BodyTess], topos: list) -> tuple[list[dict], list[dict]]:
    rows, warns = [], []
    for tb, topo in zip(tbs, topos):
        faces, w = mf.face_entries(tb.name, topo, tb.face_ids)
        warns += w
        rows.append({"body": tb.name, "node": tb.name, "edges_node": f"{tb.name}.edges" if tb.edges else None, "faces": faces})
    return rows, warns


def glb_info(name: str, data: bytes, tbs: list[BodyTess] | None) -> dict:
    d = {"file": name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
    if tbs is not None:
        d["triangles"] = int(sum(len(t.triangles) for t in tbs))
        d["vertices"] = int(sum(len(t.positions) for t in tbs))
    return d


def manifest_doc(mode: str, status: str, code: str | None, message: str | None, source: dict, glb: dict | None, tess: dict, bbox: list, bodies: list, features: list, warnings: list,
                 kind: str = "solid", fixed_clusters: list | None = None) -> dict:
    """Section 4.2 key order (envelope keys first: schema_version, engine, engine_version)."""
    d = envelope(kind=kind, mode=mode, status=status, code=code, category=CODE_CATEGORY.get(code) if code else None, message=message, unit="mm", up_axis="Z")
    d.update(source=source, glb=glb, tess=tess, bbox=bbox, bodies=bodies, features=features, fixed_clusters=list(fixed_clusters or []), warnings=warnings)
    return d


def source_of(cad, features_path: str | Path) -> dict:
    return {"cad": cad.files, "features_sha256": sha256_file(features_path), "fixed_digest": None}


def run(args, rep: Reporter) -> int:
    vopts = load_view_options(args.view_options)
    out = OutDir(args.out_dir, [VIEW_MANIFEST, VIEW_GLB])
    out.prepare()
    doc = load_features(args.features)
    rep.progress(10, "loading nominal CAD")
    cad, bodies = nominal_cad(args.cad, doc, args.body_map)
    names = [b["body"] for b in doc["bodies"]]
    source = source_of(cad, args.features)
    gopts = options.load(None)
    topos = [b.topology() for b in bodies]
    bbs = [b.summary().bbox for b in bodies]
    rep.progress(30, "tessellating")

    def build(tbs: list[BodyTess]) -> bytes:
        items = [it for tb in tbs for it in body_items(tb)]
        return gltf.write_glb(items, generator(), root_extras=ROOT_EXTRAS)

    try:
        data, tbs, used, warnings = glb_with_lod(bodies, names, vopts["tess"], vopts, build)
    except PaicadError as e:
        if not e.code.startswith("VIEW_"):
            raise
        rep.warn(f"{e.code}: {e.message}")
        d = manifest_doc("nominal", "FAIL", e.code, e.message, source, None, dict(vopts["tess"], coarsened=None), bbox_union(bbs), [], [], [])
        out.write_text(VIEW_MANIFEST, dumps(d))
        out.commit([VIEW_MANIFEST])
        rep.result("FAIL", e.code, VIEW_MANIFEST)
        return EXIT_VIEW
    rep.progress(80, "writing manifest")
    rows, w = body_rows(tbs, topos)
    warnings += w
    by_name = dict(zip(names, range(len(names))))
    param = mf.parameter_of(doc)
    feats = []
    for f in doc["features"]:
        k = by_name.get(f["body"])
        fc = f.get("faces") or {}
        row, fw = mf.feature_entry(
            f,
            param[f["name"]],
            f["nominal"],
            list(fc.get("moving") or []),
            list(fc.get("fixed") or []),
            None if k is None else topos[k],
            None if k is None else bbs[k],
            options.body_tol(gopts, bbs[k]) if k is not None else 0.0,
        )
        feats.append(row)
        warnings += fw
    with open(out.tmp_path(VIEW_GLB), "wb") as fh:
        fh.write(data)
    d = manifest_doc("nominal", "OK", None, None, source, glb_info(VIEW_GLB, data, tbs), used, bbox_union(bbs), rows, feats, warnings)
    out.write_text(VIEW_MANIFEST, dumps(d))
    out.commit([VIEW_GLB, VIEW_MANIFEST])
    rep.progress(100, f"view export done: {d['glb']['triangles']} triangles, {len(data)} bytes")
    rep.result("OK", None, VIEW_MANIFEST)
    return EXIT_OK
