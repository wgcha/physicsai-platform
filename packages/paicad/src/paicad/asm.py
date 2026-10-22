"""``paicad asm parts | check | write`` - assembly match (asm-match.md sections 4.2, 4.3, 5.1, 5.4, 6.1).

* ``parts``: include tree index (streaming + sha256 cache) -> every PART with elements (title, element kinds and
  counts, node count, TETRA4 volume, bbox, defining files) + 1:1 recommendation per STEP body (bbox IoU, volume
  ratio, name; RENUM ranges first when ``--renum-csv`` is given). ``--features`` needs no OCP.
* ``check``: per match row (body <-> pids, TETRA4 only) the skin nodes are classified on the body B-rep with the
  tag code (same tolerance, ``tol = max(tol_abs_mm, tol_rel * L_body)``, ``match_ratio >= min_match_ratio``);
  nodes shared with non-matched PART elements fail the row; origin / unit differences are diagnosed (never
  corrected); ``match_fe.glb`` carries ``_DIST_MM`` per skin node.
* ``write``: include tree copy where only the ``/NODE`` coordinate fields of the patch nodes change (section 6.4
  format, every other byte kept, ids unchanged); the assembly folder is only read.
"""

from __future__ import annotations

import hashlib
import math
import re
import shutil
import time
from pathlib import Path

import numpy as np

from . import bodymap, options
from .common import CODE_CATEGORY, EXIT_ASM, EXIT_INPUT, EXIT_OK, OutDir, PaicadError, Reporter, dumps, envelope, rnd, sha256_file, vec
from .mesh import asmtree
from .mesh.radioss import _TET_FACES, Component, node_line_id, read_renum_csv, rewrite_node_line
from .meshsrc import INVALID, AsmSource, _read_json, load_xyz, parse_rows

ASM_PARTS_JSON = "asm_parts.json"
ASM_CHECK_JSON = "asm_check.json"
ASM_WRITE_JSON = "asm_write.json"
MATCH_GLB = "match_fe.glb"
UNIT_FACTORS = (1000.0, 0.001, 25.4, 1.0 / 25.4, 10.0, 0.1)
SHARED_PARTS_MAX = 20
DUP_LIST_MAX = 10


def run(args, rep: Reporter) -> int:
    if args.asm_cmd == "parts":
        return run_parts(args, rep)
    if args.asm_cmd == "check":
        return run_check(args, rep)
    return run_write(args, rep)


def _info(rep: Reporter):
    return lambda m: rep.info(f"[asm] {m}")


# ------------------------------------------------------------------ parts
def _tet_volume(xyz: np.ndarray, conn_rows: np.ndarray) -> float:
    p = [xyz[conn_rows[:, i]] for i in range(4)]
    return float(np.abs(np.einsum("ij,ij->i", np.cross(p[1] - p[0], p[2] - p[0]), p[3] - p[0])).sum() / 6.0)


def part_summaries(idx: asmtree.AsmIndex) -> list[dict]:
    """Every PART with elements (asm-match.md section 4.2 ``parts``), pid order."""
    by_pid: dict[int, list[asmtree.Block]] = {}
    for b in idx.blocks:
        by_pid.setdefault(b.pid, []).append(b)
    out = []
    for pid in sorted(by_pid):
        bl = by_pid[pid]
        elems: dict[str, int] = {}
        for b in bl:
            elems[b.keyword] = elems.get(b.keyword, 0) + len(b.ids)
        flat = np.concatenate([b.conn.ravel() for b in bl])
        nodes = np.unique(flat[flat > 0])
        rows = idx.lookup(nodes)
        ok = rows[rows >= 0]
        solid = set(elems) == {"TETRA4"}
        vol = None
        if solid and ok.size == nodes.size:
            conn = np.concatenate([b.conn for b in bl])
            vol = rnd(_tet_volume(idx.node_xyz, idx.lookup(conn)), 3)
        pdef = idx.parts.get(pid)
        out.append(
            {
                "pid": pid,
                "title": pdef["title"] if pdef else "",
                "def_file": pdef["def_file"] if pdef else None,
                "elem_files": [idx.files[k].rel for k in sorted({b.file for b in bl})],
                "node_files": [idx.files[k].rel for k in sorted(set(idx.node_file[ok].tolist()))],
                "elems": dict(sorted(elems.items())),
                "nodes": int(nodes.size),
                "volume": vol,
                "bbox": vec(np.concatenate([idx.node_xyz[ok].min(axis=0), idx.node_xyz[ok].max(axis=0)])) if ok.size else None,
                "solid_ok": solid,
            }
        )
    return out


def _bodies(args) -> list[dict]:
    if args.features:
        doc, _ = _read_json(args.features, "features file", "GEOM_INPUT_INVALID")
        if not isinstance(doc, dict) or doc.get("schema_version") != 1 or not isinstance(doc.get("bodies"), list):
            raise PaicadError("GEOM_INPUT_INVALID", "features file: unsupported schema or missing bodies")
        return [{"body": b["body"], "volume": b.get("volume"), "bbox": b.get("bbox")} for b in doc["bodies"]]
    from . import cadload

    cad = cadload.load(args.cad)
    if any(b.name is None for b in cad.bodies):
        bodymap.match([b.name for b in cad.bodies], [])  # raises the unnamed-body error
    return [{"body": b.name, "volume": rnd(b.summary().volume), "bbox": vec(b.summary().bbox)} for b in cad.bodies]


def _iou(a, b) -> float:
    a, b = np.asarray(a, float), np.asarray(b, float)
    lo, hi = np.maximum(a[:3], b[:3]), np.minimum(a[3:], b[3:])
    inter = float(np.prod(np.clip(hi - lo, 0, None)))
    va, vb = float(np.prod(a[3:] - a[:3])), float(np.prod(b[3:] - b[:3]))
    uni = va + vb - inter
    return inter / uni if uni > 0 else 0.0


def _name_score(body: str, title: str) -> float:
    a, b = bodymap.normalize(body or ""), bodymap.normalize(title or "")
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return 0.5 if a in b or b in a else 0.0


def _basis(body: dict, bbox, volume, title: str, renum: bool) -> tuple[dict, bool, float]:
    """(basis, hard gate passed, score) of a body vs a PART (or a union of PARTs)."""
    bb = np.asarray(body["bbox"], float)
    pb = np.asarray(bbox, float)
    diag = float(np.linalg.norm(bb[3:] - bb[:3]))
    cdist = float(np.linalg.norm(0.5 * (bb[:3] + bb[3:]) - 0.5 * (pb[:3] + pb[3:])))
    vb, vp = float(body.get("volume") or 0.0), float(volume or 0.0)
    vr = min(vb, vp) / max(vb, vp) if vb > 0 and vp > 0 else 0.0
    iou = _iou(bb, pb)
    name = _name_score(body["body"], title)
    gate = cdist <= 0.1 * diag and vr >= 0.8
    score = 0.6 * iou + 0.3 * vr + 0.1 * name
    return {"bbox_iou": rnd(iou, 4), "volume_ratio": rnd(vr, 4), "name": name, "renum": renum}, gate, score


def _union(parts: list[dict]) -> tuple[list[float], float]:
    bb = np.array([p["bbox"] for p in parts], float)
    return list(np.concatenate([bb[:, :3].min(axis=0), bb[:, 3:].max(axis=0)])), float(sum(p["volume"] for p in parts))


def recommend(bodies: list[dict], parts: list[dict], idx: asmtree.AsmIndex, renum, min_score: float) -> list[dict]:
    """At most one row per body (1:1 draft, asm-match.md section 4.2): RENUM ranges first, then the hard gate
    (bbox centre distance <= 0.1 body diagonal, volume ratio >= 0.8) + Hungarian maximum of
    ``0.6 iou + 0.3 volume_ratio + 0.1 name``; rows below ``min_score`` are dropped."""
    from scipy.optimize import linear_sum_assignment

    cands = [p for p in parts if p["solid_ok"] and p["bbox"] and p["volume"]]
    usable = [b for b in bodies if b.get("bbox") and b.get("body")]
    rec: dict[str, dict] = {}
    used: set[int] = set()
    if renum:
        rows = sorted(renum, key=lambda r: r.elem_start)
        tet_ids = {p["pid"]: np.concatenate([b.ids for b in idx.pid_blocks(p["pid"]) if b.keyword == "TETRA4"]) for p in cands}
        max_id = max((int(v.max()) for v in tet_ids.values() if v.size), default=0)
        for k, r in enumerate(rows):
            lo, hi = r.elem_start, (rows[k + 1].elem_start - 1 if k + 1 < len(rows) else max_id)
            body = next((b for rule in (lambda s: s, lambda s: s.lower(), bodymap.normalize) for b in usable if rule(b["body"]) == rule(r.part)), None)
            pids = [p for p in cands if p["pid"] not in used and tet_ids[p["pid"]].size and tet_ids[p["pid"]].min() >= lo and tet_ids[p["pid"]].max() <= hi]
            if body is None or body["body"] in rec or not pids:
                continue
            bb, vol = _union(pids)
            basis, _, _ = _basis(body, bb, vol, " ".join(p["title"] for p in pids), True)
            rec[body["body"]] = {"body": body["body"], "pids": [p["pid"] for p in pids], "score": 1.0, "basis": basis}
            used.update(p["pid"] for p in pids)
    B = [b for b in usable if b["body"] not in rec]
    P = [p for p in cands if p["pid"] not in used]
    if B and P:
        S = np.zeros((len(B), len(P)))
        G = np.zeros((len(B), len(P)), dtype=bool)
        bases: dict[tuple[int, int], dict] = {}
        for i, b in enumerate(B):
            for j, p in enumerate(P):
                bases[i, j], G[i, j], S[i, j] = _basis(b, p["bbox"], p["volume"], p["title"], False)
        r_idx, c_idx = linear_sum_assignment(np.where(G, -S, 1.0e6))
        for i, j in zip(r_idx, c_idx):
            if G[i, j] and S[i, j] >= min_score:
                rec[B[i]["body"]] = {"body": B[i]["body"], "pids": [P[j]["pid"]], "score": rnd(S[i, j], 4), "basis": bases[i, j]}
    return [rec[b["body"]] for b in bodies if b.get("body") in rec]


def _tree_doc(idx: asmtree.AsmIndex) -> dict:
    return {
        "digest": idx.digest(),
        "starter": idx.starter,
        "tree": [{"rel": f.rel, "sha256": f.sha, "includes": list(f.includes)} for f in idx.files],
        "cache": dict(idx.cache),
    }


def run_parts(args, rep: Reporter) -> int:
    t0 = time.monotonic()
    options.load(args.options)
    aopt = options.asm_options(args.options)
    out = OutDir(args.out_dir, [ASM_PARTS_JSON])
    out.prepare()
    rep.progress(5, "indexing the include tree")
    idx = asmtree.build(args.assem_dir, args.cache_dir, _info(rep))
    rep.progress(60, "summarizing parts")
    parts = part_summaries(idx)
    if len(parts) > int(aopt["max_parts"]):
        raise PaicadError("ASM_TOO_MANY_PARTS", f"{len(parts)} parts with elements exceed asm_match.max_parts {aopt['max_parts']}")
    if not any(p["solid_ok"] for p in parts):
        raise PaicadError("ASM_NO_SOLID_PART", "no PART made of TETRA4 elements only in the include tree")
    rep.progress(75, "reading bodies")
    bodies = _bodies(args)
    renum = read_renum_csv(args.renum_csv) if args.renum_csv else None
    rec = recommend(bodies, parts, idx, renum, float(aopt["recommend_min_score"]))
    doc = envelope(status="OK", code=None, message=None, assem=_tree_doc(idx), bodies=bodies, parts=parts, recommend=rec, warnings=list(idx.warnings), elapsed_s=rnd(time.monotonic() - t0, 3))
    out.write_text(ASM_PARTS_JSON, dumps(doc))
    out.commit([ASM_PARTS_JSON])
    rep.progress(100, f"asm parts: {len(idx.files)} files, {len(parts)} parts, {len(rec)} recommended")
    rep.result("OK", None, ASM_PARTS_JSON)
    return EXIT_OK


# ------------------------------------------------------------------ check
def _row_tets(idx: asmtree.AsmIndex, pids: list[int]) -> tuple[np.ndarray, np.ndarray, list[str]]:
    tb = [b for p in pids for b in idx.pid_blocks(p) if b.keyword == "TETRA4"]
    other = sorted({b.keyword for p in pids for b in idx.pid_blocks(p) if b.keyword != "TETRA4"})
    ids = np.concatenate([b.ids for b in tb]) if tb else np.zeros(0, dtype=np.int64)
    conn = np.concatenate([b.conn for b in tb]) if tb else np.zeros((0, 4), dtype=np.int64)
    o = np.argsort(ids, kind="stable")
    return ids[o], conn[o], other


def _skin_with_elems(tets: np.ndarray, elem_ids: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Skin triangles (node ids, same order as ``skin_triangles``) and their element ids."""
    faces = tets[:, _TET_FACES].reshape(-1, 3)
    _, inv, cnt = np.unique(np.sort(faces, axis=1), axis=0, return_inverse=True, return_counts=True)
    keep = cnt[inv.ravel()] == 1
    return faces[keep], elem_ids[np.flatnonzero(keep) // 4]


def _stats(d: np.ndarray) -> dict:
    if d.size == 0:
        return {"mean": None, "p95": None, "p99": None, "max": None}
    return {"mean": rnd(float(d.mean())), "p95": rnd(float(np.percentile(d, 95))), "p99": rnd(float(np.percentile(d, 99))), "max": rnd(float(d.max()))}


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", name) or "body"


def _feature_faces(features_path: str | None, body: str) -> dict[int, list[str]]:
    if not features_path:
        return {}
    doc, _ = _read_json(features_path, "features file", "GEOM_INPUT_INVALID")
    out: dict[int, list[str]] = {}
    for f in doc.get("features") or []:
        if f.get("body") != body:
            continue
        fs = set((f.get("faces") or {}).get("moving") or []) | set((f.get("faces") or {}).get("fixed") or []) | set((f.get("measure") or {}).get("faces") or [])
        for x in fs:
            try:
                out.setdefault(int(str(x).lstrip("F")), []).append(f["name"])
            except ValueError:
                continue
    return out


def _uncovered(topo, kind: np.ndarray, ent: np.ndarray) -> list[int]:
    from .tag import KIND_EDGE, KIND_FACE, KIND_VERTEX

    covered: set[int] = set(int(e) for e in ent[kind == KIND_FACE])
    for e in set(int(x) for x in ent[kind == KIND_EDGE]):
        covered.update(topo.edge(e).faces)
    verts = set(int(x) for x in ent[kind == KIND_VERTEX])
    if verts:
        for ed in topo.edges:
            if verts & set(ed.vertices):
                covered.update(ed.faces)
    return [f.id for f in topo.faces if f.id not in covered]


def _classify(body, comp: Component, node_index: dict, xyz: np.ndarray, tol: float):
    from .tag import KIND_UNMATCHED, tag_component

    tags, tris = tag_component(body, comp, node_index, xyz, tol, [])
    b = tags.boundary
    nb = int(b.sum())
    ratio = float((tags.kind[b] != KIND_UNMATCHED).sum()) / nb if nb else 0.0
    return tags, tris, ratio


def run_check(args, rep: Reporter) -> int:
    from . import cadload
    from .tag import KIND_UNMATCHED
    from .view import generator, gltf, load_view_options
    from .view.export import ROOT_EXTRAS

    t0 = time.monotonic()
    opts = options.load(args.options)
    aopt = options.asm_options(args.options)
    topt = opts["tag"]
    min_ratio = float(topt["min_match_ratio"])
    out = OutDir(args.out_dir, [ASM_CHECK_JSON, MATCH_GLB])
    out.prepare()
    mdoc, mbytes = _read_json(args.match, "match rows file", INVALID)
    mr = parse_rows(mdoc)
    rows_sha = hashlib.sha256(mbytes).hexdigest()
    rep.progress(5, "indexing the include tree")
    idx = asmtree.build(args.assem_dir, args.cache_dir, _info(rep))
    have = {b.pid for b in idx.blocks}
    missing = sorted({p for r in mr.rows for p in r["pids"]} - have)
    if missing:
        raise PaicadError(INVALID, f"PART ids without elements in the include tree: {', '.join(map(str, missing[:10]))}")
    rep.progress(25, "loading CAD")
    cad = cadload.load(args.cad)
    byname = cad.by_name()
    nob = [r["body"] for r in mr.rows if r["body"] not in byname]
    if nob:
        raise PaicadError(INVALID, f"match rows name bodies that are not in the CAD: {', '.join(nob[:10])}")
    matched = {p for r in mr.rows for p in r["pids"]}
    other = [b for b in idx.blocks if b.pid not in matched]
    o_conn = np.concatenate([b.conn.ravel() for b in other]) if other else np.zeros(0, dtype=np.int64)
    o_pid = np.concatenate([np.full(b.conn.size, b.pid, dtype=np.int64) for b in other]) if other else np.zeros(0, dtype=np.int64)
    nz = o_conn > 0
    o_conn, o_pid = o_conn[nz], o_pid[nz]
    worst_n = int(aopt["worst_nodes"])
    rows_out: list[dict] = []
    warnings: list[dict] = list(idx.warnings)
    glb_items: list = []
    skins: dict[int, tuple[np.ndarray, np.ndarray, float]] = {}  # row -> (skin node xyz, bbox, tol)
    worst_rels: list[str] = []
    used_names: set[str] = set()
    elem_files: set[int] = set()
    node_rows_all: list[np.ndarray] = []
    for k, r in enumerate(mr.rows):
        rep.progress(30 + int(55 * k / max(1, len(mr.rows))), f"checking {r['body']}")
        body = byname[r["body"]]
        topo = body.topology()
        tol = options.body_tol(opts, body.summary().bbox)
        row: dict = {
            "body": r["body"],
            "pids": r["pids"],
            "status": "PASS",
            "code": None,
            "skin_nodes": 0,
            "match_ratio": None,
            "tol_mm": rnd(tol),
            "dist_mm": _stats(np.zeros(0)),
            "bbox_delta_mm": None,
            "faces": {"total": len(topo.faces), "uncovered": []},
            "shared": {"nodes": 0, "parts": []},
            "worst": None,
            "suggest": None,
        }
        rows_out.append(row)
        # shared nodes (AM-8): row nodes referenced by elements of non-matched PARTs
        allconn = np.concatenate([b.conn.ravel() for p in r["pids"] for b in idx.pid_blocks(p)])
        rnodes = np.unique(allconn[allconn > 0])
        hit = np.isin(o_conn, rnodes)
        if hit.any():
            pairs = np.unique(np.stack([o_pid[hit], o_conn[hit]], axis=1), axis=0)
            pid_u, cnt = np.unique(pairs[:, 0], return_counts=True)
            order = sorted(zip(pid_u.tolist(), cnt.tolist()), key=lambda t: (-t[1], t[0]))[:SHARED_PARTS_MAX]
            row["shared"] = {
                "nodes": int(np.unique(pairs[:, 1]).size),
                "parts": [{"pid": int(p), "title": (idx.parts.get(int(p)) or {}).get("title", ""), "nodes": int(c)} for p, c in order],
            }
        ids, conn, kinds = _row_tets(idx, r["pids"])
        elem_files.update(b.file for p in r["pids"] for b in idx.pid_blocks(p) if b.keyword == "TETRA4")
        if kinds or ids.size == 0:
            row.update(status="FAIL", code="GEOM_UNSUPPORTED_ELEMENT", message=f"non-TETRA4 elements: {', '.join('/' + x for x in kinds)}")
            continue
        nodes = np.unique(conn)
        nrows = idx.lookup(nodes)
        if (nrows < 0).any():
            raise PaicadError("GEOM_INPUT_INVALID", f"{int((nrows < 0).sum())} nodes of {r['body']} have no /NODE line in the include tree (first {int(nodes[nrows < 0][0])})")
        node_rows_all.append(nrows)
        xyz = idx.node_xyz[nrows]
        node_index = {int(n): i for i, n in enumerate(nodes)}
        comp = Component(r["body"], k + 1, (int(ids[0]), int(ids[-1])), ids, conn, nodes)
        tags, tris_local, ratio = _classify(body, comp, node_index, xyz, tol)
        bmask = tags.boundary
        bidx = np.flatnonzero(bmask)
        dist = np.zeros(len(nodes))
        dist[bidx] = tags.dist[bidx]
        um = bidx[tags.kind[bidx] == KIND_UNMATCHED]
        if um.size:
            dist[um] = body.distance(xyz[um])  # exact distance for the nodes beyond tol (report only)
        db = dist[bidx]
        db = np.where(np.isfinite(db), db, 0.0)
        skin_xyz = xyz[bidx]
        sbb = np.concatenate([skin_xyz.min(axis=0), skin_xyz.max(axis=0)])
        bbb = np.asarray(body.summary().bbox, float)
        row.update(skin_nodes=int(bidx.size), match_ratio=rnd(ratio), dist_mm=_stats(db), bbox_delta_mm=vec(sbb - bbb))
        skins[k] = (skin_xyz, sbb, tol)
        ff = _feature_faces(args.features, r["body"])
        unc = _uncovered(topo, tags.kind[bidx], tags.entity[bidx])
        row["faces"]["uncovered"] = [{"face": f"F{f}", "features": sorted(set(ff.get(f, [])))} for f in unc]
        if unc:
            warnings.append({"code": "ASM_FACE_UNCOVERED", "body": r["body"], "faces": [f"F{f}" for f in unc][:20], "message": f"{len(unc)} faces of {r['body']} have no node within tol"})
        # worst nodes
        wo = np.argsort(-db, kind="stable")[: min(worst_n, db.size)]
        name = f"worst_{_safe(r['body'])}"
        while name in used_names:
            name += "_"
        used_names.add(name)
        rel = f"{name}.npz"
        with open(out.tmp_path(rel), "wb") as fh:
            np.savez(fh, node_id=nodes[bidx][wo].astype(np.int64), xyz=skin_xyz[wo].astype(np.float64), dist=db[wo].astype(np.float64))
        worst_rels.append(rel)
        row["worst"] = {"count": int(wo.size), "file": rel}
        if ratio < min_ratio:
            row.update(status="FAIL", code="ASM_BOUNDARY_MISMATCH")
            row["suggest"] = _suggest(body, comp, node_index, xyz, tol, sbb, bbb, min_ratio)
        elif row["shared"]["nodes"]:
            row.update(status="FAIL", code="ASM_SHARED_NODES")
        # FE skin GLB node (geometry-view FE GLB layout + _DIST_MM)
        skin_ids, skin_el = _skin_with_elems(conn, ids)
        loc = np.searchsorted(nodes, skin_ids)
        used, tri = np.unique(loc, return_inverse=True)
        tri = tri.reshape(-1, 3)
        P = xyz[used]
        w = np.cross(P[tri[:, 1]] - P[tri[:, 0]], P[tri[:, 2]] - P[tri[:, 0]])
        N = np.zeros_like(P)
        for c in range(3):
            np.add.at(N, tri[:, c], w)
        nn = np.linalg.norm(N, axis=1)
        N = np.where(nn[:, None] > 0, N / np.where(nn > 0, nn, 1.0)[:, None], np.array([0.0, 0.0, 1.0]))
        E = np.full(len(used), np.iinfo(np.int64).max, dtype=np.int64)
        for c in range(3):
            np.minimum.at(E, tri[:, c], skin_el)
        D = np.where(np.isfinite(dist[used]), dist[used], 0.0)
        glb_items.append(gltf.TriMesh(r["body"], P, tri, N, {"_DIST_MM": D.astype(np.float32), "_ELEM_ID": E.astype(np.uint32)}, False))
    for row in rows_out:  # row PASS needs shared.nodes == 0 as well (rule 3)
        if row["status"] == "PASS" and row["shared"]["nodes"]:
            row.update(status="FAIL", code="ASM_SHARED_NODES")
    # rule 8: two rows at the same place
    keys = sorted(skins)
    for a in range(len(keys)):
        for b in range(a + 1, len(keys)):
            pa, ba, ta = skins[keys[a]]
            pb, bbx, tb = skins[keys[b]]
            t = max(ta, tb)
            if np.all(np.abs(ba - bbx) <= t):
                from scipy.spatial import cKDTree

                d, _ = cKDTree(pb).query(pa, distance_upper_bound=t)
                d2, _ = cKDTree(pa).query(pb, distance_upper_bound=t)
                if (d <= t).mean() >= 0.9 and (d2 <= t).mean() >= 0.9:
                    warnings.append({"code": "ASM_DUPLICATE_PART", "bodies": [rows_out[keys[a]]["body"], rows_out[keys[b]]["body"]], "message": "two match rows have skins at the same place"})
    # files of the matched nodes
    nfile: dict[int, int] = {}
    if node_rows_all:
        allrows = np.unique(np.concatenate(node_rows_all))
        fu, fc = np.unique(idx.node_file[allrows], return_counts=True)
        nfile = dict(zip(fu.tolist(), fc.tolist()))
    file_checks = {
        "shared_nodes": int(sum(r["shared"]["nodes"] for r in rows_out)),
        "duplicate_node_defs": len(idx.duplicates),
        "duplicate_parts": list(idx.duplicate_parts),
        "duplicate_nodes": idx.duplicates[:DUP_LIST_MAX],
    }
    fails = [r for r in rows_out if r["status"] != "PASS"]
    if idx.duplicates:
        status, code = "FAIL", "GEOM_INPUT_INVALID"
        d0 = idx.duplicates[0]
        message = f"{len(idx.duplicates)} node ids are defined more than once in the include tree (first {d0['node']}: {', '.join(d0['files'])})"
    elif fails:
        status, code = "FAIL", fails[0]["code"]
        message = "; ".join(_row_message(r) for r in fails[:3]) + (f" (+{len(fails) - 3} more)" if len(fails) > 3 else "")
    else:
        status, code, message = "PASS", None, None
    for r in rows_out:
        r.pop("message", None)
    glb = None
    rels = list(worst_rels)
    if not args.no_glb and glb_items:
        data = gltf.write_glb(glb_items, generator(), root_extras=ROOT_EXTRAS)
        if len(data) <= int(load_view_options(None)["max_glb_bytes"]):
            with open(out.tmp_path(MATCH_GLB), "wb") as fh:
                fh.write(data)
            rels.append(MATCH_GLB)
            glb = {"file": MATCH_GLB, "sha256": hashlib.sha256(data).hexdigest()}
        else:
            warnings.append({"code": "VIEW_TOO_LARGE", "message": f"match GLB exceeds max_glb_bytes ({len(data)} bytes) - not written"})
    doc = envelope(
        status=status,
        code=code,
        category=CODE_CATEGORY.get(code) if code else None,
        message=message,
        rows_sha256=rows_sha,
        assem={
            "digest": idx.digest(),
            "starter": idx.starter,
            "node_files": [{"rel": idx.files[f].rel, "nodes": int(c)} for f, c in sorted(nfile.items())],
            "elem_files": [idx.files[f].rel for f in sorted(elem_files)],
            "cache": dict(idx.cache),
        },
        tolerance={"abs_mm": topt["tol_abs_mm"], "rel": topt["tol_rel"], "min_match_ratio": topt["min_match_ratio"]},
        rows=rows_out,
        excluded_bodies=list(mr.excluded),
        file_checks=file_checks,
        glb=glb,
        warnings=warnings,
        elapsed_s=rnd(time.monotonic() - t0, 3),
    )
    out.write_text(ASM_CHECK_JSON, dumps(doc))
    out.commit(rels + [ASM_CHECK_JSON])
    rep.progress(100, f"asm check {status}")
    rep.result(status, code, ASM_CHECK_JSON)
    if status == "PASS":
        return EXIT_OK
    return EXIT_ASM if code != "GEOM_INPUT_INVALID" else EXIT_INPUT


def _row_message(r: dict) -> str:
    if r["code"] == "ASM_BOUNDARY_MISMATCH":
        m = f"{r['body']}: skin nodes do not match the CAD boundary (match_ratio {r['match_ratio']:.4f}, max {r['dist_mm']['max']} mm)"
        s = r.get("suggest") or {}
        if s.get("code") == "ASM_UNIT_SUSPECT":
            m += f" - unit factor {s['factor']:g} suspected"
        elif s.get("code") == "ASM_OFFSET_SUSPECT":
            m += f" - CAD offset {s['translate_mm']} mm suspected"
        return m + " - export the CAD with the assembly origin and mm"
    if r["code"] == "ASM_SHARED_NODES":
        return f"{r['body']}: {r['shared']['nodes']} nodes shared with other PARTs (" + ", ".join(f"{p['pid']}" for p in r["shared"]["parts"][:5]) + ")"
    return f"{r['body']}: {r.get('message') or r['code']}"


def _suggest(body, comp: Component, node_index: dict, xyz: np.ndarray, tol: float, sbb: np.ndarray, bbb: np.ndarray, min_ratio: float) -> dict | None:
    """Rule 6 diagnosis (blocking, never applied): unit factor from the bbox diagonal ratio, else a translation
    by the bbox centre difference re-measured with the same classification."""
    db = float(np.linalg.norm(bbb[3:] - bbb[:3]))
    ds = float(np.linalg.norm(sbb[3:] - sbb[:3]))
    if db <= 0:
        return None
    s = ds / db
    for k in UNIT_FACTORS:
        if abs(s / k - 1.0) <= 0.01:
            return {"code": "ASM_UNIT_SUSPECT", "factor": k if k >= 1 else rnd(k, 9)}
    if abs(s - 1.0) <= 0.01:
        t = 0.5 * (sbb[:3] + sbb[3:]) - 0.5 * (bbb[:3] + bbb[3:])
        if float(np.linalg.norm(t)) <= 0:
            return None
        _, _, ratio = _classify(body, comp, node_index, xyz - t, tol)
        if ratio >= min_ratio:
            return {"code": "ASM_OFFSET_SUSPECT", "translate_mm": vec(t, 3), "match_ratio_after": rnd(ratio)}
    return None


# ------------------------------------------------------------------ write
def run_write(args, rep: Reporter) -> int:
    t0 = time.monotonic()
    assem = Path(args.assem_dir)
    outp = Path(args.out_dir)
    a_real, o_real = assem.resolve(), outp.resolve()
    if o_real == a_real or a_real in o_real.parents:
        raise PaicadError("GEOM_INPUT_INVALID", "--out-dir must not be the assembly folder or inside it (the assembly folder is only read)")
    rep.progress(5, "indexing the include tree")
    src = AsmSource(args.asm_match, args.assem_dir, args.cache_dir, _info(rep))
    idx = src.index
    patch: dict[int, tuple[float, float, float]] = {}
    pinfo = None
    if args.patch:
        ids, xyz = load_xyz(args.patch, "node patch")
        if np.unique(ids).size != ids.size:
            raise PaicadError(INVALID, "node patch has duplicate node ids")
        extra = np.setdiff1d(ids, src.mesh.node_ids)
        if extra.size:
            raise PaicadError(INVALID, f"node patch has {extra.size} nodes without a definition line among the matched PART nodes (first {int(extra[0])})")
        patch = {int(n): (float(a), float(b), float(c)) for n, (a, b, c) in zip(ids, xyz)}
        pinfo = {"name": Path(args.patch).name, "sha256": sha256_file(args.patch)}
    rels = [f.rel for f in idx.files]
    out = OutDir(args.out_dir, rels + [ASM_WRITE_JSON])
    out.prepare()
    at: dict[int, dict[int, int]] = {}
    if patch:
        pid = np.array(sorted(patch), dtype=np.int64)
        prow = idx.lookup(pid)
        for n, r in zip(pid.tolist(), prow.tolist()):
            at.setdefault(int(idx.node_file[r]), {})[int(idx.node_line[r])] = n
    files = []
    for k, tf in enumerate(idx.files):
        rep.progress(10 + int(85 * k / max(1, len(idx.files))), f"writing {tf.rel}")
        dst = out.tmp_path(tf.rel)
        lines = at.get(k)
        if not lines:
            shutil.copyfile(tf.path, dst)
            files.append({"rel": tf.rel, "changed_lines": 0})
            continue
        changed = 0
        with open(tf.path, "rb") as fi, open(dst, "wb") as fo:
            for ln, raw in enumerate(fi):
                n = lines.get(ln)
                if n is not None:
                    if node_line_id(raw) != n:
                        raise PaicadError("GEOM_INTERNAL", f"node {n}: {tf.rel} line {ln + 1} is not its definition line")
                    new = rewrite_node_line(raw, patch)
                    _verify(new, raw, n, patch[n], tf.rel, ln)
                    if new != raw:
                        changed += 1
                    raw = new
                fo.write(raw)
        files.append({"rel": tf.rel, "changed_lines": changed})
    doc = envelope(
        status="OK",
        code=None,
        message=None,
        assem={"digest": idx.digest(), "starter": idx.starter, "cache": dict(idx.cache)},
        patch=pinfo,
        files=files,
        nodes_written=len(patch),
        elapsed_s=rnd(time.monotonic() - t0, 3),
    )
    out.write_text(ASM_WRITE_JSON, dumps(doc))
    out.commit(rels + [ASM_WRITE_JSON])
    rep.progress(100, f"asm write: {len(files)} files, {sum(f['changed_lines'] for f in files)} node lines changed")
    rep.result("OK", None, ASM_WRITE_JSON)
    return EXIT_OK


def _verify(line: bytes, old: bytes, nid: int, want: tuple[float, float, float], rel: str, ln: int) -> None:
    """Read the rewritten line back (fixed columns first, like every reader): same id, same length and line end
    (section 6.4 field widths), coordinates = patch values to the written precision."""
    r = asmtree._node_b(line)
    if r is None or r[0] != nid or len(line) != len(old) or line[len(line.rstrip(b"\r\n")) :] != old[len(old.rstrip(b"\r\n")) :]:
        raise PaicadError("GEOM_INTERNAL", f"{rel} line {ln + 1}: rewritten node line of {nid} cannot be read back with the same id and width")
    for got, w in zip(r[1:], want):
        if not math.isclose(got, w, rel_tol=1e-6, abs_tol=1e-9 * max(1.0, abs(w))):
            raise PaicadError("GEOM_INC_FORMAT", f"{rel} line {ln + 1}: rewritten coordinate {got!r} differs from {w!r}")
