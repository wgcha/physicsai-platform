"""경로 원시 판정(§17.3): 링크·junction(reparse) 판정, Windows 예약 이름, realpath·포함 비교(`real`·`is_under`)."""

from __future__ import annotations

import os
import stat

FILE_ATTRIBUTE_REPARSE_POINT = 0x400
IO_REPARSE_TAG_SYMLINK = 0xA000000C
IO_REPARSE_TAG_MOUNT_POINT = 0xA0000003  # junction
LINK_REPARSE_TAGS = frozenset({IO_REPARSE_TAG_SYMLINK, IO_REPARSE_TAG_MOUNT_POINT})
WINDOWS_RESERVED = frozenset({"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))})


def _is_windows() -> bool:
    return os.name == "nt"


def _cmp(p: str) -> str:
    return os.path.normcase(p) if _is_windows() else p


def is_link_or_reparse(p: str) -> bool:
    """실제 링크(symlink·junction)만 True. dedup·OneDrive 등 다른 reparse 태그는 링크로 보지 않는다."""
    try:
        st = os.lstat(p)
    except OSError:
        return False
    if stat.S_ISLNK(st.st_mode):
        return True
    attrs = getattr(st, "st_file_attributes", 0)
    if not attrs & FILE_ATTRIBUTE_REPARSE_POINT:
        return False
    return getattr(st, "st_reparse_tag", 0) in LINK_REPARSE_TAGS


def windows_reserved_name(name: str) -> bool:
    """CON·PRN·AUX·NUL·COM1-9·LPT1-9(확장자 포함, 대소문자 무시)와 끝 공백·마침표."""
    if name != name.rstrip(" ."):
        return True
    stem = name.split(".", 1)[0].strip().upper()
    return stem in WINDOWS_RESERVED


def real(p: str) -> str:
    return os.path.normpath(os.path.realpath(p))


def is_under(child: str, parent: str) -> bool:
    c, pr = _cmp(child), _cmp(parent).rstrip(os.sep)
    return c == pr or c.startswith(pr + os.sep)


def _real_parent(p: str) -> str:
    """마지막 요소는 풀지 않고(링크 자체를 대상으로) 상위 폴더만 realpath."""
    return os.path.join(real(os.path.dirname(p)), os.path.basename(p))
