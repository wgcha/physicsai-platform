"""paicad 0.7.0: ``props`` /PART card ``Thick`` override (PROP_OVERRIDDEN_BY_PART, contract section 11.1)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import run_cli
from paicad.common import EXIT_CHECK
from paicad.props import part_thickness, scan_tree


def load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


@pytest.fixture()
def shell_po(tmp_path):
    from data.make_synthetic import write_shell_assembly

    # PART 10 (PROP 1): fixed-width Thick 1.1 in columns 31-50; PART 12 (PROP 2, shared): explicit Thick 0 (no override)
    s = write_shell_assembly(tmp_path / "assem", part_thick={10: f"{0:10d}{1.1:20.4f}", 12: f"{0:10d}{0.0:20.4f}"})
    code, text = run_cli("props", "scan", "--assem-dir", s["folder"], "--out-dir", tmp_path / "scan")
    assert code == 0, text
    s["props_json"] = tmp_path / "scan" / "props.json"
    s["props"] = load(s["props_json"])
    s["tmp"] = tmp_path
    return s


def _apply(s, values: dict, out: str):
    vp = s["tmp"] / f"{out}_values.json"
    vp.write_text(json.dumps({"schema_version": 1, "values": values}), encoding="utf-8")
    code, text = run_cli("props", "apply", "--assem-dir", s["folder"], "--values", vp, "--props", s["props_json"], "--out-dir", s["tmp"] / out)
    rep = s["tmp"] / out / "props_apply.json"
    return code, text, (load(rep) if rep.is_file() else None)


def test_scan_marks_part_overrides(shell_po):
    rows = {r["id"]: r for r in shell_po["props"]["props"]}
    assert rows[1]["part_overrides"] == [{"id": 10, "title": "BRACKET", "thickness": 1.1}] and rows[1]["selectable"] is False
    assert rows[2]["part_overrides"] == [] and rows[2]["selectable"] is True  # Thick 0 = take the PROP
    assert all("part_overrides" in r for r in rows.values())
    w = [x for x in shell_po["props"]["warnings"] if x["code"] == "PROP_OVERRIDDEN_BY_PART"]
    assert len(w) == 1 and w[0]["prop"] == 1 and w[0]["parts"] == [10]


def test_scan_without_part_thick_unchanged(tmp_path):
    from data.make_synthetic import write_shell_assembly

    s = write_shell_assembly(tmp_path / "a")
    props, _ = scan_tree(s["folder"])
    assert all(pd.part_overrides == [] for pd in props.values())


def test_apply_overridden_by_part_fails(shell_po):
    before = {p.relative_to(shell_po["folder"]).as_posix(): p.read_bytes() for p in shell_po["folder"].rglob("*") if p.is_file()}
    code, text, d = _apply(shell_po, {"BRACKET_SHELL_T": 1.3}, "a1")
    assert code == EXIT_CHECK and "PAICAD RESULT FAIL PROP_OVERRIDDEN_BY_PART props_apply.json" in text, text
    assert d["status"] == "FAIL" and d["code"] == "PROP_OVERRIDDEN_BY_PART" and d["category"] == "PROP" and d["files"] == []
    assert "10" in d["message"]
    after = {p.relative_to(shell_po["folder"]).as_posix(): p.read_bytes() for p in shell_po["folder"].rglob("*") if p.is_file()}
    assert after == before


def test_apply_unchanged_value_with_part_override_is_ok(shell_po):
    # same value as the PROP -> nothing to change -> no failure (like the element override rule)
    code, text, d = _apply(shell_po, {"BRACKET_SHELL_T": 1.2}, "a2")
    assert code == 0 and d["status"] == "OK", text


def test_apply_other_prop_not_affected(shell_po):
    code, text, d = _apply(shell_po, {"COVER_2_SHELL_T": 0.9}, "a3")
    assert code == 0 and d["status"] == "OK", text


@pytest.mark.parametrize(
    "line,expected",
    [
        (f"{1:10d}{1:10d}", 0.0),
        (f"{1:10d}{1:10d}{0:10d}{2.5:20.4f}", 2.5),
        (f"{1:10d}{1:10d}{0:10d}{'':20s}", 0.0),
        ("1 1 0 0.75", 0.75),
        ("1, 1, 0, 0.0", 0.0),
        ("1 1", 0.0),
    ],
)
def test_part_thickness_field(line, expected):
    assert part_thickness(line) == expected
