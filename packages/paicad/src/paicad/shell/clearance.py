"""In-plane clearances of bead entry loops (shell-morph sections 4.4 feasible, 6.4-2 collision pre-check)."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .beads import Bead, Profile, core_coords, region_distance

STEP_MM = 0.5


def sample_edges(body, topo, eids, step: float = STEP_MM) -> np.ndarray:
    pts = []
    for e in eids:
        L = topo.edge(e).length
        n = max(2, int(math.ceil(L / step)) + 1)
        pts.append(body.eval_edge(e, np.linspace(0.0, 1.0, n)))
    return np.concatenate(pts) if pts else np.zeros((0, 3))


def loop_points(bead: Bead, rho: float, shift: np.ndarray, step: float = STEP_MM) -> np.ndarray:
    """Points of the entry loop (distance ``rho`` around the shifted core) on the base plane."""
    n = bead.n
    core = [c + shift for c in bead.core]
    if len(core) == 1:
        a = np.cross(n, [1.0, 0.0, 0.0] if abs(n[0]) < 0.9 else [0.0, 1.0, 0.0])
        a /= np.linalg.norm(a)
        b = np.cross(n, a)
        k = max(16, int(math.ceil(2 * math.pi * rho / step)))
        t = np.linspace(0.0, 2 * math.pi, k, endpoint=False)
        return core[0] + rho * (np.outer(np.cos(t), a) + np.outer(np.sin(t), b))
    A, B = core
    u = (B - A) / np.linalg.norm(B - A)
    w = np.cross(n, u)
    L = float(np.linalg.norm(B - A))
    m = max(2, int(math.ceil(L / step)) + 1)
    s = np.linspace(0.0, 1.0, m)
    k = max(8, int(math.ceil(math.pi * rho / step)))
    t = np.linspace(0.0, math.pi, k)
    out = [A + np.outer(s, B - A) + rho * w, A + np.outer(s, B - A) - rho * w]
    out.append(B + rho * (np.outer(np.cos(t), w) + np.outer(np.sin(t), u)))
    out.append(A + rho * (np.outer(np.cos(t), -w) + np.outer(np.sin(t), -u)))
    return np.concatenate(out)


def loop_clearance(bead: Bead, prof: Profile, shift: np.ndarray, pts: np.ndarray) -> float:
    """min over points of (in-plane distance to the shifted core - entry loop radius); negative = inside."""
    if len(pts) == 0:
        return math.inf
    core = [c + shift for c in bead.core]
    rho, _, _, _ = core_coords(pts, core, bead.n, bead.p0, bead.ed)
    return float(np.min(rho) - prof.rho0)


@dataclass
class Obstacles:
    """Obstacles of the beads of one body: base outer boundaries, holes (static), other beads' loops."""

    static: dict[int, list[tuple[str, np.ndarray]]] = field(default_factory=dict)  # base face -> [(label, pts)]

    @classmethod
    def build(cls, body, topo, beads: list[Bead]) -> "Obstacles":
        ob = cls()
        for fid in sorted({b.base_face for b in beads}):
            f = topo.face(fid)
            items = [("base_boundary", sample_edges(body, topo, f.outer_edges))]
            for w in f.inner_wires:
                if all(len(topo.edge(e).faces) == 1 for e in w):
                    items.append(("base_boundary", sample_edges(body, topo, w)))
            ob.static[fid] = items
        return ob

    def items(self, bead: Bead, others: list[tuple[str, Bead, Profile, np.ndarray]]) -> list[tuple[str, np.ndarray]]:
        out = list(self.static.get(bead.base_face, []))
        for label, ob, prof, sh in others:
            if ob is bead or ob.base_face != bead.base_face:
                continue
            out.append((label, loop_points(ob, prof.rho0, sh)))
        return out


def fixed_clearance(bead: Bead, prof: Profile, shift: np.ndarray, fixed_xyz: np.ndarray, tol: float) -> float:
    if fixed_xyz is None or len(fixed_xyz) == 0:
        return math.inf
    return float(np.min(region_distance(bead, prof, shift, fixed_xyz, tol)))


def search_limit(ok, hi: float, step: float, slack=None, lip: float = 1.0) -> float:
    """Largest x in [0, hi] with ok(x) true on the whole way: scan (by ``step``, or by ``slack(x) / lip`` when
    the constraint slack has Lipschitz constant ``lip`` in x), then bisection."""
    x = 0.0
    while x < hi:
        st = step
        if slack is not None:
            st = max(step, slack(x) / lip)
        nx = min(hi, x + st)
        if not ok(nx):
            lo_, hi_ = x, nx
            for _ in range(30):
                mid = 0.5 * (lo_ + hi_)
                if ok(mid):
                    lo_ = mid
                else:
                    hi_ = mid
            return lo_
        x = nx
    return hi
