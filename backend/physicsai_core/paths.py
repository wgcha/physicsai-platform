"""경로 검사(§17.3), Study 경로, 백업 이동(§8.3). 링크 판정·realpath 비교 원시 함수는 path_links(여기서 재노출).

사용자 산출물은 삭제하지 않는다. 기존 산출물은 `_backup/<UTC>_<job_id>/<상대경로>`로 os.replace 이동한다.
300줄 분할(R-B): 경로 요소·파일 이름 안전 검사는 `path_names`(여기서 재노출).
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import DomainError, StepFailure
from .path_links import (  # noqa: F401 - 기존 경로 재노출(paths.is_link_or_reparse 등)
    FILE_ATTRIBUTE_REPARSE_POINT,
    IO_REPARSE_TAG_MOUNT_POINT,
    IO_REPARSE_TAG_SYMLINK,
    LINK_REPARSE_TAGS,
    WINDOWS_RESERVED,
    _cmp,
    _is_windows,
    _real_parent,
    is_link_or_reparse,
    is_under,
    real,
    windows_reserved_name,
)
from .path_names import (  # noqa: F401 - 기존 경로 재노출
    FILE_NAME_EXTRA_CHARS, unsafe_reason, path_component_problem, name_unsafe_chars, file_name_problem_message,
    file_safety_problem,
)

MAX_PATH_LEN = 400
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


def assert_writable(path: str, *, allow_final_link: bool = False) -> None:
    """쓰기 대상 검사: 마지막 요소가 링크(symlink·junction)면 거부(링크를 따라 다른 곳에 쓰지 않는다), SPDM(보호 루트) 하위 거부.

    `allow_final_link=True`는 링크 자체를 옮기는 경우(`backup_existing`의 os.replace는 링크를 따라가지 않음)만.
    """
    if not allow_final_link and is_link_or_reparse(path):
        raise StepFailure("PATH_UNSAFE", f"링크에는 쓸 수 없습니다: {path}")
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


class PathError(DomainError):
    status = 422


@dataclass(frozen=True)
class CheckedPath:
    path: str  # 정규화된 절대경로
    root: str  # 일치한 허용 루트


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
    comp = path_component_problem(raw)
    if comp:
        raise PathError("PATH_UNSAFE", f"경로 요소에 {comp}을 쓸 수 없습니다", path=raw)
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
    # 대소문자 무시(phase3 D3-34): Windows에서 `_BACKUP`·`_Platform`으로 우회하지 못하게 한다.
    folded = [x.casefold() for x in rel_parts]
    if BACKUP_DIR in folded:
        raise PathError("PATH_UNSAFE", "_backup 폴더 아래 경로는 쓸 수 없습니다", path=raw)
    if folded and folded[0] == PLATFORM_DIR:
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
        parts = [] if rel == "." else [x.casefold() for x in rel.split(os.sep)]  # 대소문자 무시(D3-34)
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
        assert_writable(p, allow_final_link=True)
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
