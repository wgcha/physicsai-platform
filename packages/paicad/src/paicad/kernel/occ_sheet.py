"""OCCT sheet (mid-surface) bodies for the shell path (shell-morph sections 4.1, 6.3, 6.4).

A sheet body is one ``TopoDS_Shell`` (faces sharing edges, no solid). ``OccSheet`` reuses the solid
adapter (``OccBody``) for projections/evaluation and overrides what needs a material side. The
topology-preserving rebuild (:meth:`OccSheet.rebuilt`) replaces the geometry of selected faces, edges
and vertices while keeping every sub-shape, its order and orientation, so the face map nominal ->
sample is the identity by construction (same idea as ``occ_push`` for solids).

Only this kernel subpackage imports OCP.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from OCP.BRep import BRep_Builder, BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Curve2d
from OCP.BRepBuilderAPI import BRepBuilderAPI_Sewing
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepGProp import BRepGProp
from OCP.BRepLib import BRepLib
from OCP.ElCLib import ElCLib
from OCP.GC import GC_MakeArcOfCircle, GC_MakeCircle
from OCP.Geom import (
    Geom_Circle,
    Geom_ConicalSurface,
    Geom_CylindricalSurface,
    Geom_Line,
    Geom_Plane,
    Geom_RectangularTrimmedSurface,
    Geom_SphericalSurface,
    Geom_ToroidalSurface,
    Geom_TrimmedCurve,
)
from OCP.Geom2d import Geom2d_BSplineCurve
from OCP.Geom2dAPI import Geom2dAPI_Interpolate
from OCP.GeomAbs import GeomAbs_Circle, GeomAbs_Line
from OCP.GeomProjLib import GeomProjLib
from OCP.gp import gp_Ax1, gp_Dir, gp_Lin, gp_Pnt, gp_Pnt2d, gp_Vec
from OCP.GProp import GProp_GProps
from OCP.ShapeAnalysis import ShapeAnalysis_Surface
from OCP.TColgp import TColgp_Array1OfPnt2d, TColgp_HArray1OfPnt2d
from OCP.TColStd import TColStd_Array1OfInteger, TColStd_Array1OfReal, TColStd_HArray1OfReal
from OCP.TopAbs import TopAbs_FACE, TopAbs_FORWARD, TopAbs_REVERSED, TopAbs_SHELL, TopAbs_SOLID, TopAbs_WIRE
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS, TopoDS_Compound, TopoDS_Edge, TopoDS_Face, TopoDS_Iterator, TopoDS_Shape, TopoDS_Shell, TopoDS_Vertex, TopoDS_Wire
from OCP.BRepTools import BRepTools

from .base import BodySummary, SurfaceEdit
from .occ import KernelError, OccBody, _bbox, _dir, _xyz

TOL = 1.0e-7
ON_TOL = 1.0e-6
TWO_PI = 2.0 * math.pi


# ------------------------------------------------------------------ loading
def _walk_xde(path: str | Path) -> list[tuple[str | None, object]]:
    """Leaf shapes of a STEP file with XDE names (assembly placements applied)."""
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.STEPCAFControl import STEPCAFControl_Reader
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDF import TDF_Label, TDF_LabelSequence
    from OCP.TDocStd import TDocStd_Document
    from OCP.TopLoc import TopLoc_Location
    from OCP.XCAFDoc import XCAFDoc_DocumentTool

    from .occ import _label_name

    doc = TDocStd_Document(TCollection_ExtendedString("XmlOcaf"))
    reader = STEPCAFControl_Reader()
    reader.SetNameMode(True)
    if reader.ReadFile(str(path)) != IFSelect_RetDone:
        raise KernelError("GEOM_INPUT_INVALID", f"cannot read STEP file: {Path(path).name}")
    if not reader.Transfer(doc):
        raise KernelError("GEOM_INPUT_INVALID", f"STEP transfer failed: {Path(path).name}")
    tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    free = TDF_LabelSequence()
    tool.GetFreeShapes(free)
    out: list[tuple[str | None, object]] = []

    def walk(label, loc, inherited: str | None):
        name = _label_name(label) or inherited
        if tool.IsReference_s(label):
            ref = TDF_Label()
            tool.GetReferredShape_s(label, ref)
            walk(ref, loc.Multiplied(tool.GetLocation_s(label)), name or _label_name(ref))
            return
        if tool.IsAssembly_s(label):
            comps = TDF_LabelSequence()
            tool.GetComponents_s(label, comps)
            start = len(out)
            for i in range(1, comps.Length() + 1):
                walk(comps.Value(i), loc, None)
            if name and len(out) == start + 1 and out[start][0] is None:
                out[start] = (name, out[start][1])
            return
        out.append((name, tool.GetShape_s(label).Moved(loc)))

    for i in range(1, free.Length() + 1):
        walk(free.Value(i), TopLoc_Location(), None)
    return out


def _count(shape, kind) -> int:
    n = 0
    exp = TopExp_Explorer(shape, kind)
    while exp.More():
        n += 1
        exp.Next()
    return n


def _sheet_of(shape, label: str):
    """One TopoDS_Shell from a leaf shape (faces without a shell are sewn), else SHELL_BODY_NOT_SHEET."""
    if _count(shape, TopAbs_SOLID):
        raise KernelError("SHELL_BODY_NOT_SHEET", f"{label}: body is a solid, a mid-surface (sheet) body is required")
    shells = []
    exp = TopExp_Explorer(shape, TopAbs_SHELL)
    while exp.More():
        shells.append(TopoDS.Shell_s(exp.Current()))
        exp.Next()
    if len(shells) == 1:
        return shells[0]
    if _count(shape, TopAbs_FACE) == 0:
        raise KernelError("SHELL_BODY_NOT_SHEET", f"{label}: body has no faces")
    sew = BRepBuilderAPI_Sewing(1.0e-6)
    exp = TopExp_Explorer(shape, TopAbs_FACE)
    while exp.More():
        sew.Add(exp.Current())
        exp.Next()
    sew.Perform()
    res = sew.SewedShape()
    shells = []
    exp = TopExp_Explorer(res, TopAbs_SHELL)
    while exp.More():
        shells.append(TopoDS.Shell_s(exp.Current()))
        exp.Next()
    if len(shells) != 1:
        raise KernelError("SHELL_BODY_NOT_SHEET", f"{label}: faces do not form one connected sheet ({len(shells)} shells)")
    return shells[0]


def load_sheet_step(path: str | Path) -> list["OccSheet"]:
    leaves = _walk_xde(path)
    if not leaves:
        raise KernelError("GEOM_INPUT_INVALID", f"no body in STEP file: {Path(path).name}")
    out = []
    for name, shape in leaves:
        out.append(OccSheet(name, _sheet_of(shape, name or Path(path).name)))
    return out


def load_sheet_parts_dir(folder: str | Path, extensions: tuple[str, ...] = (".step", ".stp")) -> list["OccSheet"]:
    files = sorted(p for p in Path(folder).iterdir() if p.is_file() and p.suffix.lower() in extensions)
    if not files:
        raise KernelError("GEOM_INPUT_INVALID", f"no STEP file in folder: {Path(folder).name}")
    out = []
    for f in files:
        leaves = _walk_xde(f)
        if len(leaves) != 1:
            raise KernelError("GEOM_INPUT_INVALID", f"{f.name}: expected exactly 1 sheet body, found {len(leaves)}")
        out.append(OccSheet(f.stem, _sheet_of(leaves[0][1], f.name)))
    return out


def load_sheet_brep(path: str | Path, names: list[str]) -> list["OccSheet"]:
    shape = TopoDS_Shape()
    if not BRepTools.Read_s(shape, str(path), BRep_Builder()) or shape.IsNull():
        raise KernelError("GEOM_INPUT_INVALID", f"cannot read BRep file: {Path(path).name}")
    shells = []
    it = TopoDS_Iterator(shape)
    while it.More():
        c = it.Value()
        if c.ShapeType() == TopAbs_SHELL:
            shells.append(TopoDS.Shell_s(c))
        it.Next()
    if len(shells) != len(names):
        raise KernelError("GEOM_INPUT_INVALID", f"{Path(path).name}: expected {len(names)} sheets, found {len(shells)}")
    return [OccSheet(n, s) for n, s in zip(names, shells)]


# ------------------------------------------------------------------ body
class OccSheet(OccBody):
    """One sheet body (shell). Public methods return neutral types only."""

    _bbox_optimal = False

    def summary(self) -> BodySummary:
        if self._summary is None:
            props = GProp_GProps()
            BRepGProp.SurfaceProperties_s(self._solid, props)
            free = sum(1 for e in self.topology().edges if len(e.faces) == 1 and e.convexity != "SEAM")
            self._summary = BodySummary(
                name=self.name or "",
                volume=0.0,
                bbox=_bbox(self._solid, False),
                n_faces=len(self._faces),
                n_edges=len(self._edges),
                n_vertices=len(self._verts),
                extra={"area": float(props.Mass()), "free_edges": free},
            )
        return self._summary

    def is_sheet(self) -> bool:
        return True

    def _convexity(self, edge, ad, flist):
        """Sheets have no material side: SMOOTH (tangent, < 1 deg) or UNKNOWN, with the dihedral angle."""
        if len(flist) != 2:
            return "UNKNOWN", None
        um = 0.5 * (ad.FirstParameter() + ad.LastParameter())
        p = _xyz(ad.Value(um))
        normals = []
        for fid in flist:
            f, sad, sas, _ = self._surf(fid)
            uv = sas.ValueOfUV(gp_Pnt(*p), 1e-7)
            _, n = self._normal_at(f, sad, uv.X(), uv.Y())
            normals.append(n)
        ang = math.degrees(math.acos(max(-1.0, min(1.0, float(np.dot(normals[0], normals[1]))))))
        return ("SMOOTH" if ang < 1.0 else "UNKNOWN"), 180.0 - ang

    def points_inside(self, pts: np.ndarray) -> np.ndarray:
        return np.zeros(len(np.asarray(pts).reshape(-1, 3)), dtype=bool)

    def surface_params(self, fid: int) -> dict:
        """Analytic parameters of the face surface in global coordinates (frame as stored, not face-oriented)."""
        s = BRep_Tool.Surface_s(self._faces[fid - 1])
        if isinstance(s, Geom_RectangularTrimmedSurface):
            s = s.BasisSurface()
        out: dict = {"kind": "OTHER"}
        if isinstance(s, Geom_Plane):
            ax = s.Position()
            out = {"kind": "PLANE"}
        elif isinstance(s, Geom_CylindricalSurface):
            ax = s.Position()
            out = {"kind": "CYLINDER", "radius": float(s.Radius())}
        elif isinstance(s, Geom_ConicalSurface):
            ax = s.Position()
            out = {"kind": "CONE", "radius": float(s.RefRadius()), "semi_angle": float(s.SemiAngle())}
        elif isinstance(s, Geom_ToroidalSurface):
            ax = s.Position()
            out = {"kind": "TORUS", "radius": float(s.MajorRadius()), "minor_radius": float(s.MinorRadius())}
        elif isinstance(s, Geom_SphericalSurface):
            ax = s.Position()
            out = {"kind": "SPHERE", "radius": float(s.Radius())}
        else:
            return out
        out["location"] = _xyz(ax.Location())
        out["axis"] = _dir(ax.Direction())
        out["xdir"] = _dir(ax.XDirection())
        return out

    def rebuilt(self, face_edits: dict[int, SurfaceEdit], edge_points: dict[int, np.ndarray], vertex_pos: dict[int, np.ndarray]) -> "OccSheet":
        try:
            shell = _SheetRebuild(self, face_edits, edge_points, vertex_pos).run()
        except KernelError:
            raise
        except Exception as e:  # OCCT exceptions -> CAD failure, never a crash
            raise KernelError("GEOM_CAD_FAILED", f"OCCT error during sheet rebuild: {e.__class__.__name__}: {e}") from None
        nb = OccSheet(self.name, shell)
        if (len(nb._faces), len(nb._edges), len(nb._verts)) != (len(self._faces), len(self._edges), len(self._verts)):
            raise KernelError(
                "GEOM_TOPOLOGY_CHANGED",
                f"topology changed: faces {len(self._faces)}->{len(nb._faces)}, edges {len(self._edges)}->{len(nb._edges)}",
            )
        return nb


# ------------------------------------------------------------------ rebuild
def _base_surface(face):
    s = BRep_Tool.Surface_s(face)
    if isinstance(s, Geom_RectangularTrimmedSurface):
        s = s.BasisSurface()
    return s


def _edited_surface(face, ed: SurfaceEdit):
    s = _base_surface(face)
    g = s.Copy()
    if ed.rotate_axis is not None and ed.rotate_angle != 0.0:
        p = ed.rotate_point if ed.rotate_point is not None else np.zeros(3)
        g.Rotate(gp_Ax1(gp_Pnt(*map(float, p)), gp_Dir(*map(float, ed.rotate_axis))), float(ed.rotate_angle))
    if ed.translate is not None and np.any(np.asarray(ed.translate) != 0):
        g.Translate(gp_Vec(*map(float, ed.translate)))
    if ed.radius is not None:
        r = float(ed.radius)
        if not (r > 0 and math.isfinite(r)):
            raise KernelError("GEOM_CAD_FAILED", f"invalid surface radius {r!r}")
        if isinstance(g, Geom_CylindricalSurface):
            g.SetRadius(r)
        elif isinstance(g, Geom_ToroidalSurface):
            if r <= g.MinorRadius():
                raise KernelError("GEOM_CAD_FAILED", "torus major radius would not exceed its minor radius")
            g.SetMajorRadius(r)
        elif isinstance(g, Geom_ConicalSurface):
            g.SetRadius(r)
        else:
            raise KernelError("GEOM_CAD_FAILED", "radius change on a surface without a radius")
    if ed.semi_angle is not None:
        if not isinstance(g, Geom_ConicalSurface):
            raise KernelError("GEOM_CAD_FAILED", "semi-angle change on a non-conical surface")
        a = float(ed.semi_angle)
        if not (0.0 < abs(a) < 0.5 * math.pi - 1e-9):
            raise KernelError("GEOM_CAD_FAILED", f"invalid cone semi-angle {math.degrees(a):.3f} deg")
        g.SetSemiAngle(a)
    return g


def _bspline2d_line(p0: np.ndarray, p1: np.ndarray, u1: float, u2: float):
    poles = TColgp_Array1OfPnt2d(1, 2)
    poles.SetValue(1, gp_Pnt2d(float(p0[0]), float(p0[1])))
    poles.SetValue(2, gp_Pnt2d(float(p1[0]), float(p1[1])))
    knots = TColStd_Array1OfReal(1, 2)
    knots.SetValue(1, float(u1))
    knots.SetValue(2, float(u2))
    mult = TColStd_Array1OfInteger(1, 2)
    mult.SetValue(1, 2)
    mult.SetValue(2, 2)
    return Geom2d_BSplineCurve(poles, knots, mult, 1)


class _SheetRebuild:
    def __init__(self, body: OccSheet, face_edits, edge_points, vertex_pos):
        self.b = body
        self.topo = body.topology()
        self.face_edits = {int(k): v for k, v in face_edits.items()}
        self.edge_points = {int(k): np.asarray(v, dtype=float) for k, v in edge_points.items()}
        self.vertex_pos = {int(k): np.asarray(v, dtype=float) for k, v in vertex_pos.items()}

    # ---- geometry
    def surfaces(self):
        out = []
        for i, f in enumerate(self.b._faces, 1):
            ed = self.face_edits.get(i)
            out.append(_edited_surface(f, ed) if ed is not None else _base_surface(f))
        return out

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
            raise KernelError("GEOM_CAD_FAILED", "edge without FORWARD/REVERSED vertices is not supported")
        return vf, vl

    def new_edge_curve(self, eid: int):
        """(curve, u1, u2) of a changed edge from its mapped sample points."""
        E = self.b._edges[eid - 1]
        _, ad, _, _, _ = self.b._curve(eid)
        pts = self.edge_points[eid]
        vf, vl = self.edge_vertices(E)
        closed = vf == vl
        kind = ad.GetType()
        if kind == GeomAbs_Line:
            p0, p1 = pts[0], pts[-1]
            d = p1 - p0
            ln = float(np.linalg.norm(d))
            if ln <= TOL:
                raise KernelError("GEOM_TOPOLOGY_CHANGED", f"edge E{eid} collapsed (length {ln:.3g} mm)")
            lin = gp_Lin(gp_Pnt(*p0), gp_Dir(*(d / ln)))
            for p in pts:
                if lin.Distance(gp_Pnt(*p)) > ON_TOL:
                    raise KernelError("GEOM_CAD_FAILED", f"edge E{eid}: mapped points are not collinear")
            return Geom_Line(lin), 0.0, ln
        if kind == GeomAbs_Circle:
            if closed:
                mk = GC_MakeCircle(gp_Pnt(*pts[0]), gp_Pnt(*pts[1]), gp_Pnt(*pts[2]))
                if not mk.IsDone():
                    raise KernelError("GEOM_CAD_FAILED", f"edge E{eid}: circle through mapped points failed")
                c = mk.Value()
                circ = c.Circ()
                u1 = ElCLib.Parameter_s(circ, gp_Pnt(*pts[0]))
                um = ElCLib.Parameter_s(circ, gp_Pnt(*pts[1]))
                if ((um - u1) % TWO_PI) > math.pi:  # 1/3 point must come first: keep the old orientation
                    c = Geom_Circle(circ.Reversed())
                    u1 = ElCLib.Parameter_s(c.Circ(), gp_Pnt(*pts[0]))
                return c, u1, u1 + TWO_PI
            mk = GC_MakeArcOfCircle(gp_Pnt(*pts[0]), gp_Pnt(*pts[1]), gp_Pnt(*pts[2]))
            if not mk.IsDone():
                raise KernelError("GEOM_CAD_FAILED", f"edge E{eid}: arc through mapped points failed")
            tc: Geom_TrimmedCurve = mk.Value()
            return tc.BasisCurve(), tc.FirstParameter(), tc.LastParameter()
        raise KernelError("GEOM_CAD_FAILED", f"edge E{eid}: only line and circle edges can change (sheet rebuild)")

    def old_curve(self, eid: int):
        E = self.b._edges[eid - 1]
        c = BRep_Tool.Curve_s(E, 0.0, 0.0)  # with the edge location applied
        u1, u2 = BRep_Tool.Range_s(E)
        if c is None:
            raise KernelError("GEOM_CAD_FAILED", f"edge E{eid} has no 3D curve")
        return c, u1, u2

    @staticmethod
    def _old_mid_uv(E, F) -> np.ndarray:
        a = BRepAdaptor_Curve2d(E, F)
        p = a.Value(0.5 * (a.FirstParameter() + a.LastParameter()))
        return np.array([p.X(), p.Y()])

    def pcurve(self, eid: int, curve, u1: float, u2: float, surf, ref_uv: np.ndarray):
        if isinstance(surf, Geom_Plane):
            return GeomProjLib.Curve2d_s(curve, u1, u2, surf)
        sas = ShapeAnalysis_Surface(surf)
        n = 9
        ts = np.linspace(u1, u2, n)
        uv = np.zeros((n, 2))
        for i, t in enumerate(ts):
            p = sas.ValueOfUV(curve.Value(float(t)), 1e-10)
            if sas.Gap() > ON_TOL:
                raise KernelError("GEOM_CAD_FAILED", f"edge E{eid}: curve leaves its face surface (gap {sas.Gap():.3g} mm)")
            uv[i] = (p.X(), p.Y())
        per = [surf.IsUPeriodic(), surf.IsVPeriodic()]
        period = [surf.UPeriod() if per[0] else 0.0, surf.VPeriod() if per[1] else 0.0]
        for k in (0, 1):
            if per[k]:
                uv[:, k] = np.unwrap(uv[:, k], period=period[k])
                mid = uv[n // 2, k]
                uv[:, k] += period[k] * round((ref_uv[k] - mid) / period[k])
        # linear in the curve parameter -> exact degree-1 pcurve with the same parameter
        lin = uv[0] + (uv[-1] - uv[0]) * ((ts - u1) / (u2 - u1))[:, None]
        if float(np.abs(lin - uv).max()) <= 1e-9 * (1.0 + float(np.abs(uv).max())):
            return _bspline2d_line(uv[0], uv[-1], u1, u2)
        m = 25
        ts2 = np.linspace(u1, u2, m)
        pts = TColgp_HArray1OfPnt2d(1, m)
        par = TColStd_HArray1OfReal(1, m)
        prev = None
        for i, t in enumerate(ts2):
            p = sas.ValueOfUV(curve.Value(float(t)), 1e-10)
            q = np.array([p.X(), p.Y()])
            for k in (0, 1):
                if per[k]:
                    ref = prev[k] if prev is not None else uv[0, k]
                    q[k] += period[k] * round((ref - q[k]) / period[k])
            prev = q
            pts.SetValue(i + 1, gp_Pnt2d(float(q[0]), float(q[1])))
            par.SetValue(i + 1, float(t))
        it = Geom2dAPI_Interpolate(pts, par, False, 1e-12)
        it.Perform()
        if not it.IsDone():
            raise KernelError("GEOM_CAD_FAILED", f"edge E{eid}: pcurve construction failed")
        return it.Curve()

    def run(self):
        b = self.b
        topo = self.topo
        surfs = self.surfaces()
        B = BRep_Builder()
        nv = []
        for i in range(len(b._verts)):
            V = TopoDS_Vertex()
            p = self.vertex_pos.get(i + 1, topo.vertices[i])
            B.MakeVertex(V, gp_Pnt(*map(float, p)), TOL)
            nv.append(V)
        nf = []
        for i in range(len(b._faces)):
            F = TopoDS_Face()
            B.MakeFace(F, surfs[i], TOL)
            B.NaturalRestriction(F, BRep_Tool.NaturalRestriction_s(b._faces[i]))
            nf.append(F)
        ne = []
        for e in topo.edges:
            E_old = b._edges[e.id - 1]
            changed = e.id in self.edge_points
            if changed:
                curve, u1, u2 = self.new_edge_curve(e.id)
            else:
                curve, u1, u2 = self.old_curve(e.id)
                vf, vl = self.edge_vertices(E_old)
                for v, u in ((vf, u1), (vl, u2)):
                    if v in self.vertex_pos and float(np.linalg.norm(_xyz(curve.Value(u)) - self.vertex_pos[v])) > ON_TOL:
                        raise KernelError("GEOM_CAD_FAILED", f"edge E{e.id}: vertex V{v} moves but the edge is unchanged")
            E = TopoDS_Edge()
            B.MakeEdge(E, curve, TOL)
            it = TopoDS_Iterator(E_old, False, True)
            while it.More():
                c = it.Value()
                k = b._vmap.FindIndex(c)
                B.Add(E, nv[k - 1].Oriented(c.Orientation()))
                it.Next()
            for fid in e.faces:
                F_old = b._faces[fid - 1]
                F_fwd = TopoDS.Face_s(F_old.Oriented(TopAbs_FORWARD))
                seam = BRep_Tool.IsClosed_s(E_old, F_old)
                ors = (TopAbs_FORWARD, TopAbs_REVERSED) if seam else (None,)
                pcs = []
                for o in ors:
                    Eo = TopoDS.Edge_s(E_old.Oriented(o)) if o is not None else E_old
                    if not changed and fid not in self.face_edits:
                        c2 = BRep_Tool.CurveOnSurface_s(Eo, F_fwd, 0.0, 0.0)
                        if c2 is None:
                            raise KernelError("GEOM_CAD_FAILED", f"edge E{e.id} has no pcurve on F{fid}")
                        pcs.append(c2)
                    else:
                        pcs.append(self.pcurve(e.id, curve, u1, u2, surfs[fid - 1], self._old_mid_uv(Eo, F_fwd)))
                if len(pcs) == 2:
                    B.UpdateEdge(E, pcs[0], pcs[1], nf[fid - 1], TOL)
                else:
                    B.UpdateEdge(E, pcs[0], nf[fid - 1], TOL)
            B.Range(E, u1, u2)
            B.SameRange(E, True)
            B.SameParameter(E, True)
            if BRep_Tool.Degenerated_s(E_old):
                B.Degenerated(E, True)
            ne.append(E)
        for i in range(len(b._faces)):
            it = TopoDS_Iterator(b._faces[i], False, True)
            while it.More():
                w_old = it.Value()
                if w_old.ShapeType() != TopAbs_WIRE:
                    raise KernelError("GEOM_CAD_FAILED", "unexpected face child")
                W = TopoDS_Wire()
                B.MakeWire(W)
                it2 = TopoDS_Iterator(w_old, False, True)
                while it2.More():
                    c = it2.Value()
                    B.Add(W, ne[b._emap.FindIndex(c) - 1].Oriented(c.Orientation()))
                    it2.Next()
                W.Closed(w_old.Closed())
                B.Add(nf[i], W.Oriented(w_old.Orientation()))
                it.Next()
        Sh = TopoDS_Shell()
        B.MakeShell(Sh)
        it = TopoDS_Iterator(b._solid, False, True)
        while it.More():
            c = it.Value()
            B.Add(Sh, nf[b._fmap.FindIndex(c) - 1].Oriented(c.Orientation()))
            it.Next()
        Sh.Closed(b._solid.Closed())
        Sh = TopoDS.Shell_s(Sh.Oriented(b._solid.Orientation()))
        BRepLib.SameParameter_s(Sh, TOL)
        if not BRepCheck_Analyzer(Sh).IsValid():
            raise KernelError("GEOM_CAD_FAILED", "rebuilt sheet is not valid (BRepCheck)")
        return Sh


def write_sheet_brep(bodies: list[OccSheet], path: str | Path) -> None:
    comp = TopoDS_Compound()
    bld = BRep_Builder()
    bld.MakeCompound(comp)
    for b in bodies:
        bld.Add(comp, b._solid)
    if not BRepTools.Write_s(comp, str(path)):
        raise KernelError("GEOM_INTERNAL", f"cannot write BRep file: {Path(path).name}")


__all__ = ["OccSheet", "load_sheet_brep", "load_sheet_parts_dir", "load_sheet_step", "write_sheet_brep"]
