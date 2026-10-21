"""설정 스키마 — 업로드 절 `upload`·보고서 절 `report`(upload-report.md §6.1·§9.5). 기본값은 이 파일 한 곳.

`storage.upload_root`(AI 루트 기준 상대 또는 AI 루트 하위 절대, null = 업로드 끔)는 StorageCfg에 있다. 이 파일은
업로드 상한·낡음 시간·패턴(`upload`)과 보고서 상한(`report`), 그리고 두 절·업로드 루트의 검증을 맡는다.
보고서 구현(별도 브랜치)은 `ReportCfg`를 그대로 읽는다 — 설정 클래스는 업로드 브랜치 소유(계약 §10).
"""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING

from pydantic import Field

from ._model import _M

if TYPE_CHECKING:
    from .schema import ConfigIssue, Settings

# purpose별 모양(§3.1). file = 파일 1개, dir = 폴더, dir_or_file = 폴더 또는 파일 1개.
PURPOSE_MODES: dict[str, str] = {
    "CAD_FILE": "file",
    "RADIOSS_ASSEM": "dir",
    "RESULT_FOLDER": "dir",
    "CURATION_INPUT": "dir",
    "DATASET_INPUT": "dir",
    "MODEL_FOLDER": "dir",
    "PARAM_SET": "dir",
    "PREDICT_INPUT": "dir_or_file",
    "DISCOVER": "dir",
    "FEM_ASSEMBLY": "dir",
}
UPLOAD_PURPOSES = tuple(PURPOSE_MODES)

# 항상 거부(설정으로 풀 수 없음, §3.1): pickle(.pscfg)·학습 데이터(.psdata)·실행/스크립트·서버 임시 이름(.part)
ALWAYS_DENIED: tuple[str, ...] = (
    "*.pscfg", "*.psdata",
    "*.exe", "*.dll", "*.pyd", "*.so", "*.bat", "*.cmd", "*.ps1", "*.vbs", "*.js", "*.py", "*.lnk", "*.scr", "*.msi",
    "*.part",
)
RESERVED_FIRST = ("_backup", "_platform")  # 업로드 루트·rel 첫 성분으로 쓸 수 없는 이름(대소문자 무시)
PATTERN_MAX_LEN = 64
_PATTERN_BAD = re.compile(r"[\x00-\x1f\x7f/\\\s]")


def pattern_problem(p: object) -> str | None:
    """glob 패턴 1개의 형식 문제(파일 이름에만 적용 — 경로 구분자·공백·제어문자 불가). 문제 없으면 None."""
    if not isinstance(p, str) or not p.strip():
        return "빈 패턴"
    if len(p) > PATTERN_MAX_LEN:
        return f"{PATTERN_MAX_LEN}자 초과"
    if _PATTERN_BAD.search(p):
        return "경로 구분자·공백·제어문자 불가"
    return None


def is_always_denied_pattern(p: str) -> bool:
    return p.strip().lower() in ALWAYS_DENIED


class UploadPurposeCfg(_M):
    patterns: list[str] = Field(default_factory=list)


class UploadCfg(_M):
    chunk_mb: int = 16                      # 1~64. 리버스 프록시 요청 크기 제한보다 작게(§6.5)
    max_file_bytes: int = 68719476736       # 64 GiB(h3d 30 GB급 수용)
    max_upload_bytes: int = 214748364800    # 200 GiB(학습 결과 폴더)
    max_files: int = 20000
    max_concurrent_per_user: int = 2
    min_free_gb: float = 50                 # 업로드 뒤에도 AI 루트 드라이브에 남길 여유
    stale_hours: int = 72
    extra_patterns: list[str] = Field(default_factory=list)  # 모든 purpose에 더할 glob(항상 거부 목록은 못 풂)
    purposes: dict[str, UploadPurposeCfg] = Field(default_factory=dict)  # purpose별 patterns 덮어쓰기(생략 = §3.1 기본)

    @property
    def chunk_bytes(self) -> int:
        return int(self.chunk_mb) * 1024 * 1024


class ReportCfg(_M):
    max_bytes: int = 31457280      # 30 MiB
    max_images: int = 24
    max_image_bytes: int = 2097152  # 2 MiB
    max_table_rows: int = 500


def upload_root_problem(ai_root: str, upload_root: str | None, spdm_roots: list[str], inbox_dir: str) -> str | None:
    """`storage.upload_root` 검사(§6.1 CONFIG_INVALID). 문제 없으면 None. null(끔)은 정상."""
    from .rules import has_unsafe_chars, is_abs_path_str, paths_overlap

    if upload_root is None:
        return None
    if not isinstance(upload_root, str) or not upload_root.strip():
        return "비어 있을 수 없습니다(끄려면 null)"
    if has_unsafe_chars(upload_root):
        return "공백·제어문자·cmd 메타문자를 쓸 수 없습니다"
    raw = upload_root.replace("\\", "/")
    if is_abs_path_str(upload_root):
        ci = os.name == "nt" or bool(re.match(r"^[A-Za-z]:", ai_root or ""))  # Windows 경로는 대소문자 무시
        fold = (lambda x: x.lower()) if ci else (lambda x: x)
        base = os.path.normpath((ai_root or "").replace("\\", "/")).replace("\\", "/").rstrip("/")
        norm = os.path.normpath(raw).replace("\\", "/").rstrip("/")
        if not ai_root or not fold(norm).startswith(fold(base) + "/"):
            return "AI 루트 하위 폴더여야 합니다(AI 루트 밖·AI 루트 자체 불가)"
        parts = norm[len(base) + 1:].split("/")
        abs_path = upload_root
    else:
        if raw.startswith("/"):
            return "AI 루트 기준 상대 경로이거나 AI 루트 하위 절대 경로여야 합니다"
        parts = raw.split("/")
        abs_path = os.path.normpath(os.path.join(ai_root, *parts)) if ai_root else raw
    if any(x in ("", ".", "..") for x in parts):
        return "'..'·'.'·빈 성분을 쓸 수 없습니다"
    if any(":" in x or x[-1:] in (".", " ") for x in parts):
        return "':'·끝 마침표·끝 공백을 쓸 수 없습니다"
    if parts[0].casefold() in RESERVED_FIRST or parts[0].startswith("."):
        return "_backup·_platform·'.'으로 시작하는 이름은 쓸 수 없습니다"
    for sp in spdm_roots:
        if sp and paths_overlap(abs_path, sp):
            return f"SPDM 루트와 겹칩니다: {sp}"
    inbox_abs = os.path.normpath(os.path.join(ai_root, *inbox_dir.replace("\\", "/").split("/"))) if ai_root and inbox_dir else ""
    if inbox_abs and paths_overlap(abs_path, inbox_abs):
        return "받은 파일 폴더(storage.inbox_dir)와 겹칩니다"
    return None


def effective_patterns_dropped(s: Settings) -> list[tuple[str, str]]:
    """설정의 extra_patterns·purposes 패턴 중 항상 거부 패턴 → [(키, 패턴)]. 경고 후 무시된다(§6.1)."""
    out: list[tuple[str, str]] = []
    for p in s.upload.extra_patterns:
        if isinstance(p, str) and is_always_denied_pattern(p):
            out.append(("upload.extra_patterns", p))
    for name, pc in s.upload.purposes.items():
        for p in pc.patterns:
            if isinstance(p, str) and is_always_denied_pattern(p):
                out.append((f"upload.purposes.{name}.patterns", p))
    return out


def validate_upload(s: Settings, issues: list[ConfigIssue]) -> None:
    from .schema import ConfigIssue as issue

    u, r = s.upload, s.report
    for k, lo, hi in (("chunk_mb", 1, 64), ("max_files", 1, 1000000), ("max_concurrent_per_user", 1, 20),
                      ("stale_hours", 1, 8760), ("max_file_bytes", 1, 1 << 50), ("max_upload_bytes", 1, 1 << 52)):
        if not lo <= getattr(u, k) <= hi:
            issues.append(issue(f"upload.{k}", f"{lo}~{hi}"))
    if not 0 <= u.min_free_gb <= 1000000:
        issues.append(issue("upload.min_free_gb", "0~1000000"))
    if u.max_upload_bytes < u.max_file_bytes:
        issues.append(issue("upload.max_upload_bytes", "max_file_bytes 이상이어야 합니다"))
    for i, p in enumerate(u.extra_patterns):
        why = pattern_problem(p)
        if why:
            issues.append(issue(f"upload.extra_patterns[{i}]", why))
    for name, pc in u.purposes.items():
        if name not in UPLOAD_PURPOSES:
            issues.append(issue(f"upload.purposes.{name}", f"알 수 없는 purpose입니다({' | '.join(UPLOAD_PURPOSES)})"))
        for i, p in enumerate(pc.patterns):
            why = pattern_problem(p)
            if why:
                issues.append(issue(f"upload.purposes.{name}.patterns[{i}]", why))
    why = upload_root_problem(s.storage.ai_root, s.storage.upload_root, s.storage.spdm_roots, s.storage.inbox_dir)
    if why:
        issues.append(issue("storage.upload_root", why))
    for k, lo, hi in (("max_bytes", 1 << 20, 1 << 30), ("max_images", 0, 200), ("max_image_bytes", 1024, 1 << 25),
                      ("max_table_rows", 1, 100000)):
        if not lo <= getattr(r, k) <= hi:
            issues.append(issue(f"report.{k}", f"{lo}~{hi}"))
