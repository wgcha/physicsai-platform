"""extract-filter.md (paicad part): ``extract.filter`` options, early exclusion, EF-INV subset invariant, tie order,
``extract_stats.json``, RIB_POS recognition (V-EF-1, -2, -3, -5, -6, -9, -10).

R_all = the same extract with ``filter.types`` = all 11 types and no condition. Filter results must be exactly the
R_all features of the selected types meeting the conditions (comparison keys of section 5.1).
"""

from __future__ import annotations

import json
import math
import random
from pathlib import Path

import numpy as np
import pytest
from conftest import run_cli
from paicad import features, options
from paicad.common import EXIT_EXTRACT_EMPTY, EXIT_INPUT, PaicadError
from paicad.kernel.base import BodySummary, FaceData, Topology

ALL_TYPES = list(features.TYPE_ORDER)
PAIR = ("THICKNESS", "RIB_THICKNESS", "POCKET_WIDTH")
HEIGHT = ("RIB_HEIGHT", "POCKET_DEPTH")


def load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def write_opts(path: Path, flt, **extract) -> Path:
    ex = dict(extract)
    if flt is not ...:
        ex["filter"] = flt
    path.write_text(json.dumps({"schema_version": 1, "extract": ex}), encoding="utf-8")
    return path


def extract(cad, out: Path, flt=..., *extra, png=False, expect=0) -> dict:
    args = ["extract", "--cad", cad, "--out-dir", out, *([] if png else ["--no-png"]), *extra]
    if flt is not ...:
        args += ["--options", write_opts(out.parent / f"{out.name}_opts.json", flt)]
    code, text = run_cli(*args)
    assert code == expect, text
    return load(out / "parameter_features.json")


# ------------------------------------------------------------- comparison helpers (section 5.1)
def key(f: dict) -> str:
    """Comparison key of a feature: everything but name, group, png and feasible.limited_by."""
    d = {k: v for k, v in f.items() if k not in ("name", "group", "png", "feasible")}
    d["feasible"] = {"min": f["feasible"]["min"], "max": f["feasible"]["max"]}
    return json.dumps(d, sort_keys=True)


def _within(x, r) -> bool:
    if not r:
        return True
    lo, hi = r.get("min"), r.get("max")
    return (lo is None or x >= lo - 1e-9) and (hi is None or x <= hi + 1e-9)


def keeps(f: dict, flt: dict) -> bool:
    """Section 4.2 conditions evaluated on an R_all feature (test thresholds stay clear of rounding)."""
    t = f["type"]
    if t not in flt["types"]:
        return False
    sig = f["face_signatures"]
    mf = [sig[x] for x in f["measure"]["faces"]]
    v = f["nominal"]
    if t in PAIR:
        a = flt.get("face_area_min_mm2")
        return _within(v, flt.get("thickness_mm")) and (a is None or all(s["area"] >= a for s in mf))
    if t in HEIGHT:
        return _within(v, flt.get("height_mm"))
    pmin = flt.get("position_min_size_mm")
    if t in ("HOLE_POS_U", "HOLE_POS_V"):
        return pmin is None or 2 * mf[0]["radius"] >= pmin
    if t in ("RIB_POS_U", "RIB_POS_V"):
        k = int(np.argmax(np.abs(mf[-1]["normal"])))
        bb = np.asarray(mf[0]["bbox"])
        ext = [bb[3 + a] - bb[a] for a in range(3) if a != k]
        return pmin is None or min(ext) >= pmin
    if t == "HOLE_RADIUS":
        return flt.get("hole_radius_min_mm") is None or v >= flt["hole_radius_min_mm"]
    if t == "FILLET_RADIUS":
        return flt.get("fillet_radius_min_mm") is None or v >= flt["fillet_radius_min_mm"]
    raise AssertionError(t)


def group_sets(doc: dict) -> set[frozenset]:
    return {frozenset(g["members"]) for g in doc["groups"]}


def assert_subset_of_rall(doc: dict, rall: dict, flt: dict):
    want = sorted(key(f) for f in rall["features"] if keeps(f, flt))
    got = sorted(key(f) for f in doc["features"])
    assert got == want
    # names renumbered among the kept features, per body and type, in R_all order
    for b in {f["body"] for f in doc["features"]}:
        for t in ALL_TYPES:
            names = [f["name"] for f in doc["features"] if f["body"] == b and f["type"] == t]
            assert [int(n.rsplit("_", 1)[1]) for n in names] == list(range(1, len(names) + 1))
    # every group is (a subset of) an R_all group of kept features
    by_key = {key(f): f["name"] for f in rall["features"]}
    name_map = {f["name"]: by_key[key(f)] for f in doc["features"]}
    rgroups = group_sets(rall)
    for g in doc["groups"]:
        assert len(g["members"]) >= 2
        assert any({name_map[m] for m in g["members"]} <= rg for rg in rgroups), g
    assert doc["filter"] == dict(flt, draft_max_deg=3.0)


def assert_rall_matches_nofilter(rall: dict, plain: dict):
    """R_all without RIB_POS == no-filter output (except limited_by pointing at RIB_POS, group ids, filter key)."""
    rib_pos = {f["name"] for f in rall["features"] if f["type"] in features.RIB_POS_TYPES}
    rest = [f for f in rall["features"] if f["name"] not in rib_pos]
    assert len(rest) == len(plain["features"])
    gm_r = {g["id"]: frozenset(g["members"]) for g in rall["groups"]}
    gm_p = {g["id"]: frozenset(g["members"]) for g in plain["groups"]}
    for a, b in zip(rest, plain["features"]):
        a, b = dict(a), dict(b)
        if a["feasible"]["limited_by"] in rib_pos:
            a["feasible"] = dict(a["feasible"], limited_by=b["feasible"]["limited_by"])
        ga, gb = a.pop("group"), b.pop("group")
        assert (ga is None) == (gb is None) and (ga is None or gm_r[ga] == gm_p[gb]), (a["name"], ga, gb)
        assert a == b
    assert {g for g in group_sets(rall) if not g & rib_pos} == group_sets(plain)
    assert "filter" not in plain and rall["filter"]["types"] == ALL_TYPES
    for k in ("bodies", "warnings", "cad"):
        assert rall[k] == plain[k]


# ------------------------------------------------------------- V-EF-6 options validation
@pytest.mark.parametrize(
    "flt, msg",
    [
        ({"types": []}, "non-empty list"),
        ({"types": ["THICKNESS", "THICKNESS"]}, "duplicates"),
        ({"types": ["BOSS"]}, "unknown feature types: BOSS"),
        ({"types": ["THICKNESS"], "thickness": 2}, "extract.filter.thickness"),
        ({"types": ["THICKNESS"], "thickness_mm": {"min": 2, "mx": 3}}, "extract.filter.thickness_mm.mx"),
        ({"types": ["THICKNESS"], "thickness_mm": {"min": 5, "max": 3}}, "min > max"),
        ({"types": ["THICKNESS"], "thickness_mm": {"min": -1}}, "thickness_mm.min"),
        ({"types": ["THICKNESS"], "height_mm": {"max": 0}}, "height_mm.max"),
        ({"types": ["THICKNESS"], "face_area_min_mm2": -5}, "face_area_min_mm2"),
        ({"types": ["THICKNESS"], "fillet_radius_min_mm": 0}, "fillet_radius_min_mm"),
        ({"types": ["THICKNESS"], "hole_radius_min_mm": float("inf")}, "hole_radius_min_mm"),
        ({"types": ["THICKNESS"], "position_min_size_mm": True}, "position_min_size_mm"),
        ("THICKNESS", "must be an object"),
    ],
)
def test_filter_validation_errors(tmp_path, flt, msg):
    p = tmp_path / "o.json"
    p.write_text(json.dumps({"schema_version": 1, "extract": {"filter": flt}}), encoding="utf-8")
    with pytest.raises(PaicadError) as e:
        options.load(p, keep_filter=True)
    assert e.value.code == "GEOM_INPUT_INVALID" and msg in e.value.message
    with pytest.raises(PaicadError):  # every command validates it
        options.load(p)


def test_filter_valid_forms(tmp_path):
    p = write_opts(tmp_path / "a.json", {"types": ["THICKNESS"], "thickness_mm": {"min": 0, "max": None}, "height_mm": None, "face_area_min_mm2": None})
    o = options.load(p, keep_filter=True)
    assert o["extract"]["filter"]["thickness_mm"] == {"min": 0, "max": None}
    assert "filter" not in options.load(p)["extract"]  # update/morph/check/tag: validated, then ignored
    assert options.load(p)["extract"] == options.load(None)["extract"]
    o = options.load(write_opts(tmp_path / "b.json", None), keep_filter=True)  # null = no filter
    assert "filter" not in o["extract"]
    assert "filter" not in options.DEFAULTS["extract"]


def test_filter_type_vocabulary_single_source():
    from paicad import paramap
    from paicad.view import manifest

    assert options.FILTER_TYPES == features.TYPE_ORDER
    assert features.TYPE_ORDER[-2:] == ("RIB_POS_U", "RIB_POS_V") and features.TYPE_ORDER[:9] == features.LEGACY_TYPES
    assert manifest.POSITION_TYPES is features.POSITION_TYPES
    assert set(features.POSITION_TYPES) == {"HOLE_POS_U", "HOLE_POS_V", "RIB_POS_U", "RIB_POS_V"}
    assert all(paramap.TYPE_KIND[t] == "position" for t in features.POSITION_TYPES)
    assert features.TYPE_ABBR["RIB_POS_U"] == "RIB_U" and features.MEASURE["RIB_POS_V"] == "rib_center"
    from paicad import update

    assert update.OP["RIB_POS_U"] == update.OP["RIB_POS_V"] == "AXIS_SHIFT"


def test_cli_rejects_bad_filter(golden, tmp_path):
    code, text = run_cli(
        "extract", "--cad", golden["step"], "--out-dir", tmp_path / "e", "--no-png", "--options", write_opts(tmp_path / "o.json", {"types": ["THK"]})
    )
    assert code == EXIT_INPUT and "GEOM_INPUT_INVALID" in text, text


# ------------------------------------------------------------- V-EF-1 / V-EF-2 on the virtual cushion
@pytest.fixture(scope="module")
def cushion(golden, tmp_path_factory):
    root = tmp_path_factory.mktemp("ef_cushion")
    rall = extract(golden["step"], root / "rall", {"types": ALL_TYPES}, "--renum-csv", golden["renum"], png=True)
    return {"root": root, "rall": rall, "rall_dir": root / "rall"}


def test_no_filter_is_unchanged_and_writes_stats(golden):
    """V-EF-1: the session golden (no options) has no RIB_POS / filter key; byte equality with the 0.10.1 algorithms is
    test_extract_perf.test_golden_extract_matches_reference. extract_stats.json is always written."""
    d = golden["features"]
    assert "filter" not in d and not [f for f in d["features"] if f["type"] in features.RIB_POS_TYPES]
    s = load(golden["extract_dir"] / "extract_stats.json")
    assert s["schema_version"] == 1 and s["engine"] == "native" and s["filter_applied"] is False
    assert [b["body"] for b in s["bodies"]] == ["CUSH_L", "CUSH_R"]
    b = s["bodies"][0]
    assert b["types"]["RIB_POS_U"] == {"selected": False} and b["types"]["THICKNESS"]["selected"] is True
    kept = {t: sum(1 for f in d["features"] if f["body"] == "CUSH_L" and f["type"] == t) for t in features.LEGACY_TYPES}
    assert {t: b["types"][t]["kept"] for t in features.LEGACY_TYPES} == kept
    assert s["png"]["rendered"] == len(d["features"]) and set(s["elapsed_s"]) == {"load", "recognize", "finalize", "png", "total"}
    assert b["faces"] == 23 and b["planes"] == 21 and sum(b["rib_rejects"].values()) == b["planes"] - 2  # 2 ribs recognized


def test_rall_matches_no_filter(cushion, golden):
    assert_rall_matches_nofilter(cushion["rall"], golden["features"])
    # RIB_POS: 2 ribs x (U, V) per body, V mirrored in one group, U ungrouped (positions differ from the bbox minimum)
    rp = [f for f in cushion["rall"]["features"] if f["type"] in features.RIB_POS_TYPES]
    assert sorted((f["name"], f["nominal"]) for f in rp if f["body"] == "CUSH_L") == [
        ("CUSH_L_RIB_U_1", 28.0), ("CUSH_L_RIB_U_2", 92.0), ("CUSH_L_RIB_V_1", 40.0), ("CUSH_L_RIB_V_2", 40.0)
    ]
    assert {f["group"] is None for f in rp if f["type"] == "RIB_POS_U"} == {True}
    assert len({f["group"] for f in rp if f["type"] == "RIB_POS_V"}) == 1
    u1 = next(f for f in rp if f["name"] == "CUSH_L_RIB_U_1")
    assert u1["range"] == {"min": 23.0, "max": 33.0, "mm": 5.0} and u1["measure"]["method"] == "rib_center" and u1["measure"]["axis"] == "x"
    assert u1["feasible"]["min"] == 3.5 and u1["feasible"]["max"] == 85.5  # base bbox edge (-x) / other rib side (+x) - 0.5 mm
    assert len(u1["faces"]["moving"]) == 5 and len(u1["faces"]["fixed"]) == 1 and u1["ref"]["rule"] == "feature_default"
    pngs = sorted(p.name for p in (cushion["rall_dir"] / "features").iterdir())
    assert pngs == sorted(f"{f['name']}.png" for f in cushion["rall"]["features"])


GROUP_TYPES = {
    "thickness": ["THICKNESS", "RIB_THICKNESS", "POCKET_WIDTH"],
    "height": ["RIB_HEIGHT", "POCKET_DEPTH"],
    "position": ["HOLE_POS_U", "HOLE_POS_V", "RIB_POS_U", "RIB_POS_V"],
    "hole_radius": ["HOLE_RADIUS"],
    "fillet": ["FILLET_RADIUS"],
}
CUSHION_FILTERS = {
    **{f"group_{g}": {"types": t} for g, t in GROUP_TYPES.items()},
    "cond_thickness": {"types": ALL_TYPES, "thickness_mm": {"min": 10.0, "max": 50.0}},
    "cond_area": {"types": ALL_TYPES, "face_area_min_mm2": 1000.0},
    "cond_height": {"types": ALL_TYPES, "height_mm": {"max": 10.0}},
    "cond_position": {"types": ALL_TYPES, "position_min_size_mm": 6.5},
    "cond_hole_r": {"types": ALL_TYPES, "hole_radius_min_mm": 6.0},
    "cond_fillet": {"types": ALL_TYPES, "fillet_radius_min_mm": 2.0},
    "combo_contract": {
        "types": ["THICKNESS", "RIB_THICKNESS", "POCKET_WIDTH", "HOLE_POS_U", "HOLE_POS_V", "RIB_POS_U", "RIB_POS_V", "FILLET_RADIUS"],
        "thickness_mm": {"min": 2.0, "max": 30.0}, "face_area_min_mm2": 50.0, "position_min_size_mm": 3.0, "fillet_radius_min_mm": 1.0,
    },
    "combo_min_only": {"types": ["THICKNESS", "POCKET_WIDTH", "RIB_HEIGHT"], "thickness_mm": {"min": 25.0}, "height_mm": {"min": 9.0, "max": 20.0}},
    "combo_pos_rib": {"types": ["RIB_POS_V", "RIB_THICKNESS", "HOLE_RADIUS"], "position_min_size_mm": 5.0, "thickness_mm": {"max": 6.5}, "hole_radius_min_mm": 4.0},
}


@pytest.mark.parametrize("case", sorted(CUSHION_FILTERS))
def test_filter_is_subset_of_rall_cushion(cushion, golden, case):
    flt = CUSHION_FILTERS[case]
    doc = extract(golden["step"], cushion["root"] / case, flt, "--renum-csv", golden["renum"])
    assert doc["features"], case
    assert_subset_of_rall(doc, cushion["rall"], flt)


def test_filter_excluding_everything_is_extract_empty(golden, tmp_path):
    doc = extract(golden["step"], tmp_path / "e", {"types": ["HOLE_RADIUS"], "hole_radius_min_mm": 50.0}, expect=EXIT_EXTRACT_EMPTY)
    assert doc["features"] == [] and doc["filter"]["hole_radius_min_mm"] == 50.0
    s = load(tmp_path / "e" / "extract_stats.json")
    assert s["filter_applied"] is True and s["bodies"][0]["types"]["HOLE_RADIUS"] == {
        "selected": True, "candidates": 1, "kept": 0, "excluded": {"hole_radius_min": 1}, "elapsed_s": s["bodies"][0]["types"]["HOLE_RADIUS"]["elapsed_s"]
    }
    assert not (tmp_path / "e" / "parameter_extracted.xml").exists()


def _strip_elapsed(x):
    if isinstance(x, dict):
        return {k: _strip_elapsed(v) for k, v in x.items() if k != "elapsed_s"}
    if isinstance(x, list):
        return [_strip_elapsed(v) for v in x]
    return x


def test_filter_output_deterministic(golden, tmp_path):
    flt = CUSHION_FILTERS["combo_contract"]
    outs = []
    for k in (1, 2):
        extract(golden["step"], tmp_path / f"e{k}", flt, png=True)
        d = tmp_path / f"e{k}"
        files = {p.relative_to(d).as_posix(): p.read_bytes() for p in sorted(d.rglob("*")) if p.is_file() and p.name not in ("paicad.log", "extract_stats.json") and "_opts" not in p.name}
        outs.append((files, _strip_elapsed(load(d / "extract_stats.json"))))
    assert outs[0] == outs[1] and any(n.endswith(".png") for n in outs[0][0])


# ------------------------------------------------------------- V-EF-3 early exclusion (kernel call counts)
@pytest.fixture
def overlap_calls(monkeypatch):
    calls = []
    orig = features._overlap_ok

    def wrapped(ctx, a, b, check_material):
        calls.append((ctx.body.name, a, b, check_material))
        return orig(ctx, a, b, check_material)

    monkeypatch.setattr(features, "_overlap_ok", wrapped)
    return calls


def test_unselected_pair_types_make_no_overlap_test(golden, tmp_path, overlap_calls):
    extract(golden["step"], tmp_path / "e", {"types": ["RIB_HEIGHT", "POCKET_DEPTH", "HOLE_RADIUS", "HOLE_POS_U", "HOLE_POS_V", "FILLET_RADIUS", "RIB_POS_U", "RIB_POS_V"]})
    assert overlap_calls == []
    s = load(tmp_path / "e" / "extract_stats.json")
    assert all(s["bodies"][0]["types"][t] == {"selected": False} for t in PAIR)
    overlap_calls.clear()
    extract(golden["step"], tmp_path / "e2", {"types": ["THICKNESS"]})
    s2 = load(tmp_path / "e2" / "extract_stats.json")["bodies"][0]["types"]
    assert len(overlap_calls) == sum(b["types"]["THICKNESS"]["pair_tests"] for b in load(tmp_path / "e2" / "extract_stats.json")["bodies"]) > 0
    assert s2["RIB_THICKNESS"] == {"selected": False} and s2["THICKNESS"]["kept"] == 3


def test_area_and_max_conditions_cut_before_overlap(golden, tmp_path, overlap_calls):
    """face_area_min: smaller planes are not initiators; thickness max: no overlap test for d > max."""
    flt = {"types": ["THICKNESS", "RIB_THICKNESS", "POCKET_WIDTH"], "thickness_mm": {"max": 30.0}, "face_area_min_mm2": 1000.0}
    doc = extract(golden["step"], tmp_path / "e", flt)
    for _, a, b, _ in overlap_calls:
        assert features._plane_distance(a, b) <= 30.0 + 1e-9
    s = load(tmp_path / "e" / "extract_stats.json")["bodies"][0]["types"]["THICKNESS"]
    # CUSH_L free planes (not rib / pocket faces): 6, the 4 side walls and the top / bottom faces; all >= 1000 mm2
    assert s["initiators"] == 6 and s["kept"] == 1 and doc["features"][0]["nominal"] == 20.0
    flt2 = dict(flt, face_area_min_mm2=2000.0)  # only the 120 x 20 walls and top / bottom remain initiators
    extract(golden["step"], tmp_path / "e2", flt2)
    s2 = load(tmp_path / "e2" / "extract_stats.json")["bodies"][0]["types"]["THICKNESS"]
    assert s2["initiators"] == 4 and s2["excluded"]["face_area"] == 2


def test_png_and_triangulation_only_for_kept_features(tmp_path, monkeypatch):
    from build123d import Align, Box, Cylinder, Pos
    from data.make_synthetic import write_step
    from paicad.kernel import occ

    plate = Box(60, 40, 10) - Cylinder(5, 10)
    step = tmp_path / "two.step"
    write_step(step, [("PLATE", plate.solids()[0]), ("BOX", (Pos(100, 0, 0) * Box(10, 20, 30, align=(Align.MIN,) * 3)).solids()[0])])
    tri = []
    orig = occ.OccBody.triangulate

    def counted(self, *a, **k):
        tri.append(self.name)
        return orig(self, *a, **k)

    monkeypatch.setattr(occ.OccBody, "triangulate", counted)
    doc = extract(step, tmp_path / "e", {"types": ["HOLE_RADIUS"]}, png=True)
    assert [(f["body"], f["type"]) for f in doc["features"]] == [("PLATE", "HOLE_RADIUS")]
    assert sorted(p.name for p in (tmp_path / "e" / "features").iterdir()) == ["PLATE_HOLE_R_1.png"]
    assert tri == ["PLATE"]  # the box body (no kept feature) is never triangulated
    s = load(tmp_path / "e" / "extract_stats.json")
    assert s["png"]["rendered"] == 1 and s["bodies"][1]["types"]["HOLE_RADIUS"]["candidates"] == 0


# ------------------------------------------------------------- V-EF-2 / V-EF-5 on the load-test cushion
@pytest.fixture(scope="module")
def heavy(tmp_path_factory):
    from data.make_heavy import HeavySpec, write

    root = tmp_path_factory.mktemp("ef_heavy")
    step = write(root / "heavy.step", HeavySpec(nx=4, ny=3))
    plain = extract(step, root / "plain")
    rall = extract(step, root / "rall", {"types": ALL_TYPES})
    return {"root": root, "step": step, "plain": plain, "rall": rall}


def test_heavy_rall_matches_no_filter(heavy):
    assert_rall_matches_nofilter(heavy["rall"], heavy["plain"])
    s = load(heavy["root"] / "rall" / "extract_stats.json")["bodies"][0]
    assert s["types"]["RIB_POS_U"]["kept"] == 2 and s["rib_rejects"]["lateral_not_plane"] == 2  # filleted ribs are not ribs


HEAVY_FILTERS = {
    "contract": CUSHION_FILTERS["combo_contract"],
    "area_thk": {"types": ["THICKNESS"], "thickness_mm": {"min": 5.0, "max": 45.0}, "face_area_min_mm2": 400.0},
    "pos_fillet": {"types": ["HOLE_POS_U", "RIB_POS_V", "FILLET_RADIUS", "POCKET_DEPTH"], "position_min_size_mm": 5.0, "fillet_radius_min_mm": 1.5, "height_mm": {"max": 11.0}},
    "thk_max_only": {"types": ["THICKNESS", "RIB_THICKNESS", "POCKET_WIDTH"], "thickness_mm": {"max": 12.0}},
}


@pytest.mark.parametrize("case", sorted(HEAVY_FILTERS))
def test_filter_is_subset_of_rall_heavy(heavy, case):
    flt = HEAVY_FILTERS[case]
    doc = extract(heavy["step"], heavy["root"] / case, flt)
    assert_subset_of_rall(doc, heavy["rall"], flt)


def test_heavy_filter_halves_thickness_pair_tests(heavy):
    """V-EF-5: face_area_min + thickness range -> thickness pair tests <= 50 % of the unfiltered run; THICKNESS
    unselected -> 0 (judged on call counts, times are recorded only)."""
    base = load(heavy["root"] / "plain" / "extract_stats.json")["bodies"][0]["types"]["THICKNESS"]
    extract(heavy["step"], heavy["root"] / "speed", HEAVY_FILTERS["contract"])
    f = load(heavy["root"] / "speed" / "extract_stats.json")["bodies"][0]["types"]["THICKNESS"]
    assert base["pair_tests"] >= 20 and f["pair_tests"] <= 0.5 * base["pair_tests"], (base, f)
    extract(heavy["step"], heavy["root"] / "nothk", {"types": ["HOLE_POS_U", "RIB_POS_U"]})
    n = load(heavy["root"] / "nothk" / "extract_stats.json")["bodies"][0]["types"]
    assert n["THICKNESS"] == {"selected": False}


# ------------------------------------------------------------- tie order (synthetic planes, fake kernel)
class FakePlanes:
    """Axis-aligned rectangles normal to z (no edges -> no ribs / pockets) + material boxes (BodyGeom subset)."""

    def __init__(self, name, rects, boxes):
        self.name = name
        self.boxes = [(np.asarray(lo, float), np.asarray(hi, float)) for lo, hi in boxes]
        faces = []
        self._r = []
        for k, (z, s, x0, x1, y0, y1) in enumerate(rects, 1):
            bb = np.array([x0, y0, z, x1, y1, z], float)
            faces.append(
                FaceData(
                    id=k, surface="PLANE", area=(x1 - x0) * (y1 - y0), centroid=np.array([(x0 + x1) / 2, (y0 + y1) / 2, z]), bbox=bb,
                    edges=(), outer_edges=(), inner_wires=(), uv_bounds=(0.0, 1.0, 0.0, 1.0), normal=np.array([0.0, 0.0, float(s)]),
                )
            )
            self._r.append(bb)
        self._topo = Topology(faces=tuple(faces), edges=(), vertices=np.zeros((0, 3)))
        allb = np.array(self._r)
        self._bbox = np.concatenate([allb[:, :3].min(0), allb[:, 3:].max(0)])

    def summary(self):
        return BodySummary(self.name, 1.0, self._bbox, len(self._r), 0, 0)

    def topology(self):
        return self._topo

    def sample_face(self, fid, n):
        bb = self._r[fid - 1]
        g = (np.arange(n) + 0.5) / n
        return np.array([[bb[0] + a * (bb[3] - bb[0]), bb[1] + b * (bb[4] - bb[1]), bb[2]] for a in g for b in g])

    def project_to_face(self, fid, pts):
        bb = self._r[fid - 1]
        pts = np.asarray(pts, float).reshape(-1, 3)
        foot = pts.copy()
        foot[:, 2] = bb[2]
        ins = (foot[:, 0] >= bb[0] - 1e-9) & (foot[:, 0] <= bb[3] + 1e-9) & (foot[:, 1] >= bb[1] - 1e-9) & (foot[:, 1] <= bb[4] + 1e-9)
        return np.abs(pts[:, 2] - bb[2]), foot[:, :2], ins, foot

    def points_inside(self, pts):
        pts = np.asarray(pts, float).reshape(-1, 3)
        out = np.zeros(len(pts), bool)
        for lo, hi in self.boxes:
            out |= np.all((pts > lo) & (pts < hi), axis=1)
        return out


def _thk_pairs(body, flt):
    o = options.load(None)
    if flt is not None:
        o["extract"]["filter"] = flt
    return sorted((f.pair, f.nominal) for f in features.recognize_body(body, o) if f.type == "THICKNESS")


@pytest.mark.parametrize("noise", [0.0, 1e-12, -1e-12])
def test_tie_keeps_enumeration_order(noise):
    """Top face T with two coplanar bottom faces each covering exactly half of it (overlap 0.5 = overlap_min):
    the full scan keeps the first partner in enumeration order (B2, index 0) even when B1 is nearer by 1e-12 -
    the filtered (nearest-first) search must give the same pair."""
    rects = [(0.0, -1, 51, 100, 0, 10), (10.0, 1, 0, 100, 0, 10), (noise, -1, 0, 49, 0, 10)]  # B2, T, B1
    body = FakePlanes("TIE", rects, [((0, 0, -1), (100, 10, 10))])
    legacy = _thk_pairs(body, None)
    assert [p for p, _ in legacy] == [(1, 2)]  # (B2, T)
    assert _thk_pairs(body, {"types": ["THICKNESS"]}) == legacy
    assert _thk_pairs(body, {"types": ["THICKNESS"], "thickness_mm": {"max": 10.0}, "face_area_min_mm2": 400.0}) == legacy
    assert _thk_pairs(body, {"types": ["THICKNESS"], "thickness_mm": {"max": 9.0}}) == []


def test_lazy_thickness_equals_full_scan_random():
    """Random stacks of z-facing rectangles on a coarse grid (many exact and 1e-12 ties, partial overlaps):
    the filtered search returns exactly the full-scan mutual pairs, and conditions return the R_all subset."""
    rng = random.Random(20261021)
    for trial in range(60):
        rects, boxes = [], []
        for _ in range(rng.randint(6, 16)):
            x0 = rng.randint(0, 8) * 10.0
            y0 = rng.randint(0, 3) * 10.0
            w, h = rng.choice([10.0, 20.0, 40.0]), rng.choice([10.0, 20.0])
            z = rng.randint(0, 6) * 5.0 + rng.choice([0.0, 0.0, 1e-12, -1e-12])
            rects.append((z, rng.choice([-1, 1]), x0, x0 + w, y0, y0 + h))
        for _ in range(rng.randint(1, 4)):
            lo = (rng.randint(0, 6) * 10.0, rng.randint(0, 2) * 10.0, rng.randint(0, 3) * 5.0)
            boxes.append((lo, (lo[0] + rng.randint(2, 6) * 10.0, lo[1] + rng.randint(1, 3) * 10.0, lo[2] + rng.randint(1, 4) * 5.0)))
        body = FakePlanes(f"R{trial}", rects, boxes)
        legacy = _thk_pairs(body, None)
        assert _thk_pairs(body, {"types": ALL_TYPES}) == legacy, trial
        area = {f.id: f.area for f in body.topology().faces}
        flt = {"types": ["THICKNESS"], "thickness_mm": {"min": 4.0, "max": 16.0}, "face_area_min_mm2": 300.0}
        want = [(p, d) for p, d in legacy if 4.0 <= d <= 16.0 and area[p[0]] >= 300.0 and area[p[1]] >= 300.0]
        assert _thk_pairs(body, flt) == want, trial


# ------------------------------------------------------------- RIB_POS recognition rules
def test_rib_pos_side_split_in_two_has_no_axis(tmp_path):
    """Rib whose +x side is two faces (bent by 0.6 deg, both within the draft angle): no RIB_POS_U for it (stats
    reason shape), RIB_POS_V still made; the straight rib gets both."""
    from build123d import Align, Box, Polygon, Pos, export_step, extrude

    mn = (Align.MIN, Align.MIN, Align.MIN)
    plate = Box(100, 80, 10, align=mn)
    bent = extrude(Polygon((20, 20), (26, 20), (26.2, 40), (26, 60), (20, 60), align=None), amount=12)
    straight = Pos(70, 20, 10) * Box(6, 40, 12, align=mn)
    solid = (plate + Pos(0, 0, 10) * bent + straight).solids()[0]
    step = tmp_path / "bent.step"
    export_step(solid, str(step))
    doc = extract(step, tmp_path / "e", {"types": ["RIB_POS_U", "RIB_POS_V", "RIB_HEIGHT"]})
    assert sum(1 for f in doc["features"] if f["type"] == "RIB_HEIGHT") == 2
    rp = sorted((f["type"], round(f["nominal"], 3)) for f in doc["features"] if f["type"] in features.RIB_POS_TYPES)
    assert rp == [("RIB_POS_U", 73.0), ("RIB_POS_V", 40.0), ("RIB_POS_V", 40.0)]
    st = load(tmp_path / "e" / "extract_stats.json")["bodies"][0]["types"]
    assert st["RIB_POS_U"]["excluded"] == {"shape": 1} and st["RIB_POS_U"]["kept"] == 1 and st["RIB_POS_V"]["kept"] == 2


def test_rib_pos_dimension_line_and_selftest_counters(cushion, golden):
    from paicad import render

    f = next(x for x in cushion["rall"]["features"] if x["name"] == "CUSH_L_RIB_U_1")
    bb = next(b["bbox"] for b in cushion["rall"]["bodies"] if b["body"] == "CUSH_L")
    p1, p0 = render.dimension_points(f, bb)
    assert p0[0] == pytest.approx(bb[0]) and p1[0] - p0[0] == pytest.approx(28.0)
    assert render.dimension_points(f) is None  # no bbox: no line (PNG still rendered)
    assert math.isclose(p1[1], 40.0 + bb[1], abs_tol=1e-6)
