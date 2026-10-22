"""``paicad tag`` - classify baseline mesh nodes onto the nominal B-rep (contract sections 4.5, 6.1)."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import cadload, options
from .common import (
    EXIT_OK,
    EXIT_TAG,
    OutDir,
    PaicadError,
    Reporter,
    dumps,
    envelope,
    rnd,
    sha256_file,
)
from .kernel.base import BodyGeom
from .mesh.radioss import (
    Component,
    collect_assembly_surface,
    components,
    read_mesh,
    read_renum_csv,
    skin_triangles,
)
from .meshgeom import TriangleSet
from .meshsrc import mesh_args, open_source

TAG_JSON = "tag.json"
TAG_NPZ = "tag_nodes.npz"

KIND_UNMATCHED, KIND_INTERIOR, KIND_FACE, KIND_EDGE, KIND_VERTEX = -1, 0, 1, 2, 3


@dataclass
class NodeTags:
    node_ids: np.ndarray  # int64[n] (component nodes, sorted)
    kind: np.ndarray  # int8[n]
    entity: np.ndarray  # int32[n]
    uv: np.ndarray  # float64[n,2]
    dist: np.ndarray  # float64[n]
    boundary: np.ndarray  # bool[n]


def classify_points(body: BodyGeom, pts: np.ndarray, tol: float) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Vertex -> edge -> face classification of boundary points (section 6.1 step 2).

    Returns kind[n], entity[n], uv[n,2], dist[n].
    """
    topo = body.topology()
    n = len(pts)
    kind = np.full(n, KIND_UNMATCHED, dtype=np.int8)
    ent = np.full(n, -1, dtype=np.int32)
    uv = np.zeros((n, 2))
    dist = np.full(n, np.inf)
    V = topo.vertices
    if len(V):
        dv = np.linalg.norm(pts[:, None, :] - V[None, :, :], axis=2)
        iv = np.argmin(dv, axis=1)
        mv = dv[np.arange(n), iv]
        hit = mv <= tol
        kind[hit] = KIND_VERTEX
        ent[hit] = iv[hit] + 1
        dist[hit] = mv[hit]
    # edges
    rest = np.flatnonzero(kind == KIND_UNMATCHED)
    best_d = np.full(n, np.inf)
    best_e = np.full(n, -1)
    best_t = np.zeros(n)
    for e in topo.edges:
        lo, hi = e.bbox[:3] - tol, e.bbox[3:] + tol
        sub = rest[np.all((pts[rest] >= lo) & (pts[rest] <= hi), axis=1)]
        if sub.size == 0:
            continue
        d, t, _ = body.project_to_edge(e.id, pts[sub])
        better = d < best_d[sub]
        idx = sub[better]
        best_d[idx], best_e[idx], best_t[idx] = d[better], e.id, t[better]
    hit = (best_e > 0) & (best_d <= tol)
    kind[hit] = KIND_EDGE
    ent[hit] = best_e[hit]
    uv[hit, 0] = best_t[hit]
    dist[hit] = best_d[hit]
    # faces
    rest = np.flatnonzero(kind == KIND_UNMATCHED)
    best_d = np.full(n, np.inf)
    best_f = np.full(n, -1)
    best_uv = np.zeros((n, 2))
    any_d = np.full(n, np.inf)
    for f in topo.faces:
        lo, hi = f.bbox[:3] - tol, f.bbox[3:] + tol
        sub = rest[np.all((pts[rest] >= lo) & (pts[rest] <= hi), axis=1)]
        if sub.size == 0:
            continue
        d, fuv, inside, _ = body.project_to_face(f.id, pts[sub])
        any_d[sub] = np.minimum(any_d[sub], d)
        better = inside & (d < best_d[sub])
        idx = sub[better]
        best_d[idx], best_f[idx], best_uv[idx] = d[better], f.id, fuv[better]
    hit = (best_f > 0) & (best_d <= tol)
    kind[hit] = KIND_FACE
    ent[hit] = best_f[hit]
    uv[hit] = best_uv[hit]
    dist[hit] = best_d[hit]
    miss = kind == KIND_UNMATCHED
    dist[miss] = np.minimum(any_d[miss], np.minimum(best_d[miss], dist[miss]))
    return kind, ent, uv, dist


def _consistency(body: BodyGeom, pts: np.ndarray, kind, ent, uv, dist, tris_local: np.ndarray, tol: float, warnings: list, part: str) -> None:
    """Section 6.1 step 3: triangle on three faces -> try common edges; one kind=3 node per vertex."""
    topo = body.topology()
    face_edges = {f.id: set(f.edges) for f in topo.faces}
    for tri in tris_local:
        k = kind[tri]
        if not np.all(k == KIND_FACE):
            continue
        fs = ent[tri]
        if len(set(fs.tolist())) < 3:
            continue
        for i in tri:
            others = [int(f) for f in fs if f != ent[i]]
            cands = set()
            for g in others:
                cands |= face_edges[int(ent[i])] & face_edges[g]
            best = None
            for e in sorted(cands):
                d, t, _ = body.project_to_edge(e, pts[i : i + 1])
                if d[0] <= tol and (best is None or d[0] < best[0]):
                    best = (d[0], e, t[0])
            if best is not None:
                kind[i], ent[i], uv[i], dist[i] = KIND_EDGE, best[1], (best[2], 0.0), best[0]
    # vertices: exactly one kind=3 node each
    vert_edges: dict[int, list[int]] = {}
    for e in topo.edges:
        for v in e.vertices:
            vert_edges.setdefault(v, []).append(e.id)
    missing = 0
    for v in range(1, len(topo.vertices) + 1):
        idx = np.flatnonzero((kind == KIND_VERTEX) & (ent == v))
        if idx.size == 0:
            missing += 1
            continue
        if idx.size == 1:
            continue
        keep = idx[np.argmin(dist[idx])]
        for i in idx:
            if i == keep:
                continue
            best = None
            for e in vert_edges.get(v, []):
                d, t, _ = body.project_to_edge(e, pts[i : i + 1])
                if best is None or d[0] < best[0]:
                    best = (d[0], e, t[0])
            if best is not None and best[0] <= tol:
                kind[i], ent[i], uv[i], dist[i] = KIND_EDGE, best[1], (best[2], 0.0), best[0]
            else:
                kind[i], ent[i], uv[i] = KIND_UNMATCHED, -1, (0.0, 0.0)
    if missing:
        warnings.append({"code": "TAG_VERTEX_NO_NODE", "part": part, "message": f"{missing} B-rep vertices of {part} have no mesh node"})


def tag_component(body: BodyGeom, comp: Component, node_index: dict[int, int], xyz: np.ndarray, tol: float, warnings: list) -> tuple[NodeTags, np.ndarray]:
    """Returns (tags of all component nodes, skin triangles as local node indices)."""
    nodes = comp.node_ids
    local = {int(nid): i for i, nid in enumerate(nodes)}
    skin = skin_triangles(comp.tets)
    tris_local = np.vectorize(local.__getitem__, otypes=[np.int64])(skin) if skin.size else np.zeros((0, 3), dtype=np.int64)
    bmask = np.zeros(len(nodes), dtype=bool)
    bmask[np.unique(tris_local)] = True
    coords = xyz[[node_index[int(n)] for n in nodes]]
    kind = np.zeros(len(nodes), dtype=np.int8)
    ent = np.full(len(nodes), -1, dtype=np.int32)
    uv = np.zeros((len(nodes), 2))
    dist = np.zeros(len(nodes))
    b = np.flatnonzero(bmask)
    k, e, u, d = classify_points(body, coords[b], tol)
    kind[b], ent[b], uv[b], dist[b] = k, e, u, d
    _consistency(body, coords, kind, ent, uv, dist, tris_local, tol, warnings, comp.part)
    return NodeTags(nodes, kind, ent, uv, dist, bmask), tris_local


def _read_features_bodies(path: str | Path) -> list[dict]:
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError) as ex:
        raise PaicadError("GEOM_INPUT_INVALID", f"cannot read features file: {ex.__class__.__name__}") from None
    if not isinstance(doc, dict) or doc.get("schema_version") != 1 or not isinstance(doc.get("bodies"), list):
        raise PaicadError("GEOM_INPUT_INVALID", "features file: unsupported schema or missing bodies")
    return doc["bodies"]


def run(args, rep: Reporter) -> int:
    opts = options.load(args.options)
    out = OutDir(args.out_dir, [TAG_JSON, TAG_NPZ])
    out.prepare()
    topt = opts["tag"]
    src = None
    if mesh_args(args, ("baseline_inc", "renum_csv")) == "M":
        rep.progress(5, "reading the assembly include tree")
        src = open_source(args)
        base = None
        doc_head = dict(
            status="OK",
            code=None,
            message=None,
            baseline_inc=None,
            asm_match={"name": src.match.path.name, "sha256": src.match.sha256},
            excluded_bodies=list(src.match.excluded),
            tolerance={"abs_mm": topt["tol_abs_mm"], "rel": topt["tol_rel"]},
        )
        mesh = src.mesh
        warnings: list[dict] = []
        if getattr(args, "body_map", None):
            warnings.append({"code": "BODY_MAP_IGNORED", "message": "body map ignored: the assembly match is the only body/component correspondence"})
        comps, w = src.components()
        warnings += w
        rep.progress(15, "loading CAD")
        cad = cadload.load(args.cad)
        byname = cad.by_name()
        missing = [c.part for c in comps if c.part not in byname]
        extra = sorted(set(byname) - {c.part for c in comps} - set(src.match.excluded))
        if missing or extra:
            raise PaicadError("GEOM_BODY_MAP_FAILED", f"unmatched bodies: [{', '.join(extra[:10])}]; match rows without a CAD body: [{', '.join(missing[:10])}]")
        body_of_part = {c.part: c.part for c in comps}
    else:
        base = Path(args.baseline_inc)
        if not base.is_file():
            raise PaicadError("GEOM_INPUT_INVALID", f"baseline include not found: {base.name}")
        renum = read_renum_csv(args.renum_csv)
        doc_head = dict(
            status="OK",
            code=None,
            message=None,
            baseline_inc={"name": base.name, "sha256": sha256_file(base)},
            tolerance={"abs_mm": topt["tol_abs_mm"], "rel": topt["tol_rel"]},
        )
        rep.progress(5, "reading baseline mesh")
        mesh = read_mesh(base)
        warnings = []
        comps, w = components(mesh, renum)
        warnings += w
        rep.progress(15, "loading CAD")
        cad = cadload.load(args.cad)
        fb = _read_features_bodies(args.features)
        body_of_part = {b.get("part"): b.get("body") for b in fb}
        byname = cad.by_name()
        missing = [c.part for c in comps if body_of_part.get(c.part) not in byname]
        if missing:
            # fall back to the section 4.1 rules (same result as extract when inputs did not change)
            pairs = cadload.correspond(cad, renum, args.body_map)
            body_of_part = {p: b.name for b, p, _ in pairs}
        extra = sorted(set(byname) - set(body_of_part.values()))
        if extra:
            raise PaicadError("GEOM_BODY_MAP_FAILED", f"unmatched bodies: [{', '.join(extra[:10])}]; unmatched parts: []")
    node_index = mesh.node_index()
    all_tags: list[NodeTags] = []
    skins: list[np.ndarray] = []
    parts_json = []
    bnd_total = unmatched_total = 0
    for k, comp in enumerate(comps):
        body = byname[body_of_part[comp.part]]
        tol = options.body_tol(opts, body.summary().bbox)
        rep.progress(20 + int(60 * k / max(1, len(comps))), f"classifying nodes: {comp.part}")
        tags, tris_local = tag_component(body, comp, node_index, mesh.xyz, tol, warnings)
        all_tags.append(tags)
        skins.append(tris_local)
        bk = tags.kind[tags.boundary]
        cnt = Counter(bk.tolist())
        bd = tags.dist[tags.boundary]
        matched = bd[bk != KIND_UNMATCHED]
        nb = int(tags.boundary.sum())
        nu = int(cnt.get(KIND_UNMATCHED, 0))
        bnd_total += nb
        unmatched_total += nu
        parts_json.append(
            {
                "part": comp.part,
                "body": body.name,
                "elem_range": [comp.elem_range[0], comp.elem_range[1]],
                "nodes": len(tags.node_ids),
                "boundary_nodes": nb,
                "classified": {
                    "vertex": int(cnt.get(KIND_VERTEX, 0)),
                    "edge": int(cnt.get(KIND_EDGE, 0)),
                    "face": int(cnt.get(KIND_FACE, 0)),
                    "interior": int(len(tags.node_ids) - nb),
                    "unmatched": nu,
                },
                "dist_mm": {"mean": rnd(matched.mean()) if matched.size else 0.0, "max": rnd(matched.max()) if matched.size else 0.0},
                "tol_mm": rnd(tol),
            }
        )
        if src is not None:  # asm-match.md section 5.6 (additive keys)
            parts_json[-1].update(pids=list(src.match.rows[k]["pids"]), renum_row=None)
    match_ratio = (bnd_total - unmatched_total) / bnd_total if bnd_total else 0.0
    if match_ratio < float(topt["min_match_ratio"]):
        dd = np.concatenate([t.dist[t.boundary] for t in all_tags])
        dd = dd[np.isfinite(dd)]
        doc = envelope(
            **doc_head,
            match_ratio=rnd(match_ratio),
            parts=parts_json,
            contacts=[],
            files={},
            warnings=warnings,
        )
        doc.update(
            status="FAIL",
            code="GEOM_BASELINE_MISMATCH",
            message=(
                f"nominal STEP and baseline mesh coordinates do not match (match_ratio {match_ratio:.4f}, "
                f"mean {float(dd.mean()) if dd.size else 0:.3f} mm, max {float(dd.max()) if dd.size else 0:.3f} mm) - check origin, units, shape"
                + (" - check the assembly match again" if src is not None else "")
            ),
        )
        out.write_text(TAG_JSON, dumps(doc))
        out.commit([TAG_JSON])
        rep.result("FAIL", "GEOM_BASELINE_MISMATCH", TAG_JSON)
        return EXIT_TAG
    if unmatched_total:
        warnings.append({"code": "TAG_UNMATCHED", "message": f"{unmatched_total} boundary nodes are unmatched (treated as free boundary)"})
    rep.progress(85, "detecting contact faces")
    contacts = detect_contacts(args, base, comps, all_tags, skins, mesh, node_index, cad, body_of_part, opts, src)
    # npz: one row per node (a node shared by two components is kept in the first)
    seen: set[int] = set()
    cols = {"node_id": [], "part": [], "kind": [], "entity": [], "uv": [], "dist": []}
    for pi, t in enumerate(all_tags):
        keep = np.array([int(n) not in seen for n in t.node_ids], dtype=bool)
        seen.update(int(n) for n in t.node_ids)
        cols["node_id"].append(t.node_ids[keep].astype(np.int64))
        cols["part"].append(np.full(int(keep.sum()), pi, dtype=np.int32))
        cols["kind"].append(t.kind[keep].astype(np.int8))
        cols["entity"].append(t.entity[keep].astype(np.int32))
        cols["uv"].append(t.uv[keep].astype(np.float64))
        d = t.dist[keep].astype(np.float64)
        cols["dist"].append(np.where(np.isfinite(d), d, -1.0))
    arrays = {k: np.concatenate(v) for k, v in cols.items()}
    with open(out.tmp_path(TAG_NPZ), "wb") as f:
        np.savez(f, **arrays)
    doc = envelope(**doc_head, match_ratio=rnd(match_ratio), parts=parts_json, contacts=contacts, files={"nodes": TAG_NPZ}, warnings=warnings)
    out.write_text(TAG_JSON, dumps(doc))
    out.commit([TAG_NPZ, TAG_JSON])
    rep.progress(100, f"tag done: match_ratio {match_ratio:.4f}")
    rep.result("OK", None, TAG_JSON)
    return EXIT_OK


def detect_contacts(args, base: Path | None, comps, all_tags, skins, mesh, node_index, cad, body_of_part, opts, src=None) -> list[dict]:
    """Section 6.1 step 6: face F is a contact face if >= contact_min_ratio of its face nodes lie within contact_mm."""
    topt = opts["tag"]
    cmm = float(topt["contact_mm"])
    cratio = float(topt["contact_min_ratio"])
    coords_of = [mesh.xyz[[node_index[int(n)] for n in t.node_ids]] for t in all_tags]
    lo = np.min([c.min(axis=0) for c in coords_of], axis=0)
    hi = np.max([c.max(axis=0) for c in coords_of], axis=0)
    bbox = np.concatenate([lo, hi])
    product = TriangleSet(src.product_surface(bbox, margin=10.0) if src is not None else collect_assembly_surface(args.assem_dir, [base], bbox, margin=10.0))
    # skin triangles of each component with their majority face id
    comp_tris = []
    for t, tris, coords in zip(all_tags, skins, coords_of):
        faces = np.full(len(tris), -1, dtype=np.int64)
        for i, tri in enumerate(tris):
            fk = [int(t.entity[j]) for j in tri if t.kind[j] == KIND_FACE]
            if fk:
                faces[i] = Counter(fk).most_common(1)[0][0]
        comp_tris.append((TriangleSet(coords[tris]) if len(tris) else TriangleSet(np.zeros((0, 3, 3))), faces))
    out = []
    for ci, (comp, t, coords) in enumerate(zip(comps, all_tags, coords_of)):
        fmask = t.kind == KIND_FACE
        if not fmask.any():
            continue
        ids = np.flatnonzero(fmask)
        dprod, _ = product.distance(coords[ids], cmm)
        for fid in sorted(set(t.entity[ids].tolist())):
            sel = t.entity[ids] == fid
            n_face = int(sel.sum())
            n_hit = int((dprod[sel] <= cmm).sum())
            if n_face and n_hit / n_face >= cratio:
                out.append({"part": comp.part, "face": f"F{fid}", "with": "PRODUCT", "nodes": n_hit})
        for cj, (ts, tri_faces) in enumerate(comp_tris):
            if cj == ci:
                continue
            d, ti = ts.distance(coords[ids], cmm)
            for fid in sorted(set(t.entity[ids].tolist())):
                sel = (t.entity[ids] == fid)
                n_face = int(sel.sum())
                hit = sel & (d <= cmm)
                if n_face and hit.sum() / n_face >= cratio:
                    other = Counter(int(tri_faces[x]) for x in ti[hit] if tri_faces[x] > 0).most_common(1)
                    of = f"F{other[0][0]}" if other else "F?"
                    out.append({"part": comp.part, "face": f"F{fid}", "with": f"{comps[cj].part}:{of}", "nodes": int(hit.sum())})
    return out
