"""설정 스키마 — ④ 컨투어 캡처 절 `capture`(phase3 §15 S10)와 캡처 TCL 자원 경로 결정·검증."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import Field

from ._model import _M

if TYPE_CHECKING:
    from .schema import ConfigIssue, Settings

CAPTURE_VIEWS = ("iso", "front", "back", "top", "bottom", "left", "right")
CAPTURE_VIDEO_EXTS = ("mp4", "avi", "gif")
# 표시 설정 문자열 금지 문자(stage4_predict.contour_capture._TEXT_FORBIDDEN과 같은 규칙 — `|`는 hwc 명령 구분자, D3-53)
DEFAULT_FIELD_FORBIDDEN = frozenset('"{}[]$\\;|')
# 저장소 리소스(사용자 제공 이슈 #2 TCL). resources.contour_capture_tcl이 비면 이 파일을 쓴다(repo 설치·개발).
CAPTURE_TCL_REPO_REL = ("resources", "hyperview", "contour_capture.tcl")


class CaptureCfg(_M):
    enabled: bool = True  # false = 기능 끔(altair.hw_exe_path가 없어도 꺼짐)
    views: list[str] = Field(default_factory=lambda: ["iso", "front", "top", "right"])
    video: bool = True  # 방향마다 애니메이션 동영상도 저장
    video_ext: str = "mp4"  # mp4 | avi | gif
    use_last: bool = True  # 마지막 프레임 기준 캡처(false = 첫 프레임)
    default_field: str = "CornerStress"  # 템플릿 표시 설정·응답 정의가 없을 때의 결과 필드(예측 h3d 응력, 성분 없음 — D3-53)
    timeout_s: float | None = 1800  # 캡처 1회 상한(초). 넘으면 프로세스 종료 + 경고. null = 상한 없음
    max_video_bytes: int = 209715200  # 동영상 1개 등록·제공 상한(200 MiB)


def repo_capture_tcl() -> str:
    """저장소 `resources/hyperview/contour_capture.tcl`('/' 표기). 패키지 위치에서 위로 찾고 없으면 ''(wheel 설치)."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        cand = parent.joinpath(*CAPTURE_TCL_REPO_REL)
        if cand.is_file():
            return str(cand).replace("\\", "/")
    return ""


def effective_capture_tcl(s: Settings) -> str:
    """캡처 TCL 원본 경로: resources.contour_capture_tcl, 비었으면 저장소 리소스."""
    return s.resources.contour_capture_tcl or repo_capture_tcl()


def capture_missing(s: Settings) -> list[str]:
    """기능 `contour_capture`에 빠진 설정(템플릿·실행 파일 외): capture.enabled, 캡처 TCL 파일."""
    out = []
    if not s.capture.enabled:
        out.append("capture.enabled")
    tcl = effective_capture_tcl(s)
    if not tcl or not os.path.isfile(tcl):
        out.append("resources.contour_capture_tcl")
    return out


def validate_capture(s: Settings, issues: list[ConfigIssue]) -> None:
    from .rules import has_unsafe_chars, is_abs_path_str  # rules → schema → 이 모듈 순환을 피하는 지역 import
    from .schema import ConfigIssue as issue

    c = s.capture
    if not c.views or any(v not in CAPTURE_VIEWS for v in c.views) or len(set(c.views)) != len(c.views):
        issues.append(issue("capture.views", f"방향 1개 이상(중복 없음): {', '.join(CAPTURE_VIEWS)}"))
    if c.video_ext not in CAPTURE_VIDEO_EXTS:
        issues.append(issue("capture.video_ext", "mp4 | avi | gif"))
    df = c.default_field
    if not df.strip() or len(df) > 64 or any(ch in DEFAULT_FIELD_FORBIDDEN or ord(ch) < 0x20 or ord(ch) == 0x7F for ch in df):
        issues.append(issue("capture.default_field", "1~64자, 따옴표·괄호·$·\\·;·|·제어문자 없음"))
    if c.timeout_s is not None and not 1 <= c.timeout_s <= 86400:
        issues.append(issue("capture.timeout_s", "1~86400 또는 null"))
    if not 1048576 <= c.max_video_bytes <= 4294967296:
        issues.append(issue("capture.max_video_bytes", "1 MiB~4 GiB"))
    v = s.resources.contour_capture_tcl
    if v:
        if not is_abs_path_str(v):
            issues.append(issue("resources.contour_capture_tcl", "절대경로여야 합니다"))
        elif has_unsafe_chars(v):
            issues.append(issue("resources.contour_capture_tcl", "공백·제어문자·cmd 메타문자를 쓸 수 없습니다"))
