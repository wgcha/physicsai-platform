#!/usr/bin/env python3
"""paicad 정적 검사(geometry-engine.md §17.5·§18.6·§14 V-GE-2·11·13·14·19). 표준 라이브러리만 쓴다.

사용: python scripts/check_paicad.py [--root <저장소>] [--base <git 비교 기준>] [--skip-git]

1. 버전(§17.5): CHANGELOG 최상단 `## x.y.z — YYYY-MM-DD` == `__version__`, `pyproject.toml`에 정적 version 없음,
   루트 `paicad==` 고정·`deploy/requirements.local.lock` == `__version__`, `packages/paicad/**`가 기준과 다르면 `__version__`도 다름.
   기준: 작업 트리에 packages/paicad 변경이 있으면 HEAD, 없으면 HEAD~1(CI는 --base 또는 환경변수 PAICAD_VERSION_BASE).
2. 플랫폼 → paicad·OCP import 금지(V-GE-2): physicsai_core·physicsai_api·physicsai_worker.
3. paicad → 플랫폼 import 금지(V-GE-13)·kernel/ 밖 OCP import 금지(V-GE-19)·플랫폼 고유 이름 리터럴·한국어 없음(V-GE-14)·
   라이선스 고지 파일 존재(§18.5).
실패 메시지는 한국어, 종료코드 1.
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import subprocess
import sys
from pathlib import Path

PLATFORM_ROOTS = ("physicsai_core", "physicsai_api", "physicsai_worker", "backend", "worker")
PLATFORM_PKG_DIRS = ("backend/physicsai_core", "backend/physicsai_api", "worker/physicsai_worker")
FORBIDDEN_FROM_PLATFORM = ("paicad", "OCP", "cadquery")
HARDCODED_NAMES = ("104_replace_node_elem.inc", "RENUM_INIT.csv", "radioss_assem")  # V-GE-14: src/에 리터럴로 없어야 함
VERSION_RE = re.compile(r'^__version__\s*=\s*"([^"]+)"\s*$', re.MULTILINE)
CHANGELOG_RE = re.compile(r"^##\s+(\d+\.\d+\.\d+)\s+—\s+\d{4}-\d{2}-\d{2}\s*$", re.MULTILINE)
KOREAN_RE = re.compile("[가-힣ㄱ-ㆎ]")


def _py_files(base: Path) -> list[Path]:
    return sorted(p for p in base.rglob("*.py") if "__pycache__" not in p.parts and ".egg-info" not in str(p))


def _imports(path: Path) -> list[tuple[int, str]]:
    """(줄, 최상위 모듈 이름) — 함수 안 지연 import 포함, 상대 import 제외."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    except SyntaxError as exc:
        return [(exc.lineno or 0, "<syntax-error>")]
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out += [(node.lineno, a.name.split(".")[0]) for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            out.append((node.lineno, node.module.split(".")[0]))
    return out


def version_of(root: Path) -> str | None:
    f = root / "packages/paicad/src/paicad/__init__.py"
    m = VERSION_RE.search(f.read_text(encoding="utf-8")) if f.is_file() else None
    return m.group(1) if m else None


def check_versions(root: Path) -> list[str]:
    errs: list[str] = []
    ver = version_of(root)
    if ver is None:
        return ["packages/paicad/src/paicad/__init__.py에서 `__version__ = \"x.y.z\"` 한 줄을 찾지 못했습니다"]
    cl = root / "packages/paicad/CHANGELOG.md"
    m = CHANGELOG_RE.search(cl.read_text(encoding="utf-8")) if cl.is_file() else None
    if m is None:
        errs.append("packages/paicad/CHANGELOG.md 최상단에 `## x.y.z — YYYY-MM-DD` 항목이 없습니다")
    elif m.group(1) != ver:
        errs.append(f"CHANGELOG 최상단 버전({m.group(1)})이 __version__({ver})과 다릅니다 — 같은 커밋에서 함께 올리세요")
    pp = root / "packages/paicad/pyproject.toml"
    text = pp.read_text(encoding="utf-8") if pp.is_file() else ""
    proj = re.search(r"^\[project\]\n(.*?)(?=^\[)", text, re.MULTILINE | re.DOTALL)
    if proj and re.search(r"^version\s*=", proj.group(1), re.MULTILINE):
        errs.append("packages/paicad/pyproject.toml [project]에 정적 version이 있습니다 — dynamic version(attr)만 허용")
    if 'dynamic = ["version"]' not in text or "paicad.__version__" not in text:
        errs.append("packages/paicad/pyproject.toml에 dynamic version(attr = paicad.__version__)이 없습니다")
    root_pp = (root / "pyproject.toml").read_text(encoding="utf-8")
    pins = re.findall(r'"paicad==([^"]+)"', root_pp)
    if pins != [ver]:
        errs.append(f"루트 pyproject.toml의 paicad 고정({pins or '없음'})이 __version__({ver})과 다릅니다")
    lock = root / "deploy/requirements.local.lock"
    lpins = re.findall(r"^paicad==(\S+)\s*$", lock.read_text(encoding="utf-8"), re.MULTILINE) if lock.is_file() else []
    if lpins != [ver]:
        errs.append(f"deploy/requirements.local.lock의 paicad 고정({lpins or '없음'})이 __version__({ver})과 다릅니다")
    return errs


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=60)


def check_version_bumped(root: Path, base: str | None = None) -> list[str]:
    """packages/paicad/**가 기준과 다르면 __version__도 달라야 한다(§17.5 (1))."""
    if _git(root, "rev-parse", "--git-dir").returncode != 0:
        print("버전 증가 검사 생략: git 저장소가 아닙니다")
        return []
    base = base or os.environ.get("PAICAD_VERSION_BASE")
    dirty = _git(root, "status", "--porcelain", "--", "packages/paicad").stdout.strip() != ""
    if base is None:
        base = "HEAD" if dirty else "HEAD~1"
    if _git(root, "rev-parse", "--verify", "--quiet", base + "^{commit}").returncode != 0:
        print(f"버전 증가 검사 생략: 비교 기준 {base}이(가) 없습니다(얕은 복제·첫 커밋)")
        return []
    changed = _git(root, "diff", "--name-only", base, "--", "packages/paicad").stdout.split()
    changed += [x for x in _git(root, "ls-files", "--others", "--exclude-standard", "--", "packages/paicad").stdout.split()]
    changed = [c for c in changed if "__pycache__" not in c and ".egg-info" not in c]
    if not changed:
        return []
    shown = _git(root, "show", f"{base}:packages/paicad/src/paicad/__init__.py")
    m = VERSION_RE.search(shown.stdout) if shown.returncode == 0 else None
    old, new = (m.group(1) if m else None), version_of(root)
    if old is not None and old == new:
        return [f"packages/paicad가 {base} 대비 바뀌었는데 __version__({new})이 그대로입니다 — 버전을 올리고 CHANGELOG 최상단에 항목을 추가하세요"
                f"(바뀐 파일 {len(changed)}개, 예: {changed[0]})"]
    return []


def check_platform_imports(root: Path) -> list[str]:
    errs: list[str] = []
    for d in PLATFORM_PKG_DIRS:
        for f in _py_files(root / d):
            for line, mod in _imports(f):
                if mod in FORBIDDEN_FROM_PLATFORM:
                    errs.append(f"{f.relative_to(root)}:{line}: 플랫폼 프로세스는 `{mod}`를 import할 수 없습니다(결과 JSON만 읽음, geometry-engine.md §1.4)")
    return errs


def check_paicad_independence(root: Path) -> list[str]:
    errs: list[str] = []
    src = root / "packages/paicad/src/paicad"
    for base in (root / "packages/paicad/src", root / "packages/paicad/tests"):
        for f in _py_files(base):
            for line, mod in _imports(f):
                if mod in PLATFORM_ROOTS:
                    errs.append(f"{f.relative_to(root)}:{line}: paicad는 플랫폼 모듈 `{mod}`를 import할 수 없습니다(§18.1)")
    kernel = src / "kernel"
    for f in _py_files(src):
        if kernel in f.parents:
            continue
        for line, mod in _imports(f):
            if mod in ("OCP", "cadquery"):
                errs.append(f"{f.relative_to(root)}:{line}: OCP는 paicad/kernel/ 안에서만 import할 수 있습니다(§18.9)")
    for f in _py_files(src):
        text = f.read_text(encoding="utf-8-sig")
        rel = f.relative_to(root)
        for name in HARDCODED_NAMES:
            if name in text:
                errs.append(f"{rel}: 플랫폼 고유 이름 `{name}` 리터럴이 있습니다 — CLI 인자·입력 JSON으로 받으세요(§18.1)")
        if KOREAN_RE.search(text):
            errs.append(f"{rel}: 한국어가 있습니다 — paicad 메시지·주석은 영문(§18.4)")
    notice = root / "packages/paicad/THIRD_PARTY_NOTICES.md"
    if not notice.is_file() or notice.stat().st_size == 0:
        errs.append("packages/paicad/THIRD_PARTY_NOTICES.md(제3자 라이선스 고지)가 없습니다(§18.5)")
    for need in ("pyproject.toml", "CHANGELOG.md"):
        if not (root / "packages/paicad" / need).is_file():
            errs.append(f"packages/paicad/{need}가 없습니다(§18.5)")
    return errs


def run_all(root: Path, base: str | None = None, skip_git: bool = False) -> list[str]:
    errs = check_versions(root)
    if not skip_git:
        errs += check_version_bumped(root, base)
    errs += check_platform_imports(root) + check_paicad_independence(root)
    return errs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    ap.add_argument("--base", default=None, help="git 버전 비교 기준(기본: 작업 트리 변경이 있으면 HEAD, 없으면 HEAD~1)")
    ap.add_argument("--skip-git", action="store_true")
    a = ap.parse_args(argv)
    errs = run_all(Path(a.root), a.base, a.skip_git)
    for e in errs:
        print("paicad 검사 실패:", e, file=sys.stderr)
    if not errs:
        print(f"paicad 검사 통과(__version__ {version_of(Path(a.root))})")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
