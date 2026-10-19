"""OCCT (OCP) implementation of the kernel boundary (contract section 18.9).

This is the only module tree allowed to import OCP. Public functions/methods return
neutral types only (see ``paicad.kernel.base``).
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import numpy as np
from OCP.Bnd import Bnd_Box
from OCP.BRep import BRep_Builder, BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
from OCP.BRepClass import BRepClass_FaceClassifier
from OCP.BRepClass3d import BRepClass3d_SolidClassifier
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.BRepGProp import BRepGProp
from OCP.BRepLProp import BRepLProp_SLProps
from OCP.BRepTools import BRepTools
from OCP.Extrema import Extrema_ExtPC
from OCP.GCPnts import GCPnts_AbscissaPoint
from OCP.GeomAbs import (
    GeomAbs_Circle,
    GeomAbs_Cone,
    GeomAbs_Cylinder,
    GeomAbs_Ellipse,
    GeomAbs_Line,
    GeomAbs_Plane,
    GeomAbs_Sphere,
    GeomAbs_Torus,
)
from OCP.GeomLib import GeomLib_IsPlanarSurface
from OCP.gp import gp_Pnt, gp_Pnt2d
from OCP.GProp import GProp_GProps
from OCP.IFSelect import IFSelect_RetDone
from OCP.ShapeAnalysis import ShapeAnalysis_Surface
from OCP.STEPCAFControl import STEPCAFControl_Reader
from OCP.TCollection import TCollection_ExtendedString
from OCP.TDataStd import TDataStd_Name
from OCP.TDF import TDF_Label, TDF_LabelSequence
from OCP.TDocStd import TDocStd_Document
from OCP.TopAbs import (
    TopAbs_EDGE,
    TopAbs_FACE,
    TopAbs_IN,
    TopAbs_ON,
    TopAbs_REVERSED,
    TopAbs_SOLID,
    TopAbs_VERTEX,
    TopAbs_WIRE,
)
from OCP.TopExp import TopExp, TopExp_Explorer
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS, TopoDS_Compound, TopoDS_Shape
from OCP.TopTools import (
    TopTools_IndexedDataMapOfShapeListOfShape,
    TopTools_IndexedMapOfShape,
)
from OCP.XCAFDoc import XCAFDoc_DocumentTool

from .base import BodySummary, EdgeData, FaceData, FaceMove, Topology


class KernelError(Exception):
    """Raised by the kernel for unreadable/invalid CAD input. ``code`` is a contract failure code."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def ocp_version() -> str:
    try:
        from importlib.metadata import version

        return version("cadquery-ocp")
    except Exception:  # pragma: no cover - metadata missing
        return "unknown"


def occt_version() -> str:
    try:
        from OCP.Standard import Standard_Version  # type: ignore

        return str(Standard_Version.String_s())
    except Exception:
        return "unknown"


_AUTO_NAME = re.compile(r"^=>\[[0-9:]+\]$")


def _label_name(label) -> str | None:
    attr = TDataStd_Name()
    if label.FindAttribute(TDataStd_Name.GetID_s(), attr):
        s = attr.Get().ToExtString()
        if s and not _AUTO_NAME.match(s) and s.strip():
            return s.strip()
    return None


def _solids(shape) -> list:
    out = []
    exp = TopExp_Explorer(shape, TopAbs_SOLID)
    while exp.More():
        out.append(TopoDS.Solid_s(exp.Current()))
        exp.Next()
    return out


def read_step_bodies(path: str | Path) -> list[tuple[str | None, object]]:
    """Read a STEP file with XDE names. Returns [(name|None, solid)] in document order (internal use)."""
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

    def leaf(name, shape):
        solids = _solids(shape)
        if len(solids) == 1:
            out.append((name, solids[0]))
        else:
            for k, s in enumerate(solids, 1):
                out.append((f"{name}_{k}" if name else None, s))

    def walk(label, loc: TopLoc_Location):
        name = _label_name(label)
        if tool.IsReference_s(label):
            ref = TDF_Label()
            tool.GetReferredShape_s(label, ref)
            loc2 = loc.Multiplied(tool.GetLocation_s(label))
            nm = name or _label_name(ref)
            if tool.IsAssembly_s(ref):
                comps = TDF_LabelSequence()
                tool.GetComponents_s(ref, comps)
                start = len(out)
                for i in range(1, comps.Length() + 1):
                    walk(comps.Value(i), loc2)
                if nm and len(out) == start + 1:
                    out[start] = (nm, out[start][1])  # sub-assembly holding one solid: the sub-assembly name wins
            else:
                leaf(nm, tool.GetShape_s(ref).Moved(loc2))
            return
        if tool.IsAssembly_s(label):
            comps = TDF_LabelSequence()
            tool.GetComponents_s(label, comps)
            for i in range(1, comps.Length() + 1):
                walk(comps.Value(i), loc)
            return
        leaf(name, tool.GetShape_s(label).Moved(loc))

    for i in range(1, free.Length() + 1):
        walk(free.Value(i), TopLoc_Location())
    if not out:
        raise KernelError("GEOM_INPUT_INVALID", f"no solid body in STEP file: {Path(path).name}")
    return out


def load_step(path: str | Path) -> list[OccBody]:
    """Single STEP (multi-body). Bodies keep XDE names; unnamed bodies get name None -> caller decides."""
    return [OccBody(name, solid) for name, solid in read_step_bodies(path)]


def load_parts_dir(folder: str | Path, extensions: tuple[str, ...] = (".step", ".stp")) -> list[OccBody]:
    """Per-component STEP files: exactly one solid per file, body name = file stem."""
    files = sorted(p for p in Path(folder).iterdir() if p.is_file() and p.suffix.lower() in extensions)
    if not files:
        raise KernelError("GEOM_INPUT_INVALID", f"no STEP file in folder: {Path(folder).name}")
    bodies = []
    for f in files:
        items = read_step_bodies(f)
        if len(items) != 1:
            raise KernelError("GEOM_INPUT_INVALID", f"{f.name}: expected exactly 1 solid, found {len(items)}")
        bodies.append(OccBody(f.stem, items[0][1]))
    return bodies


def _bbox(shape, optimal: bool = True) -> np.ndarray:
    box = Bnd_Box()
    if optimal:
        BRepBndLib.AddOptimal_s(shape, box, False, False)
    else:
        BRepBndLib.Add_s(shape, box)
    if box.IsVoid():
        return np.zeros(6)
    return np.array(box.Get(), dtype=float)


def _xyz(p) -> np.ndarray:
    return np.array([p.X(), p.Y(), p.Z()], dtype=float)


def _dir(d) -> np.ndarray:
    return np.array([d.X(), d.Y(), d.Z()], dtype=float)


_SURF = {GeomAbs_Plane: "PLANE", GeomAbs_Cylinder: "CYLINDER", GeomAbs_Cone: "CONE", GeomAbs_Sphere: "SPHERE", GeomAbs_Torus: "TORUS"}
_CURV = {GeomAbs_Line: "LINE", GeomAbs_Circle: "CIRCLE", GeomAbs_Ellipse: "ELLIPSE"}


class OccBody:
    """One solid. Holds OCP objects privately; every public method returns neutral types."""

    _bbox_optimal = True  # sub-shape boxes: optimal (solids) / fast enclosing boxes (sheets, candidate filters only)

    def __init__(self, name: str | None, solid):
        self.name = name  # may be None for unnamed XDE bodies (caller reports GEOM_BODY_MAP_FAILED)
        self._solid = solid
        self._fmap = TopTools_IndexedMapOfShape()
        self._emap = TopTools_IndexedMapOfShape()
        self._vmap = TopTools_IndexedMapOfShape()
        TopExp.MapShapes_s(solid, TopAbs_FACE, self._fmap)
        TopExp.MapShapes_s(solid, TopAbs_EDGE, self._emap)
        TopExp.MapShapes_s(solid, TopAbs_VERTEX, self._vmap)
        self._faces = [TopoDS.Face_s(self._fmap.FindKey(i)) for i in range(1, self._fmap.Extent() + 1)]
        self._edges = [TopoDS.Edge_s(self._emap.FindKey(i)) for i in range(1, self._emap.Extent() + 1)]
        self._verts = [TopoDS.Vertex_s(self._vmap.FindKey(i)) for i in range(1, self._vmap.Extent() + 1)]
        self._topo: Topology | None = None
        self._summary: BodySummary | None = None
        self._surf_cache: dict[int, tuple] = {}
        self._curve_cache: dict[int, tuple] = {}
        self.uv_changed: set[int] = set()  # faces whose (u,v) parametrization differs from the nominal (push/pull)

    # ---------------- summary / topology ----------------
    def summary(self) -> BodySummary:
        if self._summary is None:
            props = GProp_GProps()
            BRepGProp.VolumeProperties_s(self._solid, props)
            self._summary = BodySummary(
                name=self.name or "",
                volume=float(props.Mass()),
                bbox=_bbox(self._solid),
                n_faces=len(self._faces),
                n_edges=len(self._edges),
                n_vertices=len(self._verts),
            )
        return self._summary

    def _face_index(self, shape) -> int:
        return self._fmap.FindIndex(shape)

    def _edge_index(self, shape) -> int:
        return self._emap.FindIndex(shape)

    def _wire_edges(self, wire) -> tuple[int, ...]:
        ids = []
        exp = TopExp_Explorer(wire, TopAbs_EDGE)
        while exp.More():
            k = self._edge_index(exp.Current())
            if k not in ids:
                ids.append(k)
            exp.Next()
        return tuple(ids)

    def topology(self) -> Topology:
        if self._topo is not None:
            return self._topo
        e2f = TopTools_IndexedDataMapOfShapeListOfShape()
        TopExp.MapShapesAndAncestors_s(self._solid, TopAbs_EDGE, TopAbs_FACE, e2f)
        faces = [self._face_data(i + 1) for i in range(len(self._faces))]
        verts = np.array([_xyz(BRep_Tool.Pnt_s(v)) for v in self._verts], dtype=float).reshape(-1, 3)
        edges = []
        for i, e in enumerate(self._edges, 1):
            flist = []
            if e2f.Contains(e):
                for f in e2f.FindFromKey(e):
                    k = self._face_index(f)
                    if k not in flist:
                        flist.append(k)
            vids = []
            exp = TopExp_Explorer(e, TopAbs_VERTEX)
            while exp.More():
                k = self._vmap.FindIndex(exp.Current())
                if k not in vids:
                    vids.append(k)
                exp.Next()
            ad = BRepAdaptor_Curve(e)
            ctype = _CURV.get(ad.GetType(), "OTHER")
            length = float(GCPnts_AbscissaPoint.Length_s(ad))
            seam = len(flist) == 1 and BRep_Tool.IsClosed_s(e, self._faces[flist[0] - 1])
            conv, dih = ("SEAM", None) if seam else self._convexity(e, ad, flist)
            edges.append(
                EdgeData(id=i, curve=ctype, length=length, vertices=tuple(vids), faces=tuple(sorted(flist)), convexity=conv, bbox=_bbox(e, self._bbox_optimal), dihedral_deg=dih)
            )
        self._topo = Topology(faces=tuple(faces), edges=tuple(edges), vertices=verts)
        return self._topo

    def _face_data(self, fid: int) -> FaceData:
        f = self._faces[fid - 1]
        props = GProp_GProps()
        BRepGProp.SurfaceProperties_s(f, props)
        area = float(props.Mass())
        centroid = _xyz(props.CentreOfMass())
        ad = BRepAdaptor_Surface(f)
        st = ad.GetType()
        kind = _SURF.get(st, "OTHER")
        umin, umax, vmin, vmax = BRepTools.UVBounds_s(f)
        outer = BRepTools.OuterWire_s(f)
        outer_ids = self._wire_edges(outer) if not outer.IsNull() else ()
        inner = []
        exp = TopExp_Explorer(f, TopAbs_WIRE)
        while exp.More():
            w = TopoDS.Wire_s(exp.Current())
            if outer.IsNull() or not w.IsSame(outer):
                inner.append(self._wire_edges(w))
            exp.Next()
        all_edges = []
        for ids in [outer_ids, *inner]:
            for k in ids:
                if k not in all_edges:
                    all_edges.append(k)
        kw: dict = {}
        reversed_ = f.Orientation() == TopAbs_REVERSED
        if kind == "OTHER" and GeomLib_IsPlanarSurface(BRep_Tool.Surface_s(f), 1e-6).IsPlanar():
            kind = "PLANE"  # planar B-spline (e.g. ruled/lofted flat face) is treated as a plane
        if kind == "PLANE":
            if st == GeomAbs_Plane:
                n = _dir(ad.Plane().Axis().Direction())
                kw["normal"] = -n if reversed_ else n
            else:
                _, n = self._normal_at(f, ad, 0.5 * (umin + umax), 0.5 * (vmin + vmax))
                kw["normal"] = n / np.linalg.norm(n)
        elif kind in ("CYLINDER", "CONE", "TORUS", "SPHERE"):
            if kind == "CYLINDER":
                g = ad.Cylinder()
                kw["radius"] = float(g.Radius())
            elif kind == "CONE":
                g = ad.Cone()
                kw["radius"] = float(g.RefRadius())
            elif kind == "TORUS":
                g = ad.Torus()
                kw["radius"] = float(g.MajorRadius())
                kw["minor_radius"] = float(g.MinorRadius())
            else:
                g = ad.Sphere()
                kw["radius"] = float(g.Radius())
            ax = g.Position()
            kw["axis_point"] = _xyz(ax.Location())
            kw["axis_dir"] = _dir(ax.Direction())
            kw["span_deg"] = float(math.degrees(umax - umin))
            # concavity: outward normal at the face center vs. radial direction
            u0, v0 = 0.5 * (umin + umax), 0.5 * (vmin + vmax)
            p, n = self._normal_at(f, ad, u0, v0)
            if kind == "TORUS":
                # radial w.r.t. the tube center circle
                a, d = kw["axis_point"], kw["axis_dir"]
                r = p - a
                r_pl = r - np.dot(r, d) * d
                c = a + r_pl / (np.linalg.norm(r_pl) or 1.0) * kw["radius"]
                radial = p - c
            elif kind == "SPHERE":
                radial = p - kw["axis_point"]
            else:
                a, d = kw["axis_point"], kw["axis_dir"]
                r = p - a
                radial = r - np.dot(r, d) * d
            kw["concave"] = bool(np.dot(radial, n) < 0)
        return FaceData(
            id=fid,
            surface=kind,
            area=area,
            centroid=centroid,
            bbox=_bbox(f, self._bbox_optimal),
            edges=tuple(all_edges),
            outer_edges=outer_ids,
            inner_wires=tuple(inner),
            uv_bounds=(float(umin), float(umax), float(vmin), float(vmax)),
            **kw,
        )

    @staticmethod
    def _normal_at(face, ad: BRepAdaptor_Surface, u: float, v: float) -> tuple[np.ndarray, np.ndarray]:
        props = BRepLProp_SLProps(ad, u, v, 1, 1e-9)
        p = _xyz(props.Value())
        if props.IsNormalDefined():
            n = _dir(props.Normal())
        else:  # degenerate point; fall back to derivative cross product
            n = np.cross(_dir(props.D1U()), _dir(props.D1V()))
            nn = np.linalg.norm(n)
            n = n / nn if nn > 0 else np.array([0.0, 0.0, 1.0])
        if face.Orientation() == TopAbs_REVERSED:
            n = -n
        return p, n

    def _surf(self, fid: int):
        c = self._surf_cache.get(fid)
        if c is None:
            f = self._faces[fid - 1]
            surf = BRep_Tool.Surface_s(f)
            c = (f, BRepAdaptor_Surface(f), ShapeAnalysis_Surface(surf), BRepTools.UVBounds_s(f))
            self._surf_cache[fid] = c
        return c

    def _curve(self, eid: int):
        c = self._curve_cache.get(eid)
        if c is None:
            e = self._edges[eid - 1]
            ad = BRepAdaptor_Curve(e)
            u1, u2 = ad.FirstParameter(), ad.LastParameter()
            total = float(GCPnts_AbscissaPoint.Length_s(ad, u1, u2))
            c = (e, ad, u1, u2, total)
            self._curve_cache[eid] = c
        return c

    def _convexity(self, edge, ad: BRepAdaptor_Curve, flist: list[int]) -> tuple[str, float | None]:
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
        n1, n2 = normals
        ang = math.degrees(math.acos(max(-1.0, min(1.0, float(np.dot(n1, n2))))))
        if ang < 1.0:
            return "SMOOTH", 180.0 - ang
        d = n1 - n2
        d /= np.linalg.norm(d)
        bb = self.summary().bbox
        diag = float(np.linalg.norm(bb[3:] - bb[:3]))
        eps = min(1e-2, 1e-4 * diag + 1e-4)
        inside = bool(self.points_inside((p + eps * d)[None, :])[0])
        return ("CONCAVE" if inside else "CONVEX"), 180.0 - ang

    # ---------------- projections / evaluation ----------------
    def project_to_edge(self, edge_id: int, pts: np.ndarray):
        e, ad, u1, u2, total = self._curve(edge_id)
        pts = np.asarray(pts, dtype=float).reshape(-1, 3)
        n = len(pts)
        dist = np.full(n, np.inf)
        tt = np.zeros(n)
        foot = np.zeros((n, 3))
        p1, p2 = _xyz(ad.Value(u1)), _xyz(ad.Value(u2))
        for i, q in enumerate(pts):
            best_d, best_u = np.linalg.norm(q - p1), u1
            d2 = np.linalg.norm(q - p2)
            if d2 < best_d:
                best_d, best_u = d2, u2
            ext = Extrema_ExtPC(gp_Pnt(*q), ad, u1, u2)
            if ext.IsDone():
                for k in range(1, ext.NbExt() + 1):
                    dk = math.sqrt(ext.SquareDistance(k))
                    if dk < best_d:
                        best_d, best_u = dk, ext.Point(k).Parameter()
            dist[i] = best_d
            foot[i] = _xyz(ad.Value(best_u))
            if total > 0:
                tt[i] = float(GCPnts_AbscissaPoint.Length_s(ad, u1, best_u)) / total if best_u != u1 else 0.0
        return dist, np.clip(tt, 0.0, 1.0), foot

    def project_to_face(self, face_id: int, pts: np.ndarray):
        f, sad, sas, (umin, umax, vmin, vmax) = self._surf(face_id)
        pts = np.asarray(pts, dtype=float).reshape(-1, 3)
        n = len(pts)
        dist = np.full(n, np.inf)
        uv = np.zeros((n, 2))
        inside = np.zeros(n, dtype=bool)
        foot = np.zeros((n, 3))
        du = (umax - umin) or 1.0
        dv = (vmax - vmin) or 1.0
        for i, q in enumerate(pts):
            p2 = sas.ValueOfUV(gp_Pnt(*q), 1e-7)
            u, v = p2.X(), p2.Y()
            if sad.IsUPeriodic():
                per = sad.UPeriod()
                while u < umin - 1e-9:
                    u += per
                while u > umax + 1e-9:
                    u -= per
            fp = _xyz(sad.Value(u, v))
            foot[i] = fp
            dist[i] = float(np.linalg.norm(q - fp))
            uv[i] = ((u - umin) / du, (v - vmin) / dv)
            st = BRepClass_FaceClassifier(f, gp_Pnt2d(u, v), 1e-6).State()
            inside[i] = st in (TopAbs_IN, TopAbs_ON)
        return dist, uv, inside, foot

    def eval_face(self, face_id: int, uv: np.ndarray):
        f, sad, _, (umin, umax, vmin, vmax) = self._surf(face_id)
        uv = np.asarray(uv, dtype=float).reshape(-1, 2)
        pts = np.zeros((len(uv), 3))
        nrm = np.zeros((len(uv), 3))
        for i, (a, b) in enumerate(uv):
            u = umin + a * (umax - umin)
            v = vmin + b * (vmax - vmin)
            pts[i], nrm[i] = self._normal_at(f, sad, u, v)
        return pts, nrm

    def sample_face(self, face_id: int, n: int) -> np.ndarray:
        f, sad, _, (umin, umax, vmin, vmax) = self._surf(face_id)
        out = []
        g = (np.arange(n) + 0.5) / n
        for a in g:
            for b in g:
                u = umin + a * (umax - umin)
                v = vmin + b * (vmax - vmin)
                if BRepClass_FaceClassifier(f, gp_Pnt2d(u, v), 1e-6).State() == TopAbs_IN:
                    out.append(_xyz(sad.Value(u, v)))
        return np.array(out, dtype=float).reshape(-1, 3)

    def points_inside(self, pts: np.ndarray) -> np.ndarray:
        pts = np.asarray(pts, dtype=float).reshape(-1, 3)
        res = np.zeros(len(pts), dtype=bool)
        cls = BRepClass3d_SolidClassifier(self._solid)
        for i, q in enumerate(pts):
            cls.Perform(gp_Pnt(*q), 1e-7)
            res[i] = cls.State() == TopAbs_IN
        return res

    def eval_edge(self, edge_id: int, t: np.ndarray) -> np.ndarray:
        e, ad, u1, u2, total = self._curve(edge_id)
        t = np.clip(np.asarray(t, dtype=float).reshape(-1), 0.0, 1.0)
        out = np.zeros((len(t), 3))
        linear = ad.GetType() in (GeomAbs_Line, GeomAbs_Circle)
        for i, ti in enumerate(t):
            if linear or total <= 0:
                u = u1 + ti * (u2 - u1)
            elif ti <= 0.0:
                u = u1
            elif ti >= 1.0:
                u = u2
            else:
                ap = GCPnts_AbscissaPoint(1e-10, ad, ti * total, u1)
                u = ap.Parameter() if ap.IsDone() else u1 + ti * (u2 - u1)
            out[i] = _xyz(ad.Value(u))
        return out

    def classify_face_uv(self, face_id: int, uv: np.ndarray) -> np.ndarray:
        f, _, _, (umin, umax, vmin, vmax) = self._surf(face_id)
        uv = np.asarray(uv, dtype=float).reshape(-1, 2)
        res = np.zeros(len(uv), dtype=bool)
        for i, (a, b) in enumerate(uv):
            st = BRepClass_FaceClassifier(f, gp_Pnt2d(umin + a * (umax - umin), vmin + b * (vmax - vmin)), 1e-6).State()
            res[i] = st in (TopAbs_IN, TopAbs_ON)
        return res

    def distance(self, pts: np.ndarray) -> np.ndarray:
        pts = np.asarray(pts, dtype=float).reshape(-1, 3)
        out = np.full(len(pts), np.inf)
        if getattr(self, "_faces_compound", None) is None:
            comp = TopoDS_Compound()
            bld = BRep_Builder()
            bld.MakeCompound(comp)
            for f in self._faces:
                bld.Add(comp, f)
            self._faces_compound = comp
        for i, q in enumerate(pts):
            ext = BRepExtrema_DistShapeShape(BRepBuilderAPI_MakeVertex(gp_Pnt(*q)).Vertex(), self._faces_compound)
            if ext.IsDone():
                out[i] = float(ext.Value())
        return out

    def triangulate(self, deflection: float | None = None, angle_deg: float = 20.0) -> list[tuple[int, np.ndarray, np.ndarray]]:
        """Display tessellation (feature highlight PNG): [(face id, points[n,3], triangles[m,3] 0-based)],
        triangles oriented with the outward normal. Meshes a copy so the body's own shape stays untouched."""
        from OCP.BRepBuilderAPI import BRepBuilderAPI_Copy
        from OCP.BRepMesh import BRepMesh_IncrementalMesh

        if deflection is None:
            bb = self.summary().bbox
            deflection = max(1e-3, 0.002 * float(np.linalg.norm(bb[3:] - bb[:3])))
        copy = BRepBuilderAPI_Copy(self._solid, True, False).Shape()
        BRepMesh_IncrementalMesh(copy, float(deflection), False, math.radians(angle_deg), True)
        fmap = TopTools_IndexedMapOfShape()
        TopExp.MapShapes_s(copy, TopAbs_FACE, fmap)
        if fmap.Extent() != len(self._faces):
            raise KernelError("GEOM_INTERNAL", "tessellation copy has a different face count")
        out = []
        for i in range(1, fmap.Extent() + 1):
            f = TopoDS.Face_s(fmap.FindKey(i))
            loc = TopLoc_Location()
            tri = BRep_Tool.Triangulation_s(f, loc)
            if tri is None:
                continue
            trsf = loc.Transformation()
            pts = np.array([_xyz(tri.Node(k).Transformed(trsf)) for k in range(1, tri.NbNodes() + 1)], dtype=float).reshape(-1, 3)
            tris = np.array([tri.Triangle(k).Get() for k in range(1, tri.NbTriangles() + 1)], dtype=np.int64).reshape(-1, 3) - 1
            if f.Orientation() == TopAbs_REVERSED:
                tris = tris[:, [0, 2, 1]]
            out.append((i, pts, tris))
        return out

    # ---------------- push/pull (section 6.3) ----------------
    def moved(self, moves: dict[int, FaceMove]) -> OccBody:
        """New body with face moves applied (same topology and sub-shape order). Raises KernelError."""
        from .occ_push import PushPullError, push_pull

        eff = {int(k): v for k, v in moves.items() if v.is_effective()}
        if not eff:
            return OccBody(self.name, self._solid)
        try:
            solid, uv_changed = push_pull(self, eff)
        except PushPullError as e:
            raise KernelError(e.code, e.message) from None
        except Exception as e:  # OCCT exceptions -> CAD failure, never a crash
            raise KernelError("GEOM_CAD_FAILED", f"OCCT error during push/pull: {e.__class__.__name__}: {e}") from None
        nb = OccBody(self.name, solid)
        nb.uv_changed = set(uv_changed)
        if (len(nb._faces), len(nb._edges), len(nb._verts)) != (len(self._faces), len(self._edges), len(self._verts)):
            raise KernelError(
                "GEOM_TOPOLOGY_CHANGED",
                f"topology changed: faces {len(self._faces)}->{len(nb._faces)}, edges {len(self._edges)}->{len(nb._edges)}",
            )
        if nb.summary().volume <= 0:
            raise KernelError("GEOM_CAD_FAILED", "rebuilt solid has non-positive volume")
        return nb


def write_brep(bodies: list[OccBody], path: str | Path) -> None:
    """OCCT native BRep: compound of the bodies' solids in the given order."""
    comp = TopoDS_Compound()
    bld = BRep_Builder()
    bld.MakeCompound(comp)
    for b in bodies:
        bld.Add(comp, b._solid)
    if not BRepTools.Write_s(comp, str(path)):
        raise KernelError("GEOM_INTERNAL", f"cannot write BRep file: {Path(path).name}")


def load_brep(path: str | Path, names: list[str]) -> list[OccBody]:
    """Read a compound written by :func:`write_brep`; solids are named from ``names`` in order."""
    shape = TopoDS_Shape()
    if not BRepTools.Read_s(shape, str(path), BRep_Builder()) or shape.IsNull():
        raise KernelError("GEOM_INPUT_INVALID", f"cannot read BRep file: {Path(path).name}")
    solids = _solids(shape)
    if len(solids) != len(names):
        raise KernelError("GEOM_INPUT_INVALID", f"{Path(path).name}: expected {len(names)} solids, found {len(solids)}")
    return [OccBody(n, s) for n, s in zip(names, solids)]


__all__ = ["KernelError", "OccBody", "load_brep", "load_parts_dir", "load_step", "occt_version", "ocp_version", "write_brep"]
