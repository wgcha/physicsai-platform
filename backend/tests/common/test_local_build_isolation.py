"""이슈 #9(v0.2.6): 로컬 소스 패키지(simdash_adapters·paicad·플랫폼) 설치가 빌드 격리로 인덱스(PyPI·프록시)에 의존하지 않는다.

정적: lock에 setuptools 고정(빌드 도구, 3개 pyproject 하한 만족)·로컬 소스 설치 명령에 --no-build-isolation·lock이 먼저·실패 안내·오프라인 묶음 검사.
동적(slow, 네트워크는 setuptools wheel 1개에만): scripts/check_offline_local_build.py — 빈 venv + --no-index + --no-build-isolation로 3개 설치.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tomllib

import pytest
from packaging.specifiers import SpecifierSet
from packaging.version import Version
from physicsai_test_support import REPO

PKG_PYPROJECTS = ("pyproject.toml", "packages/simdash_adapters/pyproject.toml", "packages/paicad/pyproject.toml")


def _read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8-sig")


def _pins() -> dict[str, str]:
    out = {}
    for ln in _read("deploy/requirements.lock").splitlines():
        if ln and not ln.startswith("#") and "==" in ln:
            n, _, v = ln.partition("==")
            out[n.strip().lower().replace("_", "-")] = v.strip()
    return out


def test_lock_pins_build_backend_satisfying_every_local_package():
    pins = _pins()
    assert "setuptools" in pins
    assert "wheel" not in pins  # setuptools>=70.1은 bdist_wheel 내장 — 불필요한 고정을 넣지 않는다
    ver = Version(pins["setuptools"])
    assert ver >= Version("70.1")
    for rel in PKG_PYPROJECTS:
        bs = tomllib.loads(_read(rel))["build-system"]
        assert bs["build-backend"] == "setuptools.build_meta", rel
        reqs = [r for r in bs["requires"]]
        assert len(reqs) == 1 and reqs[0].startswith("setuptools"), (rel, reqs)  # wheel 등 다른 빌드 의존이 생기면 lock·이 시험을 같이 갱신
        assert ver in SpecifierSet(reqs[0].removeprefix("setuptools")), (rel, reqs[0], ver)


def _repo_packages_body() -> str:
    t = _read("deploy/install-common.ps1")
    i = t.index("function Install-PhysicsAIRepoPackages")
    return t[i:t.index("function Publish-PhysicsAIFrontend")]


def test_repo_packages_install_lock_first_then_local_sources_without_build_isolation():
    body = _repo_packages_body()
    lines = [ln for ln in body.splitlines() if "Invoke-PhysicsAIPip" in ln and "'install'" in ln]
    assert len(lines) == 4, lines
    assert "requirements.lock" in lines[0] and "--no-build-isolation" not in lines[0]
    targets = ("packages\\simdash_adapters", "packages\\paicad", "$RepoRoot)")
    for ln, tgt in zip(lines[1:], targets):
        assert "'--no-build-isolation'" in ln and "'--no-deps'" in ln and "'--force-reinstall'" in ln and tgt in ln, ln
        assert "'--no-index'" not in ln  # 인덱스 사용 가능 환경에서도 같은 명령(lock 의존은 이미 설치) — 격리만 끈다
        assert "-ExtraHint $buildHint" in ln, ln
    assert "pip show setuptools" in body and "$VenvPy -m pip show setuptools" in body


def test_pip_failure_messages_append_build_tool_hint():
    t = _read("deploy/install-common.ps1")
    fn = t[t.index("function Invoke-PhysicsAIPip"):t.index("function ConvertFrom-PhysicsAIDbUrl")]
    assert "[string]$ExtraHint = ''" in fn
    assert fn.count("$extra") >= 3  # 정의 1 + 인덱스 접근 실패 + 일반 실패


def test_no_script_installs_local_source_with_build_isolation():
    """저장소 소스 경로(packages\\… · $RepoRoot)를 설치하는 pip install 호출(편집 설치 -e 제외)은 모두 --no-build-isolation."""
    hits = []
    for rel in ("deploy/install-common.ps1", "deploy/demo/demo-python.ps1", "deploy/setup.ps1", "deploy/update-repo.ps1",
                "deploy/install.ps1", "deploy/update.ps1"):
        for n, ln in enumerate(_read(rel).splitlines(), 1):
            if "'install'" in ln and re.search(r"packages\\\\?(simdash_adapters|paicad)|\$RepoRoot\)", ln) and "-e" not in ln.split("'install'")[1].split(")")[0]:
                hits.append((rel, n, ln))
                assert "--no-build-isolation" in ln, (rel, n, ln)
    assert len(hits) >= 4  # install-common 3 + demo-python 1


def test_demo_installs_lock_before_local_adapters():
    t = _read("deploy/demo/demo-python.ps1")
    i_lock = t.index("-PipArgs @('install', '-r', (Join-Path $RepoRoot 'deploy\\requirements.lock'))")
    i_ad = t.index("'--no-build-isolation', (Join-Path $RepoRoot 'packages\\simdash_adapters')")
    assert i_lock < i_ad


def test_offline_install_paths_use_prebuilt_wheels_only():
    """오프라인 묶음 설치(install.ps1·update.ps1)는 wheel만 설치 — 빌드 없음. 묶음에는 setuptools wheel이 들어간다(lock → pip download)."""
    for f in ("deploy/install.ps1", "deploy/update.ps1"):
        t = _read(f)
        assert "pip install --no-index --find-links" in t and "packages" not in re.findall(r"pip install[^\n]*", t)[0], f
    assert "setuptools-*.whl" in _read("deploy/collect-offline.ps1")
    assert "dist/wheels/setuptools-*.whl" in _read("deploy/collect-offline.sh")


@pytest.mark.posix
def test_collect_offline_dry_run_checks_setuptools_wheel():
    r = subprocess.run(["bash", str(REPO / "deploy" / "collect-offline.sh"), "--dry-run"], capture_output=True, text=True, cwd=REPO, timeout=60)
    assert r.returncode == 0, r.stderr
    out = r.stdout
    assert out.index("pip download -r deploy/requirements.lock") < out.index("setuptools-*.whl")


@pytest.mark.slow
def test_offline_local_build_in_empty_venv(tmp_path):
    """빈 venv + --no-index + --no-build-isolation로 paicad·adapters·플랫폼 설치(setuptools wheel 1개만 pip download — 네트워크)."""
    r = subprocess.run([sys.executable, str(REPO / "scripts" / "check_offline_local_build.py"), "--work", str(tmp_path)], capture_output=True, text=True,
                       timeout=900, cwd=REPO)
    if r.returncode == 3:
        pytest.skip("패키지 인덱스에 접근할 수 없어 건너뜀(네트워크 필요): " + r.stderr[-200:])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "설치됨" in r.stdout
