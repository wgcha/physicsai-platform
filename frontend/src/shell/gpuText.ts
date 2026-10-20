// S19(phase3.md §24.3 / s19_followup.md): GPU 조회 실패 툴팁·서랍 줄 문구 — 순수 함수만(React 없음).
import type { Resources } from "../api";

type FailFields = Pick<Resources, "gpu_status" | "gpu_message" | "gpu_fail_streak" | "gpu_next_query_at">;

/** ISO 시각 → HH:mm:ss(현지 시각). 잘못된 값은 null */
export function clockText(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

/** 서랍 회색 줄: 연속 2회 이상 실패일 때만 `연속 N회 실패 · 다음 조회 HH:mm:ss`(다음 조회 시각이 없으면 그 뒷부분 생략) */
export function gpuStreakText(r: Pick<Resources, "gpu_fail_streak" | "gpu_next_query_at">): string | null {
  const k = r.gpu_fail_streak ?? 0;
  if (k < 2) return null;
  const at = clockText(r.gpu_next_query_at);
  return `연속 ${k}회 실패${at ? ` · 다음 조회 ${at}` : ""}`;
}

/** 상단 자원 칩 title(§24.3): ERROR·NOT_FOUND만 문구를 바꾼다. 그 밖(OK·없음)은 null → 기존 `워커 자원 열기` */
export function gpuFailTip(r: FailFields): string | null {
  if (r.gpu_status !== "ERROR" && r.gpu_status !== "NOT_FOUND") return null;
  const head = r.gpu_status === "NOT_FOUND" ? "GPU 없음" : "GPU 조회 실패";
  const k = r.gpu_fail_streak ?? 0;
  const at = clockText(r.gpu_next_query_at);
  const tail = k >= 2 ? ` (연속 ${k}회${at ? ` · 다음 조회 ${at}` : ""})` : "";
  return `${head} — ${r.gpu_message ?? ""}${tail}`;
}
