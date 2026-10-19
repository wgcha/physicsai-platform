"""Analytic fake kernel (axis-aligned box) implementing ``paicad.kernel.base.BodyGeom`` without OCCT."""

from __future__ import annotations

import itertools

import numpy as np
from paicad.kernel.base import BodySummary, EdgeData, FaceData, Topology


class FakeBox:
    def __init__(self, name: str, lo, hi):
        self.name = name
        self.lo, self.hi = np.asarray(lo, float), np.asarray(hi, float)
        corners = np.array(list(itertools.product(*zip(self.lo, self.hi))))  # 8, index bits (x,y,z)
        self._v = corners
        faces, edges = [], []
        eid = {}
        for a, b in itertools.combinations(range(8), 2):
            if np.count_nonzero(corners[a] != corners[b]) == 1:
                eid[(a, b)] = len(edges) + 1
                edges.append((a, b))
        self._edges = edges
        fid = 0
        self._faces = []
        for axis in range(3):
            for side in (0, 1):
                fid += 1
                verts = [i for i in range(8) if np.isclose(corners[i][axis], (self.lo, self.hi)[side][axis])]
                fe = tuple(sorted(eid[(a, b)] for (a, b) in edges if a in verts and b in verts))
                n = np.zeros(3)
                n[axis] = 1.0 if side else -1.0
                pts = corners[verts]
                bb = np.concatenate([pts.min(0), pts.max(0)])
                ext = np.delete(bb[3:] - bb[:3], axis)
                self._faces.append((axis, side, verts, fe, n, bb))
                faces.append(
                    FaceData(
                        id=fid, surface="PLANE", area=float(np.prod(ext)), centroid=pts.mean(0), bbox=bb, edges=fe, outer_edges=fe,
                        inner_wires=(), uv_bounds=(0.0, 1.0, 0.0, 1.0), normal=n,
                    )
                )
        e_data = []
        for k, (a, b) in enumerate(edges, 1):
            fs = tuple(f.id for f in faces if k in f.edges)
            pts = corners[[a, b]]
            e_data.append(
                EdgeData(id=k, curve="LINE", length=float(np.linalg.norm(pts[1] - pts[0])), vertices=(a + 1, b + 1), faces=fs, convexity="CONVEX",
                         bbox=np.concatenate([pts.min(0), pts.max(0)]), dihedral_deg=90.0)
            )
        self._topo = Topology(faces=tuple(faces), edges=tuple(e_data), vertices=corners.copy())

    def summary(self):
        return BodySummary(self.name, float(np.prod(self.hi - self.lo)), np.concatenate([self.lo, self.hi]), 6, 12, 8)

    def topology(self):
        return self._topo

    def project_to_edge(self, edge_id, pts):
        a, b = self._v[list(self._edges[edge_id - 1])]
        pts = np.asarray(pts, float).reshape(-1, 3)
        d = b - a
        t = np.clip((pts - a) @ d / (d @ d), 0, 1)
        foot = a + t[:, None] * d
        return np.linalg.norm(pts - foot, axis=1), t, foot

    def _uv_axes(self, axis):
        return [k for k in range(3) if k != axis]

    def project_to_face(self, face_id, pts):
        axis, side, _, _, n, bb = self._faces[face_id - 1]
        pts = np.asarray(pts, float).reshape(-1, 3)
        foot = pts.copy()
        foot[:, axis] = bb[axis]
        u, v = self._uv_axes(axis)
        uv = np.stack([(foot[:, u] - bb[u]) / (bb[3 + u] - bb[u]), (foot[:, v] - bb[v]) / (bb[3 + v] - bb[v])], axis=1)
        inside = np.all((uv >= -1e-9) & (uv <= 1 + 1e-9), axis=1)
        return np.abs(pts[:, axis] - bb[axis]), uv, inside, foot

    def eval_face(self, face_id, uv):
        axis, side, _, _, n, bb = self._faces[face_id - 1]
        uv = np.asarray(uv, float).reshape(-1, 2)
        u, v = self._uv_axes(axis)
        p = np.zeros((len(uv), 3))
        p[:, axis] = bb[axis]
        p[:, u] = bb[u] + uv[:, 0] * (bb[3 + u] - bb[u])
        p[:, v] = bb[v] + uv[:, 1] * (bb[3 + v] - bb[v])
        return p, np.tile(n, (len(uv), 1))

    def sample_face(self, face_id, n):
        g = (np.arange(n) + 0.5) / n
        uv = np.array([(a, b) for a in g for b in g])
        return self.eval_face(face_id, uv)[0]

    def points_inside(self, pts):
        pts = np.asarray(pts, float).reshape(-1, 3)
        return np.all((pts > self.lo) & (pts < self.hi), axis=1)
