"""paicad 0.4.0: position parameters in absolute mm (extract range, envelope steps) and the
feature collision pre-check of update (GEOM_FEATURE_COLLISION)."""

from __future__ import annotations

import csv

import numpy as np
import pytest
from fake_kernel import FakeBox
from paicad import features, options
from paicad.cli import _parser as build_parser
from paicad.collision import find_collisions
from paicad.common import CODE_CATEGORY, CODE_EXIT, PaicadError
from paicad.kernel.base import FaceMove
from test_stage2 import load, run_morph, run_update, write_json

POS = ("HOLE_POS_U", "HOLE_POS_V")


# ------------------------------------------------------------- extract range
def test_extract_position_range_is_absolute_mm(golden):
    feats = golden["features"]["features"]
    assert any(f["type"] in POS for f in feats)
    for f in feats:
        r, feas, nom = f["range"], f["feasible"], f["nominal"]
        if f["type"] in POS:
            assert r["mm"] == 5.0 and "ratio" not in r
            assert r["min"] == pytest.approx(max(nom - 5.0, feas["min"])) and r["max"] == pytest.approx(min(nom + 5.0, feas["max"]))
        else:
            assert r["ratio"] == 0.05 and "mm" not in r
    r_hole = next(f for f in feats if f["name"] == "CUSH_R_HOLE_U_1")
    assert r_hole["range"]["max"] - r_hole["range"]["min"] <= 10.0 + 1e-9 and r_hole["range"]["min"] == pytest.approx(103.0)


def test_position_range_option(tmp_path):
    assert options.load(None)["extract"]["position_range_mm"] == 5.0
    for bad in (0, -1, "5", None):
        p = write_json(tmp_path / "o.json", {"schema_version": 1, "extract": {"position_range_mm": bad}})
        with pytest.raises(PaicadError) as ei:
            options.load(p)
        assert ei.value.code == "GEOM_INPUT_INVALID" and "position_range_mm" in ei.value.message
    assert features._range_mm(12.0, 3.0, {"min": 10.0, "max": 30.0}) == {"min": 10.0, "max": 15.0, "mm": 3.0}
    assert features._range_mm(12.0, 3.0, {"min": 0.0, "max": 30.0}) == {"min": 9.0, "max": 15.0, "mm": 3.0}


def test_extract_uses_position_range_option(golden, tmp_path):
    from conftest import run_cli

    opts = write_json(tmp_path / "o.json", {"schema_version": 1, "extract": {"position_range_mm": 2.0}})
    code, text = run_cli("extract", "--cad", golden["step"], "--out-dir", tmp_path / "ex", "--renum-csv", golden["renum"], "--options", opts, "--no-png")
    assert code == 0, text
    f = {x["name"]: x for x in load(tmp_path / "ex" / "parameter_features.json")["features"]}
    assert f["CUSH_L_HOLE_U_1"]["range"] == {"min": 10.0, "max": 14.0, "mm": 2.0}
    assert f["CUSH_L_THK_3"]["range"] == next(x for x in golden["features"]["features"] if x["name"] == "CUSH_L_THK_3")["range"]


# ------------------------------------------------------------- collision pre-check
def test_collision_code_maps_to_cad_failed():
    assert CODE_EXIT["GEOM_FEATURE_COLLISION"] == 10 and CODE_CATEGORY["GEOM_FEATURE_COLLISION"] == "CAD_FAILED"


def test_collision_unit_fake_box():
    box = FakeBox("B", (0, 0, 0), (10, 4, 2))
    topo = box.topology()
    xp = next(f.id for f in topo.faces if f.normal[0] > 0.5)
    owner = {xp: ["B_THK_1"]}
    assert find_collisions(box, {}, owner, 0.05) == []
    assert find_collisions(box, {xp: FaceMove(translate=np.array([-5.0, 0, 0]))}, owner, 0.05) == []
    hits = find_collisions(box, {xp: FaceMove(translate=np.array([-12.0, 0, 0]))}, owner, 0.05)
    kinds = {h.kind for h in hits}
    assert "WALL_PENETRATION" in kinds and any("B_THK_1" in h.features for h in hits)
    d = hits[0].as_dict()
    assert set(d) == {"kind", "face", "other", "features", "detail"} and d["face"].startswith("F")


def test_update_hole_into_rib_is_collision(golden, tmp_path):
    """Regression: CUSH_R_HOLE_U_1 -20 % (108 -> 86.4 mm) puts the hole under the rib foot print.

    0.3.0: update did not stop it (later failing as degenerate triangles / an invalid rebuild);
    0.4.0: update stops with GEOM_FEATURE_COLLISION (exit 10) before the rebuild.
    """
    code, text, _ = run_update(golden, tmp_path / "u", {"CUSH_R_HOLE_U_1": 86.4})
    assert code == 10 and "PAICAD RESULT FAIL GEOM_FEATURE_COLLISION update.json" in text, text
    d = load(tmp_path / "u" / "update.json")
    assert (d["status"], d["code"], d["category"]) == ("FAIL", "GEOM_FEATURE_COLLISION", "CAD_FAILED")
    assert not (tmp_path / "u" / "sample.brep").exists()
    c = d["collisions"]
    assert c and c[0]["kind"] == "BOUNDARY_OVERLAP" and c[0]["body"] == "CUSH_R"
    names = set(c[0]["features"])
    assert "CUSH_R_HOLE_U_1" in names and any(n.startswith("CUSH_R_RIB_T_") for n in names)


@pytest.mark.parametrize(
    "values,expect",
    [
        ({"CUSH_R_HOLE_U_1": 102.6}, None),  # -5.4 mm: still clear of the rib
        ({"CUSH_R_HOLE_U_1": 113.4}, None),  # 1.6 mm wall left: not a collision (quality decides in check)
        ({"CUSH_R_HOLE_U_1": 118.8}, "BOUNDARY_OVERLAP"),  # hole through the end wall
        ({"CUSH_L_RIB_T_1": 30.0}, "BOUNDARY_OVERLAP"),  # rib grows over the hole
        ({"CUSH_L_POCKET_W_1": -2.0}, "SELF_INTERSECTION"),  # pocket opening inverted
        ({"CUSH_L_POCKET_D_1": 21.0}, "WALL_PENETRATION"),  # floor through the bottom face
    ],
)
def test_update_collision_kinds(golden, tmp_path, values, expect):
    code, text, _ = run_update(golden, tmp_path / "u", values)
    if expect is None:
        assert code == 0, text
        return
    assert code == 10 and "GEOM_FEATURE_COLLISION" in text, text
    assert expect in {c["kind"] for c in load(tmp_path / "u" / "update.json")["collisions"]}


# ------------------------------------------------------------- envelope in mm
def test_sweep_position_parameter_in_mm(golden, tmp_path):
    code, text, _ = run_update(golden, tmp_path / "u", {})
    assert code == 0, text
    code, text = run_morph(golden, tmp_path / "u", tmp_path / "e", "--sweep", "--params", "CUSH_R_HOLE_U_1", "--pos-steps", "5,12,20,30", "--check", "off")
    assert code == 0, text
    env = load(tmp_path / "e" / "envelope.json")
    assert env["pos_steps_mm"] == [5.0, 12.0, 20.0, 30.0]
    minus = [r for r in env["rows"] if r["direction"] == "-"]
    assert [(r["step"], r["unit"], r["value"]) for r in minus] == [(5.0, "mm", 103.0), (12.0, "mm", 96.0), (20.0, "mm", 88.0)]
    assert [r["status"] for r in minus] == ["OK", "FAIL", "FAIL"] and minus[1]["fail_code"] == "GEOM_FEATURE_COLLISION"
    s = env["summary"][0]
    assert s["unit"] == "mm" and s["last_ok"]["-"] == 5.0 and s["first_fail"]["-"] == 12.0 and s["last_ok_label"]["-"] == "5 mm"
    assert s["last_ok_pct"] == {"+": None, "-": None}
    f = next(x for x in load(tmp_path / "e" / "parameter_features.json")["features"] if x["name"] == "CUSH_R_HOLE_U_1")
    assert f["feasible"]["source"] == "envelope" and f["feasible"]["min"] == pytest.approx(103.0)
    assert f["feasible"]["max"] == pytest.approx(108.0 + s["last_ok"]["+"])
    with open(tmp_path / "e" / "envelope.csv", newline="") as fh:
        table = list(csv.DictReader(fh))
    assert {t["unit"] for t in table} == {"mm"} and all(t["pct"] == "" for t in table)
    md = (tmp_path / "e" / "report_envelope.md").read_text(encoding="utf-8")
    assert "| mm | " in md and "5 mm" in md and "12 mm GEOM_FEATURE_COLLISION" in md


def test_sweep_default_position_steps():
    a = build_parser().parse_args(["morph", "--baseline-inc", "b", "--tag-dir", "t", "--features", "f", "--update-dir", "u", "--out-dir", "o", "--sweep"])
    assert a.pos_steps == "1,2,3,5,8,10" and a.steps == "5,10,20,30,40,50" and a.stop_after_fail == 2
