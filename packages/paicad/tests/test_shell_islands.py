"""Shell morphing SM-C3~C8 (shell-morph.md section 14, V-SM-16~22): bottom islands, feature distortion safety net,
strict element labels, fixed / quality policies, bead hold, mesh-only judgement core and the esl hard cases.

Synthetic B-rep sheets (``make_synthetic_shell.py``, nothing committed): SMI (islands, hold) and SMH1..SMH4
(esl ``synth_hard`` H1..H4 as mid-surface variants)."""

from __future__ import annotations

import ast
import copy
import json
from pathlib import Path

import numpy as np
import pytest
from conftest import run_cli

from paicad.common import PaicadError
from paicad.shell import opts as shopts

PARTS = "2001"
KF, KE, KV = 1, 2, 3


# ------------------------------------------------------------------ helpers
def _prep(root: Path, spec) -> dict:
    """fixed-scan -> extract -> tag of a synthetic sheet, plus the in-memory inputs of update / morph / check."""
    from data.make_synthetic_shell import make_all
    from paicad.shell.cad import load
    from paicad.shell.common import load_shell_features
    from paicad.shell.morph import load_mesh_inputs

    g = make_all(root / "g", spec)
    fx, ex, tg = root / "fx", root / "ex", root / "tg"
    assert run_cli("shell", "fixed-scan", "--assem-dir", g["assem"], "--out-dir", fx, "--parts", PARTS)[0] == 0
    code, log = run_cli("shell", "extract", "--cad", g["step"], "--assem-dir", g["assem"], "--out-dir", ex, "--no-png")
    assert code == 0, log
    feats = ex / "shell_features.json"
    code, log = run_cli("shell", "tag", "--cad", g["step"], "--features", feats, "--assem-dir", g["assem"], "--fixed-dir", fx, "--out-dir", tg)
    assert code == 0, log
    doc = load_shell_features(feats)
    tag_doc, tag, fixed, asm, meshes = load_mesh_inputs(tg, fx, g["assem"])
    return {"g": g, "root": root, "fx": fx, "ex": ex, "tg": tg, "feats": feats, "doc": doc, "tag_doc": tag_doc, "fixed": fixed, "asm": asm, "meshes": meshes,
            "nominal": load(g["step"]).bodies, "nom": {f["name"]: float(f["nominal"]) for f in doc["features"]}}


def _opts(over: dict | None = None) -> dict:
    o = shopts._merge(shopts.DEFAULTS, over or {})
    assert not shopts.validate(o)
    return o


def _cores(c, values: dict, o=None, fixed=True):
    from paicad.shell.check import check_core
    from paicad.shell.morph import morph_core
    from paicad.shell.update import update_core

    o = o or _opts()
    res = update_core(c["nominal"], c["doc"], values, o, c["fixed"] if fixed else None)
    sample = {b.name: b for b in res.bodies}
    m = morph_core(c["meshes"], sample, {"changed": res.changed, "beads": res.beads}, o)
    zero = {mm.index: np.zeros(len(mm.node_ids)) for mm in c["meshes"]}
    chk = check_core(c["meshes"], m.xyz, sample, c["doc"], values, res.expected, res.changed, o, None, {}, {"dist_of": zero}, None, full=False)
    return res, m, chk


def _bead(c, center) -> dict:
    return min(c["doc"]["beads"], key=lambda b: sum((a - x) ** 2 for a, x in zip(b["center"][:2], center)))


def _fname(c, bead: dict, t: str) -> str:
    return next(f["name"] for f in c["doc"]["features"] if f["bead"] == bead["id"] and f["type"] == t)


def _island_nodes(m, isl: dict) -> np.ndarray:
    fs = [int(x[1:]) for x in isl["faces"]]
    return np.flatnonzero((m.kind == KF) & np.isin(m.ent, fs))


@pytest.fixture(scope="session")
def smi(tmp_path_factory):
    from data.make_synthetic_shell import smi_spec

    return _prep(tmp_path_factory.mktemp("smi"), smi_spec())


@pytest.fixture(scope="session")
def smh(tmp_path_factory):
    from data.make_synthetic_shell import smh_spec

    return {k: _prep(tmp_path_factory.mktemp(f"smh{k}"), smh_spec(k)) for k in (1, 2, 3, 4)}


# ------------------------------------------------------------------ options (SM-C3~C7 keys)
def test_new_option_keys_defaults_compat_and_ranges(tmp_path):
    o = shopts.load(None)
    assert o["extract"]["islands"] is True and o["extract"]["island_max_mm"] == 40.0 and o["extract"]["island_ring_frac"] == 0.9
    assert o["fixed"]["policy"] == "skip" and o["quality"]["fail_policy"] == "skip" and o["quality"]["distort_min_mm"] == 0.1 and o["quality"]["distort_rel"] == 0.25
    assert o["bead"]["hold"] == {"beads": [], "ring_mm": 3.0, "blend_mm": 8.0} and o["tag"]["label_angle_deg"] == 15.0
    # default-valued new keys never reach reports / ids (0.14.1 bytes)
    used = shopts.used(o)
    for sec, key in shopts.NEW_KEYS:
        assert key not in used[sec]
    explicit = {"schema_version": 1, "fixed": {"policy": "skip"}, "quality": {"fail_policy": "skip"}, "extract": {"islands": True}, "bead": {"hold": {"beads": []}}}
    p = tmp_path / "o.json"
    p.write_text(json.dumps(explicit), encoding="utf-8")
    assert shopts.used(shopts.load(p)) == used
    warn = shopts.load(_write(tmp_path, "w.json", {"schema_version": 1, "fixed": {"policy": "warn"}}))
    assert shopts.used(warn)["fixed"]["policy"] == "warn"
    for bad, needle in (({"fixed": {"policy": "ignore"}}, "fixed.policy"), ({"quality": {"fail_policy": 1}}, "quality.fail_policy"),
                        ({"extract": {"island_ring_frac": 1.5}}, "island_ring_frac"), ({"extract": {"islands": "yes"}}, "extract.islands"),
                        ({"bead": {"hold": {"beads": "B1"}}}, "bead.hold.beads"), ({"bead": {"hold": {"ring": 2}}}, "bead.hold.ring"),
                        ({"tag": {"label_angle_deg": 0}}, "label_angle_deg"), ({"quality": {"distort_min_mm": 0}}, "distort_min_mm")):
        with pytest.raises(PaicadError) as e:
            shopts.load(_write(tmp_path, "b.json", {"schema_version": 1, **bad}))
        assert e.value.code == "GEOM_INPUT_INVALID" and needle in e.value.message


def _write(tmp_path, name, obj) -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(obj), encoding="utf-8")
    return p


# ------------------------------------------------------------------ V-SM-16 islands
def test_vsm16_islands_recognized(smi):
    c = smi
    doc = c["doc"]
    i1 = _bead(c, (130.0, 100.0))
    kinds = [(i["kind"], len(i["faces"]), i["free_loops"]) for i in i1["islands"]]
    # hole D6 (no face), dimple D10 h1, burring D8 (free collar edge), fastening boss D16 with hole D4
    assert kinds == [("hole", 0, 1), ("feature", 4, 0), ("feature", 2, 1), ("feature", 4, 1)]
    assert all(i["id"].startswith(i1["id"] + "_I") and i["size_mm"] <= 40.0 for i in i1["islands"])
    # absorbed islands are no beads of their own; the 44 mm island and the annular mound are refused
    assert not any(abs(b["center"][2] + 4.0) < 1e-6 and abs(b["center"][0] - 105.0) < 1e-6 for b in doc["beads"])
    w = {x["code"]: x for x in doc["warnings"]}
    assert w["BEAD_ISLAND_TOO_LARGE"]["size_mm"] > 40.0 and "bead_loop" in w["BEAD_ISLAND_TOO_LARGE"]
    assert any(x["code"] == "BEAD_IRREGULAR" and "annular inner mound" in x["message"] for x in doc["warnings"])
    assert not any("islands" in b for b in doc["beads"] if b["id"] not in (i1["id"], _bead(c, (300.0, 100.0))["id"]))
    # width shrink is limited by the islands (bottom outline - land_min)
    fw = next(f for f in doc["features"] if f["name"] == _fname(c, i1, "BEAD_WIDTH"))
    assert fw["feasible"]["limited_by"].startswith("island:" + i1["id"])
    assert not [x for x in c["tag_doc"]["warnings"] if x["code"] == "TAG_ISLAND_MISMATCH"]  # B-rep islands = mesh islands


def test_vsm16_islands_false_is_legacy_behaviour(smi, tmp_path):
    c = smi
    o = _write(tmp_path, "o.json", {"schema_version": 1, "extract": {"islands": False}})
    code, _ = run_cli("shell", "extract", "--cad", c["g"]["step"], "--assem-dir", c["g"]["assem"], "--out-dir", tmp_path / "e", "--no-png", "--options", o)
    d = json.loads((tmp_path / "e" / "shell_features.json").read_text())
    assert code == 0 and not any("islands" in b for b in d["beads"])
    codes = [x["code"] for x in d["warnings"]]
    assert "BEAD_OPEN_UNSUPPORTED" in codes and "BEAD_ISLAND_TOO_LARGE" not in codes  # 0.14.1: bottom hole = open bead
    assert any(abs(b["center"][0] - 105.0) < 1e-6 and abs(b["center"][2] + 4.0) < 1e-6 for b in d["beads"])  # the dimple is its own bead
    assert d["options"]["extract"]["islands"] is False


def test_vsm16_features_prepared_without_islands_still_run(smi, tmp_path):
    """A set prepared before 0.15.0 (or with islands false) keeps working with the default options: the dimple that
    is now an island of I1 is still a bead of that features file."""
    from paicad.shell.common import load_shell_features

    c = smi
    o = _write(tmp_path, "o.json", {"schema_version": 1, "extract": {"islands": False}})
    code, _ = run_cli("shell", "extract", "--cad", c["g"]["step"], "--assem-dir", c["g"]["assem"], "--out-dir", tmp_path / "e", "--no-png", "--options", o)
    assert code == 0
    old = dict(c, doc=load_shell_features(tmp_path / "e" / "shell_features.json"))
    dimple = next(b for b in old["doc"]["beads"] if abs(b["center"][0] - 105.0) < 1e-6 and abs(b["center"][2] + 4.0) < 1e-6)
    name = _fname(old, dimple, "BEAD_DEPTH")
    _, _, chk = _cores(old, {name: 1.1})
    assert chk.status == "PASS", chk.message


@pytest.mark.parametrize("scale", [1.2, 0.8])
def test_vsm16_island_rigid_motion_depth(smi, scale):
    c = smi
    i1 = _bead(c, (130.0, 100.0))
    name = _fname(c, i1, "BEAD_DEPTH")
    res, m, chk = _cores(c, {name: c["nom"][name] * scale})
    assert chk.status == "PASS", chk.message
    mesh = c["meshes"][0]
    d = m.disp[0]
    t = np.asarray(next(s for s in res.beads if s["id"] == i1["id"])["island_shift"])
    assert abs(abs(t[2]) - 0.8) < 1e-9
    for isl in i1["islands"]:
        es = [int(x[1:]) for x in isl["loop"]]
        sel = np.flatnonzero((mesh.kind == KE) & np.isin(mesh.ent, es))
        if isl["faces"]:
            sel = np.concatenate([sel, _island_nodes(mesh, isl)])
        assert len(sel) and float(np.abs(d[sel] - t).max()) <= 1e-6, isl["id"]
    assert chk.checks["feature"]["status"] == "PASS" and chk.checks["feature"]["features"] == 3
    items = {i["name"]: i for i in chk.checks["param"]["items"]}
    assert items[name]["err"] <= 0.05 and chk.checks["deviation"]["max_mm"] <= 0.05


def test_vsm16_island_collision(smi):
    from paicad.shell.update import update_core

    c = smi
    i1 = _bead(c, (130.0, 100.0))
    name = _fname(c, i1, "BEAD_WIDTH")
    with pytest.raises(PaicadError) as e:
        update_core(c["nominal"], c["doc"], {name: 20.0}, _opts(), c["fixed"])
    assert e.value.code == "GEOM_FEATURE_COLLISION"
    assert [x["kind"] for x in e.value.detail["collisions"]] == ["island"] and e.value.detail["collisions"][0]["other"].startswith(i1["id"] + "_I")


# ------------------------------------------------------------------ V-SM-17 feature distortion
def test_vsm17_feature_distorted_injection(smi):
    from paicad.shell.check import check_core

    c = smi
    i1 = _bead(c, (130.0, 100.0))
    name = _fname(c, i1, "BEAD_DEPTH")
    vals = {name: c["nom"][name] * 1.2}
    res, m, chk = _cores(c, vals)
    assert chk.checks["feature"]["status"] == "PASS"
    mesh = c["meshes"][0]
    bad = {mesh.index: m.xyz[mesh.index].copy()}
    boss = i1["islands"][3]
    sel = _island_nodes(mesh, boss)
    bad[mesh.index][sel] = mesh.xyz[sel]  # island interior left behind: rides on the bottom only by its rim
    sample = {b.name: b for b in res.bodies}
    zero = {mesh.index: np.zeros(len(mesh.node_ids))}
    for over in (None, {"fixed": {"policy": "warn"}, "quality": {"fail_policy": "warn"}}):
        r = check_core(c["meshes"], bad, sample, c["doc"], vals, res.expected, res.changed, _opts(over), None, {}, {"dist_of": zero}, None, full=False)
        assert r.status == "FAIL" and r.code == "SHELL_FEATURE_DISTORTED" and boss["id"] in r.message
        assert r.checks["feature"]["worst"]["island"] == boss["id"] and r.checks["feature"]["worst"]["dev_mm"] > 0.7


@pytest.mark.parametrize("label,target,island,half", [("dimple->bottom", "bottom", 1, False), ("boss->bottom", "bottom", 3, False), ("dimple->base", "base", 1, False),
                                                       ("boss->base", "base", 3, False), ("dimple half->bottom", "bottom", 1, True)])
def test_vsm17_mistagged_island_nodes_fail(smi, label, target, island, half):
    """Tag errors (island nodes classified on the bottom / the base face) are caught without the tag: island nodes found
    geometrically must move by the island shift and the sample island surfaces must be followed by the mesh."""
    c = smi
    i1 = _bead(c, (130.0, 100.0))
    name = _fname(c, i1, "BEAD_DEPTH")
    mesh0 = c["meshes"][0]
    isl = i1["islands"][island]
    sel = _island_nodes(mesh0, isl)
    if half:
        sel = sel[mesh0.xyz[sel, 0] < isl["center"][0]]
    mm = copy.copy(mesh0)
    mm.kind, mm.ent = mesh0.kind.copy(), mesh0.ent.copy()
    mm.ent[sel] = int((i1["bottom"][0] if target == "bottom" else i1["base_face"])[1:])
    for k in [k for k in vars(mm) if k.startswith("_")]:
        delattr(mm, k)
    for over in (None, {"fixed": {"policy": "warn"}, "quality": {"fail_policy": "warn"}}):
        _, _, chk = _cores(dict(c, meshes=[mm]), {name: c["nom"][name] * 1.2}, _opts(over))
        assert chk.status == "FAIL" and chk.code == "SHELL_FEATURE_DISTORTED", (label, chk.code, chk.message)
        assert chk.checks["feature"]["coverage"]["max_mm"] >= 0.79
    _, _, ok = _cores(c, {name: c["nom"][name] * 1.2})
    assert ok.status == "PASS" and ok.checks["feature"]["coverage"]["max_mm"] <= 1e-6


@pytest.mark.parametrize("island", [0, 1, 3, 4])
def test_vsm17_mistag_on_held_bead_unanchored_island(smh, island):
    """hold on: only the island holding the anchors is left out; the other islands of the held bead are still checked."""
    c = smh[4]
    t = _bead(c, (120.0, 70.0))
    name = _fname(c, t, "BEAD_DEPTH")
    mesh0 = c["meshes"][0]
    isl = t["islands"][island]
    sel = _island_nodes(mesh0, isl)
    assert len(sel) and not mesh0.fixed[sel].any()
    mm = copy.copy(mesh0)
    mm.kind, mm.ent = mesh0.kind.copy(), mesh0.ent.copy()
    mm.ent[sel] = int(t["base_face"][1:])
    for k in [k for k in vars(mm) if k.startswith("_")]:
        delattr(mm, k)
    for over in ({}, {"fixed": {"policy": "warn"}, "quality": {"fail_policy": "warn"}}):
        o = _opts(dict(over, bead={"hold": {"beads": [t["id"]]}}))
        _, _, chk = _cores(dict(c, meshes=[mm]), {name: c["nom"][name] * 1.2}, o)
        assert chk.status == "FAIL" and chk.code == "SHELL_FEATURE_DISTORTED" and isl["id"] in chk.message, (chk.code, chk.message)
    _, _, ok = _cores(c, {name: c["nom"][name] * 1.2}, _opts({"bead": {"hold": {"beads": [t["id"]]}}}))
    assert ok.status == "PASS" and ok.checks["feature"]["coverage"]["max_mm"] <= 0.1


@pytest.fixture(scope="module")
def smh4_near(tmp_path_factory):
    """SMH4 with two more dimples on T at 9~17 mm (near1) and 6~14 mm (near2) from the hold anchors (boss at 110, 70)."""
    import dataclasses

    from data.make_synthetic_shell import _dimple, smh_spec

    spec = smh_spec(4)
    t0 = spec.beads[0]
    spec.beads[0] = dataclasses.replace(t0, islands=tuple(t0.islands) + (_dimple((124.0, 80.0), -4.0, d=8.0), _dimple((110.0, 84.0), -4.0, d=8.0)))
    return _prep(tmp_path_factory.mktemp("smh4near"), spec)


@pytest.mark.parametrize("center", [(124.0, 80.0), (110.0, 84.0)], ids=["near1", "near2"])
def test_vsm17_hold_blend_islands(smh4_near, center):
    """Islands inside the hold blend zone: expected displacement = s(r) * shift (no exclusion radius) in both the tag-free
    coverage and the tag-based rigidity; a mistagged blended island fails, the normal sample does not."""
    c = smh4_near
    t = _bead(c, (120.0, 70.0))
    isl = min(t["islands"], key=lambda i: (i["center"][0] - center[0]) ** 2 + (i["center"][1] - center[1]) ** 2)
    nm = {f["type"]: f["name"] for f in c["doc"]["features"] if f["bead"] == t["id"]}
    mesh0 = c["meshes"][0]
    sel = _island_nodes(mesh0, isl)
    mm = copy.copy(mesh0)
    mm.kind, mm.ent = mesh0.kind.copy(), mesh0.ent.copy()
    mm.ent[sel] = int(t["base_face"][1:])
    for k in [k for k in vars(mm) if k.startswith("_")]:
        delattr(mm, k)
    hold = {"bead": {"hold": {"beads": [t["id"]]}}}
    for vals, over in (({nm["BEAD_POS_U"]: c["nom"][nm["BEAD_POS_U"]] + 5.0}, {"fixed": {"policy": "warn"}, "quality": {"fail_policy": "warn"}}),
                       ({nm["BEAD_DEPTH"]: c["nom"][nm["BEAD_DEPTH"]] * 1.2}, {})):
        o = _opts(dict(over, **hold))
        _, _, ok = _cores(c, vals, o)
        assert ok.code != "SHELL_FEATURE_DISTORTED" and ok.checks["feature"]["status"] != "FAIL", (ok.code, ok.message)
        assert ok.checks["feature"]["coverage"]["max_mm"] <= 0.1
        _, _, bad = _cores(dict(c, meshes=[mm]), vals, o)
        assert bad.code == "SHELL_FEATURE_DISTORTED" and isl["id"] in bad.message, (bad.code, bad.message)


def test_final_code_order_by_policy():
    from paicad.shell.judge import final_code

    fails = {"SHELL_FIXED_REGION_VIOLATION": "f", "GEOM_QUALITY_HARD": "inv", "GEOM_INTERFERENCE": "i"}
    assert final_code(fails, _opts()) == "SHELL_FIXED_REGION_VIOLATION"  # skip: 0.14.1 order
    assert final_code({"GEOM_QUALITY_HARD": "inv", "GEOM_INTERFERENCE": "i"}, _opts()) == "GEOM_INTERFERENCE"
    assert final_code(fails, _opts({"quality": {"fail_policy": "warn"}})) == "GEOM_QUALITY_HARD"
    assert final_code(dict(fails, SHELL_FEATURE_DISTORTED="d"), _opts()) == "SHELL_FEATURE_DISTORTED"
    assert final_code({}, _opts()) is None


def test_skip_keeps_fixed_before_inversion(shell_golden):
    import argparse

    from paicad.shell.check import check_core
    from paicad.shell.morph import load_inputs

    g = shell_golden
    ns = argparse.Namespace(features=g["features_path"], tag_dir=g["tag_dir"], fixed_dir=g["fixed_dir"], assem_dir=g["assem"], update_dir=g["update0"])
    o = shopts.load(None)
    doc, _, _, _, _, samples, meshes = load_inputs(ns, o)
    m = meshes[0]
    x = m.xyz.copy()
    x[np.flatnonzero(m.fixed)[0], 2] += 0.01
    q = next(int(i) for i in np.flatnonzero(~m.tri) if not m.fixed[m.conn[i]].any())
    a, _, c_, _ = m.conn[q]
    x[c_] = x[a] - (x[c_] - x[a]) * 0.5  # folded quad
    zero = {m.index: np.zeros(len(m.node_ids))}
    r = check_core(meshes, {m.index: x}, samples, doc, {}, {}, {}, o, None, {}, {"dist_of": zero}, None, full=False)
    assert r.code == "SHELL_FIXED_REGION_VIOLATION" and r.checks["quality"]["inverted"] > 0
    r = check_core(meshes, {m.index: x}, samples, doc, {}, {}, {}, _opts({"quality": {"fail_policy": "warn"}}), None, {}, {"dist_of": zero}, None, full=False)
    assert r.code == "GEOM_QUALITY" and "inverted" in r.message


def test_vsm17_no_islands_skipped(shell_golden):
    import argparse

    from paicad.shell.check import check_core
    from paicad.shell.morph import load_inputs

    g = shell_golden
    ns = argparse.Namespace(features=g["features_path"], tag_dir=g["tag_dir"], fixed_dir=g["fixed_dir"], assem_dir=g["assem"], update_dir=g["update0"])
    o = shopts.load(None)
    doc, _, _, _, u, samples, meshes = load_inputs(ns, o)
    zero = {m.index: np.zeros(len(m.node_ids)) for m in meshes}
    r = check_core(meshes, {m.index: m.xyz for m in meshes}, samples, doc, {}, {}, {}, o, None, {}, {"dist_of": zero}, None, full=False)
    assert r.status == "PASS" and r.checks["feature"]["status"] == "SKIPPED" and r.checks["feature"]["features"] == 0
    assert not any("islands" in b or "hold_eligible" in b for b in doc["beads"])
    assert set(doc["options"]["extract"]) == set(shopts.DEFAULTS["extract"]) - {"islands", "island_max_mm", "island_ring_frac"}


# ------------------------------------------------------------------ V-SM-18 strict labels
def test_vsm18_strict_labels(smi):
    from paicad.shell.judge import Tables, element_faces, strict_labels
    from paicad.shell.morph import _element_faces

    c = smi
    mesh = c["meshes"][0]
    body = c["nominal"][0]
    topo = body.topology()
    T = Tables.from_topology(topo)
    lab = strict_labels(mesh.xyz, mesh.conn, mesh.tri, mesh.kind, mesh.ent, T, 15.0)
    i1 = _bead(c, (130.0, 100.0))
    bottom = int(i1["bottom"][0][1:])
    outer = set(topo.face(bottom).outer_edges)
    en = [el[:3] if t else el for el, t in zip(mesh.conn, mesh.tri)]
    # bottom edge row: FACE-bottom nodes + EDGE nodes on the bottom outline -> bottom label
    row = [i for i, el in enumerate(en) if any(mesh.kind[j] == KF and mesh.ent[j] == bottom for j in el) and any(mesh.kind[j] == KE and mesh.ent[j] in outer for j in el)
           and all((mesh.kind[j] == KF and mesh.ent[j] == bottom) or (mesh.kind[j] == KE and mesh.ent[j] in outer) or mesh.kind[j] == KV for j in el)]
    assert len(row) > 20 and all(lab[i] == bottom for i in row)
    # a flank FACE node in a bottom element -> mixed
    flank = int(i1["flanks"][0][1:])
    k = row[0]
    kind, ent = mesh.kind.copy(), mesh.ent.copy()
    j = next(j for j in en[k] if kind[j] == KF)
    ent[j] = flank
    assert strict_labels(mesh.xyz, mesh.conn, mesh.tri, kind, ent, T, 15.0)[k] == -1
    # a bottom element tilted by more than 15 deg -> mixed
    x = mesh.xyz.copy()
    x[j] = x[j] + np.array([0.0, 0.0, 3.0])
    assert strict_labels(x, mesh.conn, mesh.tri, mesh.kind, mesh.ent, T, 15.0)[k] == -1
    # the morph element -> face assignment is unchanged (and equal to the table based one)
    from paicad.shell.judge import element_faces_loop
    from paicad.shell.morph import _element_faces_loop

    ref = _element_faces_loop(mesh, topo)
    assert np.array_equal(_element_faces(mesh, topo), ref) and np.array_equal(element_faces_loop(mesh.conn, mesh.tri, mesh.kind, mesh.ent, T), ref)
    rng = np.random.default_rng(7)  # vectorized assignment = 0.15.0 loop, also for scrambled tags
    for _ in range(3):
        kk, ee = mesh.kind.copy(), mesh.ent.copy()
        idx = rng.choice(len(kk), len(kk) // 5, replace=False)
        kk[idx] = rng.choice([-1, 1, 2, 3], len(idx))
        ee[idx] = rng.integers(1, len(topo.edges), len(idx))
        assert np.array_equal(element_faces(mesh.conn, mesh.tri, kk, ee, T), element_faces_loop(mesh.conn, mesh.tri, kk, ee, T))


# ------------------------------------------------------------------ V-SM-19 policies
def test_vsm19_default_keys_keep_bytes(shell_golden, tmp_path):
    g = shell_golden
    vals = _write(tmp_path, "v.json", {"schema_version": 1, "values": {g["names"]["B2"]["BEAD_DEPTH"]: 3.3}})
    explicit = _write(tmp_path, "o.json", {"schema_version": 1, "fixed": {"policy": "skip"}, "quality": {"fail_policy": "skip", "distort_rel": 0.25},
                                           "extract": {"islands": True, "island_max_mm": 40.0}, "bead": {"hold": {"beads": [], "ring_mm": 3.0}}, "tag": {"label_angle_deg": 15.0}})
    outs = []
    for k, extra in enumerate(([], ["--options", explicit])):
        d = tmp_path / f"r{k}"
        code, log = run_cli("shell", "run", "--cad", g["step"], "--features", g["features_path"], "--values", vals, "--assem-dir", g["assem"], "--tag-dir", g["tag_dir"],
                            "--fixed-dir", g["fixed_dir"], "--update-dir", d / "u", "--morph-dir", d / "m", "--check-dir", d / "c", "--out-files-dir", d / "of", *extra)
        assert code == 0, log
        outs.append(d)
    for rel in ("u/shell_update.json", "m/shell_morph.json", "c/shell_check.json"):
        a, b = (json.loads((d / rel).read_text()) for d in outs)
        for x in (a, b):
            x.pop("elapsed_s", None)
        assert a == b, rel
    for p in sorted((outs[0] / "of").rglob("*.inc")):
        assert p.read_bytes() == (outs[1] / "of" / p.relative_to(outs[0] / "of")).read_bytes()
    u = json.loads((outs[0] / "u" / "shell_update.json").read_text())
    assert "hold" not in u["options"]["bead"] and "islands" not in u["options"]["extract"]


def test_vsm19_fixed_warn(shell_golden):
    import argparse

    from paicad.shell.morph import load_inputs

    g = shell_golden
    ns = argparse.Namespace(features=g["features_path"], tag_dir=g["tag_dir"], fixed_dir=g["fixed_dir"], assem_dir=g["assem"], update_dir=g["update0"])
    doc, _, fixed, asm, _, samples, meshes = load_inputs(ns, shopts.load(None))
    c = {"doc": doc, "fixed": fixed, "meshes": meshes, "nominal": [samples[p["body"]] for p in doc["parts"]]}
    name = g["names"]["B5"]["BEAD_DEPTH"]
    vals = {name: 3.3}
    from paicad.shell.update import update_core

    with pytest.raises(PaicadError) as e:
        update_core(c["nominal"], doc, vals, _opts(), fixed)
    assert e.value.code == "SHELL_FIXED_REGION_VIOLATION"
    res, m, chk = _cores(c, vals, _opts({"fixed": {"policy": "warn"}}))
    assert res.fixed_precheck["status"] == "WARN" and res.fixed_precheck["violations"] > 0
    part = m.parts[0]
    assert part["fixed_max_disp_mm"] > 0 and part["fixed_moved"]["nodes"] > 0 and part["fixed_moved"]["clusters"]
    assert chk.status == "PASS", chk.message
    assert chk.checks["fixed"]["status"] == "WARN" and chk.waived == ["SHELL_FIXED_REGION_VIOLATION"]
    w = next(x for x in chk.warnings if x["code"] == "SHELL_FIXED_MOVED")
    assert w["n"] == chk.checks["fixed"]["moved_fixed_nodes"] > 0 and w["clusters"]


def test_vsm19_quality_warn_and_hard_failures():
    from paicad.shell.judge import quality_judge
    from paicad.shell.quality import evaluate

    base = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [10, 0, 0], [14, 0, 0], [14, 4, 0], [10, 4, 0]], dtype=float)
    conn = np.array([[0, 1, 2, 3], [4, 5, 6, 7]])
    tri = np.array([False, False])
    sheared = base.copy()
    sheared[[6, 7], 0] += 8.0  # skew 63 deg on the big quad; the small quad keeps the minimum dt
    q = _opts()["quality"]
    rep, msg, _ = evaluate(base, sheared, conn, tri, q)
    assert msg is not None and rep["inverted"] == 0 and rep["dt_ratio"] >= q["dt_ratio_min"] and rep["failed_elements"]["skew"] == 1
    skip = quality_judge(base, sheared, conn, tri, q)
    assert skip["fail"] == ("GEOM_QUALITY", msg)  # skip: 0.14.1 code and message
    qw = dict(q, fail_policy="warn")
    w = quality_judge(base, sheared, conn, tri, qw)
    assert w["fail"] is None and w["check"]["status"] == "WARN" and w["waived"] == ["GEOM_QUALITY"]
    assert w["warnings"][-1]["code"] == "SHELL_QUALITY_WARN" and w["warnings"][-1]["failed_elements"]["skew"] == 1
    inv = base.copy()
    inv[2] = [-1.0, -1.0, 0.0]  # inverted quad
    h = quality_judge(base, inv, conn, tri, qw)
    assert h["fail"][0] == "GEOM_QUALITY_HARD" and "inverted" in h["fail"][1]
    flat = base.copy()
    flat[[2, 3], 1] = 0.1  # dt_ratio collapse without inversion
    h = quality_judge(base, flat, conn, tri, qw)
    assert h["fail"][0] == "GEOM_QUALITY_HARD" and "dt_ratio" in h["fail"][1] and "inverted" not in h["fail"][1]


def test_vsm19_tie_fails_under_warn(shell_golden):
    import argparse

    from paicad.shell.check import check_core
    from paicad.shell.morph import load_inputs

    g = shell_golden
    ns = argparse.Namespace(features=g["features_path"], tag_dir=g["tag_dir"], fixed_dir=g["fixed_dir"], assem_dir=g["assem"], update_dir=g["update0"])
    o = _opts({"fixed": {"policy": "warn"}, "quality": {"fail_policy": "warn"}})
    doc, _, _, asm, _, samples, meshes = load_inputs(ns, o)
    m = meshes[0]
    tie_sec = set(g["truth"]["fixed"]["nodes"]["INTER_TYPE2_SECONDARY"])
    sel = np.flatnonzero(np.isin(m.node_ids, sorted(tie_sec)))
    x = m.xyz.copy()
    x[sel[:5], 2] += 5.0  # tie secondary nodes lifted off the bracket
    zero = {m.index: np.zeros(len(m.node_ids))}
    r = check_core(meshes, {m.index: x}, samples, doc, {}, {}, {}, o, asm, {}, {"dist_of": zero}, None, full=True)
    assert r.status == "FAIL" and r.checks["tie"]["status"] == "FAIL" and r.checks["fixed"]["status"] == "WARN" and "SHELL_FIXED_REGION_VIOLATION" in r.waived
    assert r.code in ("GEOM_DEVIATION", "GEOM_TIE_PROJECTION")  # tie failure is never waived (deviation ranks first)


def test_vsm19_sweep_warn_column(shell_golden, tmp_path):
    g = shell_golden
    o = _write(tmp_path, "o.json", {"schema_version": 1, "fixed": {"policy": "warn"}})
    name = g["names"]["B5"]["BEAD_DEPTH"]
    code, log = run_cli("shell", "morph", "--sweep", "--assem-dir", g["assem"], "--tag-dir", g["tag_dir"], "--fixed-dir", g["fixed_dir"], "--features", g["features_path"],
                        "--update-dir", g["update0"], "--out-dir", tmp_path / "s", "--params", name, "--steps", "5", "--options", o)
    assert code == 0, log
    head, *rows = (tmp_path / "s" / "envelope.csv").read_text().splitlines()
    assert head.endswith(",fixed_moved_nodes") and all(r.split(",")[-1] != "" for r in rows)
    env = json.loads((tmp_path / "s" / "envelope.json").read_text())
    assert env["summary"][0]["limited_by"] == {"+": None, "-": None}
    assert any(r["fail_code"] != "SHELL_FIXED_REGION_VIOLATION" for r in env["rows"])


# ------------------------------------------------------------------ V-SM-20 hold
def test_vsm20_hold(smi):
    from paicad.shell.judge import Tables, element_faces, hold_weights
    from paicad.shell.update import update_core

    c = smi
    i2 = _bead(c, (300.0, 100.0))
    assert i2["fixed_overlap"] == "inside" and i2["hold_eligible"] is True
    name = _fname(c, i2, "BEAD_DEPTH")
    vals = {name: c["nom"][name] * 1.2}
    o = _opts({"bead": {"hold": {"beads": [i2["id"]]}}})
    with pytest.raises(PaicadError) as e:
        update_core(c["nominal"], c["doc"], vals, _opts(), c["fixed"])
    assert e.value.code == "SHELL_FIXED_REGION_VIOLATION"
    res, m, chk = _cores(c, vals, o)
    assert chk.status == "PASS", chk.message
    assert res.fixed_precheck["status"] == "PASS" and res.fixed_precheck["held"] > 0
    mesh = c["meshes"][0]
    d = m.disp[0]
    assert np.all(m.xyz[0][mesh.fixed] == mesh.xyz[mesh.fixed])  # fixed (anchor) nodes exactly unchanged
    topo = c["nominal"][0].topology()
    ef = element_faces(mesh.conn, mesh.tri, mesh.kind, mesh.ent, Tables.from_topology(topo))
    isl = {int(x[1:]) for i in i2["islands"] for x in i["faces"]}
    region = {int(x[1:]) for k in ("fillets_top", "flanks", "fillets_bottom", "bottom") for x in i2[k]} | isl
    anchors = {int(x[1:]) for x in i2["bottom"]} | isl
    phi, gd, reg = hold_weights(mesh.xyz, mesh.conn, mesh.tri, ef, region, anchors, mesh.fixed, 3.0, 8.0)
    near = reg & (gd <= 3.0)
    assert near.any() and float(np.abs(d[near]).max()) == 0.0
    bottom = [int(x[1:]) for x in i2["bottom"]]
    far = np.flatnonzero(reg & (gd >= 11.0) & (mesh.kind == KF) & np.isin(mesh.ent, bottom))
    assert len(far) and np.allclose(d[far, 2], -0.8, atol=1e-6)  # full depth change (in-plane: keep_angle bottom shrink)
    boss = float(np.mean(m.xyz[0][far, 2])) - float(np.mean(m.xyz[0][mesh.fixed & reg, 2]))
    boss0 = float(np.mean(mesh.xyz[far, 2])) - float(np.mean(mesh.xyz[mesh.fixed & reg, 2]))
    assert abs((boss0 - boss) - 0.8) <= 0.05  # boss height grows by the depth change
    assert chk.checks["hold"]["beads"] == [i2["id"]] and chk.checks["hold"]["nodes"] > 0
    # not eligible -> input error; beads [] = default result
    with pytest.raises(PaicadError) as e:
        update_core(c["nominal"], c["doc"], vals, _opts({"bead": {"hold": {"beads": [_bead(c, (130.0, 100.0))["id"]]}}}), c["fixed"])
    assert e.value.code == "GEOM_INPUT_INVALID"
    i1 = _bead(c, (130.0, 100.0))
    v1 = {_fname(c, i1, "BEAD_DEPTH"): 4.4}
    _, m0, _ = _cores(c, v1)
    _, m1, _ = _cores(c, v1, _opts({"bead": {"hold": {"beads": []}}}))
    assert np.array_equal(m0.xyz[0], m1.xyz[0])
    # moving the bead away from its anchors: hold collision
    with pytest.raises(PaicadError) as e:
        update_core(c["nominal"], c["doc"], {_fname(c, i2, "BEAD_POS_U"): c["nom"][_fname(c, i2, "BEAD_POS_U")] + 20.0}, o, c["fixed"])
    assert e.value.code == "GEOM_FEATURE_COLLISION" and e.value.detail["collisions"][0]["kind"] == "hold"


# ------------------------------------------------------------------ V-SM-21 judgement core
def _close(a, b, path="") -> list[str]:
    """Differences beyond the V-SM-21 tolerance: codes / strings / ints equal, floats rel 1e-6 or abs 1e-9, warning
    messages are text renderings of the compared fields and are not compared."""
    if isinstance(a, dict) and isinstance(b, dict):
        if set(a) != set(b):
            return [f"{path}: keys {sorted(set(a) ^ set(b))}"]
        return [d for k in a if not (k == "message" and "code" in a) for d in _close(a[k], b[k], f"{path}.{k}")]
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        if len(a) != len(b):
            return [f"{path}: length {len(a)} != {len(b)}"]
        return [d for i, (u, v) in enumerate(zip(a, b)) for d in _close(u, v, f"{path}[{i}]")]
    if isinstance(a, (float, np.floating)) and isinstance(b, (float, np.floating, int)):
        if a == b or abs(a - b) <= max(1e-9, 1e-6 * abs(a)):
            return []
        return [f"{path}: {a!r} != {b!r}"]
    if isinstance(a, np.ndarray):
        return [] if np.array_equal(a, b) else [f"{path}: arrays differ"]
    return [] if a == b else [f"{path}: {a!r} != {b!r}"]


def _judge_roundtrip(c, vals: dict, tmp: Path, o=None) -> dict:
    """judge(memory) vs judge(arrays of the include copies written by the morph writer and read back by the assembly reader)."""
    import shutil

    from paicad.shell.assem import read_assembly
    from paicad.shell.check import judge_inputs
    from paicad.shell.fixed import part_mesh
    from paicad.shell.judge import judge_mesh
    from paicad.shell.morph import morph_core, write_files
    from paicad.shell.update import update_core

    o = o or _opts()
    res = update_core(c["nominal"], c["doc"], vals, o, c["fixed"])
    sample = {b.name: b for b in res.bodies}
    mr = morph_core(c["meshes"], sample, {"changed": res.changed, "beads": res.beads}, o)
    m = c["meshes"][0]
    x = mr.xyz[m.index]  # memory coordinates, not rounded
    J = judge_inputs(m, x, sample[m.body], c["doc"], res.expected, res.changed.get(m.body, {}), o, set(shopts.hold_ids(o)))
    mem = judge_mesh(J, o)
    A = tmp / "assem"
    shutil.copytree(c["g"]["assem"], A)
    files = write_files(c["asm"], mr.moved, None)
    assert files
    for rel, data, *_ in files:
        (A / rel).write_bytes(data)
    asm = read_assembly(A)
    pm = part_mesh(asm, 2001)
    assert np.array_equal(pm.node_ids, m.node_ids)
    J2 = copy.copy(J)
    J2.x = asm.xyz[asm.index(pm.node_ids)]
    J2.conn, J2.tri = np.searchsorted(pm.node_ids, pm.conn), pm.tri
    assert np.array_equal(J2.conn, m.conn) and np.array_equal(J2.tri, m.tri)
    disk = judge_mesh(J2, o)
    assert set(mem["fails"]) == set(disk["fails"]) and [w["code"] for w in mem["warnings"]] == [w["code"] for w in disk["warnings"]]
    diffs = _close({k: v for k, v in mem.items() if k != "fails"}, {k: v for k, v in disk.items() if k != "fails"})
    assert not diffs, diffs[:5]
    return mem


@pytest.mark.parametrize("case", [1, 2, 3, 4])
def test_vsm21_judge_memory_equals_files(smh, tmp_path, case):
    c = smh[case]
    island_beads = [b for b in c["doc"]["beads"] if b.get("islands")]
    b = island_beads[0] if island_beads else c["doc"]["beads"][0]
    o = None
    if b.get("hold_eligible"):
        o = _opts({"bead": {"hold": {"beads": [b["id"]]}}})
    name = _fname(c, b, "BEAD_DEPTH")
    mem = _judge_roundtrip(c, {name: c["nom"][name] * 1.1}, tmp_path, o)
    assert set(mem["checks"]) >= {"fixed", "quality", "feature"}


def test_vsm21_judge_has_no_kernel_import():
    src = Path(__file__).resolve().parents[1] / "src" / "paicad" / "shell" / "judge.py"
    mods = set()
    for node in ast.walk(ast.parse(src.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            mods |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            mods.add(("." * node.level) + (node.module or ""))
    assert not any("kernel" in m or m.startswith("OCP") or "beads" in m or "cad" in m for m in mods), mods


def test_vsm21_island_mismatch_is_information_only(smh):
    w = [x for x in smh[4]["tag_doc"]["warnings"] if x["code"] == "TAG_ISLAND_MISMATCH"]
    t = _bead(smh[4], (120.0, 70.0))
    assert smh[4]["tag_doc"]["status"] == "OK" and w and w[0]["bead"] == t["id"] and w[0]["brep"] == len(t["islands"]) == 5 and w[0]["mesh"] != 5
    for k in (1, 2, 3):
        assert not [x for x in smh[k]["tag_doc"]["warnings"] if x["code"] == "TAG_ISLAND_MISMATCH"]


# ------------------------------------------------------------------ V-SM-22 esl hard cases
def test_vsm22_smh1_crossing_and_dimples(smh):
    c = smh[1]
    doc = c["doc"]
    assert len(doc["beads"]) == 1  # no false READY for the crossing pair
    assert any(x["code"] == "BEAD_IRREGULAR" for x in doc["warnings"])
    d = doc["beads"][0]
    assert [i["kind"] for i in d["islands"]] == ["feature", "feature"]
    name = _fname(c, d, "BEAD_DEPTH")
    _, m, chk = _cores(c, {name: c["nom"][name] * 1.1})
    assert chk.status == "PASS", chk.message
    assert chk.checks["feature"]["features"] == 2


def test_vsm22_smh2_stairs(smh):
    c = smh[2]
    doc = c["doc"]
    msgs = [x["message"] for x in doc["warnings"] if x["code"] == "BEAD_IRREGULAR"]
    assert sum("nested bead" in m for m in msgs) == 2  # both outer steps
    assert any(x["code"] == "BEAD_ISLAND_TOO_LARGE" for x in doc["warnings"])  # middle step of A: inner step > 40 mm
    ai = _bead(c, (100.0, 150.0))
    assert abs(ai["nominal"]["width"] - 50.0) < 0.01 and [i["kind"] for i in ai["islands"]] == ["hole"]
    bm = [b for b in doc["beads"] if abs(b["center"][0] - 290.0) < 1e-6 and abs(b["nominal"]["width"] - 66.0) < 0.01]
    assert len(bm) == 1 and len(bm[0]["islands"]) == 2  # small inner step (<= 40 mm) absorbed as an island
    assert not any(abs(b["nominal"]["width"] - 24.0) < 0.01 for b in doc["beads"])
    name = _fname(c, ai, "BEAD_DEPTH")
    res, m, chk = _cores(c, {name: c["nom"][name] * 1.1})
    assert chk.status == "PASS", chk.message
    t = np.asarray(next(s for s in res.beads if s["id"] == ai["id"])["island_shift"])
    mesh = c["meshes"][0]
    hole = np.flatnonzero((mesh.kind == KE) & np.isin(mesh.ent, [int(x[1:]) for x in ai["islands"][0]["loop"]]))
    assert len(hole) and float(np.abs(m.disp[0][hole] - t).max()) <= 1e-6


def test_vsm22_smh3_near_and_merged(smh):
    from paicad.shell.update import update_core

    c = smh[3]
    doc = c["doc"]
    assert len(doc["beads"]) == 2 and any(x["code"] == "BEAD_IRREGULAR" for x in doc["warnings"])  # merged pocket refused
    b1, b2 = sorted(doc["beads"], key=lambda b: b["center"][1])
    fw = next(f for f in doc["features"] if f["name"] == _fname(c, b1, "BEAD_WIDTH"))
    assert fw["feasible"]["limited_by"] == _fname(c, b2, "BEAD_WIDTH")
    fv = next(f for f in doc["features"] if f["bead"] == b1["id"] and f["type"] in ("BEAD_POS_U", "BEAD_POS_V") and abs(f["ref"]["axis"][1]) > 0.9)
    assert fv["feasible"]["limited_by"] == _fname(c, b2, "BEAD_WIDTH")
    toward = fv["nominal"] + 3.0 * (1 if fv["ref"]["sign"] * fv["ref"]["axis"][1] > 0 else -1) * (1 if b2["center"][1] > b1["center"][1] else -1)
    with pytest.raises(PaicadError) as e:
        update_core(c["nominal"], doc, {fv["name"]: toward}, _opts(), c["fixed"])
    assert e.value.code == "GEOM_FEATURE_COLLISION"
    name = _fname(c, b1, "BEAD_DEPTH")
    _, m, chk = _cores(c, {name: c["nom"][name] * 1.1})
    assert chk.status == "PASS", chk.message
    mesh = c["meshes"][0]
    other = [int(x[1:]) for k in ("fillets_top", "flanks", "fillets_bottom", "bottom") for x in b2[k]]
    sel = np.flatnonzero((mesh.kind == KF) & np.isin(mesh.ent, other))
    assert len(sel) and float(np.abs(m.disp[0][sel]).max()) == 0.0  # neighbour bead does not move (B9)


def test_vsm22_smh4_dense_islands_slot_hold(smh):
    c = smh[4]
    doc = c["doc"]
    assert any(x["code"] == "BEAD_OPEN_UNSUPPORTED" for x in doc["warnings"])  # slot through the wall
    t = _bead(c, (120.0, 70.0))
    assert len(t["islands"]) == 5 and sum(i["free_loops"] for i in t["islands"]) == 3  # 2 louver slots + boss hole
    assert t["fixed_overlap"] == "inside" and t["hold_eligible"] is True
    name = _fname(c, t, "BEAD_DEPTH")
    vals = {name: c["nom"][name] * 1.1}
    o = _opts({"bead": {"hold": {"beads": [t["id"]]}}})
    res, m, chk = _cores(c, vals, o)
    assert chk.status == "PASS", chk.message
    assert chk.checks["hold"]["beads"] == [t["id"]] and chk.checks["feature"]["features"] == 4  # the anchored boss is left to hold
    from paicad.shell.check import check_core

    mesh = c["meshes"][0]
    bad = m.xyz[0].copy()
    louver = t["islands"][0]
    sel = _island_nodes(mesh, louver)
    bad[sel] = mesh.xyz[sel]
    sample = {b.name: b for b in res.bodies}
    r = check_core(c["meshes"], {0: bad}, sample, doc, vals, res.expected, res.changed, o, None, {}, {"dist_of": {0: np.zeros(len(mesh.node_ids))}}, None, full=False)
    assert r.code == "SHELL_FEATURE_DISTORTED"
