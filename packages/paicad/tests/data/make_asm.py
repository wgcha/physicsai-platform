"""Synthetic assemblies for the assembly match tests (asm-match.md V-AM-*), pure Python (nothing committed).

Layout of :func:`write_split` (the user's file organisation, asm-match.md section 1.1, file names carry no meaning):

* ``MODEL_0000.rad`` - starter: ``/BEGIN``, ``#include 101_parts.inc``, ``#include 102_parts_node_element.inc``,
  ``#include sub/103_more.inc``, ``/END``
* ``101_parts.inc`` - ``/PART`` cards (cushions + product), ``/PROP``, ``/MAT``, ``/INTER/TYPE2`` on product sets,
  ``/GRNOD/NODE``, ``/SURF/SEG``
* ``102_parts_node_element.inc`` - ``/NODE`` (first half of cushion 1 mixed with the product nodes),
  ``/TETRA4/<pid1>`` (first half), product ``/SHELL``
* ``sub/103_more.inc`` - ``/NODE`` (rest of cushion 1 + cushion 2), ``/TETRA4/<pid1>`` (rest), ``/TETRA4/<pid2>``
* ``unused.inc`` - not included (``ASM_FILE_UNUSED``)
"""

from __future__ import annotations

import json
from itertools import permutations
from pathlib import Path

import numpy as np

PID = (3000001, 3000002)
NODE_START = (3000001, 3100001)
ELEM_START = (3000001, 3100001)
PRODUCT_PID = 2001
SPRING_PID = 2002
STARTER = "MODEL_0000.rad"
PARTS_INC = "101_parts.inc"
MESH_INC = "102_parts_node_element.inc"
SUB_INC = "sub/103_more.inc"


def box_mesh(lo, hi, n) -> tuple[np.ndarray, np.ndarray]:
    """Conforming tet4 mesh of an axis-aligned box: n = (nx, ny, nz) cubes, 6 Kuhn tets per cube (positive volume)."""
    lo, hi = np.asarray(lo, float), np.asarray(hi, float)
    nx, ny, nz = n
    g = np.stack(np.meshgrid(*(np.linspace(lo[k], hi[k], n[k] + 1) for k in range(3)), indexing="ij"), axis=-1)
    xyz = g.reshape(-1, 3)

    def vid(i, j, k):
        return (i * (ny + 1) + j) * (nz + 1) + k

    tets = []
    for i in range(nx):
        for j in range(ny):
            for k in range(nz):
                for perm in permutations(range(3)):
                    p = [0, 0, 0]
                    t = [vid(i, j, k)]
                    for ax in perm:
                        p[ax] = 1
                        t.append(vid(i + p[0], j + p[1], k + p[2]))
                    tets.append(t)
    tets = np.array(tets, dtype=np.int64)
    a, b, c, d = (xyz[tets[:, q]] for q in range(4))
    neg = np.einsum("ij,ij->i", np.cross(b - a, c - a), d - a) < 0
    tets[neg] = tets[neg][:, [0, 2, 1, 3]]
    return xyz, tets


def _nl(nid: int, p) -> str:
    return f"{nid:10d}{p[0]:20.10f}{p[1]:20.10f}{p[2]:20.10f}"


def _el(eid: int, conn) -> str:
    return f"{eid:10d}" + "".join(f"{int(x):10d}" for x in conn)


def write_split(
    folder: Path,
    cushions: list[tuple[np.ndarray, np.ndarray]],
    titles=("EPS_LEFT", "EPS_RIGHT"),
    shared: bool = False,
    eol: str = "\n",
    extra_parts: str = "",
    plate: tuple[float, float, float, float] | None = None,
) -> dict:
    """Write the split assembly; ``cushions`` = [(xyz, tets 0-based)] for pid 3000001 / 3000002.
    ``shared``: a product ``/SPRING`` element joins a product node to the first cushion node (AM-8)."""
    folder = Path(folder)
    (folder / "sub").mkdir(parents=True, exist_ok=True)
    allp = np.concatenate([c[0] for c in cushions])
    x0, y0, x1, y1 = plate or (allp[:, 0].min() - 10, allp[:, 1].min() - 10, allp[:, 0].max() + 10, allp[:, 1].max() + 10)
    z0 = float(allp[:, 2].min())
    # product plate (shell) under the cushions
    nxp, nyp = 6, 4
    prod_nodes, ids = [], np.zeros((nxp + 1, nyp + 1), dtype=int)
    nid = 1
    for i in range(nxp + 1):
        for j in range(nyp + 1):
            ids[i, j] = nid
            prod_nodes.append(_nl(nid, (x0 + i * (x1 - x0) / nxp, y0 + j * (y1 - y0) / nyp, z0 - 5.0)))
            nid += 1
    shells, eid = [], 1
    for i in range(nxp):
        for j in range(nyp):
            shells.append(_el(eid, (ids[i, j], ids[i + 1, j], ids[i + 1, j + 1], ids[i, j + 1])))
            eid += 1
    # cushion lines
    c_nodes, c_elems = [], []
    for k, (xyz, tets) in enumerate(cushions):
        c_nodes.append([_nl(NODE_START[k] + i, p) for i, p in enumerate(xyz)])
        c_elems.append([_el(ELEM_START[k] + j, NODE_START[k] + t) for j, t in enumerate(tets)])
    h1n = len(c_nodes[0]) // 2
    h1e = len(c_elems[0]) // 2
    parts = []
    for k, t in enumerate(titles[: len(cushions)]):
        parts += [f"/PART/{PID[k]}", t, "#  prop_ID    mat_ID", f"{1:10d}{1:10d}"]
    parts += [f"/PART/{PRODUCT_PID}", "PRODUCT_PLATE", f"{2:10d}{2:10d}"]
    if shared:
        parts += [f"/PART/{SPRING_PID}", "PRODUCT_SPRING", f"{3:10d}{2:10d}"]
    parts += [
        "/PROP/TYPE14/1", "CUSHION_SOLID", "#   Isolid",
        f"{24:10d}",
        "/PROP/TYPE1/2", "PLATE", f"{24:10d}", "", f"{5:10d}{0:10d}{1.0:20.4f}",
        "/MAT/LAW70/1", "EPS", f"{3.0e-11:20.6e}",
        "/MAT/LAW1/2", "STEEL", f"{7.85e-9:20.6e}",
        "/GRNOD/NODE/10", "PLATE_NODES", "".join(f"{n:10d}" for n in (1, 2, 3)),
        "/SURF/SEG/20", "PLATE_SEG", _el(1, (ids[1, 1], ids[2, 1], ids[2, 2], ids[1, 2])),
        "/INTER/TYPE2/50", "PRODUCT_TIE", "#  grnd_ID   surf_ID", f"{10:10d}{20:10d}",
    ]
    if extra_parts:
        parts += extra_parts.rstrip("\n").split("\n")
    mesh = ["#RADIOSS include: nodes and elements", "/NODE"] + c_nodes[0][:h1n] + prod_nodes
    mesh += [f"/TETRA4/{PID[0]}", "#  elem_ID"] + c_elems[0][:h1e]
    mesh += [f"/SHELL/{PRODUCT_PID}"] + shells
    if shared:
        mesh += [f"/SPRING/{SPRING_PID}", _el(9001, (1, NODE_START[0]))]
    sub = ["/NODE"] + c_nodes[0][h1n:] + (c_nodes[1] if len(cushions) > 1 else [])
    sub += [f"/TETRA4/{PID[0]}"] + c_elems[0][h1e:]
    if len(cushions) > 1:
        sub += [f"/TETRA4/{PID[1]}"] + c_elems[1]
    starter = [
        "#RADIOSS STARTER", "/BEGIN", "MODEL", "      2024         0",
        "                  Mg                  mm                   s", "                  Mg                  mm                   s",
        f"#include {PARTS_INC}", f"#include {MESH_INC}", "#include sub\\103_more.inc", "/END",
    ]

    def w(rel, lines):
        (folder / rel).write_bytes((eol.join(lines) + eol).encode("ascii"))

    w(STARTER, starter)
    w(PARTS_INC, parts)
    w(MESH_INC, mesh)
    w(SUB_INC, sub)
    w("unused.inc", ["/NODE", _nl(99, (0, 0, 0))])
    return {"folder": folder, "starter": folder / STARTER, "files": [STARTER, PARTS_INC, MESH_INC, SUB_INC], "plate_nodes": len(prod_nodes)}


def features_doc(bodies: dict[str, tuple[np.ndarray, float]]) -> dict:
    """Minimal parameter_features.json (bodies only): {name: (bbox[6], volume)}."""
    return {"schema_version": 1, "bodies": [{"body": n, "volume": float(v), "bbox": [float(x) for x in bb]} for n, (bb, v) in bodies.items()], "features": [], "groups": []}


def write_json(path: Path, obj) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1), encoding="utf-8")
    return path


def write_match(path: Path, assem: Path, rows: list[dict], excluded: list[str] | None = None) -> Path:
    """Confirmed asm_match.json with the current include tree digest (what the platform writes on confirm)."""
    from paicad.mesh.asmtree import build

    idx = build(assem)
    doc = {
        "schema_version": 1,
        "engine": "native",
        "engine_version": "test",
        "match_id": "M-test",
        "cad": {"rel": "cushion.step", "sha256": None},
        "features_sha256": None,
        "unit_system": "mm-ton-s",
        "assem": {"digest": idx.digest(), "starter": idx.starter, "node_files": []},
        "rows": rows,
        "excluded_bodies": excluded or [],
        "check": None,
        "confirmed_by": "user",
        "confirmed_at": "2026-10-22T00:00:00Z",
    }
    return write_json(path, doc)
