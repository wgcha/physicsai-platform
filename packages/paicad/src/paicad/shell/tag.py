"""``paicad shell tag`` - classify shell nodes onto the mid-surface B-rep (shell-morph sections 4.6, 6.2).

Every node of the shell part is a boundary node (no interior): vertex -> edge -> face within
``tol = max(tol_abs_mm, tol_rel * L_body)`` (solid tag rules, GE section 6.1), triangle consistency, then
the fixed set of ``--fixed-dir`` is marked and the mesh geodesic distance to it (edge-length weighted
Dijkstra) is stored for the transition zone.
"""

from __future__ import annotations

import time
from collections import Counter
from pathlib import Path

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import dijkstra

from ..common import EXIT_OK, EXIT_TAG, OutDir, PaicadError, Reporter, dumps, rnd
from ..tag import KIND_EDGE, KIND_FACE, KIND_UNMATCHED, KIND_VERTEX, _consistency, classify_points
from ..update import read_json
from . import opts as shopts
from .assem import read_assembly
from .cad import correspond, load
from .common import load_shell_features, shell_envelope
from .fixed import load_fixed, part_mesh

TAG_JSON = "shell_tag.json"
TAG_NPZ = "shell_tag_nodes.npz"


def quad_tris(conn_local: np.ndarray, tri: np.ndarray) -> np.ndarray:
    """Triangles (local node indices) of shell elements: quads split 0-1-2 / 0-2-3."""
    t1 = conn_local[:, [0, 1, 2]]
    t2 = conn_local[~tri][:, [0, 2, 3]]
    return np.concatenate([t1, t2])


def mesh_edges(conn_local: np.ndarray, tri: np.ndarray) -> np.ndarray:
    q = conn_local
    e = np.concatenate([q[:, [0, 1]], q[:, [1, 2]], q[~tri][:, [2, 3]], q[~tri][:, [3, 0]], q[tri][:, [2, 0]]])
    e = e[e[:, 0] != e[:, 1]]
    return np.unique(np.sort(e, axis=1), axis=0)


def geodesic_to(xyz: np.ndarray, edges: np.ndarray, sources: np.ndarray) -> np.ndarray:
    n = len(xyz)
    if len(sources) == 0:
        return np.full(n, np.inf)
    w = np.linalg.norm(xyz[edges[:, 0]] - xyz[edges[:, 1]], axis=1)
    g = coo_matrix((w, (edges[:, 0], edges[:, 1])), shape=(n, n)).tocsr()
    return dijkstra(g, directed=False, indices=sources, min_only=True)


def edge_respect(body, kind, ent, conn_local, tri) -> list[int]:
    """B-rep edges between two faces that the mesh crosses (> 50 % of the touching elements)."""
    topo = body.topology()
    bad = []
    cross: Counter = Counter()
    touch: Counter = Counter()
    pair_edge = {}
    for e in topo.edges:
        if len(e.faces) == 2:
            pair_edge.setdefault(tuple(sorted(e.faces)), []).append(e.id)
    for el, t in zip(conn_local, tri):
        nodes = el[:3] if t else el
        fs = {int(ent[i]) for i in nodes if kind[i] == KIND_FACE}
        es = {int(ent[i]) for i in nodes if kind[i] == KIND_EDGE}
        for e in es:
            touch[e] += 1
        if len(fs) == 2:
            for e in pair_edge.get(tuple(sorted(fs)), []):
                cross[e] += 1
    for e, c in sorted(cross.items()):
        if c > 0.5 * (c + touch.get(e, 0)):
            bad.append(e)
    return bad


def run(args, rep: Reporter) -> int:
    t0 = time.monotonic()
    o = shopts.load(args.options)
    out = OutDir(args.out_dir, [TAG_JSON, TAG_NPZ])
    out.prepare()
    topt = o["tag"]
    doc = load_shell_features(args.features)
    fixed = load_fixed(args.fixed_dir)
    rep.progress(5, "reading the assembly folder")
    asm = read_assembly(args.assem_dir)
    if fixed.doc.get("assem_digest") and fixed.doc["assem_digest"] != asm.digest():
        raise PaicadError("GEOM_INPUT_INVALID", "fixed-scan output was made from a different assembly folder (assem_digest differs)")
    rep.progress(15, "loading mid-surface CAD")
    cad = load(args.cad)
    byname = cad.by_name()
    pairs = []
    corr = None
    for p in doc["parts"]:
        pid = p.get("part_id")
        if pid is None or p["body"] not in byname:
            corr = corr or correspond([b.name for b in cad.bodies], asm, args.body_map)
            pid = corr.get(p["body"], (None, ""))[0]
        if pid is None or p["body"] not in byname:
            raise PaicadError("GEOM_BODY_MAP_FAILED", f"body {p['body']!r} has no shell part")
        pairs.append((byname[p["body"]], int(pid)))
    extra = sorted(set(byname) - {b.name for b, _ in pairs})
    if extra:
        raise PaicadError("GEOM_BODY_MAP_FAILED", f"unmatched bodies: [{', '.join(extra[:10])}]")
    head = dict(status="OK", code=None, message=None, tolerance={"abs_mm": topt["tol_abs_mm"], "rel": topt["tol_rel"]})
    warnings: list[dict] = []
    parts_json = []
    cols = {k: [] for k in ("node_id", "part", "kind", "entity", "uv", "dist", "fixed", "geo_dist_fixed")}
    seen: set[int] = set()
    total = unmatched = 0
    fset = fixed.node_id
    trans = float(o["fixed"]["transition_mm"])
    for pi, (body, pid) in enumerate(pairs):
        pm = part_mesh(asm, pid)
        other = [b for b in asm.part_blocks(pid) if b.keyword not in ("SHELL", "SH3N")]
        if other:
            raise PaicadError("SHELL_UNSUPPORTED_ELEMENT", f"part {pid}: {sum(len(b.ids) for b in other)} non-shell elements (/{other[0].keyword})")
        if len(pm.elem_ids) == 0:
            raise PaicadError("SHELL_PART_NOT_FOUND", f"shell part {pid} has no /SHELL or /SH3N element")
        rows = asm.index(pm.node_ids)
        if np.any(rows < 0):
            raise PaicadError("GEOM_INPUT_INVALID", f"part {pid}: {int(np.sum(rows < 0))} element nodes without /NODE")
        xyz = asm.xyz[rows]
        conn_local = np.searchsorted(pm.node_ids, pm.conn)
        tol = shopts.body_tol(o, body.summary().bbox)
        rep.progress(20 + int(60 * pi / max(1, len(pairs))), f"classifying nodes: part {pid}")
        kind, ent, uv, dist = classify_points(body, xyz, tol)
        tris = quad_tris(conn_local, pm.tri)
        _consistency(body, xyz, kind, ent, uv, dist, tris, tol, warnings, str(pid))
        bad_edges = edge_respect(body, kind, ent, conn_local, pm.tri)
        if bad_edges:
            warnings.append({"code": "TAG_EDGE_NOT_RESPECTED", "part_id": pid, "edges": [f"E{e}" for e in bad_edges[:50]],
                             "message": f"the mesh crosses {len(bad_edges)} B-rep edges (nodes are mapped per face)"})
        is_fixed = np.isin(pm.node_ids, fset)
        g = geodesic_to(xyz, mesh_edges(conn_local, pm.tri), np.flatnonzero(is_fixed))
        g[is_fixed] = 0.0
        cnt = Counter(kind.tolist())
        nu = int(cnt.get(KIND_UNMATCHED, 0))
        total += len(kind)
        unmatched += nu
        md = dist[kind != KIND_UNMATCHED]
        parts_json.append(
            {
                "part_id": pid, "body": body.name, "nodes": int(len(kind)),
                "elements": {"quad": int((~pm.tri).sum()), "tri": int(pm.tri.sum())},
                "classified": {"vertex": int(cnt.get(KIND_VERTEX, 0)), "edge": int(cnt.get(KIND_EDGE, 0)), "face": int(cnt.get(KIND_FACE, 0)), "unmatched": nu},
                "fixed": int(is_fixed.sum()),
                "transition": int(((g > 0) & (g < trans)).sum()),
                "dist_mm": {"mean": rnd(md.mean()) if md.size else 0.0, "max": rnd(md.max()) if md.size else 0.0},
                "tol_mm": rnd(tol),
            }
        )
        keep = np.array([int(n) not in seen for n in pm.node_ids], dtype=bool)
        seen.update(int(n) for n in pm.node_ids)
        cols["node_id"].append(pm.node_ids[keep])
        cols["part"].append(np.full(int(keep.sum()), pi, dtype=np.int32))
        cols["kind"].append(kind[keep].astype(np.int8))
        cols["entity"].append(ent[keep].astype(np.int32))
        cols["uv"].append(uv[keep].astype(float))
        cols["dist"].append(np.where(np.isfinite(dist[keep]), dist[keep], -1.0))
        cols["fixed"].append(is_fixed[keep])
        cols["geo_dist_fixed"].append(g[keep].astype(float))
    ratio = (total - unmatched) / total if total else 0.0
    base = dict(head, match_ratio=rnd(ratio), parts=parts_json, fixed_digest=fixed.digest, assem_digest=asm.digest())
    if ratio < float(topt["min_match_ratio"]):
        d = shell_envelope(**base, files={}, warnings=warnings)
        d.update(status="FAIL", code="GEOM_BASELINE_MISMATCH", category="PREP",
                 message=f"shell nodes are not on the mid-surface (match_ratio {ratio:.4f}) - check that the mesh is a mid-surface mesh, not an offset / skin mesh")
        out.write_text(TAG_JSON, dumps(d))
        out.commit([TAG_JSON])
        rep.result("FAIL", "GEOM_BASELINE_MISMATCH", TAG_JSON)
        return EXIT_TAG
    if unmatched:
        warnings.append({"code": "TAG_UNMATCHED", "message": f"{unmatched} shell nodes are unmatched (moved as free nodes)"})
    arrays = {k: np.concatenate(v) for k, v in cols.items()}
    arrays["kind"] = arrays["kind"].astype(np.int8)
    with open(out.tmp_path(TAG_NPZ), "wb") as f:
        np.savez(f, **arrays)
    d = shell_envelope(**base, files={"nodes": TAG_NPZ}, warnings=warnings, elapsed_s=rnd(time.monotonic() - t0, 3))
    out.write_text(TAG_JSON, dumps(d))
    out.commit([TAG_NPZ, TAG_JSON])
    rep.progress(100, f"shell tag done: match_ratio {ratio:.4f}")
    rep.result("OK", None, TAG_JSON)
    return EXIT_OK


def load_shell_tag(tag_dir: str | Path) -> tuple[dict, dict]:
    d = Path(tag_dir)
    doc = read_json(d / TAG_JSON, TAG_JSON)
    if doc.get("status") != "OK" or doc.get("kind") != "shell":
        raise PaicadError("GEOM_INPUT_INVALID", "shell_tag.json is not an OK shell tag report")
    try:
        z = np.load(d / (doc.get("files") or {}).get("nodes", TAG_NPZ))
        arr = {k: np.asarray(z[k]) for k in ("node_id", "part", "kind", "entity", "uv", "dist", "fixed", "geo_dist_fixed")}
    except (OSError, KeyError, ValueError) as ex:
        raise PaicadError("GEOM_INPUT_INVALID", f"cannot read shell tag nodes file: {ex.__class__.__name__}") from None
    return doc, arr
