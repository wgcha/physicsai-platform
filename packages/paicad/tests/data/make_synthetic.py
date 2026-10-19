"""Development golden set generator (contract section 9 stage 0(a), section 7.8).

Test-only (``test`` extra: build123d, gmsh). Produces, into an output folder:

* ``cad/cushion.step``   - two named bodies (CUSH_L, CUSH_R = mirror) with ribs, a drafted pocket,
                           a through hole and a small fillet;
* ``truth.json``         - design dimensions (ground truth for extract);
* ``assem/``             - synthetic assembly: starter ``MODEL_0000.rad`` (#include), baseline
                           include (``/NODE`` + ``/TETRA4`` only), a product shell plate include,
                           synthetic ``RENUM_INIT.csv`` (start number 3000001).

Nothing generated here is committed to the repository.

Usage: python make_synthetic.py OUT_DIR
"""

from __future__ import annotations

import json
import math
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

BASELINE_INC = "104_replace_node_elem.inc"
RENUM_CSV = "RENUM_INIT.csv"
STARTER = "MODEL_0000.rad"
PRODUCT_INC = "product.inc"
START_ID = 3000001

# gmsh baseline parameters (section 7.8): avg 10, min 1, grade 1.5, 45 deg per element, curvature min 5 mm
MESH = {"size_avg": 10.0, "size_min": 1.0, "grade": 1.5, "curv_angle_deg": 45.0, "curv_min_mm": 5.0}


@dataclass
class CushionSpec:
    L: float = 120.0  # x
    W: float = 80.0  # y
    T: float = 20.0  # base thickness (z)
    rib_x: tuple[float, float] = (25.0, 89.0)  # rib x-min positions (mirror pair about L/2)
    rib_t: float = 6.0
    rib_y: tuple[float, float] = (15.0, 65.0)
    rib_h: float = 15.0
    pocket_x: tuple[float, float] = (45.0, 75.0)
    pocket_y: tuple[float, float] = (20.0, 60.0)
    pocket_d: float = 8.0
    draft_deg: float = 1.0
    hole_xy: tuple[float, float] = (12.0, 12.0)
    hole_r: float = 5.0
    fillet_r: float = 1.0  # vertical edge at (L, W): small fillet near the mesh min size
    offset_x: float = -150.0  # CUSH_L placement; CUSH_R = mirror about x = 0
    names: tuple[str, str] = ("CUSH_L", "CUSH_R")
    extra: dict = field(default_factory=dict)


def build_bodies(spec: CushionSpec):
    """Return [(name, build123d Solid)] for CUSH_L and its mirror CUSH_R."""
    from build123d import (
        Align,
        Axis,
        Box,
        Cylinder,
        Plane,
        Pos,
        Rectangle,
        extrude,
        fillet,
        mirror,
    )

    s = spec
    mn = (Align.MIN, Align.MIN, Align.MIN)
    base = Box(s.L, s.W, s.T, align=mn)
    corner = base.edges().filter_by(Axis.Z).group_by(Axis.X)[-1].group_by(Axis.Y)[-1]
    base = fillet(corner, s.fillet_r)
    for x0 in s.rib_x:
        base = base + Pos(x0, s.rib_y[0], s.T) * Box(s.rib_t, s.rib_y[1] - s.rib_y[0], s.rib_h, align=mn)
    px, py = s.pocket_x, s.pocket_y
    pocket = extrude(
        Pos(0.5 * (px[0] + px[1]), 0.5 * (py[0] + py[1]), s.T) * Rectangle(px[1] - px[0], py[1] - py[0]),
        amount=s.pocket_d,
        dir=(0, 0, -1),
        taper=s.draft_deg,
    )
    base = base - pocket
    base = base - Pos(s.hole_xy[0], s.hole_xy[1], 0) * Cylinder(s.hole_r, s.T, align=(Align.CENTER, Align.CENTER, Align.MIN))
    left = (Pos(s.offset_x, 0, 0) * base).solids()[0]
    right = mirror(left, about=Plane.YZ).solids()[0]
    return [(s.names[0], left), (s.names[1], right)]


def write_step(path: Path, bodies) -> None:
    from build123d import Compound, export_step

    kids = []
    for name, solid in bodies:
        solid.label = name
        kids.append(solid)
    path.parent.mkdir(parents=True, exist_ok=True)
    export_step(Compound(children=kids), str(path))


def truth(spec: CushionSpec) -> dict:
    """Ground-truth features per body (design intent). Pocket width = width at mid-depth (drafted walls)."""
    s = spec
    tan = math.tan(math.radians(s.draft_deg))
    pw = [s.pocket_x[1] - s.pocket_x[0] - s.pocket_d * tan, s.pocket_y[1] - s.pocket_y[0] - s.pocket_d * tan]
    common = {
        "THICKNESS": sorted([s.T, s.W, s.L]),
        "POCKET_DEPTH": [s.pocket_d],
        "POCKET_WIDTH": sorted(pw),
        "RIB_THICKNESS": [s.rib_t, s.rib_t],
        "RIB_HEIGHT": [s.rib_h, s.rib_h],
        "HOLE_RADIUS": [s.hole_r],
        "HOLE_POS_V": [s.hole_xy[1]],
        "FILLET_RADIUS": [s.fillet_r],
    }
    left = dict(common, HOLE_POS_U=[s.hole_xy[0]])
    right = dict(common, HOLE_POS_U=[s.L - s.hole_xy[0]])  # mirrored: measured from the new bbox minimum
    groups = {
        # mirror L<->R for every feature type except HOLE_POS_U (12 vs 108); ribs also mirror inside a body
        "count": 11,
        "rib_members": 4,
    }
    return {
        "bodies": {s.names[0]: left, s.names[1]: right},
        "groups": groups,
        "parameters": 13,  # 11 group representatives + 2 ungrouped HOLE_POS_U
        "spec": asdict(s),
        "mesh": MESH,
        "bottom_contact": True,
    }


def mesh_step(step: Path, names: list[str], bboxes: list[np.ndarray]) -> list[tuple[np.ndarray, np.ndarray]]:
    """gmsh tetra4 mesh per body. Returns [(xyz[n,3], tets[m,4] local 0-based)] in ``names`` order."""
    import gmsh

    gmsh.initialize(["-noenv"], readConfigFiles=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setNumber("General.NumThreads", 1)
        gmsh.model.add("cushion")
        ents = gmsh.model.occ.importShapes(str(step))
        gmsh.model.occ.synchronize()
        gmsh.option.setNumber("Mesh.MeshSizeMax", MESH["size_avg"])
        gmsh.option.setNumber("Mesh.MeshSizeMin", MESH["size_min"])
        gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", round(360.0 / MESH["curv_angle_deg"]))
        gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 1)
        gmsh.option.setNumber("Mesh.SmoothRatio", MESH["grade"])
        gmsh.option.setNumber("Mesh.Algorithm", 6)
        gmsh.option.setNumber("Mesh.Algorithm3D", 1)
        gmsh.option.setNumber("Mesh.Optimize", 1)
        gmsh.option.setNumber("Mesh.ElementOrder", 1)
        gmsh.option.setNumber("Mesh.RandomSeed", 1)
        gmsh.model.mesh.generate(3)
        node_tags, coords, _ = gmsh.model.mesh.getNodes()
        coords = np.asarray(coords).reshape(-1, 3)
        pos = {int(t): i for i, t in enumerate(node_tags)}
        vols = [t for d, t in gmsh.model.getEntities(3)]
        by_vol = {}
        for v in vols:
            bb = np.array(gmsh.model.getBoundingBox(3, v))
            k = int(np.argmin([np.abs(bb - b).max() for b in bboxes]))
            by_vol[k] = v
        out = []
        for k in range(len(names)):
            et, _, en = gmsh.model.mesh.getElements(3, by_vol[k])
            tets = None
            for t, conn in zip(et, en):
                if t == 4:
                    tets = np.asarray(conn, dtype=np.int64).reshape(-1, 4)
            if tets is None:
                raise RuntimeError("no tetra4 elements")
            used = np.unique(tets)
            local = {int(t): i for i, t in enumerate(used)}
            xyz = coords[[pos[int(t)] for t in used]]
            lt = np.vectorize(local.__getitem__)(tets)
            a, b, c, d = (xyz[lt[:, i]] for i in range(4))
            vol = np.einsum("ij,ij->i", np.cross(b - a, c - a), d - a)
            neg = vol < 0
            lt[neg] = lt[neg][:, [0, 2, 1, 3]]
            out.append((xyz, lt))
        del ents
        return out
    finally:
        gmsh.finalize()


def write_assembly(folder: Path, names: list[str], meshes, product_bbox: np.ndarray) -> dict:
    folder.mkdir(parents=True, exist_ok=True)
    renum = []
    node_lines = ["/NODE", "#  node_ID                   X                   Y                   Z"]
    elem_blocks = []
    nstart = estart = START_ID
    for k, (name, (xyz, tets)) in enumerate(zip(names, meshes)):
        renum.append((name, nstart, estart))
        for i, p in enumerate(xyz):
            node_lines.append(f"{nstart + i:10d}{p[0]:20.10f}{p[1]:20.10f}{p[2]:20.10f}")
        lines = [f"/TETRA4/{k + 1}", "#  elem_ID   node_ID1  node_ID2  node_ID3  node_ID4"]
        for j, t in enumerate(tets):
            lines.append(f"{estart + j:10d}" + "".join(f"{nstart + int(x):10d}" for x in t))
        elem_blocks.append("\n".join(lines))
        step_n = 100000 * (len(xyz) // 100000 + 1)
        step_e = 100000 * (len(tets) // 100000 + 1)
        nstart += step_n
        estart += step_e
    inc = "#RADIOSS include: synthetic cushion baseline (paicad golden)\n" + "\n".join(node_lines) + "\n" + "\n".join(elem_blocks) + "\n"
    (folder / BASELINE_INC).write_bytes(inc.encode("ascii"))
    (folder / RENUM_CSV).write_text("part,node_start,elem_start\n" + "".join(f"{n},{a},{b}\n" for n, a, b in renum), encoding="utf-8")
    # product: shell plate on z = 0 under both cushions (bottom faces are contact faces)
    x0, y0, x1, y1 = product_bbox
    nx, ny = int(round((x1 - x0) / 10.0)), int(round((y1 - y0) / 10.0))
    plines = ["/NODE"]
    nid = 1
    ids = np.zeros((nx + 1, ny + 1), dtype=int)
    for i in range(nx + 1):
        for j in range(ny + 1):
            ids[i, j] = nid
            plines.append(f"{nid:10d}{x0 + i * (x1 - x0) / nx:20.10f}{y0 + j * (y1 - y0) / ny:20.10f}{0.0:20.10f}")
            nid += 1
    plines.append("/SHELL/100")
    eid = 1
    for i in range(nx):
        for j in range(ny):
            plines.append(f"{eid:10d}{ids[i, j]:10d}{ids[i + 1, j]:10d}{ids[i + 1, j + 1]:10d}{ids[i, j + 1]:10d}")
            eid += 1
    (folder / PRODUCT_INC).write_text("\n".join(plines) + "\n", encoding="ascii")
    parts = "".join(f"/PART/{k + 1}\n{n}\n         {k + 1}         1\n" for k, n in enumerate(names))
    starter = (
        "#RADIOSS STARTER\n/BEGIN\nMODEL\n      2024         0\n                  Mg                  mm                   s\n"
        "                  Mg                  mm                   s\n"
        f"{parts}/PART/100\nPRODUCT\n       100         2\n#include {BASELINE_INC}\n#include {PRODUCT_INC}\n/END\n"
    )
    (folder / STARTER).write_text(starter, encoding="ascii")
    return {"renum": renum}


def make_all(out: Path, spec: CushionSpec | None = None) -> dict:
    spec = spec or CushionSpec()
    out = Path(out)
    bodies = build_bodies(spec)
    step = out / "cad" / "cushion.step"
    write_step(step, bodies)
    bbs = []
    for _, s in bodies:
        bb = s.bounding_box()
        bbs.append(np.array([bb.min.X, bb.min.Y, bb.min.Z, bb.max.X, bb.max.Y, bb.max.Z]))
    names = [n for n, _ in bodies]
    meshes = mesh_step(step, names, bbs)
    assem = out / "assem"
    lo = np.min(bbs, axis=0)
    hi = np.max(bbs, axis=0)
    info = write_assembly(assem, names, meshes, np.array([lo[0] - 10, lo[1] - 10, hi[3] + 10, hi[4] + 10]))
    t = truth(spec)
    t["renum"] = info["renum"]
    (out / "truth.json").write_text(json.dumps(t, indent=1), encoding="utf-8")
    shell = write_shell_assembly(out / "assem_shell")
    return {
        "step": step,
        "assem": assem,
        "assem_shell": shell["folder"],
        "baseline": assem / BASELINE_INC,
        "renum": assem / RENUM_CSV,
        "truth": t,
        "meshes": meshes,
        "names": names,
    }


# ---------------------------------------------------------------- stage 3S: shell properties
SHELL_STARTER = "SHELL_0000.rad"
SHELL_MESH = "shell_mesh.inc"
SHELL_PROPS = "props/shell_props.inc"  # subfolder + CRLF line ends


def _prop_type1(pid: int, title: str, thick: float | None, kw: str = "TYPE1", free: bool = False) -> list[str]:
    card3 = f"{5:10d}{0:10d}{thick:20.4f}{0.0:20.4f}{'':10s}{1:10d}{1:10d}" if not free else f"5 0 {thick!r} 0.0 1 1"
    return [
        f"/PROP/{kw}/{pid}",
        title,
        "#   Ishell    Ismstr     Ish3n    Idrill                            P_thick_fail",
        f"{24:10d}{0:10d}{0:10d}{0:10d}{'':40s}{0:10d}",
        "#                 hm                  hf                  hr                  dm                  dn",
        "",  # blank data line = all defaults
        "#        N   Istrain               Thick              Ashear              Ithick     Iplas",
        card3,
    ]


def write_shell_assembly(folder: Path) -> dict:
    """Synthetic assembly with shell PROPs (section 11.1 cases), pure Python (no gmsh/CAD).

    PROP 1 Bracket (TYPE1, 1.2, CRLF file in a subfolder, PART 10)
    PROP 2 Cover (/PROP/SHELL, 0.8, shared by PART 11 and 12 -> PROP_SHARED_BY_PARTS)
    PROP 3 Panel (TYPE1, 2.0, PART 13 /SHELL elements carry their own thickness -> PROP_OVERRIDDEN_BY_ELEMENT)
    PROP 4 Laminate (/PROP/TYPE9 -> unsupported)
    PROP 5 untitled (TYPE1, thickness 0 -> PROP_THICKNESS_INVALID, name PROP5_SHELL_T)
    PROP 6 Cover (TYPE1, free format card, PART 14 /SH3N with element thickness 0 -> name conflict with PROP 2)
    """
    folder = Path(folder)
    (folder / "props").mkdir(parents=True, exist_ok=True)
    props1 = ["#RADIOSS include: shell properties (paicad golden)"] + _prop_type1(1, "Bracket", 1.2)
    (folder / SHELL_PROPS).write_bytes(("\r\n".join(props1) + "\r\n").encode("ascii"))
    lam = ["/PROP/TYPE9/4", "Laminate", "#   Ishell    Ismstr     Ish3n", f"{24:10d}{0:10d}{0:10d}", "", f"{5:10d}{0:10d}{1.5:20.4f}"]
    parts = [(10, "BRACKET", 1), (11, "COVER_A", 2), (12, "COVER_B", 2), (13, "PANEL", 3), (14, "LID", 6), (15, "SKIN", 4), (16, "DUMMY", 5)]
    part_lines = []
    for pid, title, prop in parts:
        part_lines += [f"/PART/{pid}", title, "#  prop_ID    mat_ID", f"{prop:10d}{1:10d}"]
    starter = (
        ["#RADIOSS STARTER", "/BEGIN", "SHELLS", "      2024         0"]
        + part_lines
        + _prop_type1(2, "Cover", 0.8, kw="SHELL")
        + _prop_type1(3, "Panel", 2.0)
        + lam
        + _prop_type1(5, "", 0.0)
        + _prop_type1(6, "Cover", 1.5, free=True)
        + [f"#include {SHELL_PROPS}", f"#include {SHELL_MESH}", "/END"]
    )
    (folder / SHELL_STARTER).write_text("\n".join(starter) + "\n", encoding="ascii")
    nodes = ["/NODE"]
    for i in range(1, 13):
        nodes.append(f"{i:10d}{float(i % 4) * 10:20.10f}{float(i // 4) * 10:20.10f}{0.0:20.10f}")
    mesh = nodes
    mesh += ["/SHELL/10", f"{1:10d}{1:10d}{2:10d}{6:10d}{5:10d}"]  # no phi / thickness columns
    mesh += ["/SHELL/11", f"{2:10d}{2:10d}{3:10d}{7:10d}{6:10d}{'':10s}{0.0:20.4f}{0.0:20.4f}"]
    mesh += ["/SHELL/12", f"{3:10d}{3:10d}{4:10d}{8:10d}{7:10d}"]
    mesh += ["/SHELL/13", f"{4:10d}{5:10d}{6:10d}{10:10d}{9:10d}{'':10s}{0.0:20.4f}{2.5:20.4f}", f"{5:10d}{6:10d}{7:10d}{11:10d}{10:10d}{'':10s}{0.0:20.4f}{2.5:20.4f}"]
    mesh += ["/SH3N/14", f"{6:10d}{7:10d}{8:10d}{12:10d}{'':10s}{'':10s}{0.0:20.4f}{0.0:20.4f}"]
    mesh += ["/SHELL/15", f"{7:10d}{9:10d}{10:10d}{11:10d}{12:10d}"]
    (folder / SHELL_MESH).write_text("\n".join(mesh) + "\n", encoding="ascii")
    return {"folder": folder, "starter": folder / SHELL_STARTER, "props_file": folder / SHELL_PROPS, "mesh": folder / SHELL_MESH}


if __name__ == "__main__":  # pragma: no cover
    r = make_all(Path(sys.argv[1]))
    print(json.dumps({k: str(v) for k, v in r.items() if k in ("step", "assem", "baseline", "renum")}, indent=1))
