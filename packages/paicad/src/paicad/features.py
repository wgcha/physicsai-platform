"""Feature recognition, reference-face rule and symmetry groups (contract section 6.2).

Works only through the neutral kernel protocol (``paicad.kernel.base.BodyGeom``).
"""

from __future__ import annotations

import hashlib
import math
import time
from dataclasses import dataclass, field

import numpy as np

from .bodymap import normalize
from .common import rnd, vec
from .kernel.base import BodyGeom, FaceData, Topology

TYPE_ORDER = (
    "THICKNESS",
    "POCKET_DEPTH",
    "POCKET_WIDTH",
    "RIB_THICKNESS",
    "RIB_HEIGHT",
    "HOLE_RADIUS",
    "HOLE_POS_U",
    "HOLE_POS_V",
    "FILLET_RADIUS",
    "RIB_POS_U",  # extract-filter.md EF-5: appended so the other types keep order, names and group ids
    "RIB_POS_V",
)
TYPE_ABBR = {
    "THICKNESS": "THK",
    "POCKET_DEPTH": "POCKET_D",
    "POCKET_WIDTH": "POCKET_W",
    "RIB_THICKNESS": "RIB_T",
    "RIB_HEIGHT": "RIB_H",
    "HOLE_RADIUS": "HOLE_R",
    "HOLE_POS_U": "HOLE_U",
    "HOLE_POS_V": "HOLE_V",
    "FILLET_RADIUS": "FILLET_R",
    "RIB_POS_U": "RIB_U",
    "RIB_POS_V": "RIB_V",
}
MEASURE = {
    "THICKNESS": "face_distance",
    "POCKET_DEPTH": "pocket_depth",
    "POCKET_WIDTH": "pocket_width",
    "RIB_THICKNESS": "face_distance",
    "RIB_HEIGHT": "rib_height",
    "HOLE_RADIUS": "hole_radius",
    "HOLE_POS_U": "hole_center",
    "HOLE_POS_V": "hole_center",
    "FILLET_RADIUS": "fillet_radius",
    "RIB_POS_U": "rib_center",
    "RIB_POS_V": "rib_center",
}
PAIR_TYPES = ("THICKNESS", "POCKET_WIDTH", "RIB_THICKNESS")  # reference-face rule applies
# position parameters: absolute mm range / sweep steps (single definition - update, sweep, view, paramap import it)
POSITION_TYPES = ("HOLE_POS_U", "HOLE_POS_V", "RIB_POS_U", "RIB_POS_V")
HOLE_POS_TYPES = ("HOLE_POS_U", "HOLE_POS_V")
RIB_POS_TYPES = ("RIB_POS_U", "RIB_POS_V")
LEGACY_TYPES = TYPE_ORDER[:9]  # types recognized without extract.filter (RIB_POS only with a filter, EF-5)
FILTER_TOL = 1.0e-9  # extract.filter boundary tolerance (mm / mm^2), values compared before rounding
TIE_TOL = 1.0e-9  # thickness nearest-partner tie window (same as the mutual-nearest rule)
WALL_MIN_MM = 0.5
NAME_MAX = 64


@dataclass
class Feature:
    type: str
    body: str
    nominal: float
    faces: list[int]  # all faces that define the feature (signature faces)
    moving: list[int]
    fixed: list[int]
    pair: tuple[int, int] | None = None
    draft_deg: float = 0.0
    axis: int | None = None  # HOLE_POS_*: global axis index of the coordinate
    obstacle_faces: dict = field(default_factory=dict)  # feasible limiting face -> side
    ref: dict | None = None
    feasible: dict | None = None
    range: dict | None = None
    name: str = ""
    group: str | None = None
    order_key: tuple = ()


# ---------------------------------------------------------------- extract.filter (extract-filter.md sections 4-5)
@dataclass(frozen=True)
class Filter:
    """Feature types to find and conditions. ``active=False`` = no ``extract.filter`` (legacy types, no conditions,
    legacy algorithms - output byte-identical to 0.10.1)."""

    active: bool
    types: frozenset
    thickness: tuple = (None, None)  # (min, max) mm
    height: tuple = (None, None)
    face_area_min: float | None = None
    position_min_size: float | None = None
    hole_radius_min: float | None = None
    fillet_radius_min: float | None = None

    @classmethod
    def from_opts(cls, opts: dict) -> "Filter":
        f = (opts.get("extract") or {}).get("filter")
        if f is None:
            return cls(False, frozenset(LEGACY_TYPES))

        def rng(k):
            r = f.get(k) or {}
            return (r.get("min"), r.get("max"))

        return cls(
            True,
            frozenset(f["types"]),
            rng("thickness_mm"),
            rng("height_mm"),
            f.get("face_area_min_mm2"),
            f.get("position_min_size_mm"),
            f.get("hole_radius_min_mm"),
            f.get("fillet_radius_min_mm"),
        )

    def sel(self, *types: str) -> bool:
        return any(t in self.types for t in types)

    @staticmethod
    def at_least(x: float, lo: float | None) -> bool:
        return lo is None or x >= lo - FILTER_TOL

    @staticmethod
    def within(x: float, r: tuple) -> bool:
        lo, hi = r
        return (lo is None or x >= lo - FILTER_TOL) and (hi is None or x <= hi + FILTER_TOL)

    def thickness_max(self) -> float | None:
        return None if self.thickness[1] is None else self.thickness[1] + FILTER_TOL


class _Stats:
    """Per-body counters of ``extract_stats.json`` (section 7.1). Unselected types only carry ``selected: false``."""

    def __init__(self, flt: Filter):
        self.types: dict[str, dict] = {}
        for t in TYPE_ORDER:
            self.types[t] = {"selected": True, "candidates": 0, "kept": 0, "excluded": {}} if flt.sel(t) else {"selected": False}
        if flt.sel("THICKNESS"):
            self.types["THICKNESS"] ={"selected": True, "initiators": 0, "pair_tests": 0, "kept": 0, "excluded": {}}
        for t in ("RIB_THICKNESS", "POCKET_WIDTH"):
            if flt.sel(t):
                self.types[t] = {"selected": True, "candidates": 0, "pair_tests": 0, "kept": 0, "excluded": {}}
        self.rib_rejects: dict[str, int] = {}

    def add(self, t: str, key: str, n: int = 1) -> None:
        self.types[t][key] += n

    def excl(self, t: str, why: str, n: int = 1) -> None:
        e = self.types[t]["excluded"]
        e[why] = e.get(why, 0) + n

    def elapsed(self, types, sec: float) -> None:
        for t in types:
            if self.types[t]["selected"]:
                self.types[t]["elapsed_s"] = sec

    def as_dict(self) -> dict:
        return {"types": self.types, "rib_rejects": dict(sorted(self.rib_rejects.items()))}


# ---------------------------------------------------------------- geometry helpers
def _unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n > 0 else v


def _angle_deg(a: np.ndarray, b: np.ndarray) -> float:
    return math.degrees(math.acos(max(-1.0, min(1.0, float(np.dot(_unit(a), _unit(b)))))))


def _plane_distance(fa: FaceData, fb: FaceData) -> float:
    """Mean of centroid-to-other-plane distances (works with small draft)."""
    d1 = abs(float(np.dot(fa.centroid - fb.centroid, fb.normal)))
    d2 = abs(float(np.dot(fb.centroid - fa.centroid, fa.normal)))
    return 0.5 * (d1 + d2)


def _overlap(body: BodyGeom, fa: FaceData, fb: FaceData, grid: int) -> tuple[float, np.ndarray, np.ndarray]:
    """Fraction of fa samples whose projection along fb's normal lies on fb. Returns (ratio, pts_a, feet_on_b)."""
    pts = body.sample_face(fa.id, grid)
    if len(pts) == 0:
        return 0.0, pts, pts
    n = fb.normal
    feet = pts - np.outer((pts - fb.centroid) @ n, n)
    _, _, inside, _ = body.project_to_face(fb.id, feet)
    return float(inside.mean()), pts[inside], feet[inside]


_SCAN_CHUNK = 12  # points per kernel call in the early-exit scan (per-point answers do not depend on it)


def _overlap_at_least(
    body: BodyGeom, fa: FaceData, fb: FaceData, grid: int, ratio_min: float, margin: float | None, full: bool
) -> tuple[bool, np.ndarray, np.ndarray]:
    """``_overlap(...)[0] >= ratio_min`` with the same per-point answers, but cheaper.

    Feet farther than ``margin`` outside fb's bbox are 'not on fb' without asking the kernel (valid only for an
    unclamped projection: a foot classified on fb then lies in fb.bbox up to the projection residual, far below
    ``margin``; ``margin=None`` asks the kernel for every point). Points are classified in small chunks
    and the scan stops once the comparison is decided; ``full=True`` keeps scanning a passing face so the
    returned (pts_a, feet_on_b) equal ``_overlap``'s."""
    pts = body.sample_face(fa.id, grid)
    m = len(pts)
    if m == 0:
        return 0.0 >= ratio_min, pts, pts
    n = fb.normal
    feet = pts - np.outer((pts - fb.centroid) @ n, n)
    if margin is None:
        near = np.arange(m)
    else:
        near = np.nonzero(np.all((feet >= fb.bbox[:3] - margin) & (feet <= fb.bbox[3:] + margin), axis=1))[0]
    inside = np.zeros(m, dtype=bool)
    k_in, left = 0, len(near)
    for c0 in range(0, len(near), _SCAN_CHUNK):
        if (k_in + left) / m < ratio_min:
            return False, pts[:0], feet[:0]  # cannot reach ratio_min any more
        if not full and k_in / m >= ratio_min:
            return True, pts[:0], feet[:0]
        idx = near[c0 : c0 + _SCAN_CHUNK]
        _, _, ins, _ = body.project_to_face(fb.id, feet[idx])
        inside[idx] = ins
        left -= len(idx)
        k_in += int(np.count_nonzero(ins))
    return k_in / m >= ratio_min, pts[inside], feet[inside]


def _bbox_overlap_2d(a: np.ndarray, b: np.ndarray, skip_axis: int | None, margin: float = 1e-6) -> bool:
    for k in range(3):
        if k == skip_axis:
            continue
        if min(a[3 + k], b[3 + k]) - max(a[k], b[k]) <= margin:
            return False
    return True


def _dominant_axis(n: np.ndarray, cos_tol: float) -> int | None:
    k = int(np.argmax(np.abs(n)))
    return k if abs(float(n[k])) >= cos_tol else None


def _face_region_overlap(fa: FaceData, fb: FaceData, normal: np.ndarray) -> bool:
    """bbox overlap of two faces in the plane perpendicular to ``normal`` (axis-aligned approximation)."""
    ax = _dominant_axis(normal, math.cos(math.radians(10)))
    return _bbox_overlap_2d(fa.bbox, fb.bbox, ax)


# ---------------------------------------------------------------- recognition
class _Ctx:
    def __init__(self, body: BodyGeom, opts: dict):
        self.body = body
        self.topo: Topology = body.topology()
        self.summary = body.summary()
        ex = opts["extract"]
        self.draft = float(ex["draft_max_deg"])
        self.cos_par = math.cos(math.radians(self.draft))
        self.sin_perp = math.sin(math.radians(self.draft))
        self.overlap_min = float(ex["overlap_min"])
        self.grid = int(ex["sample_grid"])
        self.planes = [f for f in self.topo.faces if f.surface == "PLANE"]
        self.edge_faces = {e.id: e.faces for e in self.topo.edges}
        self.edge_conv = {e.id: e.convexity for e in self.topo.edges}
        bb = self.summary.bbox
        self.bbox_margin = 1e-2 + 1e-5 * float(np.linalg.norm(bb[3:] - bb[:3]))  # pre-filter slack (mm)
        self.stats = {"overlap_checks": 0, "overlap_prefiltered": 0}

    def neighbours(self, f: FaceData, edges) -> dict[int, list[int]]:
        """edge id -> other face ids across that edge."""
        out = {}
        for e in edges:
            out[e] = [g for g in self.edge_faces[e] if g != f.id]
        return out

    def face(self, fid: int) -> FaceData:
        return self.topo.face(fid)


def _find_protrusions(ctx: _Ctx, sign: int, rejects: dict | None = None) -> list[tuple[int, list[int], int, float]]:
    """sign=+1: ribs (convex top, concave base); sign=-1: pockets (concave floor, convex entry).

    Returns [(cap face, lateral faces, base/entry face, height/depth)]. ``rejects``: first reason per rejected cap
    candidate plane is counted there (``extract_stats.json`` ``rib_rejects``, section 7.1).
    """
    want_cap = "CONVEX" if sign > 0 else "CONCAVE"
    want_base = "CONCAVE" if sign > 0 else "CONVEX"
    found = []

    def reject(why: str) -> None:
        if rejects is not None:
            rejects[why] = rejects.get(why, 0) + 1

    for cap in ctx.planes:
        if cap.inner_wires or not cap.outer_edges:
            reject("cap_inner_wire")
            continue
        if any(ctx.edge_conv[e] != want_cap for e in cap.outer_edges):
            reject("cap_not_convex")
            continue
        lat_ids = []
        ok = True
        for e, others in ctx.neighbours(cap, cap.outer_edges).items():
            if len(others) != 1:
                ok = False
                break
            if others[0] not in lat_ids:
                lat_ids.append(others[0])
        if not ok or len(lat_ids) < 3:
            reject("lateral_count")
            continue
        lats = [ctx.face(g) for g in lat_ids]
        if any(l.surface != "PLANE" for l in lats):
            reject("lateral_not_plane")
            continue
        if any(abs(float(np.dot(l.normal, cap.normal))) > ctx.sin_perp for l in lats):
            reject("lateral_draft")
            continue
        base_id = None
        for l in lats:
            for e, others in ctx.neighbours(l, l.edges).items():
                for g in others:
                    if g == cap.id:
                        continue
                    if g in lat_ids:
                        if ctx.edge_conv[e] != want_cap:
                            ok = False
                        continue
                    if ctx.edge_conv[e] != want_base:
                        ok = False
                    elif base_id is None:
                        base_id = g
                    elif base_id != g:
                        ok = False
        if not ok or base_id is None:
            reject("base_mismatch")
            continue
        base = ctx.face(base_id)
        if base.surface != "PLANE" or float(np.dot(base.normal, cap.normal)) < ctx.cos_par:
            reject("base_mismatch")
            continue
        h = float(np.dot(cap.centroid - base.centroid, cap.normal)) * sign
        if h <= 0:
            reject("height_not_positive")
            continue
        found.append((cap.id, sorted(lat_ids), base_id, h))
    return found


_PAIR_BLOCK = 512  # rows per vectorized pre-filter block (memory ~ block x n doubles)


def _pair_candidates(faces: list[FaceData], cos_par: float, material: bool):
    """(i, j>i) index pairs in row-major order that may pass the exact tests of ``_pairs_across``.

    Conservative vectorized pre-filter (margins wider than float rounding): every pair it drops would fail
    the exact antiparallel or side test, so the exact loop sees the same survivors in the same order."""
    n = len(faces)
    if n < 2:
        return
    N = np.array([f.normal for f in faces], dtype=float)
    C = np.array([f.centroid for f in faces], dtype=float)
    tol_dot = 1e-9
    tol_s = 1e-9 * (1.0 + float(np.abs(C).max()))  # |s| rounding bound is far below this
    nc = np.einsum("ij,ij->i", N, C)
    for i0 in range(0, n, _PAIR_BLOCK):
        i1 = min(n, i0 + _PAIR_BLOCK)
        Nb = N[i0:i1]
        dot = -(Nb @ N.T)  # dot(a.n, -b.n)
        s_a = Nb @ C.T - nc[i0:i1, None]  # a.n . (b.c - a.c)
        s_b = (N @ C[i0:i1].T).T - nc[None, :]  # b.n . (a.c - b.c)
        m = dot >= cos_par - tol_dot
        if material:
            m &= (s_a < tol_s) & (s_b < tol_s)
        else:
            m &= (s_a > -tol_s) & (s_b > -tol_s)
        m &= np.arange(n)[None, :] > np.arange(i0, i1)[:, None]
        ii, jj = np.nonzero(m)
        for i, j in zip((ii + i0).tolist(), jj.tolist()):
            yield i, j


def _pairs_across(ctx: _Ctx, faces: list[FaceData], material: bool) -> list[tuple[FaceData, FaceData, float, float]]:
    """Antiparallel plane pairs. material=True: material between (faces look away from each other)."""
    return [(faces[i], faces[j], d, dr) for i, j, d, dr in _pairs_across_idx(ctx, faces, material)]


def _pairs_across_idx(ctx: _Ctx, faces: list[FaceData], material: bool) -> list[tuple[int, int, float, float]]:
    """``_pairs_across`` as (i, j > i, d, draft) index tuples, same order."""
    out = []
    for i, j in _pair_candidates(faces, ctx.cos_par, material):
        a, b = faces[i], faces[j]
        if float(np.dot(a.normal, -b.normal)) < ctx.cos_par:
            continue
        ab = b.centroid - a.centroid
        s_a = float(np.dot(a.normal, ab))
        s_b = float(np.dot(b.normal, -ab))
        if material and not (s_a < 0 and s_b < 0):
            continue
        if not material and not (s_a > 0 and s_b > 0):
            continue
        d = _plane_distance(a, b)
        if d <= 1e-9:
            continue
        draft = 0.5 * (180.0 - _angle_deg(a.normal, b.normal))
        out.append((i, j, d, draft))
    return out


def _projection_misses(fa: FaceData, fb: FaceData, margin: float) -> bool:
    """True if no point of fa's bbox, projected along fb.normal onto fb's plane, can land in fb's bbox.

    fa samples lie in fa.bbox, their feet in the hull of the projected bbox corners, and (unclamped projection
    only, see ``_bbox_margin_for``) a foot classified on fb lies (to the projection residual, << margin) in
    fb.bbox - so True means ``_overlap`` ratio 0."""
    lo, hi = fa.bbox[:3], fa.bbox[3:]
    corners = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
    n = fb.normal
    feet = corners - np.outer((corners - fb.centroid) @ n, n)
    flo, fhi = feet.min(axis=0), feet.max(axis=0)
    return bool(np.any(flo > fb.bbox[3:] + margin) or np.any(fhi < fb.bbox[:3] - margin))


def _bbox_margin_for(ctx: _Ctx, target: FaceData) -> float | None:
    """bbox shortcut slack for projections onto ``target``; None when the kernel may clamp far points onto the
    face boundary (then only the kernel can answer, see ``face_projection_unclamped``)."""
    fn = getattr(ctx.body, "face_projection_unclamped", None)
    return ctx.bbox_margin if fn is not None and fn(target.id) else None


def _overlap_ok(ctx: _Ctx, a: FaceData, b: FaceData, check_material: bool) -> bool:
    ctx.stats["overlap_checks"] += 1
    mb = _bbox_margin_for(ctx, b)
    if ctx.overlap_min > 0 and mb is not None and _projection_misses(a, b, mb):
        ctx.stats["overlap_prefiltered"] += 1
        return False  # r1 would be 0
    ok1, pa, fb = _overlap_at_least(ctx.body, a, b, ctx.grid, ctx.overlap_min, mb, full=check_material)
    if not ok1:
        return False
    ma = _bbox_margin_for(ctx, a)
    if ctx.overlap_min > 0 and ma is not None and _projection_misses(b, a, ma):
        ctx.stats["overlap_prefiltered"] += 1
        return False  # r2 would be 0
    ok2, _, _ = _overlap_at_least(ctx.body, b, a, ctx.grid, ctx.overlap_min, ma, full=False)
    if not ok2:
        return False
    if check_material and len(pa):
        idx = np.linspace(0, len(pa) - 1, min(len(pa), 16)).astype(int)
        mid = 0.5 * (pa[idx] + fb[idx])
        if not _mostly_inside(ctx.body, mid):
            return False
    return True


def _mostly_inside(body: BodyGeom, pts: np.ndarray) -> bool:
    """``points_inside(pts).mean() >= 0.5``, classifying one point at a time and stopping once decided."""
    m = len(pts)
    need = math.ceil(0.5 * m)  # inside count k passes iff k / m >= 0.5
    k_in = k_out = 0
    for q in pts:
        if bool(body.points_inside(q[None, :])[0]):
            k_in += 1
            if k_in >= need:
                return True
        else:
            k_out += 1
            if m - k_out < need:
                return False
    return k_in >= need


def _quiet(_msg: str) -> None:
    pass


def _thickness_lazy(ctx: _Ctx, free: list[FaceData], flt: Filter, st: _Stats) -> list[tuple[FaceData, FaceData, float, float]]:
    """THICKNESS pairs with a filter (section 5.2): same mutual-nearest rule as the full scan, but each initiator
    face (area >= face_area_min) walks its cheap-test partners in ascending distance (ties: enumeration order) and
    asks the overlap test only until the first pass (or ``d > thickness max``). Overlap answers are cached per pair
    (lower index first, like the full scan). Ties: the full scan keeps the first partner (ascending index) within
    ``TIE_TOL`` of the nearest one, so after the first pass the lower-index partners within the window are tried too.
    Returns pairs in the full scan's (i, j) order."""
    n = len(free)
    adj: list[list[tuple[float, int, int, int, float]]] = [[] for _ in range(n)]
    for i, j, d, dr in _pairs_across_idx(ctx, free, material=True):
        adj[i].append((d, j, i, j, dr))
        adj[j].append((d, i, i, j, dr))
    for lst in adj:
        lst.sort(key=lambda x: (x[0], x[1]))
    cache: dict[tuple[int, int], bool] = {}
    ts = st.types["THICKNESS"]

    def passes(i: int, j: int) -> bool:
        key = (i, j)
        if key not in cache:
            ts["pair_tests"] += 1
            cache[key] = _overlap_ok(ctx, free[i], free[j], check_material=True)
        return cache[key]

    dmax = flt.thickness_max()
    memo: dict[int, tuple | None] = {}

    def nearest(p: int) -> tuple | None:
        """(partner, d, i, j, draft) of the mutual-nearest rule for face p, None = no partner within dmax."""
        if p in memo:
            return memo[p]
        lst = adj[p]
        res = None
        for k, (d, q, i, j, dr) in enumerate(lst):
            if dmax is not None and d > dmax:
                break
            if not passes(i, j):
                continue
            res = (q, d, i, j, dr)
            for d2, q2, i2, j2, dr2 in lst[k + 1 :]:
                if d2 > d + TIE_TOL:
                    break
                if q2 < res[0] and passes(i2, j2):
                    res = (q2, d2, i2, j2, dr2)
            break
        memo[p] = res
        return res

    found: dict[tuple[int, int], tuple[float, float]] = {}
    amin = flt.face_area_min
    for p in range(n):
        if not Filter.at_least(free[p].area, amin):
            st.excl("THICKNESS", "face_area")
            continue
        ts["initiators"] += 1
        r = nearest(p)
        if r is None:
            st.excl("THICKNESS", "thickness_range" if dmax is not None and adj[p] else "no_partner")
            continue
        q, d, i, j, dr = r
        if (i, j) in found:
            continue
        if not Filter.within(d, flt.thickness):
            st.excl("THICKNESS", "thickness_range")
            continue
        if not Filter.at_least(free[q].area, amin):
            st.excl("THICKNESS", "face_area")
            continue
        r2 = nearest(q)
        if r2 is None or r2[0] != p:
            st.excl("THICKNESS", "not_mutual")
            continue
        found[(i, j)] = (d, dr)
    return [(free[i], free[j], d, dr) for (i, j), (d, dr) in sorted(found.items())]


def _rib_pos(ctx: _Ctx, name: str, cap: int, lats: list[int], base: int, flt: Filter, st: _Stats, feats: list[Feature]) -> None:
    """RIB_POS_U/V of one recognized rib (section 3.2): base normal within 1 deg of a global axis, per in-plane axis
    exactly one lateral face looking +a and one looking -a (within the draft angle)."""
    want = [t for t in RIB_POS_TYPES if flt.sel(t)]
    if not want:
        return
    B = ctx.face(base)
    k = _dominant_axis(np.asarray(B.normal, dtype=float), math.cos(math.radians(1.0)))
    if k is None:
        for t in want:
            st.add(t, "candidates")
            st.excl(t, "base_axis")
        return
    others = [a for a in range(3) if a != k]
    C = ctx.face(cap)
    ext = C.bbox[3:] - C.bbox[:3]
    size = float(min(ext[others[0]], ext[others[1]]))
    bb = ctx.summary.bbox
    L = [ctx.face(g) for g in lats]
    for t, a in zip(RIB_POS_TYPES, others):
        if t not in want:
            continue
        st.add(t, "candidates")
        plus = [f for f in L if float(f.normal[a]) >= ctx.cos_par]
        minus = [f for f in L if -float(f.normal[a]) >= ctx.cos_par]
        if len(plus) != 1 or len(minus) != 1:
            st.excl(t, "shape")
            continue
        if not Filter.at_least(size, flt.position_min_size):
            st.excl(t, "position_min_size")
            continue
        nom = 0.5 * (float(plus[0].centroid[a]) + float(minus[0].centroid[a])) - float(bb[a])
        feats.append(Feature(t, name, nom, [cap, *lats, base], [cap, *lats], [base], axis=a))


def rib_sides(topo: Topology, faces: list[int], axis: int) -> tuple[int, int] | None:
    """(lateral face looking -axis, lateral face looking +axis) among a RIB_POS feature's faces (the faces looking
    most along -axis / +axis; None when either side is missing)."""
    best_m = best_p = None
    for g in faces:
        f = topo.face(g)
        if f.surface != "PLANE" or f.normal is None:
            continue
        c = float(f.normal[axis])
        if c > 0.5 and (best_p is None or c > best_p[0]):
            best_p = (c, g)
        if c < -0.5 and (best_m is None or c < best_m[0]):
            best_m = (c, g)
    if best_m is None or best_p is None:
        return None
    return best_m[1], best_p[1]


def recognize_body(body: BodyGeom, opts: dict, log=None, timing: dict | None = None, stats: dict | None = None, progress=None) -> list[Feature]:
    """``log(msg)``: optional progress lines (stderr in extract); ``timing``: filled with stage seconds/counts;
    ``stats``: filled with the ``extract_stats.json`` body entry (section 7.1); ``progress(msg)``: one line per
    recognition stage (stdout PROGRESS in extract). ``opts["extract"]["filter"]`` (extract-filter.md) selects the
    types and conditions; the excluded candidates are dropped before the expensive steps (section 5.2)."""
    log = log or _quiet
    progress = progress or _quiet
    timing = {} if timing is None else timing
    flt = Filter.from_opts(opts)
    st = _Stats(flt)
    t0 = time.perf_counter()
    ctx = _Ctx(body, opts)
    t1 = time.perf_counter()
    timing["topology_s"] = t1 - t0
    log(f"topology: {len(ctx.topo.faces)} faces, {len(ctx.topo.edges)} edges {t1 - t0:.1f}s")
    name = body.name or ""
    feats: list[Feature] = []
    claimed: set[int] = set()
    cos1 = math.cos(math.radians(1.0))

    def kept(t: str, ft: Feature) -> None:
        feats.append(ft)
        st.add(t, "kept")

    # holes and fillets (revolved faces)
    sel_hr, sel_hp, sel_fr = flt.sel("HOLE_RADIUS"), flt.sel(*HOLE_POS_TYPES), flt.sel("FILLET_RADIUS")
    if sel_hr or sel_hp or sel_fr:
        for f in ctx.topo.faces:
            if f.surface != "CYLINDER" or f.span_deg is None:
                continue
            if f.span_deg >= 359.9 and f.concave:
                # through: every non-seam boundary edge borders a plane perpendicular to the axis
                caps = []
                for e in f.edges:
                    if ctx.edge_conv[e] == "SEAM":
                        continue
                    for g in ctx.edge_faces[e]:
                        if g != f.id:
                            caps.append(ctx.face(g))
                if len(caps) < 2 or any(c.surface != "PLANE" or abs(float(np.dot(c.normal, f.axis_dir))) < ctx.cos_par for c in caps):
                    continue
                if max(float(np.dot(c.normal, f.axis_dir)) for c in caps) < ctx.cos_par or min(float(np.dot(c.normal, f.axis_dir)) for c in caps) > -ctx.cos_par:
                    continue  # entry and exit must face opposite ways
                claimed.add(f.id)
                if sel_hr:
                    st.add("HOLE_RADIUS", "candidates")
                    if Filter.at_least(f.radius, flt.hole_radius_min):
                        kept("HOLE_RADIUS", Feature("HOLE_RADIUS", name, f.radius, [f.id], [f.id], []))
                    else:
                        st.excl("HOLE_RADIUS", "hole_radius_min")
                k = _dominant_axis(f.axis_dir, cos1)
                if k is not None and sel_hp:
                    bb = ctx.summary.bbox
                    others = [a for a in range(3) if a != k]
                    for t, a in zip(HOLE_POS_TYPES, others):
                        if not flt.sel(t):
                            continue
                        st.add(t, "candidates")
                        if Filter.at_least(2.0 * f.radius, flt.position_min_size):
                            kept(t, Feature(t, name, float(f.axis_point[a] - bb[a]), [f.id], [f.id], [], axis=a))
                        else:
                            st.excl(t, "position_min_size")
            elif f.span_deg < 180.0 - 1e-6:
                smooth = sum(1 for e in f.edges if ctx.edge_conv[e] == "SMOOTH")
                if smooth >= 2:
                    claimed.add(f.id)
                    if sel_fr:
                        st.add("FILLET_RADIUS", "candidates")
                        if Filter.at_least(f.radius, flt.fillet_radius_min):
                            kept("FILLET_RADIUS", Feature("FILLET_RADIUS", name, f.radius, [f.id], [f.id], []))
                        else:
                            st.excl("FILLET_RADIUS", "fillet_radius_min")
        if sel_fr:
            for f in ctx.topo.faces:
                if f.surface == "TORUS" and f.id not in claimed:
                    smooth = sum(1 for e in f.edges if ctx.edge_conv[e] == "SMOOTH")
                    if smooth >= 2:
                        claimed.add(f.id)
                        st.add("FILLET_RADIUS", "candidates")
                        if Filter.at_least(f.minor_radius, flt.fillet_radius_min):
                            kept("FILLET_RADIUS", Feature("FILLET_RADIUS", name, f.minor_radius, [f.id], [f.id], []))
                        else:
                            st.excl("FILLET_RADIUS", "fillet_radius_min")
        n_rev = sum(1 for ft in feats)
        progress(f"holes/fillets: {n_rev} kept")
    t2 = time.perf_counter()
    timing["revolved_s"] = t2 - t1
    st.elapsed(("HOLE_RADIUS", "HOLE_POS_U", "HOLE_POS_V", "FILLET_RADIUS"), t2 - t1)

    # ribs (always recognized when a type depends on them: rib faces are not thickness candidates, EF-INV)
    n_ribs = n_pockets = 0
    if flt.sel("THICKNESS", "RIB_THICKNESS", "RIB_HEIGHT", *RIB_POS_TYPES):
        for cap, lats, base, h in _find_protrusions(ctx, +1, st.rib_rejects):
            n_ribs += 1
            claimed.update([cap, *lats])
            if flt.sel("RIB_HEIGHT"):
                st.add("RIB_HEIGHT", "candidates")
                if Filter.within(h, flt.height):
                    kept("RIB_HEIGHT", Feature("RIB_HEIGHT", name, h, [cap, base], [cap], [base], draft_deg=0.0))
                else:
                    st.excl("RIB_HEIGHT", "height_range")
            if flt.sel("RIB_THICKNESS"):
                for a, b, d, dr in _pairs_across(ctx, [ctx.face(g) for g in lats], material=True):
                    st.add("RIB_THICKNESS", "candidates")
                    if not d < h:
                        st.excl("RIB_THICKNESS", "not_thinner_than_height")
                        continue
                    if not Filter.within(d, flt.thickness):
                        st.excl("RIB_THICKNESS", "thickness_range")
                        continue
                    if not (Filter.at_least(a.area, flt.face_area_min) and Filter.at_least(b.area, flt.face_area_min)):
                        st.excl("RIB_THICKNESS", "face_area")
                        continue
                    st.add("RIB_THICKNESS", "pair_tests")
                    if _overlap_ok(ctx, a, b, check_material=True):
                        kept("RIB_THICKNESS", Feature("RIB_THICKNESS", name, d, [a.id, b.id], [], [], pair=(a.id, b.id), draft_deg=dr))
                    else:
                        st.excl("RIB_THICKNESS", "no_overlap")
            if flt.sel(*RIB_POS_TYPES):
                n0 = len(feats)
                _rib_pos(ctx, name, cap, lats, base, flt, st, feats)
                for ft in feats[n0:]:
                    st.add(ft.type, "kept")
        rt = st.types["RIB_THICKNESS"]
        progress(f"ribs: {n_ribs} ribs" + (f", rib thickness: {rt['pair_tests']} tests, {rt['kept']} kept" if rt["selected"] else ""))
    t2b = time.perf_counter()
    st.elapsed(("RIB_HEIGHT", "RIB_THICKNESS", "RIB_POS_U", "RIB_POS_V"), t2b - t2)

    # pockets
    if flt.sel("THICKNESS", "POCKET_DEPTH", "POCKET_WIDTH"):
        for floor, walls, entry, depth in _find_protrusions(ctx, -1):
            n_pockets += 1
            claimed.update([floor, *walls])
            if flt.sel("POCKET_DEPTH"):
                st.add("POCKET_DEPTH", "candidates")
                if Filter.within(depth, flt.height):
                    kept("POCKET_DEPTH", Feature("POCKET_DEPTH", name, depth, [floor, entry], [floor], [entry]))
                else:
                    st.excl("POCKET_DEPTH", "height_range")
            if flt.sel("POCKET_WIDTH"):
                for a, b, d, dr in _pairs_across(ctx, [ctx.face(g) for g in walls], material=False):
                    st.add("POCKET_WIDTH", "candidates")
                    if not Filter.within(d, flt.thickness):
                        st.excl("POCKET_WIDTH", "thickness_range")
                        continue
                    if not (Filter.at_least(a.area, flt.face_area_min) and Filter.at_least(b.area, flt.face_area_min)):
                        st.excl("POCKET_WIDTH", "face_area")
                        continue
                    st.add("POCKET_WIDTH", "pair_tests")
                    if _overlap_ok(ctx, a, b, check_material=False):
                        kept("POCKET_WIDTH", Feature("POCKET_WIDTH", name, d, [a.id, b.id], [], [], pair=(a.id, b.id), draft_deg=dr))
                    else:
                        st.excl("POCKET_WIDTH", "no_overlap")
        pw = st.types["POCKET_WIDTH"]
        progress(f"pockets: {n_pockets} pockets" + (f", pocket width: {pw['pair_tests']} tests, {pw['kept']} kept" if pw["selected"] else ""))

    t3 = time.perf_counter()
    st.elapsed(("POCKET_DEPTH", "POCKET_WIDTH"), t3 - t2b)
    timing["ribs_pockets_s"] = t3 - t2
    log(f"holes/fillets {t2 - t1:.1f}s, ribs/pockets {t3 - t2:.1f}s")

    # thickness: remaining planes, mutual nearest antiparallel pair with material between
    if flt.sel("THICKNESS"):
        free = [f for f in ctx.planes if f.id not in claimed]
        ts = st.types["THICKNESS"]
        if flt.active:
            t4 = t3
            timing["thickness_free_planes"] = len(free)
            log(f"thickness (filtered): free planes {len(free)}")
            mutual = _thickness_lazy(ctx, free, flt, st)
            t5 = time.perf_counter()
        else:
            pairs = _pairs_across(ctx, free, material=True)
            t4 = time.perf_counter()
            timing["thickness_free_planes"] = len(free)
            timing["thickness_pairs"] = len(pairs)
            timing["thickness_pairs_s"] = t4 - t3
            log(f"thickness candidate pairs: {len(pairs)} (free planes {len(free)}) {t4 - t3:.1f}s")
            cands = []
            step = max(1, len(pairs) // 10)
            last = t4
            for k, (a, b, d, dr) in enumerate(pairs, 1):
                if _overlap_ok(ctx, a, b, check_material=True):
                    cands.append((a, b, d, dr))
                now = time.perf_counter()
                if k == len(pairs) or (k % step == 0 and now - last >= 1.0):
                    log(f"thickness pairs checked {k}/{len(pairs)} {now - t4:.1f}s")
                    last = now
            t5 = time.perf_counter()
            best: dict[int, tuple[float, int]] = {}
            for a, b, d, _ in cands:
                for x, y in ((a.id, b.id), (b.id, a.id)):
                    if x not in best or d < best[x][0] - 1e-9:
                        best[x] = (d, y)
            mutual = [(a, b, d, dr) for a, b, d, dr in cands if best.get(a.id, (0, -1))[1] == b.id and best.get(b.id, (0, -1))[1] == a.id]
            ts["initiators"] = len(free)
            ts["pair_tests"] = len(pairs)
            if len(pairs) - len(cands):
                st.excl("THICKNESS", "no_overlap", len(pairs) - len(cands))
            if len(cands) - len(mutual):
                st.excl("THICKNESS", "not_mutual", len(cands) - len(mutual))
        timing["thickness_overlap_s"] = t5 - t4
        for a, b, d, dr in mutual:
            kept("THICKNESS", Feature("THICKNESS", name, d, [a.id, b.id], [], [], pair=(a.id, b.id), draft_deg=dr))
        st.elapsed(("THICKNESS",), time.perf_counter() - t3)
        progress(f"thickness: {ts['pair_tests']} tests, {ts['kept']} kept")
    for ft in feats:
        ft.nominal = rnd(ft.nominal)
        ft.draft_deg = rnd(ft.draft_deg, 4)
    timing["overlap_checks"] = ctx.stats["overlap_checks"]
    timing["overlap_prefiltered"] = ctx.stats["overlap_prefiltered"]
    timing["features"] = len(feats)
    timing["recognize_s"] = time.perf_counter() - t0
    if stats is not None:
        stats.update(faces=len(ctx.topo.faces), planes=len(ctx.planes), **st.as_dict())
    return feats


# ---------------------------------------------------------------- reference-face rule
def choose_ref(
    fa: FaceData,
    fb: FaceData,
    *,
    body_center: np.ndarray,
    mode: str = "contact_fixed",
    contacts: set[int] | None = None,
    override_fixed: int | None = None,
) -> dict:
    """Pick (moving, fixed) for a pair feature (section 6.2 rules 1-3, larger_area_fixed, overrides).

    ``contacts`` = contact face ids of this body from tag.json; None = no contact info (provisional).
    Returns {moving, fixed, rule, locked, provisional, reason, warning}.
    """

    def by_area(x: FaceData, y: FaceData) -> tuple[FaceData, FaceData]:
        """(fixed, moving): larger area fixed; ties -> lower face id fixed."""
        if abs(x.area - y.area) <= 1e-6 * max(x.area, y.area):
            return (x, y) if x.id < y.id else (y, x)
        return (x, y) if x.area > y.area else (y, x)

    if override_fixed is not None and override_fixed in (fa.id, fb.id):
        fixed = fa if fa.id == override_fixed else fb
        moving = fb if fixed is fa else fa
        return dict(moving=moving.id, fixed=fixed.id, rule="override", locked=False, provisional=False, reason="user override", warning=None)
    if mode == "larger_area_fixed":
        fixed, moving = by_area(fa, fb)
        return dict(moving=moving.id, fixed=fixed.id, rule="larger_area_fixed", locked=False, provisional=False, reason="larger area face fixed", warning=None)
    if contacts is not None:
        ca, cb = fa.id in contacts, fb.id in contacts
        if ca != cb:
            fixed, moving = (fa, fb) if ca else (fb, fa)
            return dict(moving=moving.id, fixed=fixed.id, rule="contact_fixed", locked=False, provisional=False, reason="contact face fixed", warning=None)
        if ca and cb:
            fixed, moving = by_area(fa, fb)
            return dict(
                moving=moving.id,
                fixed=fixed.id,
                rule="both_contact_locked",
                locked=True,
                provisional=False,
                reason="both faces in contact (larger area face fixed if enabled)",
                warning="REF_BOTH_CONTACT",
            )

    def dist(f: FaceData) -> float:
        return abs(float(np.dot(body_center - f.centroid, f.normal)))

    da, db = dist(fa), dist(fb)
    if abs(da - db) <= 1e-6 * max(1.0, da, db):
        fixed, moving = by_area(fa, fb)
    else:
        fixed, moving = (fa, fb) if da < db else (fb, fa)
    return dict(
        moving=moving.id,
        fixed=fixed.id,
        rule="center_distance",
        locked=False,
        provisional=contacts is None,
        reason="no contact on either face: face nearer the body center fixed",
        warning=None,
    )


# ---------------------------------------------------------------- feasible range (informational)
def _feasible(ctx_faces: list[FaceData], topo: Topology, ft: Feature, face_owner: dict[int, str], bbox: np.ndarray, cos_par: float) -> dict:
    nom = ft.nominal
    planes = [f for f in ctx_faces if f.surface == "PLANE"]

    def scan(m: FaceData, direction: np.ndarray, exclude: set[int]) -> tuple[float | None, int | None]:
        best, who = None, None
        for q in planes:
            if q.id in exclude or q.id == m.id:
                continue
            if abs(float(np.dot(q.normal, direction))) < cos_par:
                continue
            s = float(np.dot(q.centroid - m.centroid, direction))
            if s <= 1e-6 or not _face_region_overlap(m, q, direction):
                continue
            if best is None or s < best:
                best, who = s, q.id
        return best, who

    lo, hi, lim = WALL_MIN_MM, 2.0 * nom, None
    t = ft.type
    if t in ("THICKNESS", "RIB_THICKNESS", "POCKET_WIDTH"):
        m, x = topo.face(ft.moving[0]), topo.face(ft.fixed[0])
        inward = -m.normal if t != "POCKET_WIDTH" else m.normal  # direction that reduces the value
        s_in, w_in = scan(m, inward, {x.id})
        s_out, w_out = scan(m, -inward, {x.id})
        if s_in is not None:
            lo = max(lo, nom - s_in + WALL_MIN_MM)
            lim = w_in
        if s_out is not None:
            hi = nom + s_out - WALL_MIN_MM
            lim = lim if lim is not None else w_out
    elif t == "RIB_HEIGHT":
        m = topo.face(ft.moving[0])
        s_out, w_out = scan(m, m.normal, set())
        if s_out is not None:
            hi, lim = nom + s_out - WALL_MIN_MM, w_out
    elif t == "POCKET_DEPTH":
        m = topo.face(ft.moving[0])
        s_in, w_in = scan(m, -m.normal, set())
        if s_in is not None:
            hi, lim = nom + s_in - WALL_MIN_MM, w_in
    elif t in ("HOLE_RADIUS", "HOLE_POS_U", "HOLE_POS_V"):
        c = topo.face(ft.moving[0])
        a, d = c.axis_point, _unit(c.axis_dir)
        ax = _dominant_axis(d, math.cos(math.radians(1.0)))
        best = {}
        for q in planes:
            if abs(float(np.dot(q.normal, d))) > 1e-3:
                continue
            if ax is not None and min(q.bbox[3 + ax], c.bbox[3 + ax]) - max(q.bbox[ax], c.bbox[ax]) <= 1e-6:
                continue
            sd = float(np.dot(a - q.centroid, q.normal))  # >0: axis on the material side? (q.normal points outward)
            dist = abs(sd)
            if t == "HOLE_RADIUS":
                if "r" not in best or dist < best["r"][0]:
                    best["r"] = (dist, q.id)
            else:
                k = ft.axis
                comp = float(q.normal[k])
                if abs(comp) < cos_par:
                    continue
                side = "minus" if float(q.centroid[k]) < float(a[k]) else "plus"
                if side not in best or dist < best[side][0]:
                    best[side] = (dist, q.id)
        r = float(c.radius)
        if t == "HOLE_RADIUS":
            if "r" in best:
                hi, lim = r + (best["r"][0] - r) - WALL_MIN_MM, best["r"][1]
        else:
            lo, hi = nom - (bbox[3 + ft.axis] - bbox[ft.axis]), nom + (bbox[3 + ft.axis] - bbox[ft.axis])
            if "minus" in best:
                lo, lim = nom - (best["minus"][0] - r - WALL_MIN_MM), best["minus"][1]
            if "plus" in best:
                hi = nom + (best["plus"][0] - r - WALL_MIN_MM)
                lim = lim if lim is not None else best["plus"][1]
    elif t in RIB_POS_TYPES:
        lo, hi, lim = _rib_pos_feasible(planes, topo, ft, bbox, cos_par)
    elif t == "FILLET_RADIUS":
        lo, hi = max(0.1, 0.25 * nom), 2.0 * nom
    hi = max(hi, lo)
    return {"min": rnd(lo), "max": rnd(hi), "limited_by": face_owner.get(lim) if lim is not None else None}


def _rib_pos_feasible(planes: list[FaceData], topo: Topology, ft: Feature, bbox: np.ndarray, cos_par: float) -> tuple[float, float, int | None]:
    """RIB_POS feasible (section 3.2): from the rib foot print (lateral faces' bbox interval along the axis) towards
    -a / +a, the smaller of (i) the nearest plane normal to a whose region overlaps the rib (wall, other rib side)
    minus WALL_MIN_MM and (ii) the base face bbox boundary minus WALL_MIN_MM. Returns (lo, hi, limiting face)."""
    a = int(ft.axis)
    nom = ft.nominal
    own = set(ft.faces)
    lats = [topo.face(g) for g in ft.faces[1:-1]]
    box = np.concatenate([np.min([f.bbox[:3] for f in lats], axis=0), np.max([f.bbox[3:] for f in lats], axis=0)])
    lo_a, hi_a = float(box[a]), float(box[3 + a])
    base = topo.face(ft.fixed[0])
    room = {"minus": (lo_a - float(base.bbox[a]) - WALL_MIN_MM, base.id), "plus": (float(base.bbox[3 + a]) - hi_a - WALL_MIN_MM, base.id)}
    for q in planes:
        if q.id in own or q.normal is None or abs(float(q.normal[a])) < cos_par:
            continue
        if not _bbox_overlap_2d(box, q.bbox, a):
            continue
        c = float(q.centroid[a])
        if c - hi_a > 1e-6:
            side, s = "plus", c - hi_a - WALL_MIN_MM
        elif lo_a - c > 1e-6:
            side, s = "minus", lo_a - c - WALL_MIN_MM
        else:
            continue
        if s < room[side][0]:
            room[side] = (s, q.id)
    lo = nom - max(0.0, room["minus"][0])
    hi = nom + max(0.0, room["plus"][0])
    lim = room["minus"][1] if room["minus"][0] <= room["plus"][0] else room["plus"][1]
    return lo, hi, lim


# ---------------------------------------------------------------- naming / ordering / groups
def component_name(part: str) -> str:
    c = normalize(part) or "BODY"
    if not (c[0].isalpha() or c[0] == "_"):
        c = "_" + c
    return c


def make_name(comp: str, abbr: str, k: int) -> str:
    name = f"{comp}_{abbr}_{k}"
    if len(name) <= NAME_MAX:
        return name
    h = hashlib.sha1(comp.encode("utf-8")).hexdigest()[:4].upper()
    keep = NAME_MAX - len(f"_{h}_{abbr}_{k}")
    return f"{comp[:keep]}_{h}_{abbr}_{k}"


def _sig_centroid(topo: Topology, ft: Feature) -> tuple:
    c = np.mean([topo.face(f).centroid for f in ft.faces], axis=0)
    return tuple(rnd(x, 4) for x in c)


def _mirror_point(p: np.ndarray, plane: tuple[np.ndarray, np.ndarray]) -> np.ndarray:
    q, n = plane
    return p - 2.0 * float(np.dot(p - q, n)) * n


def _is_mirror(ta: Topology, fa: Feature, tb: Topology, fb: Feature, plane, tol: float, same_body: bool = False) -> bool:
    if fa.type != fb.type or len(fa.faces) != len(fb.faces):
        return False
    if abs(fa.nominal - fb.nominal) > tol:
        return False
    used: set[int] = set()
    shared = set(fa.faces) & set(fb.faces) if same_body else set()
    for f in fa.faces:
        if f in shared:  # e.g. the common base face of two ribs maps onto itself
            used.add(f)
            continue
        A = ta.face(f)
        m = _mirror_point(A.centroid, plane)
        hit = None
        for g in fb.faces:
            if g in used:
                continue
            B = tb.face(g)
            if float(np.linalg.norm(B.centroid - m)) <= tol and abs(A.area - B.area) <= 0.01 * max(A.area, B.area):
                hit = g
                break
        if hit is None:
            return False
        used.add(hit)
    return True


def _mirror_candidates(feats: list[Feature], tol_of: dict[str, float]):
    """(i, j>i) pairs in row-major order that ``_is_mirror`` could accept: same type and signature-face count,
    nominal within the largest body tolerance (every dropped pair fails ``_is_mirror``'s first checks)."""
    import bisect

    tmax = max(tol_of.values(), default=0.0)
    win = tmax * (1.0 + 1e-9) + 1e-12
    buckets: dict[tuple, list[tuple[float, int]]] = {}
    for k, ft in enumerate(feats):
        buckets.setdefault((ft.type, len(ft.faces)), []).append((ft.nominal, k))
    sorted_b = {key: sorted(v) for key, v in buckets.items()}
    noms = {key: [x for x, _ in v] for key, v in sorted_b.items()}
    for i, ft in enumerate(feats):
        key = (ft.type, len(ft.faces))
        vals, lst = noms[key], sorted_b[key]
        lo = bisect.bisect_left(vals, ft.nominal - win)
        hi = bisect.bisect_right(vals, ft.nominal + win)
        for j in sorted(k for _, k in lst[lo:hi] if k > i):
            yield i, j


def symmetry_groups(feats: list[Feature], topo_of: dict[str, Topology], bbox_of: dict[str, np.ndarray], tol_of: dict[str, float]) -> list[dict]:
    """MIRROR groups via union-find over mirror relations (bbox-center planes, common inter-body planes)."""
    n = len(feats)
    parent = list(range(n))
    plane_of: dict[int, tuple] = {}

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def center(b):
        bb = bbox_of[b]
        return 0.5 * (bb[:3] + bb[3:])

    eye = np.eye(3)
    for i, j in _mirror_candidates(feats, tol_of):
        a, b = feats[i], feats[j]
        if a.type != b.type:
            continue
        tol = max(tol_of[a.body], tol_of[b.body])
        planes = []
        if a.body == b.body:
            c = center(a.body)
            planes = [(c, eye[k]) for k in range(3)]
        else:
            ca, cb = center(a.body), center(b.body)
            d = cb - ca
            for k in range(3):
                others = [x for x in range(3) if x != k]
                if abs(d[k]) > tol and all(abs(d[x]) <= tol for x in others):
                    planes.append((0.5 * (ca + cb), eye[k]))
        for pl in planes:
            if _is_mirror(topo_of[a.body], a, topo_of[b.body], b, pl, tol, same_body=a.body == b.body):
                ri, rj = find(i), find(j)
                if ri != rj:
                    parent[rj] = ri
                    plane_of.setdefault(ri, pl)
                    plane_of.setdefault(rj, pl)
                break
    clusters: dict[int, list[int]] = {}
    for i in range(n):
        clusters.setdefault(find(i), []).append(i)
    groups = []
    for root, members in clusters.items():
        if len(members) < 2:
            continue
        names = sorted(feats[m].name for m in members)
        pl = plane_of.get(root)
        if pl is None:
            for m in members:
                if m in plane_of:
                    pl = plane_of[m]
                    break
        first_pos = min(members)
        groups.append((first_pos, names, pl, members))
    groups.sort(key=lambda g: g[0])
    out = []
    for k, (_, names, pl, members) in enumerate(groups, 1):
        gid = f"G{k}"
        for m in members:
            feats[m].group = gid
        out.append(
            {
                "id": gid,
                "kind": "MIRROR",
                "plane": {"point": vec(pl[0]), "normal": vec(pl[1])} if pl is not None else None,
                "parameter": names[0],
                "members": names,
            }
        )
    return out


def finalize(
    per_body: list[tuple[str, str, BodyGeom, list[Feature]]],
    opts: dict,
    tol_of: dict[str, float],
    timing: dict | None = None,
) -> tuple[list[Feature], list[dict], list[dict]]:
    """Order, name, reference rule (provisional), feasible/range, groups.

    ``per_body`` = [(body name, part name, body, features)] in component order.
    Returns (features in output order, groups, warnings).
    """
    warnings: list[dict] = []
    ordered: list[Feature] = []
    topo_of, bbox_of = {}, {}
    overrides = opts.get("thickness_ref_overrides") or {}
    mode = opts.get("thickness_ref", "contact_fixed")
    ratio = float(opts["extract"]["range_ratio"])
    pos_mm = float(opts["extract"]["position_range_mm"])
    cos_par = math.cos(math.radians(float(opts["extract"]["draft_max_deg"])))
    for bname, part, body, feats in per_body:
        topo = body.topology()
        topo_of[bname] = topo
        bbox_of[bname] = body.summary().bbox
        comp = component_name(part)
        for ft in feats:
            ft.order_key = (TYPE_ORDER.index(ft.type), _sig_centroid(topo, ft))
        feats.sort(key=lambda f: f.order_key)
        counters: dict[str, int] = {}
        for ft in feats:
            counters[ft.type] = counters.get(ft.type, 0) + 1
            ft.name = make_name(comp, TYPE_ABBR[ft.type], counters[ft.type])
        ordered.extend(feats)
    # reference faces (extract has no contact info -> provisional rule 3 unless larger_area_fixed/override)
    for ft in ordered:
        topo = topo_of[ft.body]
        if ft.type in PAIR_TYPES and ft.pair is not None:
            fa, fb = topo.face(ft.pair[0]), topo.face(ft.pair[1])
            ov = overrides.get(ft.name)
            ov_id = int(str(ov)[1:]) if isinstance(ov, str) and ov[:1] == "F" and str(ov)[1:].isdigit() else None
            bb = bbox_of[ft.body]
            r = choose_ref(fa, fb, body_center=0.5 * (bb[:3] + bb[3:]), mode=mode, contacts=None, override_fixed=ov_id)
            ft.moving, ft.fixed = [r["moving"]], [r["fixed"]]
            ft.ref = {"rule": r["rule"], "face": f"F{r['fixed']}", "reason": r["reason"], "provisional": r["provisional"], "locked": r["locked"]}
        else:
            ft.ref = {
                "rule": "feature_default",
                "face": f"F{ft.fixed[0]}" if ft.fixed else None,
                "reason": "fixed by feature type",
                "provisional": False,
                "locked": False,
            }
    # feasible ranges
    owner: dict[str, dict[int, str]] = {}
    for ft in ordered:
        d = owner.setdefault(ft.body, {})
        for f in ft.moving + [g for g in ft.faces if g not in ft.fixed]:
            d.setdefault(f, ft.name)
    timing = {} if timing is None else timing
    t0 = time.perf_counter()
    for ft in ordered:
        topo = topo_of[ft.body]
        ft.feasible = _feasible(list(topo.faces), topo, ft, owner.get(ft.body, {}), bbox_of[ft.body], cos_par)
    t1 = time.perf_counter()
    groups = symmetry_groups(ordered, topo_of, bbox_of, tol_of)
    timing["feasible_s"] = t1 - t0
    timing["symmetry_s"] = time.perf_counter() - t1
    for ft in ordered:
        ft.range = _range_mm(ft.nominal, pos_mm, ft.feasible) if ft.type in POSITION_TYPES else _range(ft.nominal, ratio, ft.feasible)
    return ordered, groups, warnings


def _range(nom: float, ratio: float, feas: dict) -> dict:
    lo, hi = nom * (1 - ratio), nom * (1 + ratio)
    if nom < 0:
        lo, hi = hi, lo
    lo = max(lo, feas["min"])
    hi = min(hi, feas["max"])
    if hi < lo:
        lo = hi = min(max(nom, feas["min"]), feas["max"])
    return {"min": rnd(lo), "max": rnd(hi), "ratio": ratio}


def _range_mm(nom: float, mm: float, feas: dict) -> dict:
    """Position parameters: absolute range nominal +- ``mm`` (clipped to ``feasible``)."""
    lo = max(nom - mm, feas["min"])
    hi = min(nom + mm, feas["max"])
    if hi < lo:
        lo = hi = min(max(nom, feas["min"]), feas["max"])
    return {"min": rnd(lo), "max": rnd(hi), "mm": mm}


def face_signature(f: FaceData) -> dict:
    sig = {"surface": f.surface}
    if f.normal is not None:
        sig["normal"] = vec(f.normal)
    if f.axis_dir is not None:
        sig["axis_point"] = vec(f.axis_point)
        sig["axis_dir"] = vec(f.axis_dir)
        sig["radius"] = rnd(f.radius) if f.radius is not None else None
    sig["centroid"] = vec(f.centroid)
    sig["area"] = rnd(f.area)
    sig["bbox"] = vec(f.bbox)
    return sig


def adjacent_surfaces(topo: Topology, faces) -> list[str]:
    """Sorted surface kinds of the faces sharing an edge with the feature's faces (1-hop, feature faces
    excluded) - the neighbourhood descriptor used by ``paicad map`` (S_nbr)."""
    own = {int(f) for f in faces}
    adj: set[int] = set()
    for f in own:
        for e in topo.face(f).edges:
            adj.update(g for g in topo.edge(e).faces if g not in own)
    return sorted(topo.face(g).surface for g in adj)
