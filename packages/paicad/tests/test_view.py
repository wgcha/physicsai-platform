"""paicad 0.9.0: ``paicad view export|preview`` (geometry-view.md sections 4, 5, 8 GV-1/GV-3/GV-4, V-GV-*).

Virtual golden: the development cushion (``data/make_synthetic.py``); the truth of every preview is the
build123d cushion rebuilt with the changed dimension. GLB files are parsed with the independent
``gltf_check`` reader (glTF 2.0 structure checks, no external library). Nothing generated is committed.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import tomllib
from dataclasses import replace
from pathlib import Path

import gltf_check as gc
import numpy as np
import paicad
import pytest
from conftest import PKG, run_cli
from paicad.kernel import load_brep, load_cad
from paicad.meshgeom import TriangleSet

LIN = 0.1  # default view_options tess.linear_mm
FACE_TOL = LIN + 0.01  # section 8 GV-1 / GV-3 tolerance


def load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def write_json(path, obj):
    Path(path).write_text(json.dumps(obj), encoding="utf-8")
    return path


def export(g, out, *extra):
    return run_cli("view", "export", "--cad", g["step"], "--features", g["features_path"], "--out-dir", out, *extra)


def preview(g, out, values, *extra, tag=True):
    vp = write_json(Path(out).parent / f"{Path(out).name}_values.json", {"schema_version": 1, "values": values})
    args = ["view", "preview", "--cad", g["step"], "--features", g["features_path"], "--values", vp, "--out-dir", out, *extra]
    if tag:
        args += ["--tag-dir", g["tag_dir"]]
    code, text = run_cli(*args)
    return code, text, vp


def fe_args(g, mode):
    return ["--fe", mode, "--baseline-inc", g["baseline"], "--renum-csv", g["renum"], "--assem-dir", g["assem"]]


def cad_bodies(g) -> dict:
    _, bodies = load_cad(g["step"])
    return {b.name: b for b in bodies}


def truth_bodies(spec, path) -> dict:
    from data.make_synthetic import build_bodies, write_step

    write_step(path, build_bodies(spec))
    _, bodies = load_cad(path)
    return {b.name: b for b in bodies}


def mesh_tris(m: dict) -> np.ndarray:
    return m["POSITION"].astype(float)[m["indices"]]


@pytest.fixture(scope="session")
def view_dir(golden):
    out = golden["root"] / "out" / "view"
    code, text = export(golden, out)
    assert code == 0, text
    return out


# ------------------------------------------------------------------ GV-1: nominal view
def test_export_glb_structure(golden, view_dir):
    doc, bin_ = gc.load(view_dir / "view.glb")
    m = load(view_dir / "view_manifest.json")
    names = [b["body"] for b in golden["features"]["bodies"]]
    assert doc["asset"] == {"version": "2.0", "generator": f"paicad {paicad.__version__}"}
    root = doc["nodes"][doc["scenes"][doc["scene"]]["nodes"][0]]
    assert root["name"] == "paicad_view" and root["extras"] == {"unit": "mm", "up_axis": "Z"} and "matrix" not in root
    assert [doc["nodes"][c]["name"] for c in root["children"]] == [x for n in names for x in (n, f"{n}.edges")]
    assert all("matrix" not in n and "translation" not in n and "rotation" not in n and "scale" not in n for n in doc["nodes"])
    for n in names:
        mesh = doc["meshes"][next(x["mesh"] for x in doc["nodes"] if x["name"] == n)]
        prim = mesh["primitives"][0]
        assert prim["mode"] == 4 and set(prim["attributes"]) == {"POSITION", "NORMAL", "_FACE_ID"}
        assert doc["accessors"][prim["attributes"]["_FACE_ID"]]["componentType"] == 5123  # UNSIGNED_SHORT (faces <= 65535)
        assert doc["accessors"][prim["indices"]]["componentType"] == 5123  # vertices < 65536
        assert doc["materials"][prim["material"]]["doubleSided"] is False  # solid
        e = gc.node_mesh(doc, bin_, f"{n}.edges")
        assert e["_mode"] == 1 and set(e) == {"POSITION", "_EDGE_ID", "indices", "_mode"}
        topo = cad_bodies(golden)[n].topology()
        assert set(np.unique(e["_EDGE_ID"]).tolist()) <= {x.id for x in topo.edges}
    assert (m["unit"], m["up_axis"], m["kind"], m["mode"], m["status"]) == ("mm", "Z", "solid", "nominal", "OK")
    assert m["engine_version"] == paicad.__version__ and m["schema_version"] == 1 and m["fixed_clusters"] == []
    assert m["glb"]["bytes"] == (view_dir / "view.glb").stat().st_size and m["tess"] == {"linear_mm": 0.1, "angular_deg": 20.0, "coarsened": 0}
    assert m["source"]["cad"] == golden["features"]["cad"]["files"]


def test_face_id_matches_brep_faces(golden, view_dir):
    """Section 8 GV-1 (1): triangle centre <-> face of its _FACE_ID, no other face closer, faces[].tri ranges."""
    doc, bin_ = gc.load(view_dir / "view.glb")
    m = load(view_dir / "view_manifest.json")
    bodies = cad_bodies(golden)
    assert not [w for w in m["warnings"] if w["code"] == "VIEW_FACE_EMPTY"]
    for brow in m["bodies"]:
        body = bodies[brow["body"]]
        topo = body.topology()
        g = gc.node_mesh(doc, bin_, brow["node"])
        tri, fid = g["indices"], g["_FACE_ID"].astype(np.int64)
        tface = fid[tri]
        assert (tface == tface[:, :1]).all()  # same id on the three vertices
        owner = np.zeros(len(fid), dtype=np.int64)
        for k in range(3):
            owner[tri[:, k]] = tface[:, 0]
        assert np.array_equal(owner, fid)  # every vertex belongs to the triangles of one face only (no sharing)
        tf = tface[:, 0]
        assert (np.diff(tf) >= 0).all() and set(tf.tolist()) == {f.id for f in topo.faces}  # ascending, every face >= 1 triangle
        assert [r["id"] for r in brow["faces"]] == [f"F{f.id}" for f in topo.faces]
        for r in brow["faces"]:
            first, cnt = r["tri"]
            assert cnt >= 1 and (tf[first : first + cnt] == int(r["id"][1:])).all()
            assert r["surface"] == topo.face(int(r["id"][1:])).surface
        assert sum(r["tri"][1] for r in brow["faces"]) == len(tri)
        cen = g["POSITION"].astype(float)[tri].mean(axis=1)
        dist = np.full((len(cen), len(topo.faces)), np.inf)
        for f in topo.faces:
            d, _, inside, _ = body.project_to_face(f.id, cen)
            dist[inside, f.id - 1] = d[inside]
        own = dist[np.arange(len(cen)), tf - 1]
        assert own.max() <= FACE_TOL, brow["body"]
        other = dist.copy()
        other[np.arange(len(cen)), tf - 1] = np.inf
        assert int((other.min(axis=1) < own - 0.01).sum()) == 0


def test_dimensions_equal_extract_nominal(golden, view_dir):
    m = load(view_dir / "view_manifest.json")
    feats = {f["name"]: f for f in golden["features"]["features"]}
    assert [f["name"] for f in m["features"]] == list(feats)
    approx = {w["feature"] for w in m["warnings"] if w["code"] == "VIEW_DIM_APPROX"}
    groups = {mm: g["parameter"] for g in golden["features"]["groups"] for mm in g["members"]}
    for row in m["features"]:
        f = feats[row["name"]]
        d = row["dimension"]
        assert d is not None and d["unit"] == "mm" and d["kind"] in ("linear", "radius", "position")
        assert type(d["value"]) is float and d["value"] == f["nominal"] == row["value"] == row["nominal"]  # same float
        assert row["range"] == f["range"] and {k: v for k, v in row["feasible"].items() if k != "source"} == f["feasible"]
        assert row["feasible"]["source"] == "estimate" and row["parameter"] == groups.get(row["name"], row["name"])
        assert row["faces"]["moving"] == f["faces"]["moving"] and row["faces"]["fixed"] == f["faces"]["fixed"]
        geom = float(np.linalg.norm(np.subtract(d["p1"], d["p0"])))
        assert abs(geom - d["geom_len"]) <= 1e-5
        if row["name"] not in approx:
            assert abs(d["geom_len"] - f["nominal"]) <= 0.05, row["name"]
        kind = {"HOLE_RADIUS": "radius", "FILLET_RADIUS": "radius", "HOLE_POS_U": "position", "HOLE_POS_V": "position"}.get(f["type"], "linear")
        assert d["kind"] == kind


def test_dimension_points_kinds(golden, view_dir):
    m = {f["name"]: f for f in load(view_dir / "view_manifest.json")["features"]}
    thk = m["CUSH_L_THK_3"]["dimension"]  # base thickness: bottom/top pair, line along z
    assert thk["p0"][:2] == thk["p1"][:2] and abs(thk["p1"][2] - thk["p0"][2]) == pytest.approx(20.0)
    hu = m["CUSH_L_HOLE_U_1"]["dimension"]  # position: bbox minimum plane (x = -150) -> hole axis (x = -138)
    assert hu["p0"][0] == pytest.approx(-150.0) and hu["p1"][0] == pytest.approx(-138.0) and hu["p0"][1:] == hu["p1"][1:]
    hr = m["CUSH_L_HOLE_R_1"]["dimension"]
    assert hr["kind"] == "radius" and hr["p0"][:2] == pytest.approx([-138.0, 12.0]) and hr["geom_len"] == pytest.approx(5.0)
    r1, r2 = m["CUSH_L_RIB_H_1"]["dimension"], m["CUSH_L_RIB_H_2"]["dimension"]  # each rib gets its own line
    assert r1["p0"] != r2["p0"] and r1["geom_len"] == pytest.approx(15.0)


def test_export_is_byte_identical(golden, view_dir, tmp_path):
    code, text = export(golden, tmp_path / "v2")
    assert code == 0, text
    for n in ("view.glb", "view_manifest.json"):
        assert (tmp_path / "v2" / n).read_bytes() == (view_dir / n).read_bytes(), n


def test_export_lod_coarsening_and_too_large(golden, view_dir, tmp_path):
    base = load(view_dir / "view_manifest.json")["glb"]["bytes"]
    # GLB byte limit just under the default result -> one coarsening step
    vo = write_json(tmp_path / "vo.json", {"schema_version": 1, "max_glb_bytes": base - 1})
    code, text = export(golden, tmp_path / "a", "--view-options", vo)
    m = load(tmp_path / "a" / "view_manifest.json")
    assert code == 0, text
    assert m["tess"]["coarsened"] >= 1 and m["tess"]["linear_mm"] == 0.1 * 2 ** m["tess"]["coarsened"]
    assert [w for w in m["warnings"] if w["code"] == "VIEW_COARSENED"][0]["coarsened"] == m["tess"]["coarsened"]
    assert m["glb"]["bytes"] <= base - 1
    # triangle limit: fine tolerances give > 1000 triangles -> re-tessellated with larger tolerances
    vo2 = write_json(tmp_path / "vo2.json", {"schema_version": 1, "tess": {"linear_mm": 0.001, "angular_deg": 5}, "max_triangles": 1000, "coarsen_steps": 5})
    code, text = export(golden, tmp_path / "b", "--view-options", vo2)
    m2 = load(tmp_path / "b" / "view_manifest.json")
    assert code == 0, text
    assert m2["tess"]["coarsened"] >= 1 and m2["glb"]["triangles"] <= 1000 and m2["tess"]["angular_deg"] == min(45.0, 5.0 * 2 ** m2["tess"]["coarsened"])
    # impossible limit -> VIEW_TOO_LARGE, exit 14, FAIL manifest without GLB
    vo3 = write_json(tmp_path / "vo3.json", {"schema_version": 1, "max_glb_bytes": 1000, "coarsen_steps": 1})
    code, text = export(golden, tmp_path / "c", "--view-options", vo3)
    m3 = load(tmp_path / "c" / "view_manifest.json")
    assert code == 14 and "PAICAD RESULT FAIL VIEW_TOO_LARGE view_manifest.json" in text
    assert (m3["status"], m3["code"], m3["category"], m3["glb"]) == ("FAIL", "VIEW_TOO_LARGE", "VIEW", None)
    assert not (tmp_path / "c" / "view.glb").exists()


def test_export_without_edges_and_option_errors(golden, tmp_path):
    vo = write_json(tmp_path / "vo.json", {"schema_version": 1, "edges": False})
    code, text = export(golden, tmp_path / "a", "--view-options", vo)
    assert code == 0, text
    doc, _ = gc.load(tmp_path / "a" / "view.glb")
    assert not [n for n in doc["nodes"] if n.get("name", "").endswith(".edges")]
    assert all(b["edges_node"] is None for b in load(tmp_path / "a" / "view_manifest.json")["bodies"])
    for bad in ({"tess": {"linear_mm": 0}}, {"tess": {"angular_deg": 50}}, {"max_triangles": 10}, {"coarsen_steps": 6}, {"edgez": True}, {"tess": {"lin": 1}}):
        vb = write_json(tmp_path / "bad.json", dict({"schema_version": 1}, **bad))
        out = tmp_path / f"bad_{len(list(tmp_path.iterdir()))}"
        code, text = export(golden, out, "--view-options", vb)
        assert code == 3 and "GEOM_INPUT_INVALID" in text, bad
        assert load(out / "view_manifest.json")["code"] == "GEOM_INPUT_INVALID"
    code, text = export(golden, tmp_path / "a")
    assert code == 3 and "GEOM_OUTPUT_EXISTS" in text


def test_export_tessellation_failure_exit_14(golden, tmp_path, monkeypatch):
    from paicad.kernel import occ

    def boom(self, *a, **k):
        raise RuntimeError("Standard_Failure")

    monkeypatch.setattr(occ.OccBody, "tessellate", boom)
    code, text = export(golden, tmp_path / "f")
    assert code == 14 and "VIEW_TESSELLATION_FAILED" in text
    assert load(tmp_path / "f" / "view_manifest.json")["code"] == "VIEW_TESSELLATION_FAILED"


# ------------------------------------------------------------------ GV-3: preview (update only)
def _cases(g):
    from data.make_synthetic import CushionSpec

    s = CushionSpec()
    return {
        "THICKNESS": ({"CUSH_L_THK_3": 22.0}, replace(s, T=22.0), [("CUSH_L", "CUSH_L_THK_3", 2.0)]),
        "HOLE_POS": ({"CUSH_L_HOLE_U_1": 15.0, "CUSH_R_HOLE_U_1": 105.0}, replace(s, hole_xy=(15.0, 12.0)), [("CUSH_L", "CUSH_L_HOLE_U_1", 3.0), ("CUSH_R", "CUSH_R_HOLE_U_1", 3.0)]),
        "HOLE_RADIUS": ({"CUSH_L_HOLE_R_1": 5.5}, replace(s, hole_r=5.5), [("CUSH_L", "CUSH_L_HOLE_R_1", 0.5)]),
    }


@pytest.mark.parametrize("cid", ["THICKNESS", "HOLE_POS", "HOLE_RADIUS"])
def test_preview_matches_truth(golden, view_dir, tmp_path, cid):
    values, spec, moved = _cases(golden)[cid]
    out = tmp_path / "p"
    code, text, vp = preview(golden, out, values, "--nominal-manifest", view_dir / "view_manifest.json")
    assert code == 0, text
    m = load(out / "preview_manifest.json")
    nom = load(view_dir / "view_manifest.json")
    assert (m["status"], m["mode"], m["fe"], m["failure"]) == ("OK", "preview", {"mode": "off"}, None)
    assert m["nominal_ref"] == {"view_sha256": nom["glb"]["sha256"], "tess": {"linear_mm": 0.1, "angular_deg": 20.0}}
    assert m["reports"] == {"update": "update/update.json", "morph": None, "check": None}
    assert sorted(p.name for p in out.iterdir()) == ["paicad.log", "preview.glb", "preview_manifest.json", "update"]
    doc, bin_ = gc.load(out / "preview.glb")
    truth = truth_bodies(spec, tmp_path / "truth.step")
    for brow in m["bodies"]:
        g = gc.node_mesh(doc, bin_, brow["node"])
        assert set(g) >= {"POSITION", "NORMAL", "_FACE_ID", "_DISP_MM"}
        t = truth[brow["body"]]
        # (1) GLB vertices on the truth shape and truth surface samples on the GLB (both directions)
        assert t.distance(g["POSITION"].astype(float)).max() <= FACE_TOL, brow["body"]
        samples = np.concatenate([t.sample_face(f.id, 6) for f in t.topology().faces])
        d, _ = TriangleSet(mesh_tris(g)).distance(samples, cutoff=1.0)
        assert d.max() <= FACE_TOL, brow["body"]
        # _DISP_MM = the manifest by_face statistics
        tf = g["_FACE_ID"].astype(np.int64)
        for fid, st in m["disp"]["by_face"][brow["body"]].items():
            sel = tf == int(fid[1:])
            assert float(g["_DISP_MM"][sel].max()) == pytest.approx(st["max"], abs=1e-5)
    # (2) moved faces: max = |delta| +- 1e-3, fixed faces 0
    u = load(out / "update" / "update.json")
    for body, name, delta in moved:
        a = next(x for x in u["applied"] if x["name"] == name)
        for f in a["moved"]:
            st = m["disp"]["by_face"][body][f]
            assert st["max"] == pytest.approx(delta, abs=1e-3) and st["change"] == "geometry"
        for f in a["fixed"]:
            assert m["disp"]["by_face"][body][f]["max"] == 0.0
    assert m["disp"]["max_mm"] == pytest.approx(max(d for _, _, d in moved), abs=1e-3)
    # (3) same B-rep as a standalone ``paicad update``
    code, text = run_cli("update", "--cad", golden["step"], "--features", golden["features_path"], "--values", vp, "--out-dir", tmp_path / "u", "--tag-dir", golden["tag_dir"])
    assert code == 0, text
    names = [b["body"] for b in golden["features"]["bodies"]]
    a = load_brep(tmp_path / "u" / "sample.brep", names)
    b = load_brep(out / "update" / "sample.brep", names)
    for x, y in zip(a, b):
        for f in x.topology().faces:
            pts = x.sample_face(f.id, 4)
            if len(pts):
                assert y.distance(pts).max() <= 1e-9
    ua, ub = load(tmp_path / "u" / "update.json"), u
    assert {k: v for k, v in ua.items() if k != "elapsed_s"} == {k: v for k, v in ub.items() if k != "elapsed_s"}
    assert (tmp_path / "u" / "face_map.json").read_bytes() == (out / "update" / "face_map.json").read_bytes()
    # dimension value = input value (group members follow the representative)
    fv = {f["name"]: f["value"] for f in m["features"]}
    for k, v in values.items():
        assert fv[k] == v and next(f for f in m["features"] if f["name"] == k)["dimension"]["value"] == v


def test_preview_is_deterministic(golden, view_dir, tmp_path):
    vals = {"CUSH_L_RIB_H_1": 16.5}
    outs = []
    for k in range(2):
        code, text, _ = preview(golden, tmp_path / f"p{k}", vals, "--nominal-manifest", view_dir / "view_manifest.json")
        assert code == 0, text
        outs.append(tmp_path / f"p{k}")
    assert (outs[0] / "preview.glb").read_bytes() == (outs[1] / "preview.glb").read_bytes()
    a, b = (load(o / "preview_manifest.json") for o in outs)
    a.pop("timing"), b.pop("timing")
    assert a == b
    ta = (outs[0] / "preview_manifest.json").read_text(encoding="utf-8").split('"timing"')[0]
    tb = (outs[1] / "preview_manifest.json").read_text(encoding="utf-8").split('"timing"')[0]
    assert ta == tb  # byte identical up to the timing block (last key)


def test_preview_collision_failure(golden, tmp_path):
    out = tmp_path / "p"
    code, text, _ = preview(golden, out, {"CUSH_R_HOLE_U_1": 86.4})  # hole runs into the rib foot print (0.4.0)
    assert code == 10 and "PAICAD RESULT FAIL GEOM_FEATURE_COLLISION preview_manifest.json" in text
    m = load(out / "preview_manifest.json")
    assert (m["status"], m["code"], m["category"], m["glb"], m["disp"]) == ("FAIL", "GEOM_FEATURE_COLLISION", "CAD_FAILED", None, None)
    assert len(m["failure"]["features"]) == 2 and "CUSH_R_HOLE_U_1" in m["failure"]["features"]
    u = load(out / "update" / "update.json")
    assert u["status"] == "FAIL" and u["code"] == "GEOM_FEATURE_COLLISION" and u["collisions"]
    assert not (out / "preview.glb").exists() and not (out / "update" / "sample.brep").exists()


def test_preview_input_and_argument_errors(golden, tmp_path):
    code, text, _ = preview(golden, tmp_path / "a", {"NO_SUCH": 1.0})
    assert code == 3 and load(tmp_path / "a" / "preview_manifest.json")["code"] == "GEOM_INPUT_INVALID"
    code, text, _ = preview(golden, tmp_path / "b", {"CUSH_L_THK_3": 21.0}, "--fe", "morph")  # FE arguments missing
    assert code == 2 and not (tmp_path / "b" / "preview_manifest.json").exists()
    bad = write_json(tmp_path / "nm.json", {"status": "OK"})
    code, text, _ = preview(golden, tmp_path / "c", {}, "--nominal-manifest", bad)
    assert code == 3 and "nominal view manifest" in load(tmp_path / "c" / "preview_manifest.json")["message"]


def test_preview_view_too_large_exit_14(golden, tmp_path):
    vo = write_json(tmp_path / "vo.json", {"schema_version": 1, "max_glb_bytes": 1000, "coarsen_steps": 0})
    code, text, _ = preview(golden, tmp_path / "p", {"CUSH_L_THK_3": 21.0}, "--view-options", vo)
    m = load(tmp_path / "p" / "preview_manifest.json")
    assert code == 14 and (m["status"], m["code"], m["glb"]) == ("FAIL", "VIEW_TOO_LARGE", None)
    assert (tmp_path / "p" / "update" / "sample.brep").exists() and not (tmp_path / "p" / "preview.glb").exists()


def test_preview_speed_single_parameter(golden, view_dir, tmp_path):
    """Section 8 GV-3 (5): whole command incl. process start, target <= 5 s (dev PC), CI limit 15 s."""
    vp = write_json(tmp_path / "v.json", {"schema_version": 1, "values": {"CUSH_L_THK_3": 22.0}})
    env = dict(os.environ, PYTHONPATH=str(PKG / "src") + os.pathsep + os.environ.get("PYTHONPATH", ""))
    cmd = [sys.executable, "-m", "paicad", "view", "preview", "--cad", str(golden["step"]), "--features", str(golden["features_path"]), "--values", str(vp),
           "--tag-dir", str(golden["tag_dir"]), "--nominal-manifest", str(view_dir / "view_manifest.json"), "--out-dir", str(tmp_path / "p")]
    t0 = time.monotonic()
    r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=120)
    wall = time.monotonic() - t0
    assert r.returncode == 0, r.stdout + r.stderr
    m = load(tmp_path / "p" / "preview_manifest.json")
    print(f"\npreview speed: wall {wall:.2f} s (process start included), timing.total_s {m['timing']['total_s']} s, {m['timing']}")
    assert wall <= 15.0 and m["timing"]["total_s"] <= 15.0


# ------------------------------------------------------------------ GV-4: FE preview
def test_preview_fe_morph_matches_standalone_morph(golden, tmp_path):
    from paicad.mesh import radioss
    from paicad.meshdata import components_from_tag, load_tag

    vals = {"CUSH_L_THK_3": 21.0}
    out = tmp_path / "p"
    code, text, vp = preview(golden, out, vals, *fe_args(golden, "morph"))
    assert code == 0, text
    m = load(out / "preview_manifest.json")
    assert m["fe"]["mode"] == "morph" and m["fe"]["status"] == "OK" and m["reports"]["morph"] == "morph/morph.json" and m["reports"]["check"] is None
    assert not list(out.rglob("*.inc")) and not (out / "files").exists() and not (out / "morph" / "morphed.inc").exists()
    assert load(out / "morph" / "morph.json")["status"] == "OK"
    # standalone update + morph
    run_cli("update", "--cad", golden["step"], "--features", golden["features_path"], "--values", vp, "--out-dir", tmp_path / "u", "--tag-dir", golden["tag_dir"])
    code, text = run_cli("morph", "--baseline-inc", golden["baseline"], "--tag-dir", golden["tag_dir"], "--features", golden["features_path"], "--update-dir", tmp_path / "u", "--out-dir", tmp_path / "m")
    assert code == 0, text
    base = radioss.read_mesh(golden["baseline"])
    new = radioss.read_mesh(tmp_path / "m" / "morphed.inc")
    comps = components_from_tag(base, load_tag(golden["tag_dir"]))
    doc, bin_ = gc.load(out / "preview_fe.glb")
    assert m["fe"]["glb"]["sha256"] and m["fe"]["max_disp_mm"] == load(tmp_path / "m" / "morph.json")["max_disp_mm"]
    for c in comps:
        g = gc.node_mesh(doc, bin_, c.part)
        assert set(g) >= {"POSITION", "NORMAL", "_DISP_MM", "_ELEM_ID"}
        assert len(g["indices"]) == len(c.skin)  # skin triangle count = tag skin
        used = np.unique(c.skin)
        rows = c.gidx[used]
        assert np.abs(g["POSITION"].astype(float) - new.xyz[rows]).max() <= 1e-4  # float32 storage of mm coordinates
        disp = np.linalg.norm(new.xyz[rows] - base.xyz[rows], axis=1)
        disp[disp <= 1e-6] = 0
        assert np.abs(g["_DISP_MM"] - disp).max() <= 1e-5
        assert set(g["_ELEM_ID"].tolist()) <= set(c.elem_ids.tolist())
        e = gc.node_mesh(doc, bin_, f"{c.part}.edges")
        assert e["_mode"] == 1


def test_preview_fe_check_pass_and_quality_failure(golden, tmp_path):
    code, text, _ = preview(golden, tmp_path / "ok", {"CUSH_L_THK_3": 21.0}, *fe_args(golden, "check"))
    assert code == 0, text
    m = load(tmp_path / "ok" / "preview_manifest.json")
    assert m["fe"]["status"] == "PASS" and set(m["fe"]["quality"]) == {"min_stretch", "max_aspect", "edge_ratio", "dt_ratio"}
    c = load(tmp_path / "ok" / "check" / "check.json")
    assert c["status"] == "PASS" and c["out_inc"] is None
    assert not list((tmp_path / "ok").rglob("*.inc"))
    # large deformation: geometry fine, mesh too distorted -> GEOM_QUALITY, geometry GLB kept, exit 11
    out = tmp_path / "bad"
    code, text, _ = preview(golden, out, {"CUSH_L_RIB_H_1": 4.0, "CUSH_L_THK_3": 12.5}, *fe_args(golden, "check"))
    m = load(out / "preview_manifest.json")
    assert code == 11 and (m["status"], m["code"]) == ("FAIL", "GEOM_QUALITY")
    assert (m["fe"]["status"], m["fe"]["code"], m["fe"]["category"]) == ("FAIL", "GEOM_QUALITY", "QUALITY")
    assert (out / "preview.glb").exists() and m["glb"] is not None and (out / "preview_fe.glb").exists()
    assert not list(out.rglob("*.inc"))


def test_preview_fe_morph_failure_keeps_geometry_glb(golden, tmp_path, monkeypatch):
    import paicad.view.preview as pv
    from paicad.morph import MorphFailed

    def boom(*a, **k):
        raise MorphFailed("interior solve did not converge")

    monkeypatch.setattr(pv, "morph_core", boom)
    out = tmp_path / "p"
    code, text, _ = preview(golden, out, {"CUSH_L_THK_3": 21.0}, *fe_args(golden, "check"))
    m = load(out / "preview_manifest.json")
    assert code == 11 and "PAICAD RESULT FAIL GEOM_MORPH_FAILED preview_manifest.json" in text
    assert (m["status"], m["code"], m["fe"]["status"], m["fe"]["code"], m["reports"]["check"]) == ("FAIL", "GEOM_MORPH_FAILED", "FAIL", "GEOM_MORPH_FAILED", None)
    assert (out / "preview.glb").exists() and not (out / "preview_fe.glb").exists() and load(out / "morph" / "morph.json")["status"] == "FAIL"


# ------------------------------------------------------------------ units without OCCT, isolation
def test_gltf_writer_unit_large_indices_and_ids():
    from paicad.view import gltf

    n = 70000  # > 65535 vertices -> UNSIGNED_INT indices; ids > 65535 -> UNSIGNED_INT attribute
    pos = np.random.default_rng(0).random((n, 3))
    tri = np.arange(n - n % 3).reshape(-1, 3)
    ids = np.arange(n, dtype=np.int64)
    data = gltf.write_glb([gltf.TriMesh("A", pos, tri, None, {"_FACE_ID": ids.astype(gltf.id_dtype(int(ids.max())))})], "paicad test")
    doc, bin_ = gc.parse_glb(data)
    gc.validate(doc, bin_)
    prim = doc["meshes"][0]["primitives"][0]
    assert doc["accessors"][prim["indices"]]["componentType"] == 5125 and doc["accessors"][prim["attributes"]["_FACE_ID"]]["componentType"] == 5125
    g = gc.node_mesh(doc, bin_, "A")
    assert np.array_equal(g["_FACE_ID"], ids) and np.array_equal(g["indices"], tri)
    small = gltf.write_glb([gltf.TriMesh("B", pos[:3], np.array([[0, 1, 2]]), None, {"_FACE_ID": np.array([7, 7, 7], dtype=np.uint16)})], "x")
    d2, b2 = gc.parse_glb(small)
    gc.validate(d2, b2)
    acc = d2["accessors"][d2["meshes"][0]["primitives"][0]["attributes"]["_FACE_ID"]]
    assert acc["componentType"] == 5123 and d2["bufferViews"][acc["bufferView"]]["byteStride"] == 4
    assert gc.node_mesh(d2, b2, "B")["_FACE_ID"].tolist() == [7, 7, 7]


def test_manifest_with_fake_kernel():
    """Face table, dimension and displacement statistics on the analytic fake box (no OCCT)."""
    from fake_kernel import FakeBox
    from paicad.kernel import distance_to_face, tessellate
    from paicad.view import BodyTess, body_items, gltf
    from paicad.view import manifest as mf

    box = FakeBox("B", [0, 0, 0], [10, 20, 5])
    topo = box.topology()
    p, n, t, f = tessellate(box, 0.1, 20)
    rows, warns = mf.face_entries("B", topo, f)
    assert warns == [] and [r["tri"] for r in rows] == [[2 * k, 2] for k in range(6)]
    feat = {"name": "B_THK_1", "type": "THICKNESS", "body": "B", "nominal": 5.0, "unit": "mm", "range": {"min": 4.75, "max": 5.25, "ratio": 0.05},
            "feasible": {"min": 1.0, "max": 9.0, "limited_by": None}, "faces": {"moving": ["F6"], "fixed": ["F5"]}, "measure": {"method": "face_distance", "faces": ["F6", "F5"]}}
    row, w = mf.feature_entry(feat, "B_THK_1", 5.0, ["F6"], ["F5"], topo, box.summary().bbox, 0.01)
    assert w == [] and row["dimension"]["value"] == 5.0 and row["dimension"]["p0"] == [5.0, 10.0, 0.0] and row["dimension"]["p1"] == [5.0, 10.0, 5.0]
    assert row["feasible"]["source"] == "estimate" and row["faces"]["other"] == []
    row2, w2 = mf.feature_entry(feat, "B_THK_1", 6.0, ["F6"], ["F5"], topo, box.summary().bbox, 0.01)  # geometry not changed -> approx warning
    assert row2["dimension"]["value"] == 6.0 and w2[0]["code"] == "VIEW_DIM_APPROX"
    moved = FakeBox("B", [0, 0, 0], [10, 20, 6])
    pm, nm, tm, fm = tessellate(moved, 0.1, 20)
    vf = mf.vertex_faces(len(pm), tm, fm)
    d = np.zeros(len(pm))
    for k in np.unique(vf):
        d[vf == k] = distance_to_face(pm[vf == k], box, int(k))
    st = mf.face_disp_stats(moved.topology(), vf, mf.clean_disp(d), {6}, mf.boundary_changed(topo, moved.topology()))
    assert st["F6"] == {"max": 1.0, "mean": 1.0, "change": "geometry"} and st["F5"]["change"] == "none" and st["F1"]["change"] == "boundary"
    items = body_items(BodyTess("B", p, n, t, f, box.edge_polylines(0.1, 20)))
    doc, bin_ = gc.parse_glb(gltf.write_glb(items, "x"))
    gc.validate(doc, bin_)
    assert [x["name"] for x in doc["nodes"]] == ["paicad_view", "B", "B.edges"]


def test_view_modules_isolated_from_occt():
    code = (
        "import sys; import paicad.view.gltf, paicad.view.manifest; "
        "print(any(m == 'OCP' or m.startswith('OCP.') for m in sys.modules))"
    )
    env = dict(os.environ, PYTHONPATH=str(PKG / "src"))
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=120)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "False"
    py = tomllib.loads((PKG / "pyproject.toml").read_text(encoding="utf-8"))
    assert py["project"]["dependencies"] == ["cadquery-ocp==7.8.1.1.post1", "numpy>=2,<3", "scipy>=1.13,<2"]  # no new runtime dependency
    for p in sorted((PKG / "src" / "paicad" / "view").glob("*.py")):
        src = p.read_text(encoding="utf-8")
        assert "import OCP" not in src and "from OCP" not in src, p.name


def test_existing_options_schema_has_no_view_keys():
    from paicad.options import DEFAULTS

    assert not {"tess", "max_triangles", "max_glb_bytes", "coarsen_steps", "edges", "fe_edges", "view"} & set(DEFAULTS)
