import type { JobState, JobType, Role } from "../api";

/** 화면 단계(phase3.md §19.3, D3-62): 표시 순서 ① 학습데이터 생성 · ② 데이터 정리 · ③ 데이터셋·모델 · ④ 예측 · ⑤ 결과분석(신설) · ⑥ 최적화.
 *  n = 내부 단계 번호(jobs.stage·URL 숫자·stage4_predict/stage5_optimize 불변 — 최적화는 내부 5 = 표시 ⑥), path = URL 끝(/stage/<path>), 번호 배지·원 문자는 표시 순서에서 계산한다.
 *  결과분석은 프런트 전용(n = null, 작업 없음). */
export const STAGES = [
  { n: 1, path: "1", name: "학습데이터 생성", active: true },
  { n: 2, path: "2", name: "데이터 정리", active: true },
  { n: 3, path: "3", name: "데이터셋·모델", active: true },
  { n: 4, path: "4", name: "예측", active: true },
  { n: null, path: "analysis", name: "결과분석", active: true },
  { n: 5, path: "5", name: "최적화", active: true },
] as const;

export type StagePath = (typeof STAGES)[number]["path"];
const CIRCLED = ["", "①", "②", "③", "④", "⑤", "⑥"];

/** 표시 번호(1~6) — STAGES 표시 순서 위치 */
export const stageNo = (path: string): number => STAGES.findIndex((s) => s.path === path) + 1;
/** 표시 원 문자(①~⑥) */
export const stageCircled = (path: string): string => CIRCLED[stageNo(path)] ?? "";
/** 읽기용 이름 "⑥ 최적화" */
export const stageTitle = (path: string): string => `${stageCircled(path)} ${STAGES.find((s) => s.path === path)?.name ?? ""}`;
/** 내부 단계 번호(jobs.stage 1~5) → 표시 번호(내부 5 = 6) */
export const stageDisplayNo = (n: number): number => (n === 5 ? 6 : n);
/** 내부 단계 번호(jobs.stage 1~5) → 표시 원 문자: 내부 5(최적화) = ⑥ */
export const stageMarkOf = (n: number): string => CIRCLED[n === 5 ? 6 : n] ?? "";
/** 작업 `stage_label`(서버 값 불변)의 표시: 최적화 계열(OPTIMIZE·SURROGATE_OPT)의 "⑤"만 "⑥"으로, 나머지 불변(phase3.md §19.3) */
export function stageMark(job: { job_type: JobType; stage: number; stage_label?: string | null }): string {
  const label = job.stage_label || stageMarkOf(job.stage) || String(job.stage);
  return job.job_type === "OPTIMIZE" || job.job_type === "SURROGATE_OPT" ? label.replace(/^⑤/, "⑥") : label;
}

export const JOB_TYPE_LABEL: Record<JobType, string> = {
  DATASET_CREATE: "데이터셋 생성",
  PACKAGE_EXPORT: "학습 패키지 내보내기",
  MODEL_REGISTER: "모델 등록",
  EVALUATE: "평가",
  PREDICT: "예측",
  PREDICT_VERIFY: "PBS 검증 해석",
  // phase2.md §7.3 job_label()
  TD_EXTRACT_PARAMS: "파라미터 추출",
  TD_DOE_GEN: "DOE·Radioss 입력 생성",
  TD_SOLVE: "PBS 해석",
  TD_RESULT_IMPORT: "결과 가져오기",
  TD_RESP_EXTRACT: "run 응답 추출",
  CU_H3D_PREVIEW: "h3d 미리보기",
  CU_H3D_CURATE: "큐레이션",
  CU_T01_PREVIEW: "T01 미리보기",
  CU_T01_CURVES: "곡선 추출",
  SPDM_IMPORT: "SPDM 가져오기",
  OPTIMIZE: "최적화",
  // phase3.md §5.2 Study 관리(stage 0)
  STUDY_STORAGE_SCAN: "용량 계산",
  STUDY_CLEANUP: "Study 정리",
  // phase3.md §14.5 S9
  PREDICT_BATCH: "일괄 예측 입력 생성",
  // S10 다시 캡처
  CONTOUR_RECAPTURE: "컨투어 다시 캡처",
  // phase3.md §18.4 S13
  SURROGATE_OPT: "내장 최적화 반복",
  // phase3.md §21.3.5 S16
  FEM_VERIFY: "조립 FEM 검증",
  // phase3.md §22.3.5 S17
  PB_RESP_EXTRACT: "일괄 예측 성능 다시 추출",
  // geometry-engine.md §7.3.4 native 세트 등록·다시 준비·baseline 추가
  PARAM_SET_NATIVE: "형상 준비(native)",
  // equiv-check.md §4.5
  EQ_CHECK: "등가성 판정",
};

/** 작업 유형 → 단계 번호(phase2.md §6.1, 0 = Study 관리 phase3.md R3-1) */
export const JOB_STAGE: Record<JobType, number> = {
  DATASET_CREATE: 3,
  PACKAGE_EXPORT: 3,
  MODEL_REGISTER: 3,
  EVALUATE: 3,
  PREDICT: 4,
  PREDICT_VERIFY: 4,
  TD_EXTRACT_PARAMS: 1,
  TD_DOE_GEN: 1,
  TD_SOLVE: 1,
  TD_RESULT_IMPORT: 1,
  TD_RESP_EXTRACT: 1,
  CU_H3D_PREVIEW: 2,
  CU_H3D_CURATE: 2,
  CU_T01_PREVIEW: 2,
  CU_T01_CURVES: 2,
  SPDM_IMPORT: 2,
  OPTIMIZE: 5,
  STUDY_STORAGE_SCAN: 0,
  STUDY_CLEANUP: 0,
  PREDICT_BATCH: 4,
  CONTOUR_RECAPTURE: 4,
  SURROGATE_OPT: 5,
  FEM_VERIFY: 4,
  PB_RESP_EXTRACT: 4,
  PARAM_SET_NATIVE: 4,
  EQ_CHECK: 4,
};

export const JOB_STATE_LABEL: Record<JobState, string> = {
  QUEUED: "대기",
  RUNNING: "실행 중",
  WAITING_HPC: "PBS 대기",
  COLLECTING: "회수 중",
  SUCCEEDED: "성공",
  FAILED: "실패",
  CANCELED: "취소됨",
  INTERRUPTED: "중단됨",
};

export const ROLE_LABEL: Record<Role, string> = { general: "조회", power: "실행", admin: "관리" };

export function fmtNum(v: number | null | undefined, digits = 4): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "–";
  const a = Math.abs(v);
  if (a !== 0 && (a >= 1e5 || a < 1e-3)) return v.toExponential(Math.max(1, digits - 1));
  return Number(v.toPrecision(digits)).toString();
}

export function fmtPct(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "–";
  return `${v > 0 ? "+" : ""}${v.toFixed(1)}%`;
}

export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "–";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "–";
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getMonth() + 1}/${d.getDate()} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

export function fmtElapsed(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "";
  const s = Math.max(0, Math.floor((now - new Date(iso).getTime()) / 1000));
  if (s < 60) return `${s}초`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}분`;
  return `${Math.floor(m / 60)}시간 ${m % 60}분`;
}

export function isTerminal(s: JobState): boolean {
  return s === "SUCCEEDED" || s === "FAILED" || s === "CANCELED" || s === "INTERRUPTED";
}

/** 정수 tpl 형식(%Ni, %Nd) — 계약 §8.8 */
export function isIntegerFormat(fmt: string | undefined): boolean {
  return !!fmt && /^%[-0-9.]*[id]$/.test(fmt);
}

export function fmtBytes(n: number | null | undefined): string {
  if (n === null || n === undefined || !Number.isFinite(n)) return "–";
  const u = ["B", "KB", "MB", "GB", "TB"];
  let v = n;
  let i = 0;
  while (v >= 1024 && i < u.length - 1) {
    v /= 1024;
    i++;
  }
  return `${i === 0 ? v : v.toFixed(v >= 100 ? 0 : 1)} ${u[i]}`;
}

/**
 * PBS run 집계 한 줄(phase2.md §12.9): "PBS 12/30 완료 · 실패 1".
 * 변경 메모 C11: succeeded는 hpc 상태 SUCCEEDED, collected는 그중 회수 완료(succeeded와 겹침) → 완료 = succeeded
 */
export function hpcSummaryText(h: { total: number; succeeded: number; failed: number; collected: number } | null | undefined): string {
  if (!h) return "";
  let t = `PBS ${h.succeeded}/${h.total} 완료`;
  if (h.failed) t += ` · 실패 ${h.failed}`;
  if (h.collected) t += ` · 회수 ${h.collected}`;
  return t;
}

/** 작업 주의 코드 표시(phase2.md 변경 메모 C18 등) */
export const ATTENTION_TEXT: Record<string, string> = {
  HPC_CANCEL_FAILED: "취소 실패, 재시도 중",
  HPC_RUN_FAILED: "PBS 일부 실패",
  HPC_SUBMISSION_UNKNOWN: "SCX 제출 확인 필요",
};
export function attentionText(code: string | null | undefined): string | null {
  if (!code) return null;
  return ATTENTION_TEXT[code] ?? code;
}
