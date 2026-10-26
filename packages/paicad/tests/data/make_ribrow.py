"""Rib row golden set (rib-gap.md section 10): parallel free-standing rib rows for RIB_PITCH_U/V.

Test-only (``test`` extra: build123d, gmsh). Two named bodies ROW_L / ROW_R (= mirror about x = 0), each a base plate
with:

* U rows (thickness along x): U1 = 3 ribs (odd), U2 = 5 ribs (odd, pitches symmetric about the plate center so the
  same-row mirror rule is exercised), U3 = 4 ribs (even);
* one V row (thickness along y): V1 = 3 ribs;
* an end wall along x = 0 (end obstacle of the U rows), a pillar (not slender), a partition rib touching the wall
  (not a rib: ``cap_not_convex``) and a through hole between the first two ribs of U1 (path collision).

``build_bodies(spec)`` rebuilds the bodies with any rib centers (the truth of an update sample). ``make_all`` also
meshes the bodies (gmsh tetra4) and writes the synthetic assembly like ``make_synthetic.make_all``.

Usage: python make_ribrow.py OUT_DIR
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np

BASE_ROWS = {
    # row id: (thickness axis, rib centers, rib extent along the other in-plane axis)
    "U1": ("x", (24.0, 42.0, 62.0), (12.0, 42.0)),
    "U2": ("x", (42.0, 60.0, 80.0, 100.0, 118.0), (52.0, 82.0)),
    "U3": ("x", (24.0, 40.0, 58.0, 74.0), (92.0, 112.0)),
    "V1": ("y", (14.0, 32.0, 52.0), (130.0, 156.0)),
}


@dataclass
class RibRowSpec:
    L: float = 160.0  # x
    W: float = 120.0  # y
    T: float = 8.0  # plate thickness (z)
    rib_h: float = 10.0
    rib_t: float = 6.0
    rows: dict = field(default_factory=lambda: dict(BASE_ROWS))
    thickness: dict = field(default_factory=dict)  # (row id, 1-based rib index) -> thickness (default rib_t)
    wall_t: float = 4.0  # end wall x 0..wall_t, full width
    wall_h: float = 14.0
    pillar: tuple | None = (140.0, 100.0, 6.0)  # x, y center, side
    partition: tuple | None = (4.0, 16.0, 114.0, 118.0)  # x0, x1, y0, y1 (touches the wall)
    hole: tuple | None = (33.0, 27.0, 2.0)  # x, y, radius
    extra_boxes: tuple = ()  # (x0, y0, x1, y1, height) boxes on the plate (recognition variants)
    extra_polys: tuple = ()  # (((x, y), ...), height) vertical prisms on the plate (recognition variants)
    offset_x: float = -200.0
    names: tuple = ("ROW_L", "ROW_R")
    mirror: bool = True


def rib_boxes(spec: RibRowSpec) -> list[tuple[float, float, float, float]]:
    out = []
    for rid, (ax, centers, (b0, b1)) in spec.rows.items():
        for i, c in enumerate(centers, 1):
            t = spec.thickness.get((rid, i), spec.rib_t)
            out.append((c - t / 2, b0, c + t / 2, b1) if ax == "x" else (b0, c - t / 2, b1, c + t / 2))
    return out


def build_bodies(spec: RibRowSpec):
    """[(name, build123d Solid)]: ROW_L and (``mirror``) its mirror ROW_R."""
    from build123d import Align, Box, Cylinder, Plane, Polygon, Pos, extrude, mirror

    s = spec
    mn = (Align.MIN, Align.MIN, Align.MIN)
    body = Box(s.L, s.W, s.T, align=mn)
    if s.wall_t:
        body = body + Pos(0, 0, s.T) * Box(s.wall_t, s.W, s.wall_h, align=mn)
    for x0, y0, x1, y1 in rib_boxes(s):
        body = body + Pos(x0, y0, s.T) * Box(x1 - x0, y1 - y0, s.rib_h, align=mn)
    if s.pillar:
        px, py, a = s.pillar
        body = body + Pos(px - a / 2, py - a / 2, s.T) * Box(a, a, s.rib_h, align=mn)
    if s.partition:
        x0, x1, y0, y1 = s.partition
        body = body + Pos(x0, y0, s.T) * Box(x1 - x0, y1 - y0, s.rib_h, align=mn)
    for x0, y0, x1, y1, h in s.extra_boxes:
        body = body + Pos(x0, y0, s.T) * Box(x1 - x0, y1 - y0, h, align=mn)
    for pts, h in s.extra_polys:
        body = body + extrude(Pos(0, 0, s.T) * Polygon(*pts, align=None), amount=h)
    if s.hole:
        hx, hy, r = s.hole
        body = body - Pos(hx, hy, 0) * Cylinder(r, s.T, align=(Align.CENTER, Align.CENTER, Align.MIN))
    left = (Pos(s.offset_x, 0, 0) * body).solids()[0]
    out = [(s.names[0], left)]
    if s.mirror:
        out.append((s.names[1], mirror(left, about=Plane.YZ).solids()[0]))
    return out


def with_centers(spec: RibRowSpec, row: str, centers) -> RibRowSpec:
    rows = dict(spec.rows)
    ax, _, ext = rows[row]
    rows[row] = (ax, tuple(float(c) for c in centers), ext)
    return replace(spec, rows=rows)


def write_step(path: Path, bodies) -> None:
    from data.make_synthetic import write_step as ws

    ws(path, bodies)


def make_all(out: Path, spec: RibRowSpec | None = None) -> dict:
    from data.make_synthetic import BASELINE_INC, RENUM_CSV, mesh_step, write_assembly

    spec = spec or RibRowSpec()
    out = Path(out)
    bodies = build_bodies(spec)
    step = out / "cad" / "ribrow.step"
    write_step(step, bodies)
    bbs = []
    for _, sld in bodies:
        bb = sld.bounding_box()
        bbs.append(np.array([bb.min.X, bb.min.Y, bb.min.Z, bb.max.X, bb.max.Y, bb.max.Z]))
    names = [n for n, _ in bodies]
    meshes = mesh_step(step, names, bbs)
    assem = out / "assem"
    lo, hi = np.min(bbs, axis=0), np.max(bbs, axis=0)
    info = write_assembly(assem, names, meshes, np.array([lo[0] - 10, lo[1] - 10, hi[3] + 10, hi[4] + 10]))
    return {"step": step, "assem": assem, "baseline": assem / BASELINE_INC, "renum": assem / RENUM_CSV, "names": names, "renum_rows": info["renum"], "spec": spec}


if __name__ == "__main__":  # pragma: no cover
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    r = make_all(Path(sys.argv[1]))
    print(json.dumps({k: str(v) for k, v in r.items() if k in ("step", "assem", "baseline", "renum")}, indent=1))
