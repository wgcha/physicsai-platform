"""명령 템플릿 검증·펼침(계약 §9).

- 외부 프로그램 argv는 설정 `commands.<key>`(문자열 배열)에서만 만든다.
- 이 모듈은 argv 목록을 만들 뿐 실행하지 않는다(실행은 워커만, shell=False).
300줄 분할(R-B): 템플릿 키·placeholder 표와 템플릿 검증은 `commands_spec`, 값 검사·argv 펼침은 `commands_render`
(여기서 재노출). 템플릿 사용 판정·pscfg 문구·S16 파생 영상 템플릿은 이 파일.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence

from simdash_adapters.pathstr import fwd  # noqa: F401 (재노출 — 정의는 simdash_adapters, phase3.md §6.4)

from .errors import StepFailure
from .commands_spec import (  # noqa: F401 - 기존 경로 재노출
    EXECUTABLE_PLACEHOLDERS, EXPANSION_TOKENS, TemplateSpec, TEMPLATE_SPECS, PHASE2_TEMPLATE_KEYS, PATH_STYLE,
    RESPONSE_EXTRACT_TCL_PLACEHOLDER, CMD_META_CHARS, CMD_BAT_EXTRA_CHARS, BAT_EXTENSIONS, parse_placeholders,
    validate_template,
    # native 형상 엔진(geometry-engine.md §7.1)·쉘(SM §8.1)·가시화(GV §6.1)
    EXECUTABLE_CONFIG_NAME, PAICAD_SHELL_KEYS, PAICAD_VIEW_KEYS, PAICAD_KEYS, OPTIONAL_PAIRS, executable_config_name,
)
from .commands_render import check_value, cmd_c_prefix, os_path, styled_value, render_argv  # noqa: F401 - 기존 경로 재노출

PSCFG_MANY_MESSAGE = ".pscfg 파일이 여러 개라 어느 것인지 알 수 없습니다 — 0개 또는 1개만 두세요(현재 {n}개)"
PSCFG_REQUIRED_MESSAGE = "이 명령 설정은 .pscfg가 필요합니다 — pscfg가 있는 모델을 등록하거나 설정에서 {model_pscfg}를 빼세요"


def template_uses(template: Sequence[str] | None, name: str) -> bool:
    """템플릿 요소 중 placeholder `{name}`이 있는지(형식 오류 요소는 무시 — 검증은 validate_template)."""
    for el in template or []:
        if not isinstance(el, str) or el.startswith("@"):
            continue
        try:
            if name in parse_placeholders(el):
                return True
        except ValueError:
            continue
    return False


def model_lacks_required_pscfg(template: Sequence[str] | None, model: Mapping[str, object]) -> bool:
    """D3-43: 모델에 .pscfg가 없는데(선택 등록) 템플릿이 {model_pscfg}를 쓰면 True."""
    return not model.get("pscfg_rel") and template_uses(template, "model_pscfg")


# ---- phase3 §21.4.4 S16: 파생 영상 템플릿(commands 절이 아니라 capture.ffmpeg에서 만든다) ----------------------
# 실행 파일 placeholder → 펼침용 executables 키(effective_altair 표 밖, capture.ffmpeg.exe·probe_exe)
VIDEO_EXECUTABLE_PLACEHOLDERS: dict[str, str] = {"ffmpeg": "ffmpeg_exe", "ffprobe": "ffprobe_exe"}
VIDEO_TEMPLATE_SPECS: dict[str, TemplateSpec] = {
    "video_transcode": TemplateSpec(frozenset({"video_in", "video_out", "scale", "crf", "fps"}), frozenset(), False),
    "video_probe": TemplateSpec(frozenset({"video_in"}), frozenset(), False),
}
_VIDEO_HEAD = {"video_transcode": "ffmpeg", "video_probe": "ffprobe"}


def video_template(capture_cfg: object, key: str) -> list[str] | None:
    """`video_transcode = ["{ffmpeg}", *capture.ffmpeg.args]`, `video_probe = ["{ffprobe}", *probe_args]`. exe 빈 값 = None."""
    f = capture_cfg.ffmpeg  # type: ignore[attr-defined]
    if key == "video_transcode":
        return ["{ffmpeg}", *f.args] if f.exe else None
    if key == "video_probe":
        return ["{ffprobe}", *f.probe_args] if f.probe_exe else None
    raise KeyError(key)


def video_executables(capture_cfg: object) -> dict[str, str]:
    f = capture_cfg.ffmpeg  # type: ignore[attr-defined]
    return {"ffmpeg_exe": f.exe, "ffprobe_exe": f.probe_exe}


def render_video_argv(key: str, template: Sequence[str] | None, values: Mapping[str, str], *,
                      executables: Mapping[str, str], is_windows: bool | None = None) -> list[str]:
    """파생 영상 템플릿 펼침(shell=False argv). argv[0] = {ffmpeg}|{ffprobe}, 나머지는 허용 값 placeholder만."""
    if template is None:
        raise StepFailure("TEMPLATE_NOT_CONFIGURED", f"영상 변환 실행 파일이 설정되지 않았습니다({key})")
    spec = VIDEO_TEMPLATE_SPECS[key]
    head = _VIDEO_HEAD[key]
    if not template or template[0] != f"{{{head}}}":
        raise StepFailure("CONFIG_INVALID", f"'{key}'의 argv[0]은 {{{head}}}여야 합니다")
    exe = executables.get(VIDEO_EXECUTABLE_PLACEHOLDERS[head]) or ""
    if not exe:
        raise StepFailure("EXECUTABLE_MISSING", f"실행 파일 설정 capture.ffmpeg.{'exe' if head == 'ffmpeg' else 'probe_exe'}이 비어 있습니다")
    check_value(head, exe, allow_space=True)
    win = is_windows if is_windows is not None else os.name == "nt"
    argv = [os_path(exe, True) if win else exe]
    for el in template[1:]:
        try:
            names = parse_placeholders(el)
        except ValueError as exc:
            raise StepFailure("CONFIG_INVALID", f"'{key}': {exc}") from exc
        mapping: dict[str, str] = {}
        for n in names:
            if n not in spec.placeholders:
                raise StepFailure("CONFIG_INVALID", f"'{key}'에서 placeholder '{{{n}}}'은 허용되지 않습니다")
            if n not in values:
                raise StepFailure("INTERNAL_ERROR", f"placeholder '{{{n}}}' 값이 준비되지 않았습니다")
            check_value(n, values[n], allow_space=False)
            mapping[n] = values[n]
        argv.append(el.format_map(mapping) if names or ("{{" in el or "}}" in el) else el)
    return argv
