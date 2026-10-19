"""Parameter re-measurement on the morphed mesh (contract section 6.5 (a)), numpy only.

Feature faces are found on the mesh through the tag classification: a skin triangle belongs to
face F when F is the only face common to its three nodes (face node -> its face, edge node ->
the edge's faces, vertex node -> the vertex's faces); ties are resolved by the triangle normal.
Planar measures use area-weighted triangle centroids and normals (same definitions as extract),
cylindrical measures fit a circle to all nodes on the face (face, edge and vertex nodes).
"""

from __future__ import annotations

import math

import numpy as np

from .kernel.base import Topology
from .meshdata import KIND_EDGE, KIND_FACE, KIND_VERTEX, Comp


class FaceIndex:
    """Mesh <-> sample-face lookup for one component (all ids are sample B-rep ids)."""

    def __init__(self, comp: Comp, topo: Topology, fmap: dict, base_xyz: np.ndarray):
        self.comp = comp
        self.topo = topo
        F, E, V = (fmap[k] for k in ("F", "E", "V"))
        n = len(comp.node_ids)
        self.ent = np.full(n, -1, dtype=np.int64)
        for kind, m in ((KIND_FACE, F), (KIND_EDGE, E), (KIND_VERTEX, V)):
            sel = comp.kind == kind
            self.ent[sel] = [int(m[str(int(x))]) for x in comp.entity[sel]]
        vfaces: dict[int, set[int]] = {}
        for e in topo.edges:
            for v in e.vertices:
                vfaces.setdefault(v, set()).update(e.faces)
        self.closure: list[frozenset] = []
        for i in range(n):
            k = comp.kind[i]
            if k == KIND_FACE:
                c = frozenset([int(self.ent[i])])
            elif k == KIND_EDGE:
                c = frozenset(topo.edge(int(self.ent[i])).faces)
            elif k == KIND_VERTEX:
                c = frozenset(vfaces.get(int(self.ent[i]), ()))
            else:
                c = frozenset()
            self.closure.append(c)
        P = base_xyz[comp.gidx]
        tri = comp.skin
        nrm = np.cross(P[tri[:, 1]] - P[tri[:, 0]], P[tri[:, 2]] - P[tri[:, 0]])
        self.tri_face = np.full(len(tri), -1, dtype=np.int64)
        for t, (a, b, c) in enumerate(tri):
            common = self.closure[a] & self.closure[b] & self.closure[c]
            if len(common) == 1:
                self.tri_face[t] = next(iter(common))
            elif len(common) > 1:
                best, score = -1, -2.0
                nn = nrm[t] / (np.linalg.norm(nrm[t]) or 1.0)
                for f in sorted(common):
                    fd = topo.face(f)
                    if fd.normal is None:
                        continue
                    s = float(np.dot(nn, fd.normal))
                    if s > score:
                        best, score = f, s
                self.tri_face[t] = best

    def nodes_on(self, f: int) -> np.ndarray:
        return np.array([i for i, c in enumerate(self.closure) if f in c], dtype=np.int64)

    def plane(self, f: int, P: np.ndarray) -> tuple[np.ndarray, np.ndarray] | None:
        """(area-weighted centroid, unit normal oriented like the B-rep face) of face f on coordinates P (local rows)."""
        tri = self.comp.skin[self.tri_face == f]
        if len(tri) == 0:
            return None
        a, b, c = P[tri[:, 0]], P[tri[:, 1]], P[tri[:, 2]]
        cr = np.cross(b - a, c - a)
        ar = 0.5 * np.linalg.norm(cr, axis=1)
        tot = float(ar.sum())
        if tot <= 0:
            return None
        cen = ((a + b + c) / 3.0 * ar[:, None]).sum(axis=0) / tot
        n = cr.sum(axis=0)
        n = n / (np.linalg.norm(n) or 1.0)
        ref = self.topo.face(f).normal
        if ref is not None and float(np.dot(n, ref)) < 0:
            n = -n
        return cen, n


def _circle_fit(pts: np.ndarray, axis: np.ndarray) -> tuple[np.ndarray, float] | None:
    """Algebraic (Kasa) circle fit of points projected on the plane normal to ``axis``. Returns (3D center, radius)."""
    if len(pts) < 3:
        return None
    d = axis / np.linalg.norm(axis)
    tmp = np.array([1.0, 0.0, 0.0]) if abs(d[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    x = np.cross(d, tmp)
    x /= np.linalg.norm(x)
    y = np.cross(d, x)
    o = pts.mean(axis=0)
    q = pts - o
    u, v = q @ x, q @ y
    A = np.column_stack([2 * u, 2 * v, np.ones_like(u)])
    rhs = u * u + v * v
    sol, *_ = np.linalg.lstsq(A, rhs, rcond=None)
    a, b, c = sol
    r2 = c + a * a + b * b
    if not (r2 > 0 and math.isfinite(r2)):
        return None
    return o + a * x + b * y + float(np.dot(q.mean(axis=0), d)) * d, math.sqrt(r2)


def measure_feature(feat: dict, fi: FaceIndex, fmapF: dict, P: np.ndarray) -> float | None:
    """Value of one feature on local coordinates P of its component (None = cannot measure)."""
    faces = [int(fmapF[str(int(x[1:]))]) for x in feat["measure"]["faces"]]
    meth = feat["measure"]["method"]
    if meth in ("face_distance", "pocket_width", "pocket_depth", "rib_height"):
        if len(faces) != 2:
            return None
        pa, pb = fi.plane(faces[0], P), fi.plane(faces[1], P)
        if pa is None or pb is None:
            return None
        (ca, na), (cb, nb) = pa, pb
        if meth in ("face_distance", "pocket_width"):
            return 0.5 * (abs(float(np.dot(ca - cb, nb))) + abs(float(np.dot(cb - ca, na))))
        if meth == "rib_height":
            return float(np.dot(ca - cb, na))
        return float(np.dot(cb - ca, na))  # pocket_depth: entry - floor along the floor normal
    if meth in ("hole_radius", "fillet_radius", "hole_center"):
        f = faces[0]
        fd = fi.topo.face(f)
        if fd.axis_dir is None:
            return None
        idx = fi.nodes_on(f)
        fit = _circle_fit(P[idx], np.asarray(fd.axis_dir, dtype=float))
        if fit is None:
            return None
        center, r = fit
        if meth != "hole_center":
            return r
        ax = "xyz".index(feat["measure"].get("axis", "x"))
        return float(center[ax] - P[:, ax].min())
    return None
