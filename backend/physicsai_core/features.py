"""2차 기능 활성 판정(phase2 §12.1 `features`, §6.1.1 사전조건). 필요한 템플릿·자원·altair 키 기준."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import Settings, effective_altair


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
}

# 작업 유형 → 기능(생성 시 사전조건 확인용). 템플릿/자원은 그 작업 step이 실제로 쓰는 것만.
JOB_FEATURE: dict[str, FeatureReq] = {
    "TD_EXTRACT_PARAMS": FEATURES["train_extract"],
    "TD_DOE_GEN": FEATURES["train_doe"],
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


_SPECIAL_MISSING = {
    "contour_capture": contour_capture_missing,
    "predict_parametric": predict_parametric_missing,
    "predict_mesh_only": predict_mesh_only_missing,
    "predict_responses": predict_responses_missing,
}


def feature_status(s: Settings, hpc_configured: bool) -> dict[str, dict[str, Any]]:
    out = {}
    for name, req in FEATURES.items():
        fn = _SPECIAL_MISSING.get(name)
        t, r = fn(s) if fn else missing_for(s, req, hpc_configured)
        out[name] = {"enabled": not t and not r, "missing": t + r}
    return out
