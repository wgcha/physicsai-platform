"""Bead operations -> topology-preserving sheet rebuild input (shell-morph section 6.4), no OCP.

Surfaces keep their own frame: planes / cylinders are moved rigidly (flank planes also rotated when the
flank angle changes), tori get a new major radius and height, cones a new reference radius and
semi-angle. Edge and vertex geometry are the images of the nominal points under :func:`beads.point_map`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from ..kernel.base import SurfaceEdit
from .beads import Bead, Profile, core_coords, point_map

EPS = 1e-10


@dataclass
class EditPlan:
    face_edits: dict[int, SurfaceEdit] = field(default_factory=dict)
    edge_points: dict[int, np.ndarray] = field(default_factory=dict)
    vertex_pos: dict[int, np.ndarray] = field(default_factory=dict)
    geometry: set[int] = field(default_factory=set)
    boundary_only: set[int] = field(default_factory=set)


def _edge_t(topo, eid: int) -> np.ndarray:
    e = topo.edge(eid)
    return np.array([0.0, 1.0 / 3.0, 2.0 / 3.0]) if len(e.vertices) == 1 else np.array([0.0, 0.5, 1.0])


def plan_bead(body, bead: Bead, new: Profile, shift: np.ndarray, plan: EditPlan) -> None:
    topo = body.topology()
    sp = body.surface_params
    old = bead.prof
    po, pn = old.points(), new.points()
    shift = np.asarray(shift, dtype=float)
    moved_any = bool(np.any(np.abs(shift) > EPS))

    def d3(rhat, dprof):
        return float(dprof[0]) * rhat + float(dprof[1]) * bead.ed

    for f in bead.all_faces():
        fd = topo.face(f)
        k = bead.face_frame[f]["elem"]
        rho, h, foot, rhat = core_coords(np.asarray(fd.centroid)[None, :], bead.core, bead.n, bead.p0, bead.ed)
        rhat = rhat[0]
        ed = None
        if k == 3:
            t = (new.depth - old.depth) * bead.ed + shift
            if np.any(np.abs(t) > EPS):
                ed = SurfaceEdit(translate=t)
        elif fd.surface in ("CYLINDER", "TORUS"):
            C, Cn = (po["C1"], pn["C1"]) if k == 0 else (po["C2"], pn["C2"])
            dC = Cn - C
            if fd.surface == "CYLINDER":
                t = d3(rhat, dC) + shift
                if np.any(np.abs(t) > EPS):
                    ed = SurfaceEdit(translate=t)
            else:
                t = float(dC[1]) * bead.ed + shift
                if np.any(np.abs(t) > EPS) or abs(dC[0]) > EPS:
                    ed = SurfaceEdit(translate=t, radius=float(Cn[0]))
        elif fd.surface == "PLANE":  # straight flank
            dth = po["theta"] - pn["theta"]
            t = d3(rhat, pn["P1"] - po["P1"]) + shift
            if abs(dth) > EPS or np.any(np.abs(t) > EPS):
                X1 = foot[0] + d3(rhat, po["P1"])
                ed = SurfaceEdit(translate=t, rotate_point=X1, rotate_axis=np.cross(rhat, bead.ed), rotate_angle=float(dth))
        elif fd.surface == "CONE":
            prm = sp(f)
            a = np.asarray(prm["axis"], dtype=float)
            sgn = float(np.dot(a, bead.ed))
            L = np.asarray(prm["location"], dtype=float)
            hL = float(np.dot(L - bead.p0, bead.ed))
            dn = pn["d"]
            r_new = float(pn["P1"][0] + (hL - pn["P1"][1]) * dn[0] / dn[1])
            phi_new = math.atan((dn[0] / dn[1]) * sgn)
            do = po["d"]
            phi_old = math.atan((do[0] / do[1]) * sgn)
            if abs(phi_old - float(prm["semi_angle"])) > 1e-6:
                raise ValueError(f"F{f}: cone semi-angle does not match the bead cross-section")
            if moved_any or abs(r_new - float(prm["radius"])) > EPS or abs(phi_new - phi_old) > EPS:
                ed = SurfaceEdit(translate=shift if moved_any else None, radius=r_new, semi_angle=phi_new if abs(phi_new - phi_old) > EPS else None)
        if ed is not None:
            plan.face_edits[f] = ed
            plan.geometry.add(f)
    edges = sorted({e for f in bead.all_faces() for e in topo.face(f).edges})
    for eid in edges:
        t = _edge_t(topo, eid)
        p = body.eval_edge(eid, t)
        q = point_map(bead, new, shift, p)
        if float(np.abs(q - p).max()) > EPS:
            plan.edge_points[eid] = q
            for f in topo.edge(eid).faces:
                if f == bead.base_face:
                    plan.boundary_only.add(f)
                else:
                    plan.geometry.add(f)
    verts = sorted({v for e in edges for v in topo.edge(e).vertices})
    if verts:
        P = topo.vertices[np.array(verts) - 1]
        Q = point_map(bead, new, shift, P)
        for v, p, q in zip(verts, P, Q):
            if float(np.abs(q - p).max()) > EPS:
                plan.vertex_pos[v] = q
