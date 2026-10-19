"""paicad 0.6.0: stage 3S shell thickness (``props scan/apply``), stage 4B ``paicad map``, feature
highlight PNGs, selftest ``--nx-samples``, narrow inc fields, non-finite quality values excluded."""

from __future__ import annotations

import json
import math
import struct
from collections import Counter
from pathlib import Path

import numpy as np
import pytest
from conftest import run_cli
from paicad import options, paramap, quality
from paicad.common import EXIT_CHECK, EXIT_INPUT, PaicadError
from paicad.mesh import radioss


def load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def write_json(p: Path, obj) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj), encoding="utf-8")
    return p


# ============================================================= 1. stage 3S shell thickness
@pytest.fixture()
def shell(tmp_path):
    from data.make_synthetic import write_shell_assembly

    s = write_shell_assembly(tmp_path / "assem_shell")
    code, text = run_cli("props", "scan", "--assem-dir", s["folder"], "--out-dir", tmp_path / "scan")
    assert code == 0 and text.strip().splitlines()[-1] == "PAICAD RESULT OK - props.json", text
    s["props_json"] = tmp_path / "scan" / "props.json"
    s["props"] = load(s["props_json"])
    s["tmp"] = tmp_path
    return s


def _snapshot(folder: Path) -> dict[str, bytes]:
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in sorted(folder.rglob("*")) if p.is_file()}


def test_props_scan_lists_cases(shell):
    d = shell["props"]
    assert d["schema_version"] == 1 and d["engine"] == "native" and d["status"] == "OK"
    rows = {r["id"]: r for r in d["props"]}
    assert sorted(rows) == [1, 2, 3, 4, 5, 6]
    assert rows[1]["parameter"] == "BRACKET_SHELL_T" and rows[1]["thickness"] == 1.2 and rows[1]["file"] == "props/shell_props.inc"
    assert rows[1]["parts"] == [{"id": 10, "title": "BRACKET"}] and rows[1]["selectable"] and rows[1]["range"] == {"min": 1.14, "max": 1.26, "ratio": 0.05}
    assert rows[2]["type"] == "SHELL" and rows[2]["keyword"] == "/PROP/SHELL" and [p["id"] for p in rows[2]["parts"]] == [11, 12]
    # same title "Cover" on PROP 2 and 6 -> PROP id appended; untitled PROP 5 -> PROP5_SHELL_T
    assert rows[2]["parameter"] == "COVER_2_SHELL_T" and rows[6]["parameter"] == "COVER_6_SHELL_T" and rows[5]["parameter"] == "PROP5_SHELL_T"
    assert rows[3]["element_overrides"] == 2 and not rows[3]["selectable"]
    assert rows[4]["type"] == "SH_ORTH" and rows[4]["supported"] is False and rows[4]["parameter"] is None and not rows[4]["selectable"]
    assert rows[5]["thickness"] == 0.0 and not rows[5]["selectable"]
    assert rows[6]["thickness"] == 1.5 and rows[6]["element_overrides"] == 0  # SH3N elements with thickness 0
    codes = sorted((w["code"], w["prop"]) for w in d["warnings"])
    assert codes == [("PROP_OVERRIDDEN_BY_ELEMENT", 3), ("PROP_SHARED_BY_PARTS", 2), ("PROP_THICKNESS_INVALID", 5), ("PROP_UNSUPPORTED_TYPE", 4)]
    shared = next(w for w in d["warnings"] if w["code"] == "PROP_SHARED_BY_PARTS")
    assert shared["parts"] == [11, 12]
    assert all(paramap.NAME_RE.match(r["parameter"]) for r in d["props"] if r["parameter"])


def _apply(shell, values: dict, out: str):
    vp = write_json(shell["tmp"] / f"{out}_values.json", {"schema_version": 1, "values": values})
    code, text = run_cli("props", "apply", "--assem-dir", shell["folder"], "--values", vp, "--props", shell["props_json"], "--out-dir", shell["tmp"] / out)
    rep = shell["tmp"] / out / "props_apply.json"
    return code, text, (load(rep) if rep.is_file() else None)


def test_props_apply_changes_only_thickness_field(shell):
    before = _snapshot(shell["folder"])
    code, text, d = _apply(shell, {"BRACKET_SHELL_T": 1.32, "COVER_6_SHELL_T": 1.25}, "a1")
    assert code == 0 and d["status"] == "OK", text
    assert _snapshot(shell["folder"]) == before  # the assembly folder is never written
    out = shell["tmp"] / "a1"
    assert sorted(f["rel"] for f in d["files"]) == ["SHELL_0000.rad", "props/shell_props.inc"]
    # fixed-width card (CRLF file in a subfolder): only columns 21-40 of the thickness line differ
    old = before["props/shell_props.inc"].split(b"\r\n")
    new = (out / "props" / "shell_props.inc").read_bytes().split(b"\r\n")
    assert len(old) == len(new)
    diff = [i for i, (a, b) in enumerate(zip(old, new)) if a != b]
    assert len(diff) == 1
    a, b = old[diff[0]], new[diff[0]]
    assert len(a) == len(b) and a[:20] == b[:20] and a[40:] == b[40:] and float(b[20:40]) == 1.32
    # free-format card: the token is replaced, nothing else
    old_r, new_r = before["SHELL_0000.rad"].decode().splitlines(), (out / "SHELL_0000.rad").read_text().splitlines()
    changed = [(x, y) for x, y in zip(old_r, new_r) if x != y]
    assert changed == [("5 0 1.5 0.0 1 1", "5 0 1.25 0.0 1 1")]
    ap = {a["parameter"]: a for a in d["applied"]}
    assert ap["BRACKET_SHELL_T"]["old"] == 1.2 and ap["BRACKET_SHELL_T"]["new"] == 1.32 and ap["BRACKET_SHELL_T"]["changed"]
    # re-scan of the written copy reads the new values back
    sc = shell["tmp"] / "rescan"
    sc.mkdir()
    for rel in ("SHELL_0000.rad", "props/shell_props.inc", "shell_mesh.inc"):
        (sc / rel).parent.mkdir(parents=True, exist_ok=True)
        (sc / rel).write_bytes((out / rel).read_bytes() if (out / rel).is_file() else before[rel])
    from paicad.props import scan_tree

    rows, _ = scan_tree(sc)
    assert rows[1].thickness == 1.32 and rows[6].thickness == 1.25 and rows[2].thickness == 0.8


def test_props_apply_unchanged_is_byte_identical(shell):
    code, text, d = _apply(shell, {"BRACKET_SHELL_T": 1.2, "COVER_2_SHELL_T": 0.8, "COVER_6_SHELL_T": 1.5}, "a0")
    assert code == 0 and d["status"] == "OK", text
    for f in d["files"]:
        assert (shell["tmp"] / "a0" / f["rel"]).read_bytes() == (shell["folder"] / f["rel"]).read_bytes() and f["changed"] is False


def test_props_apply_overridden_by_element(shell):
    code, text, d = _apply(shell, {"PANEL_SHELL_T": 2.2}, "a2")
    assert code == EXIT_CHECK and "PAICAD RESULT FAIL PROP_OVERRIDDEN_BY_ELEMENT props_apply.json" in text, text
    assert d["status"] == "FAIL" and d["code"] == "PROP_OVERRIDDEN_BY_ELEMENT" and d["category"] == "PROP" and d["files"] == []
    assert sorted(p.name for p in (shell["tmp"] / "a2").iterdir() if p.is_file()) == ["paicad.log", "props_apply.json"]


@pytest.mark.parametrize("value", [0.0, -1.0])
def test_props_apply_thickness_invalid(shell, value):
    code, text, d = _apply(shell, {"BRACKET_SHELL_T": value}, f"a3_{abs(value)}")
    assert code == EXIT_CHECK and d["code"] == "PROP_THICKNESS_INVALID", text


def test_props_apply_prop_not_found_and_unknown_name(shell):
    # run copy without PROP 1 (its include file removed)
    (shell["folder"] / "props" / "shell_props.inc").unlink()
    code, text, d = _apply(shell, {"BRACKET_SHELL_T": 1.3}, "a4")
    assert code == EXIT_INPUT and d["code"] == "PROP_NOT_FOUND", text
    code, text, d = _apply(shell, {"NOPE_SHELL_T": 1.3}, "a5")
    assert code == EXIT_INPUT and d["code"] == "GEOM_INPUT_INVALID" and "NOPE_SHELL_T" in d["message"], text


def test_props_apply_refuses_existing_output(shell):
    code, _, _ = _apply(shell, {"BRACKET_SHELL_T": 1.3}, "a6")
    assert code == 0
    vp = shell["tmp"] / "a6_values.json"
    code, text = run_cli("props", "apply", "--assem-dir", shell["folder"], "--values", vp, "--props", shell["props_json"], "--out-dir", shell["tmp"] / "a6")
    assert code == EXIT_INPUT and "GEOM_OUTPUT_EXISTS" in text


def test_props_field_rules():
    from paicad.props import PROP_FIELDS, PROP_THICK, field_value, replace_field

    fixed = f"{5:10d}{0:10d}{2.0:20.4f}{0.0:20.4f}"
    assert field_value(fixed, PROP_FIELDS, PROP_THICK) == 2.0
    assert replace_field(fixed, PROP_FIELDS, PROP_THICK, 2.5) == f"{5:10d}{0:10d}{'2.5':>20s}{0.0:20.4f}"
    left = "5         0         1.0                 0.0"  # left-aligned fixed columns
    assert field_value(left, PROP_FIELDS, PROP_THICK) == 1.0
    assert replace_field(left, PROP_FIELDS, PROP_THICK, 1.1)[20:40] == f"{'1.1':>20s}"
    assert field_value("5,0,1.5,0", PROP_FIELDS, PROP_THICK) == 1.5
    assert replace_field("5,0,1.5,0", PROP_FIELDS, PROP_THICK, 1.75) == "5,0,1.75,0"
    assert field_value(f"{5:10d}{0:10d}", PROP_FIELDS, PROP_THICK) == 0.0  # blank field = default 0


# ============================================================= 2. stage 4B paicad map
def _plate(path: Path, xs, T=10.0, H=15.0) -> None:
    from build123d import Align, Box, Compound, Pos, export_step

    mn = (Align.MIN,) * 3
    b = Box(200, 80, T, align=mn)
    for x in xs:
        b = b + Pos(x - 3, 10, T) * Box(6, 60, H, align=mn)
    s = b.solids()[0]
    s.label = "PLATE"
    export_step(Compound(children=[s]), str(path))


@pytest.fixture(scope="module")
def plates(tmp_path_factory):
    root = tmp_path_factory.mktemp("plates")
    cases = {"B5": ([20, 60, 100, 140, 180], 10.0, 15.0), "B3": ([20, 100, 180], 10.0, 15.0), "R1": ([20, 100, 180], 12.0, 20.0), "R2": ([20, 100, 180], 14.0, 25.0)}
    out = {"root": root}
    for k, (xs, T, H) in cases.items():
        _plate(root / f"{k}.step", xs, T, H)
        code, text = run_cli("extract", "--cad", root / f"{k}.step", "--out-dir", root / k, "--no-png")
        assert code == 0, text
        out[k] = root / k / "parameter_features.json"
    return out


def _map(plates, ids, out, *extra):
    bl = write_json(plates["root"] / f"{out}_bl.json", [{"id": i, "features": str(plates[i]), "rel": f"set/{i}"} for i in ids])
    code, text = run_cli("map", "--baselines", bl, "--out-dir", plates["root"] / out, *extra)
    p = plates["root"] / out / "param_map.json"
    return code, text, (load(p) if p.is_file() else None)


def test_map_topology_ribs_5_vs_3(plates):
    code, text, d = _map(plates, ["B5", "B3"], "m53")
    assert code == 0 and text.strip().splitlines()[-1] == "PAICAD RESULT OK - param_map.json", text
    assert d["schema_version"] == 1 and d["map_status"] == "OK" and d["status"] == "draft"
    assert d["confirmed_by"] is None and d["confirmed_at"] is None and d["usage"] == "topology" and d["range_split"] is None
    assert d["discrete"] == {"name": "baseline", "values": ["B5", "B3"]}
    assert d["baselines"] == [{"id": "B5", "rel": "set/B5"}, {"id": "B3", "rel": "set/B3"}]
    assert d["map_options"] == {"weights": {"pos": 0.35, "dim": 0.3, "ori": 0.15, "nbr": 0.2}, "sigma": 0.1, "accept": 0.7, "warn": 0.5, "axis_deg": 10.0}
    rows = {r["proposed"]["name"]: r for r in d["common"]}
    m = {n: r["proposed"]["map"] for n, r in rows.items()}
    # end ribs (mirror group of 2) and the center rib share a row; the inner pair of B5 is N/A in B3
    for kind in ("RIB_T", "RIB_H"):
        assert m[f"PLATE_{kind}_1"] == {"B5": f"PLATE_{kind}_1", "B3": f"PLATE_{kind}_1"}
        assert m[f"PLATE_{kind}_3"] == {"B5": f"PLATE_{kind}_3", "B3": f"PLATE_{kind}_2"}
        assert m[f"PLATE_{kind}_2"] == {"B5": f"PLATE_{kind}_2", "B3": None}
        assert rows[f"PLATE_{kind}_2"]["proposed"]["grade"] == "unmatched" and rows[f"PLATE_{kind}_2"]["proposed"]["candidates"]
        assert rows[f"PLATE_{kind}_1"]["proposed"]["grade"] == "recommend" and rows[f"PLATE_{kind}_1"]["proposed"]["group_size"] == 2
    assert all(m[f"PLATE_THK_{k}"] == {"B5": f"PLATE_THK_{k}", "B3": f"PLATE_THK_{k}"} for k in (1, 2, 3))
    assert len(d["common"]) == 9
    for r in d["common"]:  # proposal only: never a decision, even for score >= 0.7
        assert r["decision"] is None and r["needs_review"] is False and r["signature"].startswith("sha256:")
        assert set(r["proposed"]) >= {"name", "score", "grade", "map", "candidates"}
    names = [r["proposed"]["name"] for r in d["common"]]
    assert len(set(names)) == len(names) and "baseline" not in names


def test_map_range_split_all_matched(plates):
    code, text, d = _map(plates, ["B3", "R1", "R2"], "mr", "--usage", "range", "--split-param", "PLATE_RIB_H_1")
    assert code == 0, text
    assert d["usage"] == "range" and d["discrete"] is None
    assert all(None not in r["proposed"]["map"].values() for r in d["common"]) and len(d["common"]) == 7
    assert all(r["proposed"]["grade"] == "recommend" for r in d["common"])
    assert d["range_split"] == {
        "param": "PLATE_RIB_H_1",
        "intervals": [{"baseline": "B3", "nominal": 15.0}, {"baseline": "R1", "nominal": 20.0}, {"baseline": "R2", "nominal": 25.0}],
    }


def test_map_user_map_inherits_by_signature(plates, tmp_path):
    _, _, d = _map(plates, ["B5", "B3"], "mu0")
    prev = json.loads(json.dumps(d))
    prev["status"], prev["confirmed_by"], prev["confirmed_at"] = "confirmed", "user1", "2026-10-19T00:00:00"
    for r in prev["common"]:
        r["decision"] = {"action": "accept", "name": r["proposed"]["name"], "map": r["proposed"]["map"]}
    prev["common"][0]["signature"] = "sha256:changed"  # as if this row's features had changed
    up = write_json(tmp_path / "prev.json", prev)
    code, text, d2 = _map(plates, ["B5", "B3"], "mu1", "--user-map", up)
    assert code == 0, text
    assert d2["status"] == "draft" and d2["confirmed_by"] is None and d2["confirmed_at"] is None
    first, rest = d2["common"][0], d2["common"][1:]
    assert first["decision"] is None and first["needs_review"] is True
    assert all(r["decision"] == {"action": "accept", "name": r["proposed"]["name"], "map": r["proposed"]["map"]} and not r["needs_review"] for r in rest)
    # inherited decisions that collide -> PARAM_NAME_CONFLICT (exit 3, no param_map.json)
    prev["common"][2]["decision"]["name"] = prev["common"][1]["decision"]["name"]
    up2 = write_json(tmp_path / "prev2.json", prev)
    code, text, d3 = _map(plates, ["B5", "B3"], "mu2", "--user-map", up2)
    assert code == EXIT_INPUT and "PAICAD RESULT FAIL PARAM_NAME_CONFLICT" in text and d3 is None
    prev["common"][2]["decision"]["name"] = "baseline"  # reserved
    code, text, _ = _map(plates, ["B5", "B3"], "mu3", "--user-map", write_json(tmp_path / "prev3.json", prev))
    assert code == EXIT_INPUT and "PARAM_NAME_CONFLICT" in text


def test_map_input_errors(plates, tmp_path):
    code, text, _ = _map(plates, ["B5", "B3"], "me1", "--split-param", "PLATE_RIB_H_1")  # topology + range split
    assert code == EXIT_INPUT and "GEOM_INPUT_INVALID" in text
    code, text, _ = _map(plates, ["B5"], "me2")
    assert code == EXIT_INPUT and "GEOM_INPUT_INVALID" in text
    code, text, _ = _map(plates, ["B3", "R1"], "me3", "--usage", "range", "--split-param", "NOPE")
    assert code == EXIT_INPUT and "GEOM_INPUT_INVALID" in text


def test_map_options_change_is_applied(plates, tmp_path):
    opts = write_json(tmp_path / "o.json", {"schema_version": 1, "map": {"accept": 0.95, "warn": 0.9}})
    code, text, d = _map(plates, ["B5", "B3"], "mo", "--options", opts)
    assert code == 0, text
    assert d["map_options"]["accept"] == 0.95 and d["map_options"]["warn"] == 0.9
    g = {r["proposed"]["name"]: r["proposed"]["grade"] for r in d["common"]}
    assert g["PLATE_THK_3"] == "check" and g["PLATE_RIB_T_1"] == "recommend"  # 0.933 is in [0.9, 0.95)
    assert [w["row_id"] for w in d["warnings"] if w["code"] == "MAP_LOW_SCORE"]
    with pytest.raises(PaicadError):
        options.load(write_json(tmp_path / "bad.json", {"map": {"warn": 0.8, "accept": 0.6}}))
    with pytest.raises(PaicadError):
        options.load(write_json(tmp_path / "bad2.json", {"map": {"weights": {"pos": 1, "dim": 0, "ori": 0, "nbr": 0, "x": 1}}}))


def _member(type_="RIB_THICKNESS", comp="A", pos=(0.5, 0.5, 0.5), d=(1, 0, 0), nominal=6.0, nbr=("PLANE",) * 4):
    return paramap.Member("n", type_, comp, np.array(pos, dtype=float), None if d is None else np.array(d, dtype=float) / np.linalg.norm(d), nominal, Counter(nbr), {})


def test_map_score_gates_and_terms():
    mo = options.load(None)["map"]
    a = _member()
    assert paramap.member_score(a, _member(), mo) == pytest.approx(1.0)
    assert paramap.member_score(a, _member(type_="RIB_HEIGHT"), mo) == paramap.GATED  # type gate
    assert paramap.member_score(a, _member(comp="B"), mo) == paramap.GATED  # component gate
    t = math.radians(11.0)
    assert paramap.member_score(a, _member(d=(math.cos(t), math.sin(t), 0)), mo) == paramap.GATED  # axis gate > 10 deg
    t = math.radians(5.0)
    s_ori = (math.cos(t) - math.cos(math.radians(10))) / (1 - math.cos(math.radians(10)))
    assert paramap.member_score(a, _member(d=(math.cos(t), math.sin(t), 0)), mo) == pytest.approx(1 - 0.15 * (1 - s_ori))
    assert paramap.member_score(a, _member(d=(-1, 0, 0)), mo) == pytest.approx(1.0)  # direction sign does not matter
    # S_pos = exp(-(d/0.1)^2), S_dim = 1 - |dv|/max, S_nbr = multiset Jaccard
    assert paramap.member_score(a, _member(pos=(0.6, 0.5, 0.5)), mo) == pytest.approx(0.65 + 0.35 * math.exp(-1.0))
    assert paramap.member_score(a, _member(nominal=4.0), mo) == pytest.approx(1 - 0.30 * (2.0 / 6.0))
    assert paramap.member_score(a, _member(nbr=("PLANE", "PLANE", "CYLINDER")), mo) == pytest.approx(1 - 0.20 * (1 - 2 / 5))
    # groups: size mismatch gates, members paired by assignment
    u = lambda *ms: paramap.Unit("B", "n", "RIB_THICKNESS", 6.0, list(ms), 0)
    assert paramap.unit_score(u(a, _member(pos=(0.1, 0.5, 0.5))), u(a), mo) == paramap.GATED
    g1 = u(_member(pos=(0.1, 0.5, 0.5)), _member(pos=(0.9, 0.5, 0.5)))
    g2 = u(_member(pos=(0.9, 0.5, 0.5)), _member(pos=(0.1, 0.5, 0.5)))
    assert paramap.unit_score(g1, g2, mo) == pytest.approx(1.0)
    # grade bounds
    assert [paramap.grade_of(s, True, mo) for s in (0.7, 0.6999, 0.5, 0.4999)] == ["recommend", "check", "check", "unmatched"]
    assert paramap.grade_of(0.99, False, mo) == "unmatched"


def test_map_hungarian_maximizes_total():
    mo = options.load(None)["map"]
    mk = lambda b, xs: [paramap.Unit(b, f"{b}_{i}", "RIB_THICKNESS", 6.0, [_member(pos=(x, 0.5, 0.5))], i) for i, x in enumerate(xs)]
    rows = paramap.match([("A", mk("A", [0.30, 0.36])), ("B", mk("B", [0.33, 0.40]))], mo)
    pairs = sorted((r.units["A"].name, r.units["B"].name) for r in rows if len(r.units) == 2)
    assert pairs == [("A_0", "B_0"), ("A_1", "B_1")]  # greedy (A_1-B_0 first) would be worse in total


# ============================================================= 3. feature highlight PNGs
def _png_size(data: bytes) -> tuple[int, int]:
    assert data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR"
    return struct.unpack(">II", data[16:24])


def test_extract_writes_feature_pngs(golden):
    feats = golden["features"]["features"]
    assert feats and not [w for w in golden["features"]["warnings"] if w["code"] == "PNG_RENDER_FAILED"]
    for f in feats:
        assert f["png"] == f"features/{f['name']}.png"
        data = (golden["extract_dir"] / f["png"]).read_bytes()
        assert len(data) > 2000 and _png_size(data) == (800, 600)
    assert sorted(p.name for p in (golden["extract_dir"] / "features").iterdir()) == sorted(f"{f['name']}.png" for f in feats)
    assert all(isinstance(f["adjacent_surfaces"], list) and f["adjacent_surfaces"] for f in feats)


def test_extract_png_failure_is_a_warning(tmp_path):
    from paicad import extract
    from paicad.common import OutDir

    out = OutDir(tmp_path / "o", ["x"])
    out.prepare()

    class NoTess:
        name = "B"

    feat = [{"name": "B_THK_1", "body": "B", "faces": {"moving": ["F1"], "fixed": ["F2"]}, "face_signatures": {}, "png": None}]
    warnings: list[dict] = []
    assert extract._render_pngs(feat, {"B": NoTess()}, out, warnings) == []
    assert feat[0]["png"] is None and warnings[0]["code"] == "PNG_RENDER_FAILED" and warnings[0]["feature"] == "B_THK_1"


def test_extract_no_png(golden, tmp_path):
    code, text = run_cli("extract", "--cad", golden["step"], "--out-dir", tmp_path / "e", "--renum-csv", golden["renum"], "--no-png")
    assert code == 0, text
    d = load(tmp_path / "e" / "parameter_features.json")
    assert all(f["png"] is None for f in d["features"]) and not (tmp_path / "e" / "features").exists()
    assert not [w for w in d["warnings"] if w["code"] == "PNG_RENDER_FAILED"]


# ============================================================= 4. selftest --nx-samples
def test_selftest_nx_samples(golden, tmp_path):
    from data.make_synthetic import CushionSpec, build_bodies, write_step

    nx = tmp_path / "nx"
    write_step(nx / "S1.step", build_bodies(CushionSpec(rib_h=16.0)))  # NX sample = build123d variant
    write_json(nx / "S1.json", {"schema_version": 1, "values": {"CUSH_L_RIB_H_1": 16.0}})
    (nx / "S2.step").write_bytes((nx / "S1.step").read_bytes())  # wrong values on purpose: nominal rib height
    write_json(nx / "S2.json", {"schema_version": 1, "values": {}})
    out = tmp_path / "kit"
    code, text = run_cli(
        "selftest", "--cad", golden["step"], "--baseline-inc", golden["baseline"], "--renum-csv", golden["renum"], "--assem-dir", golden["assem"],
        "--out-dir", out, "--no-envelope", "--nx-samples", nx,
    )
    assert code == 0, text
    r = load(out / "selftest_report.json")
    n = r["nx_samples"]
    assert n["count"] == 2 and n["compared"] == 2 and [s["sample"] for s in n["samples"]] == ["S1", "S2"]
    s1, s2 = n["samples"]
    assert all(st["exit_code"] == 0 for st in s1["stages"].values()) and set(s1["stages"]) == {"nx update", "nx morph", "nx check"}
    assert s1["boundary_vs_nx_mm"]["max"] < 0.05 and s1["boundary_vs_nx_mm"]["n"] > 100
    assert s1["brep_vs_nx_mm"]["max"] < 0.01 and abs(s1["volume_rel_diff_max"]) < 1e-3
    assert s1["param_remeasure"]["max_abs_mm"] < 0.05 and s1["param_remeasure"]["unmeasured"] == 0
    assert 0.9 < s2["boundary_vs_nx_mm"]["max"] < 1.1  # 1 mm rib height difference is reported
    assert n["boundary_vs_nx_max_mm"] == s2["boundary_vs_nx_mm"]["max"]
    from test_stage3 import _keys

    forbidden = {"xyz", "bbox", "centroid", "worst_node", "node_ids", "face_signatures", "pairs", "items", "rows", "applied"}
    assert not (_keys(r, set()) & forbidden)
    md = (out / "selftest_report.md").read_text(encoding="utf-8")
    assert "## NX change samples" in md and "| S1 |" in md


# ============================================================= 5. residuals
def test_narrow_field_takes_representable_values():
    assert radioss._fmt(3.25, 4) == b"3.25"
    assert radioss._fmt(-1.5, 5) == b" -1.5"
    assert radioss._fmt(12.0, 3) == b"12."
    with pytest.raises(PaicadError):
        radioss._fmt(3.123456789, 6)  # needs 7 significant digits
    with pytest.raises(PaicadError):  # exponent text must keep 7 significant digits (no lossy 1.5e+02)
        radioss._fmt(-149.123456, 8)
    assert radioss._fmt(1.5e-8, 8) == b"1.50e-08"
    assert radioss._fmt(-149.123456, 20) == b"-149.123456000000004"  # wide fields unchanged
    # free-format node lines keep a separating blank (tokens never merge)
    data = b"/NODE\n1  0.0   0.0  0.0\n/TETRA4/1\n"
    new = radioss.rewrite_nodes(data, {1: (0.25, 0.0, 0.0)}).split(b"\n")
    assert len(new[1]) == len(data.split(b"\n")[1]) and new[1].split() == [b"1", b"0.25", b"0.", b"0."] and new[1].startswith(b"1 0.25")
    with pytest.raises(PaicadError):  # " 0.0" leaves 3 columns after the blank
        radioss.rewrite_nodes(b"/NODE\n1 0.0 0.0 0.0\n", {1: (0.25, 0.0, 0.0)})


def test_nonfinite_quality_value_is_excluded_not_fail():
    q = options.load(None)["quality"]
    x = np.array([[0, 0, 0], [10, 0, 0], [5, 8.66, 0], [5, 2.89, 8.16]], dtype=float)
    tets = np.array([[0, 1, 2, 3]])
    skin = np.array([[0, 1, 2], [0, 1, 1]])  # second boundary triangle degenerate (repeated node)
    with np.errstate(all="ignore"):
        r = quality.evaluate(x, x, tets, skin, q, np.array([0]))
    assert r.status == "PASS" and r.baseline_ok and r.report["baseline_status"] == "PASS"
    assert r.report["nonfinite_excluded"] == {"max_aspect": 1, "baseline_max_aspect": 1}
    assert r.report["max_aspect"] is not None and quality.nonfinite_metrics(r.report) == ["max_aspect", "baseline_max_aspect"]
    # a finite violation still fails
    q2 = dict(q, max_aspect=1.0)
    with np.errstate(all="ignore"):
        assert quality.evaluate(x, x * [1, 1, 0.2], tets, skin, q2, np.array([0])).status == "FAIL"
    # no non-finite values -> no extra key (outputs of regular meshes unchanged)
    assert "nonfinite_excluded" not in quality.evaluate(x, x, tets, skin[:1], q, np.array([0])).report


def test_golden_report_normalization():
    from data.make_envelope_report import normalize_report

    a = b"# R\n\n- schema_version: 2\n- engine_version: 0.5.0\n- sweep_id: S-aaaaaaaaaaaa\n- steps\n"
    b = b"# R\n\n- schema_version: 2\n- engine_version: 0.6.0\n- sweep_id: S-bbbbbbbbbbbb\n- steps\n"
    assert normalize_report(a) == normalize_report(b) and b"schema_version: 2" in normalize_report(a)
    assert normalize_report(a) != normalize_report(a.replace(b"- steps", b"- steps changed"))
