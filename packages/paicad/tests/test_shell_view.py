"""paicad 0.10.0: ``paicad shell view export|preview`` (geometry-view.md sections 4, 5, 8 GV-5, V-GV-14).

Virtual golden: the sheet-metal set SM1 (``data/make_synthetic_shell.py``, conftest ``shell_golden``); the truth
of every preview is the build123d sheet rebuilt with the changed bead. GLB files are parsed with the
independent ``gltf_check`` reader. Nothing generated is committed.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import gltf_check as gc
import numpy as np
import paicad
import pytest
from conftest import run_cli
from paicad.kernel import load_sheet_brep, load_sheets
from paicad.meshgeom import point_triangle_distance

LIN = 0.1
FACE_TOL = LIN + 0.01  # section 8 GV-1 / GV-3 tolerance


def load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def write_json(path, obj):
    Path(path).write_text(json.dumps(obj), encoding="utf-8")
    return path


def export(g, out, *extra):
    return run_cli("shell", "view", "export", "--cad", g["step"], "--features", g["features_path"], "--out-dir", out, *extra)


def preview(g, out, values, *extra):
    vp = write_json(Path(out).parent / f"{Path(out).name}_values.json", {"schema_version": 1, "values": values})
    code, text = run_cli("shell", "view", "preview", "--cad", g["step"], "--features", g["features_path"], "--values", vp, "--out-dir", out, *extra)
    return code, text, vp


def fe_args(g, mode):
    return ["--fe", mode, "--assem-dir", g["assem"], "--tag-dir", g["tag_dir"], "--fixed-dir", g["fixed_dir"]]


def mesh_distance(T: np.ndarray, pts: np.ndarray, cutoff: float) -> np.ndarray:
    """Distance of every point to the triangle soup T[k,3,3] (inf beyond ``cutoff``): bounding-box prefilter
    per point (large planar view triangles make the centre KD-tree of TriangleSet query everything)."""
    lo, hi = T.min(axis=1) - cutoff, T.max(axis=1) + cutoff
    out = np.full(len(pts), np.inf)
    for i, p in enumerate(pts):
        c = np.flatnonzero(np.all((lo <= p) & (p <= hi), axis=1))
        if len(c):
            out[i] = point_triangle_distance(np.repeat(p[None, :], len(c), axis=0), T[c, 0], T[c, 1], T[c, 2]).min()
    return out


def sheet(g):
    return {b.name: b for b in load_sheets(g["step"])[1]}


@pytest.fixture(scope="module")
def sview(shell_golden):
    out = shell_golden["root"] / "out" / "shell_view"
    code, text = export(shell_golden, out, "--fixed-dir", shell_golden["fixed_dir"])
    assert code == 0, text
    return out


# ------------------------------------------------------------------ export
def test_shell_view_export_structure(shell_golden, sview):
    g = shell_golden
    doc, bin_ = gc.load(sview / "view.glb")
    m = load(sview / "view_manifest.json")
    body = g["features"]["parts"][0]["body"]
    root = doc["nodes"][doc["scenes"][doc["scene"]]["nodes"][0]]
    assert root["name"] == "paicad_view" and root["extras"] == {"unit": "mm", "up_axis": "Z"}
    assert doc["asset"]["generator"] == f"paicad {paicad.__version__}"
    assert [doc["nodes"][c]["name"] for c in root["children"]] == [body, f"{body}.edges", f"{body}.fixed"]
    prim = doc["meshes"][next(x["mesh"] for x in doc["nodes"] if x["name"] == body)]["primitives"][0]
    assert prim["mode"] == 4 and set(prim["attributes"]) == {"POSITION", "NORMAL", "_FACE_ID"}
    assert doc["materials"][prim["material"]]["doubleSided"] is True  # shell
    # fixed node markers: every fixed node of the part, cluster ids of shell_scan
    fx = gc.node_mesh(doc, bin_, f"{body}.fixed")
    assert fx["_mode"] == 0 and set(fx) == {"POSITION", "_CLUSTER_ID", "_NODE_ID", "_mode"}
    z = np.load(g["fixed_dir"] / "fixed_nodes.npz")
    sel = z["part"] == 2001
    order = np.argsort(z["node_id"][sel])
    assert np.array_equal(fx["_NODE_ID"].astype(np.int64), z["node_id"][sel][order])
    assert np.array_equal(fx["_CLUSTER_ID"].astype(np.int64), z["cluster"][sel][order])
    assert np.abs(fx["POSITION"].astype(float) - z["xyz"][sel][order]).max() <= 1e-4
    assert (m["kind"], m["mode"], m["status"], m["unit"], m["up_axis"]) == ("shell", "nominal", "OK", "mm", "Z")
    assert m["engine_version"] == paicad.__version__ and m["source"]["fixed_digest"] == g["scan"]["fixed"]["digest"]
    sc = {c["id"]: c for c in g["scan"]["fixed"]["clusters"]}
    assert [c["id"] for c in m["fixed_clusters"]] == sorted(sc)
    for c in m["fixed_clusters"]:
        assert {k: c[k] for k in ("nodes", "center", "radius_mm", "kinds")} == {k: sc[c["id"]][k] for k in ("nodes", "center", "radius_mm", "kinds")}
        assert c["body"] == body and c["node"] == f"{body}.fixed" and c["faces"]
    # the RBE2 spider under the overlapping bead (B5) marks the bead faces too
    b5 = next(b for b in g["features"]["beads"] if b["id"] == g["names"]["B5"]["id"])
    assert any(set(c["faces"]) & set(b5["fillets_top"] + b5["flanks"]) for c in m["fixed_clusters"])
    # without --fixed-dir: no marker node, no clusters
    code, text = export(g, sview.parent / "shell_view_nofixed")
    assert code == 0, text
    m2 = load(sview.parent / "shell_view_nofixed" / "view_manifest.json")
    doc2, _ = gc.load(sview.parent / "shell_view_nofixed" / "view.glb")
    assert m2["fixed_clusters"] == [] and m2["source"]["fixed_digest"] is None and not [n for n in doc2["nodes"] if n.get("name", "").endswith(".fixed")]


def test_shell_view_face_id_mapping(shell_golden, sview):
    doc, bin_ = gc.load(sview / "view.glb")
    m = load(sview / "view_manifest.json")
    bodies = sheet(shell_golden)
    assert not [w for w in m["warnings"] if w["code"] == "VIEW_FACE_EMPTY"]
    for brow in m["bodies"]:
        body = bodies[brow["body"]]
        topo = body.topology()
        gm = gc.node_mesh(doc, bin_, brow["node"])
        tri, fid = gm["indices"], gm["_FACE_ID"].astype(np.int64)
        tface = fid[tri]
        assert (tface == tface[:, :1]).all()
        tf = tface[:, 0]
        assert (np.diff(tf) >= 0).all() and set(tf.tolist()) == {f.id for f in topo.faces}
        for r in brow["faces"]:
            first, cnt = r["tri"]
            assert cnt >= 1 and (tf[first : first + cnt] == int(r["id"][1:])).all() and r["surface"] == topo.face(int(r["id"][1:])).surface
        cen = gm["POSITION"].astype(float)[tri].mean(axis=1)
        dist = np.full((len(cen), len(topo.faces)), np.inf)
        for f in topo.faces:
            d, _, inside, _ = body.project_to_face(f.id, cen)
            dist[inside, f.id - 1] = d[inside]
        own = dist[np.arange(len(cen)), tf - 1]
        assert own.max() <= FACE_TOL
        other = dist.copy()
        other[np.arange(len(cen)), tf - 1] = np.inf
        assert int((other.min(axis=1) < own - 0.01).sum()) == 0


def test_shell_view_dimensions_equal_extract_nominal(shell_golden, sview):
    g = shell_golden
    m = load(sview / "view_manifest.json")
    feats = {f["name"]: f for f in g["features"]["features"]}
    beads = {b["id"]: b for b in g["features"]["beads"]}
    assert [f["name"] for f in m["features"]] == list(feats)
    assert not [w for w in m["warnings"] if w["code"] == "VIEW_DIM_APPROX"]
    body = sheet(g)[g["features"]["parts"][0]["body"]]
    for row in m["features"]:
        f = feats[row["name"]]
        b = beads[f["bead"]]
        d = row["dimension"]
        assert type(d["value"]) is float and d["value"] == f["nominal"] == row["value"] == row["nominal"]
        assert row["faces"] == {"moving": b["bottom"] + b["flanks"] + b["fillets_top"] + b["fillets_bottom"], "fixed": [b["base_face"]], "other": []}
        assert d["kind"] == ("position" if f["type"] in ("BEAD_POS_U", "BEAD_POS_V") else "linear")
        assert abs(float(np.linalg.norm(np.subtract(d["p1"], d["p0"]))) - d["geom_len"]) <= 1e-5
        assert abs(d["geom_len"] - f["nominal"]) <= 0.01, row["name"]
        if f["type"] == "BEAD_DEPTH":  # along the base normal, from the base plane
            v = np.subtract(d["p1"], d["p0"])
            assert abs(abs(float(v @ np.asarray(b["normal"]))) - f["nominal"]) <= 1e-6 and abs(d["p0"][2]) <= 1e-6
        if f["type"] in ("BEAD_POS_U", "BEAD_POS_V"):  # p0 on the reference edge line
            e = int(f["ref"]["edge"][1:])
            q = body.eval_edge(e, np.array([0.0, 1.0]))
            t = (q[1] - q[0]) / np.linalg.norm(q[1] - q[0])
            r = np.asarray(d["p0"]) - q[0]
            assert np.linalg.norm(r - (r @ t) * t) <= 1e-5


def test_shell_view_export_byte_identical_and_errors(shell_golden, sview, tmp_path):
    g = shell_golden
    code, text = export(g, tmp_path / "v2", "--fixed-dir", g["fixed_dir"])
    assert code == 0, text
    for n in ("view.glb", "view_manifest.json"):
        assert (tmp_path / "v2" / n).read_bytes() == (sview / n).read_bytes(), n
    code, text = export(g, tmp_path / "v2")
    assert code == 3 and "GEOM_OUTPUT_EXISTS" in text
    vo = write_json(tmp_path / "vo.json", {"schema_version": 1, "max_glb_bytes": 1000, "coarsen_steps": 1})
    code, text = export(g, tmp_path / "big", "--view-options", vo)
    m = load(tmp_path / "big" / "view_manifest.json")
    assert code == 14 and (m["kind"], m["status"], m["code"], m["category"], m["glb"]) == ("shell", "FAIL", "VIEW_TOO_LARGE", "VIEW", None)
    assert not (tmp_path / "big" / "view.glb").exists()
    code, text = export(dict(g, features_path=g["root"] / "nope.json"), tmp_path / "nf")
    assert code == 3 and load(tmp_path / "nf" / "view_manifest.json")["kind"] == "shell"


@pytest.mark.parametrize("argv", [["shell", "view"], ["shell", "view", "export", "--cad", "x"], ["shell", "view", "preview", "--cad", "x", "--features", "y"],
                                  ["shell", "view", "preview", "--cad", "x", "--features", "y", "--values", "z", "--out-dir", "o", "--fe", "bogus"]])
def test_shell_view_argument_errors_exit_2(argv):
    r = subprocess.run([sys.executable, "-m", "paicad", *argv], capture_output=True, text=True, timeout=60)
    assert r.returncode == 2


# ------------------------------------------------------------------ preview (update only)
CASES = {"depth": ("B1", "BEAD_DEPTH", 0.4, {"depth": 4.4}), "position": ("B1", "BEAD_POS_U", 3.0, {"shift": (3.0, 0.0)}), "width": ("B1", "BEAD_WIDTH", 1.2, {"width": 13.2})}


def _value(g, bead, ptype, delta, change):
    f = next(x for x in g["features"]["features"] if x["name"] == g["names"][bead][ptype])
    if ptype in ("BEAD_POS_U", "BEAD_POS_V"):
        sh = np.asarray(change["shift"] + (0.0,))
        return f["name"], f["nominal"] + float(np.dot(sh, np.asarray(f["ref"]["axis"]) * f["ref"]["sign"]))
    return f["name"], f["nominal"] + delta


@pytest.mark.parametrize("case", list(CASES))
def test_shell_preview_matches_build123d_variant(shell_golden, sview, tmp_path, case):
    from data.make_synthetic_shell import make_step, variant

    g = shell_golden
    bead, ptype, delta, change = CASES[case]
    name, value = _value(g, bead, ptype, delta, change)
    out = tmp_path / "p"
    code, text, vp = preview(g, out, {name: value}, "--fixed-dir", g["fixed_dir"], "--nominal-manifest", sview / "view_manifest.json")
    assert code == 0, text
    m = load(out / "preview_manifest.json")
    nom = load(sview / "view_manifest.json")
    assert (m["kind"], m["status"], m["mode"], m["fe"], m["failure"]) == ("shell", "OK", "preview", {"mode": "off"}, None)
    assert m["nominal_ref"] == {"view_sha256": nom["glb"]["sha256"], "tess": {"linear_mm": 0.1, "angular_deg": 20.0}}
    assert m["reports"] == {"update": "update/shell_update.json", "morph": None, "check": None}
    assert sorted(p.name for p in out.iterdir()) == ["paicad.log", "preview.glb", "preview_manifest.json", "update"]
    assert m["fixed_clusters"] == nom["fixed_clusters"]
    doc, bin_ = gc.load(out / "preview.glb")
    vb = {b.name: b for b in load_sheets(make_step(tmp_path, variant(g["spec"], bead, **change), "variant.step"))[1]}
    for brow in m["bodies"]:
        gm = gc.node_mesh(doc, bin_, brow["node"])
        assert set(gm) >= {"POSITION", "NORMAL", "_FACE_ID", "_DISP_MM"}
        t = vb[brow["body"]]
        P = gm["POSITION"].astype(float)
        tf = gm["_FACE_ID"].astype(np.int64)
        # GLB vertices on the variant faces (same face numbering) and variant face samples on the GLB
        for f in t.topology().faces:
            sel = tf == f.id
            d, _, _, _ = t.project_to_face(f.id, P[sel])
            assert float(d.max()) <= FACE_TOL, f.id
        samples = np.concatenate([t.sample_face(f.id, 6) for f in t.topology().faces])
        assert mesh_distance(P[gm["indices"]], samples, 1.0).max() <= FACE_TOL
        for fid, st in m["disp"]["by_face"][brow["body"]].items():
            assert float(gm["_DISP_MM"][tf == int(fid[1:])].max()) == pytest.approx(st["max"], abs=1e-5)
    # changed faces = shell_update.json changed; same B-rep and report as a standalone ``shell update``
    u = load(out / "update" / "shell_update.json")
    bf = m["disp"]["by_face"][g["features"]["parts"][0]["body"]]
    ch = u["changed"][g["features"]["parts"][0]["body"]]
    assert {f for f, s in bf.items() if s["change"] == "geometry"} >= set(ch["geometry"]) and {f for f, s in bf.items() if s["change"] == "boundary"} == set(ch["boundary_only"])
    code, text = run_cli("shell", "update", "--cad", g["step"], "--features", g["features_path"], "--values", vp, "--fixed-dir", g["fixed_dir"], "--out-dir", tmp_path / "u")
    assert code == 0, text
    names = [p["body"] for p in g["features"]["parts"]]
    for x, y in zip(load_sheet_brep(tmp_path / "u" / "sample.brep", names), load_sheet_brep(out / "update" / "sample.brep", names)):
        for f in x.topology().faces:
            pts = x.sample_face(f.id, 4)
            if len(pts):
                d, _, _, _ = y.project_to_face(f.id, pts)
                assert d.max() <= 1e-9
    ua = load(tmp_path / "u" / "shell_update.json")
    assert {k: v for k, v in ua.items() if k != "elapsed_s"} == {k: v for k, v in u.items() if k != "elapsed_s"}
    assert (tmp_path / "u" / "face_map.json").read_bytes() == (out / "update" / "face_map.json").read_bytes()
    row = next(f for f in m["features"] if f["name"] == name)
    assert row["value"] == value and row["dimension"]["value"] == value
    assert abs(row["dimension"]["geom_len"] - u["expected_measured"][name]) <= 0.01  # dimension line on the changed bead


def test_shell_preview_deterministic_and_fixed_violation(shell_golden, sview, tmp_path):
    g = shell_golden
    vals = {g["names"]["B3"]["BEAD_WIDTH"]: 31.5}
    outs = []
    for k in range(2):
        code, text, _ = preview(g, tmp_path / f"p{k}", vals, "--fixed-dir", g["fixed_dir"], "--nominal-manifest", sview / "view_manifest.json")
        assert code == 0, text
        outs.append(tmp_path / f"p{k}")
    assert (outs[0] / "preview.glb").read_bytes() == (outs[1] / "preview.glb").read_bytes()
    ta, tb = ((o / "preview_manifest.json").read_text(encoding="utf-8").split('"timing"')[0] for o in outs)
    assert ta == tb
    # the bead over the RBE2 spider: update pre-check failure, clusters for the viewer, no GLB
    out = tmp_path / "fx"
    code, text, _ = preview(g, out, {g["names"]["B5"]["BEAD_DEPTH"]: 3.3}, "--fixed-dir", g["fixed_dir"])
    m = load(out / "preview_manifest.json")
    assert code == 10 and "PAICAD RESULT FAIL SHELL_FIXED_REGION_VIOLATION preview_manifest.json" in text
    assert (m["status"], m["code"], m["category"], m["glb"], m["disp"], m["bodies"]) == ("FAIL", "SHELL_FIXED_REGION_VIOLATION", "FIXED", None, None, [])
    assert m["failure"]["features"] == [g["names"]["B5"]["BEAD_DEPTH"]] and m["failure"]["clusters"]
    assert set(m["failure"]["clusters"]) <= {c["id"] for c in g["scan"]["fixed"]["clusters"]}
    assert all(r["dimension"] is None for r in m["features"]) and not (out / "preview.glb").exists()
    assert load(out / "update" / "shell_update.json")["code"] == "SHELL_FIXED_REGION_VIOLATION"
    # missing FE inputs -> 2
    code, text, _ = preview(g, tmp_path / "noargs", vals, "--fe", "check")
    assert code == 2


# ------------------------------------------------------------------ FE preview
def test_shell_preview_fe_matches_standalone_morph(shell_golden, tmp_path):
    from paicad.mesh.radioss import parse_text
    from paicad.shell.assem import read_assembly
    from paicad.shell.fixed import part_mesh

    g = shell_golden
    vals = {g["names"]["B1"]["BEAD_DEPTH"]: 4.4, g["names"]["B2"]["BEAD_POS_U"]: 152.0}
    out = tmp_path / "p"
    code, text, vp = preview(g, out, vals, *fe_args(g, "check"))
    assert code == 0, text
    m = load(out / "preview_manifest.json")
    assert (m["fe"]["mode"], m["fe"]["status"]) == ("check", "PASS") and m["reports"] == {"update": "update/shell_update.json", "morph": "morph/shell_morph.json", "check": "check/shell_check.json"}
    assert set(m["fe"]["quality"]) == {"max_warpage_deg", "max_skew_deg", "max_aspect", "min_jacobian", "edge_ratio", "dt_ratio"}
    assert not list(out.rglob("*.inc")) and not list(out.rglob("files"))
    c = load(out / "check" / "shell_check.json")
    assert c["status"] == "PASS" and c["out_files"] == []
    # standalone shell update -> morph -> check
    code, text = run_cli("shell", "run", "--cad", g["step"], "--features", g["features_path"], "--values", vp, "--assem-dir", g["assem"], "--tag-dir", g["tag_dir"],
                         "--fixed-dir", g["fixed_dir"], "--update-dir", tmp_path / "u", "--morph-dir", tmp_path / "m", "--check-dir", tmp_path / "c", "--out-files-dir", tmp_path / "of")
    assert code == 0, text
    ms, mp = load(tmp_path / "m" / "shell_morph.json"), load(out / "morph" / "shell_morph.json")
    assert {k: v for k, v in ms.items() if k != "elapsed_s"} == {k: v for k, v in mp.items() if k != "elapsed_s"}
    cs = load(tmp_path / "c" / "shell_check.json")
    assert {k: v for k, v in cs.items() if k not in ("elapsed_s", "out_files")} == {k: v for k, v in c.items() if k not in ("elapsed_s", "out_files")}
    asm = read_assembly(g["assem"])
    pm = part_mesh(asm, 2001)
    new = dict(zip(asm.node_ids.tolist(), asm.xyz))
    for rel in ms["files"]:
        mm = parse_text((tmp_path / "m" / "files" / rel["rel"]).read_bytes().decode("latin-1"))
        new.update(zip(mm.node_ids.tolist(), mm.xyz))
    doc, bin_ = gc.load(out / "preview_fe.glb")
    title = g["features"]["parts"][0]["title"]
    fe = gc.node_mesh(doc, bin_, title)
    assert set(fe) >= {"POSITION", "NORMAL", "_DISP_MM", "_ELEM_ID"}
    tag = load(g["tag_dir"] / "shell_tag.json")["parts"][0]["elements"]
    assert len(fe["indices"]) == 2 * tag["quad"] + tag["tri"]  # quads split along n1-n3, n3 = n4 / SH3N one triangle
    nodes = np.unique(pm.conn[pm.conn > 0])
    xyz_new = np.array([new[int(n)] for n in nodes])
    xyz_base = asm.xyz[asm.index(nodes)]
    assert np.abs(fe["POSITION"].astype(float) - xyz_new).max() <= 1e-4  # float32 storage of the written coordinates
    disp = np.linalg.norm(xyz_new - xyz_base, axis=1)
    disp[disp <= 1e-6] = 0.0
    assert np.abs(fe["_DISP_MM"] - disp).max() <= 1e-5 and fe["_DISP_MM"].max() > 0
    assert set(fe["_ELEM_ID"].tolist()) <= set(int(x) for x in pm.elem_ids)
    first = {}
    for eid, c4 in zip(pm.elem_ids, pm.conn):
        for nn in set(int(x) for x in c4 if x > 0):
            first[nn] = min(first.get(nn, 1 << 62), int(eid))
    assert np.array_equal(fe["_ELEM_ID"].astype(np.int64), np.array([first[int(n)] for n in nodes]))
    assert gc.node_mesh(doc, bin_, f"{title}.edges")["_mode"] == 1
    assert doc["materials"][doc["meshes"][next(x["mesh"] for x in doc["nodes"] if x["name"] == title)]["primitives"][0]["material"]]["doubleSided"] is True
    # morph-only FE preview: no check report, same FE GLB
    code, text, _ = preview(g, tmp_path / "pm", vals, *fe_args(g, "morph"))
    mm_ = load(tmp_path / "pm" / "preview_manifest.json")
    assert code == 0 and mm_["fe"]["status"] == "OK" and mm_["reports"]["check"] is None
    assert (tmp_path / "pm" / "preview_fe.glb").read_bytes() == (out / "preview_fe.glb").read_bytes()


def test_shell_preview_fe_morph_failure_clusters(shell_golden, tmp_path, monkeypatch):
    """Morph-stage fixed violation (no update pre-check without --fixed-dir semantics is not possible in the
    preview: FE needs --fixed-dir) is simulated: the failure keeps the sheet GLB and names the cluster."""
    import paicad.shell.morph as sm

    g = shell_golden
    z = np.load(g["fixed_dir"] / "fixed_nodes.npz")
    nid = int(z["node_id"][0])

    def boom(*a, **k):
        raise sm.MorphFailed("SHELL_FIXED_REGION_VIOLATION", "part 2001: 1 fixed nodes would move", [nid])

    monkeypatch.setattr(sm, "morph_core", boom)
    out = tmp_path / "p"
    code, _, _ = preview(g, out, {g["names"]["B1"]["BEAD_DEPTH"]: 4.4}, *fe_args(g, "check"))
    m = load(out / "preview_manifest.json")
    assert code == 11 and (m["status"], m["code"], m["fe"]["code"], m["fe"]["category"]) == ("FAIL", "SHELL_FIXED_REGION_VIOLATION", "SHELL_FIXED_REGION_VIOLATION", "FIXED")
    assert m["failure"]["clusters"] == [int(z["cluster"][0])] and (out / "preview.glb").exists() and not (out / "preview_fe.glb").exists()
