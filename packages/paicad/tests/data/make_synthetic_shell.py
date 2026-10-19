"""Virtual sheet-metal golden set SM1 (shell-morph section 9.1), test-only (build123d + gmsh, ``test`` extra).

Produces, into an output folder (nothing here is committed):

* ``cad/chassis_mid.step`` - one mid-surface sheet body ``chassis_rear``: plate 400 x 300 (z = 0, normal +z),
  flanges on both long edges (bend radius 3, height 15), 5 beads (B1/B2 linear deboss, B3 circular
  emboss, B4 linear deboss next to the tie band -> BEAD_NEAR_FIXED, B5 circular deboss whose loop is covered
  by the screw-hole RBE2 spider H6 -> BEAD_FIXED_OVERLAP), 6 screw holes D4;
* ``assem/`` - synthetic Radioss assembly: starter ``MODEL_0000.rad``, ``inc/chassis.inc`` (plate/bead nodes +
  ``/SHELL`` + ``/SH3N`` + a few degenerate quads), ``inc/chassis_flange_nodes.inc`` (flange nodes),
  ``inc/parts.inc`` (bracket, pad, clip parts), ``inc/fix.inc`` (``/RBE2`` x6, ``/RBE3``, ``/RBODY``, ``/BCS``,
  ``/GRNOD/NODE|PART|GRNOD``, ``/SURF/SEG|PART``, two ``/INTER/TYPE2``);
* ``truth.json`` - design bead parameters and the fixed node sets per kind.

Bead cross-section (profile in (rho, h), h = depth into the bead): plate (h = 0) -> top fillet (radius r_top,
tangent) -> straight flank at ``flank_deg`` -> bottom fillet (r_bot) -> flat bottom (h = depth). Width = distance
of the flanks at half depth; linear length = core length + width. Linear beads: two prisms per side (fillets
= cylinders, flank = plane), half revolutions at the ends (tori, cones); circular beads: one revolution.

Usage: python make_synthetic_shell.py OUT_DIR
"""

from __future__ import annotations

import copy
import json
import math
import sys
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

import numpy as np

BODY_NAME = "chassis_rear"
PART_ID = 2001
PART_TITLE = "CHASSIS_REAR"
STEP_REL = "cad/chassis_mid.step"
NODE_START = 2000001
ELEM_START = 2000001
MESH = {"size_avg": 3.0, "size_min": 0.3, "arc_mm": 1.1, "circle_step_deg": 12.0, "hole_segments": 16}


@dataclass
class BeadSpec:
    name: str
    kind: str  # linear | circular
    center: tuple[float, float]
    width: float
    depth: float
    sense: str = "deboss"
    length: float = 0.0  # linear: overall length (core + width)
    axis_deg: float = 0.0  # linear: direction in the plate plane
    flank_deg: float = 60.0
    r_top: float = 2.0
    r_bot: float = 2.0
    halves: bool = False  # circular: two half revolutions (no seam edges) instead of one full revolution


@dataclass
class SheetSpec:
    L: float = 400.0
    W: float = 300.0
    flange_h: float = 15.0
    bend_r: float = 3.0
    hole_d: float = 4.0
    holes: tuple = ((25.0, 40.0), (200.0, 40.0), (375.0, 40.0), (25.0, 270.0), (200.0, 270.0), (64.48, 255.0))
    spider_r: tuple = (5.0, 5.0, 5.0, 5.0, 5.0, 6.5)
    beads: list = field(
        default_factory=lambda: [
            BeadSpec("B1", "linear", (120.0, 90.0), width=12.0, depth=4.0, length=80.0, axis_deg=0.0),
            BeadSpec("B2", "linear", (250.0, 150.0), width=10.0, depth=3.0, length=70.0, axis_deg=90.0),
            BeadSpec("B3", "circular", (300.0, 220.0), width=30.0, depth=3.0, sense="emboss", halves=True),
            BeadSpec("B4", "linear", (351.0, 150.0), width=10.0, depth=3.0, length=60.0, axis_deg=90.0),
            BeadSpec("B5", "circular", (80.0, 255.0), width=20.0, depth=3.0),
        ]
    )
    tie_band: tuple = (361.0, 110.0, 392.0, 190.0)  # x0 y0 x1 y1 of the bracket footprint (tie secondary nodes)
    pad_box: tuple = (195.3, 140.2, 210.3, 155.2)  # pad part (tie 2 secondary) over the plate
    clip_x: tuple = (150.0, 190.0)  # clip part shares the y=0 flange free-edge nodes in this x range
    rbe3_at: tuple = (300.0, 60.0)


# ------------------------------------------------------------------ profile
def profile(b: BeadSpec) -> dict:
    """Key points of the bead cross-section in (rho, h)."""
    th = math.radians(b.flank_deg)
    rh = 0.5 * b.width
    rl0 = rh + 0.5 * b.depth / math.tan(th)
    rld = rh - 0.5 * b.depth / math.tan(th)
    t1 = b.r_top * math.tan(0.5 * th)
    t2 = b.r_bot * math.tan(0.5 * th)
    d = np.array([-math.cos(th), math.sin(th)])
    P0 = np.array([rl0 + t1, 0.0])
    C1 = np.array([rl0 + t1, b.r_top])
    P1 = np.array([rl0, 0.0]) + t1 * d
    P2 = np.array([rld, b.depth]) - t2 * d
    C2 = np.array([rld - t2, b.depth - b.r_bot])
    P3 = np.array([rld - t2, b.depth])
    return {"P0": P0, "C1": C1, "P1": P1, "P2": P2, "C2": C2, "P3": P3, "rho0": float(P0[0]), "rho_b": float(P3[0])}


def _frame(b: BeadSpec):
    n = np.array([0.0, 0.0, 1.0])
    ed = -n if b.sense == "deboss" else n
    a = math.radians(b.axis_deg)
    u = np.array([math.cos(a), math.sin(a), 0.0])
    w = np.cross(n, u)
    c = np.array([b.center[0], b.center[1], 0.0])
    half = 0.5 * (b.length - b.width) if b.kind == "linear" else 0.0
    return n, ed, u, w, c, half


# ------------------------------------------------------------------ B-rep construction (OCP via build123d)
def _p(v):
    from OCP.gp import gp_Pnt

    return gp_Pnt(float(v[0]), float(v[1]), float(v[2]))


def _arc(c, p, q):
    """Edge: circle arc from p to q with center c (minor arc)."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
    from OCP.GC import GC_MakeArcOfCircle

    r = float(np.linalg.norm(p - c))
    m = (p - c) + (q - c)
    m = c + r * m / np.linalg.norm(m)
    return BRepBuilderAPI_MakeEdge(GC_MakeArcOfCircle(_p(p), _p(m), _p(q)).Value()).Edge()


def _line(p, q):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge

    return BRepBuilderAPI_MakeEdge(_p(p), _p(q)).Edge()


def _profile_edges(b: BeadSpec, origin, rhat, ed, with_bottom: bool):
    pr = profile(b)

    def P(k):
        x = pr[k]
        return origin + x[0] * rhat + x[1] * ed

    edges = [_arc(P("C1"), P("P0"), P("P1")), _line(P("P1"), P("P2")), _arc(P("C2"), P("P2"), P("P3"))]
    if with_bottom:
        edges.append(_line(P("P3"), origin + pr["P3"][1] * ed))
    return edges


def _faces_of(shape) -> list:
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    out = []
    exp = TopExp_Explorer(shape, TopAbs_FACE)
    while exp.More():
        out.append(TopoDS.Face_s(exp.Current()))
        exp.Next()
    return out


def _prism(edge, vec) -> list:
    from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
    from OCP.gp import gp_Vec

    return _faces_of(BRepPrimAPI_MakePrism(edge, gp_Vec(*map(float, vec))).Shape())


def _revol(edge, point, axis, angle) -> list:
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeRevol
    from OCP.gp import gp_Ax1, gp_Dir

    return _faces_of(BRepPrimAPI_MakeRevol(edge, gp_Ax1(_p(point), gp_Dir(*map(float, axis))), float(angle)).Shape())


def _loop_wire(b: BeadSpec, rho: float, h: float):
    """Closed wire at radius ``rho`` around the bead core at depth ``h`` (stadium or circle)."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire
    from OCP.gp import gp_Ax2, gp_Circ, gp_Dir

    n, ed, u, w, c, half = _frame(b)
    o = c + h * ed
    mk = BRepBuilderAPI_MakeWire()
    if b.kind == "circular":
        if b.halves:
            ex, ey = np.array([1.0, 0.0, 0.0]), np.array([0.0, 1.0, 0.0])
            mk.Add(_semi(o, rho * ex, rho * ey))
            mk.Add(_semi(o, -rho * ex, -rho * ey))
            return mk.Wire()
        circ = gp_Circ(gp_Ax2(_p(o), gp_Dir(*n), gp_Dir(1.0, 0.0, 0.0)), rho)
        mk.Add(BRepBuilderAPI_MakeEdge(circ).Edge())
        return mk.Wire()
    A, B = o - half * u, o + half * u
    mk.Add(_line(A + rho * w, B + rho * w))
    mk.Add(_semi(B, rho * w, rho * u))
    mk.Add(_line(B - rho * w, A - rho * w))
    mk.Add(_semi(A, -rho * w, -rho * u))
    return mk.Wire()


def _semi(center, r0, rmid):
    """Half circle from center + r0 through center + rmid to center - r0."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
    from OCP.GC import GC_MakeArcOfCircle

    return BRepBuilderAPI_MakeEdge(GC_MakeArcOfCircle(_p(center + r0), _p(center + rmid), _p(center - r0)).Value()).Edge()


def _bead_faces(b: BeadSpec) -> list:
    n, ed, u, w, c, half = _frame(b)
    pr = profile(b)
    if b.kind == "circular":
        faces = []
        for start in ((np.array([1.0, 0.0, 0.0]), np.array([-1.0, 0.0, 0.0])) if b.halves else (np.array([1.0, 0.0, 0.0]),)):
            for e in _profile_edges(b, c, start, ed, not b.halves):
                faces += _revol(e, c, n, math.pi if b.halves else 2.0 * math.pi)
        if b.halves:
            from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace

            faces.append(BRepBuilderAPI_MakeFace(_loop_wire(b, pr["rho_b"], b.depth), True).Face())
        return faces
    A, B = c - half * u, c + half * u
    faces = []
    for side in (w, -w):
        for e in _profile_edges(b, A, side, ed, False):
            faces += _prism(e, 2.0 * half * u)
    for e in _profile_edges(b, B, w, ed, False):
        faces += _revol(e, B, n, -math.pi)
    for e in _profile_edges(b, A, -w, ed, False):
        faces += _revol(e, A, n, -math.pi)
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace

    faces.append(BRepBuilderAPI_MakeFace(_loop_wire(b, pr["rho_b"], b.depth), True).Face())
    return faces


def build_sheet(spec: SheetSpec):
    """Sewn sheet (OCP TopoDS_Shell) of the spec; plate normal = +z."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakeWire, BRepBuilderAPI_Sewing
    from OCP.BRep import BRep_Tool
    from OCP.gp import gp_Ax2, gp_Circ, gp_Dir, gp_Pln
    from OCP.TopAbs import TopAbs_REVERSED, TopAbs_SHELL
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    s = spec
    L, W, R, H = s.L, s.W, s.bend_r, s.flange_h
    outer = BRepBuilderAPI_MakeWire()
    corners = [np.array(p, dtype=float) for p in ((0, 0, 0), (L, 0, 0), (L, W, 0), (0, W, 0))]
    for i in range(4):
        outer.Add(_line(corners[i], corners[(i + 1) % 4]))
    mkf = BRepBuilderAPI_MakeFace(gp_Pln(), outer.Wire(), True)
    for b in s.beads:
        wire = _loop_wire(b, profile(b)["rho0"], 0.0)
        mkf.Add(TopoDS.Wire_s(wire.Reversed()))
    for (x, y) in s.holes:
        circ = gp_Circ(gp_Ax2(_p((x, y, 0.0)), gp_Dir(0, 0, 1), gp_Dir(1, 0, 0)), 0.5 * s.hole_d)
        hw = BRepBuilderAPI_MakeWire(BRepBuilderAPI_MakeEdge(circ).Edge()).Wire()
        mkf.Add(TopoDS.Wire_s(hw.Reversed()))
    faces = [mkf.Face()]
    for y0, sg in ((0.0, -1.0), (W, 1.0)):
        c = np.array([0.0, y0, -R])
        p0 = np.array([0.0, y0, 0.0])
        p1 = np.array([0.0, y0 + sg * R, -R])
        faces += _prism(_arc(c, p0, p1), (L, 0, 0))
        faces += _prism(_line(p1, np.array([0.0, y0 + sg * R, -H])), (L, 0, 0))
    for b in s.beads:
        faces += _bead_faces(b)
    sew = BRepBuilderAPI_Sewing(1.0e-6)
    for f in faces:
        sew.Add(f)
    sew.Perform()
    res = sew.SewedShape()
    shells = []
    exp = TopExp_Explorer(res, TopAbs_SHELL)
    while exp.More():
        shells.append(TopoDS.Shell_s(exp.Current()))
        exp.Next()
    if len(shells) != 1:
        raise RuntimeError(f"sewing produced {len(shells)} shells")
    sh = shells[0]
    # plate normal must be +z (sense = sign of (bottom - plate) . plate normal)
    from OCP.BRepAdaptor import BRepAdaptor_Surface

    for f in _faces_of(sh):
        ad = BRepAdaptor_Surface(f)
        bb = BRep_Tool.Surface_s(f)
        from OCP.GeomAbs import GeomAbs_Plane

        if ad.GetType() == GeomAbs_Plane:
            from OCP.BRepGProp import BRepGProp
            from OCP.GProp import GProp_GProps

            g = GProp_GProps()
            BRepGProp.SurfaceProperties_s(f, g)
            if g.Mass() > 0.5 * L * W:
                nz = ad.Plane().Axis().Direction().Z()
                if f.Orientation() == TopAbs_REVERSED:
                    nz = -nz
                if nz < 0:
                    sh = TopoDS.Shell_s(sh.Reversed())
                break
    del bb
    return sh


def write_sheet_step(path: Path, shell, name: str = BODY_NAME) -> None:
    from build123d import Compound, Shell, export_step

    s = Shell(shell)
    s.label = name
    path.parent.mkdir(parents=True, exist_ok=True)
    export_step(Compound(children=[s]), str(path))


# ------------------------------------------------------------------ mesh
def mesh_sheet(step: Path) -> tuple[np.ndarray, list[list[int]]]:
    """gmsh quad-dominant mesh (avg 3 mm). Returns (xyz[n,3], elements as 0-based node lists of 3 or 4).

    Curves are discretized uniformly (lines ~3 mm, fillet / bend arcs ~1.1 mm, revolution circles every
    12 deg, holes 16 segments); 4-sided curved strips (fillets, flanks of revolution, bends) and straight
    rectangles are transfinite (structured quads, like a production mesh following the fillet rows); the
    plate and the bead bottoms are unstructured Frontal-Delaunay for quads + simple recombination (quads + some triangles)."""
    import gmsh

    gmsh.initialize(["-noenv"], readConfigFiles=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setNumber("General.NumThreads", 1)
        gmsh.model.add("sheet")
        gmsh.option.setNumber("Geometry.OCCSewFaces", 0)
        gmsh.model.occ.importShapes(str(step))
        gmsh.model.occ.synchronize()
        for _, c in gmsh.model.getEntities(1):
            L = gmsh.model.occ.getMass(1, c)
            if gmsh.model.getType(1, c) == "Circle":
                a0, a1 = gmsh.model.getParametrizationBounds(1, c)
                ang = abs(a1[0] - a0[0])
                if ang > 1.9 * math.pi and L / ang < 2.5:
                    n = MESH["hole_segments"]
                elif ang <= 0.5 * math.pi + 1e-6:
                    n = max(1, math.ceil(L / MESH["arc_mm"] - 1e-9))
                else:
                    n = max(1, math.ceil(math.degrees(ang) / MESH["circle_step_deg"] - 1e-9))
            else:
                n = max(1, math.ceil(L / MESH["size_avg"] - 1e-9))
            gmsh.model.mesh.setTransfiniteCurve(c, n + 1)
        for _, srf in gmsh.model.getEntities(2):
            bnd = gmsh.model.getBoundary([(2, srf)], oriented=False)
            curves = {abs(t) for _, t in bnd}
            if gmsh.model.occ.getMass(2, srf) > 50000.0:
                continue  # the plate
            typ = gmsh.model.getType(2, srf)
            if typ != "Plane" and len(curves) in (3, 4):
                gmsh.model.mesh.setTransfiniteSurface(srf)
            elif typ == "Plane" and len(bnd) == 4 and all(gmsh.model.getType(1, c) == "Line" for c in curves):
                gmsh.model.mesh.setTransfiniteSurface(srf)
        gmsh.option.setNumber("Mesh.MeshSizeMax", MESH["size_avg"])
        gmsh.option.setNumber("Mesh.MeshSizeMin", MESH["size_min"])
        gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)
        gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 1)
        gmsh.option.setNumber("Mesh.Algorithm", 8)
        gmsh.option.setNumber("Mesh.RecombineAll", 1)
        gmsh.option.setNumber("Mesh.RecombinationAlgorithm", 0)
        gmsh.option.setNumber("Mesh.RandomSeed", 1)
        gmsh.option.setNumber("Mesh.ElementOrder", 1)
        gmsh.model.mesh.generate(2)
        tags, coords, _ = gmsh.model.mesh.getNodes()
        coords = np.asarray(coords).reshape(-1, 3)
        order = np.argsort(tags)
        tags = np.asarray(tags)[order]
        coords = coords[order]
        pos = {int(t): i for i, t in enumerate(tags)}
        elems: list[list[int]] = []
        for dim, ent in gmsh.model.getEntities(2):
            et, _, en = gmsh.model.mesh.getElements(dim, ent)
            for t, conn in zip(et, en):
                k = {2: 3, 3: 4}.get(int(t))
                if k is None:
                    continue
                for e in np.asarray(conn, dtype=np.int64).reshape(-1, k):
                    elems.append([pos[int(x)] for x in e])
        used = sorted({i for e in elems for i in e})
        remap = {o: i for i, o in enumerate(used)}
        return coords[used], [[remap[i] for i in e] for e in elems]
    finally:
        gmsh.finalize()


def clear_jacobian_band(xyz: np.ndarray, elems: list[list[int]], lo: float = 0.585, hi: float = 0.625, passes: int = 20) -> np.ndarray:
    """Move interior nodes of horizontal planar faces (plate, bead bottoms) of elements whose Jacobian lies in
    [lo, hi) (around the default 0.6 limit)
    out of that band. A move is kept only when no adjacent element drops below min(before, lo), no element
    newly enters the band and the band elements get farther from 0.6 - so that tiny far-field displacements
    cannot flip a golden element across the limit."""
    from paicad.shell.quality import metrics

    conn = np.array([e if len(e) == 4 else e + [e[2]] for e in elems], dtype=np.int64)
    tri = np.array([len(e) == 3 for e in elems])
    x = xyz.copy()
    # horizontal planar faces (plate, bead bottoms): elements whose nodes share one z; their interior nodes move in x, y
    ez = x[conn][:, :, 2]
    flat = np.ptp(ez, axis=1) <= 1e-9
    edges = np.concatenate([conn[:, [0, 1]], conn[:, [1, 2]], conn[:, [2, 3]], conn[:, [3, 0]]])
    edges = edges[edges[:, 0] != edges[:, 1]]
    key, cnt = np.unique(np.sort(edges, axis=1), axis=0, return_counts=True)
    movable = np.zeros(len(x), dtype=bool)
    movable[np.unique(conn[flat])] = True
    movable[np.unique(conn[~flat])] = False
    movable[np.unique(key[cnt == 1])] = False
    nbr: dict[int, set[int]] = {}
    for a, b in key:
        nbr.setdefault(int(a), set()).add(int(b))
        nbr.setdefault(int(b), set()).add(int(a))
    n2e: dict[int, list[int]] = {}
    for k, e in enumerate(conn):
        for v in set(e.tolist()):
            n2e.setdefault(v, []).append(k)

    def closeness(j: np.ndarray) -> float:
        inb = (j >= lo) & (j < hi)
        return float(np.min(np.abs(j[inb] - 0.6))) if inb.any() else 1.0

    for _ in range(passes):
        jac = metrics(x, conn, tri).jac
        band = np.flatnonzero((jac >= lo) & (jac < hi))
        if len(band) == 0:
            break
        changed = False
        for k in band:
            for v in sorted(set(conn[k].tolist())):
                if not movable[v]:
                    continue
                els = n2e[v]
                before = jac[els]
                inb0 = (before >= lo) & (before < hi)
                avg = x[sorted(nbr[v])].mean(axis=0)
                best = (closeness(before), None)
                for t in (0.5, 0.25, 1.0, -0.25):
                    cand = x.copy()
                    cand[v, :2] = x[v, :2] + t * (avg[:2] - x[v, :2])
                    after = metrics(cand, conn[els], tri[els]).jac
                    if np.any(after < np.minimum(before, lo) - 1e-12) or np.any((after >= lo) & (after < hi) & ~inb0):
                        continue
                    c = closeness(after)
                    if c > best[0] + 1e-9:
                        best = (c, cand[v].copy())
                if best[1] is not None:
                    x[v] = best[1]
                    jac[els] = metrics(x, conn[els], tri[els]).jac
                    changed = True
        if not changed:
            break
    return x


# ------------------------------------------------------------------ assembly
def _f(x: float) -> str:
    return f"{x:20.10f}"


def _node_line(nid: int, p) -> str:
    return f"{nid:10d}{_f(p[0])}{_f(p[1])}{_f(p[2])}"


def _ids_lines(ids, per: int = 10) -> list[str]:
    ids = list(ids)
    return ["".join(f"{i:10d}" for i in ids[k : k + per]) for k in range(0, len(ids), per)]


def _prop_type1(pid: int, title: str, thick: float) -> list[str]:
    return [
        f"/PROP/TYPE1/{pid}",
        title,
        "#   Ishell    Ismstr     Ish3n    Idrill",
        f"{24:10d}{0:10d}{0:10d}{0:10d}",
        "#                 hm                  hf                  hr                  dm                  dn",
        "",
        "#        N   Istrain               Thick              Ashear              Ithick     Iplas",
        f"{5:10d}{0:10d}{thick:20.4f}{0.0:20.4f}{'':10s}{1:10d}{1:10d}",
    ]


def _grid(x0, y0, x1, y1, z, nx, ny):
    xs = np.linspace(x0, x1, nx + 1)
    ys = np.linspace(y0, y1, ny + 1)
    pts = np.array([[x, y, z] for y in ys for x in xs])
    quads = [[j * (nx + 1) + i, j * (nx + 1) + i + 1, (j + 1) * (nx + 1) + i + 1, (j + 1) * (nx + 1) + i] for j in range(ny) for i in range(nx)]
    return pts, quads


def _point_in_poly(p, poly) -> bool:
    x, y = p
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xi = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if xi > x:
                inside = not inside
    return inside


def write_assembly(folder: Path, spec: SheetSpec, xyz: np.ndarray, elems: list[list[int]]) -> dict:
    """Synthetic Radioss assembly around the chassis mesh. Returns the fixed-node truth."""
    s = spec
    folder = Path(folder)
    (folder / "inc").mkdir(parents=True, exist_ok=True)
    nid = np.arange(NODE_START, NODE_START + len(xyz))
    plate_like = (np.abs(xyz[:, 2]) <= 1e-6) | ((xyz[:, 1] > 1e-6) & (xyz[:, 1] < s.W - 1e-6))
    flange = ~plate_like
    tri = [e for e in elems if len(e) == 3]
    quad = [e for e in elems if len(e) == 4]
    degen = tri[:3]  # written as /SHELL with n3 = n4 (treated as triangles)
    tri = tri[3:]
    lines = ["#RADIOSS include: chassis_rear mid-surface mesh (paicad shell golden)", "/NODE", "#  node_ID                   X                   Y                   Z"]
    lines += [_node_line(int(nid[i]), xyz[i]) for i in np.flatnonzero(plate_like)]
    eid = ELEM_START
    lines += [f"/SHELL/{PART_ID}", "#shell_ID     node1     node2     node3     node4"]
    for e in quad:
        lines.append(f"{eid:10d}" + "".join(f"{int(nid[i]):10d}" for i in e))
        eid += 1
    for e in degen:
        lines.append(f"{eid:10d}" + "".join(f"{int(nid[i]):10d}" for i in (e[0], e[1], e[2], e[2])))
        eid += 1
    lines += [f"/SH3N/{PART_ID}", "# sh3n_ID     node1     node2     node3"]
    for e in tri:
        lines.append(f"{eid:10d}" + "".join(f"{int(nid[i]):10d}" for i in e))
        eid += 1
    (folder / "inc" / "chassis.inc").write_text("\n".join(lines) + "\n", encoding="ascii")
    fl = ["#RADIOSS include: chassis_rear flange nodes", "/NODE"] + [_node_line(int(nid[i]), xyz[i]) for i in np.flatnonzero(flange)]
    (folder / "inc" / "chassis_flange_nodes.inc").write_text("\n".join(fl) + "\n", encoding="ascii")

    on_plate = np.abs(xyz[:, 2]) <= 1e-6
    truth: dict[str, set[int]] = {k: set() for k in ("INTER_TYPE2_SECONDARY", "INTER_TYPE2_MAIN", "RBE2", "RBE3", "RBODY", "BCS", "SHARED")}
    other_nodes: list[str] = ["/NODE"]
    parts_lines: list[str] = ["#RADIOSS include: bracket / pad / clip parts", "/NODE"]
    next_node = 3000001
    # bracket (tie 1 main) over the band, z = +0.9
    x0, y0, x1, y1 = s.tie_band
    bp, bq = _grid(x0 - 1.0, y0 - 2.0, x1 + 1.0, y1 + 2.0, 0.9, 11, 28)
    b_ids = np.arange(next_node, next_node + len(bp))
    next_node += 1000
    parts_lines += [_node_line(int(b_ids[i]), bp[i]) for i in range(len(bp))]
    pp, pq = _grid(*s.pad_box[:2], *s.pad_box[2:], 0.9, 3, 3)
    p_ids = np.arange(next_node, next_node + len(pp))
    next_node += 1000
    parts_lines += [_node_line(int(p_ids[i]), pp[i]) for i in range(len(pp))]
    # clip: shares the y=0 flange free-edge nodes
    edge = np.flatnonzero((np.abs(xyz[:, 2] + s.flange_h) <= 1e-6) & (xyz[:, 1] < 0) & (xyz[:, 0] >= s.clip_x[0]) & (xyz[:, 0] <= s.clip_x[1]))
    edge = edge[np.argsort(xyz[edge, 0])]
    c_new = np.arange(next_node, next_node + len(edge))
    next_node += 1000
    parts_lines += [_node_line(int(c_new[k]), xyz[i] + np.array([0.0, 0.0, -7.0])) for k, i in enumerate(edge)]
    e2 = 3000001
    parts_lines += ["/SHELL/2002"]
    for q in bq:
        parts_lines.append(f"{e2:10d}" + "".join(f"{int(b_ids[i]):10d}" for i in q))
        e2 += 1
    bracket_elems = list(range(3000001, e2))
    parts_lines += ["/SHELL/2004"]
    for q in pq:
        parts_lines.append(f"{e2:10d}" + "".join(f"{int(p_ids[i]):10d}" for i in q))
        e2 += 1
    parts_lines += ["/SHELL/2003"]
    for k in range(len(edge) - 1):
        parts_lines.append(f"{e2:10d}{int(nid[edge[k]]):10d}{int(nid[edge[k + 1]]):10d}{int(c_new[k + 1]):10d}{int(c_new[k]):10d}")
        e2 += 1
    (folder / "inc" / "parts.inc").write_text("\n".join(parts_lines) + "\n", encoding="ascii")
    truth["SHARED"] = {int(nid[i]) for i in edge}
    truth["RBODY"] = set(truth["SHARED"])

    fix: list[str] = ["#RADIOSS include: fixing definitions (ties, rigid elements, boundary conditions)"]
    # RBE2 per screw hole: dependent = chassis nodes within the spider radius (in-plane distance)
    ind_nodes = []
    for k, ((hx, hy), rs) in enumerate(zip(s.holes, s.spider_r), 1):
        d = np.hypot(xyz[:, 0] - hx, xyz[:, 1] - hy)
        dep = np.flatnonzero((d <= rs) & (xyz[:, 2] <= 1e-6) & plate_like)
        mid = 900000 + k
        ind_nodes.append((mid, (hx, hy, 0.0)))
        fix += [f"/RBE2/{500 + k}", f"SCREW_{k}", "#  node_ID    Trarot   Skew_ID  grnod_ID     Iflag", f"{mid:10d}{'   111111':>10s}{0:10d}{510 + k:10d}{0:10d}"]
        fix += [f"/GRNOD/NODE/{510 + k}", f"SCREW_{k}_SPIDER"] + _ids_lines(int(nid[i]) for i in dep)
        truth["RBE2"].update(int(nid[i]) for i in dep)
    # tie 1: chassis band nodes (secondary) on the bracket (main /SURF/SEG)
    band = np.flatnonzero(on_plate & (xyz[:, 0] >= x0) & (xyz[:, 0] <= x1) & (xyz[:, 1] >= y0) & (xyz[:, 1] <= y1))
    fix += ["/INTER/TYPE2/12", "TIE_BRKT", "#grnd_IDs  surf_IDm    Ignore  Spotflag     Level   Isearch    Idel_2             Dsearch",
            f"{601:10d}{701:10d}{0:10d}{0:10d}{0:10d}{0:10d}{0:10d}{1.5:20.4f}"]
    fix += ["/GRNOD/NODE/601", "TIE_BRKT_SEC"] + _ids_lines(int(nid[i]) for i in band)
    fix += ["/SURF/SEG/701", "BRACKET_SEG"]
    for k, (eidb, q) in enumerate(zip(bracket_elems, bq)):
        fix.append(f"{eidb:10d}" + "".join(f"{int(b_ids[i]):10d}" for i in q))
    truth["INTER_TYPE2_SECONDARY"] = {int(nid[i]) for i in band}
    # tie 2: pad nodes (secondary) on the chassis (main /SURF/PART)
    fix += ["/INTER/TYPE2/13", "TIE_PAD", "#grnd_IDs  surf_IDm    Ignore  Spotflag     Level   Isearch    Idel_2             Dsearch",
            f"{602:10d}{702:10d}{0:10d}{0:10d}{0:10d}{0:10d}{0:10d}{1.5:20.4f}"]
    fix += ["/GRNOD/NODE/602", "TIE_PAD_SEC"] + _ids_lines(int(i) for i in p_ids)
    fix += ["/SURF/PART/702", "CHASSIS_SURF", f"{PART_ID:10d}"]
    main_nodes: set[int] = set()
    lo_xy = np.array([min(xyz[i][0] for i in e) for e in elems]), np.array([min(xyz[i][1] for i in e) for e in elems])
    hi_xy = np.array([max(xyz[i][0] for i in e) for e in elems]), np.array([max(xyz[i][1] for i in e) for e in elems])
    for p in pp:
        near = np.flatnonzero((lo_xy[0] <= p[0]) & (hi_xy[0] >= p[0]) & (lo_xy[1] <= p[1]) & (hi_xy[1] >= p[1]))
        for k in near:
            e = elems[k]
            if all(on_plate[i] for i in e) and _point_in_poly(p[:2], [xyz[i][:2] for i in e]):
                main_nodes.update(int(nid[i]) for i in e)
    truth["INTER_TYPE2_MAIN"] = main_nodes
    # RBODY on the clip part (/GRNOD/PART) -> the shared chassis nodes
    fix += ["/RBODY/801", "CLIP_RIGID", "#  node_ID   sens_ID   Skew_ID    Ispher                Mass   grnd_ID",
            f"{900101:10d}{0:10d}{0:10d}{0:10d}{0.0:20.4f}{803:10d}"]
    fix += ["/GRNOD/PART/803", "CLIP_PART", f"{2003:10d}"]
    # BCS on both flange ends (x = 0 / x = L) of the y=0 flange, nested /GRNOD/GRNOD
    ga = np.flatnonzero(flange & (xyz[:, 0] <= 1e-6) & (xyz[:, 1] < -s.bend_r + 1e-6))
    gb = np.flatnonzero(flange & (xyz[:, 0] >= s.L - 1e-6) & (xyz[:, 1] < -s.bend_r + 1e-6))
    fix += ["/BCS/901", "FLANGE_ENDS", "#  Tra rot   skew_ID  grnod_ID", f"{'   111 111':10s}{0:10d}{904:10d}"]
    fix += ["/GRNOD/GRNOD/904", "FLANGE_ENDS"] + _ids_lines([905, 906])
    fix += ["/GRNOD/NODE/905", "END_A"] + _ids_lines(int(nid[i]) for i in ga)
    fix += ["/GRNOD/NODE/906", "END_B"] + _ids_lines(int(nid[i]) for i in gb)
    truth["BCS"] = {int(nid[i]) for i in np.concatenate([ga, gb])}
    # RBE3: 4 plate nodes nearest to rbe3_at
    d = np.hypot(xyz[:, 0] - s.rbe3_at[0], xyz[:, 1] - s.rbe3_at[1]) + np.where(on_plate, 0.0, 1e9)
    near = np.argsort(d, kind="stable")[:4]
    fix += ["/RBE3/951", "MASS_POINT", "# node_IDd   Trarotd", f"{900201:10d}{'   111111':>10s}",
            "#                 Wt_i  Trarot_i  grnod_ID", f"{1.0:20.4f}{'   111000':>10s}{952:10d}"]
    fix += ["/GRNOD/NODE/952", "MASS_POINT_IND"] + _ids_lines(int(nid[i]) for i in near)
    truth["RBE3"] = {int(nid[i]) for i in near}
    other_nodes += [_node_line(m, p) for m, p in ind_nodes]
    other_nodes += [_node_line(900101, (170.0, -10.0, -20.0)), _node_line(900201, (s.rbe3_at[0], s.rbe3_at[1], 5.0))]
    (folder / "inc" / "fix.inc").write_text("\n".join(fix + other_nodes) + "\n", encoding="ascii")

    parts = [(PART_ID, PART_TITLE, 31), (2002, "BRACKET", 32), (2003, "CLIP", 33), (2004, "PAD", 33)]
    starter = ["#RADIOSS STARTER", "/BEGIN", "CHASSIS_SM1", "      2024         0",
               "                  Mg                  mm                   s", "                  Mg                  mm                   s"]
    for pid, title, prop in parts:
        starter += [f"/PART/{pid}", title, "#  prop_ID    mat_ID", f"{prop:10d}{1:10d}"]
    starter += _prop_type1(31, "CHASSIS_T08", 0.8) + _prop_type1(32, "BRACKET_T10", 1.0) + _prop_type1(33, "SMALL_T10", 1.0)
    starter += ["#include inc/chassis.inc", "#include inc/chassis_flange_nodes.inc", "#include inc/parts.inc", "#include inc/fix.inc", "/END"]
    (folder / "MODEL_0000.rad").write_text("\n".join(starter) + "\n", encoding="ascii")
    allfix = set().union(*truth.values())
    return {
        "by_kind": {k: len(v) for k, v in truth.items()},
        "total": len(allfix),
        "nodes": {k: sorted(v) for k, v in truth.items()},
        "n_nodes": int(len(xyz)),
        "n_quad": len(quad) + len(degen),
        "n_tri": len(tri) + len(degen),
        "n_degenerate": len(degen),
    }


# ------------------------------------------------------------------ truth / top level
def bead_truth(spec: SheetSpec) -> list[dict]:
    out = []
    for b in spec.beads:
        n, ed, u, w, c, half = _frame(b)
        pr = profile(b)
        out.append(
            {
                "name": b.name,
                "kind": b.kind,
                "sense": b.sense,
                "depth": b.depth,
                "width": b.width,
                "length": b.length if b.kind == "linear" else b.width,
                "center": [b.center[0], b.center[1], 0.0],
                "axis": [float(x) for x in u],
                "flank_deg": b.flank_deg,
                "r_top": b.r_top,
                "r_bot": b.r_bot,
                "rho0": pr["rho0"],
                "rho_b": pr["rho_b"],
            }
        )
    return out


def variant(spec: SheetSpec, bead: str, **changes) -> SheetSpec:
    """Copy of the spec with one bead changed. ``shift=(dx, dy)`` moves the center; ``depth`` keeps the entry
    loop and the flank angle (keep_angle: width at half depth follows); ``width`` keeps depth and core."""
    sp = copy.deepcopy(spec)
    for i, b in enumerate(sp.beads):
        if b.name != bead:
            continue
        ch = dict(changes)
        if "shift" in ch:
            dx, dy = ch.pop("shift")
            ch["center"] = (b.center[0] + dx, b.center[1] + dy)
        if "depth" in ch and "width" not in ch:
            ch["width"] = b.width - (ch["depth"] - b.depth) / math.tan(math.radians(b.flank_deg))
        if "width" in ch and b.kind == "linear" and "length" not in ch:
            ch["length"] = b.length + (ch["width"] - b.width)  # keep the core length
        sp.beads[i] = replace(b, **ch)
    return sp


def make_step(out: Path, spec: SheetSpec, rel: str = STEP_REL) -> Path:
    step = Path(out) / rel
    write_sheet_step(step, build_sheet(spec))
    return step


def make_all(out: Path, spec: SheetSpec | None = None) -> dict:
    spec = spec or SheetSpec()
    out = Path(out)
    step = make_step(out, spec)
    xyz, elems = mesh_sheet(step)
    xyz = clear_jacobian_band(xyz, elems)
    assem = out / "assem"
    fixed = write_assembly(assem, spec, xyz, elems)
    truth = {"body": BODY_NAME, "part_id": PART_ID, "title": PART_TITLE, "beads": bead_truth(spec), "fixed": fixed, "mesh": MESH}
    (out / "truth.json").write_text(json.dumps(truth, indent=1), encoding="utf-8")
    return {"step": step, "assem": assem, "truth": truth, "spec": spec, "root": out}


if __name__ == "__main__":  # pragma: no cover
    r = make_all(Path(sys.argv[1]))
    print(json.dumps({k: str(v) for k, v in r.items() if k in ("step", "assem")}, indent=1))
