"""Development golden (virtual cushion): extract / tag against design truth (contract sections 9 stage 1, 10.6)."""

from __future__ import annotations

import json
import re
import shutil
import xml.etree.ElementTree as ET
from collections import defaultdict

import numpy as np
import pytest
from conftest import run_cli
from paicad.features import choose_ref
from paicad.kernel import load_cad
from paicad.mesh import radioss

NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
REL_TOL = 0.01  # 1 %


# ------------------------------------------------------------- golden set itself (stage 0(a))
def test_golden_assembly_layout(golden):
    assem = golden["assem"]
    base = golden["baseline"]
    assert base.stat().st_size < 1_000_000
    kws = {line.split("/")[1] for line in radioss.read_text(base).splitlines() if line.startswith("/")}
    assert kws == {"NODE", "TETRA4"}  # no /PART, no /PROP
    starter = next(assem.glob("*_0000.rad")).read_text()
    assert f"#include {base.name}" in starter
    rows = radioss.read_renum_csv(golden["renum"])
    assert [r.part for r in rows] == ["CUSH_L", "CUSH_R"] and rows[0].node_start == rows[0].elem_start == 3000001


def _stretch(xyz, tets):
    p = [xyz[tets[:, i]] for i in range(4)]
    vol = np.einsum("ij,ij->i", np.cross(p[1] - p[0], p[2] - p[0]), p[3] - p[0]) / 6.0
    faces = [(1, 2, 3), (0, 3, 2), (0, 1, 3), (0, 2, 1)]
    area = sum(0.5 * np.linalg.norm(np.cross(p[b] - p[a], p[c] - p[a]), axis=1) for a, b, c in faces)
    edges = [(0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)]
    lmax = np.max([np.linalg.norm(p[a] - p[b], axis=1) for a, b in edges], axis=0)
    r_in = 3 * vol / area
    return vol, 2 * np.sqrt(6) * r_in / lmax


def test_golden_baseline_quality(golden):
    for xyz, tets in golden["meshes"]:
        vol, stretch = _stretch(xyz, tets)
        assert (vol > 0).all()
        assert stretch.min() >= 0.1


# ------------------------------------------------------------- extract
def test_extract_features_match_truth(golden):
    truth = golden["truth"]["bodies"]
    got: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for f in golden["features"]["features"]:
        got[f["body"]][f["type"]].append(f["nominal"])
    assert set(got) == set(truth)
    for body, types in truth.items():
        assert set(got[body]) == set(types), body  # no missing / extra feature type
        for t, want in types.items():
            have = sorted(got[body][t])
            assert len(have) == len(want), (body, t, have, want)  # no missing / misrecognized feature
            for h, w in zip(have, sorted(want)):
                assert abs(h - w) <= REL_TOL * abs(w), (body, t, h, w)


def test_extract_xml_and_names(golden):
    root = ET.parse(golden["extract_dir"] / "parameter_extracted.xml").getroot()
    assert root.tag == "Root"
    model = root.find("Model")
    assert model.get("Name") == golden["step"].name
    params = {p.findtext("Name"): p.findtext("Value") for p in model.findall("Parameter")}
    assert len(params) == golden["truth"]["parameters"]
    for name, value in params.items():
        assert NAME_RE.match(name) and value.endswith(" mm")
        float(value[:-3])
    feats = golden["features"]["features"]
    assert all(NAME_RE.match(f["name"]) for f in feats)
    assert len({f["name"] for f in feats}) == len(feats)
    reps = {g["parameter"] for g in golden["features"]["groups"]}
    members = {m for g in golden["features"]["groups"] for m in g["members"]}
    assert set(params) == reps | ({f["name"] for f in feats} - members)


def test_extract_json_envelope(golden):
    d = golden["features"]
    assert d["schema_version"] == 1 and d["engine"] == "native" and d["engine_version"] == "0.1.0"
    assert d["cad"]["mode"] == "single" and d["cad"]["body_map"] == "xde" and len(d["cad"]["files"][0]["sha256"]) == 64
    assert [b["part"] for b in d["bodies"]] == ["CUSH_L", "CUSH_R"] and [b["renum_row"] for b in d["bodies"]] == [1, 2]
    for f in d["features"]:
        assert f["range"]["min"] <= f["nominal"] <= f["range"]["max"]
        assert f["feasible"]["min"] <= f["nominal"] <= f["feasible"]["max"]
        assert set(f["faces"]["moving"] + f["faces"]["fixed"]) <= set(f["face_signatures"])


def test_symmetry_groups(golden):
    d = golden["features"]
    groups = d["groups"]
    assert len(groups) == golden["truth"]["groups"]["count"]
    by_name = {f["name"]: f for f in d["features"]}
    for g in groups:
        assert g["kind"] == "MIRROR" and g["parameter"] == sorted(g["members"])[0]
        types = {by_name[m]["type"] for m in g["members"]}
        assert len(types) == 1
        noms = [by_name[m]["nominal"] for m in g["members"]]
        assert max(noms) - min(noms) <= 0.05
        assert all(by_name[m]["group"] == g["id"] for m in g["members"])
    rib = [g for g in groups if by_name[g["parameter"]]["type"] == "RIB_THICKNESS"]
    assert len(rib) == 1 and len(rib[0]["members"]) == golden["truth"]["groups"]["rib_members"]
    # HOLE_POS_U differs after mirroring (12 vs 108) -> not grouped
    assert all(f["group"] is None for f in d["features"] if f["type"] == "HOLE_POS_U")


def _thk_z(features, body):
    return next(f for f in features if f["body"] == body and f["type"] == "THICKNESS" and abs(f["nominal"] - 20.0) < 1e-6)


def test_reference_rule3_provisional_in_extract(golden):
    f = _thk_z(golden["features"]["features"], "CUSH_L")
    sig = f["face_signatures"]
    mv, fx = f["faces"]["moving"][0], f["faces"]["fixed"][0]
    # bottom (z=0) is farther from the bbox center (z=17.5) than the base top (z=20) -> bottom moves
    assert sig[mv]["centroid"][2] == pytest.approx(0.0) and sig[fx]["centroid"][2] == pytest.approx(20.0)
    assert f["ref"]["rule"] == "center_distance" and f["ref"]["provisional"] is True and f["ref"]["locked"] is False


def test_reference_rule1_with_tag_contacts(golden):
    """With tag contacts (bottom on the product plate) the bottom is fixed and the top moves."""
    f = _thk_z(golden["features"]["features"], "CUSH_L")
    contacts = {int(c["face"][1:]) for c in golden["tag"]["contacts"] if c["part"] == "CUSH_L"}
    _, bodies = load_cad(golden["step"])
    body = next(b for b in bodies if b.name == "CUSH_L")
    topo = body.topology()
    a, b = (topo.face(int(x[1:])) for x in f["measure"]["faces"])
    bb = body.summary().bbox
    r = choose_ref(a, b, body_center=0.5 * (bb[:3] + bb[3:]), contacts=contacts)
    assert r["rule"] == "contact_fixed"
    assert topo.face(r["fixed"]).centroid[2] == pytest.approx(0.0)
    assert topo.face(r["moving"]).centroid[2] == pytest.approx(20.0)
    r2 = choose_ref(a, b, body_center=0.5 * (bb[:3] + bb[3:]), contacts={a.id, b.id})
    assert r2["locked"] and r2["warning"] == "REF_BOTH_CONTACT"


def test_extract_is_deterministic(golden, tmp_path):
    code, _ = run_cli("extract", "--cad", golden["step"], "--out-dir", tmp_path, "--renum-csv", golden["renum"])
    assert code == 0
    for name in ("parameter_features.json", "parameter_extracted.xml"):
        assert (tmp_path / name).read_bytes() == (golden["extract_dir"] / name).read_bytes()


def test_extract_refuses_existing_output(golden):
    code, out = run_cli("extract", "--cad", golden["step"], "--out-dir", golden["extract_dir"])
    assert code == 3 and "PAICAD RESULT FAIL GEOM_OUTPUT_EXISTS" in out


def test_extract_body_map_rules(golden, tmp_path):
    csv = tmp_path / "renum.csv"
    csv.write_text("part,node_start,elem_start\ncush-r,3100001,3100001\ncush_l,3000001,3000001\n")
    code, _ = run_cli("extract", "--cad", golden["step"], "--out-dir", tmp_path / "o", "--renum-csv", csv, "--no-png")
    assert code == 0
    d = json.loads((tmp_path / "o" / "parameter_features.json").read_text())
    assert [(b["body"], b["part"], b["renum_row"]) for b in d["bodies"]] == [("CUSH_R", "cush-r", 1), ("CUSH_L", "cush_l", 2)]
    assert d["features"][0]["name"].startswith("CUSH_R_")
    assert d["warnings"] == []
    bad = tmp_path / "bad.csv"
    bad.write_text("part,node_start,elem_start\nCUSH_L,1,1\nOTHER,2,2\n")
    code, out = run_cli("extract", "--cad", golden["step"], "--out-dir", tmp_path / "b", "--renum-csv", bad)
    assert code == 12 and "GEOM_BODY_MAP_FAILED" in out


def test_extract_parts_folder_mode(golden, tmp_path):
    from data.make_synthetic import CushionSpec, build_bodies, write_step

    parts = tmp_path / "parts"
    for name, solid in build_bodies(CushionSpec()):
        write_step(parts / f"{name}.step", [(name, solid)])
    code, _ = run_cli("extract", "--cad", parts, "--out-dir", tmp_path / "o", "--renum-csv", golden["renum"], "--no-png")
    assert code == 0
    d = json.loads((tmp_path / "o" / "parameter_features.json").read_text())
    assert d["cad"]["mode"] == "parts" and d["cad"]["body_map"] == "file_stem" and len(d["cad"]["files"]) == 2
    assert [f["nominal"] for f in d["features"]] == [f["nominal"] for f in golden["features"]["features"]]


# ------------------------------------------------------------- tag
def test_tag_all_nodes_classified(golden):
    t = golden["tag"]
    assert t["status"] == "OK" and t["schema_version"] == 1 and t["engine_version"] == "0.1.0"
    assert t["match_ratio"] == 1.0
    assert [p["part"] for p in t["parts"]] == ["CUSH_L", "CUSH_R"] and all(p["body"] == p["part"] for p in t["parts"])
    for p in t["parts"]:
        c = p["classified"]
        assert c["unmatched"] == 0
        assert c["vertex"] + c["edge"] + c["face"] == p["boundary_nodes"]
        assert c["vertex"] == next(b["vertices"] for b in golden["features"]["bodies"] if b["part"] == p["part"])
        assert p["dist_mm"]["max"] <= p["tol_mm"]
    assert t["baseline_inc"]["name"] == golden["baseline"].name


def test_tag_nodes_npz(golden):
    z = np.load(golden["tag_dir"] / "tag_nodes.npz")
    assert z["node_id"].dtype == np.int64 and z["part"].dtype == np.int32 and z["kind"].dtype == np.int8
    assert z["entity"].dtype == np.int32 and z["uv"].shape == (len(z["node_id"]), 2) and z["dist"].dtype == np.float64
    assert len(np.unique(z["node_id"])) == len(z["node_id"]) == sum(p["nodes"] for p in golden["tag"]["parts"])
    assert not (z["kind"] == -1).any()
    face = z["kind"] == 1
    assert (z["uv"][face] >= -1e-9).all() and (z["uv"][face] <= 1 + 1e-9).all()
    assert (z["entity"][z["kind"] == 0] == -1).all()
    # exactly one vertex node per B-rep vertex
    for pi in range(2):
        v = z["entity"][(z["part"] == pi) & (z["kind"] == 3)]
        assert len(v) == len(np.unique(v))


def test_tag_contacts_bottom_on_product(golden):
    feats = golden["features"]["features"]
    for body in ("CUSH_L", "CUSH_R"):
        f = _thk_z(feats, body)
        bottom = next(k for k, s in f["face_signatures"].items() if s["centroid"][2] == pytest.approx(0.0))
        cs = [c for c in golden["tag"]["contacts"] if c["part"] == body]
        assert [(c["face"], c["with"]) for c in cs] == [(bottom, "PRODUCT")]


def test_tag_baseline_mismatch(golden, tmp_path):
    assem = tmp_path / "assem"
    shutil.copytree(golden["assem"], assem)
    base = assem / golden["baseline"].name
    mesh = radioss.read_mesh(base)
    shifted = {int(n): (x + 1.0, y, z) for n, (x, y, z) in zip(mesh.node_ids, mesh.xyz)}
    base.write_bytes(radioss.rewrite_nodes(base.read_bytes(), shifted))
    code, out = run_cli(
        "tag", "--cad", golden["step"], "--features", golden["features_path"], "--baseline-inc", base,
        "--renum-csv", assem / golden["renum"].name, "--assem-dir", assem, "--out-dir", tmp_path / "t",
    )
    assert code == 12 and "GEOM_BASELINE_MISMATCH" in out
    d = json.loads((tmp_path / "t" / "tag.json").read_text())
    assert d["status"] == "FAIL" and d["code"] == "GEOM_BASELINE_MISMATCH" and d["match_ratio"] < 0.98
    assert not (tmp_path / "t" / "tag_nodes.npz").exists()


def test_tag_missing_renum_csv(golden, tmp_path):
    code, out = run_cli(
        "tag", "--cad", golden["step"], "--features", golden["features_path"], "--baseline-inc", golden["baseline"],
        "--renum-csv", tmp_path / "none.csv", "--assem-dir", golden["assem"], "--out-dir", tmp_path / "t",
    )
    assert code == 3 and "RENUM_CSV_MISSING" in out
    assert json.loads((tmp_path / "t" / "tag.json").read_text())["code"] == "RENUM_CSV_MISSING"


def test_baseline_roundtrip_bytes_identical(golden):
    data = golden["baseline"].read_bytes()
    mesh = radioss.parse_text(data.decode("latin-1"))
    same = {int(n): tuple(p) for n, p in zip(mesh.node_ids, mesh.xyz)}
    assert radioss.rewrite_nodes(data, same) == data
