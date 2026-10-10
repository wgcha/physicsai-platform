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
from typing import Any

from .config import PATH_META_CHARS
from .errors import DomainError, StepFailure

MAX_PATH_LEN = 400
FILE_ATTRIBUTE_REPARSE_POINT = 0x400
IO_REPARSE_TAG_SYMLINK = 0xA000000C
IO_REPARSE_TAG_MOUNT_POINT = 0xA0000003  # junction
LINK_REPARSE_TAGS = frozenset({IO_REPARSE_TAG_SYMLINK, IO_REPARSE_TAG_MOUNT_POINT})
BACKUP_DIR = "_backup"
# Study 폴더 직계의 플랫폼 산출 폴더(계약 §15.1). 데이터셋 입력으로 쓰거나 수집하지 않는다.
STUDY_OUTPUT_DIRS = frozenset({"03_dataset", "03_package", "03_model", "04_params", "04_predict", "logs", BACKUP_DIR})
# phase2 §13.4(B23 확장): 2차 산출 폴더. ③-1은 01_train/results·02_import·02_curated/*/CURATED_DATA 하위를 허용한다.
STUDY_OUTPUT_DIRS_2 = frozenset({
    "01_train/extract", "01_train/doe", "01_train/tpl", "01_train/radioss_assem", "02_preview", "05_opt",
})
ALL_OUTPUT_DIRS = tuple(sorted(STUDY_OUTPUT_DIRS | STUDY_OUTPUT_DIRS_2))
PLATFORM_DIR = "_platform"  # <ai_root>/_platform (phase2 §13.2) — 사용자 입력 경로로 지정 불가
_PROTECTED_ROOTS: list[str] = []


def register_protected_roots(roots: Iterable[str]) -> None:
    """쓰기 금지 루트(SPDM) 등록. 쓰기 헬퍼가 이 하위 경로를 받으면 예외(phase2 §13.3)."""
    _PROTECTED_ROOTS[:] = [os.path.normpath(r) for r in roots if r]


def assert_writable(path: str) -> None:
    if not _PROTECTED_ROOTS:
        return
    cands = {os.path.normpath(path)}
    try:
        cands.add(_real_parent(os.path.abspath(path)))
    except OSError:
        pass
    for r in _PROTECTED_ROOTS:
        rr = {r, real(r)}
        if any(is_under(c, x) for c in cands for x in rr):
            raise StepFailure("PATH_UNSAFE", f"SPDM 경로에는 쓸 수 없습니다: {path}")
WINDOWS_RESERVED = frozenset({"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))})


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


def allowed_roots(settings: Any, *, imports: bool) -> list[str]:
    """사용자 입력 경로의 허용 루트(§17.3). imports=True(외부 가져오기 용도)면 [ai_root, *allowed_import_roots]."""
    st = settings.storage
    return [st.ai_root, *st.allowed_import_roots] if imports else [st.ai_root]


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
    # 루트는 설정값(문자 그대로)과 realpath(매핑 드라이브·SUBST가 UNC·실경로로 풀린 형태) 두 형태로 비교한다.
    matched: str | None = None
    matched_real: str | None = None
    for r in roots:
        if not r:
            continue
        rr = real(r)
        for cand in (os.path.normpath(r), rr):
            if is_under(norm, cand):
                matched, matched_real = cand, rr
                break
        if matched:
            break
    if matched is None or matched_real is None:
        raise PathError("PATH_OUTSIDE_ROOT", "허용된 루트(AI 루트) 밖의 경로입니다", path=raw)
    rel = os.path.relpath(norm, matched)
    rel_parts = [] if rel == "." else rel.split(os.sep)
    if BACKUP_DIR in rel_parts:
        raise PathError("PATH_UNSAFE", "_backup 폴더 아래 경로는 쓸 수 없습니다", path=raw)
    if rel_parts and rel_parts[0] == PLATFORM_DIR:
        raise PathError("PATH_UNSAFE", "플랫폼 폴더(_platform)는 입력 경로로 쓸 수 없습니다", path=raw)
    cur = matched
    for part in rel_parts:
        cur = os.path.join(cur, part)
        if not os.path.lexists(cur):
            break
        if is_link_or_reparse(cur):
            raise PathError("PATH_UNSAFE", "심볼릭 링크·junction이 포함된 경로입니다", path=raw)
    # 입력도 루트와 같은 방식(realpath)으로 풀어 루트 안인지 다시 확인
    if os.path.lexists(norm) and not is_under(real(norm), matched_real):
        raise PathError("PATH_UNSAFE", "링크로 루트 밖을 가리키는 경로입니다", path=raw)
    if must_exist:
        if expect == "dir" and not os.path.isdir(norm):
            raise PathError("PATH_NOT_FOUND", "폴더가 없습니다", path=raw)
        if expect == "file" and not os.path.isfile(norm):
            raise PathError("PATH_NOT_FOUND", "파일이 없습니다", path=raw)
    return CheckedPath(norm, matched)


def check_dataset_input(path: str, ai_root: str) -> list[str]:
    """③-1 입력 제한(§15.1·§15.2): AI 루트 자체·Study 산출 폴더(03_*·04_*·logs·_backup) 안은 거부.

    Study 폴더 자체를 입력으로 주면 그 직계 산출 폴더를 수집에서 제외할 목록으로 돌려준다.
    """
    p, roots = real(path), (real(ai_root), os.path.normpath(ai_root))
    for root in roots:
        if not is_under(p, root) and not is_under(os.path.normpath(path), root):
            continue
        base = p if is_under(p, root) else os.path.normpath(path)
        rel = os.path.relpath(base, root)
        parts = [] if rel == "." else rel.split(os.sep)
        if not parts:
            raise PathError("PATH_UNSAFE", "AI 루트 전체는 데이터셋 입력으로 쓸 수 없습니다. h3d 폴더를 지정하세요", path=path)
        if len(parts) >= 2 and parts[1] in STUDY_OUTPUT_DIRS:
            raise PathError("PATH_UNSAFE", f"플랫폼 산출 폴더({parts[1]})는 데이터셋 입력으로 쓸 수 없습니다", path=path)
        if len(parts) >= 2 and (parts[1] in STUDY_OUTPUT_DIRS_2 or (len(parts) >= 3 and f"{parts[1]}/{parts[2]}" in STUDY_OUTPUT_DIRS_2)):
            what = parts[1] if parts[1] in STUDY_OUTPUT_DIRS_2 else f"{parts[1]}/{parts[2]}"
            raise PathError("PATH_UNSAFE", f"플랫폼 산출 폴더({what})는 입력으로 쓸 수 없습니다", path=path)
        if len(parts) == 1:
            return [os.path.join(path, *d.split("/")) for d in ALL_OUTPUT_DIRS]
        if len(parts) == 2 and parts[1] == "01_train":
            return [os.path.join(path, d.split("/")[1]) for d in ALL_OUTPUT_DIRS if d.startswith("01_train/")]
        return []
    return []


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


def _real_parent(p: str) -> str:
    """마지막 요소는 풀지 않고(링크 자체를 대상으로) 상위 폴더만 realpath."""
    return os.path.join(real(os.path.dirname(p)), os.path.basename(p))


def to_rel(study_root: str, abs_path: str) -> str:
    """Study 기준 상대경로. 양쪽을 같은 방식(realpath)으로 풀어 비교한다(매핑 드라이브·SUBST 대응)."""
    return os.path.relpath(_real_parent(abs_path), real(study_root)).replace(os.sep, "/")


def backup_stamp(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _unique(dest: str) -> str:
    if not os.path.lexists(dest):
        return dest
    stem, ext = os.path.splitext(dest)
    i = 1
    while os.path.lexists(f"{stem}~{i}{ext}"):
        i += 1
    return f"{stem}~{i}{ext}"


def backup_existing(study_root: str, abs_paths: Iterable[str], job_id: str, stamp: str | None = None) -> list[str]:
    """이미 있는 산출물을 `_backup`으로 이동. 이동한 원래 상대경로 목록을 돌려준다.

    Study 밖 경로는 존재 여부와 무관하게 항상 거부. 백업 대상이 이미 있으면 덮어쓰지 않고 `~N` 접미사.
    이동 실패 → StepFailure(OUTPUT_LOCKED). 삭제 호출 없음.
    """
    stamp = stamp or backup_stamp()
    moved: list[str] = []
    for p in abs_paths:
        assert_writable(p)
        rel = to_rel(study_root, p)
        if rel == "." or rel.startswith("..") or os.path.isabs(rel):
            raise StepFailure("INTERNAL_ERROR", f"Study 밖 산출물은 백업할 수 없습니다: {p}")
        if not os.path.lexists(p):
            continue
        dest = _unique(os.path.join(real(study_root), BACKUP_DIR, f"{stamp}_{job_id}", *rel.split("/")))
        try:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            os.replace(p, dest)
        except OSError as exc:
            raise StepFailure("OUTPUT_LOCKED", f"기존 산출물을 백업 폴더로 옮기지 못했습니다: {os.path.basename(p)} ({exc})")
        moved.append(rel)
    return moved


def display_path(ai_root: str | None, folder_name: str, rel: str | None = None) -> str | None:
    """탐색기에 붙여넣을 표시용 절대경로(B17). ai_root가 Windows 형식이면 '\\' 구분."""
    if not ai_root:
        return None
    parts = [folder_name, *[x for x in (rel or "").replace("\\", "/").split("/") if x]]
    win = len(ai_root) >= 2 and ai_root[1] == ":"
    sep = "\\" if win else "/"
    base = ai_root.replace("/", "\\") if win else ai_root.replace("\\", "/")
    return base.rstrip("\\/") + sep + sep.join(parts)
