import type { JobState, JobType, Role } from "../api";

/** phase2.md §2.3: 스텝퍼 ①~⑤ 모두 활성 */
export const STAGES = [
  { n: 1, name: "학습데이터 생성", active: true },
  { n: 2, name: "데이터 정리", active: true },
  { n: 3, name: "데이터셋·모델", active: true },
  { n: 4, name: "단일 예측", active: true },
  { n: 5, name: "최적화", active: true },
] as const;

export const STAGE_MARK = ["", "①", "②", "③", "④", "⑤"];

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
};

/** 작업 유형 → 단계 번호(phase2.md §6.1) */
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
};
export function attentionText(code: string | null | undefined): string | null {
  if (!code) return null;
  return ATTENTION_TEXT[code] ?? code;
}
