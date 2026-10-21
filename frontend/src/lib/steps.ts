// 작업 step 표시명(백엔드 job_types.STEP_LABELS·STEP_LABELS_NATIVE와 같은 값). 서버 current_step_label이 있으면 그것이 우선이고,
// JobStep에는 표시명이 없어 현재가 아닌 step·이전 백엔드 응답에서 이 표를 쓴다(phase2 §12.9, geometry-engine.md §7.3·§8 "작업 목록").
import type { Job, JobSummary } from "../api/types";

/** native 형상 엔진 작업 step(PARAM_SET_NATIVE·4B BL_MAP) + 공용 step 일부 */
export const STEP_LABELS: Record<string, string> = {
  NP_PREP: "준비 파일 모으기",
  NP_EXTRACT: "형상 피처 추출",
  NP_TAG: "경계 노드 분류",
  BL_MAP: "baseline 변수 매칭",
  NP_REGISTER: "템플릿 등록",
  TX_PREP: "CAD 준비",
  SIMLAB_EXTRACT: "Altair 파라미터 추출",
  TX_PARSE: "파라미터 해석",
  DG_PREP: "DOE 입력 준비",
  HST_GEN_RADIOSS: "입력 생성(run별)",
  DG_SCAN: "run 폴더 확인",
  PR_PREP: "예측 준비",
  TPL_RENDER: "tpl 값 반영",
  GEOM_UPDATE: "형상 갱신",
  MESH: "메싱",
  RAD_ASSEMBLE: "입력 조립",
  EDSPY_PREDICT: "예측 실행",
  BP_PREP: "일괄 입력 준비",
  BP_GEN: "run 입력 생성",
  BP_ENQUEUE: "예측 대기열 등록",
};

/** native 엔진 작업(params.engine = native)에서 덮어쓰는 표시명(STEP_LABELS_NATIVE) */
export const STEP_LABELS_NATIVE: Record<string, string> = {
  SIMLAB_EXTRACT: "형상 피처 추출",
  HST_GEN_RADIOSS: "형상 모핑 입력 생성",
  TPL_RENDER: "샘플 값 작성",
  GEOM_UPDATE: "CAD 갱신",
  MESH: "메시 모핑·검사",
};

export function stepLabel(key: string | null | undefined, engine?: string | null): string | null {
  if (!key) return null;
  if (engine === "native" && STEP_LABELS_NATIVE[key]) return STEP_LABELS_NATIVE[key];
  return STEP_LABELS[key] ?? key;
}

/** 작업의 형상 엔진(params.engine). PARAM_SET_NATIVE는 항상 native. 요약 행(params 없음)은 job_type으로만 */
export function jobEngine(job: Pick<JobSummary, "job_type"> & { params?: Job["params"] }): string | null {
  if (job.job_type === "PARAM_SET_NATIVE") return "native";
  const e = (job.params as { engine?: unknown } | undefined)?.engine;
  return typeof e === "string" ? e : null;
}

/** 현재 step 표시명: 서버 값 우선, 없으면 표 */
export function currentStepText(job: Pick<JobSummary, "job_type" | "current_step_key" | "current_step_label"> & { params?: Job["params"] }): string | null {
  return job.current_step_label || stepLabel(job.current_step_key, jobEngine(job));
}
