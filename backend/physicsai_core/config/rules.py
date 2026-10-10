"""설정 검증 공용 규칙: 경로 문자열 규칙(절대경로·메타 문자·겹침)과 정규식 컴파일 검사."""

from __future__ import annotations

import os
import re

from .schema import ConfigIssue

PATH_META_CHARS = set('&|<>^%!"')
_WIN_ABS = re.compile(r"^[A-Za-z]:[\\/]")


def is_abs_path_str(p: str) -> bool:
    return bool(_WIN_ABS.match(p)) or p.startswith("/")


def has_unsafe_chars(p: str) -> bool:
    return bool(re.search(r"[\s\x00-\x1f\x7f]", p)) or bool(PATH_META_CHARS.intersection(p))


def _norm_for_compare(p: str) -> str:
    n = os.path.normpath(p.replace("\\", "/")).replace("\\", "/")
    return n.lower() if (os.name == "nt" or _WIN_ABS.match(p)) else n


def paths_overlap(a: str, b: str) -> bool:
    """같거나 한쪽이 다른 쪽 안에 있으면 True."""
    na, nb = _norm_for_compare(a).rstrip("/"), _norm_for_compare(b).rstrip("/")
    return na == nb or na.startswith(nb + "/") or nb.startswith(na + "/")


def _compile(key: str, pattern: str, issues: list[ConfigIssue], required_groups: tuple[str, ...] = ()) -> None:
    try:
        rx = re.compile(pattern)
    except re.error as exc:
        issues.append(ConfigIssue(key, f"정규식 컴파일 실패: {exc}"))
        return
    for g in required_groups:
        if g not in rx.groupindex:
            issues.append(ConfigIssue(key, f"정규식에 필수 그룹 '{g}'이 없습니다"))
