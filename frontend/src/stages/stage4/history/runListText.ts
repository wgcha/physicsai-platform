// ④ 실행 목록·실행 결과 공용 문구(phase3 §21.2.3). 화면 로직 없는 순수 함수.
import type { PredictRunSummary } from "../../../api/predictRuns";
import { fmtNum } from "../../../lib/format";

/** 값 앞 3개 "THK_1=4 · RIB_N=6 …" (준비된 입력은 값 없음 → 빈 문자열) */
export function valuesText(values: Record<string, number>, max = 3): string {
  const e = Object.entries(values ?? {});
  if (!e.length) return "";
  return e.slice(0, max).map(([k, v]) => `${k}=${fmtNum(v)}`).join(" · ") + (e.length > max ? " …" : "");
}

/** 첫 응답 "MaxStress 152.3 MPa"(없으면 빈 문자열) */
export function firstResponseText(r: PredictRunSummary): string {
  const x = r.responses[0];
  if (!x || x.predicted == null) return "";
  return `${x.name} ${fmtNum(x.predicted)}${x.unit ? ` ${x.unit}` : ""}`;
}

export function baseName(p: string | null | undefined): string {
  return (p ?? "").split(/[\\/]/).filter(Boolean).pop() ?? "";
}

/** 템플릿 label(없으면 id) 또는 입력 파일 이름 */
export function sourceLabel(r: PredictRunSummary): string {
  if (r.input_mode === "prepared") return r.starter || baseName(r.input_path) || "준비된 입력";
  return r.template?.label || r.template?.id || "템플릿";
}

export function durationText(sec: number | null | undefined): string {
  if (sec == null || !Number.isFinite(sec)) return "–";
  const s = Math.round(sec);
  if (s < 60) return `${s}초`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}분 ${s % 60}초`;
  return `${Math.floor(m / 60)}시간 ${m % 60}분`;
}

/** "MM-DD HH:mm" */
export function mdHm(iso: string | null | undefined): string {
  if (!iso) return "–";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "–";
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

export const isActiveState = (s: string) => s === "QUEUED" || s === "RUNNING" || s === "WAITING_HPC" || s === "COLLECTING";

export const MODE_FILTERS = [
  { key: "all", label: "전체" },
  { key: "template", label: "템플릿" },
  { key: "prepared", label: "준비된 입력" },
] as const;
