"""Shared fixtures: the development golden set is generated once per session (nothing committed)."""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path

import pytest
from paicad.cli import main

PKG = Path(__file__).resolve().parents[1]


def run_cli(*argv: str) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = main([str(a) for a in argv])
    return code, buf.getvalue()


@pytest.fixture(scope="session")
def golden(tmp_path_factory):
    from data.make_synthetic import make_all

    root = tmp_path_factory.mktemp("golden")
    g = make_all(root)
    g["root"] = root
    ex = root / "out" / "extract"
    code, out = run_cli("extract", "--cad", g["step"], "--out-dir", ex, "--renum-csv", g["renum"])
    assert code == 0, out
    g["extract_dir"] = ex
    g["features_path"] = ex / "parameter_features.json"
    g["features"] = json.loads(g["features_path"].read_text(encoding="utf-8"))
    tg = root / "out" / "tag"
    code, out = run_cli(
        "tag", "--cad", g["step"], "--features", g["features_path"], "--baseline-inc", g["baseline"],
        "--renum-csv", g["renum"], "--assem-dir", g["assem"], "--out-dir", tg,
    )
    assert code == 0, out
    g["tag_dir"] = tg
    g["tag"] = json.loads((tg / "tag.json").read_text(encoding="utf-8"))
    return g


@pytest.fixture(scope="session")
def shell_golden(tmp_path_factory):
    """Virtual sheet-metal golden SM1 (shell-morph section 9.1) prepared like a native shell set:
    fixed-scan -> extract (with PNG) -> tag -> nominal update."""
    from data.make_synthetic_shell import make_all

    root = tmp_path_factory.mktemp("shell_golden")
    g = make_all(root / "sm1")
    out = root / "out"
    fx, ex, tg, up0 = out / "fixed", out / "extract", out / "tag", out / "update0"
    code, log = run_cli("shell", "fixed-scan", "--assem-dir", g["assem"], "--out-dir", fx, "--parts", "2001")
    assert code == 0, log
    code, log = run_cli("shell", "extract", "--cad", g["step"], "--assem-dir", g["assem"], "--out-dir", ex)
    assert code == 0, log
    feats = ex / "shell_features.json"
    code, log = run_cli("shell", "tag", "--cad", g["step"], "--features", feats, "--assem-dir", g["assem"], "--fixed-dir", fx, "--out-dir", tg)
    assert code == 0, log
    v0 = root / "values_nominal.json"
    v0.write_text('{"schema_version": 1, "values": {}}', encoding="utf-8")
    code, log = run_cli("shell", "update", "--cad", g["step"], "--features", feats, "--values", v0, "--fixed-dir", fx, "--out-dir", up0)
    assert code == 0, log
    doc = json.loads(feats.read_text(encoding="utf-8"))
    # truth bead name (B1..B5) -> feature names, by bead center
    names = {}
    for tb in g["truth"]["beads"]:
        b = min(doc["beads"], key=lambda x: sum((a - c) ** 2 for a, c in zip(x["center"], tb["center"])))
        names[tb["name"]] = {"id": b["id"], **{f["type"]: f["name"] for f in doc["features"] if f["bead"] == b["id"]}}
    g.update(root=root, out=out, fixed_dir=fx, extract_dir=ex, features_path=feats, features=doc, tag_dir=tg, update0=up0, values0=v0, names=names,
             scan=json.loads((fx / "shell_scan.json").read_text(encoding="utf-8")), tag=json.loads((tg / "shell_tag.json").read_text(encoding="utf-8")))
    return g
