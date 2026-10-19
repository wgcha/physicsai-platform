"""Unit tests without OCCT: body map, Radioss I/O, options, reference-face rule, CLI conventions."""

from __future__ import annotations

import json

import numpy as np
import pytest
from paicad import bodymap, options
from paicad.common import OutDir, PaicadError
from paicad.features import choose_ref, component_name, make_name
from paicad.kernel.base import FaceData
from paicad.mesh import radioss
from paicad.meshgeom import TriangleSet, point_triangle_distance

NAME_RE = r"^[A-Za-z_][A-Za-z0-9_]{0,63}$"


# ------------------------------------------------------------- body map (section 4.1)
def test_bodymap_rules_in_order():
    m = bodymap.match(["CUSH_L", "cush-r", "Top Pad", "x"], ["CUSH_L", "CUSH_R", "TOP_PAD", "SIDE"], {"x": "SIDE"})
    assert m == {"x": "SIDE", "CUSH_L": "CUSH_L", "cush-r": "CUSH_R", "Top Pad": "TOP_PAD"}


def test_bodymap_case_insensitive_before_normalized():
    assert bodymap.match(["cush_l"], ["CUSH_L"]) == {"cush_l": "CUSH_L"}
    assert bodymap.normalize("  a--b__c ") == "A_B_C"


def test_bodymap_leftovers_and_unnamed():
    with pytest.raises(PaicadError) as e:
        bodymap.match(["A", "B"], ["A", "C"])
    assert e.value.code == "GEOM_BODY_MAP_FAILED" and "B" in e.value.message and "C" in e.value.message
    with pytest.raises(PaicadError) as e:
        bodymap.match([None, "A"], ["A"])
    assert e.value.code == "GEOM_BODY_MAP_FAILED" and "per-component STEP" in e.value.message


def test_read_body_map(tmp_path):
    p = tmp_path / "bm.json"
    p.write_text(json.dumps({"schema_version": 1, "map": {"Body1": "CUSH_L"}}))
    assert bodymap.read_body_map(p) == {"Body1": "CUSH_L"}
    p.write_text("[]")
    with pytest.raises(PaicadError):
        bodymap.read_body_map(p)


# ------------------------------------------------------------- Radioss I/O
INC = (
    "#comment\r\n/NODE\r\n"
    "#  node_ID                   X                   Y                   Z\r\n"
    "         1        0.0000000000        0.0000000000        0.0000000000\r\n"
    "         2       10.0000000000        0.0000000000        0.0000000000\r\n"
    "         3        0.0000000000       10.0000000000        0.0000000000\r\n"
    "         4        0.0000000000        0.0000000000       10.0000000000\r\n"
    "         5       10.0000000000       10.0000000000       10.0000000000\r\n"
    "/TETRA4/1\r\n"
    "       101         1         2         3         4\r\n"
    "       102         2         3         4         5\r\n"
)


def test_parse_and_components(tmp_path):
    m = radioss.parse_text(INC)
    assert m.node_ids.tolist() == [1, 2, 3, 4, 5]
    assert m.blocks[0].keyword == "TETRA4" and m.blocks[0].conn.shape == (2, 4)
    comps, warns = radioss.components(m, [radioss.RenumRow("P", 1, 101, 1)])
    assert comps[0].elem_range == (101, 102) and comps[0].node_ids.tolist() == [1, 2, 3, 4, 5] and warns == []
    comps, warns = radioss.components(m, [radioss.RenumRow("P", 3, 101, 1)])
    assert warns and warns[0]["code"] == "RENUM_NODE_RANGE"


def test_unsupported_element_in_component():
    text = INC + "/SHELL/2\r\n       103         1         2         3         3\r\n"
    m = radioss.parse_text(text)
    with pytest.raises(PaicadError) as e:
        radioss.components(m, [radioss.RenumRow("P", 1, 101, 1)])
    assert e.value.code == "GEOM_UNSUPPORTED_ELEMENT"


def test_renum_csv(tmp_path):
    p = tmp_path / "r.csv"
    p.write_bytes("﻿ Part , NODE_START,elem_start\nA,1,10\nB,100,20\n".encode())
    rows = radioss.read_renum_csv(p)
    assert [(r.part, r.node_start, r.elem_start, r.row) for r in rows] == [("A", 1, 10, 1), ("B", 100, 20, 2)]
    with pytest.raises(PaicadError) as e:
        radioss.read_renum_csv(tmp_path / "missing.csv")
    assert e.value.code == "RENUM_CSV_MISSING"


def test_skin_triangles():
    one = np.array([[1, 2, 3, 4]])
    assert len(radioss.skin_triangles(one)) == 4
    two = np.array([[1, 2, 3, 4], [2, 3, 4, 5]])
    assert len(radioss.skin_triangles(two)) == 6  # shared face removed


def test_rewrite_nodes_roundtrip_and_fields_only():
    data = INC.encode("latin-1")
    assert radioss.rewrite_nodes(data, {}) == data
    same = {1: (0.0, 0.0, 0.0), 5: (10.0, 10.0, 10.0)}
    assert radioss.rewrite_nodes(data, same) == data
    out = radioss.rewrite_nodes(data, {2: (10.5, -0.25, 1.0 / 3.0)})
    a, b = data.splitlines(keepends=True), out.splitlines(keepends=True)
    diff = [(x, y) for x, y in zip(a, b) if x != y]
    assert len(a) == len(b) and len(diff) == 1
    old, new = diff[0]
    assert len(old) == len(new) and new.endswith(b"\r\n") and new[:10] == old[:10]
    vals = [float(new[10:30]), float(new[30:50]), float(new[50:70])]
    assert vals == pytest.approx([10.5, -0.25, 1.0 / 3.0], abs=1e-12)


def test_collect_assembly_surface(tmp_path):
    (tmp_path / "base.inc").write_text(INC)
    (tmp_path / "prod.inc").write_text(
        "/NODE\n         1        0.0        0.0       -1.0\n         2       10.0        0.0       -1.0\n"
        "         3       10.0       10.0       -1.0\n         4        0.0       10.0       -1.0\n"
        "/SHELL/9\n         1         1         2         3         4\n"
    )
    tris = radioss.collect_assembly_surface(tmp_path, [tmp_path / "base.inc"], None)
    assert tris.shape == (2, 3, 3)
    d, _ = TriangleSet(tris).distance(np.array([[5.0, 5.0, 0.0], [50.0, 0, 0]]), 2.0)
    assert d[0] == pytest.approx(1.0) and np.isinf(d[1])


def test_point_triangle_distance_regions():
    a, b, c = np.array([[0.0, 0, 0]]), np.array([[1.0, 0, 0]]), np.array([[0.0, 1, 0]])
    for p, want in [([0.2, 0.2, 1.0], 1.0), ([-1.0, -1.0, 0.0], 2**0.5), ([0.5, -2.0, 0.0], 2.0), ([1.0, 1.0, 0.0], 0.5**0.5)]:
        assert point_triangle_distance(np.array([p]), a, b, c)[0] == pytest.approx(want)


# ------------------------------------------------------------- options, outputs, names
def test_options_merge_and_validate(tmp_path):
    p = tmp_path / "o.json"
    p.write_text(json.dumps({"schema_version": 1, "tag": {"tol_abs_mm": 0.1}, "engine": "native", "engine_version": "0.1.0"}))
    o = options.load(p)
    assert o["tag"]["tol_abs_mm"] == 0.1 and o["tag"]["min_match_ratio"] == 0.98
    p.write_text(json.dumps({"tag": {"tol_abs_mm": -1}}))
    with pytest.raises(PaicadError) as e:
        options.load(p)
    assert e.value.code == "GEOM_INPUT_INVALID"
    assert options.body_tol(options.load(None), [0, 0, 0, 3000, 4000, 0]) == pytest.approx(0.5)


def test_outdir_never_overwrites(tmp_path):
    (tmp_path / "a.json").write_text("x")
    with pytest.raises(PaicadError) as e:
        OutDir(tmp_path, ["a.json"]).prepare()
    assert e.value.code == "GEOM_OUTPUT_EXISTS" and e.value.exit_code == 3


def test_names():
    import re

    assert make_name("CUSH_L", "THK", 1) == "CUSH_L_THK_1"
    long = component_name("x" * 80)
    n = make_name(long, "POCKET_D", 12)
    assert len(n) <= 64 and re.match(NAME_RE, n) and n.endswith("_POCKET_D_12")
    assert make_name(long, "POCKET_D", 12) == n  # deterministic
    assert component_name("1st-pad") == "_1ST_PAD"


# ------------------------------------------------------------- reference-face rule (section 6.2)
def _plane(fid, z, nz, area):
    return FaceData(
        id=fid, surface="PLANE", area=area, centroid=np.array([0.0, 0.0, z]), bbox=np.zeros(6), edges=(), outer_edges=(),
        inner_wires=(), uv_bounds=(0, 1, 0, 1), normal=np.array([0.0, 0.0, nz]),
    )


BOTTOM, TOP = _plane(5, 0.0, -1.0, 9000.0), _plane(2, 20.0, 1.0, 7000.0)
CENTER = np.array([0.0, 0.0, 17.5])


def test_ref_rule3_center_distance_provisional():
    r = choose_ref(BOTTOM, TOP, body_center=CENTER)
    assert (r["moving"], r["fixed"], r["rule"], r["provisional"], r["locked"]) == (5, 2, "center_distance", True, False)


def test_ref_rule3_tie_larger_area_fixed():
    r = choose_ref(BOTTOM, TOP, body_center=np.array([0.0, 0.0, 10.0]), contacts=set())
    assert (r["fixed"], r["moving"], r["provisional"]) == (5, 2, False)


def test_ref_rule1_contact_face_fixed():
    r = choose_ref(BOTTOM, TOP, body_center=CENTER, contacts={5})
    assert (r["moving"], r["fixed"], r["rule"], r["locked"]) == (2, 5, "contact_fixed", False)
    r = choose_ref(BOTTOM, TOP, body_center=CENTER, contacts={2})
    assert (r["moving"], r["fixed"]) == (5, 2)


def test_ref_rule2_both_contact_locked():
    r = choose_ref(BOTTOM, TOP, body_center=CENTER, contacts={2, 5})
    assert r["locked"] is True and r["rule"] == "both_contact_locked" and r["warning"] == "REF_BOTH_CONTACT"
    assert r["fixed"] == 5  # larger area fixed if the user enables it


def test_ref_larger_area_and_override():
    r = choose_ref(BOTTOM, TOP, body_center=CENTER, mode="larger_area_fixed", contacts={2})
    assert (r["fixed"], r["rule"]) == (5, "larger_area_fixed")
    r = choose_ref(BOTTOM, TOP, body_center=CENTER, contacts={5}, override_fixed=2)
    assert (r["fixed"], r["moving"], r["rule"]) == (2, 5, "override")
