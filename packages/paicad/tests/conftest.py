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
