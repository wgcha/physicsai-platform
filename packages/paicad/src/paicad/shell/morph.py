"""``paicad shell morph`` - shell node coordinates onto the sample sheet (shell-morph sections 4.8, 6.5).

Per node (tag classification): fixed -> 0 (target checked against ``fixed.tol_mm``); vertex / edge ->
sample vertex / same normalized arc length on the sample edge (unchanged entities: 0); curved faces with a
changed surface -> same normalized (u,v) on the sample face; planar faces with a changed surface (normal
kept) and boundary-changed faces -> normal offset + in-surface solve (``fem2d``) with the face boundary,
fixed nodes (boundary-changed faces) and unchanged edges as Dirichlet; unchanged faces -> 0. Transition
zone (0 < geodesic distance to F < ``transition_mm``) on boundary-changed / unchanged faces: displacement
times ``3r^2 - 2r^3``. Tangential Laplacian relaxation of changed-face nodes (``relax_iters``).
Outputs are copies of the assembly files holding moved shell nodes, only ``/NODE`` coordinate fields changed.
"""

from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..common import CODE_CATEGORY, EXIT_CHECK, EXIT_OK, OutDir, PaicadError, Reporter, dumps, rnd, sha256_file
from ..mesh.radioss import parse_text
from ..tag import KIND_EDGE, KIND_FACE, KIND_UNMATCHED, KIND_VERTEX
from ..writers import get_writer
from . import opts as shopts
from .assem import Assembly, read_assembly
from .cad import load_sample
from .common import load_shell_features, shell_envelope
from .beads import bead_from_section, point_map
from .fem2d import SolveFailed, solve_patch
from .fixed import load_fixed, part_mesh
from .tag import load_shell_tag, mesh_edges

MORPH_JSON = "shell_morph.json"
FILES_DIR = "files"
ZERO_MM = 1.0e-6


class MorphFailed(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class ShellMesh:
    index: int
    part_id: int
    body: str
    node_ids: np.ndarray
    xyz: np.ndarray
    conn: np.ndarray  # local, (m,4), tri: c3 == c2
    tri: np.ndarray
    kind: np.ndarray
    ent: np.ndarray
    uv: np.ndarray
    fixed: np.ndarray
    geo: np.ndarray
    rel: np.ndarray  # file index of each node definition


def load_meshes(asm: Assembly, tag_doc: dict, tag: dict) -> list[ShellMesh]:
    out = []
    tid = tag["node_id"]
    order = np.argsort(tid)
    for k, p in enumerate(tag_doc.get("parts") or []):
        pm = part_mesh(asm, int(p["part_id"]))
        if len(pm.elem_ids) == 0:
            raise PaicadError("GEOM_INPUT_INVALID", f"shell part {p['part_id']} of the tag is not in the assembly folder")
        rows = asm.index(pm.node_ids)
        pos = np.searchsorted(tid[order], pm.node_ids)
        pos = np.clip(pos, 0, len(tid) - 1)
        r = order[pos]
        if np.any(rows < 0) or not np.array_equal(tid[r], pm.node_ids):
            raise PaicadError("GEOM_INPUT_INVALID", f"shell part {p['part_id']}: nodes of the assembly and the tag differ (re-run shell tag)")
        conn = np.searchsorted(pm.node_ids, pm.conn)
        out.append(
            ShellMesh(k, int(p["part_id"]), p["body"], pm.node_ids, asm.xyz[rows].copy(), conn, pm.tri, tag["kind"][r].astype(np.int8), tag["entity"][r].astype(np.int64),
                      tag["uv"][r].astype(float), tag["fixed"][r].astype(bool), tag["geo_dist_fixed"][r].astype(float), asm.node_rel[rows])
        )
    if not out:
        raise PaicadError("GEOM_INPUT_INVALID", "shell_tag.json has no parts")
    return out


@dataclass
class MorphResult:
    xyz: dict[int, np.ndarray]  # part index -> morphed coordinates
    disp: dict[int, np.ndarray]
    parts: list[dict]
    max_disp: float
    moved: dict[int, tuple[float, float, float]] = field(default_factory=dict)


def _element_faces(m: ShellMesh, topo) -> np.ndarray:
    edge_faces = {e.id: set(e.faces) for e in topo.edges}
    vert_faces: dict[int, set[int]] = {}
    for e in topo.edges:
        for v in e.vertices:
            vert_faces.setdefault(v, set()).update(e.faces)
    out = np.full(len(m.conn), -1, dtype=np.int64)
    for i, (el, t) in enumerate(zip(m.conn, m.tri)):
        nodes = el[:3] if t else el
        fs = [int(m.ent[j]) for j in nodes if m.kind[j] == KIND_FACE]
        if fs:
            c = Counter(fs).most_common()
            best = max(n for _, n in c)
            out[i] = min(f for f, n in c if n == best)
            continue
        cand = None
        for j in nodes:
            if m.kind[j] == KIND_EDGE:
                s = edge_faces.get(int(m.ent[j]), set())
            elif m.kind[j] == KIND_VERTEX:
                s = vert_faces.get(int(m.ent[j]), set())
            else:
                continue
            cand = set(s) if cand is None else cand & s
        if cand:
            out[i] = min(cand)
    return out


def _plane_basis(n: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    a = np.array([1.0, 0.0, 0.0]) if abs(n[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    e1 = np.cross(n, a)
    e1 /= np.linalg.norm(e1)
    return e1, np.cross(n, e1)


def _smoothstep(r: np.ndarray) -> np.ndarray:
    r = np.clip(r, 0.0, 1.0)
    return 3 * r * r - 2 * r**3


def morph_part(m: ShellMesh, body, changed: dict, o: dict, sections: list[dict] | None = None) -> tuple[np.ndarray, dict]:
    topo = body.topology()
    mo = o["morph"]
    G = {int(x[1:]) for x in changed.get("geometry", [])}
    Bf = {int(x[1:]) for x in changed.get("boundary_only", [])} - G
    Ec = {int(x[1:]) for x in changed.get("edges", [])}
    Vc = {int(x[1:]) for x in changed.get("vertices", [])}
    n = len(m.node_ids)
    x = m.xyz
    d = np.zeros((n, 3))
    done = np.zeros(n, dtype=bool)
    kind, ent = m.kind, m.ent
    # vertices / edges
    iv = np.flatnonzero(kind == KIND_VERTEX)
    for i in iv:
        if int(ent[i]) in Vc:
            d[i] = topo.vertices[int(ent[i]) - 1] - x[i]
    done[iv] = True
    ie = np.flatnonzero(kind == KIND_EDGE)
    for eid in sorted(set(int(e) for e in ent[ie]) & Ec):
        sel = ie[ent[ie] == eid]
        d[sel] = body.eval_edge(eid, m.uv[sel, 0]) - x[sel]
    done[ie] = True
    elem_face = getattr(m, "_elem_face", None)
    if elem_face is None:  # depends on the tag and the (nominal = sample) topology only
        elem_face = m._elem_face = _element_faces(m, topo)
    faces_stat = {"uv_map": 0, "in_surface": 0, "unchanged": 0}
    solver = {"method": "none", "iterations": 0, "rel_residual": 0.0}
    face_nodes = {}
    ifc = np.flatnonzero(kind == KIND_FACE)
    for f in sorted(set(int(e) for e in ent[ifc])):
        face_nodes[f] = ifc[ent[ifc] == f]
    fallback: list[int] = []
    # bead faces: normalized position on the bead cross-section and path (= face (u,v) of the swept
    # fillet / flank surfaces, bead-aligned for the planar flanks and bottom)
    for sec in sections or []:
        bead, new, shift = bead_from_section(sec)
        bf = sorted(int(x[1:]) for x in sec["faces"])
        for f in bf:
            idx = face_nodes.get(f)
            if idx is None or f not in G:
                continue
            d[idx] = point_map(bead, new, shift, x[idx]) - x[idx]
            done[idx] = True
            faces_stat["uv_map"] += 1
            face_nodes.pop(f)
    for f, idx in face_nodes.items():
        fd = topo.face(f)
        if f not in G and f not in Bf:
            faces_stat["unchanged"] += 1
            done[idx] = True
            continue
        planar = fd.surface == "PLANE" and fd.normal is not None
        nrm = None
        if planar:
            P = x[idx]
            c = P.mean(axis=0)
            if len(P) >= 3:
                _, _, vt = np.linalg.svd(P - c, full_matrices=False)
                nrm = vt[2]
            else:
                nrm = np.asarray(fd.normal, dtype=float)
            if abs(float(np.dot(nrm, fd.normal))) < 1.0 - 1e-9:
                planar = False  # rotated plane: (u,v) map
        if not planar:
            if f in Bf:
                fallback += idx.tolist()
                continue
            uvs = m.uv[idx]
            pts, _ = body.eval_face(f, uvs)
            ins = body.classify_face_uv(f, uvs)
            d[idx[ins]] = pts[ins] - x[idx[ins]]
            done[idx[ins]] = True
            fallback += idx[~ins].tolist()
            faces_stat["uv_map"] += 1
            continue
        faces_stat["in_surface"] += 1
        nrm = nrm / np.linalg.norm(nrm)
        delta = float(np.dot(np.asarray(fd.centroid, dtype=float) - x[idx].mean(axis=0), nrm))
        els = np.flatnonzero(elem_face == f)
        pn = np.unique(m.conn[els])
        loc = {int(g): k for k, g in enumerate(pn)}
        e1, e2 = _plane_basis(nrm)
        xy = np.stack([(x[pn] - x[idx[0]]) @ e1, (x[pn] - x[idx[0]]) @ e2], axis=1)
        own = (kind[pn] == KIND_FACE) & (ent[pn] == f) | (kind[pn] == KIND_UNMATCHED)
        if f in Bf:
            own &= ~m.fixed[pn]
        dirn = np.flatnonzero(~own)
        dvals = d[pn[dirn]]
        dvals = dvals - np.outer(dvals @ nrm, nrm)
        dir_val = np.stack([dvals @ e1, dvals @ e2], axis=1)
        conn_l = np.vectorize(loc.__getitem__, otypes=[np.int64])(m.conn[els]) if len(els) else np.zeros((0, 4), dtype=np.int64)
        tl = m.tri[els]
        import hashlib

        key = (m.part_id, f, float(mo["poisson"]), hashlib.sha1(pn.tobytes() + b"|" + dirn.tobytes() + b"|" + x[pn].tobytes()).hexdigest())
        try:
            u, info = solve_patch(xy, conn_l[tl][:, :3], conn_l[~tl], dirn, dir_val, mo["smoother"], float(mo["poisson"]), float(mo["solver_rtol"]), int(mo["solver_maxiter"]), key)
        except SolveFailed as ex:
            raise MorphFailed("GEOM_MORPH_FAILED", f"face F{f}: {ex}") from None
        if info.method != "none":
            solver = {"method": info.method, "iterations": solver["iterations"] + info.iterations, "rel_residual": max(solver["rel_residual"], info.rel_residual)}
        free = pn[own]
        d[free] = delta * nrm + np.outer(u[own, 0], e1) + np.outer(u[own, 1], e2)
        done[free] = True
        done[idx[m.fixed[idx]]] = True  # Dirichlet 0 on boundary-changed faces
    # unmatched / fallback nodes: harmonic average of neighbours, then onto the nearest sample face
    rest = np.flatnonzero(~done)
    if len(rest):
        edges = mesh_edges(m.conn, m.tri)
        nb: dict[int, list[int]] = {}
        for a, b in edges:
            nb.setdefault(int(a), []).append(int(b))
            nb.setdefault(int(b), []).append(int(a))
        free = set(rest.tolist())
        for _ in range(200):
            for i in rest:
                nbs = nb.get(int(i), [])
                if nbs:
                    d[i] = np.mean(d[nbs], axis=0)
        for i in rest:
            q = x[i] + d[i]
            best = None
            for f in {int(elem_face[e]) for e in np.flatnonzero((m.conn == i).any(axis=1)) if elem_face[e] > 0}:
                dist, _, _, foot = body.project_to_face(f, q[None, :])
                if best is None or dist[0] < best[0]:
                    best = (dist[0], foot[0])
            if best is not None:
                d[i] = best[1] - x[i]
        del free
    # transition zone
    trans = float(o["fixed"]["transition_mm"])
    if trans > 0:
        on_g = (kind == KIND_FACE) & np.isin(ent, sorted(G))
        zone = (kind == KIND_FACE) & ~on_g & (m.geo > 0) & (m.geo < trans)
        d[zone] *= _smoothstep(m.geo[zone] / trans)[:, None]
    # tangential relaxation of changed-surface nodes
    iters = int(mo["relax_iters"])
    if iters and G:
        relax = np.flatnonzero((kind == KIND_FACE) & np.isin(ent, sorted(G)) & ~m.fixed & ~((m.geo > 0) & (m.geo < trans)))
        if len(relax):
            edges = mesh_edges(m.conn, m.tri)
            deg = np.bincount(edges.ravel(), minlength=n).astype(float)
            for _ in range(iters):
                # relax the displacement field (rigid motions are kept exactly), then back onto the surface
                s = np.zeros((n, 3))
                np.add.at(s, edges[:, 0], d[edges[:, 1]])
                np.add.at(s, edges[:, 1], d[edges[:, 0]])
                avg = s[relax] / np.maximum(deg[relax], 1.0)[:, None]
                q = x[relax] + d[relax] + 0.5 * (avg - d[relax])
                for f in sorted(set(int(e) for e in ent[relax])):
                    sel = ent[relax] == f
                    _, _, _, foot = body.project_to_face(f, q[sel])
                    q[sel] = foot
                d[relax] = q - x[relax]
    fixed_max = float(np.linalg.norm(d[m.fixed], axis=1).max()) if m.fixed.any() else 0.0
    if fixed_max > float(o["fixed"]["tol_mm"]):
        bad = np.flatnonzero(m.fixed & (np.linalg.norm(d, axis=1) > float(o["fixed"]["tol_mm"])))
        raise MorphFailed("SHELL_FIXED_REGION_VIOLATION", f"part {m.part_id}: {len(bad)} fixed nodes would move (max {fixed_max:.4f} mm, e.g. node {int(m.node_ids[bad[0]])})")
    d[m.fixed] = 0.0
    d[np.linalg.norm(d, axis=1) <= ZERO_MM] = 0.0
    dn = np.linalg.norm(d, axis=1)
    return d, {
        "part_id": m.part_id,
        "moved_nodes": int((dn > 0).sum()),
        "max_disp_mm": rnd(float(dn.max()) if n else 0.0),
        "fixed_max_disp_mm": 0.0,
        "faces": faces_stat,
        "solver": {"method": solver["method"], "iterations": int(solver["iterations"]), "rel_residual": rnd(solver["rel_residual"], 12)},
    }


def morph_core(meshes: list[ShellMesh], samples: dict, update_doc: dict, o: dict) -> MorphResult:
    xyz, disp, parts = {}, {}, []
    moved: dict[int, tuple[float, float, float]] = {}
    mx = 0.0
    changed = update_doc.get("changed") or {}
    for m in meshes:
        secs = [b for b in update_doc.get("beads") or [] if b.get("body") == m.body]
        d, info = morph_part(m, samples[m.body], changed.get(m.body, {}), o, secs)
        new = m.xyz + d
        xyz[m.index] = new
        disp[m.index] = d
        parts.append(info)
        mx = max(mx, float(np.linalg.norm(d, axis=1).max()) if len(d) else 0.0)
        for i in np.flatnonzero(np.any(d != 0.0, axis=1)):
            moved[int(m.node_ids[i])] = (float(new[i, 0]), float(new[i, 1]), float(new[i, 2]))
    return MorphResult(xyz, disp, parts, mx, moved)


def write_files(asm: Assembly, moved: dict[int, tuple], solver: str | None) -> list[tuple[str, bytes, str, str, int]]:
    """[(rel, new bytes, sha_in, sha_out, moved nodes)] for every assembly file holding moved nodes."""
    import hashlib

    writer = get_writer(solver)
    by_rel: dict[int, dict] = {}
    if moved:
        ids = np.array(sorted(moved), dtype=np.int64)
        rows = asm.index(ids)
        for nid, r in zip(ids, rows):
            by_rel.setdefault(int(asm.node_rel[r]), {})[int(nid)] = moved[int(nid)]
    out = []
    for fi in sorted(by_rel):
        rel = asm.rels[fi]
        data = (asm.root / rel).read_bytes()
        mesh = parse_text(data.decode("latin-1"))
        new = writer.write(data, mesh, by_rel[fi])
        out.append((rel, new, asm.sha[rel], hashlib.sha256(new).hexdigest(), len(by_rel[fi])))
    return out


def load_inputs(args, o: dict):
    doc = load_shell_features(args.features)
    tag_doc, tag = load_shell_tag(args.tag_dir)
    fixed = load_fixed(args.fixed_dir)
    if tag_doc.get("fixed_digest") != fixed.digest:
        raise PaicadError("GEOM_INPUT_INVALID", "shell tag and fixed-scan outputs differ (fixed_digest) - re-run shell tag")
    asm = read_assembly(args.assem_dir)
    if tag_doc.get("assem_digest") and tag_doc["assem_digest"] != asm.digest():
        raise PaicadError("GEOM_INPUT_INVALID", "the assembly folder differs from the one used by shell tag (assem_digest)")
    from ..update import read_json
    from .update import SAMPLE_BREP, UPDATE_JSON

    ud = Path(args.update_dir)
    u = read_json(ud / UPDATE_JSON, UPDATE_JSON)
    if u.get("status") != "OK" or u.get("kind") != "shell":
        raise PaicadError("GEOM_INPUT_INVALID", "shell_update.json status is not OK")
    names = [p["body"] for p in doc["parts"]]
    samples = {b.name: b for b in load_sample(ud / SAMPLE_BREP, names)}
    meshes = load_meshes(asm, tag_doc, tag)
    return doc, tag_doc, fixed, asm, u, samples, meshes


def run(args, rep: Reporter) -> int:
    t0 = time.monotonic()
    o = shopts.load(args.options)
    out = OutDir(args.out_dir, [MORPH_JSON, FILES_DIR])
    out.prepare()
    get_writer(args.solver)
    rep.progress(5, "reading inputs")
    doc, tag_doc, fixed, asm, u, samples, meshes = load_inputs(args, o)
    rep.progress(20, "moving shell nodes")
    try:
        res = morph_core(meshes, samples, u, o)
    except MorphFailed as e:
        code_exit = EXIT_CHECK
        d = shell_envelope(status="FAIL", code=e.code, category=CODE_CATEGORY.get(e.code), message=e.message, max_disp_mm=None, files=[], parts=[], elapsed_s=rnd(time.monotonic() - t0, 3))
        out.write_text(MORPH_JSON, dumps(d))
        out.commit([MORPH_JSON])
        rep.warn(f"{e.code}: {e.message}")
        rep.result("FAIL", e.code, MORPH_JSON)
        return code_exit
    rep.progress(80, "writing file copies")
    files = write_files(asm, res.moved, args.solver)
    rels = []
    for rel, data, _, _, _ in files:
        p = out.tmp_path(f"{FILES_DIR}/{rel}")
        p.write_bytes(data)
        rels.append(f"{FILES_DIR}/{rel}")
    d = shell_envelope(
        status="OK", code=None, category=None, message=None, max_disp_mm=rnd(res.max_disp),
        files=[{"rel": r, "sha256_in": a, "sha256_out": b, "moved_nodes": k} for r, _, a, b, k in files],
        parts=res.parts, elapsed_s=rnd(time.monotonic() - t0, 3),
    )
    out.write_text(MORPH_JSON, dumps(d))
    out.commit(rels + [MORPH_JSON])
    rep.progress(100, f"shell morph done: {len(res.moved)} nodes moved in {len(files)} files")
    rep.result("OK", None, MORPH_JSON)
    return EXIT_OK
