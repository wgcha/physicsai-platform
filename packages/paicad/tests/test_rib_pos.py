"""RIB_POS_U/V update / morph / check / sweep against build123d truth (extract-filter.md section 3.2, V-EF-4).

The features come from an extract with ``extract.filter`` (all types, so RIB_POS exists) of the development golden;
the truth of every sample is the cushion rebuilt with the ribs moved (``data/make_synthetic.py``).
"""

from __future__ import annotations

import json
from dataclasses import replace

import numpy as np
import pytest
from conftest import run_cli
from paicad.features import TYPE_ORDER
from paicad.kernel import load_brep, load_cad
from paicad.mesh import radioss
from paicad.meshdata import components_from_tag, load_tag, tet_volumes

UPDATE_FACE_TOL = 0.01  # mm, update B-rep vs truth
VOLUME_REL_TOL = 1e-3
BOUNDARY_TOL = 0.05  # mm, morphed boundary nodes vs truth
PARAM_ABS = 0.05  # deviation.param_abs_mm default


def load(p):
    return json.loads(p.read_text(encoding="utf-8"))


def write_json(path, obj):
    path.write_text(json.dumps(obj), encoding="utf-8")
    return path


@pytest.fixture(scope="module")
def rp(golden, tmp_path_factory):
    """Golden with RIB_POS features: filtered extract (all types) -> tag -> nominal update."""
    root = tmp_path_factory.mktemp("ribpos")
    opts = write_json(root / "opts.json", {"schema_version": 1, "extract": {"filter": {"types": list(TYPE_ORDER)}}})
    ex, tg = root / "extract", root / "tag"
    code, text = run_cli("extract", "--cad", golden["step"], "--out-dir", ex, "--renum-csv", golden["renum"], "--options", opts, "--no-png")
    assert code == 0, text
    fp = ex / "parameter_features.json"
    code, text = run_cli(
        "tag", "--cad", golden["step"], "--features", fp, "--baseline-inc", golden["baseline"], "--renum-csv", golden["renum"], "--assem-dir", golden["assem"], "--out-dir", tg
    )
    assert code == 0, text
    doc = load(fp)
    by_nom: dict = {}
    for f in doc["features"]:  # first feature of a (body, type, nominal) = group representative when grouped
        by_nom.setdefault((f["body"], f["type"], f["nominal"]), f["name"])
    g = dict(golden, features_path=fp, features=doc, tag_dir=tg, root=root, by_nom=by_nom)
    code, text, vp = run_update(g, root / "update0", {})
    assert code == 0, text
    g["update0"] = root / "update0"
    return g


def run_update(g, out, values):
    vp = write_json(out.parent / f"{out.name}_values.json", {"schema_version": 1, "values": values})
    code, text = run_cli("update", "--cad", g["step"], "--features", g["features_path"], "--values", vp, "--out-dir", out, "--tag-dir", g["tag_dir"])
    return code, text, vp


def run_morph(g, upd, out, *extra):
    return run_cli("morph", "--baseline-inc", g["baseline"], "--tag-dir", g["tag_dir"], "--features", g["features_path"], "--update-dir", upd, "--out-dir", out, *extra)


def run_check(g, upd, mor, vp, out, out_inc):
    return run_cli(
        "check", "--baseline-inc", g["baseline"], "--morph-dir", mor, "--update-dir", upd, "--tag-dir", g["tag_dir"], "--features", g["features_path"],
        "--values", vp, "--assem-dir", g["assem"], "--renum-csv", g["renum"], "--out-dir", out, "--out-inc", out_inc,
    )


def truth_bodies(spec, path):
    from data.make_synthetic import build_bodies, write_step

    write_step(path, build_bodies(spec))
    _, bodies = load_cad(path)
    return {b.name: b for b in bodies}


def case(g, axis: str, delta: float):
    """(values, truth spec): CUSH_L rib 1 (x 25..31) moved along U (x) - CUSH_R mirror rib gets the mirrored value so
    the truth stays symmetric - or every rib along V (y, one mirror group)."""
    from data.make_synthetic import CushionSpec

    s = CushionSpec()
    n = g["by_nom"]
    if axis == "U":
        return {n[("CUSH_L", "RIB_POS_U", 28.0)]: 28.0 + delta, n[("CUSH_R", "RIB_POS_U", 92.0)]: 92.0 - delta}, replace(s, rib_x=(25.0 + delta, 89.0))
    return {n[("CUSH_L", "RIB_POS_V", 40.0)]: 40.0 + delta}, replace(s, rib_y=(15.0 + delta, 65.0 + delta))


def assert_sample_matches(g, upd, truth):
    names = [b["body"] for b in g["features"]["bodies"]]
    sample = dict(zip(names, load_brep(upd / "sample.brep", names)))
    worst = 0.0
    for name, body in sample.items():
        t = truth[name]
        assert abs(body.summary().volume - t.summary().volume) <= VOLUME_REL_TOL * t.summary().volume
        for f in body.topology().faces:
            pts = body.sample_face(f.id, 5)
            if len(pts):
                worst = max(worst, float(t.distance(pts).max()))
    assert worst <= UPDATE_FACE_TOL, worst
    return sample


@pytest.mark.parametrize("delta", [2.0, -2.0, 5.0, -5.0])
@pytest.mark.parametrize("axis", ["U", "V"])
def test_rib_pos_update_morph_check_match_truth(rp, tmp_path, axis, delta):
    values, spec = case(rp, axis, delta)
    upd, mor, chk = tmp_path / "upd", tmp_path / "mor", tmp_path / "chk"
    code, text, vp = run_update(rp, upd, values)
    assert code == 0, text
    u = load(upd / "update.json")
    ap = {a["name"]: a for a in u["applied"]}
    for k in values:
        assert ap[k]["op"] == "AXIS_SHIFT" and len(ap[k]["moved"]) == 5 and len(ap[k]["fixed"]) == 1
    pos = {p["name"]: p for p in u["positions"]}
    for k, v in values.items():
        assert pos[k]["expected_measured"] == pytest.approx(v, abs=1e-9) and pos[k]["mode"] == "nearest_fixed"
    truth = truth_bodies(spec, tmp_path / "truth.step")
    assert_sample_matches(rp, upd, truth)
    fm = load(upd / "face_map.json")
    assert fm["CUSH_L"]["uv_fallback"]  # base face: rib foot print (inner wire) moved -> section 6.4 fallback
    code, text = run_morph(rp, upd, mor)
    assert code == 0, text
    base, new = (radioss.parse_text(p.read_bytes().decode("latin-1")) for p in (rp["baseline"], mor / "morphed.inc"))
    for c in components_from_tag(base, load_tag(rp["tag_dir"])):
        bnd = c.kind > 0
        assert truth[c.body].distance(new.xyz[c.gidx[bnd]]).max() <= BOUNDARY_TOL
        assert (tet_volumes(new.xyz[c.gidx], c.tets) > 0).all()
    code, text = run_check(rp, upd, mor, vp, chk, tmp_path / "out.inc")
    d = load(chk / "check.json")
    assert d["checks"]["param"]["status"] == "PASS", d["checks"]["param"]
    rib = [it for it in d["checks"]["param"]["items"] if "_RIB_U_" in it["name"] or "_RIB_V_" in it["name"]]
    assert len(rib) == 8
    for it in rib:
        assert it["err"] <= PARAM_ABS, it
    assert d["checks"]["deviation"]["max_mm"] <= BOUNDARY_TOL and d["checks"]["quality"]["inverted"] == 0
    assert code == 0 and d["status"] == "PASS"


def test_rib_pos_with_rib_thickness_change(rp, tmp_path):
    """RIB_THICKNESS (group, outer side of each rib) + RIB_POS in one sample: vector sum - the thickness move keeps its
    side, the rib then moves by the position delta."""
    from data.make_synthetic import CushionSpec

    n = rp["by_nom"]
    u1, r2 = n[("CUSH_L", "RIB_POS_U", 28.0)], n[("CUSH_R", "RIB_POS_U", 92.0)]
    values = {"CUSH_L_RIB_T_1": 6.6, u1: 30.0, r2: 90.0}
    code, text, _ = run_update(rp, tmp_path / "u", values)
    assert code == 0, text
    truth = truth_bodies(replace(CushionSpec(), rib_t=6.6, rib_x=(25.0 - 0.6 + 2.0, 89.0)), tmp_path / "t.step")
    assert_sample_matches(rp, tmp_path / "u", truth)
    pos = {p["name"]: p["expected_measured"] for p in load(tmp_path / "u" / "update.json")["positions"]}
    assert pos[u1] == pytest.approx(29.7) and pos[r2] == pytest.approx(90.3)


def test_rib_pos_keeps_distance_to_fixed_face_when_wall_moves(rp, tmp_path):
    """THICKNESS change of the body length moves one end wall; nearest_fixed keeps the rib's distance to its reference
    face, the measured value (from the bbox minimum) follows the wall shift (update positions)."""
    n = rp["by_nom"]
    thk = n[("CUSH_L", "THICKNESS", 120.0)]
    u1 = n[("CUSH_L", "RIB_POS_U", 28.0)]
    code, text, _ = run_update(rp, tmp_path / "u", {thk: 126.0})
    assert code == 0, text
    u = load(tmp_path / "u" / "update.json")
    p = next(x for x in u["positions"] if x["name"] == u1)
    ref = int(p["ref_face"][1:])
    names = [b["body"] for b in rp["features"]["bodies"]]
    nom = dict(zip(names, load_brep(rp["update0"] / "sample.brep", names)))["CUSH_L"]
    new = dict(zip(names, load_brep(tmp_path / "u" / "sample.brep", names)))["CUSH_L"]
    feat = next(f for f in rp["features"]["features"] if f["name"] == u1)
    lat = [int(x[1:]) for x in feat["measure"]["faces"][1:-1]]

    def center(b):
        t = b.topology()
        xs = [t.face(g) for g in lat if abs(t.face(g).normal[0]) > 0.9]
        return 0.5 * sum(float(f.centroid[0]) for f in xs)

    gap0 = center(nom) - float(nom.topology().face(ref).centroid[0])
    gap1 = center(new) - float(new.topology().face(ref).centroid[0])
    assert gap1 == pytest.approx(gap0, abs=1e-9)
    shift = float(new.summary().bbox[0]) - float(nom.summary().bbox[0])
    assert p["expected_measured"] == pytest.approx(28.0 - shift, abs=1e-9)


@pytest.mark.parametrize(
    "axis, value, kind",
    [("U", 16.0, "BOUNDARY_OVERLAP"), ("V", 60.0, "BOUNDARY_OVERLAP")],  # rib onto the hole / foot print past the base edge
)
def test_rib_pos_collisions(rp, tmp_path, axis, value, kind):
    n = rp["by_nom"]
    name = n[("CUSH_L", "RIB_POS_U", 28.0)] if axis == "U" else n[("CUSH_L", "RIB_POS_V", 40.0)]
    code, text, _ = run_update(rp, tmp_path / "u", {name: value})
    assert code == 10 and "GEOM_FEATURE_COLLISION" in text, text
    c = load(tmp_path / "u" / "update.json")["collisions"]
    assert kind in {x["kind"] for x in c} and any(name in x["features"] for x in c)


def test_rib_pos_sweep_in_mm_and_deterministic(rp, tmp_path):
    name = rp["by_nom"][("CUSH_L", "RIB_POS_V", 40.0)]
    code, text = run_morph(rp, rp["update0"], tmp_path / "e", "--sweep", "--params", name, "--pos-steps", "2", "--check", "off")
    assert code == 0, text
    env = load(tmp_path / "e" / "envelope.json")
    assert {(r["unit"], r["step"]) for r in env["rows"]} == {("mm", 2.0)} and {r["value"] for r in env["rows"]} == {38.0, 42.0}
    assert all(r["status"] == "OK" for r in env["rows"]) and env["summary"][0]["unit"] == "mm"
    outs = []
    for k in (1, 2):
        code, text, _ = run_update(rp, tmp_path / f"u{k}", {name: 43.0})
        assert code == 0, text
        code, text = run_morph(rp, tmp_path / f"u{k}", tmp_path / f"m{k}")
        assert code == 0, text
        outs.append(((tmp_path / f"u{k}" / "sample.brep").read_bytes(), (tmp_path / f"m{k}" / "morphed.inc").read_bytes()))
    assert outs[0] == outs[1]


def test_rib_pos_view_dimension(rp, tmp_path):
    code, text = run_cli("view", "export", "--cad", rp["step"], "--features", rp["features_path"], "--out-dir", tmp_path / "v")
    assert code == 0, text
    m = load(tmp_path / "v" / "view_manifest.json")
    f = next(x for x in m["features"] if x["name"] == rp["by_nom"][("CUSH_L", "RIB_POS_U", 28.0)])
    d = f["dimension"]
    assert d["kind"] == "position" and d["value"] == 28.0 and d["geom_len"] == pytest.approx(28.0, abs=1e-6)
    assert np.isclose(d["p0"][0], -150.0) and np.isclose(d["p1"][0], -122.0)
