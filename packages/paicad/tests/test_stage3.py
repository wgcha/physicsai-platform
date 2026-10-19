"""Stage 3 (contract section 9): relative quality criteria, hole position reference, ``paicad run``,
solver writer registry, envelope report, ``paicad selftest`` (minimal kit) on the development golden."""

from __future__ import annotations

import csv
import json

import numpy as np
import paicad
import pytest
from conftest import run_cli
from paicad import options, quality
from paicad.common import PaicadError
from test_stage2 import load, run_check, run_morph, run_update, write_json


def run_all(g, out, values, *extra):
    out.mkdir(parents=True, exist_ok=True)
    vp = write_json(out / "values.json", {"schema_version": 1, "values": values})
    code, text = run_cli(
        "run", "--cad", g["step"], "--features", g["features_path"], "--values", vp, "--baseline-inc", g["baseline"], "--tag-dir", g["tag_dir"],
        "--assem-dir", g["assem"], "--renum-csv", g["renum"], "--update-dir", out / "u", "--morph-dir", out / "m", "--check-dir", out / "c",
        "--out-inc", out / "inc" / g["baseline"].name, *extra,
    )
    return code, text


# ------------------------------------------------------------- A. quality criteria
def test_quality_option_defaults_and_validation(tmp_path):
    q = options.load(None)["quality"]
    assert q == {"min_stretch": 0.1, "max_aspect": 10.0, "min_edge_mm": None, "min_edge_ratio": 0.8, "dt_ratio_min": 0.8, "relative_to_baseline": True}
    assert options.load(None)["position_ref"] == "nearest_fixed"
    ok = write_json(tmp_path / "ok.json", {"schema_version": 1, "quality": {"min_edge_mm": 1.0}, "position_ref": "proportional"})
    assert options.load(ok)["quality"]["min_edge_mm"] == 1.0
    for bad in ({"quality": {"min_edge_ratio": 0}}, {"quality": {"dt_ratio_min": 1.5}}, {"quality": {"min_edge_mm": -1}}, {"quality": {"min_stretch": 0}}, {"position_ref": "bbox"}):
        p = write_json(tmp_path / "bad.json", {"schema_version": 1, **bad})
        with pytest.raises(PaicadError) as e:
            options.load(p)
        assert e.value.code == "GEOM_INPUT_INVALID"


def _tet(scale_z=1.0, shift=0.0):
    x = np.array([[0, 0, 0], [10, 0, 0], [5, 8.66, 0], [5, 2.89, 8.16 * scale_z]], dtype=float)
    return x + shift


def test_quality_relative_edge_and_time_step():
    q = options.load(None)["quality"]
    tets = np.array([[0, 1, 2, 3], [4, 5, 6, 7]])
    skin = np.array([[0, 1, 2], [4, 5, 6]])
    base = np.vstack([_tet(), _tet(shift=20.0)])
    r = quality.evaluate(base, base, tets, skin, q, np.array([0, 1]))
    assert r.status == "PASS" and r.report["edge_ratio"] == 1.0 and r.report["dt_ratio"] == 1.0 and r.baseline_ok
    # flatten the second tetra: its smallest altitude (time step) drops to 70 %, edges stay >= 80 %
    new = np.vstack([_tet(), _tet(scale_z=0.7, shift=20.0)])
    r = quality.evaluate(base, new, tets, skin, q, np.array([0, 1]))
    assert r.status == "FAIL" and r.report["dt_ratio"] == pytest.approx(0.7, abs=1e-3) and r.report["edge_ratio"] >= 0.8
    assert "time step ratio" in r.message and "min edge ratio" not in r.message
    # the ratio is per part: a part whose elements are all smaller than another part's keeps its own reference
    small = np.vstack([_tet(), 0.5 * _tet(shift=40.0)])
    r = quality.evaluate(small, small, tets, skin, q, np.array([0, 1]))
    assert r.status == "PASS" and r.report["dt_ratio"] == 1.0
    # optional absolute floor; the baseline is judged only on absolute shape criteria
    r = quality.evaluate(base, base, tets, skin, dict(q, min_edge_mm=20.0, relative_to_baseline=False))
    assert r.status == "FAIL" and r.baseline_ok
    flat = np.vstack([_tet(), _tet(scale_z=0.3, shift=20.0)])
    r = quality.evaluate(flat, flat, tets, skin, dict(q, min_stretch=0.9))
    assert not r.baseline_ok and r.report["baseline_status"] == "FAIL" and r.status == "PASS"  # relative: not worse than the baseline


def test_golden_baseline_passes_default_check_and_stricter_absolute_warns(golden, tmp_path):
    out = tmp_path / "r"
    code, text = run_all(golden, out, {})
    assert code == 0, text
    d = load(out / "c" / "check.json")
    q = d["checks"]["quality"]
    assert d["status"] == "PASS" and q["baseline_status"] == "PASS" and d["warnings"] == []
    assert q["baseline_min_edge_mm"] < 1.0  # the old absolute 1 mm floor failed this baseline
    assert d["options"]["quality"]["min_edge_mm"] is None and q["edge_ratio"] == 1.0 and q["dt_ratio"] == 1.0
    upd, mor, vp = out / "u", out / "m", out / "values.json"
    # min edge floor above the baseline: no BASELINE_QUALITY_BELOW (relative criteria absorb it)
    o1 = write_json(tmp_path / "o1.json", {"schema_version": 1, "quality": {"min_edge_mm": 0.9}})
    code, _ = run_check(golden, upd, mor, vp, tmp_path / "c1", tmp_path / "i1.inc", "--options", o1)
    d1 = load(tmp_path / "c1" / "check.json")
    assert code == 0 and d1["checks"]["quality"]["baseline_status"] == "PASS" and d1["warnings"] == []
    # stricter absolute aspect than the baseline: warning only
    o2 = write_json(tmp_path / "o2.json", {"schema_version": 1, "quality": {"max_aspect": 2.0}})
    code, _ = run_check(golden, upd, mor, vp, tmp_path / "c2", tmp_path / "i2.inc", "--options", o2)
    d2 = load(tmp_path / "c2" / "check.json")
    assert code == 0 and d2["checks"]["quality"]["baseline_status"] == "FAIL" and [w["code"] for w in d2["warnings"]] == ["BASELINE_QUALITY_BELOW"]


# ------------------------------------------------------------- B. hole position reference
def test_body_length_change_keeps_hole_at_nearest_fixed_face(golden, tmp_path):
    """Regression: L +10 % moved the mirrored body's hole (measured from the moving bbox minimum) into a rib -> CAD_FAILED."""
    code, text = run_all(golden, tmp_path / "r", {"CUSH_L_THK_2": 132.0})
    assert code == 0, text
    u = load(tmp_path / "r" / "u" / "update.json")
    pos = {p["name"]: p for p in u["positions"]}
    assert pos["CUSH_R_HOLE_U_1"]["mode"] == "nearest_fixed" and pos["CUSH_R_HOLE_U_1"]["expected_measured"] == pytest.approx(120.0)
    assert pos["CUSH_L_HOLE_U_1"]["expected_measured"] == pytest.approx(12.0)
    moved_r = {a["name"]: a for a in u["applied"]}["CUSH_L_THK_2"]["moved"][0]
    assert pos["CUSH_R_HOLE_U_1"]["ref_face"] != moved_r
    items = {i["name"]: i for i in load(tmp_path / "r" / "c" / "check.json")["checks"]["param"]["items"]}
    assert items["CUSH_R_HOLE_U_1"]["expected"] == pytest.approx(120.0) and abs(items["CUSH_R_HOLE_U_1"]["measured"] - 120.0) < 0.05
    # proportional reference: the position scales with the body length
    o = write_json(tmp_path / "o.json", {"schema_version": 1, "position_ref": "proportional"})
    code, text, _ = run_update(golden, tmp_path / "p", {"CUSH_L_THK_2": 132.0}, "--options", o)
    assert code == 0, text
    pos = {p["name"]: p for p in load(tmp_path / "p" / "update.json")["positions"]}
    assert pos["CUSH_L_HOLE_U_1"]["mode"] == "proportional" and pos["CUSH_L_HOLE_U_1"]["expected_measured"] == pytest.approx(13.2, abs=1e-6)
    assert pos["CUSH_R_HOLE_U_1"]["expected_measured"] == pytest.approx(118.8, abs=1e-6)


def test_nearest_fixed_tie_prefers_larger_area():
    from paicad.kernel.base import FaceData, Topology
    from paicad.update import nearest_fixed_face

    def plane(i, x, area, n=-1.0):
        return FaceData(i, "PLANE", area, np.array([x, 0.0, 0.0]), np.zeros(6), (), (), (), (0.0, 1.0, 0.0, 1.0), normal=np.array([n, 0.0, 0.0]))

    faces = (plane(1, 0.0, 10.0), plane(2, 20.0, 50.0, 1.0), plane(3, 30.0, 5.0, 1.0))
    topo = Topology(faces=faces, edges=(), vertices=np.zeros((0, 3)))
    assert nearest_fixed_face(topo, 0, 10.0, {}) == 2  # tie at 10 mm: larger area
    assert nearest_fixed_face(topo, 0, 10.0, {2: np.array([1.0, 0, 0])}) == 1  # F2 moves in this sample
    assert nearest_fixed_face(topo, 0, 10.0, {1: np.array([1.0, 0, 0]), 2: np.array([1.0, 0, 0]), 3: np.array([0, 0, 1.0])}) == 3  # in-plane move = fixed


# ------------------------------------------------------------- C. paicad run
def test_run_pass_writes_every_stage(golden, tmp_path):
    out = tmp_path / "r"
    code, text = run_all(golden, out, {"CUSH_L_RIB_H_1": 16.0})
    assert code == 0 and text.strip().splitlines()[-1] == "PAICAD RESULT PASS - run.json", text
    r = load(out / "c" / "run.json")
    assert r["status"] == "PASS" and r["skip"] is None and r["engine_version"] == paicad.__version__ and r["solver"] == "radioss"
    assert [s["step"] for s in r["stages"]] == ["update", "morph", "check"] and all(s["exit_code"] == 0 for s in r["stages"])
    assert (out / "u" / "sample.brep").is_file() and (out / "m" / "morphed.inc").is_file() and (out / "inc" / golden["baseline"].name).is_file()
    assert (out / "inc" / golden["baseline"].name).read_bytes() == (out / "m" / "morphed.inc").read_bytes()
    assert all((out / d / "paicad.log").is_file() for d in ("u", "m", "c"))
    # rerun into the same folders: refused before any work
    code, text = run_all(golden, out, {"CUSH_L_RIB_H_1": 16.0})
    assert code == 3 and "GEOM_OUTPUT_EXISTS" in text


@pytest.mark.parametrize(
    "values,step,code_name,exit_code",
    [
        ({"CUSH_L_POCKET_D_1": 25.0}, "update", "GEOM_FEATURE_COLLISION", 10),  # 0.4.0 pre-check
        ({"CUSH_L_RIB_H_1": 4.0, "CUSH_L_THK_3": 12.5}, "check", "GEOM_QUALITY", 11),
    ],
)
def test_run_failure_stops_chain_with_skip_reason(golden, tmp_path, values, step, code_name, exit_code):
    out = tmp_path / "r"
    code, text = run_all(golden, out, values)
    assert code == exit_code and text.strip().splitlines()[-1] == f"PAICAD RESULT FAIL {code_name} run.json", text
    r = load(out / "c" / "run.json")
    assert (r["status"], r["code"], r["skip"]["step"], r["skip"]["code"]) == ("FAIL", code_name, step, code_name)
    assert r["skip"]["category"] in ("CAD_FAILED", "QUALITY") and r["skip"]["message"] and r["out_inc"] is None
    assert r["skip"]["report"].endswith(f"{step}.json") and r["stages"][-1]["step"] == step
    assert not (out / "inc" / golden["baseline"].name).exists()
    if step == "update":
        assert not (out / "m" / "morph.json").exists() and not (out / "c" / "check.json").exists()


def test_run_unknown_solver_and_writer_registry(golden, tmp_path):
    from paicad.writers import available, get_writer

    assert available() == ["radioss"] and get_writer(None).name == "radioss" and get_writer("radioss").output_name == "morphed.inc"
    with pytest.raises(PaicadError):
        get_writer("lsdyna")
    code, text = run_all(golden, tmp_path / "r", {}, "--solver", "lsdyna")
    assert code == 3 and "GEOM_INPUT_INVALID" in text
    assert load(tmp_path / "r" / "c" / "run.json")["code"] == "GEOM_INPUT_INVALID"
    assert not (tmp_path / "r" / "u" / "update.json").exists()


def test_check_deviation_and_param_mismatch_codes(golden, tmp_path):
    """Fifth failure type (DEVIATION): nominal mesh judged against a changed sample B-rep."""
    nom = tmp_path / "nom"
    code, _, _ = run_update(golden, nom, {})
    assert code == 0 and run_morph(golden, nom, tmp_path / "m")[0] == 0
    upd = tmp_path / "u"
    code, _, vp = run_update(golden, upd, {"CUSH_L_RIB_H_1": 17.0})
    assert code == 0
    code, text = run_check(golden, upd, tmp_path / "m", vp, tmp_path / "c", tmp_path / "o.inc")
    d = load(tmp_path / "c" / "check.json")
    assert code == 11 and d["code"] == "GEOM_DEVIATION" and d["category"] == "DEVIATION" and "(+1 more)" in d["message"]
    assert d["checks"]["param"]["status"] == "FAIL" and not (tmp_path / "o.inc").exists()


# ------------------------------------------------------------- envelope report
def test_sweep_writes_envelope_report(golden, tmp_path):
    code, text, _ = run_update(golden, tmp_path / "u", {})
    assert code == 0
    outs = []
    for k in (1, 2):
        code, text = run_morph(golden, tmp_path / "u", tmp_path / f"e{k}", "--sweep", "--params", "CUSH_L_THK_2,CUSH_L_HOLE_U_1", "--steps", "10", "--pos-steps", "2")
        assert code == 0, text
        outs.append([(tmp_path / f"e{k}" / n).read_bytes() for n in ("report_envelope.md", "report_envelope.csv")])
    assert outs[0] == outs[1]
    env = load(tmp_path / "e1" / "envelope.json")
    rows = env["rows"]
    thk = {r["direction"]: r for r in rows if r["param"] == "CUSH_L_THK_2"}
    assert thk["+"]["status"] == "OK" and thk["-"]["fail_code"] != "GEOM_CAD_FAILED"  # 0.2.0: +10 % CAD_FAILED (hole into rib)
    assert all(r["dt_ratio"] is not None for r in rows)
    with open(tmp_path / "e1" / "report_envelope.csv", newline="") as f:
        table = list(csv.DictReader(f))
    assert [t["param"] for t in table] == ["CUSH_L_THK_2", "CUSH_L_HOLE_U_1"]
    assert [t["unit"] for t in table] == ["%", "mm"]
    assert {(r["param"], r["unit"], r["step"]) for r in rows} == {("CUSH_L_THK_2", "%", 10.0), ("CUSH_L_HOLE_U_1", "mm", 2.0)}
    hole = {r["direction"]: r for r in rows if r["param"] == "CUSH_L_HOLE_U_1"}
    assert hole["+"]["value"] == pytest.approx(14.0) and hole["-"]["value"] == pytest.approx(10.0) and hole["+"]["pct"] is None
    for t, s in zip(table, env["summary"]):
        assert t["last_ok_plus"] == ("10 %" if s["unit"] == "%" else "2 mm") and s["last_ok_label"]["+"] == t["last_ok_plus"]
        assert t["limit_metric_plus"] == s["limit_metric"]["+"]["metric"] and t["limit_metric_plus"]
        assert t["limit_metric_minus"] == s["limit_metric"]["-"]["metric"]
    md = (tmp_path / "e1" / "report_envelope.md").read_text(encoding="utf-8")
    assert md.startswith("# Morphing envelope report") and "CUSH_L_THK_2" in md and env["sweep_id"] in md


def test_limit_metric_picks_smallest_margin():
    from paicad.envreport import limit_metric

    opts = options.load(None)
    ok = {"status": "OK", "pct": 5.0, "value": 10.0, "fail_code": None, "min_stretch": 0.5, "max_aspect": 3.0, "edge_ratio": 0.9, "dt_ratio": 0.85,
          "boundary_dev_max_mm": 0.001, "param_remeasure_err": {"abs": 0.001, "rel": 0.0001}, "inverted_elems": 0}
    assert limit_metric([ok], opts)["metric"] == "dt_ratio"
    cad = dict(ok, status="FAIL", pct=10.0, fail_code="GEOM_CAD_FAILED", min_stretch=None, max_aspect=None, edge_ratio=None, dt_ratio=None,
               boundary_dev_max_mm=None, param_remeasure_err={"abs": None, "rel": None}, inverted_elems=None)
    lm = limit_metric([ok, cad], opts)
    assert lm == {"metric": "GEOM_CAD_FAILED", "margin": None, "at_pct": 10.0, "at": 10.0, "unit": "%", "source": "first_fail"}


# ------------------------------------------------------------- selftest kit
def _keys(obj, acc):
    if isinstance(obj, dict):
        for k, v in obj.items():
            acc.add(k)
            _keys(v, acc)
    elif isinstance(obj, list):
        for v in obj:
            _keys(v, acc)
    return acc


def test_selftest_numeric_report(golden, tmp_path):
    out = tmp_path / "kit"
    code, text = run_cli(
        "selftest", "--cad", golden["step"], "--baseline-inc", golden["baseline"], "--renum-csv", golden["renum"], "--assem-dir", golden["assem"],
        "--out-dir", out, "--envelope-params", "CUSH_L_RIB_H_1,CUSH_L_THK_2", "--envelope-steps", "5",
    )
    assert code == 0 and text.strip().splitlines()[-1] == "PAICAD RESULT OK - selftest_report.json", text
    r = load(out / "selftest_report.json")
    assert r["engine_version"] == paicad.__version__ and r["kind"] == "selftest"
    assert all(s["exit_code"] == 0 for s in r["stages"].values()) and set(r["stages"]) == {"extract", "tag", "update", "morph", "check", "envelope"}
    assert r["tag"]["match_ratio"] >= 0.98 and isinstance(r["tag"]["unclassified_total"], int)
    assert r["roundtrip"] == {"writer_byte_identical": True, "nominal_morph_byte_identical": True}
    c = r["nominal_check"]
    assert c["status"] == "PASS" and c["quality"]["baseline_status"] == "PASS" and c["quality"]["inverted"] == 0
    assert r["extract"]["parameters"] == golden["truth"]["parameters"]
    assert [p["param"] for p in r["envelope"]["params"]] == ["CUSH_L_RIB_H_1", "CUSH_L_THK_2"]
    # numbers only: no coordinates, ids or geometry arrays
    forbidden = {"xyz", "bbox", "centroid", "worst_node", "node_ids", "face_signatures", "pairs", "items", "rows", "applied"}
    assert not (_keys(r, set()) & forbidden)
    text_all = (out / "selftest_report.json").read_text() + (out / "selftest_report.md").read_text()
    assert "/NODE" not in text_all and "TETRA" not in text_all and str(golden["root"]) not in text_all
    md = (out / "selftest_report.md").read_text(encoding="utf-8")
    assert md.startswith("# paicad selftest report") and "match_ratio" in md
    assert json.loads(json.dumps(r)) == r
