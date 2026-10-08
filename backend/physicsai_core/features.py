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


def feature_status(s: Settings, hpc_configured: bool) -> dict[str, dict[str, Any]]:
    out = {}
    for name, req in FEATURES.items():
        t, r = missing_for(s, req, hpc_configured)
        out[name] = {"enabled": not t and not r, "missing": t + r}
    return out
