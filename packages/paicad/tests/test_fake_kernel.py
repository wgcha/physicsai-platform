"""tag/extract logic runs on the kernel protocol alone (fake kernel, no OCCT) - contract section 18.9."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from fake_kernel import FakeBox
from paicad import options
from paicad.features import finalize, recognize_body
from paicad.kernel.base import BodyGeom
from paicad.tag import (
    KIND_EDGE,
    KIND_FACE,
    KIND_UNMATCHED,
    KIND_VERTEX,
    classify_points,
)

TESTS = Path(__file__).resolve().parent
SRC = TESTS.parent / "src"


def test_fake_is_a_body_geom():
    assert isinstance(FakeBox("B", [0, 0, 0], [10, 20, 30]), BodyGeom)


def test_classify_points_on_fake_box():
    box = FakeBox("B", [0, 0, 0], [10, 20, 30])
    pts = np.array(
        [
            [0, 0, 0],  # vertex
            [10.02, 20, 30],  # vertex within tol
            [5, 0, 0],  # edge x
            [0, 20, 15],  # edge z
            [5, 10, 0],  # face z-
            [5, 10, 30.03],  # face z+ within tol
            [5, 10, 31],  # off surface
        ],
        dtype=float,
    )
    kind, ent, uv, dist = classify_points(box, pts, 0.05)
    assert kind.tolist() == [KIND_VERTEX, KIND_VERTEX, KIND_EDGE, KIND_EDGE, KIND_FACE, KIND_FACE, KIND_UNMATCHED]
    assert abs(uv[2, 0] - 0.5) < 1e-12 and abs(dist[5] - 0.03) < 1e-9
    assert np.allclose(uv[4], [0.5, 0.5])


def test_recognize_thickness_on_fake_box():
    box = FakeBox("BOX", [0, 0, 0], [10, 20, 30])
    opts = options.load(None)
    feats = recognize_body(box, opts)
    assert sorted(f.nominal for f in feats if f.type == "THICKNESS") == [10.0, 20.0, 30.0]
    ordered, groups, _ = finalize([("BOX", "BOX", box, feats)], opts, {"BOX": 0.05})
    assert [f.name for f in ordered] == ["BOX_THK_1", "BOX_THK_2", "BOX_THK_3"]
    assert all(f.ref["rule"] == "center_distance" and f.ref["provisional"] for f in ordered)
    assert groups == []


def test_protocol_modules_do_not_load_ocp():
    """features/tag/mesh + fake kernel run in a fresh interpreter without importing OCP."""
    code = (
        "import sys; sys.path[:0] = [%r, %r];"
        "import paicad.features, paicad.tag, paicad.mesh.radioss, paicad.meshgeom, fake_kernel;"
        "from paicad import options;"
        "b = fake_kernel.FakeBox('B', [0, 0, 0], [1, 2, 3]);"
        "assert len(paicad.features.recognize_body(b, options.load(None))) == 3;"
        "print(any(m == 'OCP' or m.startswith('OCP.') for m in sys.modules))"
    ) % (str(SRC), str(TESTS))
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "False"


# ------------------------------------------------------------- morph / check logic on the fake kernel (stage 2)
def _box_mesh(lo, hi, n):
    """Structured tetra4 mesh of a box: every cell split into 6 equal-volume (Kuhn) tetrahedra."""
    from paicad.mesh.radioss import ElementBlock, RadMesh

    axes = [np.linspace(lo[k], hi[k], n[k] + 1) for k in range(3)]
    grid = np.array(np.meshgrid(*axes, indexing="ij")).reshape(3, -1).T
    idx = np.arange(len(grid)).reshape(n[0] + 1, n[1] + 1, n[2] + 1)
    kuhn = [(0, 1, 3, 7), (0, 3, 2, 7), (0, 2, 6, 7), (0, 6, 4, 7), (0, 4, 5, 7), (0, 5, 1, 7)]
    tets = []
    for i in range(n[0]):
        for j in range(n[1]):
            for k in range(n[2]):
                c = [idx[i + a, j + b, k + d] for a in (0, 1) for b in (0, 1) for d in (0, 1)]
                tets += [[c[q] for q in t] for t in kuhn]
    tets = np.array(tets, dtype=np.int64)
    p = grid[tets]
    vol = np.einsum("ij,ij->i", np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0]), p[:, 3] - p[:, 0])
    tets[vol < 0] = tets[vol < 0][:, [0, 2, 1, 3]]
    node_ids = np.arange(1, len(grid) + 1, dtype=np.int64)
    blk = ElementBlock("TETRA4", 1, np.arange(1, len(tets) + 1, dtype=np.int64), tets + 1)
    return RadMesh(node_ids, grid, [blk])


def test_morph_and_check_on_fake_kernel():
    """Boundary nodes follow the stretched box, the interior solve reproduces the linear field, check measures it."""
    from paicad.check import check_core
    from paicad.meshdata import TagData, components_from_tag
    from paicad.morph import SampleSet, morph_core
    from paicad.mesh.radioss import skin_triangles

    lo, hi = [0.0, 0.0, 0.0], [10.0, 20.0, 30.0]
    mesh = _box_mesh(lo, hi, (2, 3, 4))
    nominal, sample = FakeBox("B", lo, hi), FakeBox("B", lo, [12.0, 20.0, 30.0])
    bnodes = np.unique(skin_triangles(mesh.blocks[0].conn)) - 1
    kind = np.zeros(len(mesh.node_ids), dtype=np.int8)
    ent = np.full(len(mesh.node_ids), -1, dtype=np.int32)
    uv = np.zeros((len(mesh.node_ids), 2))
    k, e, u, _ = classify_points(nominal, mesh.xyz[bnodes], 1e-6)
    kind[bnodes], ent[bnodes], uv[bnodes] = k, e, u
    assert (kind[bnodes] > 0).all() and (kind == KIND_VERTEX).sum() == 8
    tag = TagData({"parts": [{"part": "P", "body": "B", "elem_range": [1, len(mesh.blocks[0].ids)]}]}, mesh.node_ids, np.zeros(len(kind), np.int32), kind, ent, uv)
    comps = components_from_tag(mesh, tag)
    topo = nominal.topology()
    fmap = {"B": {k: {str(i): i for i in range(1, n + 1)} for k, n in (("F", 6), ("E", len(topo.edges)), ("V", 8))}}
    opts = options.load(None)
    res = morph_core(mesh, comps, SampleSet({"B": sample}, fmap, {}), opts)
    want = mesh.xyz * np.array([1.2, 1.0, 1.0])
    assert np.abs(res.xyz - want).max() < 1e-6  # exact for a uniform stretch of equal-volume tetrahedra
    assert res.parts[0]["solver"]["method"] == "cg" and res.parts[0]["moved_nodes"] > 0
    doc = {
        "bodies": [{"body": "B", "part": "P"}],
        "groups": [],
        "features": [{"name": "B_THK_1", "type": "THICKNESS", "body": "B", "nominal": 10.0, "group": None, "measure": {"method": "face_distance", "faces": ["F1", "F2"]}}],
    }
    c = check_core(mesh, res.xyz, comps, SampleSet({"B": sample}, fmap, {}), doc, {"B_THK_1": 12.0}, opts, None, Path("none"), full=False)
    item = c.checks["param"]["items"][0]
    assert item["measured"] == pytest.approx(12.0) and c.checks["deviation"]["max_mm"] < 1e-6
    assert c.checks["quality"]["inverted"] == 0 and c.checks["interference"]["status"] == "NOT_EVALUATED"
    c2 = check_core(mesh, res.xyz, comps, SampleSet({"B": sample}, fmap, {}), doc, {"B_THK_1": 11.0}, opts, None, Path("none"), full=False)
    assert c2.code == "GEOM_PARAM_MISMATCH" and c2.checks["param"]["status"] == "FAIL"


def test_stage2_modules_do_not_load_ocp():
    code = (
        "import sys; sys.path[:0] = [%r];"
        "import paicad.update, paicad.morph, paicad.check, paicad.sweep, paicad.measure, paicad.quality, paicad.tie;"
        "print(any(m == 'OCP' or m.startswith('OCP.') for m in sys.modules))"
    ) % (str(SRC),)
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "False"
