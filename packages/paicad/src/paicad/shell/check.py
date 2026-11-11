"""``paicad shell check`` - checks of the morphed shell mesh (shell-morph sections 4.9, 6.6).

(f) fixed node lines byte-identical, (a) bead parameters re-measured on the morphed nodes against the
update's expected values, (b) classified node <-> sample entity distance, (c) shell quality, (d) new
penetration of moved nodes into other parts (mid-surface +- t/2), (e) ``/INTER/TYPE2`` projection.
Only on PASS the morph file copies are written to ``--out-files-dir`` (same relative paths).
"""

from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..common import CODE_CATEGORY, EXIT_CHECK, EXIT_OK, OutDir, PaicadError, Reporter, dumps, replace_retry, rnd
from ..mesh.radioss import parse_text
from ..meshgeom import TriangleSet
from ..tag import KIND_EDGE, KIND_FACE, KIND_VERTEX
from ..tie import AssemblySets, TieDef, check_ties
from ..update import read_json
from . import opts as shopts
from .assem import SHELL_KW, Assembly, SetError, resolve_grnod, resolve_surf, seg_triangles
from .beads import Bead, core_coords, recognize
from .common import load_shell_features, load_values, shell_envelope
from .judge import RANK, JudgeInput, Tables, final_code, judge_mesh
from .morph import FILES_DIR, MORPH_JSON, ShellMesh, _element_faces, load_inputs

CHECK_JSON = "shell_check.json"
# final code order (section 14.4, warn policies): feature distortion -> inversion / dt_ratio -> fixed -> interference -> quality -> deviation
# -> param -> tie; both policies skip keep the 0.14.1 order (judge.final_code)
PRIORITY = tuple(sorted(RANK, key=RANK.get))
COVER_CUTOFF_MM = 2.0


@dataclass
class CheckResult:
    status: str
    code: str | None
    message: str | None
    checks: dict
    warnings: list[dict] = field(default_factory=list)
    summary: dict = field(default_factory=dict)
    waived: list[str] = field(default_factory=list)  # SM-C6: failure codes passed under the warn policies


def node_lines(data: bytes) -> dict[int, bytes]:
    out = {}
    in_node = False
    for line in data.splitlines(keepends=True):
        if line.startswith(b"/"):
            in_node = line.rstrip(b"\r\n").strip().upper() == b"/NODE" or line.upper().startswith(b"/NODE/")
            continue
        if not in_node or line.startswith((b"#", b"$")) or not line.strip():
            continue
        tok = line.split()
        try:
            out[int(tok[0])] = line
        except (ValueError, IndexError):
            continue
    return out


# ------------------------------------------------------------------ measurements
def _plane_fit(P: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    c = P.mean(axis=0)
    _, _, vt = np.linalg.svd(P - c, full_matrices=False)
    return c, vt[2]


def measure_bead(m: ShellMesh, xyz: np.ndarray, elem_face: np.ndarray, bead: Bead, feats: dict, body, o: dict, exclude: np.ndarray | None = None) -> dict[str, float]:
    """Section 6.3 table measurements on the morphed nodes (``bead`` = recognized sample bead). ``exclude``: nodes left
    out of the depth (hold region, SM-C7). Beads with bottom islands (SM-C3) measure the position as the nominal value
    plus the displacement of the bottom-element centroid (the islands bias the absolute centroid)."""
    out: dict[str, float] = {}
    kind, ent = m.kind, m.ent
    bottoms = bead.faces["bottom"]
    bottom = bottoms[0]
    bn = np.flatnonzero((kind == KIND_FACE) & (np.isin(ent, bottoms) if len(bottoms) > 1 else (ent == bottom)))
    if exclude is not None:
        bn = bn[~exclude[bn]]
    base = np.flatnonzero((kind == KIND_FACE) & (ent == bead.base_face))
    if len(base) == 0:
        return out
    rho, _, _, _ = core_coords(xyz[base], bead.core, bead.n, bead.p0, bead.ed)
    # ring of ~2 elements outside the entry loop (fixed / transition nodes excluded)
    els = np.flatnonzero(elem_face == bead.base_face)
    e = xyz[m.conn[els]]
    hsz = float(np.median(np.linalg.norm(e[:, 1] - e[:, 0], axis=1))) if len(els) else 3.0
    trans = float(o["fixed"]["transition_mm"])
    ring = (rho >= bead.prof.rho0 - 1e-9) & (rho <= bead.prof.rho0 + 2.0 * hsz + 1e-9)
    keep = ring & ~m.fixed[base] & ~((m.geo[base] > 0) & (m.geo[base] < trans))
    sel = base[keep] if keep.sum() >= 3 else base[ring]
    if len(sel) < 3:
        sel = base
    c, nr = _plane_fit(xyz[sel])
    if float(np.dot(nr, bead.ed)) < 0:
        nr = -nr
    depth = None
    if len(bn):
        depth = float(np.mean((xyz[bn] - c) @ nr))
        out["BEAD_DEPTH"] = depth
    # position: area-weighted centroid of the bottom elements, onto the base plane
    be = np.flatnonzero(elem_face == bottom) if len(bottoms) == 1 else np.flatnonzero(np.isin(elem_face, bottoms))

    def centroid(X):
        P = X[m.conn[be]]
        t1 = P[:, [0, 1, 2]]
        t2 = P[:, [0, 2, 3]]
        A1 = 0.5 * np.linalg.norm(np.cross(t1[:, 1] - t1[:, 0], t1[:, 2] - t1[:, 0]), axis=1)
        A2 = np.where(m.tri[be], 0.0, 0.5 * np.linalg.norm(np.cross(t2[:, 1] - t2[:, 0], t2[:, 2] - t2[:, 0]), axis=1))
        cen = (A1[:, None] * t1.mean(1) + A2[:, None] * t2.mean(1)).sum(0) / max(float((A1 + A2).sum()), 1e-300)
        return cen - float(np.dot(cen - c, nr)) * nr

    if len(be):
        cen = centroid(xyz)
        cen0 = centroid(m.xyz) if bead.islands else None
        for t in ("BEAD_POS_U", "BEAD_POS_V"):
            f = feats.get(t)
            if f is None:
                continue
            r = f["ref"]
            ax = np.asarray(r["axis"], dtype=float)
            if cen0 is not None:
                out[t] = float(f["nominal"]) + float(r.get("sign", 1.0) if r["rule"] != "proportional" else 1.0) * float(np.dot(cen - cen0, ax))
            elif r["rule"] == "proportional":
                out[t] = float(cen @ ax - float(r["origin"]))
            else:
                q = body.eval_edge(int(r["edge"][1:]), np.array([0.5]))[0]
                out[t] = float(r.get("sign", 1.0)) * float(np.dot(cen - q, ax))
    # width: flank element edges crossing the half-depth plane
    if depth is not None and "BEAD_WIDTH" in feats:
        hh = 0.5 * depth
        flank = bead.faces["flanks"]
        fe = np.flatnonzero(np.isin(elem_face, flank))
        pts, side_planar = [], []
        planar = {f for f in flank if body.topology().face(f).surface == "PLANE"}
        for i in fe:
            el = m.conn[i][:3] if m.tri[i] else m.conn[i]
            k = len(el)
            for a, b in ((el[j], el[(j + 1) % k]) for j in range(k)):
                ha, hb = float((xyz[a] - c) @ nr), float((xyz[b] - c) @ nr)
                if (ha - hh) * (hb - hh) < 0:
                    t = (hh - ha) / (hb - ha)
                    pts.append(xyz[a] + t * (xyz[b] - xyz[a]))
                    side_planar.append(int(elem_face[i]) in planar)
        if pts:
            P = np.array(pts)
            sp = np.array(side_planar)
            if len(bead.core) == 1:
                e1 = np.cross(nr, [1.0, 0.0, 0.0] if abs(nr[0]) < 0.9 else [0.0, 1.0, 0.0])
                e1 /= np.linalg.norm(e1)
                e2 = np.cross(nr, e1)
                x2 = np.stack([(P - c) @ e1, (P - c) @ e2], 1)
                A = np.column_stack([2 * x2, np.ones(len(x2))])
                sol, *_ = np.linalg.lstsq(A, (x2**2).sum(1), rcond=None)
                R = math.sqrt(max(0.0, sol[2] + sol[0] ** 2 + sol[1] ** 2))
                out["BEAD_WIDTH"] = 2.0 * R
            elif sp.any():
                u = bead.core_dir()
                w = np.cross(nr, u)
                w /= np.linalg.norm(w)
                s = (P[sp] - bead.core[0]) @ w
                if (s > 0).any() and (s < 0).any():
                    out["BEAD_WIDTH"] = float(s[s > 0].mean() - s[s < 0].mean())
    return out


def deviation(m: ShellMesh, xyz: np.ndarray, body, changed: dict, moved: np.ndarray, tag_dist: np.ndarray, exclude: np.ndarray | None = None) -> tuple[float, int]:
    topo = body.topology()
    G = {int(x[1:]) for x in changed.get("geometry", []) + changed.get("boundary_only", [])}
    Ec = {int(x[1:]) for x in changed.get("edges", [])}
    Vc = {int(x[1:]) for x in changed.get("vertices", [])}
    dev = np.where(tag_dist >= 0, tag_dist, 0.0).astype(float)
    kind, ent = m.kind, m.ent
    sel_f = (kind == KIND_FACE) & (np.isin(ent, sorted(G)) | moved)
    for f in sorted(set(int(x) for x in ent[sel_f])):
        idx = np.flatnonzero(sel_f & (ent == f))
        fd = topo.face(f)
        if fd.surface == "PLANE" and fd.normal is not None:
            dev[idx] = np.abs((xyz[idx] - np.asarray(fd.centroid)) @ np.asarray(fd.normal))
        else:
            d, _, _, _ = body.project_to_face(f, xyz[idx])
            dev[idx] = d
    sel_e = (kind == KIND_EDGE) & (np.isin(ent, sorted(Ec)) | moved)
    for e in sorted(set(int(x) for x in ent[sel_e])):
        idx = np.flatnonzero(sel_e & (ent == e))
        d, _, _ = body.project_to_edge(e, xyz[idx])
        dev[idx] = d
    sel_v = (kind == KIND_VERTEX) & (np.isin(ent, sorted(Vc)) | moved)
    for i in np.flatnonzero(sel_v):
        dev[i] = float(np.linalg.norm(xyz[i] - topo.vertices[int(ent[i]) - 1]))
    if exclude is not None and exclude.any():  # SM-C7 hold region: intentionally off the sample B-rep
        dev[exclude] = 0.0
    i = int(np.argmax(dev)) if len(dev) else 0
    return (float(dev[i]) if len(dev) else 0.0), i


def interference(asm: Assembly, meshes: list[ShellMesh], new_xyz: dict[int, np.ndarray], thick: dict[int, float], o: dict) -> tuple[dict, str | None]:
    target = {m.part_id for m in meshes}
    tnodes = set()
    for m in meshes:
        tnodes.update(int(x) for x in m.node_ids)
    pmm = float(o["interference"]["product_mm"])
    tris_by_part: dict[int, np.ndarray] = {}
    for b in asm.blocks:
        if b.part in target or b.keyword not in SHELL_KW:
            continue
        segs = [[int(x) for x in c if x > 0] for c in b.conn]
        t, _ = seg_triangles(segs)
        if len(t):
            keep = ~np.isin(t, list(tnodes)).any(axis=1)
            tris_by_part[b.part] = np.concatenate([tris_by_part.get(b.part, np.zeros((0, 3), dtype=np.int64)), t[keep]])
    pairs, worst = [], 0.0
    for m in meshes:
        d = new_xyz[m.index] - m.xyz
        mv = np.flatnonzero(np.linalg.norm(d, axis=1) > 0)
        if len(mv) == 0:
            continue
        lo = m.xyz.min(0) - 10.0
        hi = m.xyz.max(0) + 10.0
        ts = thick.get(m.part_id, 0.0)
        for pid, T in sorted(tris_by_part.items()):
            rows = asm.index(T.ravel())
            if np.any(rows < 0):
                continue
            C = asm.xyz[rows].reshape(-1, 3, 3)
            inb = ((C.max(1) >= lo) & (C.min(1) <= hi)).all(1)
            C = C[inb]
            if not len(C):
                continue
            req = 0.5 * (ts + thick.get(pid, 0.0)) - pmm
            if req <= 0:
                continue
            tset = TriangleSet(C)
            d1, _ = tset.distance(new_xyz[m.index][mv], req)
            d0, _ = tset.distance(m.xyz[mv], req)
            bad = (d1 < req) & ~(d0 < req)
            if bad.any():
                pen = float((req - d1[bad]).max())
                worst = max(worst, pen)
                pairs.append({"part_id": m.part_id, "with_part": pid, "nodes": int(bad.sum()), "max_penetration_mm": rnd(pen)})
    rep = {"status": "FAIL" if pairs else "PASS", "max_penetration_mm": rnd(worst), "pairs": pairs}
    return rep, ("interference: " + ", ".join(f"part {p['part_id']} into {p['with_part']} ({p['nodes']} nodes)" for p in pairs[:5])) if pairs else None


def tie_check(asm: Assembly, meshes: list[ShellMesh], new_xyz: dict[int, np.ndarray], o: dict) -> tuple[dict, str | None, list[dict]]:
    sets = AssemblySets()
    for fd in asm.fixdefs:
        if fd.kind != "INTER_TYPE2":
            continue
        g = fd.grnods[0] if fd.grnods else None
        sets.ties.append(TieDef(fd.id, g, fd.surf, fd.dsearch, fd.rel))
        try:
            if g is not None:
                sets.grnod_node[g] = sorted(resolve_grnod(asm, g))
        except SetError:
            sets.other_sets.add(("GRNOD", g))
        try:
            if fd.surf is not None:
                sets.surf_seg[fd.surf] = [s + [s[-1]] * (4 - len(s)) for s in resolve_surf(asm, fd.surf)]
        except SetError:
            sets.other_sets.add(("SURF", fd.surf))
    shell_nodes = set()
    base = {int(n): asm.xyz[i] for i, n in enumerate(asm.node_ids)}
    new = dict(base)
    for m in meshes:
        shell_nodes.update(int(x) for x in m.node_ids)
        for k, nid in enumerate(m.node_ids):
            new[int(nid)] = new_xyz[m.index][k]
    return check_ties(sets, shell_nodes, new, base, o)


def island_coverage(m: ShellMesh, x: np.ndarray, body, doc: dict, vals: dict, expected: dict, o: dict, held: set[str]) -> list[dict]:
    """SM-C4, independent of the tag: (1) nodes on the nominal island surfaces (found geometrically) move rigidly by the
    island shift, (2) the sample B-rep surfaces of the islands and bottom pieces of every changed bead with islands are
    followed by the morphed mesh. Points of each sample face (UV grid inside the trimmed face) -> distance
    to the morphed triangles (KD-tree candidates, ``TriangleSet``) minus the same distance of the nominal surface point
    (island = sample point - island shift, rigid) to the nominal triangles (discretization error; planar bottoms 0).
    Returns [{bead, island, faces, dev_mm}] (one item per island / bottom piece)."""
    from .common import feature_values

    fv = feature_values(doc, o, vals)
    by_bead: dict[str, dict] = {}
    for f in doc["features"]:
        by_bead.setdefault(f["bead"], {})[f["type"]] = f
    en = np.where(m.tri[:, None], m.conn[:, [0, 1, 2, 2]], m.conn)
    out = []
    for bj in doc["beads"]:
        if bj["body"] != m.body or not bj.get("islands"):
            continue
        feats = by_bead.get(bj["id"], {})
        if not any(f["name"] in expected for f in feats.values()):
            continue
        t = np.zeros(3)
        if "BEAD_DEPTH" in feats:
            f = feats["BEAD_DEPTH"]
            t = t + (fv[f["name"]] - float(f["nominal"])) * np.asarray(bj["depth_dir"], dtype=float)
        for typ in ("BEAD_POS_U", "BEAD_POS_V"):
            if typ in feats:
                f = feats[typ]
                t = t + (fv[f["name"]] - float(f["nominal"])) * float(f["ref"].get("sign", 1.0)) * np.asarray(f["ref"]["axis"], dtype=float)
        groups = [(i["id"], [int(z[1:]) for z in i["faces"]], True) for i in bj["islands"] if i["faces"]]
        groups += [(f"F{int(z[1:])}", [int(z[1:])], False) for z in bj["bottom"]]
        tol = float(o["tag"]["tol_abs_mm"])
        anchors = np.zeros(0, dtype=np.int64)
        keep_out = None
        if bj["id"] in held:  # SM-C7: anchors = fixed nodes on the bottom pieces / islands (geometric, not the tag)
            hb = o["bead"]["hold"]
            reach = float(hb["ring_mm"]) + float(hb["blend_mm"])
            fx = np.flatnonzero(m.fixed)
            d_on = np.full(len(fx), np.inf)
            for f in sorted({f for _, fs, _ in groups for f in fs}):
                bb = np.asarray(body.topology().face(f).bbox, dtype=float)
                c_ = np.flatnonzero(np.all((m.xyz[fx] + t >= bb[:3] - tol) & (m.xyz[fx] + t <= bb[3:] + tol), axis=1))
                if len(c_):
                    dd, _, ins, _ = body.project_to_face(f, m.xyz[fx[c_]] + t)
                    d_on[c_] = np.minimum(d_on[c_], np.where(ins, dd, np.inf))
            anchors = fx[d_on <= tol]
            if len(anchors):
                from scipy.spatial import cKDTree

                tree = cKDTree(m.xyz[anchors])
                r_out = reach + float(np.linalg.norm(t))

                def keep_out(P):  # points within the hold ring + blend of an anchor: intentionally off the sample B-rep
                    return np.isfinite(tree.query(P, k=1, distance_upper_bound=r_out)[0])
        for gid, faces, rigid in groups:
            P1 = np.concatenate([body.sample_face(f, 12 if rigid else 30) for f in faces])
            if not len(P1):
                continue
            if keep_out is not None:
                if rigid and len(anchors):
                    d_a = np.full(len(anchors), np.inf)
                    for f in faces:
                        dd, _, ins, _ = body.project_to_face(f, m.xyz[anchors] + t)
                        d_a = np.minimum(d_a, np.where(ins, dd, np.inf))
                    if (d_a <= tol).any():
                        continue  # island holding hold anchors: deformed on purpose (section 14.2)
                P1 = P1[~keep_out(P1 - t)]
                if not len(P1):
                    continue
            P0 = P1 - t if rigid else None
            box = np.concatenate([P1] + ([P0] if P0 is not None else []))
            lo, hi = box.min(axis=0) - 3.0, box.max(axis=0) + 3.0
            near = np.all((x >= lo) & (x <= hi), axis=1) | np.all((m.xyz >= lo) & (m.xyz <= hi), axis=1)
            els = np.flatnonzero(near[m.conn].any(axis=1))

            def tris(X):
                q = X[en[els]]
                t1 = q[:, [0, 1, 2]]
                t2 = q[~m.tri[els]][:, [0, 2, 3]]
                return np.concatenate([t1, t2])

            d1, _ = TriangleSet(tris(x)).distance(P1, COVER_CUTOFF_MM)
            d1 = np.where(np.isfinite(d1), d1, COVER_CUTOFF_MM)
            if P0 is not None:
                d0, _ = TriangleSet(tris(m.xyz)).distance(P0, COVER_CUTOFF_MM)
                d0 = np.where(np.isfinite(d0), d0, COVER_CUTOFF_MM)
            else:
                d0 = np.zeros(len(P1))
            dev = float(np.max(d1 - d0))
            nodes = 0
            if rigid:  # nodes lying on the nominal island surface (geometric membership, not the tag) move by the island shift
                lo0, hi0 = P0.min(axis=0) - 0.5, P0.max(axis=0) + 0.5
                cand = np.flatnonzero(np.all((m.xyz >= lo0) & (m.xyz <= hi0), axis=1))
                if len(cand):
                    d_on = np.full(len(cand), np.inf)
                    for f in faces:
                        dd, _, ins, _ = body.project_to_face(f, m.xyz[cand] + t)
                        d_on = np.minimum(d_on, np.where(ins, dd, np.inf))
                    on = cand[d_on <= tol]
                    if keep_out is not None and len(on):
                        on = on[~keep_out(m.xyz[on])]
                    nodes = int(len(on))
                    if nodes:
                        dev = max(dev, float(np.linalg.norm(x[on] - (m.xyz[on] + t), axis=1).max()))
            out.append({"bead": bj["id"], "island": gid, "faces": len(faces), "nodes": nodes, "dev_mm": dev})
    return out


def judge_inputs(m: ShellMesh, x: np.ndarray, body, doc: dict, expected: dict, changed: dict, o: dict, held: set[str], line_changes: int = 0) -> JudgeInput:
    """Mesh-only inputs of the judgement core for one part (labels from the tag, B-rep topology as integer tables)."""
    topo = body.topology()
    by_bead: dict[str, list[str]] = {}
    for f in doc["features"]:
        by_bead.setdefault(f["bead"], []).append(f["name"])
    G = {int(x_[1:]) for x_ in changed.get("geometry", []) + changed.get("boundary_only", [])}
    feats, hold = [], []
    for bj in doc["beads"]:
        if bj["body"] != m.body or not any(nm in expected for nm in by_bead.get(bj["id"], [])):
            continue  # SM-C4: islands of the beads that moved in this sample
        isl_faces = [[int(x_[1:]) for x_ in i["faces"]] for i in bj.get("islands") or []]
        for i, fs in zip(bj.get("islands") or [], isl_faces):
            if fs:
                feats.append({"bead": bj["id"], "island": i["id"], "faces": fs, "rim_zero": False})
        roles = [int(x_[1:]) for k in ("fillets_top", "flanks", "fillets_bottom", "bottom") for x_ in bj[k]]
        region = set(roles) | {f for fs in isl_faces for f in fs}
        nb = set()
        for f in region:
            for e in topo.face(f).edges:
                nb.update(topo.edge(e).faces)
        other = sorted(nb - region - {int(bj["base_face"][1:])} - G)
        for f in other:  # faces next to the bead region that the update left unchanged: must not move (rim t = 0)
            feats.append({"bead": bj["id"], "island": f"F{f}", "faces": [f], "rim_zero": True})
        if bj["id"] in held:
            hold.append({"bead": bj["id"], "region_faces": sorted(region), "anchor_faces": sorted({int(x_[1:]) for x_ in bj["bottom"]} | {f for fs in isl_faces for f in fs})})
    return JudgeInput(m.node_ids, m.xyz, x, m.conn, m.tri, m.kind, m.ent, m.fixed, m.cluster, Tables.from_topology(topo), feats, hold, line_changes)


def check_core(meshes, morphed: dict[int, np.ndarray], samples: dict, doc: dict, vals: dict, expected: dict, changed_all: dict, o: dict, asm: Assembly | None,
               thick: dict[int, float], tag: dict, files: list[tuple[str, bytes]] | None, full: bool = True) -> CheckResult:
    checks: dict = {}
    warnings: list[dict] = []
    fails: dict[str, str] = {}
    waived: list[str] = []
    held = set(shopts.hold_ids(o))
    # (f) fixed: byte comparison of the fixed node lines (file copies), coordinates in the judgement core
    line_changes = {m.index: 0 for m in meshes}
    if files is not None and asm is not None:
        for m in meshes:
            fixed_ids = set(int(x) for x in m.node_ids[m.fixed])
            for rel, data in files:
                a = node_lines((asm.root / rel).read_bytes())
                b = node_lines(data)
                line_changes[m.index] += sum(1 for k in fixed_ids if k in a and a[k] != b.get(k))
    J = {}
    for m in meshes:
        J[m.index] = judge_mesh(judge_inputs(m, morphed[m.index], samples[m.body], doc, expected, changed_all.get(m.body, {}), o, held, line_changes[m.index]), o)
    fx = [J[m.index]["checks"]["fixed"] for m in meshes]
    st = "FAIL" if any(f["status"] == "FAIL" for f in fx) else ("WARN" if any(f["status"] == "WARN" for f in fx) else "PASS")
    checks["fixed"] = {"status": st, "moved_fixed_nodes": sum(f["moved_fixed_nodes"] for f in fx), "max_mm": rnd(max(f["max_mm"] for f in fx))}
    # (a) parameters
    by_bead: dict[str, dict] = {}
    for f in doc["features"]:
        by_bead.setdefault(f["bead"], {})[f["type"]] = f
    items = []
    errs_abs, errs_rel, margin = [], [], []
    dv = o["deviation"]
    for m in meshes:
        body = samples[m.body]
        topo = body.topology()
        ef = getattr(m, "_elem_face", None)
        if ef is None:
            ef = m._elem_face = _element_faces(m, topo)
        tol = shopts.body_tol(o, body.summary().bbox)
        rec = {tuple(b.faces["bottom"]): b for b in recognize(body, o["extract"], tol, body.name).beads}
        excl = J[m.index]["hold_nodes"]
        for bj in doc["beads"]:
            if bj["body"] != m.body:
                continue
            feats = by_bead.get(bj["id"], {})
            want = {t: f for t, f in feats.items() if f["name"] in vals or f["name"] in expected}
            if not want:
                continue
            bead = rec.get(tuple(int(x[1:]) for x in bj["bottom"]))
            if bead is None and o["extract"].get("islands") and not bj.get("islands"):  # features prepared without islands
                legacy = {tuple(b.faces["bottom"]): b for b in recognize(body, dict(o["extract"], islands=False), tol, body.name).beads}
                bead = legacy.get(tuple(int(x[1:]) for x in bj["bottom"]))
            meas = measure_bead(m, morphed[m.index], ef, bead, feats, body, o, excl if excl.any() else None) if bead is not None else {}
            for t, f in sorted(want.items(), key=lambda kv: kv[1]["name"]):
                inp = float(vals.get(f["name"], f["nominal"]))
                exp = float(expected.get(f["name"], inp))
                tl = max(float(dv["param_abs_mm"]), float(dv["param_rel"]) * abs(exp))
                v = meas.get(t)
                it = {"name": f["name"], "input": rnd(inp, 9), "expected": rnd(exp, 9), "measured": None if v is None else rnd(v), "err": None, "tol": rnd(tl)}
                if v is None:
                    fails.setdefault("GEOM_PARAM_MISMATCH", f"param: {f['name']} could not be measured")
                else:
                    err = abs(v - exp)
                    it["err"] = rnd(err)
                    errs_abs.append(err)
                    errs_rel.append(err / abs(exp) if exp else 0.0)
                    margin.append(tl / err if err > 0 else math.inf)
                    if err > tl:
                        fails.setdefault("GEOM_PARAM_MISMATCH", f"param: {f['name']} measured {v:.4f}, expected {exp:.4f} (tol {tl:.4f})")
                items.append(it)
    checks["param"] = {"status": "FAIL" if "GEOM_PARAM_MISMATCH" in fails else "PASS", "items": items}
    # (b) deviation
    worst, worst_node = 0.0, None
    for m in meshes:
        moved = np.any(morphed[m.index] != m.xyz, axis=1)
        excl = J[m.index]["hold_nodes"]
        dmax, i = deviation(m, morphed[m.index], samples[m.body], changed_all.get(m.body, {}), moved, tag["dist_of"][m.index], excl if excl.any() else None)
        if dmax >= worst:
            worst, worst_node = dmax, int(m.node_ids[i]) if len(m.node_ids) else None
    tolb = float(dv["boundary_max_mm"])
    checks["deviation"] = {"status": "FAIL" if worst > tolb else "PASS", "max_mm": rnd(worst), "tol_mm": tolb, "worst_node": worst_node}
    if worst > tolb:
        fails["GEOM_DEVIATION"] = f"deviation: {worst:.4f} mm > {tolb} mm at node {worst_node}"
    # (c) quality, (g) feature rigidity, hold: judgement core
    qreps = [J[m.index]["checks"]["quality"] for m in meshes]
    for m in meshes:
        warnings += J[m.index]["warnings"]
        waived += [w for w in J[m.index]["waived"] if w not in waived]
        for code, msg in J[m.index]["fails"].items():
            fails.setdefault(code, msg)
    q = qreps[0] if len(qreps) == 1 else _merge_quality(qreps)
    checks["quality"] = q
    gch = [J[m.index]["checks"]["feature"] for m in meshes]
    tested = [g_ for g_ in gch if g_["status"] != "SKIPPED"]
    worst_f = max((g_["worst"] for g_ in tested if g_["worst"]), key=lambda w: w["dev_mm"] - w["floor_mm"], default=None)
    checks["feature"] = {"status": "FAIL" if any(g_["status"] == "FAIL" for g_ in gch) else ("PASS" if tested else "SKIPPED"), "features": sum(g_["features"] for g_ in gch),
                         "worst": None if worst_f is None else {k: (rnd(v) if isinstance(v, float) else v) for k, v in worst_f.items()},
                         "mixed_elems": sum(g_["mixed_elems"] for g_ in gch)}
    cover = []
    for m in meshes:
        cover += island_coverage(m, morphed[m.index], samples[m.body], doc, vals, expected, o, held)
    if cover:  # tag-independent part of (g): sample island / bottom surfaces followed by the mesh
        floor = float(o["quality"]["distort_min_mm"])
        w = max(cover, key=lambda c_: c_["dev_mm"])
        checks["feature"]["coverage"] = {"surfaces": len(cover), "max_mm": rnd(w["dev_mm"]), "worst": {"bead": w["bead"], "island": w["island"]}, "tol_mm": floor}
        if w["dev_mm"] > floor:
            checks["feature"]["status"] = "FAIL"
            fails.setdefault("SHELL_FEATURE_DISTORTED", f"{w['bead']} island {w['island']}: mesh off the sample island / surface by {w['dev_mm']:.4f} mm (floor {floor:.4f} mm)")
    hl = [J[m.index]["checks"]["hold"] for m in meshes if J[m.index]["checks"].get("hold")]
    if hl:
        mxdev = 0.0
        for m in meshes:
            ex = J[m.index]["hold_nodes"]
            if ex.any():
                dv_, _ = deviation(m, morphed[m.index], samples[m.body], changed_all.get(m.body, {}), ex, tag["dist_of"][m.index])
                mxdev = max(mxdev, dv_)
        checks["hold"] = {"beads": sorted({b for h in hl for b in h["beads"]}), "nodes": sum(h["nodes"] for h in hl), "ring_mm": hl[0]["ring_mm"], "blend_mm": hl[0]["blend_mm"],
                          "max_dev_mm": rnd(mxdev)}
    summary = {
        "max_warpage_deg": q["max_warpage_deg"], "max_skew_deg": q["max_skew_deg"], "max_aspect": q["max_aspect"], "min_jacobian": q["min_jacobian"],
        "edge_ratio": q["edge_ratio"], "dt_ratio": q["dt_ratio"], "inverted_elems": q["inverted"], "boundary_dev_max_mm": rnd(worst),
        "param_remeasure_err": {"abs": rnd(max(errs_abs)) if errs_abs else None, "rel": rnd(max(errs_rel)) if errs_rel else None},
        "param_margin": rnd(min(margin)) if margin and math.isfinite(min(margin)) else None,
        "quality_margins": q.get("margins"),
        "fixed_moved_nodes": checks["fixed"]["moved_fixed_nodes"] if checks["fixed"]["status"] == "WARN" else None,
    }
    if full and asm is not None:
        rep, msg = interference(asm, meshes, morphed, thick, o)
        checks["interference"] = rep
        if msg:
            fails["GEOM_INTERFERENCE"] = msg
        rep, msg, w = tie_check(asm, meshes, morphed, o)
        checks["tie"] = rep
        warnings += w
        if msg:
            fails["GEOM_TIE_PROJECTION"] = msg
    else:
        checks["interference"] = {"status": "NOT_EVALUATED"}
        checks["tie"] = {"status": "NOT_EVALUATED"}
    code = final_code(fails, o)
    message = fails.get(code) if code else None
    if code == "GEOM_QUALITY_HARD":
        code = "GEOM_QUALITY"
    res = CheckResult("FAIL" if code else "PASS", code, message, checks, warnings, summary)
    res.waived = waived
    return res


def _merge_quality(reps: list[dict]) -> dict:
    out = dict(reps[0])
    for r in reps[1:]:
        for k in ("max_warpage_deg", "max_skew_deg", "max_aspect", "baseline_max_warpage_deg", "baseline_max_skew_deg", "baseline_max_aspect"):
            out[k] = max(x for x in (out[k], r[k]) if x is not None) if out[k] is not None or r[k] is not None else None
        for k in ("min_jacobian", "baseline_min_jacobian", "min_edge_mm", "baseline_min_edge_mm", "edge_ratio", "dt_ratio"):
            vals = [x for x in (out[k], r[k]) if x is not None]
            out[k] = min(vals) if vals else None
        out["inverted"] += r["inverted"]
        out["margins"] = {k: min((x for x in (out["margins"][k], r["margins"][k]) if x is not None), default=None) for k in out["margins"]}
        out["baseline_status"] = "FAIL" if "FAIL" in (out["baseline_status"], r["baseline_status"]) else "PASS"
        out["status"] = "FAIL" if "FAIL" in (out["status"], r["status"]) else ("WARN" if "WARN" in (out["status"], r["status"]) else "PASS")
    return out


def thickness_map(asm: Assembly, path: str | None) -> dict[int, float]:
    out = {}
    for pid, p in asm.parts.items():
        pr = asm.props.get(p.get("prop")) if p.get("prop") is not None else None
        if pr and pr.get("thickness"):
            out[pid] = float(pr["thickness"])
    if path:
        d = read_json(path, "thickness file")
        if d.get("schema_version") != 1 or not isinstance(d.get("parts"), dict):
            raise PaicadError("GEOM_INPUT_INVALID", 'thickness file must be {"schema_version":1,"parts":{"<part_id>":t}}')
        for k, v in d["parts"].items():
            try:
                pid = int(k)
            except ValueError:
                raise PaicadError("GEOM_INPUT_INVALID", f"thickness file: bad part id {k!r}") from None
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not (v > 0 and math.isfinite(v)):
                raise PaicadError("GEOM_INPUT_INVALID", f"thickness of part {k} must be a finite number > 0")
            out[pid] = float(v)
    return out


def morphed_coords(meshes: list[ShellMesh], asm: Assembly, files: list[tuple[str, bytes]]) -> dict[int, np.ndarray]:
    """Shell node coordinates as written in the morph file copies (unchanged files: assembly values)."""
    new = {}
    over: dict[int, np.ndarray] = {}
    for rel, data in files:
        mesh = parse_text(data.decode("latin-1"))
        for nid, p in zip(mesh.node_ids, mesh.xyz):
            over[int(nid)] = p
    for m in meshes:
        x = m.xyz.copy()
        for k, nid in enumerate(m.node_ids):
            p = over.get(int(nid))
            if p is not None:
                x[k] = p
        new[m.index] = x
    return new


def tag_distances(meshes: list[ShellMesh], tag: dict) -> dict[int, np.ndarray]:
    """Tag distance of every shell node (part index -> dist[n]), for check (b)."""
    look = {int(n): i for i, n in enumerate(tag["node_id"])}
    return {m.index: np.array([tag["dist"][look[int(n)]] for n in m.node_ids]) for m in meshes}


def report(res: CheckResult, o: dict, out_files: list[str], t0: float) -> dict:
    """``shell_check.json`` (also written by ``shell view preview`` with ``out_files: []``)."""
    extra = {"waived": res.waived} if res.waived and res.status == "PASS" else {}
    return shell_envelope(
        status=res.status, code=res.code, category=CODE_CATEGORY.get(res.code) if res.code else None, message=res.message,
        checks=res.checks, warnings=res.warnings, options=shopts.used(o), out_files=out_files, **extra, elapsed_s=rnd(time.monotonic() - t0, 3),
    )


def run(args, rep: Reporter) -> int:
    t0 = time.monotonic()
    o = shopts.load(args.options)
    out = OutDir(args.out_dir, [CHECK_JSON])
    out.prepare()
    ns = argparse_like(args)
    doc, tag_doc, fixed, asm, u, samples, meshes = load_inputs(ns, o)
    vals = load_values(args.values, doc, o)
    md = Path(args.morph_dir)
    mj = read_json(md / MORPH_JSON, MORPH_JSON)
    if mj.get("status") != "OK" or mj.get("kind") != "shell":
        raise PaicadError("GEOM_INPUT_INVALID", "shell_morph.json status is not OK")
    files = []
    for f in mj.get("files") or []:
        p = md / FILES_DIR / f["rel"]
        if not p.is_file():
            raise PaicadError("GEOM_INPUT_INVALID", f"morph file copy missing: {f['rel']}")
        files.append((f["rel"], p.read_bytes()))
    ofd = Path(args.out_files_dir)
    exists = [rel for rel, _ in files if (ofd / rel).exists()]
    if exists:
        raise PaicadError("GEOM_OUTPUT_EXISTS", f"output already exists: {', '.join(exists[:10])}")
    thick = thickness_map(asm, args.thickness)
    from .tag import load_shell_tag

    _, tag = load_shell_tag(args.tag_dir)
    tag_dist = tag_distances(meshes, tag)
    rep.progress(20, "checking the morphed shell mesh")
    morphed = morphed_coords(meshes, asm, files)
    res = check_core(meshes, morphed, samples, doc, vals, u.get("expected_measured") or {}, u.get("changed") or {}, o, asm, thick, {"dist_of": tag_dist}, files)
    out_files = []
    if res.status == "PASS":
        for rel, data in files:
            dst = ofd / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            tmp = dst.with_name(f".{dst.name}.{os.getpid()}.tmp")
            tmp.write_bytes(data)
            replace_retry(tmp, dst)
            out_files.append(rel)
    out.write_text(CHECK_JSON, dumps(report(res, o, out_files, t0)))
    out.commit([CHECK_JSON])
    rep.progress(100, f"shell check {res.status}")
    rep.result(res.status, res.code, CHECK_JSON)
    return EXIT_OK if res.status == "PASS" else EXIT_CHECK


def argparse_like(args):
    import argparse

    return argparse.Namespace(features=args.features, tag_dir=args.tag_dir, fixed_dir=args.fixed_dir, assem_dir=args.assem_dir, update_dir=args.update_dir)
