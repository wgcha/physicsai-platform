"""Bead model: recognition on the neutral topology and the cross-section map (shell-morph sections 6.3, 6.4).

A bead is a closed region of a planar base face: top fillet ring -> flank ring -> bottom fillet ring -> one
flat bottom face. Its geometry is a cross-section *profile* swept at constant distance around a *core*
(a point for a circular bead, a segment for a linear bead) in the base plane:

* profile coordinates ``(rho, h)``: ``rho`` = in-plane distance to the core, ``h`` = depth along ``ed``
  (unit vector from the base plane toward the bottom);
* profile elements: 0 top fillet arc (center ``(rho0, rt)``, from the entry loop ``(rho0, 0)``), 1 straight
  flank (internal tangent of both arcs), 2 bottom fillet arc (center ``(rhob, depth - rb)``), 3 flat bottom
  ``(rho <= rhob, h = depth)``.

Parameter operations change the profile (depth: ``keep_angle`` moves the bottom fillet along the flank,
``keep_bottom`` moves it straight down and re-solves the tangent; width: everything moves out by dW/2)
and translate the core (position). :func:`point_map` sends a nominal point of the bead to the point at the
same normalized position of the same profile element of the new bead; the kernel rebuild and the expected
geometry of every bead face, edge and vertex follow from it. Nothing here imports OCP.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

import numpy as np

from ..kernel.base import Topology

BLEND = ("CYLINDER", "TORUS")
FLANK = ("PLANE", "CONE")
ROLES = ("fillets_top", "flanks", "fillets_bottom", "bottom")


def _unit(v) -> np.ndarray:
    v = np.asarray(v, dtype=float)
    n = float(np.linalg.norm(v))
    return v / n if n > 0 else v


# ------------------------------------------------------------------ profile
@dataclass(frozen=True)
class Profile:
    rho0: float  # top fillet center rho (= entry loop radius)
    rt: float
    rhob: float  # bottom fillet center rho (= bottom flat radius)
    rb: float
    depth: float
    theta_req: float | None = field(default=None, compare=False)  # keep_angle: the flank angle this profile must keep

    def theta(self) -> float | None:
        """Flank angle to the base plane (rad) of the internal tangent of both fillets; None if none exists."""
        dr = self.rhob - self.rho0
        dh = (self.depth - self.rb) - self.rt
        L = math.hypot(dr, dh)
        s = (self.rt + self.rb) / L if L > 0 else 2.0
        if s > 1.0:
            return None
        phi = math.atan2(dh, dr)
        th = math.pi + math.asin(s) - phi
        th = (th + math.pi) % (2.0 * math.pi) - math.pi
        return th

    def points(self) -> dict:
        th = self.theta()
        if th is None:
            raise ValueError("no flank: fillets overlap")
        a1 = np.array([-math.sin(th), -math.cos(th)])
        C1 = np.array([self.rho0, self.rt])
        C2 = np.array([self.rhob, self.depth - self.rb])
        return {
            "P0": np.array([self.rho0, 0.0]),
            "C1": C1,
            "P1": C1 + self.rt * a1,
            "P2": C2 - self.rb * a1,
            "C2": C2,
            "P3": np.array([self.rhob, self.depth]),
            "d": np.array([-math.cos(th), math.sin(th)]),
            "theta": th,
        }

    def flank_length(self) -> float:
        p = self.points()
        return float(np.dot(p["P2"] - p["P1"], p["d"]))

    def width(self) -> float:
        """Distance of the flanks at half depth (linear: across the core line, circular: diameter)."""
        p = self.points()
        P1, d = p["P1"], p["d"]
        h = 0.5 * self.depth
        return 2.0 * float(P1[0] + (h - P1[1]) * d[0] / d[1])

    def with_depth(self, depth: float, mode: str) -> "Profile":
        dd = depth - self.depth
        if mode == "keep_bottom":
            return replace(self, depth=depth)
        th = self.theta()
        return replace(self, depth=depth, rhob=self.rhob - dd / math.tan(th), theta_req=self.theta_req if self.theta_req is not None else th)

    def with_width_delta(self, dw: float) -> "Profile":
        return replace(self, rho0=self.rho0 + 0.5 * dw, rhob=self.rhob + 0.5 * dw)

    def valid(self, min_flank_deg: float = 0.0) -> str | None:
        """None if the profile keeps the bead topology, else the reason."""
        th = self.theta()
        if th is None:
            return "fillets_overlap"
        if not (math.radians(min_flank_deg) - 1e-12 <= th <= 0.5 * math.pi + 1e-9):
            return "flank_angle"
        if self.theta_req is not None and abs(th - self.theta_req) > 1e-6:
            return "flank_length"  # keep_angle: the fillets no longer fit on the original flank line
        if self.flank_length() <= 0.05:
            return "flank_length"
        if self.rhob <= self.rb + 0.05:
            return "bottom_width"
        if self.depth <= 0:
            return "depth"
        return None

    # ---- normalized position on the profile
    def locate(self, rho: float, h: float) -> tuple[int, float]:
        """(element, tau in [0,1]) of the profile point nearest to (rho, h)."""
        p = self.points()
        q = np.array([rho, h])
        best = (math.inf, 3, 0.0)
        for k, (C, r, A, B) in enumerate(((p["C1"], self.rt, p["P0"], p["P1"]), (None, 0, p["P1"], p["P2"]), (p["C2"], self.rb, p["P2"], p["P3"]))):
            if C is None:
                d = B - A
                L2 = float(np.dot(d, d))
                t = float(np.clip(np.dot(q - A, d) / L2, 0.0, 1.0)) if L2 > 0 else 0.0
                dist = float(np.linalg.norm(A + t * d - q))
            else:
                a0 = math.atan2(*(A - C)[::-1])
                a1 = math.atan2(*(B - C)[::-1])
                aq = math.atan2(*(q - C)[::-1])
                span = (a1 - a0 + math.pi) % (2 * math.pi) - math.pi
                rel = (aq - a0 + math.pi) % (2 * math.pi) - math.pi
                t = float(np.clip(rel / span, 0.0, 1.0)) if span != 0 else 0.0
                ang = a0 + t * span
                dist = float(np.linalg.norm(C + r * np.array([math.cos(ang), math.sin(ang)]) - q))
            if dist < best[0] - 1e-12:
                best = (dist, k, t)
        # bottom flat
        rb = p["P3"][0]
        t = float(np.clip(1.0 - rho / rb, 0.0, 1.0)) if rb > 0 else 1.0
        dist = math.hypot(max(0.0, rho - rb), h - self.depth) if rho >= 0 else abs(h - self.depth)
        if dist < best[0] - 1e-12:
            best = (dist, 3, t)
        return best[1], best[2]

    def at(self, k: int, t: float) -> np.ndarray:
        p = self.points()
        if k == 1:
            return p["P1"] + t * (p["P2"] - p["P1"])
        if k == 3:
            return np.array([p["P3"][0] * (1.0 - t), self.depth])
        C, r, A, B = (p["C1"], self.rt, p["P0"], p["P1"]) if k == 0 else (p["C2"], self.rb, p["P2"], p["P3"])
        a0 = math.atan2(*(A - C)[::-1])
        a1 = math.atan2(*(B - C)[::-1])
        span = (a1 - a0 + math.pi) % (2 * math.pi) - math.pi
        ang = a0 + t * span
        return C + r * np.array([math.cos(ang), math.sin(ang)])


# ------------------------------------------------------------------ bead
@dataclass
class Bead:
    body: str
    base_face: int
    loop_edges: list[int]
    faces: dict[str, list[int]]  # ROLES -> face ids
    shape: str  # linear | circular (bottom PCA)
    sense: str  # deboss | emboss
    n: np.ndarray  # base face normal (oriented)
    p0: np.ndarray  # point of the base plane
    ed: np.ndarray  # depth direction
    core: list[np.ndarray]  # [c] or [A, B] on the base plane
    prof: Profile
    face_frame: dict[int, dict] = field(default_factory=dict)  # face id -> {"elem": k, "kind": ..., ...}
    id: str = ""
    k: int = 0

    @property
    def center(self) -> np.ndarray:
        return np.mean(self.core, axis=0)

    def core_dir(self) -> np.ndarray | None:
        return _unit(self.core[1] - self.core[0]) if len(self.core) == 2 else None

    def all_faces(self) -> list[int]:
        return sorted(f for r in ROLES for f in self.faces[r])

    def length(self) -> float:
        L = float(np.linalg.norm(self.core[1] - self.core[0])) if len(self.core) == 2 else 0.0
        return L + self.prof.width()


def section_doc(bead: Bead, new: Profile, shift: np.ndarray) -> dict:
    """Full-precision bead section data (shell_update.json ``beads``) for the morph point map."""
    def prof(p: Profile) -> dict:
        return {"rho0": p.rho0, "rt": p.rt, "rhob": p.rhob, "rb": p.rb, "depth": p.depth}

    return {
        "id": bead.id, "body": bead.body, "faces": [f"F{f}" for f in bead.all_faces()], "base_face": f"F{bead.base_face}",
        "core": [[float(x) for x in c] for c in bead.core], "normal": [float(x) for x in bead.n], "base_point": [float(x) for x in bead.p0],
        "depth_dir": [float(x) for x in bead.ed], "profile": prof(bead.prof), "new_profile": prof(new), "shift": [float(x) for x in shift],
    }


def bead_from_section(d: dict) -> tuple[Bead, Profile, np.ndarray]:
    def prof(x: dict) -> Profile:
        return Profile(float(x["rho0"]), float(x["rt"]), float(x["rhob"]), float(x["rb"]), float(x["depth"]))

    core = [np.asarray(c, dtype=float) for c in d["core"]]
    b = Bead(d["body"], int(d["base_face"][1:]), [], {r: [] for r in ROLES}, "linear" if len(core) == 2 else "circular", "", np.asarray(d["normal"], dtype=float),
             np.asarray(d["base_point"], dtype=float), np.asarray(d["depth_dir"], dtype=float), core, prof(d["profile"]), id=d["id"])
    return b, prof(d["new_profile"]), np.asarray(d["shift"], dtype=float)


def core_coords(pts: np.ndarray, core: list[np.ndarray], n: np.ndarray, p0: np.ndarray, ed: np.ndarray):
    """(rho[k], h[k], foot[k,3], rhat[k,3]) of points w.r.t. a core (point / segment) in the base plane."""
    pts = np.asarray(pts, dtype=float).reshape(-1, 3)
    h = (pts - p0) @ ed
    q = pts - np.outer((pts - p0) @ n, n)  # projection on the base plane
    if len(core) == 1:
        foot = np.repeat(core[0][None, :], len(pts), axis=0)
    else:
        A, B = core
        d = B - A
        L2 = float(np.dot(d, d))
        t = np.clip(((q - A) @ d) / L2, 0.0, 1.0) if L2 > 0 else np.zeros(len(pts))
        foot = A + t[:, None] * d
    r = q - foot
    rho = np.linalg.norm(r, axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        rhat = np.where(rho[:, None] > 1e-12, r / np.where(rho > 1e-12, rho, 1.0)[:, None], 0.0)
    return rho, h, foot, rhat


def point_map(bead: Bead, new_prof: Profile, shift: np.ndarray, pts: np.ndarray) -> np.ndarray:
    """Images of nominal bead points (on the bead faces or the entry loop) in the changed bead."""
    rho, h, foot, rhat = core_coords(pts, bead.core, bead.n, bead.p0, bead.ed)
    out = np.zeros((len(rho), 3))
    for i in range(len(rho)):
        k, t = bead.prof.locate(float(rho[i]), float(h[i]))
        q = new_prof.at(k, t)
        r = rhat[i]
        if not np.any(r) and q[0] > 1e-9:
            r = _unit(np.cross(bead.n, bead.core_dir() if bead.core_dir() is not None else np.array([1.0, 0.0, 0.0])))
        out[i] = foot[i] + shift + q[0] * r + q[1] * bead.ed
    return out


def region_distance(bead: Bead, prof: Profile, shift: np.ndarray, pts: np.ndarray, tol: float) -> np.ndarray:
    """Distance of points to the bead region (bead faces + entry loop) of a bead with profile ``prof`` and
    core shifted by ``shift``: 0 inside, else the 3D distance to the entry loop."""
    core = [c + shift for c in bead.core]
    rho, h, _, _ = core_coords(pts, core, bead.n, bead.p0 + shift, bead.ed)
    hn = (np.asarray(pts, dtype=float).reshape(-1, 3) - bead.p0) @ bead.n
    inside = (rho <= prof.rho0 + tol) & (h >= -tol) & (h <= prof.depth + tol) & (np.abs(hn) <= prof.depth + tol)
    out = np.hypot(np.maximum(0.0, rho - prof.rho0), hn)
    out[inside & (rho <= prof.rho0)] = 0.0
    return out


# ------------------------------------------------------------------ recognition
@dataclass
class Recognized:
    beads: list[Bead]
    warnings: list[dict]
    holes: list[list[int]]  # inner wires made of free edges (per base face)
    base_faces: list[int]


def _faces_of_edges(topo: Topology, edges) -> set[int]:
    out: set[int] = set()
    for e in edges:
        out.update(topo.edge(e).faces)
    return out


def _neighbors(topo: Topology, fid: int) -> set[int]:
    out: set[int] = set()
    for e in topo.face(fid).edges:
        out.update(topo.edge(e).faces)
    out.discard(fid)
    return out


def _dist_point_line(p, a, d) -> float:
    v = p - a
    return float(np.linalg.norm(v - np.dot(v, d) * d))


def recognize(body, eo: dict, tol: float, name: str) -> Recognized:
    topo = body.topology()
    sp = getattr(body, "surface_params", None)
    warnings: list[dict] = []
    beads: list[Bead] = []
    holes: list[list[int]] = []
    bases: list[int] = []
    cos_draft = math.cos(math.radians(eo["draft_max_deg"]))
    for base in topo.faces:
        if base.surface != "PLANE" or not base.inner_wires or base.normal is None:
            continue
        n = _unit(base.normal)
        p0 = np.asarray(base.centroid, dtype=float)
        for wire in base.inner_wires:
            nfree = sum(1 for e in wire if len(topo.edge(e).faces) == 1)
            if nfree == len(wire):
                holes.append(list(wire))
                continue
            loc = f"{name}: loop of F{base.id} (edges {','.join('E%d' % e for e in wire[:4])})"
            if nfree:
                warnings.append({"code": "BEAD_IRREGULAR", "body": name, "message": f"{loc}: loop mixes free and shared edges"})
                continue
            if base.id not in bases:
                bases.append(base.id)
            res = _recognize_loop(body, topo, sp, base, wire, n, p0, eo, tol, cos_draft, name, loc)
            if isinstance(res, dict):
                warnings.append(res)
            else:
                beads.append(res)
    return Recognized(beads, warnings, holes, bases)


def _recognize_loop(body, topo, sp, base, wire, n, p0, eo, tol, cos_draft, name, loc):
    def irregular(msg, code="BEAD_IRREGULAR"):
        return {"code": code, "body": name, "message": f"{loc}: {msg}"}

    if any(topo.edge(e).convexity != "SMOOTH" for e in wire):
        return irregular("entry loop is not tangent (no top fillet)")
    visited = {base.id}
    layer = sorted(_faces_of_edges(topo, wire) - visited)
    layers = []
    while layer:
        layers.append(layer)
        visited.update(layer)
        nxt: set[int] = set()
        for f in layer:
            nxt |= _neighbors(topo, f)
        layer = sorted(nxt - visited)
        if len(layers) > 4:
            break
    region = [f for L in layers for f in L]
    for f in region:
        for e in topo.face(f).edges:
            ed_ = topo.edge(e)
            if len(ed_.faces) == 1 and ed_.convexity != "SEAM":
                return irregular("bead region reaches a free edge (open bead)", "BEAD_OPEN_UNSUPPORTED")
            if base.id in ed_.faces and e not in wire:
                return irregular("bead region touches its base face outside the entry loop")
    if len(layers) != 4:
        return irregular(f"expected 4 face rings (fillet, flank, fillet, bottom), found {len(layers)}")
    kinds = [[topo.face(f).surface for f in L] for L in layers]
    if not all(k in BLEND for k in kinds[0]) or not all(k in BLEND for k in kinds[2]):
        return irregular("fillet rings must be cylinders / tori")
    if not all(k in FLANK for k in kinds[1]):
        return irregular("flank ring must be planes / cones")
    if len(layers[3]) != 1 or kinds[3][0] != "PLANE":
        return irregular("bottom must be exactly one planar face")
    bottom = topo.face(layers[3][0])
    if abs(float(np.dot(_unit(bottom.normal), n))) < cos_draft:
        return irregular("bottom is not parallel to the base face")
    sgn = float(np.dot(np.asarray(bottom.centroid) - p0, n))
    depth = abs(sgn)
    if depth < eo["min_depth_mm"]:
        return irregular(f"depth {depth:.3f} mm below min_depth_mm")
    ed = n if sgn > 0 else -n
    sense = "emboss" if sgn > 0 else "deboss"
    # core from the revolved faces (axis parallel to n)
    rot = [f for f in region if topo.face(f).surface in ("TORUS", "CONE")]
    trans = [f for f in region if topo.face(f).surface in ("CYLINDER",) or (topo.face(f).surface == "PLANE" and f in layers[1])]
    ends: list[np.ndarray] = []
    for f in rot:
        fd = topo.face(f)
        if abs(float(np.dot(_unit(fd.axis_dir), n))) < 1.0 - 1e-9:
            return irregular(f"F{f}: revolved face axis is not normal to the base face")
        a = np.asarray(fd.axis_point, dtype=float)
        q = a - float(np.dot(a - p0, n)) * n
        if not any(float(np.linalg.norm(q - e)) <= tol for e in ends):
            ends.append(q)
    if not ends:
        return irregular("no revolved faces (corners without tori/cones are not supported)")
    if len(ends) > 2:
        return irregular("more than two revolution axes")
    if len(ends) == 2:
        ends.sort(key=lambda v: tuple(np.round(v, 6)))
        A, B = ends
        u = _unit(B - A)
        if not trans:
            return irregular("linear bead without straight sides")
        core = [A, B]
    else:
        if trans:
            return irregular("straight sides around a single revolution axis")
        core = [ends[0]]
        u = None

    def rho_h(point):
        rho, h, _, _ = core_coords(np.asarray(point)[None, :], core, n, p0, ed)
        return float(rho[0]), float(h[0])

    # fillet rings -> (rho_c, h_c, r)
    def ring(L):
        vals = []
        for f in L:
            fd = topo.face(f)
            if fd.surface == "TORUS":
                c = np.asarray(fd.axis_point, dtype=float)
                vals.append((float(fd.radius), float(np.dot(c - p0, ed)), float(fd.minor_radius)))
            else:
                if u is None or abs(float(np.dot(_unit(fd.axis_dir), u))) < 1.0 - 1e-9:
                    return None
                a = np.asarray(fd.axis_point, dtype=float)
                vals.append((rho_h(a)[0], float(np.dot(a - p0, ed)), float(fd.radius)))
        arr = np.array(vals)
        if np.ptp(arr, axis=0).max() > tol:
            return None
        return arr.mean(axis=0)

    top = ring(layers[0])
    bot = ring(layers[2])
    if top is None or bot is None:
        return irregular("fillet ring faces do not share one cross-section")
    prof = Profile(rho0=float(top[0]), rt=float(top[2]), rhob=float(bot[0]), rb=float(bot[2]), depth=depth)
    if abs(top[1] - prof.rt) > tol or abs(bot[1] - (depth - prof.rb)) > tol:
        return irregular("fillet centers are not tangent to the base / bottom planes")
    th = prof.theta()
    if th is None:
        return irregular("fillets leave no flank")
    for f in layers[1]:
        fd = topo.face(f)
        if fd.surface == "PLANE":
            if u is None or abs(float(np.dot(_unit(fd.normal), u))) > 1e-6:
                return irregular(f"F{f}: planar flank not parallel to the bead axis")
            thm = math.acos(min(1.0, abs(float(np.dot(_unit(fd.normal), n)))))
        else:
            sa = sp(f).get("semi_angle") if sp else None
            if sa is None:
                return irregular(f"F{f}: cone parameters unavailable")
            thm = 0.5 * math.pi - abs(sa)
        if abs(thm - th) > math.radians(0.5):
            return irregular(f"F{f}: flank angle {math.degrees(thm):.2f} deg does not match the fillets ({math.degrees(th):.2f} deg)")
    if th < math.radians(eo["min_flank_deg"]) - 1e-9 or th > 0.5 * math.pi + 1e-9:
        return irregular(f"flank angle {math.degrees(th):.2f} deg outside [{eo['min_flank_deg']}, 90]")
    # entry loop at rho0, bottom at rhob
    for e in wire:
        mid = body.eval_edge(e, np.array([0.5]))[0]
        r_, h_ = rho_h(mid)
        if abs(r_ - prof.rho0) > tol or abs(h_) > tol:
            return irregular(f"E{e}: entry loop is not at the fillet start")
    if prof.valid() is not None:
        return irregular(f"cross-section is degenerate ({prof.valid()})")
    pts = body.sample_face(bottom.id, 24)
    shape = "circular"
    if len(pts) >= 3:
        q = pts - pts.mean(axis=0)
        q = q - np.outer(q @ n, n)
        ev = np.sort(np.linalg.eigvalsh(q.T @ q))[::-1]
        if ev[1] > 0 and math.sqrt(ev[0] / ev[1]) >= eo["linear_aspect"]:
            shape = "linear"
    frames = {}
    for k, L in enumerate(layers):
        for f in L:
            frames[f] = {"elem": k}
    faces = {ROLES[k]: list(L) for k, L in enumerate(layers)}
    return Bead(name, base.id, list(wire), faces, shape, sense, n, p0, ed, core, prof, frames)


# ------------------------------------------------------------------ axes / references
def bead_axes(bead: Bead) -> tuple[np.ndarray, np.ndarray]:
    """(U, V): linear = core direction (largest component positive), circular = global axis with the largest
    projection on the base plane (x -> y -> z); V = n x U."""
    n = bead.n
    if bead.shape == "linear" and bead.core_dir() is not None:
        u = bead.core_dir()
    else:
        best, u = -1.0, None
        for ax in np.eye(3):
            p = ax - np.dot(ax, n) * n
            ln = float(np.linalg.norm(p))
            if ln > best + 1e-9:
                best, u = ln, p / ln
    k = int(np.argmax(np.abs(u)))
    if u[k] < 0:
        u = -u
    v = _unit(np.cross(n, u))
    return u, v


def edge_line(body, topo: Topology, eid: int) -> tuple[np.ndarray, np.ndarray, float]:
    """(point, unit direction, length) of a straight edge."""
    e = topo.edge(eid)
    p = body.eval_edge(eid, np.array([0.0, 0.5, 1.0]))
    return p[1], _unit(p[2] - p[0]), float(e.length)


def nearest_fixed_edge(body, topo: Topology, bead: Bead, axis: np.ndarray, candidates: list[int]) -> dict | None:
    """Section 6.3 table: nearest straight edge normal to the axis (+-10 deg) along the axis from the bead center.
    Returns {edge, dist, sign, point} (sign: the bead lies on the +sign side of the edge along ``axis``)."""
    c = bead.center
    lim = math.sin(math.radians(10.0))
    best = None
    pool = []
    for eid in candidates:
        e = topo.edge(eid)
        if e.curve != "LINE":
            continue
        p, d, ln = edge_line(body, topo, eid)
        if abs(float(np.dot(d, axis))) > lim:
            continue
        dist = float(np.dot(c - p, axis))
        # does the line through the center along the axis hit the edge segment?
        ends = body.eval_edge(eid, np.array([0.0, 1.0]))
        perp = _unit(np.cross(bead.n, axis))
        s0, s1 = sorted(float(np.dot(x - c, perp)) for x in ends)
        hit = s0 - 1e-6 <= 0.0 <= s1 + 1e-6
        pool.append((not hit, round(abs(dist), 9), -round(ln, 9), eid, dist, p))
    if not pool:
        return None
    pool.sort(key=lambda t: t[:4])
    _, ad, _, eid, dist, p = pool[0]
    best = {"edge": eid, "dist": abs(dist), "sign": 1.0 if dist >= 0 else -1.0, "point": p}
    return best
