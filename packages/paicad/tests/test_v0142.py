"""paicad 0.14.2 hotfix: degenerated edges in the sheet rebuild, rename retry on Windows file locks.

1. ``OccSheet.rebuilt``: an unchanged edge without a 3D curve no longer fails. A degenerated edge (sphere pole after a
   STEP round trip) is rebuilt without a 3D curve (old pcurves, same range); a regular edge stored with pcurves only gets
   a 3D curve built on an empty copy (the nominal is not modified). Synthetic sheet = SM1 + a spherical deboss
   (``SheetSpec.dimples``) - its pole edge has no 3D curve after STEP, like the esl chassis.
2. ``common.replace_retry``: ``os.replace`` retried on WinError 5/32 with a backoff, then ``GEOM_INTERNAL`` naming the
   files only; a grid cell whose folder rename stays locked is that cell's ERROR only.
Nothing generated is committed.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pytest
from conftest import run_cli
from paicad import common
from paicad.common import PaicadError, replace_retry

DIMPLE = (150.0, 200.0, 20.0, 4.0)  # x, y, sphere radius, depth: clear of beads, holes and fixed nodes of SM1
THUMB = {"schema_version": 1, "w": 160, "h": 160}


# ------------------------------------------------------------------ 1. degenerated edges
@pytest.fixture(scope="module")
def dimple_step(tmp_path_factory):
    from data.make_synthetic_shell import SheetSpec, make_step

    return make_step(tmp_path_factory.mktemp("dimple_step"), SheetSpec(dimples=(DIMPLE,)))


def _degenerated(body) -> list[int]:
    from OCP.BRep import BRep_Tool

    return [i for i, e in enumerate(body._edges, 1) if BRep_Tool.Degenerated_s(e)]


def test_pole_edge_has_no_3d_curve_and_rebuilds(dimple_step):
    from OCP.BRep import BRep_Tool
    from OCP.BRepLib import BRepLib
    from paicad.kernel.base import SurfaceEdit
    from paicad.kernel.occ_sheet import load_sheet_step
    from paicad.shell.edit import _edge_t

    b = load_sheet_step(dimple_step)[0]
    deg = _degenerated(b)
    assert len(deg) == 1 and BRep_Tool.Curve_s(b._edges[deg[0] - 1], 0.0, 0.0) is None
    # option (b) of the bug report would not help: OCCT builds no 3D curve for a degenerated edge
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Copy
    from OCP.TopoDS import TopoDS

    cp = TopoDS.Shell_s(BRepBuilderAPI_Copy(b._solid, True, False).Shape())
    BRepLib.BuildCurves3d_s(cp)
    from paicad.kernel.occ_sheet import OccSheet

    assert BRep_Tool.Curve_s(OccSheet("c", cp)._edges[deg[0] - 1], 0.0, 0.0) is None

    nb = b.rebuilt({}, {}, {})  # every edge unchanged (0.14.1: GEOM_CAD_FAILED "edge E.. has no 3D curve")
    assert _degenerated(nb) == deg and BRep_Tool.Curve_s(nb._edges[deg[0] - 1], 0.0, 0.0) is None
    assert nb.summary().extra == b.summary().extra
    assert np.allclose(nb.summary().bbox, b.summary().bbox, atol=1e-9)

    # moving the dimple: sphere translated, its boundary circle / seam re-made, the pole vertex follows
    topo = b.topology()
    sph = [f for f in range(1, len(b._faces) + 1) if b.surface_params(f)["kind"] == "SPHERE"]
    assert len(sph) == 1 and deg[0] in topo.face(sph[0]).edges
    t = np.array([3.0, -2.0, 0.0])
    edges = sorted(set(topo.face(sph[0]).edges))
    ep = {e: b.eval_edge(e, _edge_t(topo, e)) + t for e in edges if e not in deg}
    vp = {v: topo.vertices[v - 1] + t for e in edges for v in topo.edge(e).vertices}
    mb = b.rebuilt({sph[0]: SurfaceEdit(translate=t)}, ep, vp)
    lo = np.asarray(mb.summary().bbox)[:3]
    assert _degenerated(mb) == deg and abs(lo[2] - np.asarray(b.summary().bbox)[2]) < 1e-6
    pole = mb.topology().vertices[mb.topology().edge(deg[0]).vertices[0] - 1]
    assert np.allclose(pole, [DIMPLE[0] + 3.0, DIMPLE[1] - 2.0, -DIMPLE[3]], atol=1e-6)

    # a pole vertex off the edited sphere is a CAD failure, not an invalid sheet
    bad = dict(vp)
    pv = topo.edge(deg[0]).vertices[0]
    bad[pv] = bad[pv] + np.array([0.0, 0.0, 0.5])
    with pytest.raises(Exception) as ei:
        b.rebuilt({sph[0]: SurfaceEdit(translate=t)}, ep, bad)
    assert getattr(ei.value, "code", None) == "GEOM_CAD_FAILED"


def test_regular_edges_without_3d_curve_rebuild(dimple_step):
    """Regular edges stored with pcurves only: 3D curve built on an empty copy, the nominal stays untouched."""
    from OCP.BRep import BRep_Tool
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Copy
    from OCP.ShapeBuild import ShapeBuild_Edge
    from OCP.TopoDS import TopoDS
    from paicad.kernel.occ_sheet import OccSheet, load_sheet_step

    b = load_sheet_step(dimple_step)[0]
    sh = TopoDS.Shell_s(BRepBuilderAPI_Copy(b._solid, True, False).Shape())
    s = OccSheet("x", sh)
    for e in s._edges:
        if not BRep_Tool.Degenerated_s(e):
            ShapeBuild_Edge().RemoveCurve3d(e)
    s = OccSheet("x", sh)
    assert all(BRep_Tool.Curve_s(e, 0.0, 0.0) is None for e in s._edges)
    nb = s.rebuilt({}, {}, {})
    assert all(BRep_Tool.Curve_s(e, 0.0, 0.0) is None for e in s._edges)  # input not modified
    assert sum(BRep_Tool.Curve_s(e, 0.0, 0.0) is not None for e in nb._edges) == len(nb._edges) - 1  # all but the pole
    assert abs(nb.summary().extra["area"] - b.summary().extra["area"]) < 1e-6
    assert np.allclose(nb.summary().bbox, b.summary().bbox, atol=1e-6)


@pytest.fixture(scope="module")
def dimple_set(tmp_path_factory):
    from data.make_synthetic_shell import SheetSpec, make_all

    root = tmp_path_factory.mktemp("dimple_sm1")
    g = make_all(root / "sm", SheetSpec(dimples=(DIMPLE,)))
    fx, ex = root / "fixed", root / "extract"
    code, log = run_cli("shell", "fixed-scan", "--assem-dir", g["assem"], "--out-dir", fx, "--parts", "2001")
    assert code == 0, log
    code, log = run_cli("shell", "extract", "--cad", g["step"], "--assem-dir", g["assem"], "--out-dir", ex)
    assert code == 0, log
    g.update(fixed_dir=fx, features_path=ex / "shell_features.json", features=json.loads((ex / "shell_features.json").read_text(encoding="utf-8")))
    return g


def test_shell_grid_with_pole_edge_all_cells_ok(dimple_set, tmp_path):
    """The esl case: every bead change on a sheet with an untouched spherical dimple (0.14.1: all GEOM_CAD_FAILED)."""
    g = dimple_set
    doc = g["features"]
    # B5 (bead nearest its truth center) overlaps the screw-hole spider by design -> excluded (SHELL_FIXED_REGION_VIOLATION)
    b5 = next(t for t in g["truth"]["beads"] if t["name"] == "B5")
    skip = min(doc["beads"], key=lambda x: sum((a - c) ** 2 for a, c in zip(x["center"], b5["center"])))["id"]
    feats = [f for f in doc["features"] if f["bead"] != skip]
    assert len(feats) >= 12
    cells = [{"id": "nominal", "values": {}}]
    for f in feats:
        cells.append({"id": f["name"].lower(), "values": {f["name"]: f["nominal"] + (0.3 if f["type"] == "BEAD_DEPTH" else 1.0)}})
    cj, tj = tmp_path / "cells.json", tmp_path / "thumb.json"
    cj.write_text(json.dumps({"schema_version": 1, "cells": cells}), encoding="utf-8")
    tj.write_text(json.dumps(THUMB), encoding="utf-8")
    out = tmp_path / "g"
    code, text = run_cli("shell", "view", "grid", "--cad", g["step"], "--features", g["features_path"], "--cells", cj, "--fixed-dir", g["fixed_dir"],
                         "--thumb-options", tj, "--out-dir", out)
    assert code == 0, text
    rows = json.loads((out / "grid_manifest.json").read_text(encoding="utf-8"))["cells"]
    assert len(rows) == len(cells)
    assert [(r["id"], r["status"], r["code"]) for r in rows if r["status"] != "OK"] == []


# ------------------------------------------------------------------ 2. rename retry
def _locked_replace(fails: dict, winerror: int = 5):
    """os.replace stand-in: raise a Windows lock error ``fails[dst name]`` times (-1 = always), then rename."""
    real = os.replace
    seen: dict[str, int] = {}

    def fake(src, dst):
        n = Path(dst).name
        k = fails.get(n, 0)
        if k == -1 or seen.get(n, 0) < k:
            seen[n] = seen.get(n, 0) + 1
            e = PermissionError(13, "Access is denied", str(Path(src).resolve()))
            e.winerror = winerror
            raise e
        real(src, dst)

    return fake, seen


@pytest.mark.parametrize("winerror", [5, 32])
def test_replace_retry_backoff_then_success(tmp_path, monkeypatch, winerror):
    fake, seen = _locked_replace({"b.txt": 3}, winerror)
    monkeypatch.setattr(os, "replace", fake)
    slept = []
    (tmp_path / "a.txt").write_text("x")
    replace_retry(tmp_path / "a.txt", tmp_path / "b.txt", sleep=slept.append)
    assert (tmp_path / "b.txt").read_text() == "x" and not (tmp_path / "a.txt").exists()
    assert seen == {"b.txt": 3} and slept == [0.2, 0.5, 1.0]


@pytest.mark.parametrize("winerror", [5, 32])
def test_replace_retry_gives_up_with_file_names_only(tmp_path, monkeypatch, winerror):
    fake, seen = _locked_replace({"b.txt": -1}, winerror)
    monkeypatch.setattr(os, "replace", fake)
    slept = []
    (tmp_path / "a.txt").write_text("x")
    with pytest.raises(PaicadError) as ei:
        replace_retry(tmp_path / "a.txt", tmp_path / "b.txt", sleep=slept.append)
    e = ei.value
    assert e.code == "GEOM_INTERNAL" and e.exit_code == common.EXIT_INTERNAL
    assert slept == [0.2, 0.5, 1.0, 2.0, 4.0] and seen == {"b.txt": 6}
    assert "a.txt" in e.message and "b.txt" in e.message and f"WinError {winerror}" in e.message
    assert str(tmp_path) not in e.message and "/" not in e.message and "\\" not in e.message
    assert e.__cause__ is None and e.__suppress_context__
    assert (tmp_path / "a.txt").exists()


def test_replace_retry_other_errors_and_config(tmp_path, monkeypatch):
    def denied(src, dst):  # POSIX permission error (no winerror) -> no retry, unchanged exception
        raise PermissionError(13, "denied", str(dst))

    monkeypatch.setattr(os, "replace", denied)
    slept = []
    with pytest.raises(PermissionError):
        replace_retry(tmp_path / "a", tmp_path / "b", sleep=slept.append)
    assert slept == []
    monkeypatch.setenv("PAICAD_REPLACE_BACKOFF_S", "0, 0.1")
    assert common.replace_backoff() == (0.0, 0.1)
    for bad in ("x", "-1", "100"):
        monkeypatch.setenv("PAICAD_REPLACE_BACKOFF_S", bad)
        assert common.replace_backoff() == common.REPLACE_BACKOFF_S
    monkeypatch.setenv("PAICAD_REPLACE_BACKOFF_S", "")
    assert common.replace_backoff() == ()
    fake, seen = _locked_replace({"b": -1})
    monkeypatch.setattr(os, "replace", fake)
    with pytest.raises(PaicadError):
        replace_retry(tmp_path / "a", tmp_path / "b", sleep=slept.append)
    assert seen == {"b": 1} and slept == []


def test_grid_cell_rename_locked(golden, tmp_path, monkeypatch):
    """A locked cell folder: retried, then only that cell is ERROR GEOM_INTERNAL (file names only); the grid goes on."""
    monkeypatch.setenv("PAICAD_REPLACE_BACKOFF_S", "0,0,0")
    fake, seen = _locked_replace({"locked": -1, "flaky": 2})
    monkeypatch.setattr(os, "replace", fake)
    cells = [("locked", {"CUSH_L_THK_3": 21.0}), ("flaky", {"CUSH_L_THK_3": 21.5}), ("ok", {"CUSH_L_THK_3": 20.5})]
    cj, tj = tmp_path / "cells.json", tmp_path / "thumb.json"
    cj.write_text(json.dumps({"schema_version": 1, "cells": [{"id": c, "values": v} for c, v in cells]}), encoding="utf-8")
    tj.write_text(json.dumps(THUMB), encoding="utf-8")
    out = tmp_path / "g"
    code, text = run_cli("view", "grid", "--cad", golden["step"], "--features", golden["features_path"], "--cells", cj, "--tag-dir", golden["tag_dir"],
                         "--thumb-options", tj, "--out-dir", out)
    assert code == 0, text
    st = {c["id"]: c for c in json.loads((out / "grid_manifest.json").read_text(encoding="utf-8"))["cells"]}
    assert (st["locked"]["status"], st["locked"]["code"], st["locked"]["category"]) == ("ERROR", "GEOM_INTERNAL", "INTERNAL")
    assert st["flaky"]["status"] == "OK" and st["ok"]["status"] == "OK"
    assert seen["locked"] == 4 and seen["flaky"] == 2
    assert sorted(p.name for p in (out / "cells").iterdir()) == ["flaky", "ok"]
    log = (out / "paicad.log").read_text(encoding="utf-8")
    line = next(x for x in log.splitlines() if "cell locked: GEOM_INTERNAL" in x)
    assert "cannot rename .part_locked to locked" in line and str(tmp_path) not in line
