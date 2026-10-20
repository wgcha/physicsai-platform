"""2차 기능 활성 판정(phase2 §12.1 `features`, §6.1.1 사전조건). 필요한 템플릿·자원·altair 키 기준."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from .config import Settings, derived_paicad_path, effective_altair


@dataclass(frozen=True)
class FeatureReq:
    templates: tuple[str, ...] = ()
    altair: tuple[str, ...] = ()
    resources: tuple[str, ...] = ()
    launchers: tuple[str, ...] = ()
    needs_hpc: bool = False
    needs_spdm: bool = False


FEATURES: dict[str, FeatureReq] = {
    "train_extract": FeatureReq(("simlab_extract_params",), ("simlab_path",), ("batchrun_dir", "pyd_dir"), ("extract_params",)),
    "train_tpl": FeatureReq((), (), ("simlab_tpl_template",)),
    "train_doe": FeatureReq(("hst_gen_radioss",), ("hyperstudy_path",),
                            ("doe_design_type_json", "hypermesh_include_tcl", "batchrun_dir", "pyd_dir"), ("gen_radioss",)),
    # phase3 §23.8 S18: ① 플랫폼 DOE 생성 = geom_update + SimLab. mesh가 {include_tcl}·{hw}를 쓰면 자원·hw도(train_doe_platform_missing)
    "train_doe_platform": FeatureReq(("geom_update",), ("simlab_path",)),
    "train_solve": FeatureReq(needs_hpc=True),
    "train_import": FeatureReq(),
    "train_resp": FeatureReq(("response_extract",), ("hw_exe_path",)),
    "curation_h3d": FeatureReq(("h3d_preview", "hvtrans_curate"), ("hw_exe_path", "hvtrans_exe_path"), ("preview_h3d_tcl",)),
    "curation_t01": FeatureReq(("t01_preview", "t01_curve_export"), ("hw_exe_path",), ("preview_hg_tcl", "curate_hg_tcl")),
    "spdm_import": FeatureReq(needs_spdm=True),
    "optimize": FeatureReq(("hst_optimization",), ("hstpy_path", "simlab_path"),
                           ("hypermesh_include_tcl", "extract_minmax_tcl", "batchrun_dir", "pyd_dir"), ("optimization",)),
    # 1차 확정 템플릿: 설정 파일에 키가 없으면(예시 일부만 복사) 그 기능만 비활성
    "dataset_create": FeatureReq(("edspy_create_dataset",)),
    "evaluate": FeatureReq(("edspy_score",)),
    "predict": FeatureReq(("edspy_predict", "contour_preview")),  # phase3 §11.4: 준비된 입력 예측 조건
    # phase3 §11.4: 파라미터로 형상 생성(기존 체인). mesh가 {include_tcl}을 쓰면 hypermesh_include_tcl도 필요(predict_parametric_missing)
    "predict_parametric": FeatureReq(("geom_update", "edspy_predict", "contour_preview")),
    # phase3 §14.4: 메시 단독(mesh_only) 템플릿 예측 — geom_update만(MESH SKIPPED라 include TCL 불필요)
    "predict_mesh_only": FeatureReq(("geom_update", "edspy_predict", "contour_preview")),
    # phase3 §14.6: 예측 응답 추출. 템플릿이 {extract_tcl}을 쓰면 resources.extract_minmax_tcl도 필요(predict_responses_missing)
    "predict_responses": FeatureReq(("response_extract",)),
    # phase3 §15 S10: 예측 컨투어 캡처. capture.enabled·캡처 TCL은 contour_capture_missing
    "contour_capture": FeatureReq(("contour_capture",), ("hw_exe_path",)),
    # phase3 §18.2 S13: 플랫폼 내장 최적화 — numpy·scipy + surrogate_opt.enabled + (parametric 또는 mesh_only 예측). optimize_builtin_missing
    "optimize_builtin": FeatureReq(),
    # geometry-engine.md §7.1: native 형상 엔진 — paicad_update·paicad_morph·paicad_check(또는 paicad_run) 비null + 실행 파일 존재
    "geometry_native": FeatureReq(),
    # phase3 §21.3.8 S16: 조립 FEM 검증 = fem_verify.enabled + HPC 연결. rebuild는 + mesh 템플릿·include TCL(fem_verify_missing)
    "fem_verify": FeatureReq(needs_hpc=True),
    "fem_verify_rebuild": FeatureReq(needs_hpc=True),
}

# opt-native §4.1(ON-1): HyperStudy(hstbatch·hstpy) 레거시 기능 — 설정했을 때만 켜지고, 미설정이면 화면에서 숨기며 점검은 SKIP.
# 이 밖의 기능 판정(FEATURES·JOB_FEATURE·_SPECIAL_MISSING)은 HyperStudy 키를 참조하지 않는다(정적 시험 V-ON-1).
LEGACY_FEATURES = frozenset({"train_doe", "optimize"})
LEGACY_JOBS = frozenset({"OPTIMIZE"})
HYPERSTUDY_ALTAIR_KEYS = ("hyperstudy_path", "hstpy_path", "altair_home")
HYPERSTUDY_TEMPLATES = ("hst_gen_radioss", "hst_optimization")
HYPERSTUDY_LAUNCHERS = ("gen_radioss", "optimization")

# 작업 유형 → 기능(생성 시 사전조건 확인용). 템플릿/자원은 그 작업 step이 실제로 쓰는 것만.
JOB_FEATURE: dict[str, FeatureReq] = {
    "TD_EXTRACT_PARAMS": FEATURES["train_extract"],
    "TD_DOE_GEN": FeatureReq(),  # phase3 §23.8: 생성 방식별(train_doe | train_doe_platform)로 prepare()가 확인
    "TD_SOLVE": FeatureReq(),
    "TD_RESULT_IMPORT": FeatureReq(),
    "TD_RESP_EXTRACT": FEATURES["train_resp"],
    "CU_H3D_PREVIEW": FeatureReq(("h3d_preview",), ("hw_exe_path",), ("preview_h3d_tcl",)),
    "CU_H3D_CURATE": FeatureReq(("hvtrans_curate",), ("hvtrans_exe_path",)),
    "CU_T01_PREVIEW": FeatureReq(("t01_preview",), ("hw_exe_path",), ("preview_hg_tcl",)),
    "CU_T01_CURVES": FeatureReq(("t01_curve_export",), ("hw_exe_path",), ("curate_hg_tcl",)),
    "SPDM_IMPORT": FeatureReq(),
    "OPTIMIZE": FEATURES["optimize"],
    "DATASET_CREATE": FEATURES["dataset_create"],
    "EVALUATE": FEATURES["evaluate"],
    "PREDICT": FEATURES["predict"],
    "PREDICT_VERIFY": FEATURES["predict"],
    # phase3 §14.5: 두 입력 종류 공통 조건(geom_update). assembly의 include TCL 조건은 predict_parametric_missing으로 따로 확인
    "PREDICT_BATCH": FEATURES["predict_mesh_only"],
}


def missing_for(s: Settings, req: FeatureReq, hpc_configured: bool | None = None) -> tuple[list[str], list[str]]:
    """(null 템플릿 키, 비어 있는 자원·altair 키)."""
    tmpl = [f"commands.{t}" for t in req.templates if getattr(s.commands, t) is None]
    alt = effective_altair(s)
    res = [f"altair.{k}" for k in req.altair if not alt.get(k)]
    res += [f"resources.{k}" for k in req.resources if not getattr(s.resources, k)]
    res += [f"resources.launchers.{k}" for k in req.launchers if k not in s.resources.launchers]
    if req.needs_hpc and hpc_configured is False:
        res.append("hpc.gateway")
    if req.needs_spdm and not s.storage.spdm_roots:
        res.append("storage.spdm_roots")
    return tmpl, res


def mesh_uses_include_tcl(s: Settings) -> bool:
    """commands.mesh가 {include_tcl}을 쓰는지(원본 m_2 HyperMesh 형태)."""
    from .commands import parse_placeholders

    for el in s.commands.mesh or []:
        try:
            if "include_tcl" in parse_placeholders(el):
                return True
        except ValueError:
            continue
    return False


def predict_parametric_missing(s: Settings) -> tuple[list[str], list[str]]:
    """④ parametric 예측에 빠진 (템플릿, 자원) 키(phase3 §11.4)."""
    tmpl, res = missing_for(s, FEATURES["predict_parametric"], None)
    if mesh_uses_include_tcl(s) and not s.resources.hypermesh_include_tcl:
        res.append("resources.hypermesh_include_tcl")
    return tmpl, res


def train_doe_platform_missing(s: Settings) -> tuple[list[str], list[str]]:
    """① 플랫폼 DOE 생성에 빠진 (템플릿, 자원) 키(phase3 §23.8). HyperStudy 자원은 필요 없다."""
    from .commands import template_uses

    tmpl, res = missing_for(s, FEATURES["train_doe_platform"], None)
    if mesh_uses_include_tcl(s) and not s.resources.hypermesh_include_tcl:
        res.append("resources.hypermesh_include_tcl")
    if template_uses(s.commands.mesh, "hw") and not effective_altair(s).get("hw_exe_path"):
        res.append("altair.hw_exe_path")
    return tmpl, res


def predict_mesh_only_missing(s: Settings) -> tuple[list[str], list[str]]:
    """④ mesh_only 템플릿 예측에 빠진 (템플릿, 자원) 키(phase3 §14.4) — commands.mesh·include TCL과 무관."""
    return missing_for(s, FEATURES["predict_mesh_only"], None)


def response_extract_uses_tcl(s: Settings) -> bool:
    """commands.response_extract가 {extract_tcl}(원본 ⑤ m_4 방식, phase3 §14.6)을 쓰는지."""
    from .commands import RESPONSE_EXTRACT_TCL_PLACEHOLDER, template_uses

    return template_uses(s.commands.response_extract, RESPONSE_EXTRACT_TCL_PLACEHOLDER)


def predict_responses_missing(s: Settings) -> tuple[list[str], list[str]]:
    """④ 예측 응답 추출에 빠진 (템플릿, 자원) 키(phase3 §14.6). 옛 {out_csv} 템플릿은 TCL 자원 불필요."""
    tmpl, res = missing_for(s, FEATURES["predict_responses"], None)
    if response_extract_uses_tcl(s) and not s.resources.extract_minmax_tcl:
        res.append("resources.extract_minmax_tcl")
    return tmpl, res


def contour_capture_missing(s: Settings) -> tuple[list[str], list[str]]:
    """④ 컨투어 캡처에 빠진 (템플릿, 설정·자원) 키(phase3 §15): 템플릿·altair.hw_exe_path + capture.enabled·캡처 TCL."""
    from .config.schema_capture import capture_missing

    tmpl, res = missing_for(s, FEATURES["contour_capture"], None)
    return tmpl, res + capture_missing(s)


def optimize_builtin_missing(s: Settings) -> tuple[list[str], list[str]]:
    """⑤ 내장 최적화에 빠진 (템플릿, 설정·모듈) 키(phase3 §18.2). 모듈은 find_spec만(API가 numpy를 불러오지 않음).
    예측 기능은 템플릿 종류 둘 중 하나만 있어도 켠다(종류별 확인은 생성 때 — TEMPLATE_NOT_CONFIGURED)."""
    from .stage5_optimize.surrogate import missing_modules

    res = [f"python.{m}" for m in missing_modules()]
    if not s.surrogate_opt.enabled:
        res.append("surrogate_opt.enabled")
    pt, pr = predict_parametric_missing(s)
    mt, mr = predict_mesh_only_missing(s)
    tmpl: list[str] = []
    nt, nr = geometry_native_missing(s)  # native 엔진 세트는 geom_update 없이 paicad_*로 형상을 만든다(§7.1)
    qt, qr = missing_for(s, FEATURES["predict"], None)
    if (pt or pr) and (mt or mr) and (nt or nr or qt or qr):
        tmpl, res = list(dict.fromkeys(pt + mt)), res + list(dict.fromkeys(pr + mr))
    return tmpl, res


def geometry_native_missing(s: Settings) -> tuple[list[str], list[str]]:
    """native 형상 엔진에 빠진 (템플릿, 실행 파일) 키(geometry-engine.md §7.1)."""
    # ④ 단건 예측(GEOM_UPDATE·MESH)이 단계별 명령을 쓰므로 update·morph·check는 paicad_run과 무관하게 필요하다
    tmpl = [f"commands.{k}" for k in ("paicad_extract", "paicad_tag", "paicad_update", "paicad_morph", "paicad_check")
            if getattr(s.commands, k) is None]
    res: list[str] = []
    exe = derived_paicad_path(s)
    if not exe or not os.path.isfile(exe):
        res.append("geometry.paicad_path")
    return tmpl, res


def geometry_status(s: Settings) -> dict[str, Any]:
    """`/status.geometry`: {engine_default, native_available, reason|null}(§7.1). reason은 한국어."""
    t, r = geometry_native_missing(s)
    reason = None
    if r:
        reason = "paicad 실행 파일을 찾을 수 없습니다 — paicad 설치 또는 geometry.paicad_path를 확인하세요"
    elif t:
        reason = "형상 명령 설정이 비어 있습니다: " + ", ".join(t)
    return {"engine_default": s.geometry.engine, "native_available": not t and not r, "reason": reason}


_SPECIAL_MISSING = {
    "geometry_native": geometry_native_missing,
    "optimize_builtin": optimize_builtin_missing,
    "contour_capture": contour_capture_missing,
    "predict_parametric": predict_parametric_missing,
    "predict_mesh_only": predict_mesh_only_missing,
    "predict_responses": predict_responses_missing,
    "train_doe_platform": train_doe_platform_missing,
}


def fem_verify_missing(s: Settings, hpc_configured: bool | None, *, rebuild: bool = False) -> tuple[list[str], list[str]]:
    """④ 조립 FEM 검증에 빠진 (템플릿, 설정) 키(phase3 §21.3.8). rebuild = 메시 교체(m_2) 조건까지."""
    tmpl, res = missing_for(s, FEATURES["fem_verify"], hpc_configured)
    if not s.fem_verify.enabled:
        res.insert(0, "fem_verify.enabled")
    if rebuild:
        if s.commands.mesh is None:
            tmpl.append("commands.mesh")
        if mesh_uses_include_tcl(s) and not s.resources.hypermesh_include_tcl:
            res.append("resources.hypermesh_include_tcl")
    return tmpl, res


def feature_status(s: Settings, hpc_configured: bool) -> dict[str, dict[str, Any]]:
    out = {}
    for name, req in FEATURES.items():
        fn = _SPECIAL_MISSING.get(name)
        if name in ("fem_verify", "fem_verify_rebuild"):
            t, r = fem_verify_missing(s, hpc_configured, rebuild=name == "fem_verify_rebuild")
        else:
            t, r = fn(s) if fn else missing_for(s, req, hpc_configured)
        out[name] = {"enabled": not t and not r, "missing": t + r}
        if name in LEGACY_FEATURES:  # opt-native §4.2 — 그 밖은 기본 false(생략)
            out[name]["legacy"] = True
    return out
