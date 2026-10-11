"""3차 S4(phase3.md §6.4·§6.5, V3-S4-1·5·7): simdash_adapters 호환층·의존 선언·배포 내용 정적 시험."""

from __future__ import annotations

import logging
import re
import subprocess
import tomllib

import pytest

import simdash_adapters
from physicsai_test_support import REPO

PKG = REPO / "packages" / "simdash_adapters"
VERSION = tomllib.loads((PKG / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
WHEEL = f"simdash_adapters-{VERSION}-py3-none-any.whl"


def _read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8-sig")


def test_compat_layer_reexports_same_objects():
    from physicsai_core import commands
    from physicsai_core.config import is_abs_path_str, rules
    from physicsai_core.hpc import adapter, command, gateway, none

    assert commands.fwd is simdash_adapters.fwd
    assert rules.is_abs_path_str is is_abs_path_str is simdash_adapters.is_abs_path_str
    for n in ("HpcAvailability", "HpcSubmitSpec", "HpcSubmitResult", "HpcStatus", "HpcGatewayError", "HpcJobGateway"):
        assert getattr(gateway, n) is getattr(simdash_adapters, n), n
    assert none.NoneHpcGateway is simdash_adapters.NoneHpcGateway
    assert adapter.AdapterHpcGateway is simdash_adapters.AdapterHpcGateway
    assert command.map_path is simdash_adapters.map_path
    assert issubclass(command.CommandHpcGateway, simdash_adapters.CommandHpcGateway)


def test_platform_command_gateway_keeps_logger_name(settings_dict, fake_tools):
    from physicsai_core.config import load_config_dict
    from physicsai_core.hpc.command import CommandHpcGateway
    from physicsai_core.hpc.gateway import get_hpc_gateway

    d = dict(settings_dict)
    d["hpc"] = {"gateway": "command", "command": {
        "allowed_executables": [fake_tools["fake_qsub"], fake_tools["fake_qstat"], fake_tools["fake_qdel"]],
        "submit": [fake_tools["fake_qsub"], "-N", "{job_name}"], "status": [fake_tools["fake_qstat"], "{external_job_id}"],
        "cancel": [fake_tools["fake_qdel"], "{external_job_id}"], "state_map": {"Q": "QUEUED"}}}
    lc = load_config_dict(d, environ={})
    assert lc.ok, lc.issues
    gw = get_hpc_gateway(lc.settings)
    assert gw.availability().configured and gw.log is logging.getLogger("physicsai_core.hpc.command")
    assert gw.env_factory is not None and "PHYSICSAI_DATABASE_URL" not in gw.env_factory()
    legacy = CommandHpcGateway(lc.settings.hpc)
    assert legacy.hpc is lc.settings.hpc and legacy.log.name == "physicsai_core.hpc.command"
    assert legacy.defaults.queue == lc.settings.hpc.defaults.queue


def test_platform_depends_on_exact_package_version():
    meta = tomllib.loads(_read("pyproject.toml"))
    assert f"simdash-adapters=={VERSION}" in meta["project"]["dependencies"]
    ini = meta["tool"]["pytest"]["ini_options"]
    assert "packages/simdash_adapters/tests" in ini["testpaths"] and "packages/simdash_adapters/src" in ini["pythonpath"]
    assert simdash_adapters.__version__ == VERSION


def test_lock_and_offline_bundle_include_wheel():
    """V3-S4-7(정적): lock 항목, collect-offline이 wheel을 먼저 만들고 --find-links로 lock을 받는다, 설치는 --no-index."""
    lock = _read("deploy/requirements.lock")
    assert re.search(rf"^simdash-adapters=={re.escape(VERSION)}$", lock, re.MULTILINE)
    for f in ("deploy/collect-offline.sh", "deploy/collect-offline.ps1"):
        t = _read(f)
        w = t.index("pip wheel packages/simdash_adapters --no-deps -w dist/wheels")
        dl = t.index("pip download -r deploy/requirements.lock")
        assert w < dl, f
        assert re.search(r"pip download -r deploy/requirements\.lock [^\n]*-d dist/wheels --find-links dist/wheels", t), f
    for f in ("deploy/install.ps1", "deploy/update.ps1", "deploy/demo/start-demo.ps1"):
        assert "pip install --no-index --find-links" in _read(f), f


@pytest.mark.posix  # Windows는 CI windows 잡에서 collect-offline.ps1 실제 실행
def test_collect_offline_dry_run_builds_adapter_wheel_first():
    r = subprocess.run(["bash", str(REPO / "deploy" / "collect-offline.sh"), "--dry-run"], capture_output=True, text=True, cwd=REPO,
                       timeout=60)
    assert r.returncode == 0, r.stderr
    lines = [ln for ln in r.stdout.splitlines() if ln.startswith("+ ")]
    iw = next(i for i, ln in enumerate(lines) if "pip wheel packages/simdash_adapters --no-deps -w dist/wheels" in ln)
    idl = next(i for i, ln in enumerate(lines) if "pip download -r deploy/requirements.lock" in ln)
    assert iw < idl and "--find-links dist/wheels" in lines[idl]


def test_dev_paths_and_ci_include_package():
    assert "packages/simdash_adapters/src" in _read("scripts/_env.sh")
    assert "packages\\simdash_adapters\\src" in _read("scripts/_env.ps1")
    for f in ("deploy/demo/start-demo.ps1", "deploy/demo/stop-demo.ps1"):
        assert "packages\\simdash_adapters\\src" in _read(f), f
    assert '"packages" / "simdash_adapters" / "src"' in _read("deploy/demo/demo_setup.py")
    for f in ("scripts/dev-setup.sh", "scripts/dev-setup.ps1"):
        t = _read(f)
        assert t.index("pip install -e packages/simdash_adapters") < t.index("pip install -r deploy/requirements.lock"), f
    ci = _read(".github/workflows/ci.yml")
    assert ci.count("pip install ./packages/simdash_adapters") == 2  # linux·windows: lock보다 먼저
    assert "scripts/check-adapters-wheel.sh" in ci and WHEEL in ci
