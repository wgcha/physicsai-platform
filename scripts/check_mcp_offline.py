#!/usr/bin/env python3
"""MCP 오프라인 설치 확인(mcp.md V-MCP-20, CI Linux): deploy/requirements.lock의 mcp 전이 의존 wheel만 모아(pip download — 네트워크 필요)
빈 venv에 `--no-index`로 설치하고 플랫폼 wheel(--no-deps)의 console script `physicsai-mcp --version`이 도는지 본다.

사용: python scripts/check_mcp_offline.py [--work DIR]   (종료 코드 0 = 통과, 1 = 실패, 3 = 패키지 인덱스 접근 불가)
Windows 묶음(win_amd64 wheel, pywin32 포함)은 collect-offline.ps1 + 수동 확인(e2e-checklist) — 여기서는 현재 OS의 wheel로 같은 구조를 본다.
shell=False, 저장소 소스는 작업 폴더로 복사해 빌드한다(저장소에 build/·egg-info를 남기지 않음).
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from importlib import metadata
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXIT_NO_INDEX = 3
NETWORK_MARKERS = ("NewConnectionError", "ConnectTimeout", "ConnectionError", "ProxyError", "Max retries exceeded", "Temporary failure in name resolution",
                   "No matching distribution found", "Could not find a version", "SSLError", "403 Client Error", "407")
# physicsai_mcp.stdio가 import하는 것: mcp(+전이 의존) + httpx(+전이 의존)
ROOTS = ("mcp", "httpx")


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, shell=False, **kw)


def lock_pins() -> dict[str, str]:
    out: dict[str, str] = {}
    for line in (REPO / "deploy" / "requirements.lock").read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#") and "==" in line:
            name, _, ver = line.partition("==")
            out[name.strip().lower().replace("_", "-")] = ver.strip()
    return out


def closure(roots: tuple[str, ...]) -> set[str]:
    from packaging.requirements import Requirement

    seen: set[str] = set()
    todo = list(roots)
    while todo:
        name = todo.pop().lower().replace("_", "-")
        if name in seen:
            continue
        seen.add(name)
        try:
            reqs = metadata.requires(name) or []
        except metadata.PackageNotFoundError:  # 이 OS에 없는 플랫폼 전용 의존(Linux의 pywin32) — 잎
            reqs = []
        for raw in reqs:
            r = Requirement(raw)
            if r.marker is None or r.marker.evaluate({"extra": ""}):
                todo.append(r.name)
    return seen


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--work", default="", help="작업 폴더(비우면 임시 폴더, 끝나면 지움)")
    args = ap.parse_args()
    tmp = None if args.work else tempfile.TemporaryDirectory(prefix="physicsai-mcp-offline-")
    work = Path(args.work or tmp.name)  # type: ignore[union-attr]
    try:
        return check(work)
    finally:
        if tmp is not None:
            tmp.cleanup()


def check(work: Path) -> int:
    wheels = work / "wheels"
    wheels.mkdir(parents=True, exist_ok=True)
    pins = lock_pins()
    names = sorted(n for n in closure(ROOTS) if n in pins)
    missing = sorted(n for n in closure(ROOTS) if n not in pins)
    if missing:
        print(f"lock에 없는 전이 의존: {missing}", file=sys.stderr)
        return 1
    req = work / "mcp-requirements.txt"
    req.write_text("".join(f"{n}=={pins[n]}\n" for n in names), encoding="utf-8")
    r = run([sys.executable, "-m", "pip", "download", "-r", str(req), "--only-binary=:all:", "-d", str(wheels), "--disable-pip-version-check"])
    if r.returncode != 0:
        print(r.stdout + r.stderr, file=sys.stderr)
        return EXIT_NO_INDEX if any(m in r.stdout + r.stderr for m in NETWORK_MARKERS) else 1
    # 플랫폼 wheel: 작업 폴더로 복사한 소스에서 빌드(--no-deps)
    src = work / "src"
    if src.exists():
        shutil.rmtree(src)
    src.mkdir()
    shutil.copy2(REPO / "pyproject.toml", src / "pyproject.toml")
    for d in ("backend", "worker"):
        shutil.copytree(REPO / d, src / d, ignore=shutil.ignore_patterns("tests", "__pycache__", "*.pyc", "fake_tools", "openapi.json"))
    r = run([sys.executable, "-m", "pip", "wheel", str(src), "--no-deps", "-w", str(wheels), "--disable-pip-version-check"])
    if r.returncode != 0:
        print(r.stdout + r.stderr, file=sys.stderr)
        return EXIT_NO_INDEX if any(m in r.stdout + r.stderr for m in NETWORK_MARKERS) else 1
    venv = work / "venv"
    r = run([sys.executable, "-m", "venv", str(venv)])
    if r.returncode != 0:
        print(r.stdout + r.stderr, file=sys.stderr)
        return 1
    bindir = venv / ("Scripts" if sys.platform == "win32" else "bin")
    py = bindir / ("python.exe" if sys.platform == "win32" else "python")
    for cmd in ([str(py), "-m", "pip", "install", "--no-index", "--find-links", str(wheels), "-r", str(req), "--disable-pip-version-check"],
                [str(py), "-m", "pip", "install", "--no-index", "--find-links", str(wheels), "--no-deps", "physicsai-platform",
                 "--disable-pip-version-check"]):
        r = run(cmd)
        if r.returncode != 0:
            print(r.stdout + r.stderr, file=sys.stderr)
            return 1
    exe = bindir / ("physicsai-mcp.exe" if sys.platform == "win32" else "physicsai-mcp")
    r = run([str(exe), "--version"])
    print(r.stdout.strip())
    if r.returncode != 0 or not r.stdout.startswith("physicsai-mcp "):
        print(r.stderr, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
