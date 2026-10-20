"""Stage 4C shell morphing (shell-morph.md): ``paicad shell`` on the virtual sheet-metal golden SM1 + units."""

from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from conftest import run_cli

from paicad.shell import opts as shopts
from paicad.shell.beads import Profile, point_map
from paicad.shell.quality import evaluate, metrics

PARTS = "2001"


# ------------------------------------------------------------------ units (no CAD)
def test_quality_definitions():
    sq = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], dtype=float)
    q = metrics(sq, np.array([[0, 1, 2, 3]]), np.array([False]))
    assert q.warp[0] == pytest.approx(0.0, abs=1e-9) and q.skew[0] == pytest.approx(0.0, abs=1e-9)
    assert q.aspect[0] == pytest.approx(1.0) and q.jac[0] == pytest.approx(1.0)
    assert q.h[0] == pytest.approx(1.0 / math.sqrt(2.0))  # area / longest diagonal
    eq = np.array([[0, 0, 0], [1, 0, 0], [0.5, math.sqrt(3) / 2, 0]])
    t = metrics(eq, np.array([[0, 1, 2, 2]]), np.array([True]))
    assert t.skew[0] == pytest.approx(0.0, abs=1e-9) and t.aspect[0] == pytest.approx(1.0) and t.jac[0] == 1.0 and t.warp[0] == 0.0
    warped = sq.copy()
    warped[2, 2] = 0.3
    assert metrics(warped, np.array([[0, 1, 2, 3]]), np.array([False])).warp[0] > 10.0
    para = np.array([[0, 0, 0], [2, 0, 0], [3, 1, 0], [1, 1, 0]], dtype=float)  # parallelogram: all corner dets equal
    assert metrics(para, np.array([[0, 1, 2, 3]]), np.array([False])).jac[0] == pytest.approx(1.0)
    rep, msg, _ = evaluate(sq, sq[[0, 1, 2, 3]] + 0.0, np.array([[0, 1, 2, 3]]), np.array([False]), shopts.load(None)["quality"])
    assert msg is None and rep["inverted"] == 0 and rep["baseline_status"] == "PASS" and rep["edge_ratio"] == 1.0


def test_quality_relative_and_inversion():
    q = shopts.load(None)["quality"]
    base = np.array([[0, 0, 0], [1, 0, 0], [1.2, 1, 0], [0, 1, 0], [0, 0, 0]], dtype=float)
    flipped = base.copy()
    flipped[:, 1] *= -1  # mirrored -> normal reversed
    rep, msg, _ = evaluate(base, flipped, np.array([[0, 1, 2, 3]]), np.array([False]), q)
    assert rep["inverted"] == 1 and "inverted" in msg
    bad = np.array([[0, 0, 0], [3, 0, 0], [3.2, 0.5, 0], [0, 0.5, 0]], dtype=float)  # aspect 6 > 5 in the baseline
    worse = bad.copy()
    worse[1:3, 0] += 0.05  # +1.7 %: not worse than 1.1 x baseline
    rep, msg, w = evaluate(bad, worse, np.array([[0, 1, 2, 3]]), np.array([False]), q)
    assert msg is None and rep["baseline_status"] == "FAIL" and w[0]["code"] == "BASELINE_QUALITY_BELOW"
    worse[1:3, 0] += 1.0
    rep, msg, _ = evaluate(bad, worse, np.array([[0, 1, 2, 3]]), np.array([False]), q)
    assert "aspect" in msg


def test_shell_options():
    o = shopts.load(None)
    assert o["quality"]["max_warpage_deg"] == 15.0 and o["quality"]["max_skew_deg"] == 60.0 and o["quality"]["max_aspect"] == 5.0
    assert o["quality"]["min_jacobian"] == 0.6 and o["quality"]["min_edge_ratio"] == 0.8 and o["quality"]["dt_ratio_min"] == 0.8
    assert o["fixed"]["transition_mm"] == 6.0 and o["bead"]["depth_mode"] == "keep_angle"


@pytest.mark.parametrize(
    "over,needle",
    [
        ({"quality": {"max_warpge_deg": 1}}, "quality.max_warpge_deg"),
        ({"fixed": {"kinds": ["RBE2", "BCS"]}}, "INTER_TYPE2 and RBE2"),
        ({"fixed": {"transition_mm": -1}}, "transition_mm"),
        ({"quality": {"max_warpage_deg": 50}}, "max_warpage_deg"),
        ({"bead": {"depth_mode": "free"}}, "depth_mode"),
        ({"kind": "solid"}, "kind"),
        ({"morph": {"relax_iters": 51}}, "relax_iters"),
        ({"morph": {"region": "global"}}, "morph.region"),
        ({"morph": {"region_band_mm": 0}}, "region_band_mm"),
        ({"morph": {"region_band_factor": -1}}, "region_band_factor"),
    ],
)
def test_shell_options_rejected(tmp_path, over, needle):
    from paicad.common import PaicadError

    p = tmp_path / "o.json"
    p.write_text(json.dumps({"schema_version": 1, **over}), encoding="utf-8")
    with pytest.raises(PaicadError) as ei:
        shopts.load(p)
    assert ei.value.code == "GEOM_INPUT_INVALID" and needle in ei.value.message


def test_profile_operations():
    p = Profile(rho0=8.309401076758503, rt=2.0, rhob=3.690598923241497, rb=2.0, depth=4.0)
    assert math.degrees(p.theta()) == pytest.approx(60.0) and p.width() == pytest.approx(12.0)
    ka = p.with_depth(4.4, "keep_angle")
    assert ka.rho0 == p.rho0 and ka.theta() == pytest.approx(p.theta()) and ka.width() == pytest.approx(12.0 - 0.4 / math.tan(math.radians(60)))
    kb = p.with_depth(4.4, "keep_bottom")
    assert kb.rhob == p.rhob and kb.rho0 == p.rho0 and kb.theta() > p.theta()
    w = p.with_width_delta(1.0)
    assert w.width() == pytest.approx(13.0) and w.depth == p.depth
    assert p.with_depth(1.0, "keep_angle").valid() is not None  # fillets leave no flank
    assert p.with_width_delta(-4.0).valid() == "bottom_width"
    # the profile map is the identity for an unchanged bead
    from paicad.shell.beads import Bead

    b = Bead("x", 1, [], {}, "linear", "deboss", np.array([0, 0, 1.0]), np.zeros(3), np.array([0, 0, -1.0]), [np.zeros(3), np.array([10.0, 0, 0])], p)
    pts = np.array([[5.0, 8.309401076758503, 0.0], [5.0, 0.0, -4.0], [12.0, 1.0, -4.0]])
    assert np.allclose(point_map(b, p, np.zeros(3), pts), pts, atol=1e-12)
    moved = point_map(b, p, np.array([1.0, 2.0, 0.0]), pts)
    assert np.allclose(moved - pts, [[1.0, 2.0, 0.0]] * 3, atol=1e-12)


def test_in_surface_solve_keeps_rigid_motion():
    from paicad.shell.fem2d import solve_patch

    g = np.array([[i, j] for j in range(5) for i in range(5)], dtype=float) * 2.0 + np.array([[0.3 * ((i * 7) % 3) for i in range(25)]] * 2).T * 0.1
    quads = np.array([[j * 5 + i, j * 5 + i + 1, (j + 1) * 5 + i + 1, (j + 1) * 5 + i] for j in range(4) for i in range(4)])
    bnd = np.array([k for k in range(25) if k % 5 in (0, 4) or k // 5 in (0, 4)])
    for sm in ("elastic", "laplacian"):
        u, info = solve_patch(g, np.zeros((0, 3), dtype=np.int64), quads, bnd, np.tile([0.7, -0.2], (len(bnd), 1)), sm, 0.3, 1e-10, 1000)
        assert np.allclose(u, [0.7, -0.2], atol=1e-8), sm


@pytest.mark.parametrize(
    "argv",
    [
        ["shell"], ["shell", "fixed-scan", "--assem-dir", "x"], ["shell", "extract", "--cad", "x"], ["shell", "tag", "--cad", "x"],
        ["shell", "update", "--cad", "x"], ["shell", "morph", "--sweep"], ["shell", "check", "--assem-dir", "x"], ["shell", "run"], ["shell", "selftest", "--cad", "x"],
    ],
)
def test_shell_cli_argument_errors_exit_2(argv):
    r = subprocess.run([sys.executable, "-m", "paicad", *argv], capture_output=True, text=True, timeout=60)
    assert r.returncode == 2


# ------------------------------------------------------------------ helpers (golden)
@pytest.fixture(scope="module")
def ctx(shell_golden):
    from paicad.shell.morph import load_inputs

    g = shell_golden
    o = shopts.load(None)
    ns = argparse.Namespace(features=g["features_path"], tag_dir=g["tag_dir"], fixed_dir=g["fixed_dir"], assem_dir=g["assem"], update_dir=g["update0"])
    doc, tag_doc, fixed, asm, u, samples, meshes = load_inputs(ns, o)
    nominal = [samples[p["body"]] for p in doc["parts"]]
    return {"g": g, "o": o, "doc": doc, "fixed": fixed, "asm": asm, "meshes": meshes, "nominal": nominal}


def _cores(c, values: dict, o=None, fixed=True):
    from paicad.shell.check import check_core
    from paicad.shell.morph import morph_core
    from paicad.shell.update import update_core

    o = o or c["o"]
    res = update_core(c["nominal"], c["doc"], values, o, c["fixed"] if fixed else None)
    sample = {b.name: b for b in res.bodies}
    m = morph_core(c["meshes"], sample, {"changed": res.changed, "beads": res.beads}, o)
    zero = {mm.index: np.zeros(len(mm.node_ids)) for mm in c["meshes"]}
    chk = check_core(c["meshes"], m.xyz, sample, c["doc"], values, res.expected, res.changed, o, None, {}, {"dist_of": zero}, None, full=False)
    return res, m, chk


def _variant_body(tmp_path, g, bead, **ch):
    from data.make_synthetic_shell import make_step, variant
    from paicad.kernel import load_sheets

    step = make_step(tmp_path, variant(g["spec"], bead, **ch), "variant.step")
    return load_sheets(step)[1][0]


def _write(tmp_path, name, obj) -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(obj), encoding="utf-8")
    return p


# ------------------------------------------------------------------ fixed-scan
def test_fixed_scan_matches_truth(shell_golden, tmp_path):
    g = shell_golden
    s = g["scan"]
    assert s["status"] == "OK" and s["kind"] == "shell" and s["parts"] == [2001]
    t = g["truth"]["fixed"]
    assert s["fixed"]["by_kind"] == t["by_kind"] and s["fixed"]["total"] == t["total"]
    z = np.load(g["fixed_dir"] / "fixed_nodes.npz")
    from paicad.shell.fixed import KINDS

    for bit, k in enumerate(KINDS):
        got = set(int(x) for x in z["node_id"][(z["kind_mask"] & (1 << bit)) != 0])
        assert got == set(t["nodes"][k]), k
    assert {w["code"] for w in s["warnings"]} == {"FIXED_SHARED_NODES"}
    kinds = {k for c in s["fixed"]["clusters"] for k in c["kinds"]}
    assert kinds == set(KINDS)
    cand = {c["part_id"]: c for c in s["candidates"]}
    assert cand[2001]["n_other"] == 0 and cand[2001]["prop"]["thickness"] == 0.8 and cand[2001]["n_shell"] == g["truth"]["fixed"]["n_quad"]
    # deterministic digest
    code, _ = run_cli("shell", "fixed-scan", "--assem-dir", g["assem"], "--out-dir", tmp_path / "f2", "--features", g["features_path"])
    assert code == 0
    assert json.loads((tmp_path / "f2" / "shell_scan.json").read_text())["fixed"]["digest"] == s["fixed"]["digest"]


def test_fixed_scan_list_mode_and_errors(shell_golden, tmp_path):
    g = shell_golden
    code, out = run_cli("shell", "fixed-scan", "--assem-dir", g["assem"], "--out-dir", tmp_path / "a")
    d = json.loads((tmp_path / "a" / "shell_scan.json").read_text())
    assert code == 0 and d["fixed"] is None and d["parts"] == [] and {c["part_id"] for c in d["candidates"]} == {2001, 2002, 2003, 2004}
    code, out = run_cli("shell", "fixed-scan", "--assem-dir", g["assem"], "--out-dir", tmp_path / "b", "--parts", "9999")
    assert code == 3 and "SHELL_PART_NOT_FOUND" in out
    assert json.loads((tmp_path / "b" / "shell_scan.json").read_text())["code"] == "SHELL_PART_NOT_FOUND"
    code, out = run_cli("shell", "fixed-scan", "--assem-dir", g["assem"], "--out-dir", tmp_path / "a", "--parts", PARTS)
    assert code == 3 and "GEOM_OUTPUT_EXISTS" in out


def test_fixed_scan_unsupported_set_and_kind_options(shell_golden, tmp_path):
    g = shell_golden
    asm = tmp_path / "assem"
    shutil.copytree(g["assem"], asm)
    extra = "/RBE2/599\nBOXED\n" + f"{900099:10d}{'   111111':>10s}{0:10d}{598:10d}{0:10d}\n/GRNOD/BOX/598\nBOX\n" + f"{1:10d}\n/NODE\n{900099:10d}{1.0:20.4f}{1.0:20.4f}{0.0:20.4f}\n"
    (asm / "inc" / "extra.inc").write_text(extra, encoding="ascii")
    code, out = run_cli("shell", "fixed-scan", "--assem-dir", asm, "--out-dir", tmp_path / "a", "--parts", PARTS)
    d = json.loads((tmp_path / "a" / "shell_scan.json").read_text())
    assert code == 12 and d["code"] == "SHELL_FIXED_PARSE_FAILED" and "GRNOD/BOX/598" in d["message"]
    o = _write(tmp_path, "o.json", {"schema_version": 1, "fixed": {"required": False, "kinds": ["INTER_TYPE2", "RBE2", "RBE3", "RBODY", "BCS"]}})
    code, out = run_cli("shell", "fixed-scan", "--assem-dir", asm, "--out-dir", tmp_path / "b", "--parts", PARTS, "--options", o)
    d = json.loads((tmp_path / "b" / "shell_scan.json").read_text())
    codes = {w["code"] for w in d["warnings"]}
    assert code == 0 and {"FIXED_PARSE_SKIPPED", "FIXED_KIND_SKIPPED"} <= codes
    t = g["truth"]["fixed"]["nodes"]
    expect = set().union(*(set(v) for k, v in t.items() if k != "SHARED")) | (set(t["SHARED"]) & set(t["RBODY"]))
    assert d["fixed"]["total"] == len(expect) and d["fixed"]["by_kind"]["SHARED"] == len(t["SHARED"])


# ------------------------------------------------------------------ extract
def test_extract_recognizes_truth_beads(shell_golden):
    g = shell_golden
    d = g["features"]
    assert d["kind"] == "shell" and d["parts"][0]["part_id"] == 2001 and d["parts"][0]["title"] == "CHASSIS_REAR"
    assert len(d["beads"]) == len(g["truth"]["beads"]) == 5
    by_id = {b["id"]: b for b in d["beads"]}
    feats = {f["name"]: f for f in d["features"]}
    for tb in g["truth"]["beads"]:
        nm = g["names"][tb["name"]]
        b = by_id[nm["id"]]
        assert b["shape"] == tb["kind"] and b["sense"] == tb["sense"]
        assert np.allclose(b["center"], tb["center"], atol=0.05)
        for key, tv in (("depth", tb["depth"]), ("width", tb["width"]), ("length", tb["length"]), ("flank_deg", tb["flank_deg"])):
            assert abs(b["nominal"][key] - tv) <= 0.01 * tv, (tb["name"], key)
        assert feats[nm["BEAD_DEPTH"]]["nominal"] == pytest.approx(tb["depth"], rel=0.01)
        assert feats[nm["BEAD_WIDTH"]]["nominal"] == pytest.approx(tb["width"], rel=0.01)
        k = {f.rsplit("_", 1)[1] for t, f in nm.items() if t != "id"}
        assert len(k) == 1 and str(b["k"]) in k  # the four parameters of one bead share k
    # fixed overlap: B5 spider covers the bead (not used by default), B4 next to the tie band
    w = {(x["code"], x.get("bead")) for x in d["warnings"]}
    b5, b4 = g["names"]["B5"], g["names"]["B4"]
    assert by_id[b5["id"]]["fixed_overlap"] == "inside" and ("BEAD_FIXED_OVERLAP", b5["id"]) in w
    assert all(not feats[b5[t]]["use_default"] for t in ("BEAD_DEPTH", "BEAD_POS_U", "BEAD_POS_V", "BEAD_WIDTH"))
    assert by_id[b4["id"]]["fixed_overlap"] == "transition" and ("BEAD_NEAR_FIXED", b4["id"]) in w and feats[b4["BEAD_DEPTH"]]["use_default"]
    for n in ("B1", "B2", "B3"):
        assert by_id[g["names"][n]["id"]]["fixed_overlap"] == "none"
    # position: nearest fixed straight edge, absolute mm range; XML = all parameters
    f = feats[g["names"]["B1"]["BEAD_POS_U"]]
    assert f["nominal"] == pytest.approx(120.0, abs=0.05) and f["range"] == {"min": 115.0, "max": 125.0, "abs_mm": 5.0} and f["ref"]["rule"] == "nearest_fixed_edge"
    xml = (g["extract_dir"] / "parameter_extracted.xml").read_text(encoding="utf-8")
    assert xml.count("<Parameter>") == len(d["features"]) == 20
    assert all((g["extract_dir"] / x["png"]).is_file() for x in d["features"])
    assert [f["type"] for f in d["features"][:5]] == ["BEAD_DEPTH"] * 5  # component -> type -> bead order


def test_extract_without_assembly_and_solid_step(shell_golden, tmp_path):
    g = shell_golden
    code, out = run_cli("shell", "extract", "--cad", g["step"], "--out-dir", tmp_path / "e", "--no-png")
    d = json.loads((tmp_path / "e" / "shell_features.json").read_text())
    assert code == 0 and d["parts"][0]["part_id"] is None and {b["fixed_overlap"] for b in d["beads"]} == {"unknown"}
    assert any(w["code"] == "FIXED_INFO_MISSING" for w in d["warnings"])
    from build123d import Box, Compound, export_step

    b = Box(10, 10, 10)
    b.label = "block"
    export_step(Compound(children=[b]), str(tmp_path / "solid.step"))
    code, out = run_cli("shell", "extract", "--cad", tmp_path / "solid.step", "--out-dir", tmp_path / "s", "--no-png")
    assert code == 12 and "SHELL_BODY_NOT_SHEET" in out


# ------------------------------------------------------------------ tag
def test_tag_classifies_every_node(shell_golden):
    g = shell_golden
    t = g["tag"]
    p = t["parts"][0]
    assert t["status"] == "OK" and t["match_ratio"] == 1.0 and p["classified"]["unmatched"] == 0
    assert p["nodes"] == g["truth"]["fixed"]["n_nodes"] and p["fixed"] == g["truth"]["fixed"]["total"] and p["transition"] > 0
    assert p["elements"] == {"quad": g["truth"]["fixed"]["n_quad"] - g["truth"]["fixed"]["n_degenerate"], "tri": g["truth"]["fixed"]["n_tri"]}
    assert p["classified"]["vertex"] == g["features"]["parts"][0]["vertices"]
    z = np.load(g["tag_dir"] / "shell_tag_nodes.npz")
    assert 0 not in set(z["kind"].tolist()) and np.all(z["geo_dist_fixed"][z["fixed"]] == 0) and np.all(z["geo_dist_fixed"][~z["fixed"]] > 0)
    assert t["fixed_digest"] == g["scan"]["fixed"]["digest"]


def test_tag_offset_mesh_is_baseline_mismatch(shell_golden, tmp_path):
    g = shell_golden
    asm = tmp_path / "assem"
    shutil.copytree(g["assem"], asm)
    for name in ("chassis.inc", "chassis_flange_nodes.inc"):
        p = asm / "inc" / name
        lines = p.read_text(encoding="ascii").splitlines()
        out, in_node = [], False
        for ln in lines:
            if ln.startswith("/"):
                in_node = ln.strip() == "/NODE"
            elif in_node and not ln.startswith("#") and ln.strip():
                ln = ln[:50] + f"{float(ln[50:70]) + 0.4:20.10f}"
            out.append(ln)
        p.write_text("\n".join(out) + "\n", encoding="ascii")
    assert run_cli("shell", "fixed-scan", "--assem-dir", asm, "--out-dir", tmp_path / "f", "--parts", PARTS)[0] == 0
    code, out = run_cli("shell", "tag", "--cad", g["step"], "--features", g["features_path"], "--assem-dir", asm, "--fixed-dir", tmp_path / "f", "--out-dir", tmp_path / "t")
    d = json.loads((tmp_path / "t" / "shell_tag.json").read_text())
    assert code == 12 and d["code"] == "GEOM_BASELINE_MISMATCH" and "mid-surface" in d["message"]


# ------------------------------------------------------------------ R1: unchanged round trip
def test_nominal_round_trip_writes_nothing(shell_golden, tmp_path):
    from paicad.mesh.radioss import rewrite_nodes

    g = shell_golden
    for p in sorted(Path(g["assem"]).rglob("*.inc")):
        assert rewrite_nodes(p.read_bytes(), {}) == p.read_bytes()
    code, out = run_cli("shell", "morph", "--assem-dir", g["assem"], "--tag-dir", g["tag_dir"], "--fixed-dir", g["fixed_dir"], "--features", g["features_path"],
                        "--update-dir", g["update0"], "--out-dir", tmp_path / "m")
    m = json.loads((tmp_path / "m" / "shell_morph.json").read_text())
    assert code == 0 and m["files"] == [] and m["max_disp_mm"] == 0.0
    code, out = run_cli("shell", "check", "--assem-dir", g["assem"], "--morph-dir", tmp_path / "m", "--update-dir", g["update0"], "--tag-dir", g["tag_dir"],
                        "--fixed-dir", g["fixed_dir"], "--features", g["features_path"], "--values", g["values0"], "--out-dir", tmp_path / "c", "--out-files-dir", tmp_path / "of")
    c = json.loads((tmp_path / "c" / "shell_check.json").read_text())
    assert code == 0 and c["status"] == "PASS" and c["out_files"] == [] and not (tmp_path / "of").exists()
    assert c["checks"]["tie"]["status"] == "PASS" and len(c["checks"]["tie"]["interfaces"]) == 2 and c["checks"]["interference"]["status"] == "PASS"


# ------------------------------------------------------------------ parameter accuracy vs build123d variants
CASES = [
    ("B1", "BEAD_DEPTH", 0.4, {"depth": 4.4}),
    ("B1", "BEAD_DEPTH", -0.4, {"depth": 3.6}),
    ("B1", "BEAD_POS_U", 3.0, {"shift": (3.0, 0.0)}),
    ("B1", "BEAD_POS_V", -3.0, {"shift": (0.0, -3.0)}),
    ("B1", "BEAD_WIDTH", 1.2, {"width": 13.2}),
    ("B1", "BEAD_WIDTH", -1.2, {"width": 10.8}),
    ("B3", "BEAD_DEPTH", 0.3, {"depth": 3.3}),
    ("B3", "BEAD_POS_V", 3.0, {"shift": (0.0, 3.0)}),
    ("B3", "BEAD_WIDTH", 3.0, {"width": 33.0}),
    ("B3", "BEAD_WIDTH", -3.0, {"width": 27.0}),
]


@pytest.mark.parametrize("bead,ptype,delta,change", CASES, ids=[f"{b}-{t}-{d:+g}" for b, t, d, _ in CASES])
def test_variant_accuracy(ctx, tmp_path, bead, ptype, delta, change):
    g = ctx["g"]
    name = g["names"][bead][ptype]
    feat = next(f for f in ctx["doc"]["features"] if f["name"] == name)
    value = feat["nominal"] + delta
    if ptype in ("BEAD_POS_U", "BEAD_POS_V"):
        sh = np.asarray(change["shift"] + (0.0,))
        move = float(np.dot(sh, np.asarray(feat["ref"]["axis"]) * feat["ref"]["sign"]))
        value = feat["nominal"] + move
    res, m, chk = _cores(ctx, {name: value})
    vb = _variant_body(tmp_path, g, bead, **change)
    sb = res.bodies[0]
    ts, tv = sb.topology(), vb.topology()
    assert len(ts.faces) == len(tv.faces)
    changed = res.changed[sb.name]
    faces = sorted(int(x[1:]) for x in changed["geometry"] + changed["boundary_only"])
    for f in faces:  # update B-rep <-> variant: face distance and area
        pts = sb.sample_face(f, 8)
        d, _, _, _ = vb.project_to_face(f, pts)
        assert float(d.max()) <= 0.01, f
        assert abs(ts.face(f).area - tv.face(f).area) <= 1e-3 * tv.face(f).area, f
    mesh = ctx["meshes"][0]
    new = m.xyz[0]
    sel = np.flatnonzero((mesh.kind == 1) & np.isin(mesh.ent, faces))
    for f in faces:  # morphed nodes <-> variant faces
        idx = sel[mesh.ent[sel] == f]
        if len(idx):
            d, _, _, _ = vb.project_to_face(f, new[idx])
            assert float(d.max()) <= 0.05, f
    edges = sorted(int(x[1:]) for x in changed["edges"])
    ie = np.flatnonzero((mesh.kind == 2) & np.isin(mesh.ent, edges))
    for e in edges:  # morphed edge nodes <-> variant edges
        idx = ie[mesh.ent[ie] == e]
        if len(idx):
            d, _, _ = vb.project_to_edge(e, new[idx])
            assert float(d.max()) <= 0.05, e
    assert np.all(new[mesh.fixed] == mesh.xyz[mesh.fixed])  # fixed nodes exactly unchanged
    items = {i["name"]: i for i in chk.checks["param"]["items"]}
    it = items[name]
    assert it["err"] <= max(0.05, 0.01 * abs(it["expected"]))
    for i in items.values():
        assert i["err"] is not None and i["err"] <= i["tol"]
    assert chk.checks["deviation"]["max_mm"] <= 0.05 and chk.checks["fixed"]["moved_fixed_nodes"] == 0


def test_keep_bottom_depth_matches_variant(ctx, tmp_path):
    g = ctx["g"]
    o = shopts.load(_write(tmp_path, "o.json", {"schema_version": 1, "bead": {"depth_mode": "keep_bottom"}}))
    name = g["names"]["B2"]["BEAD_DEPTH"]
    from paicad.shell.update import update_core

    res = update_core(ctx["nominal"], ctx["doc"], {name: 3.3}, o, ctx["fixed"])
    b = next(x for x in res.beads if x["id"] == g["names"]["B2"]["id"])
    np_ = Profile(**b["new_profile"])
    tb = next(t for t in g["truth"]["beads"] if t["name"] == "B2")
    vb = _variant_body(tmp_path, g, "B2", depth=3.3, width=np_.width(), flank_deg=math.degrees(np_.theta()))
    sb = res.bodies[0]
    for f in sorted(int(x[1:]) for x in res.changed[sb.name]["geometry"]):
        d, _, _, _ = vb.project_to_face(f, sb.sample_face(f, 8))
        assert float(d.max()) <= 0.01
    assert np_.rho0 == pytest.approx(tb["rho0"]) and np_.rhob == pytest.approx(tb["rho_b"])


# ------------------------------------------------------------------ fixed region / collisions / transition
def test_fixed_region_violation(shell_golden, ctx, tmp_path):
    g = shell_golden
    b5 = g["names"]["B5"]
    v = _write(tmp_path, "v.json", {"schema_version": 1, "values": {b5["BEAD_DEPTH"]: 3.3}})
    code, out = run_cli("shell", "update", "--cad", g["step"], "--features", g["features_path"], "--values", v, "--fixed-dir", g["fixed_dir"], "--out-dir", tmp_path / "u")
    d = json.loads((tmp_path / "u" / "shell_update.json").read_text())
    assert code == 10 and d["code"] == "SHELL_FIXED_REGION_VIOLATION" and d["category"] == "FIXED" and b5["BEAD_DEPTH"] in d["message"]
    assert d["fixed_precheck"]["status"] == "FAIL" and not (tmp_path / "u" / "sample.brep").exists()
    # without the pre-check, morph refuses to move the fixed nodes
    code, out = run_cli("shell", "update", "--cad", g["step"], "--features", g["features_path"], "--values", v, "--out-dir", tmp_path / "u2")
    assert code == 0 and json.loads((tmp_path / "u2" / "shell_update.json").read_text())["fixed_precheck"]["status"] == "NOT_EVALUATED"
    code, out = run_cli("shell", "morph", "--assem-dir", g["assem"], "--tag-dir", g["tag_dir"], "--fixed-dir", g["fixed_dir"], "--features", g["features_path"],
                        "--update-dir", tmp_path / "u2", "--out-dir", tmp_path / "m")
    d = json.loads((tmp_path / "m" / "shell_morph.json").read_text())
    assert code == 11 and d["code"] == "SHELL_FIXED_REGION_VIOLATION" and d["category"] == "FIXED"
    # moving the bead next to the tie band into it
    b4 = g["names"]["B4"]
    f = next(x for x in ctx["doc"]["features"] if x["name"] == b4["BEAD_POS_V"])
    from paicad.common import PaicadError
    from paicad.shell.update import update_core

    with pytest.raises(PaicadError) as ei:
        update_core(ctx["nominal"], ctx["doc"], {f["name"]: f["nominal"] - 5.0}, ctx["o"], ctx["fixed"])
    assert ei.value.code == "SHELL_FIXED_REGION_VIOLATION" and ei.value.exit_code == 10


def test_collision_with_plate_boundary(ctx):
    from paicad.common import PaicadError
    from paicad.shell.update import update_core

    name = ctx["g"]["names"]["B1"]["BEAD_POS_U"]
    with pytest.raises(PaicadError) as ei:
        update_core(ctx["nominal"], ctx["doc"], {name: 40.0}, ctx["o"], ctx["fixed"])
    assert ei.value.code == "GEOM_FEATURE_COLLISION" and ei.value.exit_code == 10 and ei.value.detail["collisions"][0]["kind"] == "BOUNDARY_OVERLAP"
    name = ctx["g"]["names"]["B1"]["BEAD_DEPTH"]
    with pytest.raises(PaicadError) as ei:
        update_core(ctx["nominal"], ctx["doc"], {name: 9.0}, ctx["o"], ctx["fixed"])
    assert ei.value.code == "GEOM_FEATURE_COLLISION"


def test_transition_zone_attenuation(ctx, tmp_path):
    g = ctx["g"]
    b4 = g["names"]["B4"]
    f = next(x for x in ctx["doc"]["features"] if x["name"] == b4["BEAD_POS_V"])
    vals = {f["name"]: f["nominal"] + 1.0}  # away from the tie band
    o0 = shopts.load(_write(tmp_path, "o0.json", {"schema_version": 1, "fixed": {"transition_mm": 0.0}}))
    _, m6, c6 = _cores(ctx, vals)
    _, m0, c0 = _cores(ctx, vals, o0)
    mesh = ctx["meshes"][0]
    zone = np.flatnonzero((mesh.kind == 1) & (mesh.ent == 1) & (mesh.geo > 0) & (mesh.geo < 6.0))
    d6 = np.linalg.norm(m6.disp[0][zone], axis=1)
    d0 = np.linalg.norm(m0.disp[0][zone], axis=1)
    r = mesh.geo[zone] / 6.0
    s = 3 * r * r - 2 * r**3
    keep = d0 > 1e-6
    assert keep.sum() > 10
    assert np.allclose(d6[keep], (s * d0)[keep], atol=1e-6)
    assert c6.checks["fixed"]["moved_fixed_nodes"] == 0 and c6.checks["deviation"]["max_mm"] <= 0.05


# ------------------------------------------------------------------ local region solve of the base face (0.10.0)
LOCAL_CASES = [("B1", "BEAD_POS_U", 3.0), ("B1", "BEAD_POS_U", 10.0), ("B1", "BEAD_WIDTH", 1.2), ("B3", "BEAD_POS_V", 3.0), ("B3", "BEAD_WIDTH", 3.0)]


@pytest.mark.parametrize("bead,ptype,delta", LOCAL_CASES, ids=[f"{b}-{t}-{d:+g}" for b, t, d in LOCAL_CASES])
def test_local_region_limits_moved_nodes(ctx, tmp_path, bead, ptype, delta):
    """Position / width change: only base-face nodes within the band around the moving entry loop move (all
    others keep their coordinates exactly), accuracy as before, far fewer moved nodes than the face solve."""
    from scipy.spatial import cKDTree

    g = ctx["g"]
    name = g["names"][bead][ptype]
    feat = next(f for f in ctx["doc"]["features"] if f["name"] == name)
    bj = next(b for b in ctx["doc"]["beads"] if b["id"] == feat["bead"])
    vals = {name: feat["nominal"] + delta}
    res, m, chk = _cores(ctx, vals)
    o_face = shopts.load(_write(tmp_path, "of.json", {"schema_version": 1, "morph": {"region": "face"}}))
    _, mf, chkf = _cores(ctx, vals, o_face)
    mesh = ctx["meshes"][0]
    info = m.parts[0]["region"]
    loop_disp = abs(delta) if ptype != "BEAD_WIDTH" else 0.5 * abs(delta)
    assert info["mode"] == "local" and info["faces"] == 1 and info["band_mm"] == pytest.approx(max(40.0, 5.0 * loop_disp), abs=1e-6)
    assert mf.parts[0]["region"] == {"mode": "face", "faces": 0, "nodes": 0, "band_mm": 0.0}
    moved = np.any(m.disp[0] != 0.0, axis=1)
    moved_face = np.any(mf.disp[0] != 0.0, axis=1)
    base = (mesh.kind == 1) & (mesh.ent == int(bj["base_face"][1:]))
    loop = (mesh.kind == 2) & np.isin(mesh.ent, [int(e[1:]) for e in bj["loop"]])
    dist, _ = cKDTree(mesh.xyz[loop]).query(mesh.xyz)
    band = info["band_mm"]
    assert dist[moved & base].max() < band + 3.0  # inside the region (3 mm = mesh size slack: distance to loop nodes)
    far = base & (dist > band + 3.0)
    assert far.sum() > 1000 and not moved[far].any() and np.array_equal(m.xyz[0][far], mesh.xyz[far])
    assert 0 < info["nodes"] and (moved & base).sum() <= info["nodes"]
    assert moved.sum() <= 0.25 * moved_face.sum(), (int(moved.sum()), int(moved_face.sum()))
    # accuracy unchanged: boundary deviation <= 0.05 mm, re-measure within max(0.05 mm, 1 %), fixed nodes untouched
    for c in (chk, chkf):
        assert c.checks["deviation"]["max_mm"] <= 0.05 and c.checks["fixed"]["moved_fixed_nodes"] == 0
        for it in c.checks["param"]["items"]:
            assert it["err"] is not None and it["err"] <= it["tol"]
    assert chk.status == "PASS"


# bead position steps where the 0.9.0 face solve failed the quality check (relative Jacobian of baseline-poor
# elements next to the moving loop, tie-band transition) - B1 V +10 is the one step the local solve loses
QUALITY_CASES = [("B2", "BEAD_POS_U", 8.0), ("B2", "BEAD_POS_U", 10.0), ("B2", "BEAD_POS_V", -8.0), ("B2", "BEAD_POS_V", -10.0), ("B2", "BEAD_POS_V", 10.0),
                 ("B1", "BEAD_POS_V", -10.0), ("B1", "BEAD_POS_V", 10.0), ("B4", "BEAD_POS_U", -2.0)]


def test_local_region_reduces_quality_failures(ctx, tmp_path):
    g = ctx["g"]
    o_face = shopts.load(_write(tmp_path, "of.json", {"schema_version": 1, "morph": {"region": "face"}}))
    fails = {"local": [], "face": []}
    for bead, ptype, delta in QUALITY_CASES:
        name = g["names"][bead][ptype]
        feat = next(f for f in ctx["doc"]["features"] if f["name"] == name)
        vals = {name: feat["nominal"] + delta}
        for mode, o in (("local", None), ("face", o_face)):
            _, _, chk = _cores(ctx, vals, o)
            if chk.status != "PASS":
                assert chk.code == "GEOM_QUALITY"
                fails[mode].append((bead, ptype, delta))
    # SM1 numbers (all 127 position / width steps of the default envelope: face 29 FAIL -> local 23 FAIL)
    assert len(fails["face"]) == 7 and len(fails["local"]) == 1, fails
    assert fails["local"] == [("B1", "BEAD_POS_V", 10.0)]


# ------------------------------------------------------------------ run: R1 output, determinism
def test_run_writes_node_fields_only_and_is_deterministic(shell_golden, ctx, tmp_path):
    g = shell_golden
    names = g["names"]
    v = _write(tmp_path, "v.json", {"schema_version": 1, "values": {names["B1"]["BEAD_DEPTH"]: 4.4, names["B3"]["BEAD_WIDTH"]: 31.5, names["B2"]["BEAD_POS_U"]: 152.0}})
    outs = []
    for k in (1, 2):
        d = tmp_path / f"r{k}"
        code, out = run_cli("shell", "run", "--cad", g["step"], "--features", g["features_path"], "--values", v, "--assem-dir", g["assem"], "--tag-dir", g["tag_dir"],
                            "--fixed-dir", g["fixed_dir"], "--update-dir", d / "u", "--morph-dir", d / "m", "--check-dir", d / "c", "--out-files-dir", d / "files")
        r = json.loads((d / "c" / "shell_run.json").read_text())
        assert code == 0, out
        assert r["status"] == "PASS" and r["out_files"] == ["inc/chassis.inc"] and [s["step"] for s in r["stages"]] == ["update", "morph", "check"]
        outs.append((d / "files" / "inc" / "chassis.inc").read_bytes())
    assert outs[0] == outs[1]
    assert not (tmp_path / "r1" / "files" / "inc" / "chassis_flange_nodes.inc").exists()
    old = (Path(g["assem"]) / "inc" / "chassis.inc").read_bytes().splitlines(keepends=True)
    new = outs[0].splitlines(keepends=True)
    assert len(old) == len(new)
    fixed = set(int(x) for x in np.load(g["fixed_dir"] / "fixed_nodes.npz")["node_id"])
    in_node = False
    changed = 0
    for a, b in zip(old, new):
        if a.startswith(b"/"):
            in_node = a.strip() == b"/NODE"
        if a == b:
            continue
        assert in_node and a[:10] == b[:10] and len(a) == len(b)
        assert int(a[:10]) not in fixed
        changed += 1
    assert changed > 0
    from paicad.mesh.radioss import parse_text

    m0, m1 = parse_text(b"".join(old).decode("latin-1")), parse_text(outs[0].decode("latin-1"))
    assert np.array_equal(m0.node_ids, m1.node_ids) and len(m0.blocks) == len(m1.blocks)
    assert all(np.array_equal(x.ids, y.ids) and np.array_equal(x.conn, y.conn) for x, y in zip(m0.blocks, m1.blocks))
    # a run that fails in update stops there (fixed region)
    v2 = _write(tmp_path, "v2.json", {"schema_version": 1, "values": {names["B5"]["BEAD_DEPTH"]: 3.3}})
    d = tmp_path / "rf"
    code, out = run_cli("shell", "run", "--cad", g["step"], "--features", g["features_path"], "--values", v2, "--assem-dir", g["assem"], "--tag-dir", g["tag_dir"],
                        "--fixed-dir", g["fixed_dir"], "--update-dir", d / "u", "--morph-dir", d / "m", "--check-dir", d / "c", "--out-files-dir", d / "files")
    r = json.loads((d / "c" / "shell_run.json").read_text())
    assert code == 10 and r["skip"]["code"] == "SHELL_FIXED_REGION_VIOLATION" and r["skip"]["category"] == "FIXED" and len(r["stages"]) == 1


# ------------------------------------------------------------------ envelope
def test_sweep_units_delta_and_fixed_limit(shell_golden, tmp_path):
    g = shell_golden
    n = g["names"]
    params = ",".join([n["B1"]["BEAD_DEPTH"], n["B3"]["BEAD_POS_U"], n["B5"]["BEAD_DEPTH"]])
    code, out = run_cli("shell", "morph", "--sweep", "--assem-dir", g["assem"], "--tag-dir", g["tag_dir"], "--fixed-dir", g["fixed_dir"], "--features", g["features_path"],
                        "--update-dir", g["update0"], "--out-dir", tmp_path / "s", "--params", params, "--steps", "10", "--pos-steps", "3", "--stop-after-fail", "1")
    assert code == 0, out
    env = json.loads((tmp_path / "s" / "envelope.json").read_text())
    assert env["schema_version"] == 2 and env["kind"] == "shell"
    rows = {(r["param"], r["direction"]): r for r in env["rows"]}
    assert rows[(n["B1"]["BEAD_DEPTH"], "+")]["unit"] == "%" and rows[(n["B1"]["BEAD_DEPTH"], "+")]["delta_mm"] == pytest.approx(0.4)
    assert rows[(n["B3"]["BEAD_POS_U"], "+")]["unit"] == "mm" and rows[(n["B3"]["BEAD_POS_U"], "+")]["delta_mm"] is None
    summ = {s["param"]: s for s in env["summary"]}
    s5 = summ[n["B5"]["BEAD_DEPTH"]]
    assert s5["first_fail_code"] == {"+": "SHELL_FIXED_REGION_VIOLATION", "-": "SHELL_FIXED_REGION_VIOLATION"} and s5["limited_by"] == {"+": "fixed", "-": "fixed"}
    assert summ[n["B1"]["BEAD_DEPTH"]]["last_ok"] == {"+": 10.0, "-": 10.0}
    f = json.loads((tmp_path / "s" / "shell_features.json").read_text())
    fe = {x["name"]: x["feasible"] for x in f["features"]}
    assert fe[n["B1"]["BEAD_DEPTH"]]["source"] == "envelope" and fe[n["B1"]["BEAD_DEPTH"]]["min"] == pytest.approx(3.6) and fe[n["B5"]["BEAD_DEPTH"]]["limited_by"] == "fixed"
    assert fe[n["B2"]["BEAD_DEPTH"]]["source"] == "estimate"
    md = (tmp_path / "s" / "report_envelope.md").read_text()
    assert "| " + n["B5"]["BEAD_DEPTH"] in md and "SHELL_FIXED_REGION_VIOLATION" in md
    csv_head = (tmp_path / "s" / "envelope.csv").read_text().splitlines()[0]
    assert "delta_mm" in csv_head and "max_warpage_deg" in csv_head


# ------------------------------------------------------------------ multi-baseline: bead-level matching
def test_map_bead_level_matching(shell_golden, tmp_path):
    import copy

    from data.make_synthetic_shell import make_step

    g = shell_golden
    spec3 = copy.deepcopy(g["spec"])
    spec3.beads = [b for b in spec3.beads if b.name in ("B1", "B2", "B3")]
    spec2 = copy.deepcopy(g["spec"])
    spec2.beads = [b for b in spec2.beads if b.name in ("B1", "B3")]
    docs = []
    for k, sp in (("bl3", spec3), ("bl2", spec2)):
        step = make_step(tmp_path / k, sp, "mid.step")
        assert run_cli("shell", "extract", "--cad", step, "--out-dir", tmp_path / k / "ex", "--no-png")[0] == 0
        docs.append(tmp_path / k / "ex" / "shell_features.json")
    bl = _write(tmp_path, "baselines.json", [{"id": "bl3", "features": str(docs[0])}, {"id": "bl2", "features": str(docs[1])}])
    code, out = run_cli("map", "--baselines", bl, "--out-dir", tmp_path / "map")
    assert code == 0, out
    d = json.loads((tmp_path / "map" / "param_map.json").read_text())
    assert d["kind"] == "shell" and d["status"] == "draft"
    f3 = json.loads(docs[0].read_text())
    f2 = json.loads(docs[1].read_text())
    c3 = {b["id"]: tuple(b["center"]) for b in f3["beads"]}
    c2 = {b["id"]: tuple(b["center"]) for b in f2["beads"]}
    groups: dict[str, list[dict]] = {}
    for r in d["common"]:
        groups.setdefault(r["group"], []).append(r)
    assert len(groups) == 3 and all(len(rs) == 4 for rs in groups.values())
    matched = 0
    for gid, rs in groups.items():
        beads = rs[0]["proposed"]["beads"]
        assert all(r["proposed"]["beads"] == beads for r in rs)  # one bead correspondence per group
        if beads["bl2"] is None:
            assert all(r["proposed"]["map"]["bl2"] is None for r in rs) and c3[beads["bl3"]][:2] == (250.0, 150.0)  # B2: N/A in the 2-bead baseline
        else:
            matched += 1
            assert c3[beads["bl3"]] == c2[beads["bl2"]] and rs[0]["proposed"]["grade"] == "recommend"
            assert {r["feature_type"] for r in rs} == {"BEAD_DEPTH", "BEAD_POS_U", "BEAD_POS_V", "BEAD_WIDTH"}
    assert matched == 2


# ------------------------------------------------------------------ selftest / kernel
def test_shell_selftest_numbers_only(shell_golden, tmp_path):
    g = shell_golden
    from data.make_synthetic_shell import make_step, variant

    vstep = make_step(tmp_path, variant(g["spec"], "B1", depth=4.4), "variant.step")
    vv = _write(tmp_path, "vv.json", {"schema_version": 1, "values": {g["names"]["B1"]["BEAD_DEPTH"]: 4.4}})
    code, out = run_cli("shell", "selftest", "--cad", g["step"], "--assem-dir", g["assem"], "--out-dir", tmp_path / "st", "--variant-cad", vstep, "--variant-values", vv,
                        "--envelope-params", g["names"]["B1"]["BEAD_DEPTH"], "--envelope-steps", "5", "--envelope-pos-steps", "1")
    assert code == 0, out
    r = json.loads((tmp_path / "st" / "selftest_report.json").read_text())
    assert r["kind"] == "shell" and all(s["exit_code"] == 0 for s in r["stages"].values()), r["stages"]
    assert r["tag"]["unmatched"] == 0 and r["tag"]["match_ratio"] == 1.0 and r["fixed"]["total"] == g["truth"]["fixed"]["total"]
    assert r["extract"]["beads"] == 5 and r["roundtrip"] == {"writer_byte_identical": True, "nominal_files_written": 0}
    assert r["nominal_check"]["status"] == "PASS" and r["variant"]["max_distance_mm"] <= 0.01 and r["variant"]["max_area_rel"] <= 1e-3
    assert r["envelope"][0]["last_ok"] == {"+": 5.0, "-": 5.0}
    text = (tmp_path / "st" / "selftest_report.json").read_text() + (tmp_path / "st" / "selftest_report.md").read_text()
    assert "2000001" not in text and "chassis_rear" not in text.lower().replace("chassis_rear_bead", "")  # no ids / CAD names besides parameter names


def test_kernel_sheet_neutral_types(shell_golden):
    from paicad.kernel import SurfaceEdit, load_sheets, rebuild_sheet

    _, bodies = load_sheets(shell_golden["step"])
    b = bodies[0]
    topo = b.topology()
    pts = topo.vertices[:3]
    res = [b.summary(), topo, b.project_to_edge(1, pts), b.project_to_face(1, pts), b.eval_face(1, np.array([[0.5, 0.5]])), b.eval_edge(1, np.array([0.0, 1.0])),
           b.surface_params(2), b.distance(pts), b.points_inside(pts)]
    nb = rebuild_sheet(b, {}, {}, {})
    assert nb.__class__.__module__ == "paicad.kernel.occ_sheet" and isinstance(SurfaceEdit(), SurfaceEdit)
    res += [nb.summary(), nb.topology()]

    def walk(o, depth=0):
        assert not type(o).__module__.startswith("OCP"), type(o)
        if depth > 6:
            return
        if isinstance(o, (list, tuple)):
            for x in o:
                walk(x, depth + 1)
        elif isinstance(o, dict):
            for x in o.values():
                walk(x, depth + 1)
        elif hasattr(o, "__dataclass_fields__"):
            for k in o.__dataclass_fields__:
                walk(getattr(o, k), depth + 1)

    walk(res)
    assert b.summary().volume == 0.0 and b.summary().extra["free_edges"] == 18
