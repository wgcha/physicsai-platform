"""경로 문자열 규칙(순수 문자열, 파일 시스템을 보지 않는다)."""

from __future__ import annotations

import re

_WIN_ABS = re.compile(r"^[A-Za-z]:[\\/]")


def fwd(path: str) -> str:
    """`_fwd` placeholder용 '/' 구분 경로."""
    return path.replace("\\", "/")


def is_abs_path_str(p: str) -> bool:
    return bool(_WIN_ABS.match(p)) or p.startswith("/")
