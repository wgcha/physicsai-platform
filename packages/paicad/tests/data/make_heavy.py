"""Load-test cushion generator for ``paicad extract`` performance (test-only, nothing committed).

One solid with a grid of ribs (some with filleted vertical corners), drafted pockets (some with filleted
corners), through holes and bottom pockets - many faces like a real EPS cushion (default about 1,700 faces).

Usage: python make_heavy.py OUT_STEP [--nx N] [--ny N]
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class HeavySpec:
    nx: int = 18  # grid cells in x
    ny: int = 12  # grid cells in y
    cell: float = 50.0
    T: float = 40.0
    rib_t: float = 6.0
    rib_h: float = 12.0
    pocket_d: float = 10.0
    draft_deg: float = 1.0
    hole_r: float = 3.0
    fillet_r: float = 2.0
    name: str = "CUSH_H"


def build_body(spec: HeavySpec | None = None):
    """Return (name, build123d Solid)."""
    from build123d import Align, Axis, Box, Compound, Cylinder, Pos, Rectangle, extrude, fillet

    s = spec or HeavySpec()
    mn = (Align.MIN, Align.MIN, Align.MIN)
    L, W = s.nx * s.cell, s.ny * s.cell
    body = Box(L, W, s.T, align=mn)
    adds, cuts = [], []
    c = s.cell
    for i in range(s.nx):
        for j in range(s.ny):
            x0, y0 = i * c, j * c
            k = (i + j) % 3
            if k == 0:  # rib (every other one with filleted vertical corners)
                rib = Box(s.rib_t, 0.6 * c, s.rib_h, align=mn)
                if (i // 3 + j) % 2:
                    rib = fillet(rib.edges().filter_by(Axis.Z), 0.4 * s.rib_t)
                adds.append(Pos(x0 + 0.5 * c - 0.5 * s.rib_t, y0 + 0.2 * c, s.T) * rib)
            elif k == 1:  # drafted pocket from the top
                pk = extrude(Rectangle(0.6 * c, 0.6 * c), amount=s.pocket_d, dir=(0, 0, -1), taper=s.draft_deg)
                if (i + 2 * j) % 2:
                    pk = fillet(pk.edges().filter_by(lambda e: abs(e.tangent_at(0.5).Z) > 0.9), s.fillet_r)
                cuts.append(Pos(x0 + 0.5 * c, y0 + 0.5 * c, s.T) * pk)
            else:  # through holes + a bottom pocket
                for dx, dy in ((0.25, 0.25), (0.75, 0.25), (0.25, 0.75), (0.75, 0.75)):
                    cuts.append(Pos(x0 + dx * c, y0 + dy * c, 0) * Cylinder(s.hole_r, s.T, align=(Align.CENTER, Align.CENTER, Align.MIN)))
                cuts.append(Pos(x0 + 0.4 * c, y0 + 0.4 * c, 0) * Box(0.2 * c, 0.2 * c, 0.3 * s.T, align=mn))
    body = body + Compound(children=adds)
    body = body - Compound(children=cuts)
    return s.name, body.solids()[0]


def write(path: Path, spec: HeavySpec | None = None) -> Path:
    from build123d import Compound, export_step

    name, solid = build_body(spec)
    solid.label = name
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    export_step(Compound(children=[solid]), str(path))
    return path


if __name__ == "__main__":
    args = sys.argv[1:]
    sp = HeavySpec()
    if "--nx" in args:
        sp.nx = int(args[args.index("--nx") + 1])
    if "--ny" in args:
        sp.ny = int(args[args.index("--ny") + 1])
    p = write(Path(args[0]), sp)
    print(p)
