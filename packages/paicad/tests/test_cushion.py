"""``paicad cushion write`` (input-kind.md section 5, GE-C19, V-IK-5): synthetic assembly sets."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import paicad
import pytest
from conftest import run_cli
from paicad.mesh.radioss import parse_text, rewrite_nodes

OUT_RAD = "EPS_mesh_0000.rad"
INC = "104_cushion.inc"
CUBE = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)]
CUBE_TETS = [(0, 1, 3, 4), (1, 2, 3, 6), (1, 4, 5, 6), (3, 4, 6, 7), (1, 3, 4, 6)]
COMPS = [("CushionA", 1000001, 1000001, 1, 0.0), ("CushionB", 1100001, 1100001, 2, 10.0)]

STARTER = (
    "#RADIOSS STARTER\n"
    "/BEGIN\n"
    "#runname\n"
    "MODEL\n"
    "      2024         0\n"
    "                  Mg                  mm                   s\n"
    "                  Mg                  mm                   s\n"
    "#--- parts\n"
    "/PART/1\n"
    "CushionA\n"
    "#  prop_ID    mat_ID\n"
    "         1         1\n"
    "/PART/2\n"
    "CushionB\n"
    "         1         1\n"
    "/PART/100\n"
    "PRODUCT\n"
    "       100         2\n"
    "#include product.inc\n"
    f"#include {INC}\n"
    "#include material.inc\n"
    "/END\n"
)
MATERIAL = (
    "/MAT/LAW70/1\n"
    "EPS foam\n"
    "#              RHO_I\n"
    "             2.0E-11\n"
    "/PROP/TYPE14/1\n"
    "Solid cushion\n"
    "#   Isolid    Ismstr               Icpre  Itetra4 Itetra10     Imass   Iframe\n"
    "        24         4                   0        0        0\n"
    "/MAT/LAW1/2\n"
    "Steel\n"
    "              7.8E-9\n"
)
DECOY = "/MAT/LAW70/1\nDECOY (later file, must not be used)\n             9.9E-11\n/PART/1\nDECOY\n         9         9\n"
EPS_DECOY = "#RADIOSS STARTER\n/BEGIN\nEPS\n      2024         0\n/PART/1\nEPS decoy\n         7         7\n/END\n"


def cushion_inc(eol: str = "\n") -> str:
    lines = ["#RADIOSS include: synthetic cushion + product leftovers", "/NODE", "#  node_ID                   X                   Y                   Z"]
    for _, nstart, _, _, dx in COMPS:
        for i, p in enumerate(CUBE):
            lines.append(f"{nstart + i:10d}{p[0] * 5.0 + dx:20.10f}{p[1] * 5.0:20.10f}{p[2] * 5.0:20.10f}")
    lines += ["/NODE", f"{1:10d}{0.0:20.10f}{0.0:20.10f}{-1.0:20.10f}", f"{2:10d}{9.0:20.10f}{0.0:20.10f}{-1.0:20.10f}", f"{3:10d}{9.0:20.10f}{9.0:20.10f}{-1.0:20.10f}", f"{4:10d}{0.0:20.10f}{9.0:20.10f}{-1.0:20.10f}"]
    lines += ["/SHELL/100", f"{1:10d}{1:10d}{2:10d}{3:10d}{4:10d}"]
    for _, nstart, estart, pid, _ in COMPS:
        lines += [f"/TETRA4/{pid}", "#  elem_ID   node_ID1  node_ID2  node_ID3  node_ID4"]
        for j, t in enumerate(CUBE_TETS):
            lines.append(f"{estart + j:10d}" + "".join(f"{nstart + k:10d}" for k in t))
    lines += ["/GRNOD/NODE/7", "product contact nodes", f"{1:10d}{1000001:10d}"]
    return eol.join(lines) + eol


def make_set(root: Path, eol: str = "\n", morph: bool = True) -> dict:
    assem = root / "assem"
    assem.mkdir(parents=True)
    (assem / "MODEL_0000.rad").write_bytes(STARTER.encode("ascii"))
    (assem / "material.inc").write_bytes(MATERIAL.encode("ascii"))
    (assem / "zz_decoy.inc").write_bytes(DECOY.encode("ascii"))
    (assem / "EPS_mesh_0000.rad").write_bytes(EPS_DECOY.encode("ascii"))
    (assem / "product.inc").write_bytes(b"/NODE\n         1                 0.0                 0.0                -1.0\n")
    base = cushion_inc(eol).encode("ascii")
    (assem / INC).write_bytes(base)
    renum = root / "RENUM_INIT.csv"
    renum.write_text("part,node_start,elem_start\n" + "".join(f"{n},{a},{b}\n" for n, a, b, _, _ in COMPS), encoding="utf-8")
    inc = root / "morph" / INC
    inc.parent.mkdir()
    data = rewrite_nodes(base, {1000007: (5.25, 5.5, 5.125), 1100002: (15.5, -0.25, 0.0)}) if morph else base
    inc.write_bytes(data)
    return {"assem": assem, "renum": renum, "inc": inc, "base": base, "root": root}


def run_write(s: dict, out: Path, inc: Path | None = None, *extra: str) -> tuple[int, str]:
    return run_cli(
        "cushion", "write", "--inc", inc or s["inc"], "--renum-csv", s["renum"], "--assem-dir", s["assem"],
        "--out-dir", out / "cushion", "--out-rad", out / OUT_RAD, *extra,
    )


def keywords(data: bytes) -> list[str]:
    return [ln.decode().strip() for ln in data.splitlines() if ln.startswith(b"/")]


def card(data: bytes, keyword: str) -> bytes:
    lines = data.splitlines(keepends=True)
    i = next(k for k, ln in enumerate(lines) if ln.rstrip(b"\r\n") == keyword.encode())
    j = next((k for k in range(i + 1, len(lines)) if lines[k].startswith(b"/") or lines[k].startswith(b"#include")), len(lines))
    return b"".join(lines[i:j])


def section_lines(data: bytes, kind: str) -> list[bytes]:
    """Data lines (no comments/blank) of every ``/<kind>`` block, keyword lines excluded."""
    out, on = [], False
    for ln in data.splitlines(keepends=True):
        if ln.startswith(b"/"):
            on = ln.decode().strip().split("/")[1] == kind
            continue
        if on and ln.strip() and not ln.startswith((b"#", b"$")):
            out.append(ln)
    return out


def cushion_mesh(data: bytes):
    m = parse_text(data.decode("latin-1"))
    tets = [b for b in m.blocks if b.keyword == "TETRA4"]
    used = np.unique(np.concatenate([b.conn for b in tets]))
    keep = np.isin(m.node_ids, used)
    return m.node_ids[keep], m.xyz[keep], tets


# ------------------------------------------------------------------ structure
def test_structure_ids_coordinates(tmp_path):
    s = make_set(tmp_path / "s")
    code, log = run_write(s, tmp_path / "o")
    assert code == 0, log
    assert log.strip().splitlines()[-1] == "PAICAD RESULT OK - cushion.json"
    rad = (tmp_path / "o" / OUT_RAD).read_bytes()
    lines = rad.splitlines()
    assert lines[0] == b"#RADIOSS STARTER" and lines[-1] == b"/END"
    assert keywords(rad) == ["/BEGIN", "/PART/1", "/PART/2", "/PROP/TYPE14/1", "/MAT/LAW70/1", "/NODE", "/TETRA4/1", "/TETRA4/2", "/END"]
    assert b"#include" not in rad and b"DECOY" not in rad and b"EPS decoy" not in rad and b"/GRNOD" not in rad and b"/SHELL" not in rad
    # /BEGIN: starter bytes, run name line = --out-rad stem
    begin = card(STARTER.encode(), "/BEGIN").replace(b"\nMODEL\n", b"\nEPS_mesh_0000\n")
    assert card(rad, "/BEGIN") == begin
    for kw in ("/PART/1", "/PART/2"):
        assert card(rad, kw) == card(STARTER.encode(), kw)
    for kw in ("/PROP/TYPE14/1", "/MAT/LAW70/1"):
        assert card(rad, kw) == card(MATERIAL.encode(), kw)
    # nodes / elements: ids, connectivity and morphed coordinates of the include, no product node
    inc = s["inc"].read_bytes()
    ids, xyz, tets = cushion_mesh(inc)
    oids, oxyz, otets = cushion_mesh(rad)
    out_mesh = parse_text(rad.decode())
    assert out_mesh.node_ids.tolist() == ids.tolist() == oids.tolist()
    assert np.array_equal(out_mesh.xyz, xyz)
    assert not set(out_mesh.node_ids.tolist()) & {1, 2, 3, 4}
    assert [(b.part_id, b.ids.tolist(), b.conn.tolist()) for b in out_mesh.blocks] == [(b.part_id, b.ids.tolist(), b.conn.tolist()) for b in tets]
    assert section_lines(rad, "NODE") == [ln for ln in section_lines(inc, "NODE") if int(ln[:10]) in set(ids.tolist())]
    assert card(rad, "/TETRA4/1") == card(inc, "/TETRA4/1") and card(rad, "/TETRA4/2") == card(inc, "/TETRA4/2")
    assert out_mesh.xyz[out_mesh.node_ids.tolist().index(1000007)].tolist() == [5.25, 5.5, 5.125]
    doc = json.loads((tmp_path / "o" / "cushion" / "cushion.json").read_text(encoding="utf-8"))
    assert {k: doc[k] for k in ("schema_version", "engine", "engine_version", "status", "code", "category", "out_rad")} == {
        "schema_version": 1, "engine": "native", "engine_version": paicad.__version__, "status": "OK", "code": None, "category": None, "out_rad": OUT_RAD,
    }
    assert doc["node_count"] == 16 and doc["elem_count"] == 10 and doc["bytes"] == len(rad)
    assert doc["parts"] == [
        {"part": 1, "components": ["CushionA"], "nodes": 8, "elems": 5, "part_def": True},
        {"part": 2, "components": ["CushionB"], "nodes": 8, "elems": 5, "part_def": True},
    ]
    assert doc["begin_from"] == "MODEL_0000.rad" and doc["def_sources"] == ["MODEL_0000.rad", "material.inc"]
    assert doc["warnings"] == [] and isinstance(doc["elapsed_s"], float)
    assert paicad.__version__ == "0.12.0"


def test_unchanged_include_round_trip(tmp_path):
    s = make_set(tmp_path / "s", morph=False)
    code, log = run_write(s, tmp_path / "o")
    assert code == 0, log
    rad = (tmp_path / "o" / OUT_RAD).read_bytes()
    base = s["base"]
    # every node/element line of the cushion = the include bytes; parsed cushion mesh identical
    i0 = rad.index(b"/NODE\n")
    expected = b"/NODE\n" + b"".join(section_lines(base, "NODE")[:16]) + card(base, "/TETRA4/1") + card(base, "/TETRA4/2") + b"/END\n"
    assert rad[i0:] == expected
    a, b = cushion_mesh(base), cushion_mesh(rad)
    assert a[0].tolist() == b[0].tolist() and np.array_equal(a[1], b[1])
    # the morphed variant differs only in the moved node lines
    s2 = make_set(tmp_path / "s2")
    assert run_write(s2, tmp_path / "o2")[0] == 0
    rad2 = (tmp_path / "o2" / OUT_RAD).read_bytes()
    diff = [(x, y) for x, y in zip(rad.splitlines(), rad2.splitlines()) if x != y]
    assert len(rad.splitlines()) == len(rad2.splitlines()) and sorted(int(x[:10]) for x, _ in diff) == [1000007, 1100002]


def test_deterministic(tmp_path):
    s = make_set(tmp_path / "s")
    assert run_write(s, tmp_path / "o1")[0] == 0
    assert run_write(s, tmp_path / "o2")[0] == 0
    assert (tmp_path / "o1" / OUT_RAD).read_bytes() == (tmp_path / "o2" / OUT_RAD).read_bytes()
    d1, d2 = (json.loads((tmp_path / o / "cushion" / "cushion.json").read_text(encoding="utf-8")) for o in ("o1", "o2"))
    d1.pop("elapsed_s"), d2.pop("elapsed_s")
    assert d1 == d2


def test_crlf_include_kept(tmp_path):
    s = make_set(tmp_path / "s", eol="\r\n")
    assert run_write(s, tmp_path / "o")[0] == 0
    rad = (tmp_path / "o" / OUT_RAD).read_bytes()
    inc = s["inc"].read_bytes()
    assert card(rad, "/TETRA4/2") == card(inc, "/TETRA4/2") and b"\r\n" in rad
    assert parse_text(rad.decode()).node_ids.size == 16


def test_missing_definitions_warn(tmp_path):
    s = make_set(tmp_path / "s")
    (s["assem"] / "material.inc").unlink()
    code, log = run_write(s, tmp_path / "o")
    assert code == 0, log
    doc = json.loads((tmp_path / "o" / "cushion" / "cushion.json").read_text(encoding="utf-8"))
    # zz_decoy.inc has MAT/1 (first definition after material.inc is gone), PROP/1 is nowhere
    assert [w["code"] for w in doc["warnings"]] == ["CUSHION_PART_DEF_MISSING"]
    assert doc["warnings"][0]["names"] == ["PROP/1"]
    rad = (tmp_path / "o" / OUT_RAD).read_bytes()
    assert keywords(rad)[:5] == ["/BEGIN", "/PART/1", "/PART/2", "/MAT/LAW70/1", "/NODE"] and b"DECOY" in rad
    assert doc["def_sources"] == ["MODEL_0000.rad", "zz_decoy.inc"]


def test_part_defined_in_include_wins(tmp_path):
    s = make_set(tmp_path / "s")
    inc = s["inc"].read_bytes() + b"/PART/2\nCushionB from include\n         1         2\n"
    s["inc"].write_bytes(inc)
    assert run_write(s, tmp_path / "o")[0] == 0
    rad = (tmp_path / "o" / OUT_RAD).read_bytes()
    assert b"CushionB from include" in rad and keywords(rad)[:6] == ["/BEGIN", "/PART/1", "/PART/2", "/PROP/TYPE14/1", "/MAT/LAW70/1", "/MAT/LAW1/2"]


# ------------------------------------------------------------------ failures (section 5.4 codes)
def sha_tree(d: Path) -> dict:
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(d.iterdir()) if p.is_file()}


def test_output_exists_exit_3(tmp_path):
    s = make_set(tmp_path / "s")
    before = sha_tree(s["assem"])
    assert run_write(s, tmp_path / "o")[0] == 0
    code, log = run_write(s, tmp_path / "o")
    assert code == 3 and "GEOM_OUTPUT_EXISTS" in log
    (tmp_path / "o" / "cushion" / "cushion.json").unlink()
    code, log = run_write(s, tmp_path / "o")  # the rad alone still blocks
    assert code == 3 and "GEOM_OUTPUT_EXISTS" in log and not (tmp_path / "o" / "cushion" / "cushion.json").exists()
    assert sha_tree(s["assem"]) == before


def fail_doc(out: Path) -> dict:
    return json.loads((out / "cushion" / "cushion.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "case, exit_code, code",
    [
        ("no_starter", 3, "GEOM_INPUT_INVALID"),
        ("two_starters", 3, "GEOM_INPUT_INVALID"),
        ("renum_missing", 3, "RENUM_CSV_MISSING"),
        ("inc_missing", 3, "GEOM_INPUT_INVALID"),
        ("node_missing", 3, "GEOM_INPUT_INVALID"),
        ("non_tetra", 12, "GEOM_UNSUPPORTED_ELEMENT"),
        ("no_tetra", 3, "GEOM_INPUT_INVALID"),
        ("bad_solver", 3, "GEOM_INPUT_INVALID"),
        ("bad_options", 3, "GEOM_INPUT_INVALID"),
    ],
)
def test_failures(tmp_path, case, exit_code, code):
    s = make_set(tmp_path / "s")
    extra: list[str] = []
    inc = s["inc"]
    if case == "no_starter":
        (s["assem"] / "MODEL_0000.rad").write_bytes(STARTER.replace("/BEGIN\n", "").encode())
    elif case == "two_starters":
        (s["assem"] / "OTHER_0000.rad").write_bytes(STARTER.encode())
    elif case == "renum_missing":
        s["renum"].unlink()
    elif case == "inc_missing":
        inc = tmp_path / "nope.inc"
    elif case == "node_missing":
        inc.write_bytes(inc.read_bytes().replace(b"   1100008", b"   1100099", 1))
    elif case == "non_tetra":
        inc.write_bytes(inc.read_bytes() + b"/BRICK/1\n   1000050   1000001   1000002   1000003   1000004   1000005   1000006   1000007   1000008\n")
    elif case == "no_tetra":
        s["renum"].write_text("part,node_start,elem_start\nCushionA,1000001,1000001\nCushionX,1050001,1050001\nCushionB,1100001,1100001\n", encoding="utf-8")
    elif case == "bad_solver":
        extra = ["--solver", "lsdyna"]
    elif case == "bad_options":
        (tmp_path / "opt.json").write_text('{"nope": 1}', encoding="utf-8")
        extra = ["--options", str(tmp_path / "opt.json")]
    code_, log = run_write(s, tmp_path / "o", inc, *extra)
    assert code_ == exit_code, log
    assert log.strip().splitlines()[-1].startswith(f"PAICAD RESULT FAIL {code} ")
    doc = fail_doc(tmp_path / "o")
    assert doc["status"] == "FAIL" and doc["code"] == code and doc["out_rad"] is None and doc["engine_version"] == paicad.__version__
    assert not (tmp_path / "o" / OUT_RAD).exists()


def test_missing_argument_exit_2(tmp_path):
    r = subprocess.run([sys.executable, "-m", "paicad", "cushion", "write", "--inc", "x"], capture_output=True, text=True, timeout=60)
    assert r.returncode == 2


def test_runs_without_ocp(tmp_path):
    """Kernel isolation: the command needs no OCP (import blocked) and never imports paicad.kernel."""
    s = make_set(tmp_path / "s")
    prog = (
        "import sys, importlib.abc\n"
        "class Block(importlib.abc.MetaPathFinder):\n"
        "    def find_spec(self, name, path=None, target=None):\n"
        "        if name == 'OCP' or name.startswith('OCP.'):\n"
        "            raise ImportError('OCP blocked')\n"
        "sys.meta_path.insert(0, Block())\n"
        "import paicad.cushion\n"
        "assert 'paicad.kernel' not in sys.modules, 'cushion imports the kernel'\n"
        "from paicad.cli import main\n"
        "sys.exit(main(sys.argv[1:]))\n"
    )
    argv = ["cushion", "write", "--inc", s["inc"], "--renum-csv", s["renum"], "--assem-dir", s["assem"], "--out-dir", tmp_path / "o" / "c", "--out-rad", tmp_path / "o" / OUT_RAD]
    r = subprocess.run([sys.executable, "-c", prog, *map(str, argv)], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (tmp_path / "o" / OUT_RAD).is_file()


def test_golden_baseline(golden, tmp_path):
    """Virtual cushion golden set (gmsh baseline, starter with /PART but no PROP/MAT)."""
    out = tmp_path / "o"
    code, log = run_cli(
        "cushion", "write", "--inc", golden["baseline"], "--renum-csv", golden["renum"], "--assem-dir", golden["assem"],
        "--out-dir", out / "c", "--out-rad", out / OUT_RAD,
    )
    assert code == 0, log
    rad = (out / OUT_RAD).read_bytes()
    base = Path(golden["baseline"]).read_bytes()
    m0, m1 = parse_text(base.decode()), parse_text(rad.decode())
    assert m1.node_ids.tolist() == m0.node_ids.tolist() and np.array_equal(m1.xyz, m0.xyz)
    assert [(b.part_id, b.ids.tolist()) for b in m1.blocks] == [(b.part_id, b.ids.tolist()) for b in m0.blocks]
    assert section_lines(rad, "NODE") == section_lines(base, "NODE")
    doc = json.loads((out / "c" / "cushion.json").read_text(encoding="utf-8"))
    assert doc["warnings"][0]["names"] == ["PROP/1", "PROP/2", "MAT/1"] and all(p["part_def"] for p in doc["parts"])
    assert keywords(rad)[0] == "/BEGIN" and keywords(rad)[-1] == "/END" and b"#include" not in rad
