"""Package self-checks: kernel isolation (V-GE-19), independence (V-GE-13/14), version rules (V-GE-11)."""

from __future__ import annotations

import ast
import re
import shutil
import subprocess
import sys
import tomllib
from importlib.metadata import version as dist_version
from pathlib import Path

import paicad
import pytest

PKG = Path(__file__).resolve().parents[1]
SRC = PKG / "src" / "paicad"
TESTS = PKG / "tests"
PLATFORM_MODULES = ("physicsai_core", "physicsai_api", "physicsai_worker", "backend", "worker", "simdash_adapters")
PLATFORM_LITERALS = ("104_replace_node_elem", "RENUM_INIT", "radioss_assem", "platform.yaml", "predict.mesh_include_name")


def imported_modules(source: str) -> list[str]:
    mods = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            mods += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            mods.append(node.module)
    return mods


def ocp_violations(src_root: Path) -> list[str]:
    bad = []
    for p in sorted(src_root.rglob("*.py")):
        rel = p.relative_to(src_root)
        if rel.parts[0] == "kernel":
            continue
        for m in imported_modules(p.read_text(encoding="utf-8")):
            if m == "OCP" or m.startswith("OCP."):
                bad.append(f"{rel}: {m}")
    return bad


def platform_violations(files: list[Path]) -> list[str]:
    bad = []
    for p in files:
        for m in imported_modules(p.read_text(encoding="utf-8")):
            if m.split(".")[0] in PLATFORM_MODULES:
                bad.append(f"{p.name}: {m}")
    return bad


def test_no_ocp_outside_kernel():
    assert ocp_violations(SRC) == []


def test_ocp_scanner_detects_injected_violation(tmp_path):
    (tmp_path / "kernel").mkdir()
    (tmp_path / "kernel" / "ok.py").write_text("from OCP.gp import gp_Pnt\n")
    (tmp_path / "morph.py").write_text("import numpy\nfrom OCP.TopoDS import TopoDS\n")
    assert ocp_violations(tmp_path) == ["morph.py: OCP.TopoDS"]


def test_no_platform_imports():
    files = sorted(SRC.rglob("*.py")) + sorted(TESTS.rglob("*.py"))
    assert platform_violations(files) == []


def test_platform_scanner_detects_injected_violation(tmp_path):
    p = tmp_path / "x.py"
    p.write_text("from physicsai_core.geometry import reports\n")
    assert platform_violations([p]) == ["x.py: physicsai_core.geometry"]


def test_no_platform_file_names_in_src():
    hits = []
    for p in sorted(SRC.rglob("*.py")):
        text = p.read_text(encoding="utf-8")
        hits += [f"{p.name}: {lit}" for lit in PLATFORM_LITERALS if lit in text]
    assert hits == []


def test_messages_are_english_only():
    hangul = re.compile(r"[ᄀ-ᇿ㄰-㆏가-힯]")
    assert [p.name for p in SRC.rglob("*.py") if hangul.search(p.read_text(encoding="utf-8"))] == []


def test_version_single_source_and_changelog():
    init = (SRC / "__init__.py").read_text(encoding="utf-8")
    m = re.search(r'^__version__ = "(\d+\.\d+\.\d+)"$', init, re.MULTILINE)
    assert m and m.group(1) == paicad.__version__
    assert not any(x in init for x in ("import OCP", "import numpy", "from OCP"))
    py = tomllib.loads((PKG / "pyproject.toml").read_text(encoding="utf-8"))
    assert "version" not in py["project"] and py["project"]["dynamic"] == ["version"]
    assert py["tool"]["setuptools"]["dynamic"]["version"] == {"attr": "paicad.__version__"}
    top = re.search(r"^## (\d+\.\d+\.\d+) — \d{4}-\d{2}-\d{2}$", (PKG / "CHANGELOG.md").read_text(encoding="utf-8"), re.MULTILINE)
    assert top and top.group(1) == paicad.__version__
    assert (PKG / "THIRD_PARTY_NOTICES.md").is_file()


def test_ocp_version_matches_pin():
    py = tomllib.loads((PKG / "pyproject.toml").read_text(encoding="utf-8"))
    pin = [d for d in py["project"]["dependencies"] if d.startswith("cadquery-ocp")][0].split("==")[1]
    assert dist_version("cadquery-ocp") == pin
    from paicad.kernel import kernel_versions

    assert kernel_versions()["ocp"] == pin


def test_runtime_does_not_import_test_tools():
    for p in sorted(SRC.rglob("*.py")):
        for m in imported_modules(p.read_text(encoding="utf-8")):
            assert m.split(".")[0] not in ("build123d", "gmsh", "pytest"), (p.name, m)


def test_no_cae_or_cad_files_committed():
    exts = {".step", ".stp", ".inc", ".rad", ".msh", ".brep", ".npz"}
    assert [str(p.relative_to(PKG)) for p in PKG.rglob("*") if p.suffix.lower() in exts] == []


def test_kernel_returns_neutral_types(golden):
    import numpy as np
    from paicad.kernel import load_cad

    _, bodies = load_cad(golden["step"])
    b = bodies[0]
    topo = b.topology()
    pts = topo.vertices[:3]
    results = [
        b.summary(),
        topo,
        b.project_to_edge(1, pts),
        b.project_to_face(1, pts),
        b.eval_face(1, np.array([[0.5, 0.5]])),
        b.sample_face(1, 4),
        b.points_inside(pts),
        b.eval_edge(1, np.array([0.0, 0.5, 1.0])),
        b.classify_face_uv(1, np.array([[0.5, 0.5]])),
        b.distance(pts),
    ]
    from paicad.kernel import FaceMove, move_faces

    plain = next(f for f in topo.faces if f.surface == "PLANE" and all(topo.face(g).surface == "PLANE" for e in f.edges for g in topo.edge(e).faces))
    moved = move_faces(b, {plain.id: FaceMove(translate=np.asarray(plain.normal) * 0.5)})
    assert moved.__class__.__module__ == "paicad.kernel.occ"  # the kernel's own BodyGeom, never an OCP object
    results += [moved.summary(), moved.topology()]

    def walk(o, depth=0):
        assert not type(o).__module__.startswith("OCP"), type(o)
        if depth > 6:
            return
        if isinstance(o, (list, tuple)):
            for x in o:
                walk(x, depth + 1)
        elif isinstance(o, dict):
            for x in o.values():
                walk(x, depth + 1)
        elif hasattr(o, "__dataclass_fields__"):
            for k in o.__dataclass_fields__:
                walk(getattr(o, k), depth + 1)

    walk(results)


def test_cli_entry_point_version():
    exe = shutil.which("paicad")
    cmd = [exe] if exe else [sys.executable, "-m", "paicad"]
    r = subprocess.run(cmd + ["--version"], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0
    assert r.stdout.strip() == f"paicad {paicad.__version__}"


@pytest.mark.parametrize("argv", [["extract"], ["tag", "--cad", "x"], ["bogus"], ["update", "--cad", "x"], ["morph", "--sweep"], ["check"]])
def test_cli_argument_errors_exit_2(argv):
    r = subprocess.run([sys.executable, "-m", "paicad", *argv], capture_output=True, text=True, timeout=60)
    assert r.returncode == 2
