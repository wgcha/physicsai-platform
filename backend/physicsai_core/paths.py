"""경로 검사(§17.3), Study 경로, 백업 이동(§8.3).

사용자 산출물은 삭제하지 않는다. 기존 산출물은 `_backup/<UTC>_<job_id>/<상대경로>`로 os.replace 이동한다.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .config import PATH_META_CHARS
from .errors import DomainError, StepFailure

MAX_PATH_LEN = 400
FILE_ATTRIBUTE_REPARSE_POINT = 0x400
BACKUP_DIR = "_backup"


class PathError(DomainError):
    status = 422


@dataclass(frozen=True)
class CheckedPath:
    path: str  # 정규화된 절대경로
    root: str  # 일치한 허용 루트


def _is_windows() -> bool:
    return os.name == "nt"


def _cmp(p: str) -> str:
    return os.path.normcase(p) if _is_windows() else p


def is_link_or_reparse(p: str) -> bool:
    try:
        st = os.lstat(p)
    except OSError:
        return False
    if stat.S_ISLNK(st.st_mode):
        return True
    attrs = getattr(st, "st_file_attributes", 0)
    return bool(attrs & FILE_ATTRIBUTE_REPARSE_POINT)


def unsafe_reason(text: str) -> str | None:
    if any(ord(c) < 0x20 or ord(c) == 0x7F for c in text):
        return "제어문자"
    if any(c.isspace() for c in text):
        return "공백"
    bad = PATH_META_CHARS.intersection(text)
    if bad:
        return "cmd 메타문자(" + " ".join(sorted(bad)) + ")"
    return None


def _is_abs(raw: str) -> bool:
    if _is_windows():
        return os.path.isabs(raw) and len(raw) >= 3 and raw[1] == ":"
    return raw.startswith("/")


def check_user_path(
    raw: object,
    roots: Sequence[str],
    *,
    expect: str = "dir",
    must_exist: bool = True,
) -> CheckedPath:
    """사용자 지정 경로 검사. 위반 시 PathError(PATH_OUTSIDE_ROOT | PATH_UNSAFE | PATH_NOT_FOUND)."""
    if not isinstance(raw, str) or not raw.strip():
        raise PathError("PATH_UNSAFE", "경로가 비어 있습니다")
    if len(raw) > MAX_PATH_LEN:
        raise PathError("PATH_UNSAFE", f"경로가 너무 깁니다(최대 {MAX_PATH_LEN}자)")
    reason = unsafe_reason(raw)
    if reason:
        raise PathError("PATH_UNSAFE", f"경로에 {reason}를 쓸 수 없습니다", path=raw)
    if not _is_abs(raw):
        raise PathError("PATH_UNSAFE", "절대경로를 입력하세요", path=raw)
    parts = raw.replace("\\", "/").split("/")
    if ".." in parts or "." in parts[1:]:
        raise PathError("PATH_UNSAFE", "경로에 '..' 또는 '.'을 쓸 수 없습니다", path=raw)
    norm = os.path.normpath(raw)
    matched: str | None = None
    for r in roots:
        if not r:
            continue
        rn = os.path.normpath(os.path.realpath(r))
        if _cmp(norm) == _cmp(rn) or _cmp(norm).startswith(_cmp(rn).rstrip(os.sep) + os.sep):
            matched = rn
            break
    if matched is None:
        raise PathError("PATH_OUTSIDE_ROOT", "허용된 루트(AI 루트) 밖의 경로입니다", path=raw)
    rel = os.path.relpath(norm, matched)
    rel_parts = [] if rel == "." else rel.split(os.sep)
    if BACKUP_DIR in rel_parts:
        raise PathError("PATH_UNSAFE", "_backup 폴더 아래 경로는 쓸 수 없습니다", path=raw)
    cur = matched
    for part in rel_parts:
        cur = os.path.join(cur, part)
        if not os.path.lexists(cur):
            break
        if is_link_or_reparse(cur):
            raise PathError("PATH_UNSAFE", "심볼릭 링크·reparse point가 포함된 경로입니다", path=raw)
    real = os.path.realpath(norm)
    if os.path.lexists(norm) and _cmp(os.path.normpath(real)) != _cmp(norm):
        raise PathError("PATH_UNSAFE", "링크로 해석되는 경로입니다", path=raw)
    if must_exist:
        if expect == "dir" and not os.path.isdir(norm):
            raise PathError("PATH_NOT_FOUND", "폴더가 없습니다", path=raw)
        if expect == "file" and not os.path.isfile(norm):
            raise PathError("PATH_NOT_FOUND", "파일이 없습니다", path=raw)
    return CheckedPath(norm, matched)


def file_safety_problem(path: str, base: str) -> str | None:
    """입력 트리 안 파일 1개의 안전성(공백·메타문자·링크). 문제 없으면 None."""
    rel = os.path.relpath(path, base)
    reason = unsafe_reason(path)
    if reason:
        return reason
    cur = base
    for part in rel.split(os.sep):
        cur = os.path.join(cur, part)
        if is_link_or_reparse(cur):
            return "링크"
    return None


# ---------------------------------------------------------------------------
# Study 내부 경로
# ---------------------------------------------------------------------------


def study_dir(ai_root: str, folder_name: str) -> str:
    return os.path.join(os.path.normpath(ai_root), folder_name)


def resolve_in_study(study_root: str, rel: str) -> str:
    """Study 폴더 기준 상대경로를 절대경로로. 탈출이면 DomainError."""
    if rel is None:
        raise DomainError("NOT_FOUND", "경로가 없습니다", status=404)
    base = Path(study_root).resolve()
    target = (base / rel.replace("\\", "/")).resolve()
    if target != base and base not in target.parents:
        raise DomainError("PATH_OUTSIDE_ROOT", "Study 폴더 밖 경로입니다", status=422)
    return str(target)


def to_rel(study_root: str, abs_path: str) -> str:
    return os.path.relpath(abs_path, study_root).replace(os.sep, "/")


def backup_stamp(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def backup_existing(study_root: str, abs_paths: Iterable[str], job_id: str, stamp: str | None = None) -> list[str]:
    """이미 있는 산출물을 `_backup`으로 이동. 이동한 원래 상대경로 목록을 돌려준다.

    이동 실패 → StepFailure(OUTPUT_LOCKED). 삭제 호출 없음.
    """
    stamp = stamp or backup_stamp()
    moved: list[str] = []
    for p in abs_paths:
        if not os.path.lexists(p):
            continue
        rel = to_rel(study_root, p)
        if rel.startswith(".."):
            raise StepFailure("INTERNAL_ERROR", f"Study 밖 산출물은 백업할 수 없습니다: {p}")
        dest = os.path.join(study_root, BACKUP_DIR, f"{stamp}_{job_id}", *rel.split("/"))
        try:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            os.replace(p, dest)
        except OSError as exc:
            raise StepFailure("OUTPUT_LOCKED", f"기존 산출물을 백업 폴더로 옮기지 못했습니다: {os.path.basename(p)} ({exc})")
        moved.append(rel)
    return moved
