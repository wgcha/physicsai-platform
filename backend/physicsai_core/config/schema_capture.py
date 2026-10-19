"""설정 스키마 — ④ 컨투어 캡처 절 `capture`(phase3 §15 S10)와 캡처 TCL 자원 경로 결정·검증."""

from __future__ import annotations

import math
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


CAPTURE_VIDEO_SCOPES = ("page", "window")
# phase3 §21.4.4 S16: ffmpeg 변환 인자 허용 placeholder(실행 파일 placeholder는 템플릿 머리 {ffmpeg}·{ffprobe}로만 붙는다)
FFMPEG_ARG_PLACEHOLDERS = frozenset({"video_in", "video_out", "scale", "crf", "fps"})
FFPROBE_ARG_PLACEHOLDERS = frozenset({"video_in"})
AVI_FALLBACK_MESSAGE = "avi는 브라우저에서 재생할 수 없어 mp4로 저장합니다(capture.allow_avi)"


def _default_ffmpeg_args() -> list[str]:
    return ["-hide_banner", "-loglevel", "error", "-y", "-i", "{video_in}", "-an",
            "-vf", "scale=trunc(iw*{scale}/2)*2:trunc(ih*{scale}/2)*2,fps={fps}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "{crf}", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            "{video_out}"]


def _default_probe_args() -> list[str]:
    return ["-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_name,pix_fmt", "-of", "default=nw=1",
            "{video_in}"]


class LadderStep(_M):
    scale: float = 1.0
    crf: int = 28
    fps: int = 15


def _default_ladder() -> list[LadderStep]:
    return [LadderStep(scale=1.0, crf=28, fps=15), LadderStep(scale=0.75, crf=30, fps=12),
            LadderStep(scale=0.5, crf=32, fps=10), LadderStep(scale=0.5, crf=38, fps=8)]


class FfmpegCfg(_M):
    """선택적 영상 변환(phase3 §21.4.4 S16). exe 빈 값 = 변환 안 함."""
    exe: str = ""
    probe_exe: str = ""
    args: list[str] = Field(default_factory=_default_ffmpeg_args)
    probe_args: list[str] = Field(default_factory=_default_probe_args)
    ladder: list[LadderStep] = Field(default_factory=_default_ladder)
    timeout_s: float = 300


class CaptureCfg(_M):
    enabled: bool = True  # false = 기능 끔(altair.hw_exe_path가 없어도 꺼짐)
    views: list[str] = Field(default_factory=lambda: ["iso", "front", "top", "right"])
    video: bool = True  # 방향마다 애니메이션 동영상도 저장
    video_ext: str = "mp4"  # mp4 | avi | gif
    use_last: bool = True  # 마지막 프레임 기준 캡처(false = 첫 프레임)
    default_field: str = "CornerStress"  # 템플릿 표시 설정·응답 정의가 없을 때의 결과 필드(예측 h3d 응력 — D3-53)
    # D3-54: 최종 표시 설정의 성분이 비었고 결과 필드가 default_field이면 이 성분(capture_settings.tcl DCOMP). "" = 성분 없음
    default_component: str = "vonMises"
    # D3-54: 일괄 예측 화면 "캡처 예상" 참고 문구의 가정값(서버 실측 아님) — 방향 1개당 이미지·영상 크기(MB), 캡처 시간(초)
    estimate_image_mb: float = 0.3
    estimate_video_mb: float = 1.0
    estimate_sec_per_view: float = 20
    estimate_sec_per_video: float = 40
    timeout_s: float | None = 1800  # 캡처 1회 상한(초). 넘으면 프로세스 종료 + 경고. null = 상한 없음
    max_video_bytes: int = 209715200  # 동영상 1개 등록·제공 상한(200 MiB)
    # ---- S16(phase3 §21.4.4) ----
    allow_avi: bool = False  # false면 video_ext=avi여도 실제 저장은 mp4(설정 경고)
    video_scope: str = "page"  # page | window — TCL `hwc save animation <scope>`(E4-14-V7)
    video_target_bytes: int = 1048576  # 표시용 영상 목표 크기(1 MiB). 변환이 있으면 단계 재인코딩
    ffmpeg: FfmpegCfg = Field(default_factory=FfmpegCfg)


def effective_video_ext(s: Settings) -> str:
    """실제 저장 확장자: avi는 allow_avi일 때만(아니면 mp4 — §21.4.4 M4)."""
    ext = s.capture.video_ext
    return "mp4" if ext == "avi" and not s.capture.allow_avi else ext


def transcode_enabled(s: Settings) -> bool:
    """ffmpeg 변환 가능: exe가 설정됐고 파일이 있다(/status.capture.transcode)."""
    exe = s.capture.ffmpeg.exe
    return bool(exe) and os.path.isfile(exe)


def capture_warnings(s: Settings) -> list[tuple[str, str]]:
    """설정 경고(키, 문구): avi 대체, ffmpeg 실행 파일 없음."""
    out: list[tuple[str, str]] = []
    c = s.capture
    if c.video_ext == "avi" and not c.allow_avi:
        out.append(("capture.video_ext", AVI_FALLBACK_MESSAGE))
    for k in ("exe", "probe_exe"):
        v = getattr(c.ffmpeg, k)
        if v and not os.path.isfile(v):
            out.append((f"capture.ffmpeg.{k}", "파일이 없습니다 — 영상 변환·코덱 확인을 건너뜁니다"))
    return out


def _arg_list_problem(args: list[str], allowed: frozenset[str], required: tuple[str, ...]) -> str | None:
    from ..commands import parse_placeholders  # commands → errors만 import(순환 없음), 지역 import로 통일

    if not 1 <= len(args) <= 64:
        return "인자 1~64개"
    seen: list[str] = []
    for a in args:
        if not isinstance(a, str) or len(a) > 256:
            return "각 인자는 256자 이내 문자열"
        if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in a):
            return "제어문자를 쓸 수 없습니다"
        try:
            names = parse_placeholders(a)
        except ValueError as exc:
            return str(exc)
        bad = [n for n in names if n not in allowed]
        if bad:
            return f"허용되지 않는 placeholder {{{bad[0]}}} — 허용: {', '.join('{' + x + '}' for x in sorted(allowed))}"
        seen += names
    for r in required:
        if seen.count(r) != 1:
            return f"{{{r}}}가 정확히 1번 있어야 합니다"
    return None


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
    dc = c.default_component
    if len(dc) > 64 or any(ch in DEFAULT_FIELD_FORBIDDEN or ord(ch) < 0x20 or ord(ch) == 0x7F for ch in dc):
        issues.append(issue("capture.default_component", "0~64자(빈 값 = 성분 없음), 따옴표·괄호·$·\\·;·|·제어문자 없음"))
    for k, hi in (("estimate_image_mb", 1024), ("estimate_video_mb", 4096), ("estimate_sec_per_view", 3600),
                  ("estimate_sec_per_video", 3600)):
        v = getattr(c, k)
        if not (math.isfinite(v) and 0 <= v <= hi):
            issues.append(issue(f"capture.{k}", f"0~{hi}"))
    if c.timeout_s is not None and not 1 <= c.timeout_s <= 86400:
        issues.append(issue("capture.timeout_s", "1~86400 또는 null"))
    if not 1048576 <= c.max_video_bytes <= 4294967296:
        issues.append(issue("capture.max_video_bytes", "1 MiB~4 GiB"))
    if c.video_scope not in CAPTURE_VIDEO_SCOPES:
        issues.append(issue("capture.video_scope", "page | window"))
    max_ok = 1048576 <= c.max_video_bytes <= 4294967296  # 상한 자체가 틀리면 그 오류만(목표 크기 비교 생략)
    if max_ok and not 65536 <= c.video_target_bytes <= c.max_video_bytes:
        issues.append(issue("capture.video_target_bytes", "64 KiB~capture.max_video_bytes"))
    f = c.ffmpeg
    for k in ("exe", "probe_exe"):
        v = getattr(f, k)
        if v and not is_abs_path_str(v):
            issues.append(issue(f"capture.ffmpeg.{k}", "빈 값 또는 절대경로"))
        elif v and has_unsafe_chars(v):
            issues.append(issue(f"capture.ffmpeg.{k}", "공백·제어문자·cmd 메타문자를 쓸 수 없습니다"))
    p = _arg_list_problem(f.args, FFMPEG_ARG_PLACEHOLDERS, ("video_in", "video_out"))
    if p:
        issues.append(issue("capture.ffmpeg.args", p))
    p = _arg_list_problem(f.probe_args, FFPROBE_ARG_PLACEHOLDERS, ("video_in",))
    if p:
        issues.append(issue("capture.ffmpeg.probe_args", p))
    if not 1 <= len(f.ladder) <= 8:
        issues.append(issue("capture.ffmpeg.ladder", "단계 1~8개"))
    for i, st in enumerate(f.ladder):
        if not (math.isfinite(st.scale) and 0.1 <= st.scale <= 1.0) or not 0 <= st.crf <= 51 or not 1 <= st.fps <= 60:
            issues.append(issue(f"capture.ffmpeg.ladder.{i}", "scale 0.1~1.0, crf 0~51, fps 1~60"))
    if not (math.isfinite(f.timeout_s) and 1 <= f.timeout_s <= 86400):
        issues.append(issue("capture.ffmpeg.timeout_s", "1~86400"))
    v = s.resources.contour_capture_tcl
    if v:
        if not is_abs_path_str(v):
            issues.append(issue("resources.contour_capture_tcl", "절대경로여야 합니다"))
        elif has_unsafe_chars(v):
            issues.append(issue("resources.contour_capture_tcl", "공백·제어문자·cmd 메타문자를 쓸 수 없습니다"))
