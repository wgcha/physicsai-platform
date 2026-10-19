"""파일 유틸: sha256, 진행률 복사, JSON 쓰기. 사용자 산출물 삭제 함수는 두지 않는다."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
from collections.abc import Callable
from typing import Any

from .errors import StepFailure

CHUNK = 1024 * 1024


def _guard(dst: str) -> None:
    from .paths import assert_writable

    assert_writable(dst)


def sha256_file(path: str, checkpoint: Callable[[], None] | None = None) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            b = fh.read(CHUNK)
            if not b:
                break
            h.update(b)
            if checkpoint:
                checkpoint()
    return h.hexdigest()


def copy_file(src: str, dst: str, progress: Callable[[int], None] | None = None,
              checkpoint: Callable[[], None] | None = None) -> int:
    """1 MiB 버퍼 복사(shutil.copyfile 동작 + 진행률). 복사 바이트 수. SPDM(보호 루트) 대상이면 예외."""
    _guard(dst)
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    total = 0
    with open(src, "rb") as fi, open(dst, "wb") as fo:
        while True:
            b = fi.read(CHUNK)
            if not b:
                break
            fo.write(b)
            total += len(b)
            if progress:
                progress(total)
            if checkpoint:
                checkpoint()
    shutil.copymode(src, dst)
    return total


def copy_stream(fi: Any, dst: str) -> int:
    """이미 연 원본 핸들(바이너리 읽기)에서 dst로 1 MiB 버퍼 복사. 원본 경로를 다시 열지 않는다(링크 교체 TOCTOU 방지, D3-50)."""
    _guard(dst)
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    total = 0
    with open(dst, "wb") as fo:
        while True:
            b = fi.read(CHUNK)
            if not b:
                break
            fo.write(b)
            total += len(b)
    return total


def write_json(path: str, data: Any) -> int:
    _guard(path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=2)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return len(text.encode("utf-8"))


def write_json_atomic(path: str, data: Any) -> int:
    """같은 폴더의 무작위 임시 파일(mkstemp: O_CREAT|O_EXCL)에 쓴 뒤 os.replace로 바꾼다(읽는 쪽이 반쯤 쓴 파일을 보지 않음).

    - 폴더를 만들지 않는다(없으면 FileNotFoundError) — 호출자가 폴더 존재를 보장한다.
    - 대상이나 폴더가 링크(symlink·junction)면 StepFailure(PATH_UNSAFE). SPDM 하위도 거부.
    - 삭제 호출 없음: 쓰기 중 실패하면 `.<이름>.*.tmp`가 남을 수 있다.
    """
    from .paths import is_link_or_reparse

    _guard(path)
    d = os.path.dirname(path) or "."
    if is_link_or_reparse(d):
        raise StepFailure("PATH_UNSAFE", f"링크 폴더에는 쓸 수 없습니다: {d}")
    try:
        mode = stat.S_IMODE(os.stat(path).st_mode)
    except FileNotFoundError:
        mode = 0o644
    text = json.dumps(data, ensure_ascii=False, indent=2)
    fd, tmp = tempfile.mkstemp(prefix=f".{os.path.basename(path)}.", suffix=".tmp", dir=d)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.chmod(tmp, mode)
    os.replace(tmp, path)
    return len(text.encode("utf-8"))


def write_text(path: str, text: str) -> int:
    _guard(path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    return len(text.encode("utf-8"))


def copy_tree(src: str, dst: str, checkpoint: Callable[[], None] | None = None) -> list[str]:
    """폴더 src의 파일을 dst로 복사(하위 폴더 포함, 링크·재해석 지점·_backup은 건너뜀). 복사한 상대 경로 목록(정렬).
    dst에 같은 이름이 이미 있으면 호출자가 먼저 `_backup`으로 옮긴 상태여야 한다(덮어쓰기 가드는 copy_file이 한다)."""
    from .paths import is_link_or_reparse

    out: list[str] = []
    for dirpath, dirnames, filenames in os.walk(src, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d != "_backup" and not is_link_or_reparse(os.path.join(dirpath, d)))
        rel_dir = os.path.relpath(dirpath, src)
        os.makedirs(os.path.join(dst, rel_dir) if rel_dir != "." else dst, exist_ok=True)
        for f in sorted(filenames):
            p = os.path.join(dirpath, f)
            if is_link_or_reparse(p) or not os.path.isfile(p):
                continue
            rel = f if rel_dir == "." else os.path.join(rel_dir, f)
            copy_file(p, os.path.join(dst, rel), checkpoint=checkpoint)
            out.append(rel.replace(os.sep, "/"))
    return out
