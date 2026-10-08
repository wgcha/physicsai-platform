import type { JobState, JobType, Role } from "../api";

export const STAGES = [
  { n: 1, name: "학습데이터 생성", active: false },
  { n: 2, name: "데이터 정리", active: false },
  { n: 3, name: "데이터셋·모델", active: true },
  { n: 4, name: "단일 예측", active: true },
  { n: 5, name: "최적화", active: false },
] as const;

export const STAGE_MARK = ["", "①", "②", "③", "④", "⑤"];

export const JOB_TYPE_LABEL: Record<JobType, string> = {
  DATASET_CREATE: "데이터셋 생성",
  PACKAGE_EXPORT: "학습 패키지 내보내기",
  MODEL_REGISTER: "모델 등록",
  EVALUATE: "평가",
  PREDICT: "예측",
  PREDICT_VERIFY: "PBS 검증 해석",
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
