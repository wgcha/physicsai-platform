"""paicad 0.5.0: envelope ``edge_ratio`` column / schema 2, strict options (unknown keys, ranges),
``QUALITY_METRIC_NONFINITE`` warning, failure paths without earlier tests (GEOM_MORPH_FAILED,
GEOM_INC_FORMAT, GEOM_EXTRACT_EMPTY) and the committed golden G1 envelope report."""

from __future__ import annotations

import re

import numpy as np
import pytest
from conftest import run_cli
from paicad import envreport, options, quality
from paicad.common import CODE_EXIT, EXIT_CHECK, EXIT_EXTRACT_EMPTY, EXIT_INTERNAL, PaicadError
from paicad.mesh import radioss
from paicad.morph import MorphFailed, solve_interior, write_morphed
from paicad.sweep import CSV_COLUMNS, ENVELOPE_SCHEMA_VERSION
from test_stage2 import load, run_check, run_morph, run_update, write_json


@pytest.fixture(scope="module")
def nominal_update(golden, tmp_path_factory):
    out = tmp_path_factory.mktemp("v050") / "update_nominal"
    code, text, vp = run_update(golden, out, {})
    assert code == 0, text
    return out, vp


# ------------------------------------------------------------- 1. envelope column name
def test_envelope_columns_use_check_json_name():
    assert "edge_ratio" in CSV_COLUMNS and "min_edge_ratio" not in CSV_COLUMNS
    assert ENVELOPE_SCHEMA_VERSION == 2
    row = {"status": "OK", "edge_ratio": 0.4, "min_stretch": 0.9}
    m = envreport.margins(row, options.load(None))
    assert m["edge_ratio"] == pytest.approx(0.5) and "min_edge_ratio" not in m


# ------------------------------------------------------------- 2. options
def _load(tmp_path, body):
    return options.load(write_json(tmp_path / "o.json", {"schema_version": 1, **body}))


@pytest.mark.parametrize(
    "body,key",
    [
        ({"qualty": {"min_stretch": 0.2}}, "qualty"),
        ({"quality": {"min_strech": 0.2}}, "quality.min_strech"),
        ({"morph": {"poison": 0.3}}, "morph.poison"),
        ({"tag": {"tol_abs": 0.1}, "extra": 1}, "tag.tol_abs"),
    ],
)
def test_options_reject_unknown_keys(tmp_path, body, key):
    with pytest.raises(PaicadError) as e:
        _load(tmp_path, body)
    assert e.value.code == "GEOM_INPUT_INVALID" and "unknown keys" in e.value.message and key in e.value.message


def test_options_accept_metadata_and_free_maps(tmp_path):
    o = _load(tmp_path, {"engine": "native", "engine_version": "0.5.0", "thickness_ref_overrides": {"CUSH_L_THK_1": "F7"}})
    assert o["thickness_ref_overrides"] == {"CUSH_L_THK_1": "F7"} and "engine" not in o
    # contract section 4.9 spells position_range_mm at the top level: same as extract.position_range_mm
    o = _load(tmp_path, {"position_range_mm": 3.0})
    assert o["extract"]["position_range_mm"] == 3.0 and "position_range_mm" not in o
    with pytest.raises(PaicadError):
        _load(tmp_path, {"position_range_mm": 3.0, "extract": {"position_range_mm": 4.0}})
    with pytest.raises(PaicadError) as e:
        _load(tmp_path, {"quality": 1})
    assert "quality must be an object" in e.value.message


@pytest.mark.parametrize("me,ok", [(None, True), (0.5, True), (0, False), (0.0, False), (-1, False), (float("inf"), False), (True, False)])
def test_options_min_edge_mm_null_or_positive(tmp_path, me, ok):
    body = {"quality": {"min_edge_mm": me}}  # inf is written as Infinity and read back as inf
    if ok:
        assert _load(tmp_path, body)["quality"]["min_edge_mm"] == me
    else:
        with pytest.raises(PaicadError) as e:
            _load(tmp_path, body)
        assert "quality.min_edge_mm must be null or a finite number > 0" in e.value.message


@pytest.mark.parametrize("nu,ok", [(0, True), (0.0, True), (0.3, True), (0.499, True), (0.5, False), (-0.1, False), (0.7, False), ("0.3", False)])
def test_options_poisson_range(tmp_path, nu, ok):
    body = {"morph": {"poisson": nu}}
    if ok:
        assert _load(tmp_path, body)["morph"]["poisson"] == nu
    else:
        with pytest.raises(PaicadError) as e:
            _load(tmp_path, body)
        assert e.value.code == "GEOM_INPUT_INVALID" and "morph.poisson must be in [0, 0.5)" in e.value.message


def test_cli_rejects_unknown_option_key(golden, nominal_update, tmp_path):
    upd, _ = nominal_update
    opts = write_json(tmp_path / "o.json", {"schema_version": 1, "quality": {"min_edge_ratoi": 0.5}})
    code, text = run_morph(golden, upd, tmp_path / "m", "--options", opts)
    assert code == CODE_EXIT["GEOM_INPUT_INVALID"] and "PAICAD RESULT FAIL GEOM_INPUT_INVALID" in text
    d = load(tmp_path / "m" / "morph.json")
    assert d["code"] == "GEOM_INPUT_INVALID" and "quality.min_edge_ratoi" in d["message"]


# ------------------------------------------------------------- 3. QUALITY_METRIC_NONFINITE
def test_quality_nonfinite_metric_is_null():
    q = options.load(None)["quality"]
    x = np.array([[0, 0, 0], [10, 0, 0], [5, 8.66, 0], [5, 2.89, 8.16]], dtype=float)
    collapsed = np.repeat(x[:1], 4, axis=0)
    with np.errstate(all="ignore"):
        r = quality.evaluate(x, collapsed, np.array([[0, 1, 2, 3]]), np.array([[0, 1, 2]]), q, np.array([0]))
    assert r.report["max_aspect"] is None and quality.nonfinite_metrics(r.report) == ["max_aspect"]
    assert quality.nonfinite_metrics(quality.evaluate(x, x, np.array([[0, 1, 2, 3]]), np.array([[0, 1, 2]]), q, np.array([0])).report) == []


def test_check_json_warns_on_nonfinite_metric(golden, nominal_update, tmp_path, monkeypatch):
    upd, vp = nominal_update
    code, text = run_morph(golden, upd, tmp_path / "m")
    assert code == 0, text
    code, text = run_check(golden, upd, tmp_path / "m", vp, tmp_path / "c0", tmp_path / "inc0" / "x.inc")
    assert code == 0, text
    assert not [w for w in load(tmp_path / "c0" / "check.json")["warnings"] if w["code"] == "QUALITY_METRIC_NONFINITE"]
    real = quality.evaluate

    def degenerate(*a, **k):  # as if every boundary triangle were degenerate: aspect has no finite value
        r = real(*a, **k)
        r.report["max_aspect"] = None
        return r

    monkeypatch.setattr(quality, "evaluate", degenerate)
    code, text = run_check(golden, upd, tmp_path / "m", vp, tmp_path / "c1", tmp_path / "inc1" / "x.inc")
    d = load(tmp_path / "c1" / "check.json")
    w = [w for w in d["warnings"] if w["code"] == "QUALITY_METRIC_NONFINITE"]
    assert len(w) == 1 and w[0]["metrics"] == ["max_aspect"] and "max_aspect" in w[0]["message"]
    assert d["checks"]["quality"]["max_aspect"] is None


# ------------------------------------------------------------- 4. failure paths
def test_morph_failed_orphan_free_node():
    xyz = np.array([[0, 0, 0], [10, 0, 0], [0, 10, 0], [0, 0, 10], [50, 50, 50]], dtype=float)
    fixed = np.array([True, True, True, False, False])  # node 4 belongs to no element
    u = np.zeros((5, 3))
    u[1, 0] = 1.0
    with pytest.raises(MorphFailed) as e:
        solve_interior(xyz, np.array([[0, 1, 2, 3]]), fixed, u, options.load(None))
    assert e.value.code == "GEOM_MORPH_FAILED" and e.value.exit_code == EXIT_CHECK


def test_morph_failed_cli_report(golden, tmp_path, monkeypatch):
    import paicad.morph as morph_mod

    code, text, _ = run_update(golden, tmp_path / "u", {"CUSH_L_THK_3": 22.0})
    assert code == 0, text
    monkeypatch.setattr(morph_mod, "SPSOLVE_MAX_DOF", 0)  # no direct-solver fallback
    opts = write_json(tmp_path / "o.json", {"schema_version": 1, "morph": {"solver_maxiter": 1, "solver_rtol": 1e-14}})
    code, text = run_morph(golden, tmp_path / "u", tmp_path / "m", "--options", opts)
    assert code == EXIT_CHECK and "PAICAD RESULT FAIL GEOM_MORPH_FAILED morph.json" in text, text
    d = load(tmp_path / "m" / "morph.json")
    assert d["status"] == "FAIL" and d["code"] == "GEOM_MORPH_FAILED" and d["category"] == "QUALITY" and "did not converge" in d["message"]
    assert not (tmp_path / "m" / "morphed.inc").exists()


_NARROW = b"""/NODE
1 0.0 0.0 0.0
2 1.5 2.5 3.5
/TETRA4/1
         1         1         2         1         2
"""


def test_inc_format_value_does_not_fit():
    with pytest.raises(PaicadError) as e:
        radioss._fmt(123456.789, 4)
    assert e.value.code == "GEOM_INC_FORMAT" and e.value.exit_code == EXIT_INTERNAL
    # free-format node lines: 4-byte fields cannot hold the new coordinate
    with pytest.raises(PaicadError) as e:
        radioss.rewrite_nodes(_NARROW, {2: (1.5, 2.5, 3.123456789)})
    assert e.value.code == "GEOM_INC_FORMAT"
    # unchanged nodes are copied verbatim (no formatting attempted)
    assert radioss.rewrite_nodes(_NARROW, {2: (1.5, 2.5, 3.5)}) == _NARROW


def test_inc_format_cli(golden, tmp_path):
    """A baseline written with 2-decimal free-format coordinates cannot carry morphed values."""
    src = golden["baseline"].read_bytes().decode("latin-1")
    out, in_node = [], False
    for line in src.splitlines(keepends=True):
        if line.startswith("/"):
            in_node = line.strip().upper() == "/NODE"
        elif in_node and line.strip() and not line.startswith("#"):
            t = line.split()
            line = f"{int(t[0])} {float(t[1]):.2f} {float(t[2]):.2f} {float(t[3]):.2f}\n"
        out.append(line)
    narrow = tmp_path / golden["baseline"].name
    narrow.write_bytes("".join(out).encode("latin-1"))
    code, text, _ = run_update(golden, tmp_path / "u", {"CUSH_L_RIB_H_1": 16.3})
    assert code == 0, text
    code, text = run_cli(
        "morph", "--baseline-inc", narrow, "--tag-dir", golden["tag_dir"], "--features", golden["features_path"],
        "--update-dir", tmp_path / "u", "--out-dir", tmp_path / "m",
    )
    assert code == EXIT_INTERNAL and "PAICAD RESULT FAIL GEOM_INC_FORMAT" in text, text
    assert load(tmp_path / "m" / "morph.json")["code"] == "GEOM_INC_FORMAT"
    assert not (tmp_path / "m" / "morphed.inc").exists()


def test_extract_empty_on_featureless_body(tmp_path):
    from build123d import Sphere, export_step

    step = tmp_path / "sphere.step"
    export_step(Sphere(20.0), str(step))
    code, text = run_cli("extract", "--cad", step, "--out-dir", tmp_path / "ex", "--no-png")
    assert code == EXIT_EXTRACT_EMPTY and "PAICAD RESULT FAIL GEOM_EXTRACT_EMPTY parameter_features.json" in text, text
    d = load(tmp_path / "ex" / "parameter_features.json")
    assert d["features"] == [] and d["groups"] == [] and d["engine"] == "native"
    assert not (tmp_path / "ex" / "parameter_extracted.xml").exists()


# ------------------------------------------------------------- 5. golden G1 envelope report
def test_golden_report_committed_and_well_formed():
    from data.make_envelope_report import GOLDEN_DIR, REPORT_FILES

    md, csv_text = ((GOLDEN_DIR / n).read_text(encoding="utf-8") for n in REPORT_FILES)
    assert md.startswith("# Morphing envelope report") and "- schema_version: 2" in md
    assert re.search(r"^- engine_version: \d+\.\d+\.\d+$", md, re.M)
    assert csv_text.splitlines()[0] == ",".join(envreport.REPORT_COLUMNS)
    assert "min_edge_ratio (" not in md  # limit metric name follows the column name


def test_golden_report_regenerates_byte_identical(tmp_path):
    """Full default sweep of the virtual cushion (about 2 min): committed report == regenerated, apart from
    the engine_version / sweep_id header lines (0.6.0: a version bump alone needs no regeneration)."""
    import paicad
    from data.make_envelope_report import GOLDEN_DIR, REPORT_FILES, generate, normalize_report

    committed = {n: (GOLDEN_DIR / n).read_bytes() for n in REPORT_FILES}
    regenerated = generate(tmp_path / "g1")
    assert f"- engine_version: {paicad.__version__}\n".encode() in regenerated["report_envelope.md"]
    for n in REPORT_FILES:
        assert normalize_report(regenerated[n]).decode() == normalize_report(committed[n]).decode(), n
