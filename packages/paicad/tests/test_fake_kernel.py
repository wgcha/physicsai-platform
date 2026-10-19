"""tag/extract logic runs on the kernel protocol alone (fake kernel, no OCCT) - contract section 18.9."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
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
