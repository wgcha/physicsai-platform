"""Mesh-side geometry helpers (numpy/scipy only)."""

from __future__ import annotations

import numpy as np
from scipy.spatial import cKDTree


def point_triangle_distance(p: np.ndarray, a: np.ndarray, b: np.ndarray, c: np.ndarray) -> np.ndarray:
    """Vectorized exact distance from points p[k] to triangles (a[k], b[k], c[k]) (Ericson, RTCD 5.1.5)."""
    ab, ac, ap = b - a, c - a, p - a
    d1 = np.einsum("ij,ij->i", ab, ap)
    d2 = np.einsum("ij,ij->i", ac, ap)
    bp = p - b
    d3 = np.einsum("ij,ij->i", ab, bp)
    d4 = np.einsum("ij,ij->i", ac, bp)
    cp = p - c
    d5 = np.einsum("ij,ij->i", ab, cp)
    d6 = np.einsum("ij,ij->i", ac, cp)
    va = d3 * d6 - d5 * d4
    vb = d5 * d2 - d1 * d6
    vc = d1 * d4 - d3 * d2
    denom = va + vb + vc
    with np.errstate(divide="ignore", invalid="ignore"):
        v = np.where(denom != 0, vb / denom, 0.0)
        w = np.where(denom != 0, vc / denom, 0.0)
    q = a + ab * v[:, None] + ac * w[:, None]  # interior default

    def setq(mask, val):
        q[mask] = val[mask]

    # edge regions
    with np.errstate(divide="ignore", invalid="ignore"):
        m = (vc <= 0) & (d1 >= 0) & (d3 <= 0)
        t = np.where(m, d1 / np.where(d1 - d3 != 0, d1 - d3, 1), 0)
        setq(m, a + ab * t[:, None])
        m = (vb <= 0) & (d2 >= 0) & (d6 <= 0)
        t = np.where(m, d2 / np.where(d2 - d6 != 0, d2 - d6, 1), 0)
        setq(m, a + ac * t[:, None])
        m = (va <= 0) & ((d4 - d3) >= 0) & ((d5 - d6) >= 0)
        den = (d4 - d3) + (d5 - d6)
        t = np.where(m, (d4 - d3) / np.where(den != 0, den, 1), 0)
        setq(m, b + (c - b) * t[:, None])
    # vertex regions (last: highest priority)
    setq((d6 >= 0) & (d5 <= d6), c)
    setq((d3 >= 0) & (d4 <= d3), b)
    setq((d1 <= 0) & (d2 <= 0), a)
    return np.linalg.norm(p - q, axis=1)


class TriangleSet:
    """Nearest-distance queries against a triangle soup tris[k,3,3]."""

    def __init__(self, tris: np.ndarray):
        self.tris = np.asarray(tris, dtype=float).reshape(-1, 3, 3)
        if len(self.tris):
            self.cent = self.tris.mean(axis=1)
            self.rad = np.linalg.norm(self.tris - self.cent[:, None, :], axis=2).max(axis=1)
            self.tree = cKDTree(self.cent)
            self.rmax = float(self.rad.max())
        else:
            self.tree = None

    def distance(self, pts: np.ndarray, cutoff: float) -> tuple[np.ndarray, np.ndarray]:
        """(dist[n], tri index[n]); dist = inf (index -1) when nothing within ``cutoff``."""
        pts = np.asarray(pts, dtype=float).reshape(-1, 3)
        dist = np.full(len(pts), np.inf)
        idx = np.full(len(pts), -1, dtype=np.int64)
        if self.tree is None or len(pts) == 0:
            return dist, idx
        cand = self.tree.query_ball_point(pts, r=cutoff + self.rmax)
        pi = np.repeat(np.arange(len(pts)), [len(c) for c in cand])
        ti = np.fromiter((t for c in cand for t in c), dtype=np.int64, count=len(pi))
        if len(pi) == 0:
            return dist, idx
        t = self.tris[ti]
        d = point_triangle_distance(pts[pi], t[:, 0], t[:, 1], t[:, 2])
        order = np.lexsort((d, pi))
        pi, ti, d = pi[order], ti[order], d[order]
        first = np.ones(len(pi), dtype=bool)
        first[1:] = pi[1:] != pi[:-1]
        sel = first & (d <= cutoff)
        dist[pi[sel]] = d[sel]
        idx[pi[sel]] = ti[sel]
        return dist, idx
