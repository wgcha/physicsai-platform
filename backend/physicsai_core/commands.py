"""명령 템플릿 검증·펼침(계약 §9).

- 외부 프로그램 argv는 설정 `commands.<key>`(문자열 배열)에서만 만든다.
- 이 모듈은 argv 목록을 만들 뿐 실행하지 않는다(실행은 워커만, shell=False).
"""

from __future__ import annotations

import ntpath
import os
import posixpath
import re
import string
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from simdash_adapters.pathstr import fwd  # noqa: F401 (재노출 — 정의는 simdash_adapters, phase3.md §6.4)

from .errors import StepFailure

# §9.1 argv[0]으로 허용되는 실행 파일 placeholder → altair 설정 키
EXECUTABLE_PLACEHOLDERS: dict[str, str] = {
    "edspy": "edspy_path",
    "simlab": "simlab_path",
    "hw": "hw_exe_path",
    "hstbatch": "hyperstudy_path",
    "hvtrans": "hvtrans_exe_path",
    "hstpy": "hstpy_path",  # 2차(phase2 §8.1): 빈 값이면 hyperstudy_path 폴더의 hstpy.bat로 파생
    "paicad": "paicad_path",  # native 형상 엔진(geometry-engine.md §7.1): 설정 키는 geometry.paicad_path(빈 값 = 워커 Python 폴더에서 파생)
}
# 실행 파일 설정 키의 사용자 표시 이름(오류 문구용). 목록에 없으면 altair.<키>
EXECUTABLE_CONFIG_NAME: dict[str, str] = {"paicad_path": "geometry.paicad_path"}
PAICAD_KEYS = ("paicad_extract", "paicad_tag", "paicad_update", "paicad_morph", "paicad_check", "paicad_run", "paicad_version")


def executable_config_name(exe_key: str) -> str:
    return EXECUTABLE_CONFIG_NAME.get(exe_key, f"altair.{exe_key}")


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
    # phase3 §11.4: 원본 m_2(HyperMesh include 변환). {simlab}·{rendered_script}·{cad_file}은 SimLab 변형 호환용
    "mesh": TemplateSpec(
        frozenset({"hw", "simlab", "include_tcl", "simlab_mesh", "mesh_inc", "renum_csv", "work_dir", "rendered_script",
                   "cad_file"}),
        frozenset(),
        False,
    ),
    "rad_assemble": TemplateSpec(frozenset({"hw", "work_dir", "starter", "input_dir"}), frozenset(), False),
    "edspy_predict": TemplateSpec(
        frozenset({"edspy", "pred_h3d", "model_psmdl", "model_pscfg", "starter"}),
        frozenset({"@cmd_c", "@hooks_arg"}),
        True,
    ),
    "contour_preview": TemplateSpec(
        frozenset({"hw", "preview_tcl", "pred_h3d_fwd", "preview_json_fwd"}), frozenset(), True
    ),
    # phase3 §14.6: {extract_tcl}(원본 ⑤ m_4 H3D_StaticMinMax_to_CSV_FAST.tcl 사본)이 있으면 새 방식, 없으면 {out_csv} 직접 작성(기존)
    "response_extract": TemplateSpec(
        frozenset({"hw", "pred_h3d", "pred_h3d_fwd", "responses_json", "out_csv", "work_dir", "extract_tcl"}),
        frozenset(),
        False,
    ),
    # phase3 §15 S10: {capture_tcl} = 작업 폴더(P/RESULT/media)에 복사한 contour_capture.tcl(옆에 capture_settings.tcl)
    "contour_capture": TemplateSpec(frozenset({"hw", "capture_tcl"}), frozenset(), False),
    # ---- 2차(phase2 §8.1). null이면 그 기능만 비활성(가정 A-11) ----
    "simlab_extract_params": TemplateSpec(frozenset({"simlab", "launcher", "cad_file", "xml_out"}), frozenset(), False),
    "hst_gen_radioss": TemplateSpec(frozenset({"hstbatch", "multi_execution", "launcher"}), frozenset(), False),
    "h3d_preview": TemplateSpec(frozenset({"hw", "preview_tcl", "h3d", "result_json"}), frozenset(), False),
    "hvtrans_curate": TemplateSpec(frozenset({"hvtrans", "cfg", "h3d", "out_h3d"}), frozenset(), False),
    "t01_preview": TemplateSpec(frozenset({"hw", "preview_tcl", "t01", "result_json"}), frozenset(), False),
    "t01_curve_export": TemplateSpec(frozenset({"hw", "curate_tcl", "config_json"}), frozenset(), False),
    "hst_optimization": TemplateSpec(frozenset({"hstpy", "launcher"}), frozenset({"@cmd_c"}), False),
}

# ---- native 형상 엔진(geometry-engine.md §7.1). 모두 required=False, 토큰 없음, 경로 표기 os ----
_P = frozenset
_UPD = {"cad_input", "features_json", "values_json", "tag_dir", "options_json", "update_dir"}
_MORPH = {"baseline_inc", "tag_dir", "features_json", "update_dir", "options_json", "morph_dir"}
_CHECK = {"baseline_inc", "morph_dir", "update_dir", "tag_dir", "features_json", "values_json", "assem_dir", "renum_csv",
          "options_json", "check_dir", "out_inc"}
_NATIVE_PLACEHOLDERS: dict[str, frozenset[str]] = {
    "paicad_extract": _P({"paicad", "cad_input", "renum_csv", "options_json", "out_dir"}),
    "paicad_tag": _P({"paicad", "cad_input", "features_json", "baseline_inc", "renum_csv", "assem_dir", "options_json", "out_dir"}),
    "paicad_update": _P({"paicad"} | _UPD),
    "paicad_morph": _P({"paicad"} | _MORPH),
    "paicad_check": _P({"paicad"} | _CHECK),
    "paicad_run": _P({"paicad"} | _UPD | _MORPH | _CHECK),
    "paicad_version": _P({"paicad"}),
}
for _k, _ph in _NATIVE_PLACEHOLDERS.items():
    TEMPLATE_SPECS[_k] = TemplateSpec(_ph, frozenset(), False)

PHASE2_TEMPLATE_KEYS = (
    "simlab_extract_params", "hst_gen_radioss", "h3d_preview", "hvtrans_curate", "t01_preview", "t01_curve_export",
    "hst_optimization",
)

# 키별 경로 표기(phase2 §8.1 "값 표기"): fwd = '/' 구분(원본 replace("\\","/")), os = OS 기본(원본 abspath/normpath).
# 표에 없는 placeholder는 값 그대로(1차 동작 유지).
PATH_STYLE: dict[tuple[str, str], str] = {
    ("simlab_extract_params", "launcher"): "os",
    ("simlab_extract_params", "cad_file"): "os",
    ("simlab_extract_params", "xml_out"): "os",
    ("hst_gen_radioss", "launcher"): "fwd",
    ("h3d_preview", "preview_tcl"): "fwd",
    ("h3d_preview", "h3d"): "fwd",
    ("h3d_preview", "result_json"): "fwd",
    ("hvtrans_curate", "cfg"): "os",
    ("hvtrans_curate", "h3d"): "os",
    ("hvtrans_curate", "out_h3d"): "os",
    ("t01_preview", "preview_tcl"): "fwd",
    ("t01_preview", "t01"): "fwd",
    ("t01_preview", "result_json"): "fwd",
    ("t01_curve_export", "curate_tcl"): "fwd",
    ("t01_curve_export", "config_json"): "fwd",
    ("hst_optimization", "launcher"): "os",
    ("response_extract", "extract_tcl"): "fwd",
    ("contour_capture", "capture_tcl"): "fwd",  # phase3 §15: HyperView -tcl 인자('/' 표기)  # phase3 §14.6: HyperWorks -tcl 인자(다른 hw TCL과 같은 '/' 표기)
}

for _k, _ph in _NATIVE_PLACEHOLDERS.items():
    for _n in _ph - {"paicad"}:
        PATH_STYLE[(_k, _n)] = "os"  # 모든 paicad 경로 인자는 OS 표기(§7.1)

# {renum_csv}가 없을 때 인자 쌍째 생략하는 (키, placeholder) → 옵션 이름(§7.3.1, 이 키·이 쌍 한정)
OPTIONAL_PAIRS: dict[tuple[str, str], str] = {("paicad_extract", "renum_csv"): "--renum-csv"}

# phase3 §14.6: commands.response_extract가 이 placeholder를 쓰면 원본 ⑤ m_4 방식(H3D_REQUESTS.txt → RESPONSES.txt)
RESPONSE_EXTRACT_TCL_PLACEHOLDER = "extract_tcl"

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
    if key in PAICAD_KEYS:
        if head_idx >= len(elements) or elements[head_idx] != "{paicad}":
            problems.append(f"'{key}'의 argv[0]은 {{paicad}}여야 합니다")
    elif head_idx >= len(elements) or elements[head_idx] not in {f"{{{p}}}" for p in EXECUTABLE_PLACEHOLDERS if p != "paicad"}:
        problems.append(f"'{key}'의 argv[0]은 {{edspy}} {{simlab}} {{hw}} {{hstbatch}} {{hvtrans}} {{hstpy}} 중 하나여야 합니다")
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
            if n == "paicad" and key not in PAICAD_KEYS:
                problems.append(f"'{key}'에서 {{paicad}}는 쓸 수 없습니다(paicad_* 명령 전용)")
            if n in EXECUTABLE_PLACEHOLDERS and i != head_idx:
                problems.append(f"'{key}'에서 실행 파일 placeholder '{{{n}}}'은 argv[0]에만 쓸 수 있습니다")
        if _CONTROL_RE.search(el):
            problems.append(f"'{key}'의 요소에 제어문자가 있습니다")
    return problems


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
    extra_args: Sequence[str] = (),
) -> list[str]:
    """템플릿을 argv 목록으로 펼친다.

    values: 템플릿 키별 허용 placeholder 값(경로 등). executables: 실행 파일 설정 키(altair 키·paicad_path) → 경로.
    extra_args: argv 끝에 덧붙일 요소(값 검사 동일) — `["--body-map", <경로>]`(geometry-engine.md §7.1, 템플릿 밖).
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
    skip_next = False
    tpl = list(template)
    for idx, el in enumerate(tpl):
        if skip_next:
            skip_next = False
            continue
        nxt = tpl[idx + 1] if idx + 1 < len(tpl) else ""
        for (okey, oname), flag in OPTIONAL_PAIRS.items():  # 값 없는 선택 인자 쌍 생략(이 키·이 쌍 한정)
            if okey == key and el == flag and nxt == "{" + oname + "}" and not values.get(oname):
                skip_next = True
        if skip_next:
            continue
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
                        "EXECUTABLE_MISSING", f"실행 파일 설정 {executable_config_name(EXECUTABLE_PLACEHOLDERS[n])}이 비어 있습니다"
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
    for x in extra_args:
        if x.startswith("--"):
            argv.append(x)  # 옵션 이름(코드 상수)
            continue
        v = os_path(x, is_windows)
        check_value("extra_arg", v, allow_space=False, via_cmd=via_cmd)
        argv.append(v)
    return argv
