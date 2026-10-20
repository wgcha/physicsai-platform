"""명령 템플릿 표(§9.1 실행 파일 placeholder·§9.2 템플릿 키·경로 표기·금지 문자)와 placeholder 해석·템플릿 검증 — commands에서 재노출."""

from __future__ import annotations

import re
import string
from dataclasses import dataclass

# §9.1 argv[0]으로 허용되는 실행 파일 placeholder → altair 설정 키
EXECUTABLE_PLACEHOLDERS: dict[str, str] = {
    "edspy": "edspy_path",
    "simlab": "simlab_path",
    "hw": "hw_exe_path",
    "hstbatch": "hyperstudy_path",
    "hvtrans": "hvtrans_exe_path",
    "hstpy": "hstpy_path",  # 2차(phase2 §8.1): 빈 값이면 hyperstudy_path 폴더의 hstpy.bat로 파생
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
    if head_idx >= len(elements) or elements[head_idx] not in {f"{{{p}}}" for p in EXECUTABLE_PLACEHOLDERS}:
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
            if n in EXECUTABLE_PLACEHOLDERS and i != head_idx:
                problems.append(f"'{key}'에서 실행 파일 placeholder '{{{n}}}'은 argv[0]에만 쓸 수 있습니다")
        if _CONTROL_RE.search(el):
            problems.append(f"'{key}'의 요소에 제어문자가 있습니다")
    return problems
