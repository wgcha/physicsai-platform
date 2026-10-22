"""Assembly match (asm-match.md, paicad 0.13.0): ``paicad asm parts | check | write`` and method M of the solid
commands (V-AM-1 ~ V-AM-8, paicad part). Synthetic assemblies only (``data/make_asm.py``); nothing committed."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import gltf_check as gc
import numpy as np
import paicad
import pytest
from conftest import run_cli
from data.make_asm import (
    ELEM_START,
    MESH_INC,
    NODE_START,
    PARTS_INC,
    PID,
    STARTER,
    SUB_INC,
    box_mesh,
    features_doc,
    write_json,
    write_match,
    write_split,
)
from paicad.common import sha256_file
from paicad.mesh.asmtree import build
from paicad.meshsrc import AsmSource
from paicad.mesh.radioss import parse_text

BOX_L = ((-150.0, 0.0, 0.0), (-30.0, 80.0, 20.0))
BOX_R = ((30.0, 0.0, 0.0), (150.0, 80.0, 20.0))
VOL = 120.0 * 80.0 * 20.0
ROWS = [{"body": "CUSH_L", "pids": [PID[0]]}, {"body": "CUSH_R", "pids": [PID[1]]}]
OCP_BLOCK = (
    "import sys, importlib.abc\n"
    "class Block(importlib.abc.MetaPathFinder):\n"
    "    def find_spec(self, name, path=None, target=None):\n"
    "        if name == 'OCP' or name.startswith('OCP.'):\n"
    "            raise ImportError('OCP blocked')\n"
    "sys.meta_path.insert(0, Block())\n"
    "from paicad.cli import main\n"
    "code = main(sys.argv[1:])\n"
    "assert 'OCP' not in sys.modules\n"
    "sys.exit(code)\n"
)


def load(p) -> dict:
    return json.loads(Path(p).read_text(encoding="utf-8"))


def box_assembly(root: Path, eol: str = "\n", **kw) -> dict:
    meshes = [box_mesh(*BOX_L, (6, 4, 2)), box_mesh(*BOX_R, (6, 4, 2))]
    a = write_split(root / "assem", meshes, eol=eol, **kw)
    a["meshes"] = meshes
    a["features"] = write_json(root / "features.json", features_doc({"CUSH_L": ([*BOX_L[0], *BOX_L[1]], VOL), "CUSH_R": ([*BOX_R[0], *BOX_R[1]], VOL)}))
    return a


def parts_cli(assem, out, features, *extra):
    return run_cli("asm", "parts", "--assem-dir", assem, "--features", features, "--out-dir", out, *extra)


def run_sub(prog: str, argv: list) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    src = str(Path(paicad.__file__).resolve().parents[1])
    return subprocess.run([sys.executable, "-c", f"import sys; sys.path.insert(0, {src!r})\n" + prog, *map(str, argv)], capture_output=True, text=True, timeout=300, env=env)


# ------------------------------------------------------------------ V-AM-1 parts
def test_parts_tree_parts_and_unused_file(tmp_path):
    a = box_assembly(tmp_path)
    out = tmp_path / "p"
    code, log = parts_cli(a["folder"], out, a["features"])
    assert code == 0, log
    d = load(out / "asm_parts.json")
    assert d["status"] == "OK" and d["engine_version"] == paicad.__version__
    tree = d["assem"]["tree"]
    assert [t["rel"] for t in tree] == [STARTER, PARTS_INC, MESH_INC, SUB_INC]
    assert tree[0]["includes"] == [PARTS_INC, MESH_INC, SUB_INC]  # "sub\\103_more.inc" resolved like "/"
    assert d["assem"]["starter"] == STARTER and d["assem"]["digest"].startswith("sha256:") and d["assem"]["cache"] == {"hits": 0, "misses": 4}
    by = {p["pid"]: p for p in d["parts"]}
    assert sorted(by) == [2001, PID[0], PID[1]]
    l, r, plate = by[PID[0]], by[PID[1]], by[2001]
    assert l["title"] == "EPS_LEFT" and l["def_file"] == PARTS_INC and l["solid_ok"]
    assert l["elem_files"] == [MESH_INC, SUB_INC] and l["node_files"] == [MESH_INC, SUB_INC]
    assert l["elems"] == {"TETRA4": len(a["meshes"][0][1])} and l["nodes"] == len(a["meshes"][0][0])
    assert l["volume"] == pytest.approx(VOL) and l["bbox"] == [*BOX_L[0], *BOX_L[1]]
    assert r["elem_files"] == [SUB_INC] and r["node_files"] == [SUB_INC]
    assert plate["elems"] == {"SHELL": 24} and not plate["solid_ok"] and plate["volume"] is None
    assert d["bodies"] == [{"body": "CUSH_L", "volume": VOL, "bbox": [*BOX_L[0], *BOX_L[1]]}, {"body": "CUSH_R", "volume": VOL, "bbox": [*BOX_R[0], *BOX_R[1]]}]
    w = [x for x in d["warnings"] if x["code"] == "ASM_FILE_UNUSED"]
    assert w and w[0]["count"] == 1 and w[0]["files"] == ["unused.inc"]


def test_parts_without_ocp(tmp_path):
    a = box_assembly(tmp_path)
    r = run_sub(OCP_BLOCK, ["asm", "parts", "--assem-dir", a["folder"], "--features", a["features"], "--out-dir", tmp_path / "p"])
    assert r.returncode == 0, r.stdout + r.stderr
    assert load(tmp_path / "p" / "asm_parts.json")["status"] == "OK"


# ------------------------------------------------------------------ V-AM-2 recommendation
def test_recommend_by_bbox_volume_not_names_and_not_swapped(tmp_path):
    a = box_assembly(tmp_path)
    # bodies listed right-first, names unrelated to the PART titles (EPS_LEFT / EPS_RIGHT)
    f = write_json(tmp_path / "f2.json", features_doc({"RIGHT_PAD": ([*BOX_R[0], *BOX_R[1]], VOL), "LEFT_PAD": ([*BOX_L[0], *BOX_L[1]], VOL), "NOWHERE": ([500, 500, 500, 520, 520, 520], 8000.0)}))
    code, log = parts_cli(a["folder"], tmp_path / "p", f)
    assert code == 0, log
    rec = load(tmp_path / "p" / "asm_parts.json")["recommend"]
    assert [(x["body"], x["pids"]) for x in rec] == [("RIGHT_PAD", [PID[1]]), ("LEFT_PAD", [PID[0]])]
    assert all(x["basis"]["renum"] is False and x["basis"]["name"] == 0.0 and x["score"] == pytest.approx(0.9) for x in rec)


def test_recommend_name_and_renum_first(tmp_path):
    a = box_assembly(tmp_path, titles=("CUSH_L", "CUSH_R_FOAM"))
    code, log = parts_cli(a["folder"], tmp_path / "p", a["features"])
    assert code == 0, log
    rec = {x["body"]: x for x in load(tmp_path / "p" / "asm_parts.json")["recommend"]}
    assert rec["CUSH_L"]["basis"]["name"] == 1.0 and rec["CUSH_R"]["basis"]["name"] == 0.5 and rec["CUSH_L"]["score"] == pytest.approx(1.0)
    # a RENUM table maps by element ranges (score 1.0, basis.renum) even against the geometry
    csv = tmp_path / "RENUM_INIT.csv"
    csv.write_text(f"part,node_start,elem_start\nCUSH_R,{NODE_START[0]},{ELEM_START[0]}\nCUSH_L,{NODE_START[1]},{ELEM_START[1]}\n", encoding="utf-8")
    code, log = parts_cli(a["folder"], tmp_path / "p2", a["features"], "--renum-csv", csv)
    assert code == 0, log
    rec = {x["body"]: x for x in load(tmp_path / "p2" / "asm_parts.json")["recommend"]}
    assert rec["CUSH_R"]["pids"] == [PID[0]] and rec["CUSH_L"]["pids"] == [PID[1]]
    assert all(x["score"] == 1.0 and x["basis"]["renum"] for x in rec.values())


def test_recommend_min_score(tmp_path):
    a = box_assembly(tmp_path)
    f = write_json(tmp_path / "f.json", features_doc({"CUSH_L": ([-150, 0, 0, -30, 80, 25], VOL * 1.2)}))  # gate passes, iou 0.8
    opts = write_json(tmp_path / "o.json", {"schema_version": 1, "asm_match": {"recommend_min_score": 0.95}})
    code, log = parts_cli(a["folder"], tmp_path / "p", f, "--options", opts)
    assert code == 0, log
    assert load(tmp_path / "p" / "asm_parts.json")["recommend"] == []
    bad = write_json(tmp_path / "bad.json", {"schema_version": 1, "asm_match": {"worst": 1}})
    code, log = parts_cli(a["folder"], tmp_path / "p3", f, "--options", bad)
    assert code == 3 and "GEOM_INPUT_INVALID" in log


# ------------------------------------------------------------------ include tree failures
def _starter_with(folder: Path, include: str) -> None:
    p = folder / STARTER
    p.write_text(p.read_text().replace("/END", f"#include {include}\n/END"))


@pytest.mark.parametrize(
    "case,code",
    [("outside", "ASM_INCLUDE_OUTSIDE"), ("missing", "ASM_INCLUDE_MISSING"), ("cycle", "GEOM_INPUT_INVALID"), ("twice", "GEOM_INPUT_INVALID"), ("link", "ASM_INCLUDE_OUTSIDE")],
)
def test_include_failures(tmp_path, case, code):
    a = box_assembly(tmp_path)
    f = a["folder"]
    if case == "outside":
        (tmp_path / "lib.inc").write_text("/MAT/LAW1/9\nX\n")
        _starter_with(f, "../lib.inc")
    elif case == "missing":
        _starter_with(f, "nothere.inc")
    elif case == "cycle":
        (f / SUB_INC).write_text((f / SUB_INC).read_text() + "#include ../MODEL_0000.rad\n")
    elif case == "twice":
        _starter_with(f, PARTS_INC)
    else:
        os.symlink(f / "unused.inc", f / "linked.inc")
        _starter_with(f, "linked.inc")
    code_, log = parts_cli(f, tmp_path / "p", a["features"])
    assert code_ == 3, log
    assert log.strip().splitlines()[-1].startswith(f"PAICAD RESULT FAIL {code} asm_parts.json")
    d = load(tmp_path / "p" / "asm_parts.json")
    assert d["status"] == "FAIL" and d["code"] == code and d["parts"] == []


def test_starter_rules_and_part_limits(tmp_path):
    a = box_assembly(tmp_path)
    f = a["folder"]
    (f / "OTHER_0000.rad").write_text("/BEGIN\nX\n/END\n")
    code, log = parts_cli(f, tmp_path / "p1", a["features"])
    assert code == 3 and "GEOM_INPUT_INVALID" in log
    (f / "OTHER_0000.rad").unlink()
    opts = write_json(tmp_path / "o.json", {"schema_version": 1, "asm_match": {"max_parts": 2}})
    code, log = parts_cli(f, tmp_path / "p2", a["features"], "--options", opts)
    assert code == 3 and "ASM_TOO_MANY_PARTS" in log
    (f / SUB_INC).write_text("/NODE\n")
    m = (f / MESH_INC).read_text()
    (f / MESH_INC).write_text(m[: m.index("/TETRA4")] + m[m.index("/SHELL") :])
    code, log = parts_cli(f, tmp_path / "p3", a["features"])
    assert code == 3 and "ASM_NO_SOLID_PART" in log


# ------------------------------------------------------------------ V-AM-8 cache
def test_parse_cache_hits_misses_and_rename(tmp_path):
    a = box_assembly(tmp_path)
    f, cache = a["folder"], tmp_path / "cache"

    def run(n):
        code, log = parts_cli(f, tmp_path / f"p{n}", a["features"], "--cache-dir", cache)
        assert code == 0, log
        d = load(tmp_path / f"p{n}" / "asm_parts.json")
        return d, d["assem"]["cache"]

    d1, c1 = run(1)
    assert c1 == {"hits": 0, "misses": 4} and len(list(cache.glob("*.idx.npz"))) == 4
    d2, c2 = run(2)
    assert c2 == {"hits": 4, "misses": 0} and d2["parts"] == d1["parts"] and d2["recommend"] == d1["recommend"]
    (f / PARTS_INC).write_text((f / PARTS_INC).read_text().replace("EPS_LEFT", "EPS_LEFT_2"))
    d3, c3 = run(3)
    assert c3 == {"hits": 3, "misses": 1} and {p["pid"]: p["title"] for p in d3["parts"]}[PID[0]] == "EPS_LEFT_2"
    # same content under another name: the renamed file hits, only the starter (changed include line) misses
    os.replace(f / MESH_INC, f / "renamed.inc")
    (f / STARTER).write_text((f / STARTER).read_text().replace(MESH_INC, "renamed.inc"))
    _, c4 = run(4)
    assert c4 == {"hits": 3, "misses": 1}
    # a cache entry of another engine version is ignored and rebuilt; deleting the cache gives the same result
    idx = next(iter(cache.glob("*.idx.npz")))
    with np.load(idx) as z:
        arrays = {k: z[k] for k in z.files}
    meta = json.loads(str(arrays["meta"]))
    meta["engine_version"] = "0.0.0"
    arrays["meta"] = np.array(json.dumps(meta))
    with open(idx, "wb") as fh:
        np.savez(fh, **arrays)
    d5, c5 = run(5)
    assert c5["misses"] == 1
    shutil.rmtree(cache)
    d6, c6 = run(6)
    assert c6 == {"hits": 0, "misses": 4} and d6["parts"] == d5["parts"]


# ------------------------------------------------------------------ V-AM-7 write
def _patch(path: Path, ids, xyz) -> Path:
    with open(path, "wb") as fh:
        np.savez(fh, node_id=np.asarray(ids, dtype=np.int64), xyz=np.asarray(xyz, dtype=np.float64))
    return path


def _only_coordinates_changed(old: bytes, new: bytes, moved: set[int]) -> int:
    a, b = old.splitlines(keepends=True), new.splitlines(keepends=True)
    assert len(a) == len(b)
    in_node, n = False, 0
    for x, y in zip(a, b):
        if x.startswith(b"/"):
            in_node = x.strip().upper() == b"/NODE"
        if x == y:
            continue
        assert in_node and int(x[:10]) in moved, x
        assert len(x) == len(y) and x[:10] == y[:10] and x[len(x.rstrip(b"\r\n")) :] == y[len(y.rstrip(b"\r\n")) :]
        n += 1
    return n


@pytest.mark.parametrize("eol", ["\n", "\r\n"], ids=["lf", "crlf"])
def test_write_patch_lines_only_across_files(tmp_path, eol):
    a = box_assembly(tmp_path, eol=eol)
    f = a["folder"]
    m = write_match(tmp_path / "asm_match.json", f, ROWS)
    before = {p: p.read_bytes() for p in f.rglob("*") if p.is_file()}
    # nominal copy: byte identical
    code, log = run_cli("asm", "write", "--assem-dir", f, "--asm-match", m, "--out-dir", tmp_path / "nom")
    assert code == 0, log
    for rel in a["files"]:
        assert (tmp_path / "nom" / rel).read_bytes() == (f / rel).read_bytes()
    assert not (tmp_path / "nom" / "unused.inc").exists()  # outside the tree: not copied
    w = load(tmp_path / "nom" / "asm_write.json")
    assert w["status"] == "OK" and w["patch"] is None and w["nodes_written"] == 0 and all(x["changed_lines"] == 0 for x in w["files"])
    # patch: every node of cushion L (split over two files, mixed with product nodes) + 3 nodes of cushion R
    xl = a["meshes"][0][0]
    ids = [NODE_START[0] + i for i in range(len(xl))] + [NODE_START[1] + i for i in range(3)]
    xyz = np.concatenate([xl + np.array([0.123456789, -1.5, 2.25]), a["meshes"][1][0][:3] * 1.001])
    p = _patch(tmp_path / "node_patch.npz", ids, xyz)
    code, log = run_cli("asm", "write", "--assem-dir", f, "--asm-match", m, "--patch", p, "--out-dir", tmp_path / "out")
    assert code == 0, log
    w = load(tmp_path / "out" / "asm_write.json")
    changed = {x["rel"]: x["changed_lines"] for x in w["files"]}
    assert w["nodes_written"] == len(ids)
    moved = set(ids)
    n_mesh = _only_coordinates_changed((f / MESH_INC).read_bytes(), (tmp_path / "out" / MESH_INC).read_bytes(), moved)
    n_sub = _only_coordinates_changed((f / SUB_INC).read_bytes(), (tmp_path / "out" / SUB_INC).read_bytes(), moved)
    assert n_mesh == changed[MESH_INC] > 0 and n_sub == changed[SUB_INC] > 0 and n_mesh + n_sub == len(ids)
    assert changed[STARTER] == changed[PARTS_INC] == 0
    for rel in (STARTER, PARTS_INC):
        assert (tmp_path / "out" / rel).read_bytes() == (f / rel).read_bytes()
    got = {}
    for rel in (MESH_INC, SUB_INC):
        mm = parse_text((tmp_path / "out" / rel).read_bytes().decode())
        got.update({int(n): x for n, x in zip(mm.node_ids, mm.xyz)})
    for n, x in zip(ids, xyz):
        assert np.allclose(got[n], x, rtol=1e-9, atol=1e-6)
    assert {p: p.read_bytes() for p in f.rglob("*") if p.is_file()} == before  # the assembly folder is only read


def test_write_rejections(tmp_path):
    a = box_assembly(tmp_path)
    f = a["folder"]
    m = write_match(tmp_path / "asm_match.json", f, ROWS)
    bad = _patch(tmp_path / "bad.npz", [1], [[0.0, 0.0, 0.0]])  # a product node
    code, log = run_cli("asm", "write", "--assem-dir", f, "--asm-match", m, "--patch", bad, "--out-dir", tmp_path / "o1")
    assert code == 3 and "ASM_MATCH_INVALID" in log
    code, log = run_cli("asm", "write", "--assem-dir", f, "--asm-match", m, "--out-dir", f / "copy")
    assert code == 3 and "GEOM_INPUT_INVALID" in log
    code, log = run_cli("asm", "write", "--assem-dir", f, "--asm-match", m, "--out-dir", tmp_path / "o2")
    assert code == 0, log
    code, log = run_cli("asm", "write", "--assem-dir", f, "--asm-match", m, "--out-dir", tmp_path / "o2")
    assert code == 3 and "GEOM_OUTPUT_EXISTS" in log
    (f / PARTS_INC).write_text((f / PARTS_INC).read_text() + "#\n")  # tree changed after the confirmation
    code, log = run_cli("asm", "write", "--assem-dir", f, "--asm-match", m, "--out-dir", tmp_path / "o3")
    assert code == 3 and "ASM_MATCH_INVALID" in log
    assert load(tmp_path / "o3" / "asm_write.json")["code"] == "ASM_MATCH_INVALID"
    # duplicate node definition in the tree
    (f / SUB_INC).write_text((f / SUB_INC).read_text().replace("/NODE\n", f"/NODE\n{1:10d}{0.0:20.10f}{0.0:20.10f}{0.0:20.10f}\n", 1))
    m2 = write_match(tmp_path / "m2.json", f, ROWS)
    code, log = run_cli("asm", "write", "--assem-dir", f, "--asm-match", m2, "--out-dir", tmp_path / "o4")
    assert code == 3 and "defined more than once" in load(tmp_path / "o4" / "asm_write.json")["message"]
    junk = write_json(tmp_path / "junk.json", {"schema_version": 1, "rows": [{"body": "A", "pids": [PID[0]]}, {"body": "B", "pids": [PID[0]]}], "assem": {"digest": "sha256:x"}})
    code, log = run_cli("asm", "write", "--assem-dir", f, "--asm-match", junk, "--out-dir", tmp_path / "o5")
    assert code == 3 and "ASM_MATCH_INVALID" in log and "one component per row" in load(tmp_path / "o5" / "asm_write.json")["message"]


# ------------------------------------------------------------------ cushion write (method M)
def test_cushion_write_from_match_with_patch(tmp_path):
    a = box_assembly(tmp_path)
    f = a["folder"]
    m = write_match(tmp_path / "asm_match.json", f, ROWS)
    xl = a["meshes"][0][0]
    ids = [NODE_START[0] + i for i in range(len(xl))]
    p = _patch(tmp_path / "node_patch.npz", ids, xl + 1.0)
    rad = tmp_path / "o" / "EPS_mesh_0000.rad"
    r = run_sub(OCP_BLOCK, ["cushion", "write", "--asm-match", m, "--assem-dir", f, "--patch", p, "--out-dir", tmp_path / "o" / "c", "--out-rad", rad])
    assert r.returncode == 0, r.stdout + r.stderr
    data = rad.read_bytes()
    assert b"#include" not in data and data.startswith(b"#RADIOSS STARTER\n/BEGIN\nEPS_mesh_0000\n")
    mesh = parse_text(data.decode())
    nl, nr = len(a["meshes"][0][0]), len(a["meshes"][1][0])
    assert sorted(mesh.node_ids.tolist()) == sorted(ids + [NODE_START[1] + i for i in range(nr)])
    xyz = dict(zip(mesh.node_ids.tolist(), mesh.xyz))
    assert np.allclose(xyz[ids[5]], xl[5] + 1.0) and np.allclose(xyz[NODE_START[1]], a["meshes"][1][0][0])
    assert [(b.keyword, b.part_id) for b in mesh.blocks] == [("TETRA4", PID[0]), ("TETRA4", PID[0]), ("TETRA4", PID[1])]
    assert sum(len(b.ids) for b in mesh.blocks) == len(a["meshes"][0][1]) + len(a["meshes"][1][1])
    for kw in (b"/PART/3000001", b"/PART/3000002", b"/PROP/TYPE14/1", b"/MAT/LAW70/1"):
        assert kw in data
    for kw in (b"/PART/2001", b"/SHELL", b"/INTER", b"/GRNOD", b"/PROP/TYPE1/2"):
        assert kw not in data
    doc = load(tmp_path / "o" / "c" / "cushion.json")
    assert doc["status"] == "OK" and doc["node_count"] == nl + nr and doc["def_sources"] == [PARTS_INC]
    assert [(x["part"], x["components"]) for x in doc["parts"]] == [(PID[0], ["CUSH_L"]), (PID[1], ["CUSH_R"])] and doc["warnings"] == []
    # nominal (no patch): node lines are byte copies of the tree lines
    rad2 = tmp_path / "o2" / "EPS_mesh_0000.rad"
    code, log = run_cli("cushion", "write", "--asm-match", m, "--assem-dir", f, "--out-dir", tmp_path / "o2" / "c", "--out-rad", rad2)
    assert code == 0, log
    lines = set((f / MESH_INC).read_bytes().splitlines()) | set((f / SUB_INC).read_bytes().splitlines())
    node_lines = [ln for ln in rad2.read_bytes().splitlines() if ln[:10].strip().isdigit() and int(ln[:10]) in set(mesh.node_ids.tolist()) and len(ln) == 70]
    assert len(node_lines) == nl + nr and all(ln in lines for ln in node_lines)


# ------------------------------------------------------------------ mesh source arguments
def test_mesh_source_argument_rules(tmp_path):
    a = box_assembly(tmp_path)
    m = write_match(tmp_path / "asm_match.json", a["folder"], ROWS)
    code, log = run_cli("cushion", "write", "--asm-match", m, "--inc", tmp_path / "x.inc", "--assem-dir", a["folder"], "--out-dir", tmp_path / "c", "--out-rad", tmp_path / "c" / "x.rad")
    assert code == 3 and "GEOM_INPUT_INVALID" in log and load(tmp_path / "c" / "cushion.json")["code"] == "GEOM_INPUT_INVALID"
    for argv in (
        ["tag", "--cad", "x", "--features", "x", "--assem-dir", "x", "--out-dir", tmp_path / "t"],
        ["tag", "--cad", "x", "--features", "x", "--assem-dir", "x", "--out-dir", tmp_path / "t", "--baseline-inc", "x"],
        ["morph", "--asm-match", m, "--tag-dir", "x", "--features", "x", "--update-dir", "x", "--out-dir", tmp_path / "m"],
        ["check", "--asm-match", m, "--morph-dir", "x", "--update-dir", "x", "--tag-dir", "x", "--features", "x", "--values", "x", "--assem-dir", "x", "--out-dir", tmp_path / "k"],
        ["asm", "parts", "--assem-dir", "x", "--out-dir", tmp_path / "p"],
        ["asm", "parts", "--assem-dir", "x", "--out-dir", tmp_path / "p", "--features", "a", "--cad", "b"],
    ):
        r = subprocess.run([sys.executable, "-m", "paicad", *map(str, argv)], capture_output=True, text=True, timeout=60, cwd=str(Path(paicad.__file__).parents[1]))
        assert r.returncode == 2, (argv, r.stderr)


def test_large_tree_smoke(tmp_path):
    """Streaming index throughput smoke (asm-match.md AM-11): ~0.3 M elements, cached second pass."""
    big = box_mesh((-150.0, 0.0, 0.0), (-30.0, 80.0, 20.0), (60, 40, 20))
    small = box_mesh(*BOX_R, (2, 2, 1))
    a = write_split(tmp_path / "assem", [big, small])
    f = write_json(tmp_path / "f.json", features_doc({"CUSH_L": ([*BOX_L[0], *BOX_L[1]], VOL)}))
    t0 = time.monotonic()
    code, log = parts_cli(a["folder"], tmp_path / "p1", f, "--cache-dir", tmp_path / "cache")
    t1 = time.monotonic() - t0
    assert code == 0, log
    d = load(tmp_path / "p1" / "asm_parts.json")
    assert {p["pid"]: p["elems"]["TETRA4"] for p in d["parts"] if p["solid_ok"]}[PID[0]] == len(big[1]) == 288000
    t0 = time.monotonic()
    code, log = parts_cli(a["folder"], tmp_path / "p2", f, "--cache-dir", tmp_path / "cache")
    t2 = time.monotonic() - t0
    assert code == 0 and load(tmp_path / "p2" / "asm_parts.json")["assem"]["cache"]["hits"] == 4
    assert t1 < 120 and t2 < t1, (t1, t2)


# ------------------------------------------------------------------ golden (CAD) checks: V-AM-3 ~ V-AM-6
@pytest.fixture(scope="module")
def gsplit(golden, tmp_path_factory):
    """Golden cushions in the split layout: cushion L over two files mixed with product nodes."""
    root = tmp_path_factory.mktemp("asm_golden")
    meshes = [(golden["meshes"][0][0], golden["meshes"][0][1]), (golden["meshes"][1][0], golden["meshes"][1][1])]
    a = write_split(root / "assem", meshes)
    a.update(root=root, meshes=meshes)
    return a


def check_cli(golden, assem, out, rows, *extra, excluded=None):
    m = write_json(Path(out).parent / f"{Path(out).name}_rows.json", {"rows": rows, "excluded_bodies": excluded or []})
    code, log = run_cli("asm", "check", "--cad", golden["step"], "--features", golden["features_path"], "--assem-dir", assem, "--match", m, "--out-dir", out, *extra)
    return code, log, (load(Path(out) / "asm_check.json") if (Path(out) / "asm_check.json").is_file() else None)


def test_check_pass_split_files_glb(golden, gsplit, tmp_path):
    code, log, d = check_cli(golden, gsplit["folder"], tmp_path / "c", ROWS, "--cache-dir", tmp_path / "cache")
    assert code == 0, log
    assert d["status"] == "PASS" and d["code"] is None and d["engine_version"] == paicad.__version__
    for r in d["rows"]:
        assert r["status"] == "PASS" and r["match_ratio"] >= 0.98 and r["dist_mm"]["max"] <= r["tol_mm"] and r["skin_nodes"] > 500
        assert r["shared"] == {"nodes": 0, "parts": []} and r["faces"]["uncovered"] == [] and r["suggest"] is None
        z = np.load(tmp_path / "c" / r["worst"]["file"])
        assert len(z["node_id"]) == r["worst"]["count"] == min(2000, r["skin_nodes"]) and z["xyz"].shape == (r["worst"]["count"], 3)
    assert d["assem"]["node_files"] == [{"rel": MESH_INC, "nodes": len(gsplit["meshes"][0][0]) // 2}, {"rel": SUB_INC, "nodes": len(gsplit["meshes"][0][0]) - len(gsplit["meshes"][0][0]) // 2 + len(gsplit["meshes"][1][0])}]
    assert d["assem"]["elem_files"] == [MESH_INC, SUB_INC] and d["file_checks"]["shared_nodes"] == 0 and d["file_checks"]["duplicate_node_defs"] == 0
    assert d["tolerance"] == {"abs_mm": 0.05, "rel": 1e-4, "min_match_ratio": 0.98} and len(d["rows_sha256"]) == 64
    doc, bin_ = gc.load(tmp_path / "c" / "match_fe.glb")
    assert d["glb"]["file"] == "match_fe.glb"
    nm = gc.node_mesh(doc, bin_, "CUSH_L")
    assert {"POSITION", "NORMAL", "_DIST_MM", "_ELEM_ID"} <= set(nm) and float(nm["_DIST_MM"].max()) <= 0.05
    code, log, d2 = check_cli(golden, gsplit["folder"], tmp_path / "c2", ROWS, "--cache-dir", tmp_path / "cache", "--no-glb")
    assert code == 0 and d2["glb"] is None and not (tmp_path / "c2" / "match_fe.glb").exists() and d2["assem"]["cache"]["hits"] == 4


def test_check_swapped_rows_fail(golden, gsplit, tmp_path):
    rows = [{"body": "CUSH_L", "pids": [PID[1]]}, {"body": "CUSH_R", "pids": [PID[0]]}]
    code, log, d = check_cli(golden, gsplit["folder"], tmp_path / "c", rows)
    assert code == 15, log
    assert d["status"] == "FAIL" and d["code"] == "ASM_BOUNDARY_MISMATCH" and d["category"] == "ASM"
    assert all(r["code"] == "ASM_BOUNDARY_MISMATCH" and r["match_ratio"] < 0.5 and r["dist_mm"]["max"] > 50 for r in d["rows"])
    nm = gc.node_mesh(*gc.load(tmp_path / "c" / "match_fe.glb"), "CUSH_L")
    assert float(nm["_DIST_MM"].max()) > 50


@pytest.mark.parametrize("case", ["offset", "unit"])
def test_check_origin_and_unit_diagnosis(golden, gsplit, tmp_path, case):
    xl, tl = gsplit["meshes"][0]
    moved = xl + np.array([10.0, 0.0, 0.0]) if case == "offset" else xl * 0.001
    a = write_split(tmp_path / "assem", [(moved, tl), gsplit["meshes"][1]])
    code, log, d = check_cli(golden, a["folder"], tmp_path / "c", ROWS)
    assert code == 15, log
    r = {x["body"]: x for x in d["rows"]}
    assert r["CUSH_R"]["status"] == "PASS" and r["CUSH_L"]["status"] == "FAIL" and r["CUSH_L"]["code"] == "ASM_BOUNDARY_MISMATCH"
    s = r["CUSH_L"]["suggest"]
    if case == "offset":
        assert s["code"] == "ASM_OFFSET_SUSPECT" and s["translate_mm"] == pytest.approx([10.0, 0.0, 0.0], abs=1e-3) and s["match_ratio_after"] >= 0.98
        assert r["CUSH_L"]["bbox_delta_mm"][0] == pytest.approx(10.0, abs=1e-3)
    else:
        assert s == {"code": "ASM_UNIT_SUSPECT", "factor": 0.001}


def test_check_shared_nodes_and_duplicates(golden, gsplit, tmp_path):
    a = write_split(tmp_path / "assem", gsplit["meshes"], shared=True)
    code, log, d = check_cli(golden, a["folder"], tmp_path / "c", ROWS)
    assert code == 15, log
    r = {x["body"]: x for x in d["rows"]}
    assert r["CUSH_L"]["code"] == "ASM_SHARED_NODES" and r["CUSH_L"]["match_ratio"] == 1.0
    assert r["CUSH_L"]["shared"] == {"nodes": 1, "parts": [{"pid": 2002, "title": "PRODUCT_SPRING", "nodes": 1}]} and r["CUSH_R"]["status"] == "PASS"
    assert d["code"] == "ASM_SHARED_NODES" and d["file_checks"]["shared_nodes"] == 1
    # rule 7: a node id defined twice in the tree fails the whole check (input), rows still evaluated
    f = tmp_path / "assem"
    (f / SUB_INC).write_text((f / SUB_INC).read_text().replace("/NODE\n", f"/NODE\n{2:10d}{0.0:20.10f}{0.0:20.10f}{0.0:20.10f}\n", 1))
    code, log, d = check_cli(golden, f, tmp_path / "c2", ROWS)
    assert code == 3 and d["status"] == "FAIL" and d["code"] == "GEOM_INPUT_INVALID"
    assert d["file_checks"]["duplicate_node_defs"] == 1 and d["file_checks"]["duplicate_nodes"] == [{"node": 2, "files": [MESH_INC, SUB_INC]}]


def test_check_one_to_many_and_unsupported(golden, gsplit, tmp_path):
    f = tmp_path / "assem"
    write_split(f, gsplit["meshes"], extra_parts=f"/PART/3000003\nEPS_LEFT_B\n{1:10d}{1:10d}")
    sub = (f / SUB_INC).read_text()
    (f / SUB_INC).write_text(sub.replace(f"/TETRA4/{PID[0]}", "/TETRA4/3000003", 1))  # second half of cushion L = PART 3000003
    code, log, d = check_cli(golden, f, tmp_path / "c1", [{"body": "CUSH_L", "pids": [PID[0], 3000003]}, ROWS[1]])
    assert code == 0, log
    assert d["rows"][0]["status"] == "PASS" and d["rows"][0]["pids"] == [PID[0], 3000003]
    code, log, d = check_cli(golden, f, tmp_path / "c2", [{"body": "CUSH_L", "pids": [PID[0]]}, ROWS[1]])  # half body: cut faces
    assert code == 15 and d["rows"][0]["code"] == "ASM_BOUNDARY_MISMATCH"
    code, log, d = check_cli(golden, f, tmp_path / "c3", [{"body": "CUSH_L", "pids": [PID[0], 3000003]}, {"body": "CUSH_R", "pids": [2001]}])
    assert code == 15 and d["rows"][1]["code"] == "GEOM_UNSUPPORTED_ELEMENT" and d["code"] == "GEOM_UNSUPPORTED_ELEMENT"
    code, log, d = check_cli(golden, f, tmp_path / "c4", [{"body": "CUSH_L", "pids": [PID[0]]}, {"body": "CUSH_R", "pids": [PID[0]]}])
    assert code == 3 and "ASM_MATCH_INVALID" in log and d["code"] == "ASM_MATCH_INVALID"
    code, log, d = check_cli(golden, f, tmp_path / "c5", [{"body": "NOPE", "pids": [PID[1]]}])
    assert code == 3 and "ASM_MATCH_INVALID" in log


def _L_vs_M_run(golden, tmp_path, values):
    """Method L (baseline include + RENUM) and method M (assembly match, pid = RENUM range) on the golden."""
    assem, base = golden["assem"], golden["baseline"]
    m = write_match(tmp_path / "asm_match.json", assem, [{"body": "CUSH_L", "pids": [1]}, {"body": "CUSH_R", "pids": [2]}])
    vals = write_json(tmp_path / "values.json", {"schema_version": 1, "values": values})
    cache = tmp_path / "cache"
    code, log = run_cli("tag", "--cad", golden["step"], "--features", golden["features_path"], "--asm-match", m, "--assem-dir", assem, "--out-dir", tmp_path / "tagM", "--cache-dir", cache)
    assert code == 0, log
    for mode in ("L", "M"):
        tag = golden["tag_dir"] if mode == "L" else tmp_path / "tagM"
        src = ["--baseline-inc", base, "--renum-csv", golden["renum"], "--out-inc", tmp_path / "L_out" / Path(base).name] if mode == "L" else ["--asm-match", m, "--out-patch", tmp_path / "M_out" / "node_patch.npz", "--cache-dir", cache]
        code, log = run_cli("run", "--cad", golden["step"], "--features", golden["features_path"], "--values", vals, "--tag-dir", tag, "--assem-dir", assem,
                            "--update-dir", tmp_path / f"u{mode}", "--morph-dir", tmp_path / f"m{mode}", "--check-dir", tmp_path / f"c{mode}", *src)
        assert code == 0, log
    return m, cache


def test_equivalence_with_renum_method(golden, tmp_path):
    """V-AM-6: same mesh -> same tag nodes, same check numbers, byte-identical solver input and cushion rad."""
    m, cache = _L_vs_M_run(golden, tmp_path, {"CUSH_L_THK_3": 22.0})
    zl, zm = np.load(Path(golden["tag_dir"]) / "tag_nodes.npz"), np.load(tmp_path / "tagM" / "tag_nodes.npz")
    assert all(np.array_equal(zl[k], zm[k]) for k in zl.files)
    tm = load(tmp_path / "tagM" / "tag.json")
    assert tm["baseline_inc"] is None and tm["asm_match"]["sha256"] and [p["pids"] for p in tm["parts"]] == [[1], [2]] and all(p["renum_row"] is None for p in tm["parts"])
    assert tm["contacts"] == golden["tag"]["contacts"]
    cl, cm = load(tmp_path / "cL" / "check.json"), load(tmp_path / "cM" / "check.json")
    assert cl["checks"] == cm["checks"] and cm["status"] == "PASS" and cm["out_patch"] == "node_patch.npz" and cm["out_inc"] is None
    rm = load(tmp_path / "cM" / "run.json")
    assert rm["out_patch"] == "node_patch.npz" and rm["out_inc"] is None
    assert (tmp_path / "mM" / "node_xyz.npz").is_file() and not (tmp_path / "mM" / "morphed.inc").exists()
    la = tmp_path / "L_assem"
    shutil.copytree(golden["assem"], la)
    shutil.copyfile(tmp_path / "L_out" / Path(golden["baseline"]).name, la / Path(golden["baseline"]).name)
    code, log = run_cli("asm", "write", "--assem-dir", golden["assem"], "--asm-match", m, "--patch", tmp_path / "M_out" / "node_patch.npz", "--out-dir", tmp_path / "M_assem", "--cache-dir", cache)
    assert code == 0, log
    for rel in ("MODEL_0000.rad", Path(golden["baseline"]).name, "product.inc"):
        assert (tmp_path / "M_assem" / rel).read_bytes() == (la / rel).read_bytes(), rel
    assert load(tmp_path / "M_assem" / "asm_write.json")["files"][1]["changed_lines"] > 0
    code, log = run_cli("cushion", "write", "--inc", tmp_path / "L_out" / Path(golden["baseline"]).name, "--renum-csv", golden["renum"], "--assem-dir", golden["assem"],
                        "--out-dir", tmp_path / "cuL", "--out-rad", tmp_path / "cuL" / "EPS_mesh_0000.rad")
    assert code == 0, log
    code, log = run_cli("cushion", "write", "--asm-match", m, "--patch", tmp_path / "M_out" / "node_patch.npz", "--assem-dir", golden["assem"],
                        "--out-dir", tmp_path / "cuM", "--out-rad", tmp_path / "cuM" / "EPS_mesh_0000.rad", "--cache-dir", cache)
    assert code == 0, log
    assert (tmp_path / "cuL" / "EPS_mesh_0000.rad").read_bytes() == (tmp_path / "cuM" / "EPS_mesh_0000.rad").read_bytes()


def test_method_m_split_assembly_end_to_end(golden, gsplit, tmp_path):
    """Tag / run / asm write on the split layout: only cushion node lines change, in both files; product lines
    of the same file stay byte identical; interference collects the product PART of the same file."""
    f = gsplit["folder"]
    m = write_match(tmp_path / "asm_match.json", f, ROWS)
    code, log = run_cli("extract", "--cad", golden["step"], "--out-dir", tmp_path / "ex", "--asm-match", m, "--no-png")
    assert code == 0, log
    feats = tmp_path / "ex" / "parameter_features.json"
    code, log = run_cli("tag", "--cad", golden["step"], "--features", feats, "--asm-match", m, "--assem-dir", f, "--out-dir", tmp_path / "tag", "--body-map", tmp_path / "ignored.json")
    assert code == 0, log
    t = load(tmp_path / "tag" / "tag.json")
    assert t["status"] == "OK" and [p["part"] for p in t["parts"]] == ["CUSH_L", "CUSH_R"] and any(w["code"] == "BODY_MAP_IGNORED" for w in t["warnings"])
    assert any(c["with"] == "PRODUCT" for c in t["contacts"]) is False  # plate is 5 mm below: no contact
    vals = write_json(tmp_path / "values.json", {"schema_version": 1, "values": {"CUSH_L_THK_3": 21.0}})
    code, log = run_cli("run", "--cad", golden["step"], "--features", feats, "--values", vals, "--tag-dir", tmp_path / "tag", "--assem-dir", f, "--asm-match", m,
                        "--update-dir", tmp_path / "u", "--morph-dir", tmp_path / "m", "--check-dir", tmp_path / "c", "--out-patch", tmp_path / "out" / "node_patch.npz")
    assert code == 0, log
    c = load(tmp_path / "c" / "check.json")
    assert c["status"] == "PASS" and c["checks"]["interference"]["status"] == "PASS" and c["checks"]["tie"]["status"] == "SKIPPED"
    z = np.load(tmp_path / "out" / "node_patch.npz")
    nl, nr = len(gsplit["meshes"][0][0]), len(gsplit["meshes"][1][0])
    assert len(z["node_id"]) == nl + nr
    code, log = run_cli("asm", "write", "--assem-dir", f, "--asm-match", m, "--patch", tmp_path / "out" / "node_patch.npz", "--out-dir", tmp_path / "A")
    assert code == 0, log
    idx = build(f)
    moved = {int(n) for n, x in zip(z["node_id"], z["xyz"]) if not np.array_equal(x, idx.node_xyz[idx.lookup([n])[0]])}
    assert any(n < NODE_START[1] for n in moved)
    n1 = _only_coordinates_changed((f / MESH_INC).read_bytes(), (tmp_path / "A" / MESH_INC).read_bytes(), moved)
    n2 = _only_coordinates_changed((f / SUB_INC).read_bytes(), (tmp_path / "A" / SUB_INC).read_bytes(), moved)
    assert n1 > 0 and n2 > 0
    for rel in (STARTER, PARTS_INC):
        assert (tmp_path / "A" / rel).read_bytes() == (f / rel).read_bytes()
    # product collection of method M = the whole tree minus the matched PART elements: the plate PART of the
    # same file is product, the cushion skins are not
    src = AsmSource(m, f)
    tris = src.product_surface(None)
    assert tris.shape == (48, 3, 3) and np.all(tris[:, :, 2] == -5.0)
    assert src.product_surface(np.array([500.0, 500.0, 500.0, 510.0, 510.0, 510.0])).shape == (0, 3, 3)


def test_method_m_excluded_body_sweep_and_preview(golden, gsplit, tmp_path):
    """A body left unmatched ("match nothing") is skipped by tag / check; sweep and view preview take method M."""
    f = gsplit["folder"]
    m = write_match(tmp_path / "asm_match.json", f, [ROWS[0]], excluded=["CUSH_R"])
    code, log = run_cli("tag", "--cad", golden["step"], "--features", golden["features_path"], "--asm-match", m, "--assem-dir", f, "--out-dir", tmp_path / "tag")
    assert code == 0, log
    t = load(tmp_path / "tag" / "tag.json")
    assert [p["part"] for p in t["parts"]] == ["CUSH_L"] and t["excluded_bodies"] == ["CUSH_R"]
    vals = write_json(tmp_path / "v0.json", {"schema_version": 1, "values": {}})
    code, log = run_cli("update", "--cad", golden["step"], "--features", golden["features_path"], "--values", vals, "--tag-dir", tmp_path / "tag", "--out-dir", tmp_path / "u0")
    assert code == 0, log
    code, log = run_cli("morph", "--asm-match", m, "--assem-dir", f, "--tag-dir", tmp_path / "tag", "--features", golden["features_path"], "--update-dir", tmp_path / "u0", "--out-dir", tmp_path / "m0")
    assert code == 0, log
    z = np.load(tmp_path / "m0" / "node_xyz.npz")
    assert len(z["node_id"]) == len(gsplit["meshes"][0][0])
    code, log = run_cli("check", "--morph-dir", tmp_path / "m0", "--update-dir", tmp_path / "u0", "--tag-dir", tmp_path / "tag", "--features", golden["features_path"], "--values", vals,
                        "--assem-dir", f, "--asm-match", m, "--out-dir", tmp_path / "c0", "--out-patch", tmp_path / "p0" / "node_patch.npz")
    assert code == 0, log
    items = load(tmp_path / "c0" / "check.json")["checks"]["param"]["items"]
    assert items and all(it["name"].startswith("CUSH_L") for it in items)
    p0 = np.load(tmp_path / "p0" / "node_patch.npz")
    src = build(f)
    rows = src.lookup(p0["node_id"])
    assert np.array_equal(p0["xyz"], src.node_xyz[rows])  # nominal: patch = tree coordinates
    code, log = run_cli("morph", "--sweep", "--asm-match", m, "--assem-dir", f, "--tag-dir", tmp_path / "tag", "--features", golden["features_path"], "--update-dir", tmp_path / "u0",
                        "--out-dir", tmp_path / "sw", "--params", "CUSH_L_THK_3", "--steps", "5", "--keep-steps")
    assert code == 0, log
    env = load(tmp_path / "sw" / "envelope.json")
    assert env["inputs"]["baseline_sha256"] == sha256_file(m) and all(r["status"] == "OK" for r in env["rows"])
    assert list((tmp_path / "sw" / "sweep").rglob("node_xyz.npz")) and not list((tmp_path / "sw" / "sweep").rglob("morphed.inc"))
    v1 = write_json(tmp_path / "v1.json", {"schema_version": 1, "values": {"CUSH_L_THK_3": 21.0}})
    code, log = run_cli("view", "preview", "--cad", golden["step"], "--features", golden["features_path"], "--values", v1, "--tag-dir", tmp_path / "tag", "--out-dir", tmp_path / "pv",
                        "--fe", "check", "--asm-match", m, "--assem-dir", f)
    assert code == 0, log
    pv = load(tmp_path / "pv" / "preview_manifest.json")
    assert pv["fe"]["status"] == "PASS" and pv["fe"]["glb"] is not None


def test_parts_from_cad_and_selftest_method_m(golden, gsplit, tmp_path):
    """``asm parts --cad`` reads the bodies from the STEP; ``selftest`` runs the stages with method M."""
    code, log = run_cli("asm", "parts", "--assem-dir", gsplit["folder"], "--cad", golden["step"], "--out-dir", tmp_path / "p")
    assert code == 0, log
    d = load(tmp_path / "p" / "asm_parts.json")
    assert [b["body"] for b in d["bodies"]] == ["CUSH_L", "CUSH_R"] and all(b["volume"] > 0 for b in d["bodies"])
    assert [(x["body"], x["pids"]) for x in d["recommend"]] == [("CUSH_L", [PID[0]]), ("CUSH_R", [PID[1]])]
    m = write_match(tmp_path / "asm_match.json", gsplit["folder"], ROWS)
    code, log = run_cli("selftest", "--cad", golden["step"], "--asm-match", m, "--assem-dir", gsplit["folder"], "--out-dir", tmp_path / "st", "--no-envelope")
    assert code == 0, log
    r = load(tmp_path / "st" / "selftest_report.json")
    assert {k: v["status"] for k, v in r["stages"].items()} == {"extract": "OK", "tag": "OK", "update": "OK", "morph": "OK", "check": "PASS"}
    assert r["roundtrip"] == {"writer_byte_identical": True, "nominal_morph_byte_identical": True}
    assert r["inputs"]["baseline_sha256"] == sha256_file(m) and r["inputs"]["renum_sha256"] is None
    assert (tmp_path / "st" / "work" / "check_nominal_out" / "node_patch.npz").is_file()
