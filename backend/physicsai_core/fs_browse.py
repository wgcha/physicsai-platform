"""서버 경로 탐색(phase3 §12 S7, D3-46): 허용 루트 목록과 폴더 한 단계 목록.

허용 루트 = `allowed_roots(imports=True)`(AI 루트 + allowed_import_roots). 받은 파일 폴더(`<ai_root>/<inbox_dir>`)는 AI 루트 하위라
별도 루트가 아니라 바로가기다. 파일 내용은 읽지 않는다(이름·종류·크기·mtime만). 링크·junction·숨김/시스템 항목과
`_backup`·`_platform`(대소문자 무시)은 목록에서 뺀다.
"""

from __future__ import annotations

import os
import re
import stat
from datetime import datetime, timezone
from typing import Any

from .errors import DomainError
from .paths import BACKUP_DIR, PLATFORM_DIR, PathError, allowed_roots, check_user_path
from .path_links import _cmp, is_link_or_reparse, real
from .uploads import PART_SUFFIX, upload_root_path

MAX_ENTRIES = 500
MAX_EXTS = 20
_EXT_RE = re.compile(r"^\.[A-Za-z0-9_]{1,16}$")
_HIDDEN_NAMES = frozenset({BACKUP_DIR, PLATFORM_DIR})
FILE_ATTRIBUTE_HIDDEN = 0x2
FILE_ATTRIBUTE_SYSTEM = 0x4


def inbox_path(settings: Any) -> str | None:
    """받은 파일 폴더 절대경로(설정값 기준). AI 루트가 비면 None."""
    st = settings.storage
    if not st.ai_root or not st.inbox_dir:
        return None
    return os.path.normpath(os.path.join(st.ai_root, *st.inbox_dir.replace("\\", "/").split("/")))


def upload_path(settings: Any) -> str | None:
    """업로드 폴더 절대경로(`<ai_root>/<storage.upload_root>`). 설정이 null이면 None. 위치 규칙의 단일 출처는 `uploads.upload_root_path`."""
    return upload_root_path(settings) if settings.storage.ai_root else None


def roots(settings: Any, *, include_spdm: bool = False) -> list[dict[str, str]]:
    """탐색 시작점: AI 루트, 받은 파일 폴더(있고 경로 규칙을 통과할 때만), 추가 허용 폴더.
    include_spdm(phase3 §21.3.8 S16 조립 원본 직접 지정)이면 `storage.spdm_roots`도 `SPDM <i>(읽기 전용)`로 덧붙인다."""
    st = settings.storage
    out: list[dict[str, str]] = []
    if st.ai_root:
        out.append({"key": "ai_root", "label": "AI 루트", "path": os.path.normpath(st.ai_root)})
    inbox = inbox_path(settings)
    if inbox and os.path.isdir(inbox):
        try:
            out.append({"key": "inbox", "label": "받은 파일(공유 폴더)", "path": check_user_path(inbox, [st.ai_root]).path})
        except PathError:
            pass  # 링크·금지 문자 등 — 바로가기를 보이지 않는다
    up = upload_path(settings)
    if up and os.path.isdir(up):  # upload-report.md §6.4: 내가 올린 파일(AI 루트 하위 — inbox와 같은 바로가기)
        try:
            out.append({"key": "upload", "label": "내가 올린 파일", "path": check_user_path(up, [st.ai_root]).path})
        except PathError:
            pass
    for i, r in enumerate(st.allowed_import_roots):
        if r:
            out.append({"key": f"import_{i}", "label": "추가 허용 폴더", "path": os.path.normpath(r)})
    if include_spdm:
        for i, r in enumerate(st.spdm_roots, start=1):
            if r:
                out.append({"key": f"spdm_{i}", "label": f"SPDM {i}(읽기 전용)", "path": os.path.normpath(r)})
    return out


def _checked_dir(settings: Any, raw: object) -> str:
    """허용 루트(AI·가져오기) 아래면 그 규칙, 밖이고 SPDM 루트 아래면 SPDM 규칙(읽기 전용 목록만, phase3 §21.3.8)."""
    try:
        return check_user_path(raw, allowed_roots(settings, imports=True), expect="dir").path
    except PathError as exc:
        if exc.code != "PATH_OUTSIDE_ROOT" or not settings.storage.spdm_roots:
            raise
    return check_spdm_dir(raw, settings.storage.spdm_roots)


def check_spdm_dir(raw: object, roots: Any) -> str:
    """SPDM 루트 아래 폴더 검사(읽기 전용 — §13.3 규칙 `spdm.check_spdm_path`). 단계 패키지가 공용 경로로 쓰게 둔 얇은 포장."""
    from .stage2_curation import spdm

    return spdm.check_spdm_path(raw, roots)


def spdm_configured(settings: Any) -> bool:
    return bool(settings.storage.spdm_roots)


def check_spdm_dir_for(settings: Any, raw: object) -> str:
    """설정의 SPDM 루트로 `check_spdm_dir`(phase3 §21.3.3 조립 원본 직접 지정)."""
    return check_spdm_dir(raw, settings.storage.spdm_roots)


def parse_exts(raw: str | None) -> frozenset[str] | None:
    """`.rad,.inc` → {".rad", ".inc"}(소문자). 비면 None(파일 전부)."""
    if raw is None or not raw.strip():
        return None
    items = [x.strip() for x in raw.split(",") if x.strip()]
    if len(items) > MAX_EXTS or any(not _EXT_RE.match(x) for x in items):
        raise DomainError("INVALID_PARAMS", "확장자 필터는 '.rad,.inc'처럼 점으로 시작하는 짧은 확장자 목록이어야 합니다", status=422)
    return frozenset(x.lower() for x in items)


def _is_unc(raw: str) -> bool:
    return raw.startswith(("\\\\", "//"))


def _hidden(entry: os.DirEntry, st: os.stat_result) -> bool:
    if entry.name.startswith(".") or entry.name.casefold() in _HIDDEN_NAMES:
        return True
    return bool(getattr(st, "st_file_attributes", 0) & (FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM))


def _parent(path: str, settings: Any) -> str | None:
    """허용 루트 자체면 None(루트 위로 못 감)."""
    for r in [*allowed_roots(settings, imports=True), *settings.storage.spdm_roots]:
        if r and _cmp(path) in {_cmp(os.path.normpath(r)), _cmp(real(r))}:
            return None
    up = os.path.dirname(path)
    return None if up == path else up


def list_dir(settings: Any, raw: object, exts: frozenset[str] | None = None) -> dict[str, Any]:
    """폴더 한 단계 목록. 폴더 먼저·이름순(대소문자 무시), 최대 MAX_ENTRIES개. 위반 시 PathError/DomainError."""
    if isinstance(raw, str) and _is_unc(raw):
        raise PathError("PATH_UNSAFE", "네트워크(UNC) 경로는 쓸 수 없습니다. 서버의 드라이브 경로를 쓰세요", path=raw)
    cp_path = _checked_dir(settings, raw)
    rows: list[dict[str, Any]] = []
    try:
        with os.scandir(cp_path) as it:
            for e in it:
                try:
                    if is_link_or_reparse(e.path):
                        continue
                    st = e.stat(follow_symlinks=False)
                except OSError:
                    continue
                if _hidden(e, st):
                    continue
                if stat.S_ISDIR(st.st_mode):
                    kind = "dir"
                elif stat.S_ISREG(st.st_mode):
                    if e.name.lower().endswith(PART_SUFFIX):  # 업로드 진행 중 임시 파일(upload-report.md §6.4)
                        continue
                    if exts is not None and os.path.splitext(e.name)[1].lower() not in exts:
                        continue
                    kind = "file"
                else:
                    continue
                row: dict[str, Any] = {"name": e.name, "type": kind,
                                       "mtime": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc)}
                if kind == "file":
                    row["size"] = st.st_size
                rows.append(row)
    except PermissionError:
        raise DomainError("PATH_UNREADABLE", "폴더를 읽을 권한이 없습니다", status=422, path=cp_path)
    except OSError as exc:
        raise DomainError("PATH_UNREADABLE", f"폴더를 읽지 못했습니다({exc.__class__.__name__})", status=422, path=cp_path)
    rows.sort(key=lambda r: (r["type"] != "dir", r["name"].casefold(), r["name"]))
    return {"path": cp_path, "parent": _parent(cp_path, settings), "entries": rows[:MAX_ENTRIES],
            "truncated": len(rows) > MAX_ENTRIES}
