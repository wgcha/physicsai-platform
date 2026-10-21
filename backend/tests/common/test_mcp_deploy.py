"""mcp.md V-MCP-20(오프라인 설치 정적 부분)·§20.5(배포): lock 고정·전이 의존 폐쇄·Caddy 추가분·설치 스크립트의 실행기 확인·패키지 메타.

빈 venv `--no-index` 설치 + `physicsai-mcp --version`은 scripts/check_mcp_offline.py(네트워크 필요 — slow 시험·CI Linux), Windows 묶음은 수동(e2e-checklist).
"""

from __future__ import annotations

import re
import subprocess
import tomllib
from importlib import metadata

import pytest

from physicsai_test_support import REPO

DEPLOY = REPO / "deploy"


def _lock() -> dict[str, str]:
    out = {}
    for line in (DEPLOY / "requirements.lock").read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            name, _, ver = line.partition("==")
            out[name.strip().lower().replace("_", "-")] = ver.strip()
    return out


def _closure(root: str, env: dict[str, str]) -> set[str]:
    from packaging.requirements import Requirement

    seen: set[str] = set()
    todo = [root]
    while todo:
        name = todo.pop().lower().replace("_", "-")
        if name in seen:
            continue
        seen.add(name)
        try:
            reqs = metadata.requires(name) or []
        except metadata.PackageNotFoundError:  # 이 OS에 설치되지 않은 플랫폼 전용 의존(예: Linux의 pywin32) — 잎으로 두고 lock 포함 여부만 본다
            reqs = []
        for raw in reqs:
            r = Requirement(raw)
            if r.marker is not None and not r.marker.evaluate({**env, "extra": ""}):
                continue
            todo.append(r.name)
    return seen


def test_mcp_is_pinned_in_pyproject_and_lock_with_transitive_closure():
    pyproject = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    pinned = [d for d in pyproject["project"]["dependencies"] if d.startswith("mcp")]
    assert len(pinned) == 1 and re.fullmatch(r"mcp==\d+\.\d+\.\d+", pinned[0].split("#")[0].strip()), pinned
    lock = _lock()
    assert lock["mcp"] == pinned[0].split("==")[1].strip() and lock["mcp-types"] == lock["mcp"]
    assert metadata.version("mcp") == lock["mcp"], "시험 환경의 mcp가 lock과 다릅니다"
    for env in ({"sys_platform": "win32", "platform_system": "Windows", "python_version": "3.12", "python_full_version": "3.12.13",
                 "platform_python_implementation": "CPython", "os_name": "nt", "implementation_name": "cpython"},
                {"sys_platform": "linux", "platform_system": "Linux", "python_version": "3.12", "python_full_version": "3.12.13",
                 "platform_python_implementation": "CPython", "os_name": "posix", "implementation_name": "cpython"}):
        missing = sorted(n for n in _closure("mcp", env) if n not in lock)
        assert missing == [], f"{env['sys_platform']}: lock에 없는 mcp 전이 의존 {missing}"
    assert "pywin32" in lock  # Windows 전용 전이 의존도 묶음에 포함(mcp.md §20.5)
    assert "python-multipart" in lock  # SDK 전이 의존으로만 — 플랫폼 코드 import 0은 test_layering


def test_package_metadata_exposes_console_script_and_package():
    pyproject = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["scripts"] == {"physicsai-mcp": "physicsai_mcp.stdio:main"}
    assert "physicsai_mcp*" in pyproject["tool"]["setuptools"]["packages"]["find"]["include"]
    assert (REPO / "backend" / "physicsai_mcp" / "__init__.py").is_file()


def test_caddy_snippet_adds_mcp_handle_before_catch_all_and_keeps_existing():
    caddy = (DEPLOY / "caddy" / "physicsai.caddy").read_text(encoding="utf-8")
    m = "handle /physicsai/mcp* {\n\treverse_proxy 127.0.0.1:{$PHYSICSAI_PORT:8100}\n}"
    assert m in caddy
    assert caddy.index(m) < caddy.index("\nhandle /physicsai/assets/* {") < caddy.index("\nhandle /physicsai/* {")
    for kept in ("redir /physicsai /physicsai/ 308", "handle /physicsai/api/* {", "try_files {path} /index.html"):  # 추가만, 기존 블록 불변
        assert kept in caddy


def test_install_scripts_verify_the_mcp_runner():
    common = (DEPLOY / "install-common.ps1").read_text(encoding="utf-8")
    assert "physicsai_mcp" in common and "physicsai-mcp.exe" in common and "'--version'" in common
    for n in ("install.ps1", "update.ps1"):
        assert "physicsai_mcp.stdio --version" in (DEPLOY / n).read_text(encoding="utf-8"), n
    for n in ("collect-offline.sh", "collect-offline.ps1"):
        t = (DEPLOY / n).read_text(encoding="utf-8")
        assert "mcp-*.whl" in t and "pywin32-*.whl" in t, n


@pytest.mark.posix
def test_collect_offline_dry_run_checks_mcp_wheels():
    r = subprocess.run(["bash", str(DEPLOY / "collect-offline.sh"), "--dry-run"], capture_output=True, text=True, cwd=REPO, timeout=60)
    assert r.returncode == 0, r.stderr
    assert "dist/wheels/mcp-*.whl" in r.stdout and r.stdout.index("pip download -r deploy/requirements.lock") < r.stdout.index("mcp-*.whl")


@pytest.mark.slow
def test_offline_install_runs_physicsai_mcp_version(tmp_path):
    """V-MCP-20: lock의 MCP 의존 wheel만 모아(pip download, 네트워크) 빈 venv에 --no-index로 설치 → `physicsai-mcp --version`."""
    import sys

    r = subprocess.run([sys.executable, str(REPO / "scripts" / "check_mcp_offline.py"), "--work", str(tmp_path)], capture_output=True, text=True,
                       timeout=900, cwd=REPO)
    if r.returncode == 3:
        pytest.skip("패키지 인덱스에 접근할 수 없어 건너뜀(네트워크 필요): " + r.stderr[-200:])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "physicsai-mcp " in r.stdout
