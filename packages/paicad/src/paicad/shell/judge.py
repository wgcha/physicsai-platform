"""Mesh-only judgement core of the shell check (shell-morph SM-C8, section 14.6).

Everything here is decided from mesh arrays alone - node coordinates (baseline ``x0`` and morphed ``x``),
element connectivity, the tag classification (``kind`` / ``entity``), integer face-edge-vertex incidence
tables, the fixed mask and the feature / hold labels - so that the same judgement is obtained from arrays
in memory and from arrays read back from written ``.rad`` / ``.inc`` files (V-SM-21). numpy / scipy only:
no ``kernel/`` import, no B-rep evaluation. The B-rep based checks (a) re-measure, (b) deviation,
(d) interference and (e) tie stay in ``check.py``.

Provided judgements:

* :func:`strict_labels` - SM-C5 element -> face label (-1 = mixed);
* :func:`element_faces` - the lenient element -> face assignment of the morph (same rule as ``morph``);
* :func:`fixed_judge` - (f) fixed nodes, ``fixed.policy`` (SM-C6);
* :func:`quality_judge` - (c) quality with ``quality.fail_policy`` (inversion / dt_ratio always fail);
* :func:`feature_judge` - (g) island rigidity ``SHELL_FEATURE_DISTORTED`` (SM-C4);
* :func:`hold_weights` - SM-C7 hold factor phi(g) from the mesh geodesic distance to the anchors;
* :func:`mesh_islands` - mesh based bottom islands (tag consistency diagnostic ``TAG_ISLAND_MISMATCH``);
* :func:`judge_mesh` - all of the above combined with the policy / priority rules.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components, dijkstra

from ..common import rnd
from .quality import evaluate as quality_eval

KIND_FACE, KIND_EDGE, KIND_VERTEX = 1, 2, 3
# rank of a failure code in the final decision (section 14.4: feature distortion / inversion -> fixed (skip) ->
# interference -> quality (skip) -> deviation -> param -> tie)
RANK = {"SHELL_FEATURE_DISTORTED": 0, "GEOM_QUALITY_HARD": 1, "SHELL_FIXED_REGION_VIOLATION": 2, "GEOM_INTERFERENCE": 3, "GEOM_QUALITY": 4,
        "GEOM_DEVIATION": 5, "GEOM_PARAM_MISMATCH": 6, "GEOM_TIE_PROJECTION": 7}
# both policies skip: the 0.14.1 order (inversion / dt_ratio are plain GEOM_QUALITY, after fixed and interference)
RANK_SKIP = {"SHELL_FEATURE_DISTORTED": 0, "SHELL_FIXED_REGION_VIOLATION": 1, "GEOM_INTERFERENCE": 2, "GEOM_QUALITY_HARD": 3, "GEOM_QUALITY": 3,
             "GEOM_DEVIATION": 4, "GEOM_PARAM_MISMATCH": 5, "GEOM_TIE_PROJECTION": 6}


def final_code(fails: dict, o: dict) -> str | None:
    """Code of the decision: base order with both policies ``skip``, else inversion / dt_ratio before fixed."""
    skip = o["fixed"]["policy"] == "skip" and o["quality"].get("fail_policy", "skip") == "skip"
    rank = RANK_SKIP if skip else RANK
    codes = [c for c in fails if c in rank]
    return min(codes, key=lambda c: (rank[c], RANK[c])) if codes else None


# ------------------------------------------------------------------ topology tables
@dataclass
class Tables:
    """Integer face-edge-vertex incidence of one body (plus plane normals), neutral arrays only."""

    n_faces: int
    face_edge: np.ndarray  # (k,2) int64 rows (face, edge)
    edge_vertex: np.ndarray  # (k,2) int64 rows (edge, vertex)
    face_normal: np.ndarray  # (n_faces+1, 3) float, NaN rows for non-planar faces

    @classmethod
    def from_topology(cls, topo) -> "Tables":
        fe = [(f.id, e) for f in topo.faces for e in f.edges]
        ev = [(e.id, v) for e in topo.edges for v in e.vertices]
        fn = np.full((len(topo.faces) + 1, 3), np.nan)
        for f in topo.faces:
            if f.surface == "PLANE" and f.normal is not None:
                n = np.asarray(f.normal, dtype=float)
                fn[f.id] = n / np.linalg.norm(n)
        return cls(len(topo.faces), np.asarray(fe, dtype=np.int64).reshape(-1, 2), np.asarray(ev, dtype=np.int64).reshape(-1, 2), fn)

    def face_vertex(self) -> np.ndarray:
        if not len(self.face_edge) or not len(self.edge_vertex):
            return np.zeros((0, 2), dtype=np.int64)
        order = np.argsort(self.edge_vertex[:, 0], kind="stable")
        ev = self.edge_vertex[order]
        lo = np.searchsorted(ev[:, 0], self.face_edge[:, 1], "left")
        hi = np.searchsorted(ev[:, 0], self.face_edge[:, 1], "right")
        rows = [(f, int(v)) for (f, _), a, b in zip(self.face_edge, lo, hi) for v in ev[a:b, 1]]
        return np.unique(np.asarray(rows, dtype=np.int64).reshape(-1, 2), axis=0)


def _pair_member(a: np.ndarray, b: np.ndarray, table: np.ndarray, nb: int) -> np.ndarray:
    """bool: (a[i], b[i]) is a row of ``table`` (rows (a, b)); keys a * nb + b, sorted search."""
    if not len(table):
        return np.zeros(len(a), dtype=bool)
    keys = np.unique(table[:, 0] * nb + table[:, 1])
    q = a.astype(np.int64) * nb + b.astype(np.int64)
    i = np.clip(np.searchsorted(keys, q), 0, len(keys) - 1)
    return keys[i] == q


def _elem_nodes(conn: np.ndarray, tri: np.ndarray) -> np.ndarray:
    """(m,4) local node indices with -1 in the unused 4th slot of triangles."""
    c = np.asarray(conn, dtype=np.int64).copy()
    c[np.asarray(tri, dtype=bool), 3] = -1
    return c


def _normals(x: np.ndarray, conn: np.ndarray, tri: np.ndarray) -> np.ndarray:
    a, b, c, d = (x[conn[:, i]] for i in range(4))
    n = np.where(tri[:, None], np.cross(b - a, c - a), np.cross(c - a, d - b))
    return n / np.maximum(np.linalg.norm(n, axis=1), 1e-300)[:, None]


# ------------------------------------------------------------------ labels
def strict_labels(x0: np.ndarray, conn: np.ndarray, tri: np.ndarray, kind: np.ndarray, ent: np.ndarray, tables: Tables, angle_deg: float) -> np.ndarray:
    """SM-C5 label per element: f if (i) >= 1 FACE-f node, (ii) no FACE node of another face, (iii) every EDGE /
    VERTEX node on an edge / vertex of f, (iv) planar f: element normal within ``angle_deg`` of the face normal; else -1."""
    en = _elem_nodes(conn, tri)
    m = len(en)
    valid = en >= 0
    safe = np.where(valid, en, 0)
    k = np.where(valid, np.asarray(kind)[safe], 0)
    e = np.where(valid, np.asarray(ent, dtype=np.int64)[safe], 0)
    isf = k == KIND_FACE
    big = np.iinfo(np.int64).max
    fmin = np.where(isf, e, big).min(axis=1)
    fmax = np.where(isf, e, -1).max(axis=1)
    lab = np.where((fmin == fmax) & (fmax >= 0), fmax, -1)
    nf = tables.n_faces + 1
    for kk, table in ((KIND_EDGE, tables.face_edge[:, ::-1]), (KIND_VERTEX, tables.face_vertex()[:, ::-1])):
        sel = (k == kk) & (lab[:, None] >= 0)
        r, c = np.nonzero(sel)
        if len(r):
            ok = _pair_member(e[r, c], lab[r], table, nf)
            bad = np.unique(r[~ok])
            lab[bad] = -1
    fn = tables.face_normal
    has = lab >= 0
    if has.any():
        nrm = fn[np.where(has, lab, 0)]
        planar = has & np.isfinite(nrm[:, 0])
        if planar.any():
            ne = _normals(np.asarray(x0, dtype=float), np.asarray(conn, dtype=np.int64), np.asarray(tri, dtype=bool))
            cosv = np.abs(np.einsum("ij,ij->i", ne[planar], nrm[planar]))
            off = cosv < np.cos(np.radians(float(angle_deg))) - 1e-12
            idx = np.flatnonzero(planar)[off]
            lab[idx] = -1
    del m
    return lab.astype(np.int64)


def element_faces(conn: np.ndarray, tri: np.ndarray, kind: np.ndarray, ent: np.ndarray, tables: Tables) -> np.ndarray:
    """The morph's element -> face assignment (FACE majority, ties = smallest face, else the common face of the
    edge / vertex nodes), from the incidence tables only. Vectorized; bit-identical to :func:`element_faces_loop`."""
    en = _elem_nodes(conn, tri)
    m = len(en)
    out = np.full(m, -1, dtype=np.int64)
    if m == 0:
        return out
    valid = en >= 0
    safe = np.where(valid, en, 0)
    k = np.where(valid, np.asarray(kind)[safe], 0)
    e = np.where(valid, np.asarray(ent, dtype=np.int64)[safe], -1)
    F = np.where(k == KIND_FACE, e, -1)
    hasf = (F >= 0).any(axis=1)
    cnt = ((F[:, :, None] == F[:, None, :]) & (F[:, None, :] >= 0)).sum(axis=2)
    cnt[F < 0] = 0
    best = cnt.max(axis=1)
    big = np.iinfo(np.int64).max
    pick = np.where((cnt == best[:, None]) & (F >= 0), F, big).min(axis=1)
    out[hasf] = pick[hasf]
    # no FACE node: smallest face common to every EDGE / VERTEX node (node order = intersection order, empty -> -1)
    cons = ((k == KIND_EDGE) | (k == KIND_VERTEX)) & ~hasf[:, None]
    rows = np.flatnonzero(cons.any(axis=1))
    if not len(rows):
        return out
    nf = tables.n_faces + 1
    fe = tables.face_edge[:, ::-1]  # (edge, face)
    fv = tables.face_vertex()[:, ::-1]  # (vertex, face)
    first = np.argmax(cons[rows], axis=1)
    k0, e0 = k[rows, first], e[rows, first]
    pr, pf = [], []
    for kk, tab in ((KIND_EDGE, fe), (KIND_VERTEX, fv)):
        sel = np.flatnonzero(k0 == kk)
        if not len(sel) or not len(tab):
            continue
        order = np.argsort(tab[:, 0], kind="stable")
        t = tab[order]
        lo = np.searchsorted(t[:, 0], e0[sel], "left")
        hi = np.searchsorted(t[:, 0], e0[sel], "right")
        n_ = hi - lo
        pr.append(np.repeat(rows[sel], n_))
        pf.append(t[np.concatenate([np.arange(a, b) for a, b in zip(lo, hi)]) if n_.sum() else np.zeros(0, dtype=np.int64), 1])
    if not pr:
        return out
    pr, pf = np.concatenate(pr), np.concatenate(pf)
    keep = np.ones(len(pr), dtype=bool)
    for j in range(4):
        kj, ej = k[pr, j], e[pr, j]
        isc = cons[pr, j]
        for kk, tab in ((KIND_EDGE, fe), (KIND_VERTEX, fv)):
            sel = isc & (kj == kk)
            if sel.any():
                keep[sel] &= _pair_member(ej[sel], pf[sel], tab, nf)
    pr, pf = pr[keep], pf[keep]
    if len(pr):
        mn = np.full(m, big)
        np.minimum.at(mn, pr, pf)
        hit = mn < big
        out[hit] = mn[hit]
    return out


def element_faces_loop(conn: np.ndarray, tri: np.ndarray, kind: np.ndarray, ent: np.ndarray, tables: Tables) -> np.ndarray:
    """Reference (per-element loop, 0.15.0) of :func:`element_faces` - kept for the bit-identity tests."""
    edge_faces: dict[int, set[int]] = {}
    for f, ed in tables.face_edge:
        edge_faces.setdefault(int(ed), set()).add(int(f))
    vert_faces: dict[int, set[int]] = {}
    for ed, v in tables.edge_vertex:
        vert_faces.setdefault(int(v), set()).update(edge_faces.get(int(ed), set()))
    out = np.full(len(conn), -1, dtype=np.int64)
    for i, (el, t) in enumerate(zip(conn, tri)):
        nodes = el[:3] if t else el
        fs = [int(ent[j]) for j in nodes if kind[j] == KIND_FACE]
        if fs:
            c = Counter(fs).most_common()
            best = max(n for _, n in c)
            out[i] = min(f for f, n in c if n == best)
            continue
        cand = None
        for j in nodes:
            if kind[j] == KIND_EDGE:
                s = edge_faces.get(int(ent[j]), set())
            elif kind[j] == KIND_VERTEX:
                s = vert_faces.get(int(ent[j]), set())
            else:
                continue
            cand = set(s) if cand is None else cand & s
        if cand:
            out[i] = min(cand)
    return out


# ------------------------------------------------------------------ (f) fixed
def fixed_judge(x0: np.ndarray, x: np.ndarray, fixed: np.ndarray, cluster: np.ndarray | None, policy: str, line_changes: int = 0) -> dict:
    """{"check", "fail": (code, message) | None, "warnings", "waived"}."""
    fixed = np.asarray(fixed, dtype=bool)
    dd = np.linalg.norm(np.asarray(x)[fixed] - np.asarray(x0)[fixed], axis=1)
    moved = int((dd > 0).sum()) + int(line_changes)
    fmax = float(dd.max()) if dd.size else 0.0
    out = {"check": {"status": "PASS", "moved_fixed_nodes": moved, "max_mm": fmax}, "fail": None, "warnings": [], "waived": []}
    if not moved:
        return out
    if policy == "warn":
        cl = sorted({int(c) for c in np.asarray(cluster)[fixed][dd > 0]}) if cluster is not None else []
        out["check"]["status"] = "WARN"
        out["warnings"].append({"code": "SHELL_FIXED_MOVED", "n": moved, "max_mm": rnd(fmax), "clusters": cl,
                                "message": f"fixed.policy warn: {moved} fixed nodes moved (max {fmax:.4f} mm)"})
        out["waived"].append("SHELL_FIXED_REGION_VIOLATION")
    else:
        out["check"]["status"] = "FAIL"
        out["fail"] = ("SHELL_FIXED_REGION_VIOLATION", f"fixed: {moved} fixed nodes changed")
    return out


# ------------------------------------------------------------------ (c) quality
def quality_judge(x0: np.ndarray, x: np.ndarray, conn: np.ndarray, tri: np.ndarray, q: dict) -> dict:
    """Quality report + policy. ``skip``: any failure = GEOM_QUALITY (0.14.1 message); ``warn``: only inversion and
    dt_ratio fail (rank of inversion / dt), the rest becomes ``SHELL_QUALITY_WARN``."""
    rep, msg, warns = quality_eval(x0, x, conn, tri, q)
    hard = []
    if rep["inverted"]:
        hard.append(f"{rep['inverted']} inverted elements")
    if rep["dt_ratio"] is not None and rep["dt_ratio"] < float(q["dt_ratio_min"]):
        hard.append(f"dt_ratio {rep['dt_ratio']:.3f} < {q['dt_ratio_min']}")
    out = {"check": rep, "fail": None, "warnings": list(warns), "waived": []}
    if msg is None:
        return out
    if q.get("fail_policy", "skip") == "warn":
        if hard:
            rep["status"] = "FAIL"
            out["fail"] = ("GEOM_QUALITY_HARD", "quality: " + "; ".join(hard))
        else:
            rep["status"] = "WARN"
            out["warnings"].append({"code": "SHELL_QUALITY_WARN", "failed_elements": rep["failed_elements"], "edge_ratio": rep["edge_ratio"], "dt_ratio": rep["dt_ratio"],
                                    "message": "quality.fail_policy warn: " + msg[len("quality: "):]})
            out["waived"].append("GEOM_QUALITY")
        return out
    out["fail"] = ("GEOM_QUALITY_HARD" if hard else "GEOM_QUALITY", msg)
    return out


# ------------------------------------------------------------------ (g) feature rigidity
def feature_judge(x0: np.ndarray, x: np.ndarray, conn: np.ndarray, tri: np.ndarray, labels: np.ndarray, features: list[dict], q: dict,
                  phi: np.ndarray | None = None) -> dict:
    """SM-C4. ``features``: [{"bead", "island", "faces": [face ids], "rim_zero": bool}]. rim = feature-element nodes
    shared with other elements, interior = the other feature-element nodes; t = mean rim displacement (0 if
    ``rim_zero``); dev = max |u(interior) - t| > max(distort_min_mm, distort_rel * |t|) -> SHELL_FEATURE_DISTORTED.
    ``phi`` (SM-C7 hold factor per node): expected u = phi * t with t = least squares of the rim (u = phi t), so a
    blended island next to hold anchors is judged against the same s(r) attenuation the morph applied."""
    en = _elem_nodes(conn, tri)
    mixed = int((labels < 0).sum())
    u = np.asarray(x, dtype=float) - np.asarray(x0, dtype=float)
    worst = None
    tested = 0
    fail = None
    for ft in features:
        fe = np.isin(labels, np.asarray(ft["faces"], dtype=np.int64))
        if not fe.any():
            continue
        fn = np.unique(en[fe][en[fe] >= 0])
        on = np.unique(en[~fe][en[~fe] >= 0])
        rim = np.intersect1d(fn, on)
        interior = np.setdiff1d(fn, on)
        if not len(interior):
            continue
        tested += 1
        if phi is not None and not ft.get("rim_zero") and np.any(phi[fn] < 1.0):
            w = phi[rim]
            ww = float(w @ w)
            t = (w @ u[rim]) / ww if ww > 1e-12 else np.zeros(3)
            dev = float(np.linalg.norm(u[interior] - phi[interior][:, None] * t, axis=1).max())
        else:
            t = np.zeros(3) if ft.get("rim_zero") or not len(rim) else u[rim].mean(axis=0)
            dev = float(np.linalg.norm(u[interior] - t, axis=1).max())
        floor = max(float(q["distort_min_mm"]), float(q["distort_rel"]) * float(np.linalg.norm(t)))
        item = {"bead": ft["bead"], "island": ft["island"], "dev_mm": dev, "floor_mm": floor}
        if worst is None or dev - floor > worst["dev_mm"] - worst["floor_mm"]:
            worst = item
        if dev > floor and fail is None:
            fail = ("SHELL_FEATURE_DISTORTED", f"{ft['bead']} island {ft['island']}: dev {dev:.4f} mm, floor {floor:.4f} mm")
    check = {"status": "SKIPPED" if not tested else ("FAIL" if fail else "PASS"), "features": tested, "worst": worst, "mixed_elems": mixed}
    return {"check": check, "fail": fail, "warnings": [], "waived": []}


# ------------------------------------------------------------------ SM-C7 hold
def smoothstep(r: np.ndarray) -> np.ndarray:
    r = np.clip(r, 0.0, 1.0)
    return 3 * r * r - 2 * r**3


def hold_weights(x0: np.ndarray, conn: np.ndarray, tri: np.ndarray, elem_face: np.ndarray, region_faces, anchor_faces, fixed: np.ndarray,
                 ring_mm: float, blend_mm: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(phi[n], g[n], region[n]): anchors = fixed nodes of elements on ``anchor_faces`` (bottom pieces + islands);
    g = edge-length geodesic distance to the anchors inside the bead region (elements on ``region_faces``);
    phi = 0 (g <= ring), s((g - ring) / blend) (ring < g < ring + blend), 1 beyond / outside / unreachable."""
    x0 = np.asarray(x0, dtype=float)
    n = len(x0)
    en = _elem_nodes(conn, tri)
    reg_e = np.isin(elem_face, np.asarray(sorted(region_faces), dtype=np.int64))
    anc_e = np.isin(elem_face, np.asarray(sorted(anchor_faces), dtype=np.int64))
    region = np.zeros(n, dtype=bool)
    rn = en[reg_e]
    region[rn[rn >= 0]] = True
    anchors = np.zeros(n, dtype=bool)
    an = en[anc_e]
    anchors[an[an >= 0]] = True
    anchors &= np.asarray(fixed, dtype=bool)
    phi = np.ones(n)
    g = np.full(n, np.inf)
    src = np.flatnonzero(anchors)
    if not len(src):
        return phi, g, region
    c = en[reg_e]
    pairs = [c[:, [0, 1]], c[:, [1, 2]], np.where(c[:, 3:4] >= 0, c[:, [2, 3]], c[:, [2, 0]]), c[:, [3, 0]]]
    e = np.concatenate(pairs)
    e = e[(e >= 0).all(axis=1) & (e[:, 0] != e[:, 1])]
    e = np.unique(np.sort(e, axis=1), axis=0)
    w = np.linalg.norm(x0[e[:, 0]] - x0[e[:, 1]], axis=1)
    G = coo_matrix((w, (e[:, 0], e[:, 1])), shape=(n, n)).tocsr()
    g = dijkstra(G, directed=False, indices=src, min_only=True)
    g[anchors] = 0.0
    inside = region & np.isfinite(g)
    phi[inside] = smoothstep((g[inside] - ring_mm) / blend_mm)
    phi[inside & (g <= ring_mm)] = 0.0
    return phi, g, region


# ------------------------------------------------------------------ mesh islands (SM-C8 diagnostic)
def _element_adjacency(en: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(pairs[k,2] element pairs sharing an edge, free edges[k,2] node pairs, owner element of each free edge)."""
    m = len(en)
    rows = []
    for a, b in ((0, 1), (1, 2), (2, 3), (3, 0)):
        rows.append(np.stack([en[:, a], en[:, b], np.arange(m)], axis=1))
    tri = en[:, 3] < 0
    rows.append(np.stack([en[tri, 2], en[tri, 0], np.flatnonzero(tri)], axis=1))
    E = np.concatenate(rows)
    E = E[(E[:, :2] >= 0).all(axis=1) & (E[:, 0] != E[:, 1])]
    E[:, :2] = np.sort(E[:, :2], axis=1)
    order = np.lexsort((E[:, 2], E[:, 1], E[:, 0]))
    E = E[order]
    key = E[:, 0] * (int(E[:, :2].max()) + 1 if len(E) else 1) + E[:, 1]
    same = np.flatnonzero(key[1:] == key[:-1])
    pairs = np.stack([E[same, 2], E[same + 1, 2]], axis=1)
    _, start, cnt = np.unique(key, return_index=True, return_counts=True)
    free = start[cnt == 1]
    return pairs, E[free, :2], E[free, 2]


def mesh_islands(conn: np.ndarray, tri: np.ndarray, labels: np.ndarray, bottoms: dict[str, list[int]]) -> dict[str, dict]:
    """Bottom islands found on the mesh: per bead {"features": n, "holes": n}. owner = bead of elements labelled on
    its bottom pieces; a component of the other elements whose neighbours all belong to one owner (not the largest
    component) is a feature island; a free-edge chain whose elements all belong to one owner is a hole island."""
    en = _elem_nodes(conn, tri)
    m = len(en)
    owner = np.full(m, -1, dtype=np.int64)
    names = sorted(bottoms)
    for k, b in enumerate(names):
        owner[np.isin(labels, np.asarray(bottoms[b], dtype=np.int64))] = k
    out = {b: {"features": 0, "holes": 0} for b in names}
    if m == 0:
        return out
    pairs, free, free_owner_elem = _element_adjacency(en)
    cand = owner < 0
    ce = np.flatnonzero(cand)
    if len(ce):
        loc = np.full(m, -1, dtype=np.int64)
        loc[ce] = np.arange(len(ce))
        pp = pairs[cand[pairs[:, 0]] & cand[pairs[:, 1]]]
        A = coo_matrix((np.ones(len(pp)), (loc[pp[:, 0]], loc[pp[:, 1]])), shape=(len(ce), len(ce)))
        nc, lab = connected_components(A, directed=False)
        size = np.bincount(lab, minlength=nc)
        first = np.full(nc, np.iinfo(np.int64).max)
        np.minimum.at(first, lab, ce)
        order = np.argsort(first, kind="stable")
        big = int(order[np.argmax(size[order])])
        cross = pairs[cand[pairs[:, 0]] != cand[pairs[:, 1]]]
        ce_side = np.where(cand[cross[:, 0]], cross[:, 0], cross[:, 1])
        ow_side = np.where(cand[cross[:, 0]], cross[:, 1], cross[:, 0])
        comp_owner: dict[int, set[int]] = {}
        for c_, o_ in zip(lab[loc[ce_side]], owner[ow_side]):
            comp_owner.setdefault(int(c_), set()).add(int(o_))
        for c_ in range(nc):
            if c_ == big:
                continue
            ow = comp_owner.get(c_, set())
            if len(ow) == 1:
                out[names[next(iter(ow))]]["features"] += 1
    # hole islands: chains of free edges owned by elements of one bead bottom
    if len(free):
        fo = owner[free_owner_elem]
        for k, b in enumerate(names):
            fe = free[fo == k]
            if not len(fe):
                continue
            nodes, inv = np.unique(fe.ravel(), return_inverse=True)
            inv = inv.reshape(-1, 2)
            G = coo_matrix((np.ones(len(inv)), (inv[:, 0], inv[:, 1])), shape=(len(nodes), len(nodes)))
            ncomp, lab = connected_components(G, directed=False)
            # a chain also touching free edges of other owners is not closed inside this bottom
            other = free[fo != k]
            touch = set(np.flatnonzero(np.isin(nodes, other.ravel())).tolist()) if len(other) else set()
            bad = {int(lab[i]) for i in touch}
            out[b]["holes"] += sum(1 for c_ in range(ncomp) if c_ not in bad)
    return out


# ------------------------------------------------------------------ combined
@dataclass
class JudgeInput:
    """Mesh arrays of one shell part (local node indices)."""

    node_ids: np.ndarray
    x0: np.ndarray
    x: np.ndarray
    conn: np.ndarray
    tri: np.ndarray
    kind: np.ndarray
    ent: np.ndarray
    fixed: np.ndarray
    cluster: np.ndarray | None
    tables: Tables
    features: list[dict] = field(default_factory=list)  # (g) items, see feature_judge
    hold: list[dict] = field(default_factory=list)  # [{"bead", "region_faces", "anchor_faces"}]
    line_changes: int = 0


def judge_mesh(J: JudgeInput, o: dict) -> dict:
    """Mesh judgement of one part: {"checks": {fixed, quality, feature, hold?}, "fails": {code: message}, "warnings", "waived",
    "hold_nodes": bool[n] (excluded from the B-rep checks)}. Codes use the internal GEOM_QUALITY_HARD for inversion / dt_ratio."""
    labels = strict_labels(J.x0, J.conn, J.tri, J.kind, J.ent, J.tables, float(o["tag"]["label_angle_deg"]))
    out = {"checks": {}, "fails": {}, "warnings": [], "waived": [], "labels": labels}
    fj = fixed_judge(J.x0, J.x, J.fixed, J.cluster, o["fixed"]["policy"], J.line_changes)
    qj = quality_judge(J.x0, J.x, J.conn, J.tri, o["quality"])
    hold_nodes = np.zeros(len(J.x0), dtype=bool)
    phi_all = np.ones(len(J.x0))
    hold_items = []
    hold_faces: set[int] = set()
    if J.hold:
        ef = element_faces(J.conn, J.tri, J.kind, J.ent, J.tables)
        hb = o["bead"]["hold"]
        ring, blend = float(hb["ring_mm"]), float(hb["blend_mm"])
        for h in J.hold:
            phi, g, region = hold_weights(J.x0, J.conn, J.tri, ef, h["region_faces"], h["anchor_faces"], J.fixed, ring, blend)
            phi_all[region] = np.minimum(phi_all[region], phi[region])
            sel = region & (g < ring + blend)
            hold_nodes |= sel
            hold_faces |= set(h["anchor_faces"])
            hold_items.append({"bead": h["bead"], "nodes": int(sel.sum())})
    held_beads = {h["bead"] for h in J.hold}
    feats = []
    en = _elem_nodes(J.conn, J.tri)
    fixed = np.asarray(J.fixed, dtype=bool)
    for f in J.features:  # islands holding hold anchors (fixed nodes) are intentionally deformed: not tested
        if f["bead"] in held_beads and (hold_faces & set(f["faces"])):
            fn = en[np.isin(labels, np.asarray(f["faces"], dtype=np.int64))]
            if fixed[fn[fn >= 0]].any():
                continue
        feats.append(f)
    gj = feature_judge(J.x0, J.x, J.conn, J.tri, labels, feats, o["quality"], phi_all if J.hold else None)
    for name, r in (("fixed", fj), ("quality", qj), ("feature", gj)):
        out["checks"][name] = r["check"]
        out["warnings"] += r["warnings"]
        out["waived"] += r["waived"]
        if r["fail"]:
            out["fails"].setdefault(r["fail"][0], r["fail"][1])
    if J.hold:
        u = np.linalg.norm(np.asarray(J.x) - np.asarray(J.x0), axis=1)
        out["checks"]["hold"] = {"beads": [h["bead"] for h in hold_items], "nodes": int(hold_nodes.sum()), "ring_mm": float(o["bead"]["hold"]["ring_mm"]),
                                 "blend_mm": float(o["bead"]["hold"]["blend_mm"]), "max_disp_mm": float(u[hold_nodes].max()) if hold_nodes.any() else 0.0}
    out["hold_nodes"] = hold_nodes
    return out


def rounded(obj, nd: int = 9):
    """JSON-like copy with floats rounded (V-SM-21 comparison of judgements)."""
    if isinstance(obj, dict):
        return {k: rounded(v, nd) for k, v in obj.items() if k not in ("labels", "hold_nodes")}
    if isinstance(obj, (list, tuple)):
        return [rounded(v, nd) for v in obj]
    if isinstance(obj, float):
        return round(obj, nd)
    if isinstance(obj, np.ndarray):
        return rounded(obj.tolist(), nd)
    if isinstance(obj, (np.floating,)):
        return round(float(obj), nd)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    return obj
