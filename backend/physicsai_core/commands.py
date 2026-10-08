"""명령 템플릿 검증·펼침(계약 §9).

- 외부 프로그램 argv는 설정 `commands.<key>`(문자열 배열)에서만 만든다.
- 이 모듈은 argv 목록을 만들 뿐 실행하지 않는다(실행은 워커만, shell=False).
"""

from __future__ import annotations

import os
import re
import string
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .errors import StepFailure

# §9.1 argv[0]으로 허용되는 실행 파일 placeholder → altair 설정 키
EXECUTABLE_PLACEHOLDERS: dict[str, str] = {
    "edspy": "edspy_path",
    "simlab": "simlab_path",
    "hw": "hw_exe_path",
    "hstbatch": "hyperstudy_path",
    "hvtrans": "hvtrans_exe_path",
}

EXPANSION_TOKENS = ("@cmd_c", "@write_files", "@hooks_arg")


@dataclass(frozen=True)
class TemplateSpec:
    placeholders: frozenset[str]
    tokens: frozenset[str]
    required: bool  # 확정 템플릿은 null 금지(§14.3)


# §9.2 템플릿 키와 허용 placeholder
TEMPLATE_SPECS: dict[str, TemplateSpec] = {
    "edspy_create_dataset": TemplateSpec(frozenset({"edspy", "out_psdata", "spec_yaml"}), frozenset(), True),
    "edspy_score": TemplateSpec(
        frozenset({"edspy", "score_path", "model_psmdl", "model_pscfg", "eval_psdata"}),
        frozenset({"@write_files"}),
        True,
    ),
    "geom_update": TemplateSpec(frozenset({"simlab", "rendered_script", "cad_file", "work_dir"}), frozenset(), False),
    "mesh": TemplateSpec(frozenset({"simlab", "rendered_script", "cad_file", "work_dir"}), frozenset(), False),
    "rad_assemble": TemplateSpec(frozenset({"hw", "work_dir", "starter", "input_dir"}), frozenset(), False),
    "edspy_predict": TemplateSpec(
        frozenset({"edspy", "pred_h3d", "model_psmdl", "model_pscfg", "starter"}),
        frozenset({"@cmd_c", "@hooks_arg"}),
        True,
    ),
    "contour_preview": TemplateSpec(
        frozenset({"hw", "preview_tcl", "pred_h3d_fwd", "preview_json_fwd"}), frozenset(), True
    ),
    "response_extract": TemplateSpec(
        frozenset({"hw", "pred_h3d", "pred_h3d_fwd", "responses_json", "out_csv", "work_dir"}),
        frozenset(),
        False,
    ),
}

CMD_META_CHARS = set('&|<>^%!"')
# .bat·.cmd는 cmd.exe가 인자를 다시 해석한다(BatBadBut). 이때 구분자로 쓰이는 문자도 거부한다.
CMD_BAT_EXTRA_CHARS = set(";,=()")
BAT_EXTENSIONS = (".bat", ".cmd")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_WS_RE = re.compile(r"\s")


def parse_placeholders(element: str) -> list[str]:
    """요소 문자열 안의 `{name}` 목록. 형식 오류·변환·서식 지정은 ValueError."""
    names: list[str] = []
    for _literal, field, spec, conv in string.Formatter().parse(element):
        if field is None:
            continue
        if field == "" or not re.fullmatch(r"[a-z_][a-z0-9_]*", field):
            raise ValueError(f"잘못된 placeholder '{{{field}}}'")
        if spec or conv:
            raise ValueError(f"placeholder '{{{field}}}'에 서식·변환 지정은 쓸 수 없습니다")
        names.append(field)
    return names


def validate_template(key: str, template: object) -> list[str]:
    """템플릿 1개 검증. 문제 목록(한국어)을 돌려준다(빈 목록 = 정상)."""
    spec = TEMPLATE_SPECS.get(key)
    if spec is None:
        return [f"알 수 없는 템플릿 키 '{key}'"]
    if template is None:
        return [f"확정 템플릿 '{key}'은 null일 수 없습니다"] if spec.required else []
    if not isinstance(template, list) or not template or not all(isinstance(x, str) for x in template):
        return [f"템플릿 '{key}'은 비어 있지 않은 문자열 배열이어야 합니다"]
    problems: list[str] = []
    elements = list(template)
    head_idx = 0
    if elements[0] == "@cmd_c":
        if "@cmd_c" not in spec.tokens:
            problems.append(f"'{key}'에서 @cmd_c는 허용되지 않습니다")
        head_idx = 1
    if head_idx >= len(elements) or elements[head_idx] not in {f"{{{p}}}" for p in EXECUTABLE_PLACEHOLDERS}:
        problems.append(f"'{key}'의 argv[0]은 {{edspy}} {{simlab}} {{hw}} {{hstbatch}} {{hvtrans}} 중 하나여야 합니다")
    for i, el in enumerate(elements):
        if el.startswith("@"):
            if el not in EXPANSION_TOKENS:
                problems.append(f"'{key}'의 알 수 없는 펼침 토큰 '{el}'")
            elif el not in spec.tokens:
                problems.append(f"'{key}'에서 펼침 토큰 '{el}'은 허용되지 않습니다")
            elif el == "@cmd_c" and i != 0:
                problems.append(f"'{key}'에서 @cmd_c는 맨 앞에만 둘 수 있습니다")
            continue
        try:
            names = parse_placeholders(el)
        except ValueError as exc:
            problems.append(f"'{key}': {exc}")
            continue
        for n in names:
            if n not in spec.placeholders:
                problems.append(f"'{key}'에서 placeholder '{{{n}}}'은 허용되지 않습니다")
            if n in EXECUTABLE_PLACEHOLDERS and i != head_idx:
                problems.append(f"'{key}'에서 실행 파일 placeholder '{{{n}}}'은 argv[0]에만 쓸 수 있습니다")
        if _CONTROL_RE.search(el):
            problems.append(f"'{key}'의 요소에 제어문자가 있습니다")
    return problems


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
                mapping[n] = exe
            else:
                if n not in spec.placeholders:
                    raise StepFailure("CONFIG_INVALID", f"placeholder '{{{n}}}' 미허용")
                if n not in values:
                    raise StepFailure("INTERNAL_ERROR", f"placeholder '{{{n}}}' 값이 준비되지 않았습니다")
                v = values[n]
                check_value(n, v, allow_space=False, via_cmd=via_cmd)
                mapping[n] = v
        argv.append(el.format_map(mapping) if names or ("{{" in el or "}}" in el) else el)
    return argv


def fwd(path: str) -> str:
    """`_fwd` placeholder용 '/' 구분 경로."""
    return path.replace("\\", "/")
