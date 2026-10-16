// 목 작업 step 체인·표시 이름·작업 기본값(makeSteps·baseJob). data.ts가 재노출.
import { JOB_STAGE } from "../lib/format";
import type { Job, JobStep, JobType } from "../api/types";
import { iso } from "./base";

export const STEP_CHAINS: Record<JobType, { key: string; kind: JobStep["kind"] }[]> = {
  DATASET_CREATE: [
    { key: "DS_SCAN", kind: "INTERNAL" },
    { key: "DS_YAML", kind: "INTERNAL" },
    { key: "EDSPY_DATASET_TRAIN", kind: "LOCAL" },
    { key: "EDSPY_DATASET_EVAL", kind: "LOCAL" },
    { key: "DS_REGISTER", kind: "INTERNAL" },
  ],
  PACKAGE_EXPORT: [
    { key: "PKG_COPY", kind: "INTERNAL" },
    { key: "PKG_TEXT", kind: "INTERNAL" },
  ],
  MODEL_REGISTER: [
    { key: "MR_VALIDATE", kind: "INTERNAL" },
    { key: "MR_COPY", kind: "INTERNAL" },
    { key: "MR_PARSE_LOG", kind: "INTERNAL" },
    { key: "MR_REGISTER", kind: "INTERNAL" },
  ],
  EVALUATE: [
    { key: "EV_PREP", kind: "INTERNAL" },
    { key: "EDSPY_SCORE", kind: "LOCAL" },
    { key: "EV_PARSE", kind: "INTERNAL" },
  ],
  PREDICT: [
    { key: "PR_PREP", kind: "INTERNAL" },
    { key: "TPL_RENDER", kind: "INTERNAL" },
    { key: "GEOM_UPDATE", kind: "LOCAL" },
    { key: "MESH", kind: "LOCAL" },
    { key: "RAD_ASSEMBLE", kind: "INTERNAL" },
    { key: "EDSPY_PREDICT", kind: "LOCAL" },
    { key: "CONTOUR_PREVIEW", kind: "LOCAL" },
    { key: "CURVE_PICK", kind: "INTERNAL" },
    { key: "RESPONSE_EXTRACT", kind: "LOCAL" },
    { key: "RESPONSE_TABLE", kind: "INTERNAL" },
  ],
  PREDICT_VERIFY: [
    { key: "PV_PREP", kind: "INTERNAL" },
    { key: "HPC_SUBMIT", kind: "HPC_SUBMIT" },
    { key: "HPC_WAIT", kind: "HPC_WAIT" },
    { key: "COLLECT", kind: "COLLECT" },
    { key: "PV_EXTRACT", kind: "LOCAL" },
    { key: "PV_TABLE", kind: "INTERNAL" },
  ],
  // phase2.md §6.1
  TD_EXTRACT_PARAMS: [
    { key: "TX_PREP", kind: "INTERNAL" },
    { key: "SIMLAB_EXTRACT", kind: "LOCAL" },
    { key: "TX_PARSE", kind: "INTERNAL" },
  ],
  TD_DOE_GEN: [
    { key: "DG_PREP", kind: "INTERNAL" },
    { key: "HST_GEN_RADIOSS", kind: "LOCAL" },
    { key: "DG_SCAN", kind: "INTERNAL" },
  ],
  TD_SOLVE: [
    { key: "TS_PREP", kind: "INTERNAL" },
    { key: "HPC_SUBMIT", kind: "HPC_SUBMIT" },
    { key: "HPC_WAIT", kind: "HPC_WAIT" },
    { key: "COLLECT", kind: "COLLECT" },
    { key: "TS_REGISTER", kind: "INTERNAL" },
  ],
  TD_RESULT_IMPORT: [
    { key: "RI_SCAN", kind: "INTERNAL" },
    { key: "RI_COPY", kind: "INTERNAL" },
    { key: "RI_REGISTER", kind: "INTERNAL" },
  ],
  TD_RESP_EXTRACT: [
    { key: "RX_PREP", kind: "INTERNAL" },
    { key: "RESPONSE_EXTRACT_RUNS", kind: "LOCAL" },
    { key: "RX_TABLE", kind: "INTERNAL" },
  ],
  CU_H3D_PREVIEW: [
    { key: "CP_PREP", kind: "INTERNAL" },
    { key: "HW_PREVIEW_H3D", kind: "LOCAL" },
    { key: "CP_PARSE", kind: "INTERNAL" },
  ],
  CU_H3D_CURATE: [
    { key: "HC_PREP", kind: "INTERNAL" },
    { key: "HVTRANS_CURATE", kind: "LOCAL" },
    { key: "HC_REGISTER", kind: "INTERNAL" },
  ],
  CU_T01_PREVIEW: [
    { key: "TP_PREP", kind: "INTERNAL" },
    { key: "HW_PREVIEW_T01", kind: "LOCAL" },
    { key: "TP_PARSE", kind: "INTERNAL" },
  ],
  CU_T01_CURVES: [
    { key: "TC_PREP", kind: "INTERNAL" },
    { key: "HW_CURVE_EXPORT", kind: "LOCAL" },
    { key: "TC_REGISTER", kind: "INTERNAL" },
  ],
  SPDM_IMPORT: [
    { key: "SI_SCAN", kind: "INTERNAL" },
    { key: "SI_COPY", kind: "INTERNAL" },
    { key: "SI_REGISTER", kind: "INTERNAL" },
  ],
  OPTIMIZE: [
    { key: "OP_PREP", kind: "INTERNAL" },
    { key: "HST_OPTIMIZE", kind: "LOCAL" },
    { key: "OP_SUMMARY", kind: "INTERNAL" },
  ],
  STUDY_STORAGE_SCAN: [
    { key: "SS_WALK", kind: "INTERNAL" },
    { key: "SS_CLASSIFY", kind: "INTERNAL" },
  ],
  STUDY_CLEANUP: [
    { key: "SC_VALIDATE", kind: "INTERNAL" },
    { key: "SC_MOVE", kind: "INTERNAL" },
    { key: "SC_RECORD", kind: "INTERNAL" },
  ],
  // phase3.md §14.5 S9
  PREDICT_BATCH: [
    { key: "BP_PREP", kind: "INTERNAL" },
    { key: "BP_GEN", kind: "LOCAL" },
    { key: "BP_ENQUEUE", kind: "INTERNAL" },
  ],
  // S10 다시 캡처(목 가정)
  CONTOUR_CAPTURE: [
    { key: "CC_PREP", kind: "INTERNAL" },
    { key: "HV_CAPTURE", kind: "LOCAL" },
  ],
};

/** step_key → 한국어 표시(백엔드 current_step_label 흉내) */
export const STEP_LABEL: Record<string, string> = {
  DS_SCAN: "h3d 확인", DS_YAML: "설정 작성", EDSPY_DATASET_TRAIN: "학습 데이터 변환", EDSPY_DATASET_EVAL: "평가 데이터 변환", DS_REGISTER: "등록",
  PKG_COPY: "복사", PKG_TEXT: "명령 작성", MR_VALIDATE: "검사", MR_COPY: "복사", MR_PARSE_LOG: "로그 해석", MR_REGISTER: "등록",
  EV_PREP: "준비", EDSPY_SCORE: "점수 계산", EV_PARSE: "결과 해석",
  PR_PREP: "준비", TPL_RENDER: "tpl 렌더", GEOM_UPDATE: "형상 갱신", MESH: "메싱", RAD_ASSEMBLE: "입력파일", EDSPY_PREDICT: "예측", CONTOUR_PREVIEW: "컨투어", CURVE_PICK: "커브", RESPONSE_EXTRACT: "응답 추출", RESPONSE_TABLE: "응답 표",
  PV_PREP: "준비", HPC_SUBMIT: "PBS 제출", HPC_WAIT: "PBS 대기", COLLECT: "결과 회수", PV_EXTRACT: "응답 추출", PV_TABLE: "응답 표",
  TX_PREP: "CAD 복사", SIMLAB_EXTRACT: "SimLab 추출", TX_PARSE: "XML 해석",
  DG_PREP: "입력 준비", HST_GEN_RADIOSS: "HyperStudy 입력 생성", DG_SCAN: "run 확인",
  TS_PREP: "run 준비", TS_REGISTER: "회수 등록",
  RI_SCAN: "run 매칭", RI_COPY: "복사", RI_REGISTER: "등록",
  RX_PREP: "준비", RESPONSE_EXTRACT_RUNS: "run 응답 추출", RX_TABLE: "표 작성",
  CP_PREP: "준비", HW_PREVIEW_H3D: "h3d 구조 읽기", CP_PARSE: "해석",
  HC_PREP: "cfg 작성", HVTRANS_CURATE: "hvtrans 큐레이션", HC_REGISTER: "등록",
  TP_PREP: "준비", HW_PREVIEW_T01: "T01 구조 읽기", TP_PARSE: "해석",
  TC_PREP: "준비", HW_CURVE_EXPORT: "곡선 내보내기", TC_REGISTER: "등록",
  SI_SCAN: "SPDM 확인", SI_COPY: "복사", SI_REGISTER: "등록",
  OP_PREP: "준비", HST_OPTIMIZE: "HyperStudy 최적화", OP_SUMMARY: "결과 정리",
  SS_WALK: "파일 확인", SS_CLASSIFY: "정리 후보 분류", SC_VALIDATE: "정리 대상 확인", SC_MOVE: "백업 폴더로 이동", SC_RECORD: "정리 기록",
  BP_PREP: "입력 준비", BP_GEN: "입력 생성", BP_ENQUEUE: "예측 등록",
  CC_PREP: "캡처 준비", HV_CAPTURE: "HyperView 캡처",
};

/** 1차 기본 설정에서 SKIPPED가 되는 step(템플릿 null) */
export const SKIPPED_BY_DEFAULT = new Set(["MESH", "RESPONSE_EXTRACT"]);

export function makeSteps(type: JobType, doneCount: number, runningIdx: number | null, opts: { failedIdx?: number } = {}): JobStep[] {
  return STEP_CHAINS[type].map((s, i) => {
    let state: JobStep["state"] = "PENDING";
    if (opts.failedIdx !== undefined && i === opts.failedIdx) state = "FAILED";
    else if (opts.failedIdx !== undefined && i > opts.failedIdx) state = "SKIPPED";
    else if (i < doneCount) state = SKIPPED_BY_DEFAULT.has(s.key) ? "SKIPPED" : "SUCCEEDED";
    else if (runningIdx !== null && i === runningIdx) state = "RUNNING";
    return {
      step_no: i + 1, step_key: s.key, kind: s.kind, state,
      progress_pct: state === "RUNNING" ? null : null, progress_label: null,
      started_at: state === "PENDING" ? null : iso(5), finished_at: state === "SUCCEEDED" ? iso(1) : null,
      exit_code: state === "SUCCEEDED" && s.kind === "LOCAL" ? 0 : null,
      failure_code: state === "FAILED" ? "EXIT_NONZERO" : null, failure_message: state === "FAILED" ? "종료코드 1" : null,
    };
  });
}

export function baseJob(p: Partial<Job> & Pick<Job, "id" | "study_id" | "project_id" | "study_title" | "job_type" | "state">): Job {
  const lane = ["PACKAGE_EXPORT", "MODEL_REGISTER", "TD_RESULT_IMPORT", "SPDM_IMPORT", "STUDY_STORAGE_SCAN", "STUDY_CLEANUP"].includes(p.job_type) ? "LIGHT" : "SLOT";
  return {
    stage: JOB_STAGE[p.job_type],
    lane,
    created_by: "u-power",
    created_by_name: "김연구",
    queue_position: null,
    progress_pct: null,
    progress_label: null,
    cancel_requested: false,
    created_at: iso(10),
    started_at: null,
    params: {},
    result: null,
    warnings: [],
    steps: makeSteps(p.job_type, 0, null),
    failure_code: null,
    failure_message: null,
    finished_at: null,
    retry_of_job_id: null,
    version: 1,
    can_cancel: false,
    can_retry: false,
    ...p,
  } as Job;
}
