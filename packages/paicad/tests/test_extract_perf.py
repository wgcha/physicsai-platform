"""extract speed-ups are result-invariant (geometry-engine.md section 17.2 PATCH): every pre-filter, cache and early
exit gives byte-identical ``parameter_features.json`` / ``parameter_extracted.xml`` to the plain reference loops.

Reference mode = the 0.10.0 algorithms (all O(n^2) pairs, full ``_overlap`` both ways, all 16 material points,
a fresh solid classifier per ``points_inside`` call, no sample cache, all feature pairs for symmetry).
"""

from __future__ import annotations

import json
import math
from types import SimpleNamespace

import numpy as np
import pytest
from conftest import run_cli
from paicad import features

pytest.importorskip("build123d")


def _ref_pair_candidates(faces, cos_par, material):
    n = len(faces)
    for i in range(n):
        for j in range(i + 1, n):
            yield i, j


def _ref_mirror_candidates(feats, tol_of):
    for i in range(len(feats)):
        for j in range(i + 1, len(feats)):
            yield i, j


def _ref_overlap_ok(ctx, a, b, check_material):
    r1, pa, fb = features._overlap(ctx.body, a, b, ctx.grid)
    if r1 < ctx.overlap_min:
        return False
    r2, _, _ = features._overlap(ctx.body, b, a, ctx.grid)
    if r2 < ctx.overlap_min:
        return False
    if check_material and len(pa):
        idx = np.linspace(0, len(pa) - 1, min(len(pa), 16)).astype(int)
        mid = 0.5 * (pa[idx] + fb[idx])
        if ctx.body.points_inside(mid).mean() < 0.5:
            return False
    return True


@pytest.fixture
def reference_mode(monkeypatch):
    from OCP.BRepClass3d import BRepClass3d_SolidClassifier
    from OCP.gp import gp_Pnt
    from OCP.TopAbs import TopAbs_IN
    from paicad.kernel import occ

    def fresh_points_inside(self, pts):
        pts = np.asarray(pts, dtype=float).reshape(-1, 3)
        res = np.zeros(len(pts), dtype=bool)
        cls = BRepClass3d_SolidClassifier(self._solid)
        for i, q in enumerate(pts):
            cls.Perform(gp_Pnt(*q), 1e-7)
            res[i] = cls.State() == TopAbs_IN
        return res

    monkeypatch.setattr(occ.OccBody, "points_inside", fresh_points_inside)
    monkeypatch.setattr(occ.OccBody, "sample_face", lambda self, fid, n: self._sample_face(fid, n))
    monkeypatch.setattr(features, "_pair_candidates", _ref_pair_candidates)
    monkeypatch.setattr(features, "_overlap_ok", _ref_overlap_ok)
    monkeypatch.setattr(features, "_mirror_candidates", _ref_mirror_candidates)
    from paicad import render

    monkeypatch.setattr(render, "_raster", render._raster_loop)
    monkeypatch.setattr(render, "_HIGHLIGHT_CACHE", 0)


def _extract(cad, out, *extra, png=False):
    code, log = run_cli("extract", "--cad", cad, "--out-dir", out, *([] if png else ["--no-png"]), *extra)
    assert code == 0, log
    files = {n: (out / n).read_bytes() for n in ("parameter_features.json", "parameter_extracted.xml")}
    if png:
        files |= {f"features/{q.name}": q.read_bytes() for q in sorted((out / "features").glob("*.png"))}
    return files


@pytest.fixture(scope="module")
def heavy_small(tmp_path_factory):
    """Small load-test cushion (ribs, filleted ribs, drafted/filleted pockets, holes, bottom pockets)."""
    from data.make_heavy import HeavySpec, write

    return write(tmp_path_factory.mktemp("heavy") / "heavy.step", HeavySpec(nx=4, ny=3))


@pytest.fixture(scope="module")
def heavy_fast(heavy_small, tmp_path_factory):
    out = tmp_path_factory.mktemp("heavy_fast") / "o"
    return out, _extract(heavy_small, out, png=True)


def test_heavy_extract_matches_reference(heavy_small, heavy_fast, reference_mode, tmp_path):
    """JSON, XML and every feature PNG (shared highlight faces, slivers) byte-identical to the reference."""
    _, fast = heavy_fast
    ref = _extract(heavy_small, tmp_path / "ref", png=True)
    assert sum(n.endswith(".png") for n in fast) >= 50
    assert fast == ref
    d = json.loads(fast["parameter_features.json"])
    assert d["bodies"][0]["faces"] >= 80 and len(d["features"]) >= 50


def test_golden_extract_matches_reference(golden, reference_mode, tmp_path):
    ref = _extract(golden["step"], tmp_path / "ref", "--renum-csv", golden["renum"], png=True)
    assert sum(n.endswith(".png") for n in ref) == len(json.loads(ref["parameter_features.json"])["features"])
    for name, data in ref.items():
        assert data == (golden["extract_dir"] / name).read_bytes(), name


def test_extract_progress_and_timing_log(heavy_fast, capsys):
    out, _ = heavy_fast
    log = (out / "paicad.log").read_text(encoding="utf-8")
    assert "INFO [extract] CAD loaded: 1 bodies" in log
    assert "INFO [extract] CUSH_H: topology:" in log and "thickness pairs checked" in log
    assert "INFO [extract] PNG " in log and "INFO [extract] feature PNGs:" in log
    line = next(x for x in log.splitlines() if x.startswith("EXTRACT_TIMING "))
    t = json.loads(line[len("EXTRACT_TIMING ") :])
    for k in ("load_s", "recognize_s", "finalize_s", "feasible_s", "symmetry_s", "png_s", "png_render_s", "total_s"):
        assert isinstance(t[k], (int, float)) and t[k] >= 0
    b = t["bodies"]["CUSH_H"]
    assert b["overlap_checks"] >= b["overlap_prefiltered"] > 0 and b["thickness_pairs"] > 0
    assert "timing" not in json.loads((out / "parameter_features.json").read_text(encoding="utf-8"))


def test_extract_progress_goes_to_stderr(heavy_small, tmp_path, capsys):
    _extract(heavy_small, tmp_path / "o")
    cap = capsys.readouterr()
    assert "[extract] CUSH_H: topology:" in cap.err and "[extract] total" in cap.err
    assert "[extract]" not in cap.out


# ------------------------------------------------------------- pre-filters alone
def _rand_faces(rng, n, cos_par):
    """Plane-like faces: normals on the 6 axes, jittered around the draft threshold, plus random ones."""
    out = []
    axes = np.vstack([np.eye(3), -np.eye(3)])
    ang = math.acos(cos_par)
    for k in range(n):
        nrm = axes[k % 6].copy()
        if k % 3:
            t = rng.normal(size=3)
            t -= t.dot(nrm) * nrm
            t /= np.linalg.norm(t)
            a = ang * (1.0 + rng.choice([-1e-12, 0.0, 1e-12, 1e-3, -1e-3, 0.5]))
            nrm = math.cos(a) * nrm + math.sin(a) * t
        if k % 17 == 0:
            nrm = rng.normal(size=3)
        nrm /= np.linalg.norm(nrm)
        c = rng.uniform(-500, 500, size=3)
        if k % 5 == 0 and out:
            c = out[-1].centroid.copy()  # coincident centroids: s_a = s_b = 0 exactly
        out.append(SimpleNamespace(id=k + 1, normal=nrm, centroid=c))
    return out


@pytest.mark.parametrize("material", [True, False])
def test_pair_candidates_keep_every_exact_pair(material):
    rng = np.random.default_rng(7)
    ctx = SimpleNamespace(cos_par=math.cos(math.radians(3.0)))
    faces = _rand_faces(rng, 700, ctx.cos_par)  # > one pre-filter block
    fast = features._pairs_across(ctx, faces, material)
    orig = features._pair_candidates
    try:
        features._pair_candidates = _ref_pair_candidates
        ref = features._pairs_across(ctx, faces, material)
    finally:
        features._pair_candidates = orig
    assert len(ref) > 100
    assert [(a.id, b.id, d, dr) for a, b, d, dr in fast] == [(a.id, b.id, d, dr) for a, b, d, dr in ref]


@pytest.mark.parametrize("which", ["golden", "heavy"])
def test_overlap_shortcuts_agree_with_full_overlap(which, golden, heavy_small):
    """Every opposed plane pair (what recognition asks about): bbox miss => ratio 0 (unclamped targets only);
    early-exit scan == full ratio test."""
    from paicad import cadload, options

    opts = options.load(None)
    omin, grid = opts["extract"]["overlap_min"], opts["extract"]["sample_grid"]
    body = cadload.load(golden["step"] if which == "golden" else heavy_small).bodies[0]
    ctx = features._Ctx(body, opts)
    planes = ctx.planes
    if which == "heavy":
        planes = planes[::2]  # keep the test short; still covers ribs, pockets and drafted B-spline walls
    clamped = [f for f in planes if features._bbox_margin_for(ctx, f) is None]
    assert clamped, "drafted pocket walls are planar B-splines (clamping projection) in both sets"
    checked = misses = 0
    for a in planes:
        for b in planes:
            if a.id == b.id or float(np.dot(a.normal, b.normal)) > -0.9:
                continue
            r, pa, fb = features._overlap(body, a, b, grid)
            mb = features._bbox_margin_for(ctx, b)
            if mb is not None and features._projection_misses(a, b, mb):
                misses += 1
                assert r == 0.0, (a.id, b.id)
                continue
            ok, pa2, fb2 = features._overlap_at_least(body, a, b, grid, omin, mb, full=True)
            assert ok == (not r < omin), (a.id, b.id)
            if ok:
                assert np.array_equal(pa, pa2) and np.array_equal(fb, fb2)
            ok3, _, _ = features._overlap_at_least(body, a, b, grid, omin, mb, full=False)
            assert ok3 == ok
            checked += 1
    assert checked > 5 and misses > 5


def test_mostly_inside_matches_mean(golden):
    from paicad import cadload

    body = cadload.load(golden["step"]).bodies[0]
    bb = body.summary().bbox
    rng = np.random.default_rng(3)
    for m in (1, 2, 5, 15, 16):
        for _ in range(4):
            pts = bb[:3] + rng.random((m, 3)) * (bb[3:] - bb[:3])
            assert features._mostly_inside(body, pts) == (not body.points_inside(pts).mean() < 0.5)


def test_mirror_candidates_superset():
    """Pairs dropped by the candidate filter fail ``_is_mirror`` before any geometry (type / face count / nominal)."""
    rng = np.random.default_rng(11)
    feats = [
        features.Feature(t, b, float(rng.choice([5.0, 5.04, 5.06, 7.0, 12.5])), list(range(int(rng.integers(1, 3)))), [], [])
        for t, b in zip(rng.choice(["THICKNESS", "RIB_HEIGHT", "HOLE_RADIUS"], 300), rng.choice(["A", "B"], 300))
    ]
    tol_of = {"A": 0.05, "B": 0.02}
    cand = set(features._mirror_candidates(feats, tol_of))
    assert list(features._mirror_candidates(feats, tol_of)) == sorted(cand)
    for i in range(len(feats)):
        for j in range(i + 1, len(feats)):
            a, b = feats[i], feats[j]
            tol = max(tol_of[a.body], tol_of[b.body])
            may = a.type == b.type and len(a.faces) == len(b.faces) and not abs(a.nominal - b.nominal) > tol
            if may:
                assert (i, j) in cand


# ------------------------------------------------------------- feature PNG rasterizer
def test_batched_raster_equals_loop():
    from paicad import render

    rng = np.random.default_rng(5)
    n = 1200
    ctr = np.repeat(np.c_[rng.uniform(-50, render.W + 50, n // 6), rng.uniform(-50, render.H + 50, n // 6)], 6, axis=0)
    P = np.c_[ctr + rng.normal(0, 25, (n, 2)), rng.normal(0, 50, n)]  # local triangles, some crossing the frame
    P[::7, 2] = 3.0  # equal depths: the first triangle must win
    tris = np.sort(rng.integers(0, n, size=(1500, 3)), axis=1)
    tris[:, 1:] = np.minimum(tris[:, :1] + rng.integers(0, 6, size=(1500, 2)), n - 1)  # mostly near vertices
    tris[::300] = rng.integers(0, n, size=(5, 3))  # a few frame-sized ones
    tris[::11, 2] = tris[::11, 1]  # degenerate
    sl = np.arange(1, 1500, 13)
    P[tris[sl, 1], :2] = P[tris[sl, 0], :2] + rng.normal(0, 0.3, (len(sl), 2))  # slivers / tiny triangles
    shade = rng.random(len(tris))
    for chunk in (render._FRAG_CHUNK, 1000):
        za, ca = np.full((render.H, render.W), -np.inf), np.zeros((render.H, render.W))
        zb, cb = za.copy(), ca.copy()
        za[100:200, 100:200] = 10.0  # pre-filled buffer: strict 'nearer' rule
        zb[100:200, 100:200] = 10.0
        render._raster_loop(P, tris, shade, za, ca)
        old = render._FRAG_CHUNK
        try:
            render._FRAG_CHUNK = chunk
            render._raster(P, tris, shade, zb, cb)
        finally:
            render._FRAG_CHUNK = old
        assert np.array_equal(za, zb) and np.array_equal(ca, cb)


def test_png_rows_unchanged():
    import struct
    import zlib

    from paicad import render

    img = np.random.default_rng(2).uniform(-5, 260, (render.H, render.W, 3))
    a = np.clip(np.rint(img), 0, 255).astype(np.uint8)
    raw = b"".join(b"\x00" + a[y].tobytes() for y in range(render.H))
    assert zlib.compress(raw, 6) in render.png_bytes(img)
    assert render.png_bytes(img)[16:24] == struct.pack(">II", render.W, render.H)
