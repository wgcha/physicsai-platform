"""경로 요소·파일 이름 안전 검사(§17.3, phase3 D3-35 외부 명령 인자 파일 이름) — paths에서 재노출."""

from __future__ import annotations

import os
import unicodedata

from .config import PATH_META_CHARS
from .path_links import (
    _is_windows,
    is_link_or_reparse,
)

# 외부 명령 인자로 들어가는 파일 이름(준비된 입력·파라미터 세트·데이터셋 h3d)의 추가 금지 문자(phase3 D3-35).
# cmd 메타문자(PATH_META_CHARS)에 더해 .bat 재해석 구분자(; , =)·괄호·작은따옴표.
FILE_NAME_EXTRA_CHARS = frozenset(";,=()'")


def unsafe_reason(text: str) -> str | None:
    if any(ord(c) < 0x20 or ord(c) == 0x7F for c in text):
        return "제어문자"
    if any(c.isspace() for c in text):
        return "공백"
    bad = PATH_META_CHARS.intersection(text)
    if bad:
        return "cmd 메타문자(" + " ".join(sorted(bad)) + ")"
    return None


def path_component_problem(raw: str, *, windows: bool | None = None) -> str | None:
    """경로 요소 검사(D3-50, 플랫폼 독립 문자열 검사). 문제 없으면 None.

    거부: 요소 안 `:`(NTFS 대체 데이터 스트림 `x::$INDEX_ALLOCATION`·드라이브 상대 `C:x`), 끝 마침표·공백
    (Windows가 `_platform.`·`_backup ` 을 `_platform`·`_backup`으로 열어 이름 비교를 우회). `windows`(기본: 현재 OS)면
    첫 요소의 드라이브 `X:`만 예외. 빈 요소·`.`·`..`는 다른 규칙이 본다.
    """
    win = _is_windows() if windows is None else windows
    for i, part in enumerate(raw.replace("\\", "/").split("/")):
        if not part or part in (".", ".."):
            continue
        if i == 0 and win and len(part) == 2 and part[1] == ":" and part[0].isascii() and part[0].isalpha():
            continue
        if ":" in part:
            return "':'(대체 데이터 스트림·드라이브 상대 경로)"
        if part[-1] in " .":
            return "끝 마침표·공백"
    return None


def name_unsafe_chars(name: str) -> str | None:
    """파일·폴더 이름 1개에 쓸 수 없는 문자 표시(phase3 D3-35). 문제 없으면 None.

    거부: 제어·서식 문자, 공백류(전각·줄바꿈 없는 공백 포함), cmd 메타문자 `& | < > ^ % ! "`, `; , = ( ) '`.
    영숫자·`_`·`-`·`.`·한글 등 그 밖의 글자는 허용.
    """
    bad: set[str] = set()
    for c in name:
        cat = unicodedata.category(c)
        if c.isspace() or cat.startswith("Z"):
            bad.add("공백")
        elif cat.startswith("C"):
            bad.add("제어문자")
        elif c in PATH_META_CHARS or c in FILE_NAME_EXTRA_CHARS:
            bad.add(c)
    if not bad:
        return None
    words = sorted(x for x in bad if len(x) > 1)
    return " ".join([*words, *sorted(x for x in bad if len(x) == 1)])


def file_name_problem_message(why: str) -> str:
    """`file_safety_problem`·`name_unsafe_chars` 결과의 사용자 문구."""
    return "링크 파일은 쓸 수 없습니다" if why == "링크" else f"파일 이름에 쓸 수 없는 문자({why})가 있습니다"


def file_safety_problem(path: str, base: str) -> str | None:
    """입력 트리 안 파일 1개의 안전성. 문제 없으면 None, 있으면 "링크" 또는 문제 문자 표시.

    `base`(검사를 마친 사용자 경로)는 경로 규칙(`unsafe_reason`), base 아래 이름(폴더·파일)은 더 엄격한
    `name_unsafe_chars`로 본다 — 이 이름들은 복사·외부 명령 인자로 쓰인다(phase3 D3-35).
    """
    rel = os.path.relpath(path, base)
    for part in rel.split(os.sep):
        reason = name_unsafe_chars(part) or path_component_problem(part, windows=False)
        if reason:
            return reason
    reason = unsafe_reason(path)
    if reason:
        return reason
    cur = base
    for part in rel.split(os.sep):
        cur = os.path.join(cur, part)
        if is_link_or_reparse(cur):
            return "링크"
    return None
