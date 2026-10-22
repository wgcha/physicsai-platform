"""조립 include 트리(asm-match.md §4.1·§5.4) — starter에서 `#include`로 닿는 파일 목록·digest(플랫폼 쪽, 내용 색인 없음).

paicad `mesh/asmtree.py`와 **같은 규칙**이어야 한다(digest·트리 복사 대상이 paicad 판정과 같아야 `ASM_MATCH_STALE`가 거짓 양성이 안 된다 —
V-AM-10이 실제 paicad로 대조한다). 플랫폼은 파일 내용을 해석하지 않고 `/BEGIN` 카드·`#include` 줄만 본다.

- starter = 조립 폴더 직계 `*.rad` 중 `/BEGIN` 카드가 있는 파일 정확히 1개(`eps_mesh*` 제외, IK-C1 판별 규칙).
- `#include <경로>`(대소문자 무시·앞 공백 허용·따옴표 허용·포함 파일 폴더 기준·`/`·`\\` 모두) 깊이 우선 수집.
- 링크·조립 폴더 밖(realpath) `ASM_INCLUDE_OUTSIDE`, 대상 없음 `ASM_INCLUDE_MISSING`, 순환·같은 파일 두 번 include `GEOM_INPUT_INVALID`.
- digest = `sha256:` + sha256( 줄 `<상대경로>\\t<파일 sha256>\\n` 을 (경로, sha) 순으로 정렬한 연결 ).
파일 해시는 (경로·크기·mtime_ns)가 같으면 캐시한다(목록·상태 화면이 큰 조립을 매번 다시 읽지 않게 — prep.sha256_file과 같은 방식).
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable
from dataclasses import dataclass, field

from ..fileutil import copy_file
from ..fileutil import sha256_file as _sha256_file

MESH_FILE_PREFIX = "eps_mesh"  # SimLab 쿠션 메시 파일은 starter 후보가 아니다(paicad MESH_FILE_PREFIX와 같음)
_SHA_CACHE: dict[tuple[str, int, int], str] = {}
_SHA_CACHE_MAX = 4096


class AsmTreeError(Exception):
    """include 트리 오류. code = paicad 코드와 같음(`ASM_INCLUDE_OUTSIDE` | `ASM_INCLUDE_MISSING` | `GEOM_INPUT_INVALID`)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class TreeFile:
    rel: str  # 조립 폴더 기준 '/' 구분 상대 경로
    path: str
    sha256: str
    includes: list[str] = field(default_factory=list)


@dataclass
class AsmTree:
    root: str
    starter: str  # 트리 뿌리 파일(rel)
    files: list[TreeFile]

    @property
    def digest(self) -> str:
        return tree_digest([(f.rel, f.sha256) for f in self.files])

    def rels(self) -> list[str]:
        return [f.rel for f in self.files]


def cached_sha(path: str, checkpoint: Callable[[], None] | None = None) -> str:
    """파일 sha256(경로·크기·mtime_ns가 같으면 캐시)."""
    st = os.stat(path)
    key = (os.path.abspath(path), st.st_size, st.st_mtime_ns)
    hit = _SHA_CACHE.get(key)
    if hit is None:
        hit = _sha256_file(path, checkpoint)
        if len(_SHA_CACHE) >= _SHA_CACHE_MAX:
            _SHA_CACHE.clear()
        _SHA_CACHE[key] = hit
    return hit


def tree_digest(items: list[tuple[str, str]]) -> str:
    h = hashlib.sha256()
    for rel, sha in sorted(items):
        h.update(f"{rel}\t{sha}\n".encode())
    return "sha256:" + h.hexdigest()


def _has_begin(path: str) -> bool:
    with open(path, "rb") as fh:
        for ln in fh:
            if ln.startswith(b"/"):
                kw = [p.strip().upper() for p in ln.rstrip(b"\r\n").decode("latin-1").strip().split("/")[1:]]
                if kw[:1] == ["BEGIN"]:
                    return True
    return False


def find_starter(root: str) -> str:
    """조립 폴더 직계 `*.rad` 중 `/BEGIN` 카드가 있는 파일 이름(정확히 1개, 아니면 GEOM_INPUT_INVALID)."""
    found = []
    for n in sorted(os.listdir(root)):
        p = os.path.join(root, n)
        if n.lower().endswith(".rad") and os.path.isfile(p) and not n.lower().startswith(MESH_FILE_PREFIX) and _has_begin(p):
            found.append(n)
    if not found:
        raise AsmTreeError("GEOM_INPUT_INVALID", "조립 폴더에 starter(/BEGIN 카드가 있는 *.rad)가 없습니다")
    if len(found) > 1:
        raise AsmTreeError("GEOM_INPUT_INVALID", "조립 폴더에 starter(/BEGIN 카드가 있는 *.rad)가 2개 이상입니다: " + ", ".join(found[:10]))
    return found[0]


def _includes(path: str) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    with open(path, "rb") as fh:
        for ln, raw in enumerate(fh):
            if raw[:1] == b"/":
                continue
            s = raw.lstrip()
            if s[:1] in (b"#", b"$") and s[:8].lower() == b"#include":
                p = s[8:].strip().strip(b"\"'").decode("latin-1")
                if p:
                    out.append((ln, p))
    return out


def build(assem_dir: str, checkpoint: Callable[[], None] | None = None) -> AsmTree:
    """starter에서 include 트리를 따라 파일 목록·sha256을 만든다. 오류는 AsmTreeError."""
    root = os.path.abspath(assem_dir)
    if not os.path.isdir(root):
        raise AsmTreeError("GEOM_INPUT_INVALID", "조립 폴더를 찾을 수 없습니다")
    root_real = os.path.realpath(root)
    starter = find_starter(root)
    if os.path.islink(os.path.join(root, starter)):
        raise AsmTreeError("ASM_INCLUDE_OUTSIDE", f"starter {starter}이(가) 링크입니다")
    files: list[TreeFile] = []
    seen: set[str] = set()

    def visit(path: str, rel: str, stack: list[str]) -> None:
        if checkpoint:
            checkpoint()
        tf = TreeFile(rel, path, cached_sha(path, checkpoint))
        seen.add(rel)
        files.append(tf)
        for ln, raw in _includes(path):
            target = os.path.join(os.path.dirname(path), raw.replace("\\", "/"))
            where = f"{rel} {ln + 1}번째 줄"
            if os.path.islink(target):
                raise AsmTreeError("ASM_INCLUDE_OUTSIDE", f"include {raw!r}({where})이(가) 링크입니다")
            real = os.path.realpath(target)
            try:
                trel = os.path.relpath(real, root_real).replace(os.sep, "/")
            except ValueError:  # 다른 드라이브(Windows)
                trel = "../"
            if trel == ".." or trel.startswith("../") or os.path.isabs(trel):
                raise AsmTreeError("ASM_INCLUDE_OUTSIDE", f"include {raw!r}({where})이(가) 조립 폴더 밖을 가리킵니다")
            if not os.path.isfile(real):
                raise AsmTreeError("ASM_INCLUDE_MISSING", f"include {raw!r}({where}) 대상이 없습니다")
            if trel in stack:
                raise AsmTreeError("GEOM_INPUT_INVALID", "include 순환: " + " -> ".join(stack + [trel]))
            if trel in seen:
                raise AsmTreeError("GEOM_INPUT_INVALID", f"{trel}을(를) 두 번 include했습니다({where})")
            tf.includes.append(trel)
            visit(os.path.join(root, *trel.split("/")), trel, stack + [trel])

    srel = os.path.relpath(os.path.realpath(os.path.join(root, starter)), root_real).replace(os.sep, "/")
    visit(os.path.join(root, *srel.split("/")), srel, [srel])
    return AsmTree(root, srel, files)


def digest_of(assem_dir: str) -> str | None:
    """조립 폴더의 트리 digest(트리 오류·폴더 없음 = None — 호출자가 STALE로 본다)."""
    try:
        return build(assem_dir).digest
    except (AsmTreeError, OSError):
        return None


def copy_included(tree: AsmTree, dst: str, checkpoint: Callable[[], None] | None = None) -> list[str]:
    """include 트리의 파일만 dst로 복사(상대 경로·하위 폴더 유지, 트리 밖 파일은 복사하지 않는다 — asm-match.md §5.4·§6.4). 복사한 rel 목록."""
    out: list[str] = []
    for f in tree.files:
        copy_file(f.path, os.path.join(dst, *f.rel.split("/")), checkpoint=checkpoint)
        out.append(f.rel)
    return out
