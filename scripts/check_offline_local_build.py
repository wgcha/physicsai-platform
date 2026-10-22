#!/usr/bin/env python3
"""로컬 소스 패키지 오프라인 빌드 확인(이슈 #9, CI Linux): 빈 venv에 deploy/requirements.lock의 setuptools 고정만 `--no-index`로 넣고,
저장소 안 3개 패키지(simdash_adapters·paicad·플랫폼)를 `pip install --no-index --no-build-isolation --no-deps`로 설치해 성공하는지 본다.
빌드 격리를 켜면 pip가 build-system.requires(setuptools>=68)를 인덱스에서 받으려다 폐쇄망·프록시에서 실패한다(No matching distribution found).

사용: python scripts/check_offline_local_build.py [--work DIR]   (종료 코드 0 = 통과, 1 = 실패, 3 = 패키지 인덱스 접근 불가)
네트워크는 setuptools wheel 한 개를 받을 때만 쓴다(pip download). 이후 설치는 전부 --no-index.
shell=False, 저장소 소스는 작업 폴더로 복사해 빌드한다(저장소에 build/·egg-info를 남기지 않음).
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXIT_NO_INDEX = 3
NETWORK_MARKERS = ("NewConnectionError", "ConnectTimeout", "ConnectionError", "ProxyError", "Max retries exceeded", "Temporary failure in name resolution",
                   "No matching distribution found", "Could not find a version", "SSLError", "403 Client Error", "407")
IGNORE = shutil.ignore_patterns("tests", "__pycache__", "*.pyc", "build", "*.egg-info", "fake_tools", "openapi.json")
PIP_OPTS = ["--disable-pip-version-check", "--progress-bar", "off"]


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, shell=False, **kw)


def lock_pin(name: str) -> str:
    for line in (REPO / "deploy" / "requirements.lock").read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#") and "==" in line:
            n, _, ver = line.partition("==")
            if n.strip().lower().replace("_", "-") == name:
                return f"{name}=={ver.strip()}"
    raise SystemExit(f"deploy/requirements.lock에 {name} 고정이 없습니다")


def fail(r: subprocess.CompletedProcess, what: str) -> int:
    out = (r.stdout or "") + (r.stderr or "")
    print(f"실패: {what}\n{out}", file=sys.stderr)
    return EXIT_NO_INDEX if any(m in out for m in NETWORK_MARKERS) and "--no-index" not in what else 1


def stage_sources(work: Path) -> dict[str, Path]:
    src = work / "src"
    if src.exists():
        shutil.rmtree(src)
    src.mkdir()
    shutil.copytree(REPO / "packages" / "simdash_adapters", src / "simdash_adapters", ignore=IGNORE)
    shutil.copytree(REPO / "packages" / "paicad", src / "paicad", ignore=IGNORE)
    plat = src / "platform"
    plat.mkdir()
    shutil.copy2(REPO / "pyproject.toml", plat / "pyproject.toml")
    for d in ("backend", "worker"):
        shutil.copytree(REPO / d, plat / d, ignore=IGNORE)
    return {"simdash-adapters": src / "simdash_adapters", "paicad": src / "paicad", "physicsai-platform": plat}


def check(work: Path) -> int:
    wheels = work / "wheels"
    wheels.mkdir(parents=True, exist_ok=True)
    pin = lock_pin("setuptools")
    req = work / "build-requirements.txt"
    req.write_text(pin + "\n", encoding="utf-8")
    r = run([sys.executable, "-m", "pip", "download", "-r", str(req), "--only-binary=:all:", "--no-deps", "-d", str(wheels), *PIP_OPTS])
    if r.returncode != 0:
        return fail(r, f"pip download {pin}")
    pkgs = stage_sources(work)
    venv = work / "venv"
    r = run([sys.executable, "-m", "venv", str(venv)])
    if r.returncode != 0:
        return fail(r, "python -m venv")
    bindir = venv / ("Scripts" if sys.platform == "win32" else "bin")
    py = str(bindir / ("python.exe" if sys.platform == "win32" else "python"))
    # 출발 상태: venv에 빌드 도구가 없다(Python 3.12 venv는 setuptools를 넣지 않음) — lock 설치가 넣어 주는 것을 그대로 재현
    if run([py, "-c", "import setuptools"]).returncode == 0:
        print("이 Python의 venv에는 이미 setuptools가 있습니다 — 빈 venv 조건을 만들 수 없습니다(Python 3.12 필요)", file=sys.stderr)
        return 1
    r = run([py, "-m", "pip", "install", "--no-index", "--find-links", str(wheels), "-r", str(req), *PIP_OPTS])
    if r.returncode != 0:
        return fail(r, f"pip install --no-index {pin}")
    for name, path in pkgs.items():
        r = run([py, "-m", "pip", "install", "--no-index", "--no-build-isolation", "--no-deps", "--force-reinstall", str(path), *PIP_OPTS])
        if r.returncode != 0:
            return fail(r, f"pip install --no-index --no-build-isolation {name}")
    r = run([py, "-I", "-c", (
        "import json, importlib.metadata as m, importlib.util as u;"
        "names=['simdash-adapters','paicad','physicsai-platform','setuptools'];"
        "print(json.dumps({n: m.version(n) for n in names}));"
        "assert all(u.find_spec(x) for x in ('simdash_adapters','paicad','physicsai_core','physicsai_api','physicsai_mcp'))")])
    if r.returncode != 0:
        return fail(r, "설치 확인(메타데이터·import 경로)")
    got = json.loads(r.stdout.strip().splitlines()[-1])
    print("설치됨:", got)
    if f"setuptools=={got['setuptools']}" != pin:
        print(f"setuptools 버전이 lock 고정({pin})과 다릅니다: {got['setuptools']}", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--work", default="", help="작업 폴더(비우면 임시 폴더, 끝나면 지움)")
    args = ap.parse_args()
    tmp = None if args.work else tempfile.TemporaryDirectory(prefix="physicsai-local-build-")
    work = Path(args.work or tmp.name)  # type: ignore[union-attr]
    try:
        return check(work)
    finally:
        if tmp is not None:
            tmp.cleanup()


if __name__ == "__main__":
    sys.exit(main())
