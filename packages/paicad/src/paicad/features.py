"""Feature recognition, reference-face rule and symmetry groups (contract section 6.2).

Works only through the neutral kernel protocol (``paicad.kernel.base.BodyGeom``).
"""

from __future__ import annotations

import hashlib
import math
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
}
PAIR_TYPES = ("THICKNESS", "POCKET_WIDTH", "RIB_THICKNESS")  # reference-face rule applies
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

    def neighbours(self, f: FaceData, edges) -> dict[int, list[int]]:
        """edge id -> other face ids across that edge."""
        out = {}
        for e in edges:
            out[e] = [g for g in self.edge_faces[e] if g != f.id]
        return out

    def face(self, fid: int) -> FaceData:
        return self.topo.face(fid)


def _find_protrusions(ctx: _Ctx, sign: int) -> list[tuple[int, list[int], int, float]]:
    """sign=+1: ribs (convex top, concave base); sign=-1: pockets (concave floor, convex entry).

    Returns [(cap face, lateral faces, base/entry face, height/depth)].
    """
    want_cap = "CONVEX" if sign > 0 else "CONCAVE"
    want_base = "CONCAVE" if sign > 0 else "CONVEX"
    found = []
    for cap in ctx.planes:
        if cap.inner_wires or not cap.outer_edges:
            continue
        if any(ctx.edge_conv[e] != want_cap for e in cap.outer_edges):
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
            continue
        lats = [ctx.face(g) for g in lat_ids]
        if any(l.surface != "PLANE" or abs(float(np.dot(l.normal, cap.normal))) > ctx.sin_perp for l in lats):
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
            continue
        base = ctx.face(base_id)
        if base.surface != "PLANE" or float(np.dot(base.normal, cap.normal)) < ctx.cos_par:
            continue
        h = float(np.dot(cap.centroid - base.centroid, cap.normal)) * sign
        if h <= 0:
            continue
        found.append((cap.id, sorted(lat_ids), base_id, h))
    return found


def _pairs_across(ctx: _Ctx, faces: list[FaceData], material: bool) -> list[tuple[FaceData, FaceData, float, float]]:
    """Antiparallel plane pairs. material=True: material between (faces look away from each other)."""
    out = []
    for i, a in enumerate(faces):
        for b in faces[i + 1 :]:
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
            out.append((a, b, d, draft))
    return out


def _overlap_ok(ctx: _Ctx, a: FaceData, b: FaceData, check_material: bool) -> bool:
    r1, pa, fb = _overlap(ctx.body, a, b, ctx.grid)
    if r1 < ctx.overlap_min:
        return False
    r2, _, _ = _overlap(ctx.body, b, a, ctx.grid)
    if r2 < ctx.overlap_min:
        return False
    if check_material and len(pa):
        idx = np.linspace(0, len(pa) - 1, min(len(pa), 16)).astype(int)
        mid = 0.5 * (pa[idx] + fb[idx])
        if ctx.body.points_inside(mid).mean() < 0.5:
            return False
    return True


def recognize_body(body: BodyGeom, opts: dict) -> list[Feature]:
    ctx = _Ctx(body, opts)
    name = body.name or ""
    feats: list[Feature] = []
    claimed: set[int] = set()
    cos1 = math.cos(math.radians(1.0))

    # holes and fillets (revolved faces)
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
            feats.append(Feature("HOLE_RADIUS", name, f.radius, [f.id], [f.id], []))
            k = _dominant_axis(f.axis_dir, cos1)
            if k is not None:
                bb = ctx.summary.bbox
                others = [a for a in range(3) if a != k]
                for t, a in zip(("HOLE_POS_U", "HOLE_POS_V"), others):
                    feats.append(Feature(t, name, float(f.axis_point[a] - bb[a]), [f.id], [f.id], [], axis=a))
        elif f.span_deg < 180.0 - 1e-6:
            smooth = sum(1 for e in f.edges if ctx.edge_conv[e] == "SMOOTH")
            if smooth >= 2:
                claimed.add(f.id)
                feats.append(Feature("FILLET_RADIUS", name, f.radius, [f.id], [f.id], []))
    for f in ctx.topo.faces:
        if f.surface == "TORUS" and f.id not in claimed:
            smooth = sum(1 for e in f.edges if ctx.edge_conv[e] == "SMOOTH")
            if smooth >= 2:
                claimed.add(f.id)
                feats.append(Feature("FILLET_RADIUS", name, f.minor_radius, [f.id], [f.id], []))

    # ribs
    for cap, lats, base, h in _find_protrusions(ctx, +1):
        claimed.update([cap, *lats])
        feats.append(Feature("RIB_HEIGHT", name, h, [cap, base], [cap], [base], draft_deg=0.0))
        for a, b, d, dr in _pairs_across(ctx, [ctx.face(g) for g in lats], material=True):
            if d < h and _overlap_ok(ctx, a, b, check_material=True):
                feats.append(Feature("RIB_THICKNESS", name, d, [a.id, b.id], [], [], pair=(a.id, b.id), draft_deg=dr))

    # pockets
    for floor, walls, entry, depth in _find_protrusions(ctx, -1):
        claimed.update([floor, *walls])
        feats.append(Feature("POCKET_DEPTH", name, depth, [floor, entry], [floor], [entry]))
        for a, b, d, dr in _pairs_across(ctx, [ctx.face(g) for g in walls], material=False):
            if _overlap_ok(ctx, a, b, check_material=False):
                feats.append(Feature("POCKET_WIDTH", name, d, [a.id, b.id], [], [], pair=(a.id, b.id), draft_deg=dr))

    # thickness: remaining planes, mutual nearest antiparallel pair with material between
    free = [f for f in ctx.planes if f.id not in claimed]
    cands = [(a, b, d, dr) for a, b, d, dr in _pairs_across(ctx, free, material=True) if _overlap_ok(ctx, a, b, check_material=True)]
    best: dict[int, tuple[float, int]] = {}
    for a, b, d, _ in cands:
        for x, y in ((a.id, b.id), (b.id, a.id)):
            if x not in best or d < best[x][0] - 1e-9:
                best[x] = (d, y)
    for a, b, d, dr in cands:
        if best.get(a.id, (0, -1))[1] == b.id and best.get(b.id, (0, -1))[1] == a.id:
            feats.append(Feature("THICKNESS", name, d, [a.id, b.id], [], [], pair=(a.id, b.id), draft_deg=dr))
    for ft in feats:
        ft.nominal = rnd(ft.nominal)
        ft.draft_deg = rnd(ft.draft_deg, 4)
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
    elif t == "FILLET_RADIUS":
        lo, hi = max(0.1, 0.25 * nom), 2.0 * nom
    hi = max(hi, lo)
    return {"min": rnd(lo), "max": rnd(hi), "limited_by": face_owner.get(lim) if lim is not None else None}


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
    for i in range(n):
        for j in range(i + 1, n):
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
    for ft in ordered:
        topo = topo_of[ft.body]
        ft.feasible = _feasible(list(topo.faces), topo, ft, owner.get(ft.body, {}), bbox_of[ft.body], cos_par)
    groups = symmetry_groups(ordered, topo_of, bbox_of, tol_of)
    for ft in ordered:
        ft.range = _range(ft.nominal, ratio, ft.feasible)
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
