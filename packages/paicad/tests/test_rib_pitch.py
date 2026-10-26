"""RIB_PITCH_U/V - rib rows (rib-gap.md section 10, V-RG-1..8 paicad part).

Golden: ``data/make_ribrow.py`` (ROW_L + mirror ROW_R, rows of 3 / 5 / 4 ribs along x and 3 ribs along y). The truth
of every update sample is the set rebuilt with the rib centers of the anchor rule (computed here independently).
"""

from __future__ import annotations

import copy
import json

import numpy as np
import pytest
from conftest import run_cli
from paicad import options
from paicad.common import PaicadError
from paicad.features import RIB_PITCH_TYPES, TYPE_ORDER
from paicad.kernel import FaceMove, load_brep, load_cad
from paicad.mesh import radioss
from paicad.meshdata import components_from_tag, load_tag, tet_volumes

UPDATE_FACE_TOL = 0.01  # mm, update B-rep vs truth
VOLUME_REL_TOL = 1e-3
BOUNDARY_TOL = 0.05  # mm, morphed boundary nodes vs truth
PARAM_ABS = 0.05
SPEC_ROW = {(3, "x"): "U1", (5, "x"): "U2", (4, "x"): "U3", (3, "y"): "V1"}  # (rib count, axis) -> make_ribrow row
OLD_TYPES = [t for t in TYPE_ORDER if t not in RIB_PITCH_TYPES]


def load(p):
    return json.loads(p.read_text(encoding="utf-8"))


def write_json(path, obj):
    path.write_text(json.dumps(obj), encoding="utf-8")
    return path


def filter_opts(path, types=None, **extra):
    return write_json(path, {"schema_version": 1, "extract": {"filter": {"types": list(types or TYPE_ORDER)}}, **extra})


def index_doc(doc: dict) -> tuple[dict, dict]:
    """({(body, spec row): rib_rows entry}, {(body, spec row): [pitch names by k]})."""
    rows, spec_of = {}, {}
    for r in doc.get("rib_rows") or []:
        sid = SPEC_ROW[(len(r["ribs"]), r["axis"])]
        rows[(r["body"], sid)] = r
        spec_of[(r["body"], r["id"])] = sid
    pitch: dict = {}
    for f in doc["features"]:
        if f["type"] in RIB_PITCH_TYPES:
            pitch.setdefault((f["body"], spec_of[(f["body"], f["row"]["id"])]), {})[f["row"]["k"]] = f["name"]
    return rows, {k: [v[i] for i in sorted(v)] for k, v in pitch.items()}


def extract(g, out, opts):
    code, text = run_cli("extract", "--cad", g["step"], "--out-dir", out, "--renum-csv", g["renum"], "--options", opts, "--no-png")
    assert code == 0, text
    return load(out / "parameter_features.json")


@pytest.fixture(scope="module")
def rr(tmp_path_factory):
    """Rib row golden: filtered extract (all 13 types) -> tag -> nominal update."""
    from data.make_ribrow import make_all

    root = tmp_path_factory.mktemp("ribrow")
    g = make_all(root / "set")
    opts = filter_opts(root / "opts.json")
    ex, tg = root / "extract", root / "tag"
    doc = extract(g, ex, opts)
    fp = ex / "parameter_features.json"
    code, text = run_cli("tag", "--cad", g["step"], "--features", fp, "--baseline-inc", g["baseline"], "--renum-csv", g["renum"], "--assem-dir", g["assem"], "--out-dir", tg)
    assert code == 0, text
    rows, pitch = index_doc(doc)
    g.update(root=root, opts=opts, extract_dir=ex, features_path=fp, features=doc, tag_dir=tg, rows=rows, pitch=pitch)
    code, text, _ = run_update(g, root / "update0", {})
    assert code == 0, text
    g["update0"] = root / "update0"
    return g


def run_update(g, out, values, features=None, *extra):
    vp = write_json(out.parent / f"{out.name}_values.json", {"schema_version": 1, "values": values})
    code, text = run_cli("update", "--cad", g["step"], "--features", features or g["features_path"], "--values", vp, "--out-dir", out, *extra)
    return code, text, vp


# ------------------------------------------------------------------ truth
def new_centers(c, anchor: str, dp: dict, dpos: float = 0.0) -> list[float]:
    """Rib centers after pitch deltas ``dp`` {k: delta} (rib-gap.md section 4.2, written independently)."""
    n = len(c)
    p = [c[i + 1] - c[i] + dp.get(i + 1, 0.0) for i in range(n - 1)]
    kind, m = anchor.split(":")
    m = int(m)
    out = [0.0] * n
    if kind == "rib":
        out[m - 1] = c[m - 1] + dpos
        lo = hi = m - 1
    else:
        mid = 0.5 * (c[m - 1] + c[m])
        out[m - 1], out[m] = mid - 0.5 * p[m - 1], mid + 0.5 * p[m - 1]
        lo, hi = m - 1, m
    for i in range(hi + 1, n):
        out[i] = out[i - 1] + p[i - 1]
    for i in range(lo - 1, -1, -1):
        out[i] = out[i + 1] - p[i]
    return out


def spec_with(changes: dict, **kw):
    """RibRowSpec with {spec row: centers} and keyword overrides."""
    from data.make_ribrow import RibRowSpec, with_centers

    s = RibRowSpec(**kw)
    for rid, cs in changes.items():
        s = with_centers(s, rid, cs)
    return s


def truth_bodies(spec, path):
    from data.make_ribrow import build_bodies, write_step

    write_step(path, build_bodies(spec))
    _, bodies = load_cad(path)
    return {b.name: b for b in bodies}


def assert_sample_matches(g, upd, truth, only_faces: dict | None = None):
    names = [b["body"] for b in g["features"]["bodies"]]
    sample = dict(zip(names, load_brep(upd / "sample.brep", names)))
    worst = 0.0
    for name, t in truth.items():
        body = sample[name]
        if only_faces is None:
            assert abs(body.summary().volume - t.summary().volume) <= VOLUME_REL_TOL * t.summary().volume
        for f in body.topology().faces:
            if only_faces is not None and f.id not in only_faces.get(name, ()):
                continue
            pts = body.sample_face(f.id, 5)
            if len(pts):
                worst = max(worst, float(t.distance(pts).max()))
    assert worst <= UPDATE_FACE_TOL, worst
    return sample


def base_centers(rid):
    from data.make_ribrow import BASE_ROWS

    return list(BASE_ROWS[rid][1])


# ------------------------------------------------------------------ V-RG-1 compatibility
def test_without_rib_pitch_outputs_unchanged(rr, tmp_path):
    doc = extract(rr, tmp_path / "e", filter_opts(tmp_path / "o.json", OLD_TYPES))
    assert "rib_rows" not in doc and not any(f["type"] in RIB_PITCH_TYPES for f in doc["features"])
    assert not any("row" in f for f in doc["features"])
    st = load(tmp_path / "e" / "extract_stats.json")
    for b in st["bodies"]:
        assert not set(RIB_PITCH_TYPES) & set(b["types"])
        assert b["types"]["RIB_POS_U"]["kept"] == 16 and "row_member" not in b["types"]["RIB_POS_U"]["excluded"]
    # no filter: legacy types only, no rib_rows
    code, text = run_cli("extract", "--cad", rr["step"], "--out-dir", tmp_path / "p", "--no-png")
    assert code == 0, text
    assert "rib_rows" not in load(tmp_path / "p" / "parameter_features.json")


def test_rib_gap_options_validated(rr, tmp_path, capsys):
    for bad in ({"anchor": "middle"}, {"min_gap_mm": 0}, {"slender_min": 0.5}, {"overlap_min": 1.5}, {"gap": 1}):
        code, text = run_cli("extract", "--cad", rr["step"], "--out-dir", tmp_path / "e", "--no-png", "--options", filter_opts(tmp_path / "o.json", rib_gap=bad))
        err = capsys.readouterr().err
        assert code == 3 and "GEOM_INPUT_INVALID" in text and "rib_gap" in err, (bad, text, err)
    assert options.FILTER_TYPES == TYPE_ORDER and len(TYPE_ORDER) == 13
    o = options.load(None)
    assert "rib_gap" not in o and options.rib_gap_options(o) == {"anchor": "center", "min_gap_mm": 1.0, "slender_min": 1.5, "overlap_min": 0.5}


# ------------------------------------------------------------------ V-RG-2 recognition
def test_rows_recognized(rr):
    doc = rr["features"]
    want = {"U1": (3, "rib:2"), "U2": (5, "rib:3"), "U3": (4, "mid:2"), "V1": (3, "rib:2")}
    for body in ("ROW_L", "ROW_R"):
        assert {sid for (b, sid) in rr["rows"] if b == body} == set(want)
        for sid, (n, anchor) in want.items():
            r = rr["rows"][(body, sid)]
            assert len(r["ribs"]) == n and r["anchor"] == anchor
            assert [x["thickness"] for x in r["ribs"]] == [6.0] * n
            assert all(r["ribs"][i + 1]["center"] > r["ribs"][i]["center"] for i in range(n - 1))
            assert len(rr["pitch"][(body, sid)]) == n - 1
        # names: per body and type, (row number, k) order
        for t in RIB_PITCH_TYPES:
            fs = [f for f in doc["features"] if f["body"] == body and f["type"] == t]
            assert [f["name"] for f in fs] == [f"{body}_{t}_{k}" for k in range(1, len(fs) + 1)]
            assert [(int(f["row"]["id"][1:]), f["row"]["k"]) for f in fs] == sorted((int(f["row"]["id"][1:]), f["row"]["k"]) for f in fs)
    L = {r["id"]: r for r in doc["rib_rows"] if r["body"] == "ROW_L"}
    assert [L[k]["ribs"][0]["center"] for k in ("U1", "U2", "U3")] == [-176.0, -176.0, -158.0]  # (axis, first center, b)
    for f in doc["features"]:
        if f["type"] in RIB_PITCH_TYPES:
            r = next(x for x in doc["rib_rows"] if x["body"] == f["body"] and x["id"] == f["row"]["id"])
            k = f["row"]["k"]
            assert f["nominal"] == pytest.approx(r["ribs"][k]["center"] - r["ribs"][k - 1]["center"])
            assert f["measure"]["method"] == "rib_pitch" and len(f["measure"]["faces"]) == 4 and f["row"]["n"] == len(r["ribs"])
            assert f["measure"]["faces"] == [r["ribs"][k - 1]["minus"], r["ribs"][k - 1]["plus"], r["ribs"][k]["minus"], r["ribs"][k]["plus"]]
            assert f["faces"]["fixed"] == [r["base"]]
            assert set(f["faces"]["moving"]) <= set(f["face_signatures"])
    st = {b["body"]: b for b in load(rr["extract_dir"] / "extract_stats.json")["bodies"]}
    for b in st.values():
        u, v = b["types"]["RIB_PITCH_U"], b["types"]["RIB_PITCH_V"]
        assert (u["candidates"], u["kept"], u["excluded"]) == (13, 9, {"not_slender": 1})  # 12 row ribs + pillar
        assert (v["candidates"], v["kept"], v["excluded"]) == (3, 2, {})
        assert b["types"]["RIB_POS_U"]["excluded"] == {"row_member": 10} and b["types"]["RIB_POS_V"]["excluded"] == {"row_member": 2}
        assert b["rib_rejects"].get("cap_not_convex", 0) > 0  # partition rib touching the wall is not a rib
    # RIB_POS of row ribs (same axis): only the center rib of odd rows
    for (body, sid), r in rr["rows"].items():
        t = "RIB_POS_U" if r["axis"] == "x" else "RIB_POS_V"
        caps = {f["measure"]["faces"][0] for f in doc["features"] if f["type"] == t and f["body"] == body}
        kept = [x["index"] for x in r["ribs"] if x["cap"] in caps]
        assert kept == ([] if len(r["ribs"]) % 2 == 0 else [(len(r["ribs"]) + 1) // 2]), (body, sid)


def _variant_extract(tmp_path, name, **kw):
    from data.make_ribrow import RibRowSpec, build_bodies, write_step

    spec = RibRowSpec(L=100.0, W=60.0, wall_t=0.0, pillar=None, partition=None, hole=None, mirror=False, names=("VAR", "VAR_R"), **kw)
    step = tmp_path / f"{name}.step"
    write_step(step, build_bodies(spec))
    code, text = run_cli("extract", "--cad", step, "--out-dir", tmp_path / name, "--no-png", "--options", filter_opts(tmp_path / f"{name}.json"))
    assert code == 0, text
    st = load(tmp_path / name / "extract_stats.json")["bodies"][0]
    return load(tmp_path / name / "parameter_features.json"), st


def test_row_breaks(tmp_path):
    # staggered: two equally near +x neighbours -> every link cut
    doc, st = _variant_extract(tmp_path, "stagger", rows={"A": ("x", (20.0,), (10.0, 40.0))}, extra_boxes=((37.0, 10.0, 43.0, 24.0, 10.0), (37.0, 26.0, 43.0, 40.0, 10.0)))
    assert doc["rib_rows"] == [] and st["types"]["RIB_PITCH_U"]["excluded"] == {"row_branch": 3}
    # bent side (convex kink of 1.9 deg: two lateral faces look +x within the draft angle) -> shape; the straight rib
    # next to it then has no neighbour
    bent = (((40.0, 10.0), (46.0, 10.0), (46.5, 25.0), (46.0, 40.0), (40.0, 40.0)), 10.0)
    doc, st = _variant_extract(tmp_path, "bent", rows={"A": ("x", (20.0,), (10.0, 40.0))}, extra_polys=(bent,))
    assert doc["rib_rows"] == [] and st["types"]["RIB_PITCH_U"]["excluded"] == {"shape": 1, "row_single": 1}
    # a partition (touching the plate edge: not a rib) between two ribs separates them
    doc, st = _variant_extract(tmp_path, "wall", rows={"A": ("x", (20.0, 40.0), (20.0, 50.0))}, extra_boxes=((29.0, 0.0, 31.0, 55.0, 10.0),))
    assert doc["rib_rows"] == [] and st["types"]["RIB_PITCH_U"]["excluded"] == {"row_single": 2}
    assert st["rib_rejects"].get("base_mismatch", 0) >= 1
    # same pair without the partition: one row of 2 (even, mid:1)
    doc, st = _variant_extract(tmp_path, "pair", rows={"A": ("x", (20.0, 40.0), (20.0, 50.0))})
    assert [(len(r["ribs"]), r["anchor"]) for r in doc["rib_rows"]] == [(2, "mid:1")] and st["types"]["RIB_PITCH_U"]["kept"] == 1


def test_subset_invariant_and_deterministic(rr, tmp_path):
    """EF-INV with RIB_PITCH (rib-gap.md section 2.3): pitch features / rows do not depend on the other selected types;
    the same input gives byte-identical output."""
    full = rr["features"]

    def keyed(doc, types):
        out = {}
        for f in doc["features"]:
            if f["type"] in types:
                out[f["name"]] = (f["nominal"], f["measure"], f["row"], f["faces"], f["range"], f["feasible"]["min"], f["feasible"]["max"])
        return out

    def rows(doc, axes):
        return [{k: v for k, v in r.items() if k != "end_limited_by"} for r in doc["rib_rows"] if r["axis"] in axes]

    sub = extract(rr, tmp_path / "s", filter_opts(tmp_path / "s.json", list(RIB_PITCH_TYPES)))
    assert keyed(sub, RIB_PITCH_TYPES) == keyed(full, RIB_PITCH_TYPES) and rows(sub, "xy") == rows(full, "xy")
    only_u = extract(rr, tmp_path / "u", filter_opts(tmp_path / "u.json", ["RIB_PITCH_U"]))
    assert keyed(only_u, RIB_PITCH_TYPES) == keyed(full, ("RIB_PITCH_U",)) and rows(only_u, "xy") == rows(full, "x")
    again = tmp_path / "again"
    extract(rr, again, rr["opts"])
    assert (again / "parameter_features.json").read_bytes() == rr["features_path"].read_bytes()
    assert (again / "parameter_extracted.xml").read_bytes() == (rr["extract_dir"] / "parameter_extracted.xml").read_bytes()


# ------------------------------------------------------------------ V-RG-7 symmetry
def test_symmetry_groups(rr):
    doc = rr["features"]
    row_of = {f["name"]: (f["body"], f["row"]["id"]) for f in doc["features"] if f["type"] in RIB_PITCH_TYPES}
    pitch_groups = [g for g in doc["groups"] if g["members"][0] in row_of]
    for g in pitch_groups:
        rows = [row_of[m] for m in g["members"]]
        assert len(set(rows)) == len(rows), g  # never two pitches of one row (RG-3)
        assert {b for b, _ in rows} == {"ROW_L", "ROW_R"}
    assert len(pitch_groups) == 11  # every ROW_L pitch with its mirror in ROW_R
    # U2 pitches are symmetric about the plate center (18, 20, 20, 18): still one group each
    assert sum(1 for g in pitch_groups if g["parameter"] in rr["pitch"][("ROW_L", "U2")]) == 4


# ------------------------------------------------------------------ V-RG-3 update vs truth
CASES = [(sid, k) for sid, n in (("U1", 3), ("U2", 5), ("U3", 4), ("V1", 3)) for k in range(1, n)]


@pytest.mark.parametrize("delta", [3.0, -3.0])
@pytest.mark.parametrize("sid, k", CASES)
def test_single_pitch_matches_truth(rr, tmp_path, sid, k, delta):
    row = rr["rows"][("ROW_L", sid)]
    name = rr["pitch"][("ROW_L", sid)][k - 1]
    nom = next(f["nominal"] for f in rr["features"]["features"] if f["name"] == name)
    code, text, _ = run_update(rr, tmp_path / "u", {name: nom + delta})
    assert code == 0, text
    u = load(tmp_path / "u" / "update.json")
    c0 = base_centers(sid)
    want = new_centers(c0, row["anchor"], {k: delta})
    assert_sample_matches(rr, tmp_path / "u", truth_bodies(spec_with({sid: want}), tmp_path / "t.step"))
    ur = next(r for r in u["rib_rows"] if r["body"] == "ROW_L" and r["id"] == row["id"])
    assert all(abs(x["thickness_measured"] - 6.0) <= 1e-6 and x["thickness_expected"] == 6.0 for x in ur["ribs"])
    shifts = [x["shift_mm"] for x in ur["ribs"]]
    assert shifts == pytest.approx([w - c for w, c in zip(want, c0)], abs=1e-9)
    kind, m = row["anchor"].split(":")
    m = int(m)
    if kind == "rib":
        assert shifts[m - 1] == 0.0
    else:  # even row: mid point fixed, center pitch split half / half
        assert shifts[m - 1] + shifts[m] == pytest.approx(0.0, abs=1e-12)
        if k == m:
            assert shifts[m - 1] == pytest.approx(-delta / 2) and shifts[m] == pytest.approx(delta / 2)
    p = {x["name"]: x for x in ur["pitches"]}
    assert p[name]["value"] == nom + delta and p[name]["measured"] == pytest.approx(nom + delta, abs=1e-6)
    assert p[name]["gap"] == pytest.approx(nom + delta - 6.0, abs=1e-6)
    ap = {a["name"]: a for a in u["applied"]}[name]
    assert ap["op"] == "RIB_ROW_SHIFT" and ap["ref_rule"] == "row_anchor" and ap["fixed"] == [row["base"]]
    outer = {f for f in next(f for f in rr["features"]["features"] if f["name"] == name)["faces"]["moving"]}
    assert set(ap["moved"]) == outer


def test_several_pitches_at_once(rr, tmp_path):
    vals, changes = {}, {}
    for sid, dps in (("U2", {1: 2.0, 2: -3.0, 3: 3.0, 4: -1.5}), ("U3", {1: -2.0, 2: 3.0, 3: 2.0})):
        row = rr["rows"][("ROW_L", sid)]
        names = rr["pitch"][("ROW_L", sid)]
        for k, d in dps.items():
            vals[names[k - 1]] = next(f["nominal"] for f in rr["features"]["features"] if f["name"] == names[k - 1]) + d
        changes[sid] = new_centers(base_centers(sid), row["anchor"], dps)
    code, text, _ = run_update(rr, tmp_path / "u", vals)
    assert code == 0, text
    assert_sample_matches(rr, tmp_path / "u", truth_bodies(spec_with(changes), tmp_path / "t.step"))
    m3 = rr["rows"][("ROW_L", "U3")]
    ur = next(r for r in load(tmp_path / "u" / "update.json")["rib_rows"] if r["body"] == "ROW_L" and r["id"] == m3["id"])
    c = [x["center_expected"] for x in ur["ribs"]]
    assert 0.5 * (c[1] + c[2]) == pytest.approx(0.5 * (m3["ribs"][1]["center"] + m3["ribs"][2]["center"]), abs=1e-9)  # M fixed


@pytest.mark.parametrize("mode", ["first", "last"])
def test_first_last_anchor_mirrored(rr, tmp_path, mode):
    opts = filter_opts(tmp_path / "o.json", rib_gap={"anchor": mode})
    doc = extract(rr, tmp_path / "e", opts)
    rows, pitch = index_doc(doc)
    a_l, a_r = rows[("ROW_L", "U1")]["anchor"], rows[("ROW_R", "U1")]["anchor"]
    assert (a_l, a_r) == (("rib:1", "rib:3") if mode == "first" else ("rib:3", "rib:1"))  # mirror plane normal to a
    assert rows[("ROW_L", "V1")]["anchor"] == rows[("ROW_R", "V1")]["anchor"] == ("rib:1" if mode == "first" else "rib:3")
    k = 2 if mode == "first" else 1
    name = pitch[("ROW_L", "U1")][k - 1]
    nom = next(f["nominal"] for f in doc["features"] if f["name"] == name)
    code, text, _ = run_update(rr, tmp_path / "u", {name: nom + 3.0}, tmp_path / "e" / "parameter_features.json", "--options", opts)
    assert code == 0, text
    want = new_centers(base_centers("U1"), a_l, {k: 3.0})
    assert want[0 if mode == "first" else 2] == base_centers("U1")[0 if mode == "first" else 2]
    assert_sample_matches(rr, tmp_path / "u", truth_bodies(spec_with({"U1": want}), tmp_path / "t.step"))  # both bodies (group)


def test_rib_thickness_with_pitch_symmetric(rr, tmp_path):
    """RIB_THICKNESS of row ribs + a pitch in one sample: pitch = value, thickness = value, the thickness change is
    symmetric about the rib center (gap = pitch - half thickness sum)."""
    doc = rr["features"]
    row_faces = {(r["body"], x) for r in doc["rib_rows"] for rb in r["ribs"] for x in (rb["minus"], rb["plus"])}
    grp = {g["parameter"]: g["members"] for g in doc["groups"]}
    by_name = {f["name"]: f for f in doc["features"]}
    vals = {}
    for f in doc["features"]:
        if f["type"] != "RIB_THICKNESS" or (f["group"] is not None and f["name"] not in grp):
            continue
        mem = [by_name[m] for m in grp.get(f["name"], [f["name"]])]
        hits = [all((m["body"], x) in row_faces for x in m["measure"]["faces"]) for m in mem]
        assert all(hits) or not any(hits)
        if all(hits):
            vals[f["name"]] = 7.0
    p1 = rr["pitch"][("ROW_L", "U1")][0]
    vals[p1] = 20.0
    code, text, _ = run_update(rr, tmp_path / "u", vals)
    assert code == 0, text
    from data.make_ribrow import BASE_ROWS

    thick = {(rid, i): 7.0 for rid, (_, cs, _) in BASE_ROWS.items() for i in range(1, len(cs) + 1)}
    want = new_centers(base_centers("U1"), "rib:2", {1: 2.0})
    assert_sample_matches(rr, tmp_path / "u", truth_bodies(spec_with({"U1": want}, thickness=thick), tmp_path / "t.step"))
    for ur in load(tmp_path / "u" / "update.json")["rib_rows"]:
        assert all(x["thickness_expected"] == pytest.approx(7.0) and x["thickness_measured"] == pytest.approx(7.0, abs=1e-6) for x in ur["ribs"])
        for p in ur["pitches"]:
            assert p["gap"] == pytest.approx(p["measured"] - 7.0, abs=1e-6)
            assert p["measured"] == pytest.approx(p["value"], abs=1e-6)


def test_center_rib_position_moves_row(rr, tmp_path):
    doc = rr["features"]
    row = rr["rows"][("ROW_L", "U1")]
    name = next(f["name"] for f in doc["features"] if f["type"] == "RIB_POS_U" and f["measure"]["faces"][0] == row["ribs"][1]["cap"])
    nom = next(f["nominal"] for f in doc["features"] if f["name"] == name)
    code, text, _ = run_update(rr, tmp_path / "u", {name: nom + 2.0})
    assert code == 0, text
    u = load(tmp_path / "u" / "update.json")
    pos = {p["name"]: p for p in u["positions"]}[name]
    assert pos["mode"] == "row_anchor" and pos["expected_measured"] == pytest.approx(nom + 2.0, abs=1e-9)
    truth = truth_bodies(spec_with({"U1": [c + 2.0 for c in base_centers("U1")]}, mirror=False), tmp_path / "t.step")
    assert_sample_matches(rr, tmp_path / "u", truth)
    ap = {a["name"]: a for a in u["applied"]}[name]
    assert ap["op"] == "AXIS_SHIFT" and ap["ref_rule"] == "row_anchor"


# ------------------------------------------------------------------ V-RG-4 collisions / errors
def _collision(rr, tmp_path, vals):
    code, text, _ = run_update(rr, tmp_path / "u", vals)
    assert code == 10 and "GEOM_FEATURE_COLLISION" in text, text
    return load(tmp_path / "u" / "update.json")["collisions"]


def test_pitch_below_min_gap(rr, tmp_path):
    p1 = rr["pitch"][("ROW_L", "U1")][0]
    c = _collision(rr, tmp_path, {p1: 6.5})
    assert c[0]["kind"] == "RIB_PITCH_MIN" and c[0]["features"] == [p1] and "gap 0.5" in c[0]["detail"]


def test_thickness_growth_below_min_gap(rr, tmp_path):
    """Pitch 8 is above the extract lower bound (7) but rib 1 grown to 9 mm leaves 8 - (9 + 6) / 2 = 0.5 mm."""
    doc = rr["features"]
    row = rr["rows"][("ROW_L", "U1")]
    faces = {row["ribs"][0]["minus"], row["ribs"][0]["plus"]}
    rt = next(f for f in doc["features"] if f["type"] == "RIB_THICKNESS" and f["body"] == "ROW_L" and set(f["measure"]["faces"]) == faces)
    key = next((g["parameter"] for g in doc["groups"] if rt["name"] in g["members"]), rt["name"])
    p1 = rr["pitch"][("ROW_L", "U1")][0]
    assert next(f for f in doc["features"] if f["name"] == p1)["feasible"]["min"] == 7.0
    c = _collision(rr, tmp_path, {p1: 8.0, key: 9.0})
    assert c[0]["kind"] == "RIB_PITCH_MIN" and c[0]["features"] == [p1]


@pytest.mark.parametrize("sid, k, delta", [("U1", 1, 17.0), ("V1", 2, 42.0)])
def test_end_room_exceeded(rr, tmp_path, sid, k, delta):
    """U1 rib 1 through the end wall (-a side), V1 rib 3 into the pillar (+a side)."""
    name = rr["pitch"][("ROW_L", sid)][k - 1]
    nom = next(f["nominal"] for f in rr["features"]["features"] if f["name"] == name)
    room = rr["rows"][("ROW_L", sid)]["end_room_mm"]["minus" if k == 1 else "plus"]
    assert delta > room
    c = _collision(rr, tmp_path, {name: nom + delta})
    assert {x["kind"] for x in c} & {"WALL_PENETRATION", "BOUNDARY_OVERLAP"}


def test_rib_onto_hole(rr, tmp_path):
    p1 = rr["pitch"][("ROW_L", "U1")][0]
    c = _collision(rr, tmp_path, {p1: 13.0})  # rib 1 moves +5 onto the hole (clearance 4)
    assert "BOUNDARY_OVERLAP" in {x["kind"] for x in c} and "RIB_PITCH_MIN" not in {x["kind"] for x in c}


def test_rib_position_conflict_in_hand_made_file(rr, tmp_path, capsys):
    doc = copy.deepcopy(rr["features"])
    row = rr["rows"][("ROW_L", "U1")]
    rib, sig = row["ribs"][0], row["face_signatures"]
    faces = [rib["cap"], *[x for x in rib["moving"] if x != rib["cap"]], row["base"]]
    bb = next(b for b in doc["bodies"] if b["body"] == "ROW_L")["bbox"]
    nom = rib["center"] - bb[0]
    doc["features"].append(
        {
            "name": "ROW_L_RIB_U_99", "type": "RIB_POS_U", "body": "ROW_L", "nominal": nom, "unit": "mm", "range": None, "feasible": None,
            "faces": {"moving": list(rib["moving"]), "fixed": [row["base"]]}, "face_signatures": {x: sig[x] for x in faces},
            "measure": {"method": "rib_center", "faces": faces, "axis": "x"}, "group": None, "png": None,
        }
    )
    fp = write_json(tmp_path / "f.json", doc)
    code, text, _ = run_update(rr, tmp_path / "u0", {"ROW_L_RIB_U_99": nom}, fp)
    assert code == 0, text  # nominal value: no conflict
    capsys.readouterr()
    code, text, _ = run_update(rr, tmp_path / "u", {"ROW_L_RIB_U_99": nom + 1.0}, fp)
    err = capsys.readouterr().err
    assert code == 3 and "GEOM_INPUT_INVALID" in text and "RIB_PITCH_POS_CONFLICT" in err, (text, err)


def test_post_check_drift(rr, monkeypatch):
    from paicad import update as up

    doc = rr["features"]
    nominal = up.nominal_bodies(rr["step"], doc, None)
    plus = int(rr["rows"][("ROW_L", "U1")]["ribs"][0]["plus"][1:])
    orig = up.move_faces

    def drifted(body, moves):
        if body.name == "ROW_L" and plus in moves:
            mv = moves[plus]
            moves = dict(moves)
            moves[plus] = FaceMove(translate=np.asarray(mv.translate) + np.array([0.3, 0.0, 0.0]), radius=mv.radius)
        return orig(body, moves)

    monkeypatch.setattr(up, "move_faces", drifted)
    p1 = rr["pitch"][("ROW_L", "U1")][0]
    with pytest.raises(PaicadError) as e:
        up.update_core(nominal, doc, {p1: 21.0}, None, options.load(None))
    assert e.value.code == "GEOM_CAD_FAILED" and "rib row drift" in e.value.message


# ------------------------------------------------------------------ V-RG-5 morph / check
def test_morph_check_node_ids_and_quality_regions(rr, tmp_path):
    names = rr["pitch"][("ROW_L", "U2")]
    row = rr["rows"][("ROW_L", "U2")]
    vals = {names[0]: 21.0, names[3]: 16.0}
    upd, mor, chk = tmp_path / "u", tmp_path / "m", tmp_path / "c"
    code, text, vp = run_update(rr, upd, vals, None, "--tag-dir", rr["tag_dir"])
    assert code == 0, text
    truth = truth_bodies(spec_with({"U2": new_centers(base_centers("U2"), "rib:3", {1: 3.0, 4: -2.0})}), tmp_path / "t.step")
    assert_sample_matches(rr, upd, truth)
    morph = lambda out: run_cli("morph", "--baseline-inc", rr["baseline"], "--tag-dir", rr["tag_dir"], "--features", rr["features_path"], "--update-dir", upd, "--out-dir", out)  # noqa: E731
    code, text = morph(mor)
    assert code == 0, text
    base, new = (radioss.parse_text(p.read_bytes().decode("latin-1")) for p in (rr["baseline"], mor / "morphed.inc"))
    assert np.array_equal(base.node_ids, new.node_ids) and len(base.blocks) == len(new.blocks)
    for c in components_from_tag(base, load_tag(rr["tag_dir"])):
        assert truth[c.body].distance(new.xyz[c.gidx[c.kind > 0]]).max() <= BOUNDARY_TOL
        assert (tet_volumes(new.xyz[c.gidx], c.tets) > 0).all()
    code, text = run_cli(
        "check", "--baseline-inc", rr["baseline"], "--morph-dir", mor, "--update-dir", upd, "--tag-dir", rr["tag_dir"], "--features", rr["features_path"],
        "--values", vp, "--assem-dir", rr["assem"], "--renum-csv", rr["renum"], "--out-dir", chk, "--out-inc", tmp_path / "out.inc",
    )
    d = load(chk / "check.json")
    assert code == 0 and d["status"] == "PASS", d["message"]
    items = d["checks"]["param"]["items"]
    pitch_items = [it for it in items if "_RIB_PITCH_" in it["name"]]
    assert len(pitch_items) == 22 and all(it["err"] <= PARAM_ABS for it in pitch_items)
    thick = {it["name"]: it for it in items if it.get("kind") == "rib_row_thickness"}
    assert {f"ROW_L:{row['id']}:1", f"ROW_L:{row['id']}:5"} <= set(thick)
    assert all(it["status"] == "PASS" and it["input"] == 6.0 and it["err"] <= PARAM_ABS for it in thick.values())
    reg = {x["name"]: x for x in d["checks"]["quality"]["rib_rows"] if x["row"] == f"ROW_L:{row['id']}"}
    assert set(reg) == set(names) | {"end_minus", "end_plus"}
    assert reg[names[0]]["ratio"] == pytest.approx(15.0 / 12.0) and reg[names[3]]["ratio"] == pytest.approx(10.0 / 12.0, abs=1e-6)
    assert reg[names[1]]["ratio"] == pytest.approx(1.0) and reg["end_minus"]["ratio"] == pytest.approx(32.0 / 35.0, abs=1e-6)
    assert reg["end_plus"]["ratio"] == pytest.approx((9.0 + 2.0) / 9.0, abs=1e-6)
    assert all(x["elems"] > 0 and x["status"] in ("PASS", "FAIL") for x in reg.values())
    code, text = morph(tmp_path / "m2")
    assert code == 0, text
    assert (tmp_path / "m2" / "morphed.inc").read_bytes() == (mor / "morphed.inc").read_bytes()


# ------------------------------------------------------------------ V-RG-6 range / sweep
def test_joint_range_and_feasible(rr, tmp_path):
    doc = rr["features"]
    row = rr["rows"][("ROW_L", "U2")]
    assert row["end_room_mm"] == {"minus": 34.5, "plus": 8.5}
    fs = {f["name"]: f for f in doc["features"]}
    names = rr["pitch"][("ROW_L", "U2")]
    for nm in names:
        f = fs[nm]
        assert f["feasible"]["min"] == 7.0 and f["range"]["mm"] == 5.0
    # +a side: u = 8.5 / 2 pitches = 4.25 < 5 mm; -a side: 34.5 / 2 > 5 mm
    assert [fs[nm]["range"]["max"] for nm in names] == [23.0, 25.0, 24.25, 22.25]
    assert [fs[nm]["range"]["min"] for nm in names] == [13.0, 15.0, 15.0, 13.0]
    assert fs[names[2]]["feasible"]["max"] == 28.5 and fs[names[0]]["feasible"]["max"] == 18.0 + 34.5
    u3 = rr["rows"][("ROW_L", "U3")]  # even: center pitch uses both end rooms (2 x min)
    c = fs[rr["pitch"][("ROW_L", "U3")][1]]
    assert c["feasible"]["max"] == pytest.approx(18.0 + 2 * min(u3["end_room_mm"].values()))
    vals = {nm: fs[nm]["range"]["max"] for nm in names}
    code, text, _ = run_update(rr, tmp_path / "u", vals)
    assert code == 0, text  # every pitch of the row at its upper bound at once: no collision


def test_sweep_in_mm_with_row_quality(rr, tmp_path):
    name = rr["pitch"][("ROW_L", "U1")][1]
    code, text = run_cli(
        "morph", "--baseline-inc", rr["baseline"], "--tag-dir", rr["tag_dir"], "--features", rr["features_path"], "--update-dir", rr["update0"],
        "--out-dir", tmp_path / "e", "--sweep", "--params", name, "--pos-steps", "2", "--check", "on",
    )
    assert code == 0, text
    env = load(tmp_path / "e" / "envelope.json")
    assert {(r["unit"], r["step"], r["value"]) for r in env["rows"]} == {("mm", 2.0, 22.0), ("mm", 2.0, 18.0)}
    assert all(r["status"] == "OK" for r in env["rows"]) and env["summary"][0]["unit"] == "mm"
    row = rr["rows"][("ROW_L", "U1")]
    for r in env["rows"]:
        assert {x["row"] for x in r["rib_rows"]} == {f"ROW_L:{row['id']}", f"ROW_R:{rr['rows'][('ROW_R', 'U1')]['id']}"}


# ------------------------------------------------------------------ V-RG-8 view
def test_view_dimension(rr, tmp_path):
    code, text = run_cli("view", "export", "--cad", rr["step"], "--features", rr["features_path"], "--out-dir", tmp_path / "v")
    assert code == 0, text
    m = load(tmp_path / "v" / "view_manifest.json")
    row = rr["rows"][("ROW_L", "U1")]
    for k, name in enumerate(rr["pitch"][("ROW_L", "U1")], 1):
        f = next(x for x in m["features"] if x["name"] == name)
        d = f["dimension"]
        feat = next(x for x in rr["features"]["features"] if x["name"] == name)
        assert d["kind"] == "linear" and d["value"] == feat["nominal"] and d["geom_len"] == pytest.approx(feat["nominal"], abs=1e-6)
        assert d["p0"][0] == pytest.approx(row["ribs"][k - 1]["center"]) and d["p1"][0] == pytest.approx(row["ribs"][k]["center"])
        assert d["p0"][1] == pytest.approx(27.0) and d["p0"][2] == pytest.approx(13.0)  # rib length / height middle
        assert f["faces"]["moving"] == feat["faces"]["moving"] and f["row"] == feat["row"]
    # feature PNG uses the same two points
    from paicad import render

    feat = next(x for x in rr["features"]["features"] if x["name"] == rr["pitch"][("ROW_L", "U1")][0])
    p0, p1 = render.dimension_points(feat)
    assert float(np.linalg.norm(np.asarray(p1) - np.asarray(p0))) == pytest.approx(feat["nominal"], abs=1e-6)
