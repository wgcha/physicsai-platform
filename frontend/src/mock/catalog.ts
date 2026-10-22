// 목 공용 상수(2차): 단계 표시·기능 → missing 키·작업 → 기능·DOE 유형. data.ts·phase2.ts가 재노출.
import type { DoeType, FeatureKey, JobType } from "../api/types";

export const STAGE_LABEL: Record<JobType, string> = {
  DATASET_CREATE: "③-1",
  PACKAGE_EXPORT: "③-2",
  MODEL_REGISTER: "③-4",
  EVALUATE: "③-5",
  PREDICT: "④",
  PREDICT_VERIFY: "④",
  TD_EXTRACT_PARAMS: "①-1",
  TD_DOE_GEN: "①-3",
  TD_SOLVE: "①-4",
  TD_RESULT_IMPORT: "①-5",
  TD_RESP_EXTRACT: "①-6",
  SPDM_IMPORT: "②-0",
  CU_H3D_PREVIEW: "②-1",
  CU_H3D_CURATE: "②-2",
  CU_T01_PREVIEW: "②-3",
  CU_T01_CURVES: "②-4",
  OPTIMIZE: "⑤",
  STUDY_STORAGE_SCAN: "관리",
  STUDY_CLEANUP: "관리",
  PREDICT_BATCH: "④",
  CONTOUR_RECAPTURE: "④",
  CONTOUR_3D: "④",
  SURROGATE_OPT: "⑤",
  FEM_VERIFY: "④",
  PB_RESP_EXTRACT: "④",
  PARAM_SET_NATIVE: "④",
  EQ_CHECK: "⑤",
};

/** 기능 → 비활성일 때 missing 키(phase2.md §12.1) */
export const FEATURE_MISSING: Record<FeatureKey, string[]> = {
  train_extract: ["resources.pyd_dir", "commands.simlab_extract_params"],
  train_tpl: ["resources.simlab_tpl_template"],
  train_doe: ["resources.doe_design_type_json", "resources.hypermesh_include_tcl", "resources.launchers.gen_radioss"],
  train_solve: ["hpc.mode"],
  train_import: ["hpc.transfer.collect_patterns"],
  train_resp: ["commands.response_extract"],
  curation_h3d: ["resources.preview_h3d_tcl", "altair.hvtrans_exe_path"],
  curation_t01: ["resources.preview_hg_tcl", "resources.curate_hg_tcl"],
  spdm_import: ["storage.spdm_roots"],
  optimize: ["resources.extract_minmax_tcl", "resources.launchers.optimization", "altair.hstpy_path"],
  dataset_create: ["altair.edspy_path"],
  evaluate: ["altair.edspy_path"],
  predict: ["altair.edspy_path"],
  // S6(phase3.md §11.4): parametric 체인 조건. predict는 prepared 조건(edspy_predict·contour_preview)
  predict_parametric: ["commands.geom_update", "resources.hypermesh_include_tcl"],
  // S9(phase3.md §14.4·§14.6): mesh_only 체인(include TCL 불필요)·응답 추출(새 방식)
  predict_mesh_only: ["commands.geom_update"],
  predict_responses: ["commands.response_extract", "resources.extract_minmax_tcl"],
  // S10(phase3.md §15.5): 컨투어 캡처 — 목의 캡처 동작은 MockOptions.capture가 정한다
  contour_capture: ["commands.contour_capture", "altair.hw_exe_path"],
  // S13(phase3.md §18.2): 플랫폼 내장 최적화 — numpy·scipy 설치 여부
  optimize_builtin: ["python.numpy", "python.scipy"],
  // S16(phase3.md §21.3.8): 조립 FEM 검증 — 해석 연결(HPC) + 메시 교체는 mesh 템플릿·include TCL
  fem_verify: ["hpc.mode"],
  fem_verify_rebuild: ["commands.mesh", "resources.hypermesh_include_tcl"],
  // geometry-engine.md §7.1: native 형상 엔진(paicad 실행 파일)
  geometry_native: ["geometry.paicad_exe", "commands.paicad_extract"],
  // shell-morph.md §8.1 쉘 판금 비드·geometry-view.md §6.1 3D 가시화·§13 결과 3D 컨투어(백엔드 features.py와 같은 키)
  geometry_native_shell: ["commands.paicad_shell_extract", "geometry.paicad_path"],
  geometry_view: ["geometry.view.enabled", "commands.paicad_view_export"],
  geometry_view_shell: ["geometry.view.enabled", "commands.paicad_shell_view_export"],
  contour3d: ["contour3d.enabled", "commands.contour_extract", "resources.contour_extract_tcl"],
  // S18(phase3.md §23.8): ① 플랫폼 생성 — geom_update 템플릿 + SimLab 경로(HyperStudy 자원은 필요 없음)
  train_doe_platform: ["commands.geom_update", "altair.simlab_path"],
  // equiv-check.md §5.3: 등가성 판정(항상 사용 가능 — enabled)·판정 중 추출(hw·응답 TCL·T01 곡선)
  equiv_check: ["equiv_check.enabled"],
  equiv_check_extract: ["commands.response_extract", "commands.t01_curve_export", "altair.hw_exe_path"],
  // mcp.md §4.5: API 토큰·MCP(mcp.enabled)
  mcp: ["mcp.enabled"],
  mcp_http: ["mcp.enabled"],
};
export const ALL_FEATURES = Object.keys(FEATURE_MISSING) as FeatureKey[];

export const FEATURE_OF: Partial<Record<JobType, FeatureKey>> = {
  DATASET_CREATE: "dataset_create",
  EVALUATE: "evaluate",
  PREDICT: "predict",
  TD_EXTRACT_PARAMS: "train_extract",
  TD_DOE_GEN: "train_doe",
  TD_SOLVE: "train_solve",
  TD_RESULT_IMPORT: "train_import",
  TD_RESP_EXTRACT: "train_resp",
  CU_H3D_PREVIEW: "curation_h3d",
  CU_H3D_CURATE: "curation_h3d",
  CU_T01_PREVIEW: "curation_t01",
  CU_T01_CURVES: "curation_t01",
  SPDM_IMPORT: "spdm_import",
  OPTIMIZE: "optimize",
};

/** HyperStudy 유형 정의 파일(DATA_doe_design_type.json)의 4개 그대로 + S15 §20.6 desc_id·recommended(설정 train_data.recommended_doe_type = LHS)·influence_class.
 *  목록 첫 항목은 FullFact — 기본 선택이 첫 항목이 아니라 recommended임을 보인다. */
export const DOE_TYPES: DoeType[] = [
  { label: "FullFact", value: "TYPE_FULLFACT", default_runs: 9, runs_editable: false, fields: [], desc_id: "hs_fullfact", recommended: false, influence_class: "formal" },
  {
    label: "FracFact", value: "TYPE_FRACFACT", default_runs: 8, runs_editable: false,
    fields: [{ key: "RESOLUTION", label: "Resolution", type: "combo", items: ["3", "4", "5"], default: "3" }],
    desc_id: "hs_fracfact", recommended: false, influence_class: "reference",
  },
  {
    label: "LatinHyperCube", value: "TYPE_LATINHYPERCUBE", default_runs: 30, runs_editable: true,
    fields: [{ key: "RANDOM_SEED", label: "Random Seed", type: "int", default: 1, min: 0, max: 10000 }],
    desc_id: "hs_lhs", recommended: true, influence_class: "formal",
  },
  {
    label: "Sobol", value: "TYPE_SOBOL", default_runs: 32, runs_editable: true,
    fields: [
      { key: "SEQUENCE_OFFSET", label: "Sequence Offset", type: "int", default: 1 },
      { key: "SCRAMBLE", label: "Scramble", type: "bool", default: false },
      { key: "SEED", label: "Seed", type: "int", default: 0 },
    ],
    desc_id: "hs_sobol", recommended: false, influence_class: "formal",
  },
];
