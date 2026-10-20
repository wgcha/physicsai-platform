#!/usr/bin/env python3
"""플랫폼 버전 기록 검사(배포로만 기록 — 버전 게시판). 표준 라이브러리만.

사용: python scripts/check_releases.py [--root <저장소>]

1. 저장소 루트 RELEASES.md가 있고 형식(`## x.y.z — YYYY-MM-DD` + `- 주요 기능`)·순서(최신이 위, 중복 없음)가 맞다.
2. 최상단 버전 == 루트 pyproject.toml [project] version == backend/physicsai_core/__init__.py `__version__`.
3. 설치 묶음·git 설치가 RELEASES.md를 프런트 배치 폴더에 함께 둔다(collect-offline.ps1·.sh, install-common.ps1).
실패 메시지는 한국어, 종료코드 1.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

VERSION_RE = re.compile(r'^__version__\s*=\s*"([^"]+)"\s*$', re.MULTILINE)
PROJECT_VERSION_RE = re.compile(r'^version\s*=\s*"([^"]+)"\s*$', re.MULTILINE)
DEPLOY_FILES = ("deploy/collect-offline.ps1", "deploy/collect-offline.sh", "deploy/install-common.ps1")


def _load_module():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
    from physicsai_core import releases  # noqa: E402 — 표준 라이브러리만 쓰는 모듈

    return releases


def check(root: Path) -> list[str]:
    rel = _load_module()
    errs: list[str] = []
    f = root / rel.RELEASES_FILE
    if not f.is_file():
        return [f"{rel.RELEASES_FILE}가 저장소 루트에 없습니다"]
    try:
        rels = rel.parse_releases(f.read_text(encoding="utf-8-sig"))
    except rel.ReleasesFormatError as exc:
        return [f"{rel.RELEASES_FILE} 형식 오류 — {exc}"]
    errs += rel.validate_releases(rels)
    pp = (root / "pyproject.toml").read_text(encoding="utf-8")
    proj = re.search(r"^\[project\]\n(.*?)(?=^\[|\Z)", pp, re.MULTILINE | re.DOTALL)
    m = PROJECT_VERSION_RE.search(proj.group(1)) if proj else None
    py_ver = m.group(1) if m else None
    m = VERSION_RE.search((root / "backend/physicsai_core/__init__.py").read_text(encoding="utf-8"))
    core_ver = m.group(1) if m else None
    top = rels[0].version if rels else None
    if py_ver is None:
        errs.append("루트 pyproject.toml [project]에 version이 없습니다")
    if core_ver != py_ver:
        errs.append(f"physicsai_core.__version__({core_ver})가 pyproject version({py_ver})과 다릅니다 — 함께 올리세요")
    if top is not None and top != py_ver:
        errs.append(f"RELEASES.md 최상단 버전({top})이 pyproject version({py_ver})과 다릅니다 — 릴리스 시 함께 갱신하세요")
    for d in DEPLOY_FILES:
        p = root / d
        if p.is_file() and rel.RELEASES_FILE not in p.read_text(encoding="utf-8-sig"):
            errs.append(f"{d}가 {rel.RELEASES_FILE}를 배포 묶음(프런트 배치 폴더)에 넣지 않습니다")
    return errs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="RELEASES.md·플랫폼 버전 검사")
    ap.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    a = ap.parse_args(argv)
    errs = check(Path(a.root).resolve())
    for e in errs:
        print(f"[버전 기록] {e}", file=sys.stderr)
    if not errs:
        print("버전 기록 검사 통과")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
