"""Feature collision pre-check of ``paicad update`` (code ``GEOM_FEATURE_COLLISION``, exit 10).

Runs on the *planned* face moves before the B-rep is rebuilt, so that a sample whose features run
into each other is skipped at update (CAD generation impossible) instead of producing a valid-looking
solid that later fails check with degenerate elements. Only kernel-neutral data is used
(``Topology``, ``eval_edge``) - no OCP.

Checks (each pair / wire is reported only if it was clear in the nominal geometry, so the nominal
model never fails):

* ``BOUNDARY_OVERLAP`` - on every planar face whose wires are affected by the moves, the predicted
  in-plane wires (outer wire, inner wires = holes, rib foot prints, pocket openings) are moved with
  the in-plane motion of their neighbouring faces; two wires that cross or come closer than the
  body tolerance (hole <-> rib, pocket <-> rib, ...) or an inner wire leaving the outer wire
  (hole <-> wall) is a collision;
* ``SELF_INTERSECTION`` - a predicted wire that crosses itself or flips its orientation
  (e.g. a pocket opening narrower than zero);
* ``WALL_PENETRATION`` - two opposite parallel planar faces whose projections overlap pass through
  each other (material thickness or air gap <= tolerance after the move, e.g. pocket floor through
  the bottom face, rib side into the next rib);
* ``RIB_PITCH_MIN`` (rib-gap.md section 4.3, built by the update plan with :func:`rib_pitch_min`) - the gap between
  two neighbouring ribs of a rib row (pitch - half the sample thickness sum) below ``rib_gap.min_gap_mm``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .kernel.base import BodyGeom, FaceMove, Topology

CURVE_SAMPLES = 24
PARALLEL_COS = 0.999


@dataclass
class Collision:
    kind: str  # BOUNDARY_OVERLAP | SELF_INTERSECTION | WALL_PENETRATION | RIB_PITCH_MIN
    face: int  # face on which it was found (WALL_PENETRATION: first face of the pair)
    other: int | None  # second face (WALL_PENETRATION) or None
    features: list[str]
    detail: str

    def as_dict(self) -> dict:
        return {"kind": self.kind, "face": f"F{self.face}", "other": None if self.other is None else f"F{self.other}", "features": self.features, "detail": self.detail}


# ------------------------------------------------------------------ helpers
def _frame(n: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    a = np.eye(3)[int(np.argmin(np.abs(n)))]
    e1 = np.cross(n, a)
    e1 /= np.linalg.norm(e1)
    return e1, np.cross(n, e1)


def _seg_intersections(P: np.ndarray, Q: np.ndarray, skip_adjacent: bool = False) -> bool:
    """Proper crossing between segments of polyline P (closed) and Q (closed)."""
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


def _point_seg_dist(p: np.ndarray, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """dist[n_p, n_s] from points to segments."""
    ab = b - a
    L2 = np.maximum((ab * ab).sum(-1), 1e-300)
    t = np.clip(((p[:, None, :] - a[None]) * ab[None]).sum(-1) / L2[None], 0.0, 1.0)
    foot = a[None] + t[..., None] * ab[None]
    return np.linalg.norm(p[:, None, :] - foot, axis=-1)


def _min_dist(P: np.ndarray, Q: np.ndarray) -> float:
    if _seg_intersections(P, Q):
        return 0.0
    d1 = _point_seg_dist(P, Q, np.roll(Q, -1, axis=0)).min()
    d2 = _point_seg_dist(Q, P, np.roll(P, -1, axis=0)).min()
    return float(min(d1, d2))


def _inside(pt: np.ndarray, poly: np.ndarray) -> bool:
    x, y = float(pt[0]), float(pt[1])
    xs, ys = poly[:, 0], poly[:, 1]
    xn, yn = np.roll(xs, -1), np.roll(ys, -1)
    cond = (ys > y) != (yn > y)
    with np.errstate(divide="ignore", invalid="ignore"):
        xc = xs + (y - ys) * (xn - xs) / (yn - ys)
    return bool(np.count_nonzero(cond & (x < xc)) % 2)


def _area(poly: np.ndarray) -> float:
    x, y = poly[:, 0], poly[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(np.roll(x, -1), y))


# ------------------------------------------------------------------ in-plane motion of a face boundary
class _Motion:
    def __init__(self, topo: Topology, moves: dict[int, FaceMove]):
        self.topo = topo
        self.moves = moves

    def moved(self, fid: int) -> bool:
        m = self.moves.get(fid)
        return m is not None and m.is_effective()

    def constraint(self, g: int, p: np.ndarray, nF: np.ndarray) -> tuple[np.ndarray, float, np.ndarray] | None:
        """(unit in-plane normal m of face g's trace, shift s along m, full in-plane displacement) at point p."""
        mv = self.moves.get(g)
        T = np.zeros(3) if mv is None or mv.translate is None else np.asarray(mv.translate, dtype=float)
        G = self.topo.face(g)
        Tip = T - float(np.dot(T, nF)) * nF
        if G.surface == "PLANE" and G.normal is not None:
            nG = np.asarray(G.normal, dtype=float)
            nip = nG - float(np.dot(nG, nF)) * nF
            L = float(np.linalg.norm(nip))
            if L < 1e-3:
                return None
            m = nip / L
            s = float(np.dot(T, nG)) / L
            return m, s, s * m
        d = Tip.copy()
        m = None
        if G.axis_point is not None and G.axis_dir is not None:
            ax = np.asarray(G.axis_dir, dtype=float)
            r = p - np.asarray(G.axis_point, dtype=float)
            r = r - float(np.dot(r, ax)) * ax
            r = r - float(np.dot(r, nF)) * nF
            rl = float(np.linalg.norm(r))
            if rl > 1e-12:
                m = r / rl
                if mv is not None and mv.radius is not None and G.radius is not None:
                    d = d + (float(mv.radius) - float(G.radius)) * m
        if m is None:
            return None
        return m, float(np.dot(d, m)), d


def _wire_polys(body: BodyGeom, topo: Topology, fid: int, wires: list[tuple[int, ...]], motion: _Motion, e1, e2, nF) -> list[tuple[np.ndarray, np.ndarray, list[int]]]:
    """[(nominal 2D polygon, moved 2D polygon, neighbour faces)] per wire (chained by vertices)."""
    out = []
    for w in wires:
        segs = []
        for e in w:
            ed = topo.edge(e)
            n = 2 if ed.curve == "LINE" else (2 * CURVE_SAMPLES if len(ed.vertices) == 1 else CURVE_SAMPLES)
            t = np.linspace(0.0, 1.0, n)
            pts = np.asarray(body.eval_edge(e, t), dtype=float).reshape(-1, 3)
            others = [g for g in ed.faces if g != fid]
            segs.append([e, pts, others[0] if others else None])
        poly3, nbr, ends = _chain(topo, segs)
        if poly3 is None:
            continue
        disp = np.zeros_like(poly3)
        for k, (p, g, is_end) in enumerate(zip(poly3, nbr, ends)):
            if is_end is not None:  # wire vertex: least-squares of the neighbouring faces' constraints
                rows, rhs, fulls = [], [], []
                for gg in is_end:
                    c = motion.constraint(gg, p, nF) if gg is not None else None
                    if c is not None:
                        rows.append(c[0])
                        rhs.append(c[1])
                        fulls.append(c[2])
                if rows:
                    A = np.array([[float(np.dot(r, e1)), float(np.dot(r, e2))] for r in rows])
                    x, *_ = np.linalg.lstsq(A, np.array(rhs), rcond=1e-6)
                    disp[k] = x[0] * e1 + x[1] * e2
                continue
            if g is None:
                continue
            c = motion.constraint(g, p, nF)
            if c is not None:
                disp[k] = c[2]
        to2 = lambda X: np.stack([X @ e1, X @ e2], axis=1)  # noqa: E731
        out.append((to2(poly3), to2(poly3 + disp), sorted({g for _, _, g in segs if g is not None})))
    return out


def _chain(topo: Topology, segs: list) -> tuple[np.ndarray | None, list, list]:
    """Order edge samples into one closed polyline. Returns (points, neighbour face per point, vertex marks)."""
    if len(segs) == 1:
        e, pts, g = segs[0]
        P = pts[:-1] if np.allclose(pts[0], pts[-1], atol=1e-6) else pts
        ends = [None] * len(P)
        if len(topo.edge(e).vertices) == 2:
            ends[0] = [g]
        return P, [g] * len(P), ends
    V = topo.vertices
    remaining = list(segs)
    e, pts, g = remaining.pop(0)
    vs = topo.edge(e).vertices
    # orient the first edge: its end must be a vertex shared with another edge
    end_v = _nearest_vertex(V, vs, pts[-1])
    pts_all, nbr, ends = list(pts[:-1]), [g] * (len(pts) - 1), [None] * (len(pts) - 1)
    start_v = _nearest_vertex(V, vs, pts[0])
    first_g = g
    prev_g = g
    cur = end_v
    while remaining:
        k = next((i for i, (ee, _, _) in enumerate(remaining) if cur in topo.edge(ee).vertices), None)
        if k is None:
            return None, [], []
        ee, pp, gg = remaining.pop(k)
        vv = topo.edge(ee).vertices
        if _nearest_vertex(V, vv, pp[0]) != cur:
            pp = pp[::-1]
        ends.append([prev_g, gg])
        pts_all.append(pp[0])
        nbr.append(gg)
        for q in pp[1:-1]:
            pts_all.append(q)
            nbr.append(gg)
            ends.append(None)
        cur = _nearest_vertex(V, vv, pp[-1])
        prev_g = gg
    if cur != start_v:
        return None, [], []
    ends[0] = [prev_g, first_g]
    return np.asarray(pts_all), nbr, ends


def _nearest_vertex(V: np.ndarray, vids: tuple[int, ...], p: np.ndarray) -> int:
    return min(vids, key=lambda v: float(np.linalg.norm(V[v - 1] - p)))


# ------------------------------------------------------------------ the checks
def find_collisions(body: BodyGeom, moves: dict[int, FaceMove], owner: dict[int, list[str]], tol: float) -> list[Collision]:
    """Collisions caused by ``moves`` on ``body`` (empty = none). ``owner``: face id -> feature names."""
    topo = body.topology()
    motion = _Motion(topo, moves)
    moved = {f for f in moves if motion.moved(f)}
    if not moved:
        return []
    out: list[Collision] = []

    def names(faces) -> list[str]:
        s: list[str] = []
        for f in faces:
            for n in owner.get(f, []):
                if n not in s:
                    s.append(n)
        return s

    # 1. in-plane wires of affected planar faces
    for F in topo.faces:
        if F.surface != "PLANE" or F.normal is None:
            continue
        wires = [tuple(F.outer_edges)] + [tuple(w) for w in F.inner_wires]
        touched = {g for w in wires for e in w for g in topo.edge(e).faces if g != F.id}
        if not (touched & moved):
            continue
        nF = np.asarray(F.normal, dtype=float)
        e1, e2 = _frame(nF)
        polys = _wire_polys(body, topo, F.id, wires, motion, e1, e2, nF)
        if len(polys) != len(wires):
            continue  # could not chain a wire: leave it to the kernel checks
        for i, (P0, P1, nb) in enumerate(polys):
            a0, a1 = _area(P0), _area(P1)
            if not _seg_intersections(P0, P0, skip_adjacent=True) and (
                _seg_intersections(P1, P1, skip_adjacent=True) or (abs(a0) > 0 and (a1 * a0 <= 0 or abs(a1) <= tol * tol))
            ):
                out.append(Collision("SELF_INTERSECTION", F.id, None, names(nb), f"wire {i} of face F{F.id} crosses itself or collapses"))
        outer0, outer1 = polys[0][0], polys[0][1]
        for i in range(1, len(polys)):
            P0, P1, nb = polys[i]
            d0 = _min_dist(P0, outer0)
            if d0 > tol and _inside(P0[0], outer0):
                d1 = _min_dist(P1, outer1)
                if d1 <= tol or not _inside(P1[0], outer1):
                    out.append(Collision("BOUNDARY_OVERLAP", F.id, None, names(nb + polys[0][2]), f"inner wire {i} of face F{F.id} reaches the outer boundary (clearance {d1:.3g} mm)"))
            for j in range(i + 1, len(polys)):
                Q0, Q1, nq = polys[j]
                d0 = _min_dist(P0, Q0)
                if d0 <= tol or _inside(P0[0], Q0) or _inside(Q0[0], P0):
                    continue
                d1 = _min_dist(P1, Q1)
                if d1 <= tol or _inside(P1[0], Q1) or _inside(Q1[0], P1):
                    out.append(Collision("BOUNDARY_OVERLAP", F.id, None, names(nb + nq), f"inner wires {i} and {j} of face F{F.id} overlap (clearance {d1:.3g} mm)"))
    # 2. opposite parallel planes passing through each other
    planes = [f for f in topo.faces if f.surface == "PLANE" and f.normal is not None]
    for ia, A in enumerate(planes):
        for B in planes[ia + 1 :]:
            if A.id not in moved and B.id not in moved:
                continue
            nA = np.asarray(A.normal, dtype=float)
            if float(np.dot(nA, B.normal)) > -PARALLEL_COS:
                continue
            if not _overlap(A, B, nA, tol):
                continue
            s0 = float(np.dot(B.centroid - A.centroid, nA))
            TA = _tr(moves.get(A.id))
            TB = _tr(moves.get(B.id))
            s1 = s0 + float(np.dot(TB - TA, nA))
            if abs(s0) > tol and (s0 * s1 <= 0 or abs(s1) <= tol):
                kind = "material" if s0 < 0 else "gap"
                out.append(Collision("WALL_PENETRATION", A.id, B.id, names([A.id, B.id]), f"faces F{A.id}/F{B.id}: {kind} {abs(s0):.3g} mm -> {(-s1 if s0 < 0 else s1):.3g} mm"))
    return out


def rib_pitch_min(name: str, face: int, other: int, pitch: float, gap: float, min_gap: float) -> Collision:
    """RIB_PITCH_MIN of pitch ``name``: ``face`` / ``other`` = the facing lateral faces (-a of the outer rib, +a of
    the inner one)."""
    return Collision("RIB_PITCH_MIN", face, other, [name], f"{name}: pitch {pitch:.6g} mm, gap {gap:.6g} mm < min gap {min_gap:g} mm")


def _tr(m: FaceMove | None) -> np.ndarray:
    return np.zeros(3) if m is None or m.translate is None else np.asarray(m.translate, dtype=float)


def _overlap(A, B, n: np.ndarray, tol: float) -> bool:
    """Projections of the two faces' boxes onto A's plane overlap with positive area (> tol each way)."""
    e1, e2 = _frame(n)

    def box(f):
        lo, hi = f.bbox[:3], f.bbox[3:]
        corners = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
        u, v = corners @ e1, corners @ e2
        return u.min(), u.max(), v.min(), v.max()

    a, b = box(A), box(B)
    du = min(a[1], b[1]) - max(a[0], b[0])
    dv = min(a[3], b[3]) - max(a[2], b[2])
    return du > tol and dv > tol and math.isfinite(du) and math.isfinite(dv)


__all__ = ["Collision", "find_collisions", "rib_pitch_min"]
