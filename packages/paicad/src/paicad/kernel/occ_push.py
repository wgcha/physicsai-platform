"""Topology-preserving face push/pull for OCCT bodies (contract section 6.3).

Each face gets a new surface (planes translated, cylinders translated and/or re-radiused);
edges and vertices are recomputed as intersections of the new surfaces and the solid is
rebuilt with exactly the nominal topology (same face/edge/vertex structure and order), so
the face map nominal -> sample is the identity by construction. This is the "equivalent
face offset" variant of section 6.3 step 2: unlike a prism/boolean it keeps tangent blends
and rigidly moved feature groups intact, and it never changes the topology silently.

Only this kernel subpackage imports OCP.
"""

from __future__ import annotations

import math

import numpy as np
from OCP.BRep import BRep_Builder, BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Curve2d
from OCP.BRepAlgoAPI import BRepAlgoAPI_Check
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepLib import BRepLib
from OCP.ElCLib import ElCLib
from OCP.Geom import (
    Geom_BSplineSurface,
    Geom_Circle,
    Geom_CylindricalSurface,
    Geom_Line,
    Geom_Plane,
    Geom_RectangularTrimmedSurface,
)
from OCP.Geom2d import Geom2d_Line
from OCP.GeomAbs import GeomAbs_Circle, GeomAbs_Line
from OCP.GeomAPI import GeomAPI_ProjectPointOnCurve, GeomAPI_ProjectPointOnSurf
from OCP.GeomLib import GeomLib_IsPlanarSurface
from OCP.GeomProjLib import GeomProjLib
from OCP.Geom2dAPI import Geom2dAPI_Interpolate
from OCP.ShapeAnalysis import ShapeAnalysis_Surface
from OCP.TColgp import TColgp_Array2OfPnt, TColgp_HArray1OfPnt2d
from OCP.TColStd import TColStd_Array1OfInteger, TColStd_Array1OfReal, TColStd_HArray1OfReal
from OCP.gp import gp_Ax2, gp_Circ, gp_Dir, gp_Dir2d, gp_Lin, gp_Pnt, gp_Pnt2d, gp_Vec
from OCP.TopAbs import TopAbs_FORWARD, TopAbs_REVERSED, TopAbs_SHELL, TopAbs_WIRE
from OCP.TopoDS import (
    TopoDS,
    TopoDS_Edge,
    TopoDS_Face,
    TopoDS_Iterator,
    TopoDS_Shell,
    TopoDS_Solid,
    TopoDS_Vertex,
    TopoDS_Wire,
)

from .base import FaceMove

TOL = 1.0e-7  # B-rep tolerance of rebuilt sub-shapes
ON_TOL = 1.0e-6  # max distance of a recomputed vertex from its incident surfaces / edge curve
TWO_PI = 2.0 * math.pi


class PushPullError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _xyz(p) -> np.ndarray:
    return np.array([p.X(), p.Y(), p.Z()], dtype=float)


def _dir(d) -> np.ndarray:
    return np.array([d.X(), d.Y(), d.Z()], dtype=float)


def _unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n > 0 else v


# ------------------------------------------------------------------ new surfaces
class _Surf:
    """New surface of one face + numeric distance function (for vertex solving).

    ``kind`` is the geometric kind used for the math (planar B-splines count as PLANE);
    ``geom`` is the OCCT surface put on the rebuilt face.
    """

    def __init__(self, geom, kind: str, plane: tuple[np.ndarray, np.ndarray] | None = None):
        self.geom = geom
        self.kind = kind
        if kind == "PLANE":
            if plane is None:
                pl = geom.Pln()
                plane = (_xyz(pl.Location()), _dir(pl.Axis().Direction()))
            self.p0, self.n = plane
        elif kind == "CYLINDER":
            c = geom.Cylinder()
            ax = c.Position()
            self.a = _xyz(ax.Location())
            self.d = _dir(ax.Direction())
            self.x = _dir(ax.XDirection())
            self.y = _dir(ax.YDirection())
            self.r = float(c.Radius())

    def dist_grad(self, p: np.ndarray) -> tuple[float, np.ndarray]:
        if self.kind == "PLANE":
            return float(np.dot(p - self.p0, self.n)), self.n
        if self.kind == "CYLINDER":
            v = p - self.a
            w = v - np.dot(v, self.d) * self.d
            rho = float(np.linalg.norm(w))
            if rho <= 1e-15:
                return -self.r, self.x
            return rho - self.r, w / rho
        pr = GeomAPI_ProjectPointOnSurf(gp_Pnt(*p), self.geom)
        if pr.NbPoints() == 0:
            raise PushPullError("GEOM_CAD_FAILED", "point projection on a surface failed")
        q = _xyz(pr.NearestPoint())
        g = p - q
        d = float(np.linalg.norm(g))
        return d, (g / d if d > 0 else np.zeros(3))

    def angle(self, p: np.ndarray) -> float:
        v = p - self.a
        return math.atan2(float(np.dot(v, self.y)), float(np.dot(v, self.x)))


def _base_surface(face):
    s = BRep_Tool.Surface_s(face)
    if isinstance(s, Geom_RectangularTrimmedSurface):
        s = s.BasisSurface()
    return s


def _extend_bilinear(s, factor: float = 1.0):
    """Planar degree-1 x 1 B-spline with 2 x 2 poles -> same bilinear polynomial on a larger domain.

    The parametrization is unchanged on the original domain, so normalized (u,v) keep their meaning
    when the face grows. Returns None for other B-splines.
    """
    if not isinstance(s, Geom_BSplineSurface):
        return None
    if s.UDegree() != 1 or s.VDegree() != 1 or s.NbUPoles() != 2 or s.NbVPoles() != 2 or s.IsURational() or s.IsVRational():
        return None
    u0, u1, v0, v1 = s.Bounds()
    du, dv = factor * (u1 - u0), factor * (v1 - v0)
    U = (u0 - du, u1 + du)
    V = (v0 - dv, v1 + dv)
    poles = TColgp_Array2OfPnt(1, 2, 1, 2)
    for i, u in enumerate(U, 1):
        for j, v in enumerate(V, 1):
            poles.SetValue(i, j, s.Value(u, v))
    uk = TColStd_Array1OfReal(1, 2)
    vk = TColStd_Array1OfReal(1, 2)
    mult = TColStd_Array1OfInteger(1, 2)
    uk.SetValue(1, U[0])
    uk.SetValue(2, U[1])
    vk.SetValue(1, V[0])
    vk.SetValue(2, V[1])
    mult.SetValue(1, 2)
    mult.SetValue(2, 2)
    return Geom_BSplineSurface(poles, uk, vk, mult, mult, 1, 1)


def _new_surface(face, mv: FaceMove | None) -> tuple[_Surf, bool]:
    """(new surface, uv_changed). uv_changed = the face parametrization had to be replaced."""
    s = _base_surface(face)
    plane = None
    uv_changed = False
    if isinstance(s, Geom_Plane):
        kind = "PLANE"
    elif isinstance(s, Geom_CylindricalSurface):
        kind = "CYLINDER"
    else:
        kind = "OTHER"
        chk = GeomLib_IsPlanarSurface(s, 1e-6)
        if chk.IsPlanar():
            kind = "PLANE"
            pl = chk.Plan()
            ext = _extend_bilinear(s)  # the face may grow even when its own surface does not move
            if ext is not None:
                s = ext
            elif mv is not None and mv.is_effective():
                s = Geom_Plane(pl)
                uv_changed = True
            plane = (_xyz(pl.Location()), _dir(pl.Axis().Direction()))
    t = mv.translate if mv is not None else None
    if t is not None and np.any(np.asarray(t) != 0):
        g = s.Translated(gp_Vec(*map(float, t)))
        if plane is not None:
            plane = (plane[0] + np.asarray(t, dtype=float), plane[1])
    else:
        g = s.Copy()
    if mv is not None and mv.radius is not None:
        if kind != "CYLINDER":
            raise PushPullError("GEOM_CAD_FAILED", "radius change is only supported on cylindrical faces")
        if not (mv.radius > 0 and math.isfinite(mv.radius)):
            raise PushPullError("GEOM_CAD_FAILED", f"invalid cylinder radius {mv.radius!r}")
        g.SetRadius(float(mv.radius))
    return _Surf(g, kind, plane), uv_changed


def _pcurve_by_sampling(curve, u1: float, u2: float, surf, eid: int, n: int = 24):
    """pcurve with the 3D curve parametrization: (u,v) of samples interpolated at the same parameters."""
    sas = ShapeAnalysis_Surface(surf)
    pts = TColgp_HArray1OfPnt2d(1, n)
    par = TColStd_HArray1OfReal(1, n)
    for i in range(n):
        t = u1 + (u2 - u1) * i / (n - 1)
        p = curve.Value(t)
        uv = sas.ValueOfUV(p, 1e-9)
        if sas.Gap() > ON_TOL:
            raise PushPullError("GEOM_CAD_FAILED", f"edge E{eid}: curve leaves its face surface")
        pts.SetValue(i + 1, uv)
        par.SetValue(i + 1, t)
    it = Geom2dAPI_Interpolate(pts, par, False, 1e-12)
    it.Perform()
    if not it.IsDone():
        raise PushPullError("GEOM_CAD_FAILED", f"edge E{eid}: pcurve construction failed")
    return it.Curve()


# ------------------------------------------------------------------ the rebuild
class _Rebuild:
    def __init__(self, body, moves: dict[int, FaceMove]):
        self.b = body
        self.moves = moves
        self.topo = body.topology()
        self.nf, self.ne, self.nv = len(body._faces), len(body._edges), len(body._verts)

    # ---- helpers
    def move_key(self, fid: int):
        m = self.moves.get(fid)
        if m is None:
            return (0.0, 0.0, 0.0, None)
        t = tuple(float(x) for x in (m.translate if m.translate is not None else (0, 0, 0)))
        return (*t, m.radius)

    def run(self):
        b = self.b
        topo = self.topo
        ns = [_new_surface(b._faces[i], self.moves.get(i + 1)) for i in range(self.nf)]
        self.surf = [x[0] for x in ns]
        self.uv_changed = {i + 1 for i, x in enumerate(ns) if x[1]}
        # vertex -> incident faces / seam info
        v_faces: dict[int, set[int]] = {v: set() for v in range(1, self.nv + 1)}
        v_seams: dict[int, list[int]] = {v: [] for v in range(1, self.nv + 1)}
        self.v_smooth: dict[int, list[int]] = {v: [] for v in range(1, self.nv + 1)}
        for e in topo.edges:
            for v in e.vertices:
                v_faces[v].update(e.faces)
                if e.convexity == "SEAM":
                    v_seams[v].append(e.id)
                elif e.convexity == "SMOOTH" and len(e.faces) == 2:
                    self.v_smooth[v].append(e.id)
        old_v = topo.vertices
        new_v = np.zeros_like(old_v)
        for v in range(1, self.nv + 1):
            fs = sorted(v_faces[v])
            keys = {self.move_key(f) for f in fs}
            if len(keys) == 1:
                k = next(iter(keys))
                if k[3] is None:
                    new_v[v - 1] = old_v[v - 1] + np.array(k[:3])
                    continue
            new_v[v - 1] = self.solve_vertex(v, fs, v_seams[v], old_v[v - 1])
        self.new_v = new_v
        self.translated_old: set[int] = set()
        self.edge_geom = [self.edge_curve(e) for e in topo.edges]
        return self.build()

    def solve_vertex(self, vid: int, faces: list[int], seams: list[int], p_old: np.ndarray) -> np.ndarray:
        extra = []
        seam_dirs: list[tuple[np.ndarray, np.ndarray]] = []
        drop: set[int] = set()
        for eid in self.v_smooth[vid]:
            f1, f2 = self.topo.edge(eid).faces
            s1, s2 = self.surf[f1 - 1], self.surf[f2 - 1]
            if {s1.kind, s2.kind} != {"PLANE", "CYLINDER"}:
                continue
            pln, cyl, fc = (s1, s2, f2) if s1.kind == "PLANE" else (s2, s1, f1)
            # tangent line = plane  AND  the plane through the cylinder axis along the plane normal
            q = np.cross(pln.n, cyl.d)
            if float(np.linalg.norm(q)) > 1e-9:
                extra.append((cyl.a, _unit(q)))
                drop.add(fc)
        surfs = [self.surf[f - 1] for f in faces if f not in drop]
        for eid in seams:
            f = self.topo.edge(eid).faces[0]
            s = self.surf[f - 1]
            if s.kind != "CYLINDER":
                continue
            old = _Surf(_base_surface(self.b._faces[f - 1]), "CYLINDER")
            th = old.angle(p_old)
            radial = math.cos(th) * s.x + math.sin(th) * s.y
            nrm = np.cross(s.d, radial)  # plane through the axis at the seam angle
            extra.append((s.a, _unit(nrm)))
            seam_dirs.append((s.a, radial))
        # initial guess: curved faces dominate (a moved hole carries its seam/circle vertices along)
        curved = [f for f in faces if self.surf[f - 1].kind != "PLANE"]
        ts = [np.array(self.move_key(f)[:3]) for f in (curved or faces)]
        p = p_old + np.mean(ts, axis=0)
        scale = 1.0 + float(np.abs(p_old).max())
        res = np.inf
        for _ in range(200):
            r, J = [], []
            for s in surfs:
                d, g = s.dist_grad(p)
                r.append(d)
                J.append(g)
            for a, n in extra:
                r.append(float(np.dot(p - a, n)))
                J.append(n)
            r = np.asarray(r)
            J = np.asarray(J)
            res = float(np.abs(r).max())
            if res <= 1e-13 * scale:
                break
            dp = np.linalg.lstsq(J, -r, rcond=1e-12)[0]
            p = p + dp
            if float(np.linalg.norm(dp)) <= 1e-15 * scale:
                break
        if not np.isfinite(res) or res > 1e-9 * scale:
            raise PushPullError("GEOM_CAD_FAILED", f"vertex V{vid}: incident faces have no common point after the move (residual {res:.3g} mm)")
        for a, radial in seam_dirs:
            if float(np.dot(p - a, radial)) <= 0:
                raise PushPullError("GEOM_CAD_FAILED", f"vertex V{vid}: seam vertex jumped to the opposite side of the cylinder")
        for f in sorted(drop):
            d, _ = self.surf[f - 1].dist_grad(p)
            if abs(d) > ON_TOL:
                raise PushPullError("GEOM_CAD_FAILED", f"vertex V{vid}: blend face F{f} is no longer tangent (gap {d:.3g} mm)")
        return p

    # ---- edges
    def edge_curve(self, e):
        """Return (geom_curve, u_first, u_last, kind) of the new edge."""
        b = self.b
        E = b._edges[e.id - 1]
        ad = BRepAdaptor_Curve(E)
        vf, vl = self.edge_vertices(E)
        pf, pl = self.new_v[vf - 1], self.new_v[vl - 1]
        closed = vf == vl
        old_kind = ad.GetType()
        faces = e.faces
        keys = {self.move_key(f) for f in faces}
        rigid = len(keys) == 1 and next(iter(keys))[3] is None
        both_planar = len(faces) == 2 and all(self.surf[f - 1].kind == "PLANE" for f in faces)
        if both_planar and not (rigid and old_kind == GeomAbs_Line):
            # plane/plane edge: always the analytic intersection line (also replaces bounded B-spline edges)
            s1, s2 = self.surf[faces[0] - 1], self.surf[faces[1] - 1]
            dvec = np.cross(s1.n, s2.n)
            if float(np.linalg.norm(dvec)) < 1e-9:
                raise PushPullError("GEOM_CAD_FAILED", f"edge E{e.id}: adjacent planes became parallel")
            dvec = _unit(dvec)
            if float(np.dot(dvec, self.old_direction(ad))) < 0:
                dvec = -dvec
            return self.line_from(gp_Lin(gp_Pnt(*pf), gp_Dir(*dvec)), pf, pl, e.id)
        seam_tr = e.convexity == "SEAM" and self.surf[faces[0] - 1].kind != "CYLINDER" and self.move_key(faces[0])[3] is None
        if rigid or seam_tr:
            t = np.array(next(iter(keys))[:3])
            self.translated_old.add(e.id)
            if old_kind == GeomAbs_Line:
                return self.line_from(ad.Line().Translated(gp_Vec(*t)), pf, pl, e.id)
            if old_kind == GeomAbs_Circle:
                return self.circle_from(ad.Circle().Translated(gp_Vec(*t)), pf, pl, closed, e.id, ad)
            c = BRep_Tool.Curve_s(E, 0.0, 0.0)
            c = c.Translated(gp_Vec(*t))
            return self.generic_params(c, pf, pl, closed, e.id, ad)
        if e.convexity == "SEAM":
            s = self.surf[faces[0] - 1]
            if old_kind != GeomAbs_Line:
                raise PushPullError("GEOM_CAD_FAILED", f"edge E{e.id}: unsupported seam curve")
            d_old = _dir(ad.Line().Direction())
            dvec = s.d if float(np.dot(d_old, s.d)) > 0 else -s.d
            return self.line_from(gp_Lin(gp_Pnt(*pf), gp_Dir(*dvec)), pf, pl, e.id)
        if len(faces) != 2:
            raise PushPullError("GEOM_CAD_FAILED", f"edge E{e.id}: unsupported edge (adjacent faces {len(faces)})")
        s1, s2 = self.surf[faces[0] - 1], self.surf[faces[1] - 1]
        kinds = {s1.kind, s2.kind}
        if kinds == {"PLANE", "CYLINDER"}:
            pln = s1 if s1.kind == "PLANE" else s2
            cyl = s2 if s1.kind == "PLANE" else s1
            if old_kind == GeomAbs_Circle:
                if abs(float(np.dot(pln.n, cyl.d))) < 1 - 1e-9:
                    raise PushPullError("GEOM_CAD_FAILED", f"edge E{e.id}: plane is not perpendicular to the cylinder axis")
                k = float(np.dot(pln.p0 - cyl.a, pln.n)) / float(np.dot(cyl.d, pln.n))
                c = cyl.a + k * cyl.d
                oc = ad.Circle()
                ax = gp_Ax2(gp_Pnt(*c), oc.Axis().Direction(), oc.XAxis().Direction())
                return self.circle_from(gp_Circ(ax, cyl.r), pf, pl, closed, e.id, ad)
            if old_kind == GeomAbs_Line:
                if abs(float(np.dot(pln.n, cyl.d))) > 1e-9:
                    raise PushPullError("GEOM_CAD_FAILED", f"edge E{e.id}: plane is not parallel to the cylinder axis")
                d_old = _dir(ad.Line().Direction())
                dvec = cyl.d if float(np.dot(d_old, cyl.d)) > 0 else -cyl.d
                return self.line_from(gp_Lin(gp_Pnt(*pf), gp_Dir(*dvec)), pf, pl, e.id)
        raise PushPullError("GEOM_CAD_FAILED", f"edge E{e.id}: unsupported surface pair {sorted(kinds)} for a moved face")

    @staticmethod
    def old_direction(ad) -> np.ndarray:
        if ad.GetType() == GeomAbs_Line:
            return _dir(ad.Line().Direction())
        return _xyz(ad.Value(ad.LastParameter())) - _xyz(ad.Value(ad.FirstParameter()))

    def edge_vertices(self, E) -> tuple[int, int]:
        vf = vl = None
        it = TopoDS_Iterator(E, False, True)
        while it.More():
            c = it.Value()
            k = self.b._vmap.FindIndex(c)
            if c.Orientation() == TopAbs_FORWARD:
                vf = k
            elif c.Orientation() == TopAbs_REVERSED:
                vl = k
            it.Next()
        if vf is None or vl is None:
            raise PushPullError("GEOM_CAD_FAILED", "edge without FORWARD/REVERSED vertices is not supported")
        return vf, vl

    def line_from(self, lin: gp_Lin, pf, pl, eid):
        u1 = ElCLib.Parameter_s(lin, gp_Pnt(*pf))
        u2 = ElCLib.Parameter_s(lin, gp_Pnt(*pl))
        for p in (pf, pl):
            if lin.Distance(gp_Pnt(*p)) > ON_TOL:
                raise PushPullError("GEOM_CAD_FAILED", f"edge E{eid}: recomputed vertex is off the new edge line")
        if u2 - u1 <= TOL:
            raise PushPullError("GEOM_TOPOLOGY_CHANGED", f"edge E{eid} collapsed or reversed (length {u2 - u1:.3g} mm)")
        return Geom_Line(lin), u1, u2, "LINE"

    def circle_from(self, circ: gp_Circ, pf, pl, closed, eid, ad_old):
        for p in (pf, pl):
            if circ.Distance(gp_Pnt(*p)) > ON_TOL:
                raise PushPullError("GEOM_CAD_FAILED", f"edge E{eid}: recomputed vertex is off the new edge circle")
        u1 = ElCLib.Parameter_s(circ, gp_Pnt(*pf))
        if closed:
            span_old = ad_old.LastParameter() - ad_old.FirstParameter()
            return Geom_Circle(circ), u1, u1 + span_old, "CIRCLE"
        u2 = ElCLib.Parameter_s(circ, gp_Pnt(*pl))
        while u2 <= u1 + 1e-12:
            u2 += TWO_PI
        span_old = ad_old.LastParameter() - ad_old.FirstParameter()
        if abs((u2 - u1) - span_old) > 0.5 * math.pi:
            raise PushPullError("GEOM_TOPOLOGY_CHANGED", f"edge E{eid}: arc span changed from {math.degrees(span_old):.1f} to {math.degrees(u2 - u1):.1f} deg")
        return Geom_Circle(circ), u1, u2, "CIRCLE"

    def generic_params(self, c, pf, pl, closed, eid, ad_old):
        def par(p):
            pr = GeomAPI_ProjectPointOnCurve(gp_Pnt(*p), c)
            if pr.NbPoints() == 0 or pr.LowerDistance() > ON_TOL:
                raise PushPullError("GEOM_CAD_FAILED", f"edge E{eid}: recomputed vertex is off the edge curve")
            return pr.LowerDistanceParameter()

        u1 = par(pf)
        span_old = ad_old.LastParameter() - ad_old.FirstParameter()
        if closed:
            return c, u1, u1 + span_old, "OTHER"
        u2 = par(pl)
        if c.IsPeriodic():
            while u2 <= u1:
                u2 += c.Period()
        if u2 <= u1:
            raise PushPullError("GEOM_TOPOLOGY_CHANGED", f"edge E{eid} reversed")
        return c, u1, u2, "OTHER"

    # ---- pcurves
    def pcurves(self, eid: int, fid: int, curve, u1: float, u2: float, kind: str):
        """Return [(pcurve, orientation or None)] for the new edge on the new face."""
        b = self.b
        s = self.surf[fid - 1]
        E_old = b._edges[eid - 1]
        F_old = b._faces[fid - 1]
        e = self.topo.edge(eid)
        if eid in self.translated_old and fid not in self.uv_changed and s.kind != "CYLINDER":
            # rigidly moved (or unchanged) edge: the 3D curve is the translated old curve with the same
            # parametrization and the surface keeps its (u,v), so the old pcurves stay exact as long as
            # their domain covers the new range (bounded B-spline pcurves may not)
            F_fwd = TopoDS.Face_s(F_old.Oriented(TopAbs_FORWARD))
            ors = (TopAbs_FORWARD, TopAbs_REVERSED) if e.convexity == "SEAM" else (None,)
            olds = []
            for o in ors:
                E = TopoDS.Edge_s(E_old.Oriented(o)) if o is not None else E_old
                c = BRep_Tool.CurveOnSurface_s(E, F_fwd, 0.0, 0.0)
                if c is None or c.FirstParameter() > u1 + 1e-9 or c.LastParameter() < u2 - 1e-9:
                    olds = None
                    break
                olds.append((c, o))
            if olds:
                return olds
        if s.kind == "PLANE":
            if isinstance(s.geom, Geom_Plane):
                return [(GeomProjLib.Curve2d_s(curve, u1, u2, s.geom), None)]
            return [(_pcurve_by_sampling(curve, u1, u2, s.geom, eid), None)]
        if s.kind == "CYLINDER":
            if e.convexity == "SEAM":
                out = []
                for ori in (TopAbs_FORWARD, TopAbs_REVERSED):
                    uref = self.old_pcurve_mid_u(TopoDS.Edge_s(E_old.Oriented(ori)), TopoDS.Face_s(F_old.Oriented(TopAbs_FORWARD)))
                    out.append((self.cyl_pcurve(s, curve, u1, u2, kind, uref), ori))
                return out
            uref = self.old_pcurve_mid_u(E_old, F_old)
            return [(self.cyl_pcurve(s, curve, u1, u2, kind, uref), None)]
        # other surfaces (only translated)
        return [(_pcurve_by_sampling(curve, u1, u2, s.geom, eid), None)]

    @staticmethod
    def old_pcurve_mid_u(E, F) -> float:
        a = BRepAdaptor_Curve2d(E, F)
        return a.Value(0.5 * (a.FirstParameter() + a.LastParameter())).X()

    @staticmethod
    def cyl_pcurve(s: _Surf, curve, u1, u2, kind, uref):
        if kind == "LINE":
            lin = curve.Lin()
            p0 = _xyz(lin.Location())
            dv = _dir(lin.Direction())
            th = s.angle(p0)
            th += TWO_PI * round((uref - th) / TWO_PI)
            v0 = float(np.dot(p0 - s.a, s.d))
            sg = 1.0 if float(np.dot(dv, s.d)) > 0 else -1.0
            return Geom2d_Line(gp_Pnt2d(th, v0), gp_Dir2d(0.0, sg))
        if kind == "CIRCLE":
            circ = curve.Circ()
            c = _xyz(circ.Location())
            xc = _dir(circ.XAxis().Direction())
            yc = _dir(circ.YAxis().Direction())
            th0 = math.atan2(float(np.dot(xc, s.y)), float(np.dot(xc, s.x)))
            tang = -math.sin(th0) * s.x + math.cos(th0) * s.y
            sg = 1.0 if float(np.dot(yc, tang)) > 0 else -1.0
            v = float(np.dot(c - s.a, s.d))
            umid = th0 + sg * 0.5 * (u1 + u2)
            th0 += TWO_PI * round((uref - umid) / TWO_PI)
            return Geom2d_Line(gp_Pnt2d(th0, v), gp_Dir2d(sg, 0.0))
        raise PushPullError("GEOM_CAD_FAILED", "unsupported curve on a cylindrical face")

    # ---- topology
    def build(self) -> TopoDS_Solid:
        b = self.b
        B = BRep_Builder()
        nv = []
        for i in range(self.nv):
            V = TopoDS_Vertex()
            B.MakeVertex(V, gp_Pnt(*self.new_v[i]), TOL)
            nv.append(V)
        nf = []
        for i in range(self.nf):
            F = TopoDS_Face()
            B.MakeFace(F, self.surf[i].geom, TOL)
            B.NaturalRestriction(F, BRep_Tool.NaturalRestriction_s(b._faces[i]))
            nf.append(F)
        ne = []
        for e in self.topo.edges:
            E_old = b._edges[e.id - 1]
            curve, u1, u2, kind = self.edge_geom[e.id - 1]
            E = TopoDS_Edge()
            B.MakeEdge(E, curve, TOL)
            it = TopoDS_Iterator(E_old, False, True)
            while it.More():
                c = it.Value()
                k = b._vmap.FindIndex(c)
                B.Add(E, nv[k - 1].Oriented(c.Orientation()))
                it.Next()
            for f in e.faces:
                pcs = self.pcurves(e.id, f, curve, u1, u2, kind)
                if len(pcs) == 2:
                    B.UpdateEdge(E, pcs[0][0], pcs[1][0], nf[f - 1], TOL)
                else:
                    B.UpdateEdge(E, pcs[0][0], nf[f - 1], TOL)
            B.Range(E, u1, u2)
            B.SameRange(E, True)
            B.SameParameter(E, True)
            if BRep_Tool.Degenerated_s(E_old):
                B.Degenerated(E, True)
            ne.append(E)
        # wires: one new wire per old wire TShape (wires are shared by nothing else)
        for i in range(self.nf):
            F_old = b._faces[i]
            it = TopoDS_Iterator(F_old, False, True)
            while it.More():
                w_old = it.Value()
                if w_old.ShapeType() != TopAbs_WIRE:
                    raise PushPullError("GEOM_CAD_FAILED", "unexpected face child")
                W = TopoDS_Wire()
                B.MakeWire(W)
                it2 = TopoDS_Iterator(w_old, False, True)
                while it2.More():
                    c = it2.Value()
                    k = b._emap.FindIndex(c)
                    B.Add(W, ne[k - 1].Oriented(c.Orientation()))
                    it2.Next()
                W.Closed(w_old.Closed())
                B.Add(nf[i], W.Oriented(w_old.Orientation()))
                it.Next()
        S = TopoDS_Solid()
        B.MakeSolid(S)
        it = TopoDS_Iterator(b._solid, False, True)
        while it.More():
            sh_old = it.Value()
            if sh_old.ShapeType() != TopAbs_SHELL:
                raise PushPullError("GEOM_CAD_FAILED", "unexpected solid child")
            Sh = TopoDS_Shell()
            B.MakeShell(Sh)
            it2 = TopoDS_Iterator(sh_old, False, True)
            while it2.More():
                c = it2.Value()
                k = b._fmap.FindIndex(c)
                B.Add(Sh, nf[k - 1].Oriented(c.Orientation()))
                it2.Next()
            Sh.Closed(sh_old.Closed())
            B.Add(S, Sh.Oriented(sh_old.Orientation()))
            it.Next()
        return S.Oriented(b._solid.Orientation())


def push_pull(body, moves: dict[int, FaceMove]):
    """Return (new solid, uv-changed face ids) with the face moves applied; raises PushPullError."""
    rb = _Rebuild(body, moves)
    solid = rb.run()
    BRepLib.SameParameter_s(solid, TOL)
    if not BRepCheck_Analyzer(solid).IsValid():
        raise PushPullError("GEOM_CAD_FAILED", "rebuilt solid is not valid (BRepCheck)")
    if not BRepAlgoAPI_Check(solid, True, True).IsValid():
        raise PushPullError("GEOM_CAD_FAILED", "rebuilt solid self-intersects")
    return solid, rb.uv_changed


__all__ = ["PushPullError", "push_pull"]
