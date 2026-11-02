"""paicad 0.14.1: ``classify_points`` / ``_consistency`` / collision polyline distances without dense
(N_pts x N_entity x 3) broadcasts (geometry-engine.md section 6.1, section 17.2 PATCH = results unchanged).

The 0.14.0 algorithms are kept below verbatim as reference implementations; the new code must give
bit-identical kind / entity / uv / dist (ties included) and bounded peak memory on a 222,924-point x
7,168-vertex case (the reported ``GEOM_INTERNAL`` MemoryError: 35.7 GiB for (222924, 7168, 3)).
"""

from __future__ import annotations

import time
import tracemalloc

import numpy as np
import pytest
from paicad import collision, tag
from paicad.kernel.base import EdgeData, FaceData, Topology
from paicad.tag import KIND_EDGE, KIND_FACE, KIND_UNMATCHED, KIND_VERTEX

# ----------------------------------------------------------------------------- 0.14.0 reference code


def ref_classify_points(body, pts, tol):
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


def ref_consistency(body, pts, kind, ent, uv, dist, tris_local, tol, warnings, part):
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


def ref_seg_intersections(P, Q, skip_adjacent=False):
    a, b = P, np.roll(P, -1, axis=0)
    c, d = Q, np.roll(Q, -1, axis=0)

    def orient(p, q, r):
        return (q[..., 0] - p[..., 0]) * (r[..., 1] - p[..., 1]) - (q[..., 1] - p[..., 1]) * (r[..., 0] - p[..., 0])

    A, B = a[:, None, :], b[:, None, :]
    C, D = c[None, :, :], d[None, :, :]
    o1, o2 = orient(A, B, C), orient(A, B, D)
    o3, o4 = orient(C, D, A), orient(C, D, B)
    scale = max(1.0, float(np.abs(P).max()), float(np.abs(Q).max()))
    eps = 1e-12 * scale * scale
    hit = (o1 * o2 < -eps) & (o3 * o4 < -eps)
    if skip_adjacent:
        n = len(P)
        i, j = np.indices(hit.shape)
        near = (np.abs(i - j) <= 1) | (np.abs(i - j) == n - 1)
        hit &= ~near
    return bool(hit.any())


def ref_min_dist(P, Q):
    if ref_seg_intersections(P, Q):
        return 0.0
    d1 = collision._point_seg_dist(P, Q, np.roll(Q, -1, axis=0)).min()
    d2 = collision._point_seg_dist(Q, P, np.roll(P, -1, axis=0)).min()
    return float(min(d1, d2))


# ----------------------------------------------------------------------------- synthetic kernel


class SynthBody:
    """Vertices / segment edges / axis-aligned rectangle faces; every projection is per-point independent."""

    name = "SYN"

    def __init__(self, V, edges, rects):
        self.V = np.asarray(V, dtype=float).reshape(-1, 3)
        self.E = [(int(a), int(b)) for a, b in edges]  # 0-based vertex rows
        self.R = rects  # [(axis, level, lo2[2], hi2[2])]
        es = []
        for i, (a, b) in enumerate(self.E, 1):
            p, q = self.V[a], self.V[b]
            es.append(EdgeData(id=i, curve="LINE", length=float(np.linalg.norm(q - p)), vertices=(a + 1, b + 1), faces=(), convexity="UNKNOWN",
                               bbox=np.concatenate([np.minimum(p, q), np.maximum(p, q)])))
        fs = []
        ne = len(self.E)
        for i, (ax, lev, lo2, hi2) in enumerate(self.R, 1):
            u, v = [k for k in range(3) if k != ax]
            lo, hi = np.zeros(3), np.zeros(3)
            lo[ax] = hi[ax] = lev
            lo[[u, v]], hi[[u, v]] = lo2, hi2
            # face edges: a few edge ids so the triangle-consistency pass has common edges to try
            fe = tuple(sorted({1 + (i * 7 + k) % ne for k in range(4)})) if ne else ()
            fs.append(FaceData(id=i, surface="PLANE", area=float(np.prod(np.subtract(hi2, lo2))), centroid=(lo + hi) / 2, bbox=np.concatenate([lo, hi]),
                               edges=fe, outer_edges=fe, inner_wires=(), uv_bounds=(0.0, 1.0, 0.0, 1.0), normal=np.eye(3)[ax]))
        self._topo = Topology(faces=tuple(fs), edges=tuple(es), vertices=self.V)
        self.calls = 0

    def topology(self):
        return self._topo

    def project_to_edge(self, edge_id, pts):
        self.calls += 1
        a, b = self.V[list(self.E[edge_id - 1])]
        pts = np.asarray(pts, float).reshape(-1, 3)
        d = b - a
        L2 = float((d * d).sum())
        t = np.clip(((pts - a) * d).sum(axis=1) / L2, 0.0, 1.0) if L2 > 0 else np.zeros(len(pts))
        foot = a + t[:, None] * d
        return np.linalg.norm(pts - foot, axis=1), t, foot

    def project_to_face(self, face_id, pts):
        self.calls += 1
        ax, lev, lo2, hi2 = self.R[face_id - 1]
        u, v = [k for k in range(3) if k != ax]
        pts = np.asarray(pts, float).reshape(-1, 3)
        foot = pts.copy()
        foot[:, ax] = lev
        uv = np.stack([(pts[:, u] - lo2[0]) / (hi2[0] - lo2[0]), (pts[:, v] - lo2[1]) / (hi2[1] - lo2[1])], axis=1)
        inside = np.all((uv >= 0.0) & (uv <= 1.0), axis=1)
        return np.abs(pts[:, ax] - lev), uv, inside, foot


def _random_body(rng, nv, ne, nf, size=100.0):
    V = rng.uniform(0, size, (nv, 3))
    V = np.round(V, 1)  # coarse grid -> exact ties between points, vertices, edges
    if nv >= 4:
        V[1] = V[0]  # duplicate vertex: equal distances, lowest index must win
        V[3] = V[2]
    edges = []
    for _ in range(ne):
        a = int(rng.integers(nv))
        b = int(np.argsort(np.linalg.norm(V - V[a], axis=1))[int(rng.integers(1, min(6, nv)))])
        edges.append((a, b))
    if ne >= 2:
        edges.append(edges[0])  # duplicate edge: equal distance, first edge must win
    rects = []
    for _ in range(nf):
        ax = int(rng.integers(3))
        lev = float(np.round(rng.uniform(0, size), 1))
        c = rng.uniform(0, size, 2)
        w = rng.uniform(5, 40, 2)
        rects.append((ax, lev, np.round(c - w, 1), np.round(c + w, 1)))
    if nf:
        rects.append(rects[0])  # duplicate face
    return SynthBody(V, edges, rects)


def _points_for(rng, body, n, tol):
    V = body.V
    parts = []
    k = n // 6
    # near vertices (some exactly at the vertex, some at exactly tol along an axis)
    iv = rng.integers(len(V), size=k)
    off = np.round(rng.normal(0, tol, (k, 3)), 3)
    off[: k // 4] = 0.0
    ax = rng.integers(3, size=k // 8)
    off[k // 4 : k // 4 + k // 8] = 0.0
    off[np.arange(k // 4, k // 4 + k // 8), ax] = tol
    parts.append(V[iv] + off)
    # exact midpoints between two vertices (equidistant ties)
    a, b = rng.integers(len(V), size=k), rng.integers(len(V), size=k)
    parts.append((V[a] + V[b]) / 2)
    # near edges
    E = body.E
    ie = rng.integers(len(E), size=k)
    t = np.round(rng.uniform(0, 1, k), 2)[:, None]
    p0, p1 = V[[E[i][0] for i in ie]], V[[E[i][1] for i in ie]]
    parts.append(p0 + t * (p1 - p0) + np.round(rng.normal(0, tol / 2, (k, 3)), 3))
    # on / near faces (including face-overlap ties)
    ifc = rng.integers(len(body.R), size=k)
    P = np.zeros((k, 3))
    for j, fi in enumerate(ifc):
        axf, lev, lo2, hi2 = body.R[fi]
        u, v = [q for q in range(3) if q != axf]
        P[j, axf] = lev + np.round(rng.normal(0, tol / 2), 3)
        P[j, u], P[j, v] = np.round(rng.uniform(lo2 - 1, hi2 + 1), 1)
    parts.append(P)
    # random + non-finite rows
    R = rng.uniform(-5, 105, (n - 4 * k, 3))
    if len(R) >= 3:
        R[0] = np.nan
        R[1, 2] = np.inf
    parts.append(R)
    pts = np.concatenate(parts)
    return pts[rng.permutation(len(pts))]


def _same(a, b):
    for x, y in zip(a, b):
        assert x.dtype == y.dtype and x.shape == y.shape
        assert np.array_equal(x, y, equal_nan=True), np.flatnonzero(~((x == y) | (np.isnan(x) & np.isnan(y))).reshape(len(x), -1).all(1))[:10]


@pytest.mark.parametrize("seed", range(6))
@pytest.mark.parametrize("chunk", [tag.CHUNK, 37])
def test_classify_points_bit_identical(seed, chunk, monkeypatch):
    monkeypatch.setattr(tag, "CHUNK", chunk)
    rng = np.random.default_rng(seed)
    body = _random_body(rng, nv=int(rng.integers(8, 300)), ne=int(rng.integers(5, 200)), nf=int(rng.integers(3, 40)))
    tol = float([0.05, 0.5, 2.0][seed % 3])
    pts = _points_for(rng, body, 3000, tol)
    ref = ref_classify_points(body, pts, tol)
    new = tag.classify_points(body, pts, tol)
    _same(new, ref)
    k = ref[0]
    # the sample really exercises every class and the tie cases
    assert {KIND_VERTEX, KIND_EDGE, KIND_FACE, KIND_UNMATCHED} <= set(k.tolist())
    assert np.any((k == KIND_VERTEX) & (ref[1] == 1)) or np.any((k == KIND_VERTEX) & (ref[1] == 3))


def test_vertex_ties_pick_lowest_index():
    V = np.array([[0.0, 0, 0], [2.0, 0, 0], [0.0, 0, 0], [1.0, 1, 0], [1.0, -1, 0]])
    body = SynthBody(V, [(0, 1)], [(2, 0.0, np.array([-5.0, -5.0]), np.array([5.0, 5.0]))])
    pts = np.array([[1.0, 0, 0], [0.0, 0, 0], [0.5, 0, 0], [1.0, 0.0, 0.0], [3.0, 0, 0], [2.5, 0, 0]])
    for tol in (0.5, 1.0, 1.5, np.nextafter(1.0, 0.0)):
        _same(tag.classify_points(body, pts, tol), ref_classify_points(body, pts, tol))
    k, e, _, d = tag.classify_points(body, pts, 1.0)
    assert k[0] == KIND_VERTEX and e[0] == 1 and d[0] == 1.0  # four vertices at exactly 1.0 -> first
    assert e[1] == 1  # duplicate of vertex 3 -> vertex 1
    assert k[4] == KIND_VERTEX and e[4] == 2 and d[4] == 1.0  # exactly tol


def test_empty_and_degenerate_inputs():
    body = _random_body(np.random.default_rng(1), 10, 5, 3)
    for pts in (np.zeros((0, 3)), np.full((4, 3), np.nan)):
        _same(tag.classify_points(body, pts, 0.5), ref_classify_points(body, pts, 0.5))
    nov = SynthBody(np.zeros((0, 3)), [], [(2, 0.0, np.array([0.0, 0.0]), np.array([1.0, 1.0]))])
    pts = np.array([[0.5, 0.5, 0.01], [2.0, 2.0, 0.0]])
    _same(tag.classify_points(nov, pts, 0.1), ref_classify_points(nov, pts, 0.1))
    for tol in (0.0, -1.0):
        _same(tag.classify_points(body, body.V.copy(), tol), ref_classify_points(body, body.V.copy(), tol))


@pytest.mark.parametrize("seed", range(5))
def test_consistency_bit_identical(seed):
    rng = np.random.default_rng(100 + seed)
    body = _random_body(rng, nv=60, ne=80, nf=25)
    tol = 2.0
    pts = _points_for(rng, body, 2400, tol)
    pts = pts[np.all(np.isfinite(pts), axis=1)]
    base = ref_classify_points(body, pts, tol)
    # triangles: random triples biased to share faces (three distinct faces -> common-edge pass)
    face_nodes = np.flatnonzero(base[0] == KIND_FACE)
    t1 = rng.choice(face_nodes, (4000, 3))
    t2 = rng.integers(len(pts), size=(2000, 3))
    tris = np.concatenate([t1, t2]).astype(np.int64)
    out = []
    for fn in (ref_consistency, tag._consistency):
        k, e, u, d = (x.copy() for x in base)
        w: list = []
        fn(body, pts, k, e, u, d, tris, tol, w, "P")
        out.append(((k, e, u, d), w))
    _same(out[1][0], out[0][0])
    assert out[1][1] == out[0][1]
    assert not np.array_equal(out[0][0][0], base[0])  # the pass did change something


@pytest.mark.parametrize("seed", range(8))
def test_collision_polyline_blocks_identical(seed, monkeypatch):
    rng = np.random.default_rng(200 + seed)
    monkeypatch.setattr(collision, "_ROW_BLOCK", int(rng.integers(1, 9)))
    n, m = int(rng.integers(3, 60)), int(rng.integers(3, 60))
    th = np.sort(rng.uniform(0, 2 * np.pi, n))
    P = np.stack([np.cos(th), np.sin(th)], 1) * rng.uniform(5, 10) + np.round(rng.normal(0, 1, (n, 2)), 1)
    th = np.sort(rng.uniform(0, 2 * np.pi, m))
    Q = np.stack([np.cos(th), np.sin(th)], 1) * rng.uniform(1, 12) + rng.normal(0, 3, 2)
    for skip in (False, True):
        assert collision._seg_intersections(P, P, skip_adjacent=skip) == ref_seg_intersections(P, P, skip_adjacent=skip)
        assert collision._seg_intersections(P, Q, skip_adjacent=skip) == ref_seg_intersections(P, Q, skip_adjacent=skip)
    assert collision._min_dist(P, Q) == ref_min_dist(P, Q)
    Qf = Q + 100.0
    assert collision._min_dist(P, Qf) == ref_min_dist(P, Qf)


# ----------------------------------------------------------------------------- scale: 222,924 x 7,168

N_PTS, N_V = 222_924, 7_168


def _scale_case():
    rng = np.random.default_rng(7)
    # shell-like part: 1000 x 600 plate with ribs; vertices spread over it
    V = np.column_stack([rng.uniform(0, 1000, N_V), rng.uniform(0, 600, N_V), rng.choice([0.0, 5.0, 12.0], N_V)])
    order = np.lexsort((V[:, 1], V[:, 0]))
    edges = [(int(order[i]), int(order[i + 1])) for i in range(0, N_V - 1)]  # 7,167 short-ish edges
    rects = [(2, z, np.array([x, y]), np.array([x + 100.0, y + 100.0])) for z in (0.0, 5.0, 12.0) for x in range(0, 1000, 100) for y in range(0, 600, 100)]
    body = SynthBody(V, edges, rects)
    pts = np.column_stack([rng.uniform(0, 1000, N_PTS), rng.uniform(0, 600, N_PTS), rng.choice([0.0, 5.0, 12.0], N_PTS)])
    k = 4000
    pts[:k] = V[rng.integers(N_V, size=k)] + rng.normal(0, 0.02, (k, 3))
    return body, pts


def test_scale_222k_points_7k_vertices_peak_memory():
    body, pts = _scale_case()
    assert body.V.shape == (N_V, 3) and pts.shape == (N_PTS, 3)
    dense_gib = N_PTS * N_V * 3 * 8 / 2**30
    assert dense_gib > 35.0  # the 0.14.0 vertex step alone: (222924, 7168, 3) float64 = 35.7 GiB
    tracemalloc.start()
    t0 = time.perf_counter()
    kind, ent, uv, dist = tag.classify_points(body, pts, 0.1)
    el = time.perf_counter() - t0
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print(f"\nclassify_points {N_PTS} pts x {N_V} vertices: peak {peak / 2**20:.1f} MiB (tracemalloc), {el:.2f} s")
    assert peak < 2 * 2**30
    assert peak < 64 * (N_PTS + N_V) * 8  # O(n + V): a few dozen float64 words per point
    assert (kind == KIND_VERTEX).sum() > 3000 and (kind == KIND_FACE).sum() > 0.9 * (N_PTS - 4000)
    # vertex hits agree with a brute-force check on a subset (dense on 2,000 points only)
    sub = np.arange(0, N_PTS, N_PTS // 2000)
    ref = ref_classify_points(body, pts[sub], 0.1)
    _same((kind[sub], ent[sub], uv[sub], dist[sub]), ref)
