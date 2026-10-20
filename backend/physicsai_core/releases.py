"""플랫폼 버전·버전 기록(RELEASES.md) 읽기 — 표준 라이브러리만(scripts/check_releases.py도 같이 쓴다).

- 단일 출처: 저장소 루트 `RELEASES.md`(최신이 위, `## <버전> — YYYY-MM-DD` + `- 주요 기능` 목록).
  플랫폼 버전 = 루트 pyproject `version` = `physicsai_core.__version__` = RELEASES.md 최상단(scripts/test-all 검사).
- 배포: 설치 스크립트가 RELEASES.md를 프런트 배치 폴더(`server.frontend_root`)에 함께 둔다. 백엔드는 읽기만 하며
  쓰기 수단(API·화면)은 없다. 소스 실행(개발)이면 저장소 루트의 파일을 읽는다.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

RELEASES_FILE = "RELEASES.md"
BUILD_INFO_FILE = "BUILD_INFO.json"
HEADING_RE = re.compile(r"^##\s+(\d+\.\d+\.\d+)\s+—\s+(\d{4}-\d{2}-\d{2})\s*$")
ITEM_RE = re.compile(r"^[-*]\s+(.+?)\s*$")
CONT_RE = re.compile(r"^\s{2,}(\S.*?)\s*$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


@dataclass
class Release:
    version: str
    date: str
    items: list[str] = field(default_factory=list)


class ReleasesFormatError(ValueError):
    """RELEASES.md 형식 오류(한국어 메시지)."""


def parse_releases(text: str) -> list[Release]:
    """`## x.y.z — YYYY-MM-DD` 아래 `- ` 목록을 항목으로. 첫 제목 전 머리말은 무시, 들여쓴 줄은 앞 항목에 이어 붙인다."""
    out: list[Release] = []
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip()
        if line.startswith("## "):
            m = HEADING_RE.match(line)
            if not m:
                raise ReleasesFormatError(f"{n}행: 버전 제목 형식이 아닙니다(`## x.y.z — YYYY-MM-DD`): {line}")
            out.append(Release(m.group(1), m.group(2)))
            continue
        if not out or not line.strip():
            continue
        m = ITEM_RE.match(line)
        if m:
            out[-1].items.append(m.group(1))
            continue
        c = CONT_RE.match(line)
        if c and out[-1].items:
            out[-1].items[-1] = f"{out[-1].items[-1]} {c.group(1)}"
            continue
        raise ReleasesFormatError(f"{n}행: 항목은 `- 주요 기능` 목록이어야 합니다: {line}")
    return out


def _key(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.split("."))


def validate_releases(rels: list[Release]) -> list[str]:
    """형식 외 규칙: 1개 이상, 각 항목 1줄 이상, 버전 중복 없음·최신이 위(엄격 감소), 날짜 비증가."""
    errs: list[str] = []
    if not rels:
        return ["RELEASES.md에 버전 항목(`## x.y.z — YYYY-MM-DD`)이 없습니다"]
    for r in rels:
        if not r.items:
            errs.append(f"{r.version}: 주요 기능 목록(`- ...`)이 없습니다")
    for a, b in zip(rels, rels[1:]):
        if _key(a.version) <= _key(b.version):
            errs.append(f"버전 순서 오류: {a.version} 아래에 {b.version} — 최신이 위, 중복 없이")
        if a.date < b.date:
            errs.append(f"날짜 순서 오류: {a.version}({a.date})가 {b.version}({b.date})보다 이릅니다")
    return errs


def source_repo_root() -> Path | None:
    """소스 실행이면 저장소 루트(backend/physicsai_core의 두 단계 위에 pyproject.toml), 설치본(wheel)이면 None."""
    root = Path(__file__).resolve().parents[2]
    return root if (root / "pyproject.toml").is_file() and (root / "backend" / "physicsai_core").is_dir() else None


def candidate_paths(name: str, frontend_root: str | None, repo_sub: str = "") -> list[Path]:
    """찾는 순서: 프런트 배치 폴더(설치) → 저장소(소스 실행)."""
    out: list[Path] = []
    if frontend_root:
        out.append(Path(frontend_root) / name)
    repo = source_repo_root()
    if repo is not None:
        out.append((repo / repo_sub / name) if repo_sub else repo / name)
    return out


_cache: dict[str, tuple[float, int, list[Release]]] = {}


def load_releases(frontend_root: str | None) -> list[Release]:
    """설치된 RELEASES.md를 읽어 파싱(파일 mtime·크기가 같으면 캐시). 없거나 형식 오류면 빈 목록."""
    for p in candidate_paths(RELEASES_FILE, frontend_root):
        try:
            st = p.stat()
        except OSError:
            continue
        hit = _cache.get(str(p))
        if hit and hit[0] == st.st_mtime and hit[1] == st.st_size:
            return hit[2]
        try:
            rels = parse_releases(p.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError, ReleasesFormatError):
            rels = []
        _cache[str(p)] = (st.st_mtime, st.st_size, rels)
        return rels
    return []


def load_build_info(frontend_root: str | None) -> dict | None:
    """프런트 빌드본 BUILD_INFO.json(source_hash·built_at, git_commit 선택). 없으면 None."""
    for p in candidate_paths(BUILD_INFO_FILE, frontend_root, "frontend-dist"):
        try:
            data = json.loads(p.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            return data
    return None


def installed_version(dist: str, search: list[str] | None = None) -> str | None:
    """설치 메타데이터(`<dist>-*.dist-info/METADATA`의 Version)만 읽는다 — import·importlib 없음(플랫폼 → paicad import 금지)."""
    for d in search if search is not None else sys.path:
        try:
            base = Path(d or ".")
            metas = sorted(base.glob(f"{dist}-*.dist-info/METADATA"))
        except OSError:
            continue
        for meta in metas:
            try:
                for line in meta.read_text(encoding="utf-8", errors="replace").splitlines():
                    if line.startswith("Version:"):
                        return line.split(":", 1)[1].strip() or None
                    if not line.strip():
                        break
            except OSError:
                continue
    return None


def _git_dir(repo: Path) -> Path | None:
    g = repo / ".git"
    if g.is_dir():
        return g
    if g.is_file():  # worktree: "gitdir: <경로>"
        txt = g.read_text(encoding="utf-8", errors="replace").strip()
        if txt.startswith("gitdir:"):
            p = Path(txt[7:].strip())
            return p if p.is_absolute() else (repo / p).resolve()
    return None


def git_commit_of(repo: Path | None) -> str | None:
    """`.git` 파일만 읽어 HEAD 커밋(외부 명령 없음). 알 수 없으면 None."""
    if repo is None:
        return None
    try:
        gd = _git_dir(repo)
        if gd is None:
            return None
        head = (gd / "HEAD").read_text(encoding="utf-8").strip()
        if COMMIT_RE.match(head):
            return head
        if not head.startswith("ref:"):
            return None
        ref = head[4:].strip()
        common = gd
        cd = gd / "commondir"
        if cd.is_file():
            c = Path(cd.read_text(encoding="utf-8").strip())
            common = c if c.is_absolute() else (gd / c).resolve()
        for base in (gd, common):
            f = base / ref
            if f.is_file():
                v = f.read_text(encoding="utf-8").strip()
                return v if COMMIT_RE.match(v) else None
        packed = common / "packed-refs"
        if packed.is_file():
            for line in packed.read_text(encoding="utf-8").splitlines():
                parts = line.split()
                if len(parts) == 2 and parts[1] == ref and COMMIT_RE.match(parts[0]):
                    return parts[0]
    except OSError:
        return None
    return None
