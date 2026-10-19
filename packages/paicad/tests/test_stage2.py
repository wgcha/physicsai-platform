"""Stage 2 (contract section 9): update / morph / check / sweep against the development golden.

The ground truth of every sample is the build123d cushion rebuilt with the changed dimension
(``data/make_synthetic.py``); nothing generated here is committed.
"""

from __future__ import annotations

import csv
import json
import math
import shutil
from dataclasses import replace

import numpy as np
import paicad
import pytest
from conftest import run_cli
from paicad.kernel import load_brep, load_cad
from paicad.mesh import radioss
from paicad.meshdata import components_from_tag, load_tag, tet_volumes

DRAFT_COS = math.cos(math.radians(1.0))
UPDATE_FACE_TOL = 0.01  # mm, update B-rep vs truth (section 9 stage 2)
VOLUME_REL_TOL = 1e-3
BOUNDARY_TOL = 0.05  # mm, morphed boundary nodes vs truth
REMEASURE_REL = 0.01


# ------------------------------------------------------------- helpers
def write_json(path, obj):
    path.write_text(json.dumps(obj), encoding="utf-8")
    return path


def run_update(g, out, values, *extra, tag=True):
    vp = write_json(out.parent / f"{out.name}_values.json", {"schema_version": 1, "values": values})
    args = ["update", "--cad", g["step"], "--features", g["features_path"], "--values", vp, "--out-dir", out, *extra]
    if tag:
        args += ["--tag-dir", g["tag_dir"]]
    code, text = run_cli(*args)
    return code, text, vp


def run_morph(g, upd, out, *extra):
    return run_cli(
        "morph", "--baseline-inc", g["baseline"], "--tag-dir", g["tag_dir"], "--features", g["features_path"], "--update-dir", upd, "--out-dir", out, *extra
    )


def run_check(g, upd, mor, vp, out, out_inc, *extra, assem=None):
    assem = assem or g["assem"]
    return run_cli(
        "check", "--baseline-inc", g["baseline"], "--morph-dir", mor, "--update-dir", upd, "--tag-dir", g["tag_dir"], "--features", g["features_path"],
        "--values", vp, "--assem-dir", assem, "--renum-csv", g["renum"], "--out-dir", out, "--out-inc", out_inc, *extra,
    )


def load(p):
    return json.loads(p.read_text(encoding="utf-8"))


def truth_bodies(spec, path):
    from data.make_synthetic import build_bodies, write_step

    write_step(path, build_bodies(spec))
    _, bodies = load_cad(path)
    return {b.name: b for b in bodies}


def nominal_values(g):
    feats = {f["name"]: f for f in g["features"]["features"]}
    grouped = {m for gr in g["features"]["groups"] for m in gr["members"]}
    reps = {gr["parameter"] for gr in g["features"]["groups"]}
    return {n: f["nominal"] for n, f in feats.items() if n in reps or n not in grouped}


def face_centroid(g, name, face):
    f = next(x for x in g["features"]["features"] if x["name"] == name)
    return np.array(f["face_signatures"][face]["centroid"])


# truth cases: (id, parameter changes, CushionSpec changes) for sign sg = +1 / -1 (local CUSH_L x = global x + 150)
def case_spec(g, cid, sg):
    from data.make_synthetic import CushionSpec

    s = CushionSpec()
    nom = nominal_values(g)
    if cid == "THICKNESS":
        return {"CUSH_L_THK_3": 20 * (1 + 0.1 * sg)}, replace(s, T=20 * (1 + 0.1 * sg))
    if cid == "THICKNESS_W":  # moved face is tangent to the corner fillet: the blend follows
        return {"CUSH_L_THK_1": 80 * (1 + 0.1 * sg)}, replace(s, W=80 * (1 + 0.1 * sg))
    if cid == "POCKET_DEPTH":
        return {"CUSH_L_POCKET_D_1": 8 * (1 + 0.1 * sg)}, replace(s, pocket_d=8 * (1 + 0.1 * sg))
    if cid == "POCKET_WIDTH":
        dt = 3.0 * sg  # top-width change; the measured (perpendicular) width changes by dt*cos(draft)
        return {"CUSH_L_POCKET_W_1": nom["CUSH_L_POCKET_W_1"] + dt * DRAFT_COS}, replace(s, pocket_x=(45.0, 75.0 + dt))
    if cid == "RIB_THICKNESS":
        d = 0.6 * sg  # rule 3 moves the outer side of each rib: rib 1 grows towards -x, rib 2 towards +x
        return {"CUSH_L_RIB_T_1": 6 + d}, replace(s, rib_t=6 + d, rib_x=(25.0 - d, 89.0))
    if cid == "RIB_HEIGHT":
        return {"CUSH_L_RIB_H_1": 15 * (1 + 0.1 * sg)}, replace(s, rib_h=15 * (1 + 0.1 * sg))
    if cid == "HOLE_RADIUS":
        return {"CUSH_L_HOLE_R_1": 5 * (1 + 0.1 * sg)}, replace(s, hole_r=5 * (1 + 0.1 * sg))
    if cid == "HOLE_POS_U":  # ungrouped: the mirrored body gets its own value (measured from its bbox minimum)
        return {"CUSH_L_HOLE_U_1": 12 + 1.2 * sg, "CUSH_R_HOLE_U_1": 108 - 1.2 * sg}, replace(s, hole_xy=(12 + 1.2 * sg, 12.0))
    if cid == "HOLE_POS_V":
        return {"CUSH_L_HOLE_V_1": 12 + 1.2 * sg}, replace(s, hole_xy=(12.0, 12 + 1.2 * sg))
    if cid == "FILLET_RADIUS":
        return {"CUSH_L_FILLET_R_1": 1 + 0.2 * sg}, replace(s, fillet_r=1 + 0.2 * sg)
    raise KeyError(cid)


CASES = [
    "THICKNESS",
    "THICKNESS_W",
    "POCKET_DEPTH",
    "POCKET_WIDTH",
    "RIB_THICKNESS",
    "RIB_HEIGHT",
    "HOLE_RADIUS",
    "HOLE_POS_U",
    "HOLE_POS_V",
    "FILLET_RADIUS",
]


@pytest.fixture(scope="session")
def nominal_update(golden):
    out = golden["root"] / "out" / "update_nominal"
    code, text, vp = run_update(golden, out, {})
    assert code == 0, text
    return out, vp


def assert_only_node_coordinates_changed(base: bytes, new: bytes):
    a, b = base.splitlines(keepends=True), new.splitlines(keepends=True)
    assert len(a) == len(b)
    in_node = False
    for x, y in zip(a, b):
        if x.startswith(b"/"):
            in_node = x.strip().upper() == b"/NODE"
        if x == y:
            continue
        assert in_node and not x.startswith((b"#", b"$")), x
        assert len(x) == len(y) and x[:10] == y[:10] and x[len(x.rstrip(b"\r\n")):] == y[len(y.rstrip(b"\r\n")):]


# ------------------------------------------------------------- truth comparison per feature type
@pytest.mark.parametrize("sg", [1, -1], ids=["plus", "minus"])
@pytest.mark.parametrize("cid", CASES)
def test_update_morph_check_match_truth(golden, tmp_path, cid, sg):
    values, spec = case_spec(golden, cid, sg)
    upd, mor, chk = tmp_path / "upd", tmp_path / "mor", tmp_path / "chk"
    code, text, vp = run_update(golden, upd, values)
    assert code == 0, text
    u = load(upd / "update.json")
    assert u["status"] == "OK" and u["engine_version"] == paicad.__version__ and u["topology"]["same_as_nominal"]
    if cid == "POCKET_WIDTH":  # truth assumes the +x wall moves (rule 3 tie -> lower face id fixed)
        mv = next(a for a in u["applied"] if a["name"] == "CUSH_L_POCKET_W_1")["moved"][0]
        assert face_centroid(golden, "CUSH_L_POCKET_W_1", mv)[0] > -90.0
    if cid == "RIB_THICKNESS":
        mv = next(a for a in u["applied"] if a["name"] == "CUSH_L_RIB_T_1")["moved"][0]
        assert face_centroid(golden, "CUSH_L_RIB_T_1", mv)[0] == pytest.approx(-125.0)
    truth = truth_bodies(spec, tmp_path / "truth.step")
    names = [b["body"] for b in golden["features"]["bodies"]]
    sample = dict(zip(names, load_brep(upd / "sample.brep", names)))
    for name, body in sample.items():
        t = truth[name]
        assert abs(body.summary().volume - t.summary().volume) <= VOLUME_REL_TOL * t.summary().volume
        for f in body.topology().faces:
            pts = body.sample_face(f.id, 5)
            if len(pts):
                assert t.distance(pts).max() <= UPDATE_FACE_TOL, (name, f.id)
    # morph: boundary nodes on the truth shape, nothing inverted, only /NODE coordinates changed
    code, text = run_morph(golden, upd, mor)
    assert code == 0, text
    m = load(mor / "morph.json")
    assert m["status"] == "OK" and m["max_disp_mm"] > 0
    base_bytes = golden["baseline"].read_bytes()
    new_bytes = (mor / "morphed.inc").read_bytes()
    assert_only_node_coordinates_changed(base_bytes, new_bytes)
    base, new = radioss.parse_text(base_bytes.decode("latin-1")), radioss.parse_text(new_bytes.decode("latin-1"))
    assert np.array_equal(base.node_ids, new.node_ids) and len(base.blocks) == len(new.blocks)
    for a, b in zip(base.blocks, new.blocks):
        assert (a.keyword, a.part_id) == (b.keyword, b.part_id) and np.array_equal(a.ids, b.ids) and np.array_equal(a.conn, b.conn)
    comps = components_from_tag(base, load_tag(golden["tag_dir"]))
    for c in comps:
        bnd = c.kind > 0
        assert truth[c.body].distance(new.xyz[c.gidx[bnd]]).max() <= BOUNDARY_TOL
        assert (tet_volumes(new.xyz[c.gidx], c.tets) > 0).all()
    # check: re-measured parameters within 1 %, deviation within 0.05 mm
    code, text = run_check(golden, upd, mor, vp, chk, tmp_path / "out.inc")
    d = load(chk / "check.json")
    assert d["checks"]["param"]["status"] == "PASS" and d["checks"]["deviation"]["status"] == "PASS"
    for it in d["checks"]["param"]["items"]:
        assert abs(it["measured"] - it["input"]) <= REMEASURE_REL * abs(it["input"]), it
    assert d["checks"]["deviation"]["max_mm"] <= BOUNDARY_TOL
    assert d["checks"]["quality"]["inverted"] == 0
    assert (code == 0) == (d["status"] == "PASS") == (tmp_path / "out.inc").exists()


# ------------------------------------------------------------- unchanged values, determinism, outputs
def test_nominal_values_give_byte_identical_include(golden, nominal_update, tmp_path):
    upd, vp = nominal_update
    u = load(upd / "update.json")
    assert u["applied"] and all(a["delta"] == 0 for a in u["applied"])
    fm = load(upd / "face_map.json")
    assert set(fm) == {"CUSH_L", "CUSH_R"} and all(fm[b]["F"][k] == int(k) for b in fm for k in fm[b]["F"])
    code, text = run_morph(golden, upd, tmp_path / "mor")
    assert code == 0, text
    assert (tmp_path / "mor" / "morphed.inc").read_bytes() == golden["baseline"].read_bytes()
    assert all(p["moved_nodes"] == 0 for p in load(tmp_path / "mor" / "morph.json")["parts"])
    out_inc = tmp_path / "inc" / golden["baseline"].name
    opts = write_json(tmp_path / "o.json", {"schema_version": 1, "quality": {"min_edge_mm": 0.5}})
    code, text = run_check(golden, upd, tmp_path / "mor", vp, tmp_path / "chk", out_inc, "--options", opts)
    assert code == 0, text
    d = load(tmp_path / "chk" / "check.json")
    assert d["status"] == "PASS" and d["out_inc"] == out_inc.name and out_inc.read_bytes() == golden["baseline"].read_bytes()
    assert d["checks"]["tie"] == {"status": "SKIPPED", "interfaces": [], "reason": "no_tie_on_component"}
    assert d["checks"]["interference"]["status"] == "PASS" and d["checks"]["quality"]["baseline_status"] == "PASS" and d["warnings"] == []
    assert d["options"]["quality"]["min_edge_mm"] == 0.5 and d["engine"] == "native" and d["schema_version"] == 1
    # stricter criterion than the baseline mesh -> BASELINE_QUALITY_BELOW warning, not a failure
    opts2 = write_json(tmp_path / "o2.json", {"schema_version": 1, "quality": {"min_edge_mm": 0.9, "min_stretch": 0.3}})
    code, _ = run_check(golden, upd, tmp_path / "mor", vp, tmp_path / "chk2", tmp_path / "inc2.inc", "--options", opts2)
    d2 = load(tmp_path / "chk2" / "check.json")
    assert code == 0 and d2["status"] == "PASS" and d2["checks"]["quality"]["baseline_status"] == "FAIL"
    assert [w["code"] for w in d2["warnings"]] == ["BASELINE_QUALITY_BELOW"]


def test_update_and_morph_are_deterministic(golden, tmp_path):
    vals = {"CUSH_L_RIB_H_1": 17.0, "CUSH_L_HOLE_R_1": 4.5}
    outs = []
    for k in (1, 2):
        code, text, _ = run_update(golden, tmp_path / f"u{k}", vals)
        assert code == 0, text
        code, text = run_morph(golden, tmp_path / f"u{k}", tmp_path / f"m{k}")
        assert code == 0, text
        outs.append(((tmp_path / f"u{k}" / "sample.brep").read_bytes(), (tmp_path / f"m{k}" / "morphed.inc").read_bytes()))
    assert outs[0] == outs[1]


def test_update_reference_rule_uses_tag_contacts(golden, tmp_path):
    vals = {"CUSH_L_THK_3": 21.0}
    code, _, _ = run_update(golden, tmp_path / "with", vals)
    assert code == 0
    a = next(x for x in load(tmp_path / "with" / "update.json")["applied"] if x["name"] == "CUSH_L_THK_3")
    assert a["ref_rule"] == "contact_fixed" and face_centroid(golden, "CUSH_L_THK_3", a["moved"][0])[2] == pytest.approx(20.0)
    assert a["members"] == ["CUSH_R_THK_1"] and a["op"] == "FACE_OFFSET" and a["delta"] == pytest.approx(1.0)
    code, _, _ = run_update(golden, tmp_path / "without", vals, tag=False)
    assert code == 0
    u = load(tmp_path / "without" / "update.json")
    a = next(x for x in u["applied"] if x["name"] == "CUSH_L_THK_3")
    assert a["ref_rule"] == "center_distance" and face_centroid(golden, "CUSH_L_THK_3", a["moved"][0])[2] == pytest.approx(0.0)
    assert "REF_NO_CONTACT_INFO" in {w["code"] for w in u["warnings"]}


def test_symmetry_split_makes_members_independent(golden, tmp_path):
    g3 = next(gr for gr in golden["features"]["groups"] if gr["parameter"] == "CUSH_L_THK_3")
    code, text, _ = run_update(golden, tmp_path / "bad", {"CUSH_R_THK_1": 21.0})
    assert code == 3 and "GEOM_INPUT_INVALID" in text
    assert load(tmp_path / "bad" / "update.json")["code"] == "GEOM_INPUT_INVALID"
    opts = write_json(tmp_path / "o.json", {"schema_version": 1, "symmetry_split": [g3["id"]]})
    code, text, _ = run_update(golden, tmp_path / "split", {"CUSH_R_THK_1": 21.0}, "--options", opts)
    assert code == 0, text
    bodies = load(tmp_path / "split" / "update.json")["bodies"]
    vol = {b["body"]: b["volume"] for b in bodies}
    nominal = {b["body"]: b["volume"] for b in golden["features"]["bodies"]}
    assert vol["CUSH_L"] == pytest.approx(nominal["CUSH_L"]) and vol["CUSH_R"] > nominal["CUSH_R"] + 1000


# ------------------------------------------------------------- failure paths
@pytest.mark.parametrize(
    "values,code_name",
    [
        ({"CUSH_L_POCKET_D_1": 25.0}, "GEOM_CAD_FAILED"),  # floor through the bottom face
        ({"CUSH_L_THK_3": 7.0}, "GEOM_CAD_FAILED"),  # base thinner than the pocket: self-intersection
        ({"CUSH_L_RIB_T_1": 0.0}, "GEOM_TOPOLOGY_CHANGED"),  # rib side faces collapse
        ({"CUSH_L_HOLE_R_1": -1.0}, "GEOM_CAD_FAILED"),
    ],
)
def test_update_cad_failure_codes(golden, tmp_path, values, code_name):
    code, text, _ = run_update(golden, tmp_path / "u", values)
    assert code == 10 and f"PAICAD RESULT FAIL {code_name} update.json" in text
    d = load(tmp_path / "u" / "update.json")
    assert (d["status"], d["code"], d["category"]) == ("FAIL", code_name, "CAD_FAILED") and d["message"]
    assert not (tmp_path / "u" / "sample.brep").exists() and not (tmp_path / "u" / "face_map.json").exists()


def test_update_occt_exception_is_a_cad_failure(golden, tmp_path, monkeypatch):
    from paicad.kernel import occ_push

    def boom(*a, **k):
        raise RuntimeError("Standard_ConstructionError")

    monkeypatch.setattr(occ_push, "push_pull", boom)
    code, text, _ = run_update(golden, tmp_path / "u", {"CUSH_L_RIB_H_1": 16.0})
    assert code == 10 and "GEOM_CAD_FAILED" in text
    assert "OCCT error" in load(tmp_path / "u" / "update.json")["message"]


def test_update_input_errors(golden, tmp_path):
    code, text, _ = run_update(golden, tmp_path / "u", {"NO_SUCH": 1.0})
    assert code == 3 and load(tmp_path / "u" / "update.json")["code"] == "GEOM_INPUT_INVALID"
    code, text, _ = run_update(golden, tmp_path / "v", {"CUSH_L_THK_3": "x"})
    assert code == 3
    code, text, _ = run_update(golden, tmp_path / "u", {})
    assert code == 3 and "GEOM_OUTPUT_EXISTS" in text


def test_large_deformation_fails_quality(golden, tmp_path):
    upd, mor = tmp_path / "upd", tmp_path / "mor"
    code, text, vp = run_update(golden, upd, {"CUSH_L_RIB_H_1": 4.0, "CUSH_L_THK_3": 12.5})
    assert code == 0, text
    code, text = run_morph(golden, upd, mor)
    assert code == 0, text
    out_inc = tmp_path / "out.inc"
    code, text = run_check(golden, upd, mor, vp, tmp_path / "chk", out_inc)
    d = load(tmp_path / "chk" / "check.json")
    assert code == 11 and d["status"] == "FAIL" and d["code"] == "GEOM_QUALITY" and d["category"] == "QUALITY"
    assert d["checks"]["quality"]["status"] == "FAIL" and d["out_inc"] is None and not out_inc.exists()
    assert d["checks"]["param"]["status"] == "PASS"  # the geometry itself is right; only the mesh is too distorted


def _tie_assembly(golden, tmp_path, extra: str):
    assem = tmp_path / "assem"
    shutil.copytree(golden["assem"], assem)
    (assem / "tie.inc").write_text(extra, encoding="ascii")
    return assem


def _bottom_nodes(golden, n=6):
    base = radioss.read_mesh(golden["baseline"])
    ids = base.node_ids[np.abs(base.xyz[:, 2]) < 1e-9]
    return [int(x) for x in ids[:n]]


def test_check_interference_and_tie(golden, tmp_path):
    """Bottom face moved without contact info (rule 3) -> pushed into the product plate; ties on the bottom nodes."""
    upd, mor = tmp_path / "upd", tmp_path / "mor"
    code, text, vp = run_update(golden, upd, {"CUSH_L_THK_3": 22.0}, tag=False)
    assert code == 0, text
    assert run_morph(golden, upd, mor)[0] == 0
    nodes = _bottom_nodes(golden)
    grnod = "/GRNOD/NODE/77\nbottom nodes\n" + "".join(f"{n:10d}" for n in nodes) + "\n"
    # main surface = the product plate shells
    prod = radioss.read_mesh(golden["assem"] / "product.inc")
    sh = next(b for b in prod.blocks if b.keyword == "SHELL")
    surf = "/SURF/SEG/78\nplate\n" + "".join(f"{k:10d}" + "".join(f"{int(x):10d}" for x in row) + "\n" for k, row in enumerate(sh.conn, 1))
    inter = "/INTER/TYPE2/12\ntie bottom\n#  grnd_IDs  surf_IDm\n        77        78         0         0         0         0         0\n                 0.5\n"
    assem = _tie_assembly(golden, tmp_path, inter + grnod + surf)
    code, text = run_check(golden, upd, mor, vp, tmp_path / "chk", tmp_path / "o.inc", assem=assem)
    d = load(tmp_path / "chk" / "check.json")
    assert code == 11 and d["code"] == "GEOM_INTERFERENCE" and "(+" in d["message"]
    assert d["checks"]["interference"]["status"] == "FAIL" and d["checks"]["interference"]["product_max_mm"] == pytest.approx(2.0, abs=1e-3)
    tie = d["checks"]["tie"]
    assert tie["status"] == "FAIL" and tie["interfaces"][0]["id"] == 12 and tie["interfaces"][0]["failed_nodes"] == len(nodes)
    # nominal: the same tie passes (gap 0)
    nom = tmp_path / "nom"
    code, _, vpn = run_update(golden, nom, {})
    assert run_morph(golden, nom, tmp_path / "mnom")[0] == 0
    run_check(golden, nom, tmp_path / "mnom", vpn, tmp_path / "chk2", tmp_path / "o2.inc", assem=assem)
    t2 = load(tmp_path / "chk2" / "check.json")["checks"]["tie"]
    assert t2["status"] == "PASS" and t2["interfaces"][0]["failed_nodes"] == 0 and t2["interfaces"][0]["dsearch_mm"] == 0.5
    # unsupported set type: strict FAIL by default, NOT_EVALUATED + warning when not required
    assem2 = _tie_assembly(golden, tmp_path / "x", inter.replace("        77", "        79") + "/GRNOD/PART/79\nparts\n         1\n" + surf)
    run_check(golden, nom, tmp_path / "mnom", vpn, tmp_path / "chk3", tmp_path / "o3.inc", assem=assem2)
    d3 = load(tmp_path / "chk3" / "check.json")
    assert d3["code"] == "GEOM_TIE_PROJECTION" and d3["checks"]["tie"]["status"] == "FAIL"
    opts = write_json(tmp_path / "o.json", {"schema_version": 1, "tie": {"required": False}})
    run_check(golden, nom, tmp_path / "mnom", vpn, tmp_path / "chk4", tmp_path / "o4.inc", "--options", opts, assem=assem2)
    d4 = load(tmp_path / "chk4" / "check.json")
    assert d4["checks"]["tie"]["status"] == "NOT_EVALUATED" and "TIE_PARSE_SKIPPED" in {w["code"] for w in d4["warnings"]}


def test_check_refuses_existing_out_inc(golden, nominal_update, tmp_path):
    upd, vp = nominal_update
    assert run_morph(golden, upd, tmp_path / "mor")[0] == 0
    out_inc = tmp_path / "o.inc"
    out_inc.write_text("x")
    code, text = run_check(golden, upd, tmp_path / "mor", vp, tmp_path / "chk", out_inc)
    assert code == 3 and "GEOM_OUTPUT_EXISTS" in text and out_inc.read_text() == "x"


def test_morph_requires_ok_update(golden, tmp_path):
    code, _, _ = run_update(golden, tmp_path / "u", {"CUSH_L_POCKET_D_1": 25.0})
    assert code == 10
    code, text = run_morph(golden, tmp_path / "u", tmp_path / "m")
    assert code == 3 and load(tmp_path / "m" / "morph.json")["code"] == "GEOM_INPUT_INVALID"


# ------------------------------------------------------------- sweep / envelope
def run_sweep(g, upd, out, *extra):
    return run_morph(g, upd, out, "--sweep", *extra)


def test_sweep_envelope_deterministic_and_feasible(golden, nominal_update, tmp_path):
    upd, _ = nominal_update
    params = "CUSH_L_RIB_H_1,CUSH_L_FILLET_R_1"
    args = ("--params", params, "--steps", "5,20")
    for k in (1, 2):
        code, text = run_sweep(golden, upd, tmp_path / f"e{k}", *args)
        assert code == 0 and "PAICAD RESULT OK - envelope.json" in text, text
    for name in ("envelope.json", "envelope.csv", "parameter_features.json"):
        assert (tmp_path / "e1" / name).read_bytes() == (tmp_path / "e2" / name).read_bytes(), name
    env = load(tmp_path / "e1" / "envelope.json")
    assert env["schema_version"] == 1 and env["engine_version"] == paicad.__version__ and env["steps_pct"] == [5.0, 20.0]
    assert env["options"]["quality"]["min_stretch"] == 0.1 and env["sweep_id"].startswith("S-")
    rows = env["rows"]
    assert {r["param"] for r in rows} == set(params.split(","))
    for r in rows:
        assert r["direction"] in ("+", "-") and r["status"] in ("OK", "FAIL")
        assert (r["fail_code"] is None) == (r["status"] == "OK")
        assert r["min_stretch"] > 0 and r["max_aspect"] >= 1 and r["min_edge_ratio"] > 0 and r["inverted_elems"] >= 0
        assert r["boundary_dev_max_mm"] <= BOUNDARY_TOL and r["param_remeasure_err"]["rel"] <= REMEASURE_REL
    with open(tmp_path / "e1" / "envelope.csv", newline="") as f:
        table = list(csv.DictReader(f))
    assert len(table) == len(rows) and {"min_stretch", "max_aspect", "min_edge_ratio", "boundary_dev_max_mm", "fail_code", "param_remeasure_err_rel"} <= set(table[0])
    summ = {s["param"]: s for s in env["summary"]}
    feats = {f["name"]: f for f in load(tmp_path / "e1" / "parameter_features.json")["features"]}
    for p, s in summ.items():
        assert set(s["last_ok_pct"]) == {"+", "-"} and set(s["first_fail_code"]) == {"+", "-"}
        f = feats[p]
        assert f["feasible"]["source"] == "envelope" and f["feasible"]["sweep_id"] == env["sweep_id"]
        assert f["feasible"]["max"] == pytest.approx(f["nominal"] * (1 + s["last_ok_pct"]["+"] / 100))
        assert f["feasible"]["min"] == pytest.approx(f["nominal"] * (1 - s["last_ok_pct"]["-"] / 100))
        for d in ("+", "-"):
            dr = [r for r in rows if r["param"] == p and r["direction"] == d]
            first_fail = next((r for r in dr if r["status"] == "FAIL"), None)
            assert s["first_fail_pct"][d] == (first_fail["pct"] if first_fail else None)
    # group members follow their representative, unswept features keep the estimate
    g8 = next(gr for gr in golden["features"]["groups"] if gr["parameter"] == "CUSH_L_RIB_H_1")
    assert all(feats[m]["feasible"]["source"] == "envelope" for m in g8["members"])
    assert feats["CUSH_L_THK_3"]["feasible"]["source"] == "estimate"
    assert feats["CUSH_L_THK_3"]["feasible"]["min"] == next(f for f in golden["features"]["features"] if f["name"] == "CUSH_L_THK_3")["feasible"]["min"]


def test_sweep_stops_after_consecutive_failures_and_keeps_steps(golden, nominal_update, tmp_path):
    upd, _ = nominal_update
    opts = write_json(tmp_path / "o.json", {"schema_version": 1, "quality": {"min_edge_mm": 0, "min_edge_ratio": 0.01}})
    code, text = run_sweep(
        golden, upd, tmp_path / "e", "--params", "CUSH_L_POCKET_D_1", "--steps", "20,160,170,180", "--stop-after-fail", "2", "--keep-steps", "--options", opts
    )
    assert code == 0, text
    rows = load(tmp_path / "e" / "envelope.json")["rows"]
    plus = [r for r in rows if r["direction"] == "+"]
    assert [r["pct"] for r in plus] == [20.0, 160.0, 170.0]  # 160 and 170 %: floor through the bottom face -> stop
    assert plus[0]["status"] == "OK" and [r["fail_code"] for r in plus[1:]] == ["GEOM_CAD_FAILED", "GEOM_CAD_FAILED"]
    assert (tmp_path / "e" / "sweep" / "CUSH_L_POCKET_D_1" / "+20" / "morphed.inc").is_file()
    assert (tmp_path / "e" / "sweep" / "CUSH_L_POCKET_D_1" / "+20" / "check.json").is_file()
    assert (tmp_path / "e" / "sweep" / "CUSH_L_POCKET_D_1" / "+160" / "update.json").is_file()
    assert not (tmp_path / "e" / "sweep" / "CUSH_L_POCKET_D_1" / "+180").exists()


def test_sweep_requires_nominal_update(golden, tmp_path):
    code, _, _ = run_update(golden, tmp_path / "u", {"CUSH_L_RIB_H_1": 16.0})
    assert code == 0
    code, text = run_sweep(golden, tmp_path / "u", tmp_path / "e")
    assert code == 3 and "GEOM_INPUT_INVALID" in text and not (tmp_path / "e" / "envelope.json").exists()
    code, text = run_sweep(golden, tmp_path / "u", tmp_path / "e2", "--params", "NOPE")
    assert code == 3
