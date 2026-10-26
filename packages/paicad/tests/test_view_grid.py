"""paicad 0.14.0: ``paicad view grid`` / ``paicad shell view grid`` (doe-preview.md section 3, V-DP-1/2/4/5/6/11).

Virtual goldens: the development cushion (``data/make_synthetic.py``) and the sheet SM1. A grid cell must equal the
single ``view preview --fe off`` of the same values (GLB and manifest bytes, ``timing``/``thumb`` aside), every cell
uses the camera and color range fixed by the nominal and the thumb options only (so a cell is cacheable on its own),
and an update failure is a FAIL cell with a thumbnail that does not stop the next cell. Nothing generated is committed.
"""

from __future__ import annotations

import hashlib
import json
import os
import struct
import subprocess
import sys
import time
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import gltf_check as gc
import numpy as np
import pytest
from conftest import PKG, run_cli
from paicad import render as R
from paicad.common import PaicadError

THUMB = {"schema_version": 1, "w": 320, "h": 240, "view_dir": [1, -1, 1], "margin": 1.15, "disp_range_mm": [0.0, 2.0], "colormap": "turbo16",
         "nominal_ghost": True, "edges": False}
CELLS = [
    ("nominal", {}),
    ("thk", {"CUSH_L_THK_3": 22.0}),
    ("hole", {"CUSH_L_HOLE_R_1": 5.5}),
    ("coll", {"CUSH_R_HOLE_U_1": 86.4}),  # hole runs into the rib foot print -> GEOM_FEATURE_COLLISION
    ("rib", {"CUSH_L_RIB_H_1": 16.5}),
]


def load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def write_json(path, obj):
    Path(path).write_text(json.dumps(obj), encoding="utf-8")
    return path


def read_png(path) -> np.ndarray:
    """RGB uint8 image of an 8-bit RGB, filter-0 PNG (the paicad writer)."""
    data = Path(path).read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    pos, idat, w, h = 8, b"", None, None
    while pos < len(data):
        n = struct.unpack(">I", data[pos : pos + 4])[0]
        kind, body = data[pos + 4 : pos + 8], data[pos + 8 : pos + 8 + n]
        if kind == b"IHDR":
            w, h = struct.unpack(">II", body[:8])
            assert body[8:10] == b"\x08\x02"
        elif kind == b"IDAT":
            idat += body
        pos += 12 + n
    raw = np.frombuffer(zlib.decompress(idat), dtype=np.uint8).reshape(h, 1 + 3 * w)
    assert not raw[:, 0].any()
    return raw[:, 1:].reshape(h, w, 3)


def grid(g, out, cells, *extra, thumb=None, tag=True, shell=False):
    cj = write_json(Path(out).parent / f"{Path(out).name}_cells.json", {"schema_version": 1, "cells": [{"id": i, "values": v} for i, v in cells]})
    tj = write_json(Path(out).parent / f"{Path(out).name}_thumb.json", thumb or THUMB)
    args = ["shell"] if shell else []
    args += ["view", "grid", "--cad", g["step"], "--features", g["features_path"], "--cells", cj, "--thumb-options", tj, "--out-dir", out, *extra]
    if shell:
        args += ["--fixed-dir", g["fixed_dir"]]
    if tag:
        args += ["--tag-dir", g["tag_dir"]]
    return run_cli(*args)


def manifest_wo(p, *keys) -> tuple[dict, str]:
    """(manifest without ``keys``, text before the ``timing`` block)."""
    text = Path(p).read_text(encoding="utf-8")
    d = json.loads(text)
    for k in keys:
        d.pop(k, None)
    return d, text.split('"timing"')[0]


def red_pixels(img: np.ndarray) -> np.ndarray:
    a = img.astype(int)
    return (a[..., 0] > 90) & (a[..., 0] > 3 * a[..., 1]) & (a[..., 0] > 3 * a[..., 2])


@pytest.fixture(scope="session")
def grid1(golden, tmp_path_factory):
    out = tmp_path_factory.mktemp("grid") / "g1"
    code, text = grid(golden, out, CELLS)
    assert code == 0, text
    return out


# ------------------------------------------------------------------ V-DP-1: feature PNG unchanged
def _box_faces(lo, hi, f0, n=6):
    lo, hi = np.asarray(lo, float), np.asarray(hi, float)
    faces, fid = [], f0
    for ax in range(3):
        for side in (0, 1):
            a, b = [i for i in range(3) if i != ax]
            U, V = np.meshgrid(np.linspace(lo[a], hi[a], n + 1), np.linspace(lo[b], hi[b], n + 1), indexing="ij")
            P = np.zeros(((n + 1) ** 2, 3))
            P[:, a], P[:, b], P[:, ax] = U.ravel(), V.ravel(), (hi if side else lo)[ax]
            idx = np.arange((n + 1) ** 2).reshape(n + 1, n + 1)
            t = [[idx[i, j], idx[i + 1, j], idx[i + 1, j + 1]] for i in range(n) for j in range(n)]
            t += [[idx[i, j], idx[i + 1, j + 1], idx[i, j + 1]] for i in range(n) for j in range(n)]
            t = [t[k // 2 + (k % 2) * n * n] for k in range(2 * n * n)]  # quad order: (lower, upper) per quad
            faces.append((fid, P, np.array(t, dtype=np.int64)))
            fid += 1
    return faces


def test_feature_png_pixels_unchanged_by_generalization():
    """``render.py`` size / camera generalization: the 800x600 feature picture is pixel-identical to 0.13.0
    (reference digest computed with the 0.13.0 ``render.py`` on this synthetic body; PNG writer untouched)."""
    mesh = R.BodyMesh(_box_faces([0, 0, 0], [100, 60, 20], 1) + _box_faces([20, 10, 20], [50, 30, 35], 7))
    h = hashlib.sha256()
    for mv, fx, dim in (([12], [6], (np.array([35.0, 20, 35]), np.array([35.0, 20, 20]))), ([7, 8], [], None), ([3], [1, 2], (np.array([0.0, 0, 0]), np.array([100.0, 60, 20])))):
        img = R.render_feature(mesh, mv, fx, dim)
        assert img.shape == (600, 800, 3)
        h.update(np.clip(np.rint(img), 0, 255).astype(np.uint8).tobytes())
    assert h.hexdigest() == "1507ca04a431abb5f1f39f30fb6c709315352d94fb99a715063249c3e03c872f"


def test_raster_size_from_buffer_matches_loop():
    rng = np.random.default_rng(3)
    P = np.column_stack([rng.uniform(-20, 340, 60), rng.uniform(-20, 260, 60), rng.uniform(-5, 5, 60)])
    tris = rng.integers(0, 60, (40, 3))
    shade = rng.uniform(0, 1, 40)
    za, ca = np.full((240, 320), -np.inf), np.zeros((240, 320))
    zb, cb = za.copy(), ca.copy()
    R._raster(P, tris, shade, za, ca)
    R._raster_loop(P, tris, shade, zb, cb)
    assert np.array_equal(za, zb) and np.array_equal(ca, cb) and np.isfinite(za).any()


# ------------------------------------------------------------------ thumbnail unit (no OCCT)
def test_thumb_options_validation(tmp_path):
    from paicad.view.grid import THUMB_DEFAULTS, load_thumb_options

    o = load_thumb_options(write_json(tmp_path / "a.json", {"schema_version": 1}))
    assert o == {**THUMB_DEFAULTS, "view_dir": [1.0, -1.0, 1.0], "margin": 1.15, "disp_range_mm": [0.0, 1.0]}
    for bad, word in (({"w": 100}, "w must"), ({"h": 801}, "h must"), ({"view_dir": [0, 0, 0]}, "view_dir"), ({"margin": 2.5}, "margin"),
                      ({"disp_range_mm": [1.0, 1.0]}, "disp_range_mm"), ({"colormap": "jet"}, "colormap"), ({"edges": 1}, "edges"), ({"zoom": 2}, "unknown keys: zoom")):
        with pytest.raises(PaicadError) as ei:
            load_thumb_options(write_json(tmp_path / "b.json", bad))
        assert ei.value.code == "GEOM_INPUT_INVALID" and word in ei.value.message, bad


def test_camera_fit_and_thumb_colors():
    cam = R.Camera.fit([0, 0, 0, 100, 50, 10], [0, 0, 1], 1.25, 320, 240)  # top view: x right, y up
    assert np.allclose(cam.center, [50, 25, 5]) and cam.scale == pytest.approx(min(320 / 125.0, 240 / 62.5))
    P = cam.project(np.array([[0.0, 0, 10], [100, 50, 10]]))
    assert P[0, 0] == pytest.approx(160 - 50 * cam.scale) and P[0, 1] == pytest.approx(120 + 25 * cam.scale)
    sq = np.array([[0, 0, 10], [100, 0, 10], [100, 50, 10], [0, 50, 10]], dtype=float)
    tri = np.array([[0, 1, 2], [0, 2, 3]])
    cmap = R.COLORMAPS["turbo16"]
    for v, k in ((0.0, 0), (0.53, 8), (5.0, 15), (-1.0, 0)):  # bin = floor(v / 1.0 * 16), saturated at both ends
        img, clipped = R.render_thumb(cam, [R.ThumbMesh(sq, tri, disp=np.full(4, v))], [0.0, 1.0])
        assert not clipped
        c = img[120, 160]
        shade = R._shade(np.array([0.0, 0.0, 1.0]), cam.light)
        assert np.allclose(c, cmap[k] * shade), (v, c)
    # interpolated vertex values: left edge 0, right edge 1 -> bins increase left to right
    img, _ = R.render_thumb(cam, [R.ThumbMesh(sq, tri, disp=np.array([0.0, 1.0, 1.0, 0.0]))], [0.0, 1.0])
    row = img[120, 40:280]
    assert not np.allclose(row[0], row[-1]) and np.allclose(row[-1] / row[-1].max(), cmap[15] / cmap[15].max(), atol=0.02)
    # outside the image -> clipped; triangle colors
    img, clipped = R.render_thumb(cam, [R.ThumbMesh(sq * 2.0, tri, rgb=np.tile(R.FAIL_RED, (2, 1)))], [0.0, 1.0])
    assert clipped and red_pixels(img).sum() > 1000
    # ghost lines drawn first, covered by the shape
    img, _ = R.render_thumb(cam, [], [0.0, 1.0], ghost=[sq[[0, 1, 2, 3, 0]]])
    assert (np.abs(img.astype(float) - R.GHOST).sum(axis=2) == 0).sum() > 300


def test_cells_validation(tmp_path):
    from paicad.view.grid import load_cells

    ok = lambda v: dict(v["values"])  # noqa: E731
    assert load_cells(write_json(tmp_path / "a.json", {"schema_version": 1, "cells": [{"id": "nominal", "values": {}}, {"id": "a_1"}]}), ok) == [("nominal", {}), ("a_1", {})]
    for doc, word in (({"cells": []}, "at least one cell"), ({"cells": [{"id": "A"}]}, "id must match"), ({"cells": [{"id": "a"}, {"id": "a"}]}, "duplicate cell id"),
                      ({"cells": [{"id": "x" * 65}]}, "id must match"), ({"cells": [{"id": "a", "values": []}]}, "values must be an object")):
        with pytest.raises(PaicadError) as ei:
            load_cells(write_json(tmp_path / "b.json", doc), ok)
        assert ei.value.code == "GEOM_INPUT_INVALID" and word in ei.value.message, doc


# ------------------------------------------------------------------ solid grid on the virtual cushion
def test_grid_outputs_and_statuses(golden, grid1):
    gm = load(grid1 / "grid_manifest.json")
    assert list(gm)[:3] == ["schema_version", "engine", "engine_version"]
    assert set(gm) == {"schema_version", "engine", "engine_version", "kind", "camera", "disp_range_mm", "nominal", "cells", "timing"}
    assert gm["kind"] == "solid" and gm["disp_range_mm"] == [0.0, 2.0] and set(gm["camera"]) == {"view_dir", "center", "scale", "digest"}
    assert [c["id"] for c in gm["cells"]] == [i for i, _ in CELLS]
    st = {c["id"]: c for c in gm["cells"]}
    assert all(set(c) == {"id", "status", "code", "category", "max_disp_mm", "total_s"} for c in gm["cells"])
    assert (st["nominal"]["status"], st["nominal"]["max_disp_mm"]) == ("OK", 0.0)
    assert st["thk"]["status"] == "OK" and st["thk"]["max_disp_mm"] == pytest.approx(2.0, abs=1e-3)
    assert st["hole"]["status"] == "OK" and st["hole"]["max_disp_mm"] == pytest.approx(0.5, abs=1e-3)
    assert (st["coll"]["status"], st["coll"]["code"], st["coll"]["category"], st["coll"]["max_disp_mm"]) == ("FAIL", "GEOM_FEATURE_COLLISION", "CAD_FAILED", None)
    assert st["rib"]["status"] == "OK"  # the cell after the failing one is processed
    assert sorted(p.name for p in (grid1 / "cells").iterdir()) == sorted(i for i, _ in CELLS)  # no .part_* left
    assert sorted(p.name for p in (grid1 / "cells" / "thk").iterdir()) == ["preview.glb", "preview_manifest.json", "thumb.png", "update"]
    assert sorted(p.name for p in (grid1 / "cells" / "coll").iterdir()) == ["preview_manifest.json", "thumb.png", "update"]
    for cid, _ in CELLS:
        d = grid1 / "cells" / cid
        m = load(d / "preview_manifest.json")
        png = (d / "thumb.png").read_bytes()
        assert m["thumb"] == {"file": "thumb.png", "sha256": hashlib.sha256(png).hexdigest(), "w": 320, "h": 240, "clipped": False}
        assert list(m)[-2:] == ["timing", "thumb"] and m["fe"] == {"mode": "off"}
        assert read_png(d / "thumb.png").shape == (240, 320, 3)
    assert not any(p.name in ("morphed.inc", "files") for p in grid1.rglob("*"))
    log = (grid1 / "paicad.log").read_text(encoding="utf-8")
    assert "PAICAD RESULT OK - grid_manifest.json" in log and "[coll] PAICAD RESULT FAIL GEOM_FEATURE_COLLISION" in log


@pytest.mark.parametrize("cid", ["thk", "coll"])
def test_grid_cell_equals_view_preview(golden, grid1, tmp_path, cid):
    """V-DP-2: the cell files = ``view preview --fe off`` of the same values (``timing`` / ``thumb`` aside)."""
    values = dict(CELLS)[cid]
    vp = write_json(tmp_path / "v.json", {"schema_version": 1, "values": values})
    code, text = run_cli("view", "preview", "--cad", golden["step"], "--features", golden["features_path"], "--values", vp, "--tag-dir", golden["tag_dir"],
                         "--out-dir", tmp_path / "p")
    assert code == (0 if cid == "thk" else 10), text
    c = grid1 / "cells" / cid
    a, ta = manifest_wo(c / "preview_manifest.json", "timing", "thumb")
    b, tb = manifest_wo(tmp_path / "p" / "preview_manifest.json", "timing")
    assert a == b and ta == tb
    if cid == "thk":
        assert (c / "preview.glb").read_bytes() == (tmp_path / "p" / "preview.glb").read_bytes()
        assert (c / "update" / "face_map.json").read_bytes() == (tmp_path / "p" / "update" / "face_map.json").read_bytes()
    ua, ub = load(c / "update" / "update.json"), load(tmp_path / "p" / "update" / "update.json")
    assert {k: v for k, v in ua.items() if k != "elapsed_s"} == {k: v for k, v in ub.items() if k != "elapsed_s"}


def test_grid_deterministic_and_cell_cacheable(golden, grid1, tmp_path):
    """V-DP-6 + DP-C7: another grid with other cells in another order gives the same bytes for the same values."""
    out = tmp_path / "g2"
    code, text = grid(golden, out, [("rib", dict(CELLS)["rib"]), ("thk", dict(CELLS)["thk"]), ("coll", dict(CELLS)["coll"])])
    assert code == 0, text
    a, b = load(grid1 / "grid_manifest.json"), load(out / "grid_manifest.json")
    assert a["camera"] == b["camera"] and a["nominal"] == b["nominal"]
    for cid in ("rib", "thk", "coll"):
        x, y = grid1 / "cells" / cid, out / "cells" / cid
        assert (x / "thumb.png").read_bytes() == (y / "thumb.png").read_bytes(), cid
        if (x / "preview.glb").exists():
            assert (x / "preview.glb").read_bytes() == (y / "preview.glb").read_bytes()
        assert manifest_wo(x / "preview_manifest.json", "timing") == manifest_wo(y / "preview_manifest.json", "timing")
    # nominal GLB of the grid = ``view export`` GLB
    code, text = run_cli("view", "export", "--cad", golden["step"], "--features", golden["features_path"], "--out-dir", tmp_path / "e")
    assert code == 0, text
    assert a["nominal"]["view_sha256"] == load(tmp_path / "e" / "view_manifest.json")["glb"]["sha256"]


def test_grid_common_camera_and_colors(golden, grid1):
    """V-DP-4: camera from the nominal bbox only; the nominal thumbnail silhouette = the projected nominal
    tessellation bbox (+-1 px); a changed cell shows warmer colormap bins, the nominal only the first bin."""
    gm = load(grid1 / "grid_manifest.json")
    bb = gm["nominal"]["bbox"]
    assert np.allclose(gm["camera"]["center"], 0.5 * (np.array(bb[:3]) + np.array(bb[3:])))
    cam = R.Camera(gm["camera"]["view_dir"], gm["camera"]["center"], gm["camera"]["scale"], 320, 240)
    from paicad.view.grid import camera_digest

    assert camera_digest(cam) == gm["camera"]["digest"] and cam.doc() == {k: gm["camera"][k] for k in ("view_dir", "center", "scale")}
    # same fit as the thumb options say (bbox x margin fits the image, one side touching)
    lo, hi = np.array(bb[:3]), np.array(bb[3:])
    corners = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
    P = cam.project(corners)
    span = np.ptp(P[:, :2], axis=0) * 1.15
    assert max(span[0] / 320, span[1] / 240) == pytest.approx(1.0)
    doc, bin_ = gc.load(grid1 / "cells" / "nominal" / "preview.glb")
    pts = np.concatenate([gc.node_mesh(doc, bin_, b["node"])["POSITION"].astype(float) for b in load(grid1 / "cells" / "nominal" / "preview_manifest.json")["bodies"]])
    Q = cam.project(pts)
    img = read_png(grid1 / "cells" / "nominal" / "thumb.png").astype(int)
    ys, xs = np.nonzero((img != 255).any(axis=2))
    assert abs(xs.min() - np.floor(Q[:, 0].min())) <= 1 and abs(xs.max() - np.floor(Q[:, 0].max())) <= 1
    assert abs(ys.min() - np.floor(Q[:, 1].min())) <= 1 and abs(ys.max() - np.floor(Q[:, 1].max())) <= 1
    first = R.COLORMAPS["turbo16"][0]
    shape = (img != 255).any(axis=2) & ~(img == R.GHOST.astype(int)).all(axis=2)
    ratio = img[shape] / np.maximum(img[shape].max(axis=1, keepdims=True), 1)
    assert np.allclose(ratio, first / first.max(), atol=0.03)  # nominal: displacement 0 everywhere
    thk = read_png(grid1 / "cells" / "thk" / "thumb.png").astype(int)
    assert ((thk[..., 0] > thk[..., 2] + 40) & (thk[..., 0] > 100)).sum() > 50  # warm bins on the moved face
    assert not red_pixels(img).any()


def test_grid_fail_cell_thumbnail(golden, grid1):
    """V-DP-5: FAIL cell = nominal gray with the faces of the failing features red, no GLB."""
    m = load(grid1 / "cells" / "coll" / "preview_manifest.json")
    assert (m["status"], m["code"], m["glb"]) == ("FAIL", "GEOM_FEATURE_COLLISION", None) and "CUSH_R_HOLE_U_1" in m["failure"]["features"]
    img = read_png(grid1 / "cells" / "coll" / "thumb.png").astype(int)
    assert red_pixels(img).sum() > 20
    nonred = (img != 255).any(axis=2) & ~red_pixels(img)
    assert (np.ptp(img[nonred], axis=1) <= 1).all()  # everything else gray (or ghost)


def test_grid_cell_errors_do_not_stop_the_grid(golden, tmp_path, monkeypatch):
    """V-DP-5: a cell VIEW_TOO_LARGE -> that cell ERROR (manifest + gray thumb); an internal error -> ERROR, no folder."""
    import paicad.view.preview as pv

    real = pv.glb_with_lod
    calls = {"n": 0}

    def fake(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise PaicadError("VIEW_TOO_LARGE", "test: too large")
        if calls["n"] == 2:
            raise RuntimeError("test: boom")
        return real(*a, **k)

    monkeypatch.setattr(pv, "glb_with_lod", fake)
    out = tmp_path / "g"
    code, text = grid(golden, out, [("big", {"CUSH_L_THK_3": 21.0}), ("boom", {"CUSH_L_THK_3": 21.5}), ("ok", {"CUSH_L_THK_3": 20.5})])
    assert code == 0 and "PAICAD RESULT OK - grid_manifest.json" in text, text
    st = {c["id"]: c for c in load(out / "grid_manifest.json")["cells"]}
    assert (st["big"]["status"], st["big"]["code"], st["big"]["category"]) == ("ERROR", "VIEW_TOO_LARGE", "VIEW")
    assert (st["boom"]["status"], st["boom"]["code"]) == ("ERROR", "GEOM_INTERNAL")
    assert st["ok"]["status"] == "OK"
    assert sorted(p.name for p in (out / "cells").iterdir()) == ["big", "ok"]
    img = read_png(out / "cells" / "big" / "thumb.png").astype(int)
    assert not red_pixels(img).any() and (img != 255).any()


def test_grid_nominal_failure_and_input_errors(golden, tmp_path, monkeypatch):
    import paicad.view.grid as vg

    code, text = grid(golden, tmp_path / "a", [("a", {"NO_SUCH": 1.0})])
    assert code == 3 and "GEOM_INPUT_INVALID" in text and not (tmp_path / "a" / "grid_manifest.json").exists()
    code, text = grid(golden, tmp_path / "b", [("a", {}), ("a", {})])
    assert code == 3 and not (tmp_path / "b" / "grid_manifest.json").exists()
    code, text = grid(golden, tmp_path / "c", [("a", {"CUSH_L_THK_3": "x"})])
    assert code == 3
    code, text = grid(golden, tmp_path / "d", [("a", {})], thumb={"schema_version": 1, "w": 10})
    assert code == 3
    with pytest.raises(SystemExit) as ei:  # --thumb-options is required
        run_cli("view", "grid", "--cad", golden["step"], "--features", golden["features_path"], "--cells", tmp_path / "a_cells.json", "--out-dir", tmp_path / "e")
    assert ei.value.code == 2

    def fail(*a, **k):
        raise PaicadError("VIEW_TESSELLATION_FAILED", "test")

    monkeypatch.setattr(vg, "glb_with_lod", fail)
    code, text = grid(golden, tmp_path / "f", [("a", {})])
    assert code == 14 and "PAICAD RESULT FAIL VIEW_TESSELLATION_FAILED" in text and not (tmp_path / "f" / "grid_manifest.json").exists()
    monkeypatch.undo()
    code, text = grid(golden, tmp_path / "f", [("a", {})])  # nothing was committed by the failed run
    assert code == 0, text
    code, text = grid(golden, tmp_path / "f", [("a", {})])
    assert code == 3 and "GEOM_OUTPUT_EXISTS" in text


def _doe_cells(golden, n: int, seed: int = 7) -> list[tuple[str, dict]]:
    """Nominal + ``n - 1`` space-filling samples (stratified per parameter, shuffled) over every length parameter."""
    from paicad import options
    from paicad.update import param_keys

    doc = golden["features"]
    keys = param_keys(doc, options.load(None))
    fm = {f["name"]: f for f in doc["features"]}
    names = [k for k in keys if k in fm and fm[k].get("range")]
    rng = np.random.default_rng(seed)
    m = n - 1
    cols = {k: rng.permutation((np.arange(m) + rng.uniform(0, 1, m)) / m) for k in names}
    cells = [("nominal", {})]
    for i in range(m):
        cells.append((f"s{i:02d}", {k: round(fm[k]["range"]["min"] + float(cols[k][i]) * (fm[k]["range"]["max"] - fm[k]["range"]["min"]), 4) for k in names}))
    return cells


def test_grid_speed_24_cells(golden, tmp_path):
    """V-DP-11: 24 cells, chunks of 4 in separate processes, 2 in parallel (DP_RENDER defaults); target <= 90 s on the
    development PC (CI limit 180 s). Reports the cell / raster time and the PNG / GLB sizes."""
    cells = _doe_cells(golden, 24)
    tj = write_json(tmp_path / "thumb.json", THUMB)
    env = dict(os.environ, PYTHONPATH=str(PKG / "src") + os.pathsep + os.environ.get("PYTHONPATH", ""))

    def chunk(i):
        cj = write_json(tmp_path / f"c{i}.json", {"schema_version": 1, "cells": [{"id": c, "values": v} for c, v in cells[4 * i : 4 * i + 4]]})
        cmd = [sys.executable, "-m", "paicad", "view", "grid", "--cad", str(golden["step"]), "--features", str(golden["features_path"]), "--cells", str(cj),
               "--tag-dir", str(golden["tag_dir"]), "--thumb-options", str(tj), "--threads", "1", "--out-dir", str(tmp_path / f"chunk_{i}")]
        return subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=600)

    t0 = time.monotonic()
    with ThreadPoolExecutor(2) as ex:
        res = list(ex.map(chunk, range(6)))
    wall = time.monotonic() - t0
    for r in res:
        assert r.returncode == 0, r.stdout + r.stderr
    rows, thumb_s, png_b, glb_b = [], [], [], []
    for i in range(6):
        gm = load(tmp_path / f"chunk_{i}" / "grid_manifest.json")
        rows += gm["cells"]
        for c in gm["cells"]:
            d = tmp_path / f"chunk_{i}" / "cells" / c["id"]
            m = load(d / "preview_manifest.json")
            thumb_s.append(c["total_s"] - m["timing"]["total_s"])
            png_b.append((d / "thumb.png").stat().st_size)
            if (d / "preview.glb").exists():
                glb_b.append((d / "preview.glb").stat().st_size)
    n = {s: sum(r["status"] == s for r in rows) for s in ("OK", "FAIL", "ERROR")}
    print(f"\ngrid speed: 24 cells, 6 chunks x 4, parallel 2: wall {wall:.1f} s; cells {n}; cell total_s mean {np.mean([r['total_s'] for r in rows]):.2f} s, "
          f"max {max(r['total_s'] for r in rows):.1f} s; thumbnail (raster + PNG) ~{np.mean(thumb_s):.2f} s/cell; PNG {np.mean(png_b) / 1024:.1f} KiB/cell, "
          f"GLB {np.mean(glb_b) / 1024:.0f} KiB/cell")
    assert len(rows) == 24 and n["ERROR"] == 0
    assert wall <= 180.0


# ------------------------------------------------------------------ shell grid on SM1
def test_shell_grid(shell_golden, tmp_path):
    g = shell_golden
    dep = g["names"]["B1"]["BEAD_DEPTH"]
    wid = g["names"]["B3"]["BEAD_WIDTH"]
    viol = g["names"]["B5"]["BEAD_DEPTH"]
    cells = [("nominal", {}), ("b1_depth", {dep: next(f["nominal"] for f in g["features"]["features"] if f["name"] == dep) + 0.4}), ("b5_viol", {viol: 3.3}),
             ("b3_width", {wid: 31.5})]
    thumb = dict(THUMB, disp_range_mm=[0.0, 1.0], edges=True)
    out = tmp_path / "g"
    code, text = grid(g, out, cells, thumb=thumb, tag=False, shell=True)
    assert code == 0, text
    gm = load(out / "grid_manifest.json")
    st = {c["id"]: c for c in gm["cells"]}
    assert gm["kind"] == "shell" and [c["id"] for c in gm["cells"]] == [c for c, _ in cells]
    assert st["nominal"]["status"] == "OK" and st["b1_depth"]["status"] == "OK" and st["b3_width"]["status"] == "OK"
    assert (st["b5_viol"]["status"], st["b5_viol"]["code"], st["b5_viol"]["category"]) == ("FAIL", "SHELL_FIXED_REGION_VIOLATION", "FIXED")
    # V-DP-2 on SM1: cell = ``shell view preview --fe off --fixed-dir``
    for cid, vals in cells[1:3]:
        vp = write_json(tmp_path / f"{cid}_v.json", {"schema_version": 1, "values": vals})
        code, text = run_cli("shell", "view", "preview", "--cad", g["step"], "--features", g["features_path"], "--values", vp, "--fixed-dir", g["fixed_dir"],
                             "--out-dir", tmp_path / f"p_{cid}")
        assert code in (0, 10), text
        a, ta = manifest_wo(out / "cells" / cid / "preview_manifest.json", "timing", "thumb")
        b, tb = manifest_wo(tmp_path / f"p_{cid}" / "preview_manifest.json", "timing")
        assert a == b and ta == tb, cid
        if (tmp_path / f"p_{cid}" / "preview.glb").exists():
            assert (out / "cells" / cid / "preview.glb").read_bytes() == (tmp_path / f"p_{cid}" / "preview.glb").read_bytes()
    # nominal GLB = ``shell view export --fixed-dir``
    code, text = run_cli("shell", "view", "export", "--cad", g["step"], "--features", g["features_path"], "--fixed-dir", g["fixed_dir"], "--out-dir", tmp_path / "e")
    assert code == 0, text
    assert gm["nominal"]["view_sha256"] == load(tmp_path / "e" / "view_manifest.json")["glb"]["sha256"]
    # FAIL thumbnail: the violating bead red; determinism of a cell in another grid
    assert red_pixels(read_png(out / "cells" / "b5_viol" / "thumb.png")).sum() > 10
    out2 = tmp_path / "g2"
    code, text = grid(g, out2, [cells[3], cells[1]], thumb=thumb, tag=False, shell=True)
    assert code == 0, text
    for cid in ("b1_depth", "b3_width"):
        assert (out / "cells" / cid / "thumb.png").read_bytes() == (out2 / "cells" / cid / "thumb.png").read_bytes()
        assert (out / "cells" / cid / "preview.glb").read_bytes() == (out2 / "cells" / cid / "preview.glb").read_bytes()
    assert load(out2 / "grid_manifest.json")["camera"] == gm["camera"]
