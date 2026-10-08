"""파일 유틸: sha256, 진행률 복사, JSON 쓰기. 사용자 산출물 삭제 함수는 두지 않는다."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections.abc import Callable
from typing import Any

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


def copy_into_study(src: str, dst: str, progress: Callable[[int], None] | None = None,
                    checkpoint: Callable[[], None] | None = None) -> int:
    """Study 안으로 복사(phase2 §13.3 쓰기 헬퍼). 보호 루트(SPDM) 대상은 예외."""
    return copy_file(src, dst, progress, checkpoint)


def write_json(path: str, data: Any) -> int:
    _guard(path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=2)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return len(text.encode("utf-8"))


def write_text(path: str, text: str) -> int:
    _guard(path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    return len(text.encode("utf-8"))
