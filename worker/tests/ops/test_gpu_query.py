"""GPU 조회 실행 파일 자동 탐색(phase3 D3-45): 탐색 순서(gpu_query → PATH → %SystemRoot% → %ProgramFiles%),
NOT_FOUND·ERROR 상태, 자원 스냅샷 키, 환경 점검 gpu.detect가 같은 탐색을 쓰는지."""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from physicsai_core.config.schema import GPU_QUERY_CANDIDATES
from physicsai_worker import env_check, resources

pytestmark = pytest.mark.skipif(os.name == "nt", reason="가짜 실행 파일(셸뱅 스크립트)은 POSIX에서만")

OK_LINE = "RTX A6000, 12, 2048, 49140"


def fake_exe(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!{sys.executable}\nimport sys, time\n{body}\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def printer(path: Path, name: str) -> Path:
    return fake_exe(path, f"print({name!r} + ', 12, 2048, 49140')")


@pytest.fixture
def tree(tmp_path):
    """PATH 폴더·SystemRoot·ProgramFiles 흉내. 기본 후보(백슬래시)를 비Windows에서도 그대로 쓴다."""
    bin_dir, sysroot, pf = tmp_path / "bin", tmp_path / "Windows", tmp_path / "PF"
    bin_dir.mkdir()
    env = {"PATH": str(bin_dir), "SystemRoot": str(sysroot), "ProgramFiles": str(pf)}
    exes = {
        "path": printer(bin_dir / "nvidia-smi", "from-path"),
        "sysroot": printer(sysroot / "System32" / "nvidia-smi.exe", "from-sysroot"),
        "pf": printer(pf / "NVIDIA Corporation" / "NVSMI" / "nvidia-smi.exe", "from-pf"),
    }
    return SimpleNamespace(env=env, exes=exes, tmp=tmp_path)


def q(gpu_query, env):
    return resources.query_gpu_status(gpu_query, list(GPU_QUERY_CANDIDATES), None, env)


def test_search_order_path_then_systemroot_then_programfiles(tree):
    g = q(None, tree.env)                                                # gpu_query 없음 → 자동 탐색
    assert (g.status, g.gpus[0]["name"], g.exe) == ("OK", "from-path", str(tree.exes["path"]))
    tree.exes["path"].unlink()
    g = q(None, tree.env)
    assert (g.status, g.gpus[0]["name"]) == ("OK", "from-sysroot")
    tree.exes["sysroot"].unlink()
    g = q(["C:/Windows/System32/nvidia-smi.exe", "--query-gpu=x", "--format=csv"], tree.env)   # 첫 인자 없음 → 후보, 인자 유지
    assert (g.status, g.gpus[0]["name"]) == ("OK", "from-pf")
    argv, tried = resources.resolve_gpu_argv(["/nope/nvidia-smi.exe", "--a", "--b"], GPU_QUERY_CANDIDATES, tree.env)
    assert argv == [str(tree.exes["pf"]), "--a", "--b"] and tried[0] == "/nope/nvidia-smi.exe"
    tree.exes["pf"].unlink()
    g = q(None, tree.env)
    assert g.status == "NOT_FOUND" and g.gpus == [] and g.exe is None
    assert g.message.startswith("nvidia-smi를 찾지 못했습니다(시도: nvidia-smi, %SystemRoot%")


def test_configured_first_arg_wins_and_default_args(tree):
    own = printer(tree.tmp / "own" / "smi", "from-config")
    g = q([str(own)], tree.env)                                          # 있으면 후보보다 우선(인자 그대로)
    assert (g.status, g.gpus[0]["name"]) == ("OK", "from-config")
    argv, _ = resources.resolve_gpu_argv(None, GPU_QUERY_CANDIDATES, tree.env)
    assert argv == [str(tree.exes["path"]), *resources.GPU_QUERY_ARGS]    # 설정 없으면 기본 조회 인자
    argv, _ = resources.resolve_gpu_argv(["nvidia-smi", "--x"], GPU_QUERY_CANDIDATES, tree.env)
    assert argv == [str(tree.exes["path"]), "--x"]                        # 이름만 = PATH


def test_env_expansion_and_undefined_variable(tree):
    assert resources.expand_env("%SystemRoot%\\System32", {"SYSTEMROOT": "C:\\Win"}) == "C:\\Win\\System32"   # 대소문자 무시
    assert resources.expand_env("${HOME}/x", {"HOME": "/h"}) == "/h/x"
    assert resources.expand_env("%NOPE%\\x.exe", {}) is None
    env = {"PATH": str(tree.tmp / "empty")}                               # 변수 미정의 후보는 건너뜀
    g = q(None, env)
    assert g.status == "NOT_FOUND"


@pytest.mark.parametrize(("body", "needle"), [
    ("sys.stderr.write('NVIDIA-SMI has failed\\n'); sys.exit(9)", "nvidia-smi 종료코드 9: NVIDIA-SMI has failed"),
    ("print('garbage')", "출력에서 GPU 정보를 읽지 못했습니다"),
])
def test_error_status(tree, body, needle):
    bad = fake_exe(tree.tmp / "bad" / "smi", body)
    g = q([str(bad)], tree.env)
    assert g.status == "ERROR" and g.gpus == [] and needle in g.message and g.exe == str(bad)


def test_error_not_executable_and_timeout(tree, monkeypatch):
    plain = tree.tmp / "plain" / "smi"
    plain.parent.mkdir()
    plain.write_text("not executable")
    g = q([str(plain)], tree.env)
    assert g.status == "ERROR" and g.message.startswith("nvidia-smi를 실행하지 못했습니다")
    monkeypatch.setattr(resources, "GPU_TIMEOUT_S", 0.3)
    slow = fake_exe(tree.tmp / "slow" / "smi", "time.sleep(5)")
    g = q([str(slow)], tree.env)
    assert g.status == "ERROR" and "시간 초과" in g.message


def test_sample_has_status_keys(tree, monkeypatch):
    for k, v in tree.env.items():
        monkeypatch.setenv(k, v)
    s = resources.sample(None, None, None, GPU_QUERY_CANDIDATES)
    assert s["gpu_status"] == "OK" and s["gpu"][0]["name"] == "from-path" and s["gpu_message"] == str(tree.exes["path"])
    for e in tree.exes.values():
        e.unlink()
    s = resources.sample(None, None, None, GPU_QUERY_CANDIDATES)
    assert s["gpu"] == [] and s["gpu_status"] == "NOT_FOUND" and "찾지 못했습니다" in s["gpu_message"]


def test_env_check_gpu_detect_uses_same_search(tree):
    s = SimpleNamespace(worker=SimpleNamespace(gpu_query=["C:/missing/nvidia-smi.exe"]),
                        resources=SimpleNamespace(gpu_query_candidates=list(GPU_QUERY_CANDIDATES)))
    it = env_check.gpu_item(s, None, tree.env)
    assert it["status"] == "OK" and it["detail"]["exe"] == str(tree.exes["path"]) and it["detail"]["gpus"][0]["name"] == "from-path"
    for e in tree.exes.values():
        e.unlink()
    it = env_check.gpu_item(s, None, tree.env)
    assert it["status"] == "WARN" and it["detail"]["gpu_status"] == "NOT_FOUND"
    assert it["message"].startswith("GPU를 찾지 못했습니다 — nvidia-smi를 찾지 못했습니다(시도: C:/missing/nvidia-smi.exe, nvidia-smi")
