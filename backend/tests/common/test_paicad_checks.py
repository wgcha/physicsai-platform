"""paicad 정적 검사 스크립트(scripts/check_paicad.py, geometry-engine.md §17.5·§18.6, V-GE-2·11·13·14·19) 시험.

실제 저장소는 통과해야 하고, 위반을 주입한 최소 트리에서는 실패해야 한다(검사가 헛돌지 않는다는 확인).
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from physicsai_test_support import REPO

_spec = importlib.util.spec_from_file_location("check_paicad", REPO / "scripts" / "check_paicad.py")
chk = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
sys.modules["check_paicad"] = chk
_spec.loader.exec_module(chk)  # type: ignore[union-attr]

CHANGELOG = "# paicad 변경 기록\n\n## 0.5.0 — 2026-10-19\n- 변경: x\n"
PAICAD_PYPROJECT = (
    '[project]\nname = "paicad"\ndynamic = ["version"]\n\n[tool.setuptools.dynamic]\nversion = {attr = "paicad.__version__"}\n'
)


def make_tree(root: Path, version: str = "0.5.0") -> Path:
    def w(rel: str, text: str) -> None:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    w("packages/paicad/src/paicad/__init__.py", f'"""doc"""\n\n__version__ = "{version}"\n')
    w("packages/paicad/src/paicad/kernel/__init__.py", "import OCP\n")
    w("packages/paicad/src/paicad/cli.py", "import numpy\n")
    w("packages/paicad/CHANGELOG.md", CHANGELOG.replace("0.5.0", version))
    w("packages/paicad/pyproject.toml", PAICAD_PYPROJECT)
    w("packages/paicad/THIRD_PARTY_NOTICES.md", "OCCT LGPL\n")
    w("packages/paicad/tests/test_x.py", "import paicad\n")
    w("pyproject.toml", f'[project]\ndependencies = [\n  "paicad=={version}",\n]\n')
    w("deploy/requirements.local.lock", f"simdash-adapters==0.1.0\npaicad=={version}\n")
    for d in chk.PLATFORM_PKG_DIRS:
        w(f"{d}/__init__.py", "import json\n")
    return root


def test_repository_passes():
    errs = chk.run_all(REPO, skip_git=True)
    assert errs == [], errs


def test_repository_pins_match_version():
    ver = chk.version_of(REPO)
    meta = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    assert f"paicad=={ver}" in meta["project"]["dependencies"]
    ini = meta["tool"]["pytest"]["ini_options"]
    assert "packages/paicad/src" in ini["pythonpath"]


def test_script_exit_codes(tmp_path):
    r = subprocess.run([sys.executable, str(REPO / "scripts" / "check_paicad.py"), "--skip-git"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    root = make_tree(tmp_path)
    (root / "packages/paicad/CHANGELOG.md").write_text("## 0.4.0 — 2026-01-01\n", encoding="utf-8")
    r = subprocess.run([sys.executable, str(REPO / "scripts" / "check_paicad.py"), "--root", str(root), "--skip-git"],
                       capture_output=True, text=True)
    assert r.returncode == 1 and "CHANGELOG" in r.stderr


def test_clean_tree_passes(tmp_path):
    assert chk.run_all(make_tree(tmp_path), skip_git=True) == []


@pytest.mark.parametrize("what", ["changelog", "root_pin", "lock_pin", "static_version", "no_dynamic"])
def test_version_consistency_violations(tmp_path, what):
    root = make_tree(tmp_path)
    if what == "changelog":
        (root / "packages/paicad/CHANGELOG.md").write_text("## 0.4.9 — 2026-10-19\n", encoding="utf-8")
    elif what == "root_pin":
        (root / "pyproject.toml").write_text('dependencies = ["paicad==0.4.0"]\n', encoding="utf-8")
    elif what == "lock_pin":
        (root / "deploy/requirements.local.lock").write_text("simdash-adapters==0.1.0\n", encoding="utf-8")
    elif what == "static_version":
        (root / "packages/paicad/pyproject.toml").write_text(PAICAD_PYPROJECT.replace('dynamic = ["version"]', 'version = "0.5.0"'),
                                                              encoding="utf-8")
    else:
        (root / "packages/paicad/pyproject.toml").write_text('[project]\nname = "paicad"\n\n[tool.x]\n', encoding="utf-8")
    errs = chk.check_versions(root)
    assert errs, what


@pytest.mark.parametrize("stmt", ["import paicad", "from paicad.cli import main", "import OCP.gp", "from OCP.gp import gp_Pnt",
                                  "def f():\n    import paicad.update"])
@pytest.mark.parametrize("pkg", chk.PLATFORM_PKG_DIRS)
def test_platform_must_not_import_paicad_or_ocp(tmp_path, pkg, stmt):
    root = make_tree(tmp_path)
    (root / pkg / "bad.py").write_text(stmt + "\n", encoding="utf-8")
    errs = chk.check_platform_imports(root)
    assert len(errs) == 1 and "bad.py" in errs[0]


def test_platform_geometry_package_name_is_not_flagged(tmp_path):
    root = make_tree(tmp_path)
    (root / "backend/physicsai_core/ok.py").write_text("from physicsai_core.geometry import reports\nimport json\n", encoding="utf-8")
    assert chk.check_platform_imports(root) == []


@pytest.mark.parametrize("stmt", ["import physicsai_core", "from physicsai_worker.steps import x", "import backend.x", "from worker import y"])
def test_paicad_must_not_import_platform(tmp_path, stmt):
    root = make_tree(tmp_path)
    (root / "packages/paicad/src/paicad/bad.py").write_text(stmt + "\n", encoding="utf-8")
    assert any("bad.py" in e for e in chk.check_paicad_independence(root))
    (root / "packages/paicad/src/paicad/bad.py").unlink()
    (root / "packages/paicad/tests/bad.py").write_text(stmt + "\n", encoding="utf-8")
    assert any("tests/bad.py" in e for e in chk.check_paicad_independence(root))


def test_ocp_only_inside_kernel(tmp_path):
    root = make_tree(tmp_path)
    assert chk.check_paicad_independence(root) == []  # kernel/ 안 OCP는 허용
    (root / "packages/paicad/src/paicad/morph.py").write_text("def f():\n    from OCP.gp import gp_Pnt\n", encoding="utf-8")
    errs = chk.check_paicad_independence(root)
    assert len(errs) == 1 and "morph.py" in errs[0] and "kernel" in errs[0]


def test_platform_names_korean_and_notice(tmp_path):
    root = make_tree(tmp_path)
    (root / "packages/paicad/src/paicad/a.py").write_text('X = "104_replace_node_elem.inc"\n', encoding="utf-8")
    (root / "packages/paicad/src/paicad/b.py").write_text("# 한국어 주석\n", encoding="utf-8")
    (root / "packages/paicad/THIRD_PARTY_NOTICES.md").unlink()
    errs = chk.check_paicad_independence(root)
    assert any("a.py" in e for e in errs) and any("b.py" in e for e in errs) and any("THIRD_PARTY" in e for e in errs)


def _git(root: Path, *a: str) -> None:
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-C", str(root), *a], check=True, capture_output=True)


def test_version_must_be_bumped_when_paicad_changes(tmp_path):
    root = make_tree(tmp_path)
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    assert chk.check_version_bumped(root) == []                      # 변경 없음(HEAD~1 없음 → 생략)
    (root / "packages/paicad/src/paicad/cli.py").write_text("import numpy\nX = 1\n", encoding="utf-8")
    errs = chk.check_version_bumped(root)                           # 작업 트리 변경 → HEAD 기준
    assert len(errs) == 1 and "__version__" in errs[0]
    (root / "packages/paicad/src/paicad/__init__.py").write_text('__version__ = "0.5.1"\n', encoding="utf-8")
    assert chk.check_version_bumped(root) == []
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "paicad change with bump")
    assert chk.check_version_bumped(root) == []                      # HEAD~1 기준, 버전 올림
    (root / "packages/paicad/src/paicad/cli.py").write_text("import numpy\nX = 2\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "paicad change without bump")
    assert len(chk.check_version_bumped(root)) == 1                  # 커밋 단위: 올리지 않은 커밋
    _git(root, "commit", "-q", "--allow-empty", "-m", "unrelated")
    assert chk.check_version_bumped(root) == []                      # paicad를 안 건드린 커밋은 대상 아님


def test_base_override(tmp_path):
    root = make_tree(tmp_path)
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    (root / "packages/paicad/src/paicad/cli.py").write_text("import numpy\nX = 3\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "change")
    assert len(chk.check_version_bumped(root, base="HEAD~1")) == 1
    assert chk.check_version_bumped(root, base="HEAD") == []
