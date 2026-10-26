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
    "paicad": "paicad_path",  # native 형상 엔진(geometry-engine.md §7.1): 설정 키는 geometry.paicad_path(빈 값 = 워커 Python 폴더에서 파생)
}
# 실행 파일 설정 키의 사용자 표시 이름(오류 문구용). 목록에 없으면 altair.<키>
EXECUTABLE_CONFIG_NAME: dict[str, str] = {"paicad_path": "geometry.paicad_path"}
PAICAD_SHELL_KEYS = ("paicad_shell_fixed_scan", "paicad_shell_extract", "paicad_shell_tag", "paicad_shell_update", "paicad_shell_morph",
                     "paicad_shell_check", "paicad_shell_run")
PAICAD_VIEW_KEYS = ("paicad_view_export", "paicad_view_preview", "paicad_shell_view_export", "paicad_shell_view_preview",
                    "paicad_view_grid", "paicad_shell_view_grid")  # grid = DOE 표본 형상 그리드(doe-preview.md §3.1, paicad 0.14.0+)
PAICAD_ASM_KEYS = ("paicad_asm_parts", "paicad_asm_check", "paicad_asm_write")  # 조립 매칭(asm-match.md §6.2)
PAICAD_KEYS = ("paicad_extract", "paicad_tag", "paicad_update", "paicad_morph", "paicad_check", "paicad_run", "paicad_version",
               "paicad_cushion_write", "paicad_props_scan", "paicad_props_apply", "paicad_map") + PAICAD_ASM_KEYS + PAICAD_SHELL_KEYS \
              + PAICAD_VIEW_KEYS


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
    # geometry-view.md §13.3: 결과 3D 컨투어 추출. {contour_extract_tcl} = 캐시 작업 폴더에 복사한 contour_extract.tcl
    "contour_extract": TemplateSpec(frozenset({"hw", "contour_extract_tcl"}), frozenset(), False),
}

# ---- native 형상 엔진(geometry-engine.md §7.1). 모두 required=False, 토큰 없음, 경로 표기 os ----
_P = frozenset
_UPD = {"cad_input", "features_json", "values_json", "tag_dir", "options_json", "update_dir"}
_MORPH = {"baseline_inc", "tag_dir", "features_json", "update_dir", "options_json", "morph_dir"}
_CHECK = {"baseline_inc", "morph_dir", "update_dir", "tag_dir", "features_json", "values_json", "assem_dir", "renum_csv",
          "options_json", "check_dir", "out_inc"}
_SHELL_UPD = {"cad_input", "features_json", "values_json", "fixed_dir", "options_json", "update_dir"}
_SHELL_MORPH = {"assem_dir", "tag_dir", "fixed_dir", "features_json", "update_dir", "options_json", "morph_dir"}
_SHELL_CHECK = {"assem_dir", "morph_dir", "update_dir", "tag_dir", "fixed_dir", "features_json", "values_json", "check_dir",
                "out_files_dir", "thickness_json", "options_json"}
_NATIVE_PLACEHOLDERS: dict[str, frozenset[str]] = {
    "paicad_extract": _P({"paicad", "cad_input", "renum_csv", "options_json", "out_dir"}),
    "paicad_tag": _P({"paicad", "cad_input", "features_json", "baseline_inc", "renum_csv", "assem_dir", "options_json", "out_dir"}),
    "paicad_update": _P({"paicad"} | _UPD),
    "paicad_morph": _P({"paicad"} | _MORPH),
    "paicad_check": _P({"paicad"} | _CHECK),
    "paicad_run": _P({"paicad"} | _UPD | _MORPH | _CHECK),
    # 쿠션 입력 rad(input-kind.md §5.1): {cushion_inc}(모핑 PASS include 또는 기준본)·{cushion_dir}(보고)·{cushion_rad}(출력 rad)
    "paicad_cushion_write": _P({"paicad", "cushion_inc", "renum_csv", "assem_dir", "cushion_dir", "cushion_rad"}),
    "paicad_version": _P({"paicad"}),
    # 조립 매칭(asm-match.md §6.2). {features_json}(①)과 {cad_input}(④)은 둘 중 하나 — ④는 --features 쌍을 --cad로 바꾼다(commands_asm)
    "paicad_asm_parts": _P({"paicad", "assem_dir", "features_json", "cad_input", "renum_csv", "asm_cache_dir", "options_json", "out_dir"}),
    "paicad_asm_check": _P({"paicad", "cad_input", "features_json", "assem_dir", "match_rows_json", "asm_cache_dir", "options_json", "out_dir"}),
    "paicad_asm_write": _P({"paicad", "assem_dir", "asm_match", "node_patch", "asm_cache_dir", "out_dir"}),
    # 단계 3S 쉘 두께(§11.1)·4B 다중 baseline(§7.3.8). {usage}·{split_param}은 경로가 아닌 값(map --usage·--split-param)
    "paicad_props_scan": _P({"paicad", "assem_dir", "options_json", "out_dir"}),
    "paicad_props_apply": _P({"paicad", "assem_dir", "values_json", "props_json", "out_dir"}),
    "paicad_map": _P({"paicad", "baselines_json", "map_out_dir", "user_map", "usage", "split_param", "options_json"}),
    # 쉘 판금 모핑(shell-morph.md §8.1): `paicad shell <verb>`. {fixed_dir}·{out_files_dir}·{thickness_json}(선택 쌍) 추가
    "paicad_shell_fixed_scan": _P({"paicad", "assem_dir", "features_json", "options_json", "out_dir"}),
    "paicad_shell_extract": _P({"paicad", "cad_input", "assem_dir", "options_json", "out_dir"}),
    "paicad_shell_tag": _P({"paicad", "cad_input", "features_json", "assem_dir", "fixed_dir", "options_json", "out_dir"}),
    "paicad_shell_update": _P({"paicad"} | _SHELL_UPD),
    "paicad_shell_morph": _P({"paicad"} | _SHELL_MORPH),
    "paicad_shell_check": _P({"paicad"} | _SHELL_CHECK),
    "paicad_shell_run": _P({"paicad"} | _SHELL_UPD | _SHELL_MORPH | _SHELL_CHECK),
    # 3D 가시화(geometry-view.md §6.1). {fe_mode}·{threads}는 경로가 아닌 값
    "paicad_view_export": _P({"paicad", "cad_input", "features_json", "view_options_json", "out_dir"}),
    "paicad_view_preview": _P({"paicad", "cad_input", "features_json", "values_json", "tag_dir", "options_json", "view_options_json",
                               "nominal_manifest", "fe_mode", "baseline_inc", "renum_csv", "assem_dir", "threads", "out_dir"}),
    "paicad_shell_view_export": _P({"paicad", "cad_input", "features_json", "fixed_dir", "view_options_json", "out_dir"}),
    "paicad_shell_view_preview": _P({"paicad", "cad_input", "features_json", "values_json", "fixed_dir", "tag_dir", "assem_dir",
                                     "options_json", "view_options_json", "nominal_manifest", "fe_mode", "threads", "thickness_json",
                                     "out_dir"}),
    # DOE 표본 형상 그리드(doe-preview.md §3.1·§6.5). {cells_json}·{thumb_options_json}은 새 placeholder, {tag_dir}(train 출처는 없음)은 선택 쌍
    "paicad_view_grid": _P({"paicad", "cad_input", "features_json", "cells_json", "tag_dir", "options_json", "view_options_json",
                            "thumb_options_json", "threads", "out_dir"}),
    "paicad_shell_view_grid": _P({"paicad", "cad_input", "features_json", "cells_json", "fixed_dir", "tag_dir", "options_json",
                                  "view_options_json", "thumb_options_json", "threads", "out_dir"}),
}
_NON_PATH = {("paicad_map", "usage"), ("paicad_map", "split_param"), ("paicad_view_preview", "fe_mode"), ("paicad_view_preview", "threads"),
             ("paicad_shell_view_preview", "fe_mode"), ("paicad_shell_view_preview", "threads"),
             ("paicad_view_grid", "threads"), ("paicad_shell_view_grid", "threads")}
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
    ("contour_capture", "capture_tcl"): "fwd",
    ("contour_extract", "contour_extract_tcl"): "fwd",  # geometry-view.md §6.1: {capture_tcl}과 같은 '/' 표기  # phase3 §15: HyperView -tcl 인자('/' 표기)  # phase3 §14.6: HyperWorks -tcl 인자(다른 hw TCL과 같은 '/' 표기)
}

for _k, _ph in _NATIVE_PLACEHOLDERS.items():
    for _n in _ph - {"paicad"}:
        if (_k, _n) not in _NON_PATH:
            PATH_STYLE[(_k, _n)] = "os"  # 모든 paicad 경로 인자는 OS 표기(§7.1)

# 조립 매칭 방식 M 쌍 치환(commands_asm)이 만드는 placeholder도 OS 경로 표기
from .commands_asm import ASM_EXTRA_PLACEHOLDERS, ASM_PAIR_KEYS  # noqa: E402

for _k in ASM_PAIR_KEYS:
    for _n in ASM_EXTRA_PLACEHOLDERS:
        PATH_STYLE.setdefault((_k, _n), "os")

# {renum_csv}가 없을 때 인자 쌍째 생략하는 (키, placeholder) → 옵션 이름(§7.3.1, 이 키·이 쌍 한정)
OPTIONAL_PAIRS: dict[tuple[str, str], str] = {("paicad_extract", "renum_csv"): "--renum-csv",
                                              # 조립 매칭(AM-10): RENUM 표가 없으면 추천 보조 생략, ④(STEP만)는 --features 쌍 생략, 공칭 쓰기는 --patch 생략
                                              ("paicad_asm_parts", "renum_csv"): "--renum-csv",
                                              ("paicad_asm_check", "features_json"): "--features",
                                              ("paicad_asm_write", "node_patch"): "--patch",
                                              # 4B map: 기존 param_map.json이 없으면 --user-map, range가 아니면 --split-param 생략(§7.3.8)
                                              ("paicad_map", "user_map"): "--user-map", ("paicad_map", "split_param"): "--split-param",
                                              # 쉘(SM §8.1): ①-1 extract는 조립 폴더 없음, 3S 두께가 없으면 --thickness 생략
                                              ("paicad_shell_extract", "assem_dir"): "--assem-dir",
                                              ("paicad_shell_check", "thickness_json"): "--thickness",
                                              ("paicad_shell_run", "thickness_json"): "--thickness",
                                              # 가시화(GV §6.1): 공칭 뷰가 없으면 --nominal-manifest, ①-1 쉘 뷰는 --fixed-dir 생략
                                              ("paicad_view_preview", "nominal_manifest"): "--nominal-manifest",
                                              ("paicad_shell_view_preview", "nominal_manifest"): "--nominal-manifest",
                                              ("paicad_shell_view_preview", "thickness_json"): "--thickness",
                                              ("paicad_shell_view_export", "fixed_dir"): "--fixed-dir",
                                              # DOE 그리드(DP): train 출처는 tag가 없고(①-1 쉘은 fixed도 없음) 인자 쌍째 생략
                                              ("paicad_view_grid", "tag_dir"): "--tag-dir", ("paicad_shell_view_grid", "tag_dir"): "--tag-dir",
                                              ("paicad_shell_view_grid", "fixed_dir"): "--fixed-dir"}

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
