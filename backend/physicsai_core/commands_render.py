"""명령 템플릿 값 검사·경로 표기(phase2 §8.1)·argv 펼침(§9) — commands에서 재노출."""

from __future__ import annotations

import ntpath
import os
import posixpath
from collections.abc import Mapping, Sequence

from simdash_adapters.pathstr import fwd

from .commands_spec import (
    _CONTROL_RE,
    _WS_RE,
    BAT_EXTENSIONS,
    CMD_BAT_EXTRA_CHARS,
    CMD_META_CHARS,
    EXECUTABLE_PLACEHOLDERS,
    PATH_STYLE,
    TEMPLATE_SPECS,
    parse_placeholders,
    validate_template,
)
from .errors import StepFailure


def check_value(name: str, value: str, *, allow_space: bool, via_cmd: bool = False) -> None:
    """치환 값 검사(§9.1). 위반 시 StepFailure(INPUT_INVALID)."""
    if not isinstance(value, str):
        raise StepFailure("INPUT_INVALID", f"'{name}' 값이 문자열이 아닙니다")
    if value == "":
        raise StepFailure("INPUT_INVALID", f"'{name}' 값이 비어 있습니다")
    if _CONTROL_RE.search(value):
        raise StepFailure("INPUT_INVALID", f"'{name}' 값에 제어문자가 있습니다")
    bad = sorted(CMD_META_CHARS.intersection(value))
    if bad:
        raise StepFailure("INPUT_INVALID", f"'{name}' 값에 허용되지 않는 문자 {' '.join(bad)} 가 있습니다: {value}")
    if via_cmd:
        bad2 = sorted(CMD_BAT_EXTRA_CHARS.intersection(value))
        if bad2:
            raise StepFailure("INPUT_INVALID", f"'{name}' 값에 .bat 실행 시 허용되지 않는 문자 {' '.join(bad2)} 가 있습니다: {value}")
    if not allow_space and _WS_RE.search(value):
        raise StepFailure("INPUT_INVALID", f"'{name}' 값에 공백이 있습니다: {value}")


def cmd_c_prefix(is_windows: bool | None = None, environ: Mapping[str, str] | None = None) -> list[str]:
    """`@cmd_c` 펼침. Windows는 %SystemRoot%\\System32\\cmd.exe /c, 그 외는 빈 목록."""
    if is_windows is None:
        is_windows = os.name == "nt"
    if not is_windows:
        return []
    env = environ if environ is not None else os.environ
    root = env.get("SystemRoot") or env.get("SYSTEMROOT")
    if not root:
        raise StepFailure("CONFIG_INVALID", "SystemRoot 환경변수가 없어 cmd.exe 경로를 만들 수 없습니다")
    return [root.rstrip("\\/") + "\\System32\\cmd.exe", "/c"]


def os_path(value: str, is_windows: bool | None = None) -> str:
    """OS 기본 구분자 표기(원본 os.path.normpath). Windows면 '\\'."""
    if is_windows is None:
        is_windows = os.name == "nt"
    return ntpath.normpath(value) if is_windows else posixpath.normpath(value)


def styled_value(key: str, name: str, value: str, is_windows: bool | None = None) -> str:
    style = PATH_STYLE.get((key, name))
    if style == "fwd":
        return fwd(value)
    if style == "os":
        return os_path(value, is_windows)
    return value


def render_argv(
    key: str,
    template: Sequence[str] | None,
    values: Mapping[str, str],
    *,
    executables: Mapping[str, str],
    write_files: bool = False,
    is_windows: bool | None = None,
    environ: Mapping[str, str] | None = None,
) -> list[str]:
    """템플릿을 argv 목록으로 펼친다.

    values: 템플릿 키별 허용 placeholder 값(경로 등). executables: altair 설정 키 → 경로.
    """
    if template is None:
        raise StepFailure("TEMPLATE_NOT_CONFIGURED", f"명령 템플릿 '{key}'이 설정되지 않았습니다")
    problems = validate_template(key, list(template))
    if problems:
        raise StepFailure("CONFIG_INVALID", "; ".join(problems))
    spec = TEMPLATE_SPECS[key]
    via_cmd = "@cmd_c" in template
    for el in template:
        if el.startswith("@"):
            continue
        for n in parse_placeholders(el):
            if n in EXECUTABLE_PLACEHOLDERS:
                exe0 = (executables.get(EXECUTABLE_PLACEHOLDERS[n]) or "").lower()
                via_cmd = via_cmd or exe0.endswith(BAT_EXTENSIONS)
        break
    argv: list[str] = []
    for el in template:
        if el == "@cmd_c":
            argv.extend(cmd_c_prefix(is_windows, environ))
            continue
        if el == "@write_files":
            if write_files:
                argv.append("--write-files")
            continue
        if el == "@hooks_arg":
            continue  # 1차는 항상 [] (U13)
        names = parse_placeholders(el)
        mapping: dict[str, str] = {}
        for n in names:
            if n in EXECUTABLE_PLACEHOLDERS:
                exe = executables.get(EXECUTABLE_PLACEHOLDERS[n]) or ""
                if not exe:
                    raise StepFailure(
                        "EXECUTABLE_MISSING", f"실행 파일 설정 altair.{EXECUTABLE_PLACEHOLDERS[n]}이 비어 있습니다"
                    )
                check_value(n, exe, allow_space=True)
                # phase2 §2.3: Windows에서 argv[0]은 '\\' 구분자(hvtrans는 '/' 경로면 리더를 못 찾음)
                mapping[n] = os_path(exe, True) if (is_windows if is_windows is not None else os.name == "nt") else exe
            else:
                if n not in spec.placeholders:
                    raise StepFailure("CONFIG_INVALID", f"placeholder '{{{n}}}' 미허용")
                if n not in values:
                    raise StepFailure("INTERNAL_ERROR", f"placeholder '{{{n}}}' 값이 준비되지 않았습니다")
                v = styled_value(key, n, values[n], is_windows)
                check_value(n, v, allow_space=False, via_cmd=via_cmd)
                mapping[n] = v
        argv.append(el.format_map(mapping) if names or ("{{" in el or "}}" in el) else el)
    return argv
