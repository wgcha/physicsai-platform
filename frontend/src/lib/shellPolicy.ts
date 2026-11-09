// 쉘 모핑 SM-C6·C7(shell-morph.md §14.4·§14.5) 화면 모델 — 순수 함수만.
import type { GeomOptions } from "../api/types";

export type GeomPolicy = "skip" | "warn";
export const POLICY_LABEL: Record<GeomPolicy, string> = { skip: "스킵", warn: "경고 후 사용" };
export const POLICY_WARN_NOTE = "스킵 대신 경고로 남겨 학습 데이터에 포함됨";
export const HOLD_HEAD = "체결 보스 고정";
export const HOLD_TIP = "켜면 고정 노드 둘레는 제자리에 남고, 값은 보스를 남긴 깊이(CAD와 국부적으로 다름)를 뜻합니다";

/** 정책 → DOE 요청 geom_options 덮어쓰기. 기본(skip)은 키를 보내지 않는다(기본값과 같은 새 키는 쓰지 않음, §14.4) */
export function policyOptions(p: GeomPolicy): GeomOptions | null {
  return p === "warn" ? { fixed: { policy: "warn" }, quality: { fail_policy: "warn" } } : null;
}

/** 경고 통과 run(TD_DOE_GEN result.warned_runs[]): 코드 목록과 면제된 실패 코드 */
export interface WarnedRun {
  run_key: string;
  codes?: string[];
  waived?: string[];
}
const FIXED = "SHELL_FIXED_REGION_VIOLATION";
const QUALITY = "GEOM_QUALITY";
export const WAIVED_LABEL: Record<string, string> = { [FIXED]: "고정", [QUALITY]: "품질" };

export function warnedRuns(result: unknown, doeId: string | null | undefined): WarnedRun[] {
  const r = result as { doe_id?: string; warned_runs?: unknown } | null | undefined;
  if (!r || !doeId || r.doe_id !== doeId || !Array.isArray(r.warned_runs)) return [];
  return r.warned_runs.filter((x): x is WarnedRun => !!x && typeof (x as WarnedRun).run_key === "string");
}

/** "경고 통과 n(고정 a·품질 b)" — 없으면 null. 한 run이 둘 다 면제하면 양쪽에 센다 */
export function warnSummary(runs: WarnedRun[]): string | null {
  if (!runs.length) return null;
  const has = (r: WarnedRun, c: string) => (r.waived ?? []).includes(c);
  return `경고 통과 ${runs.length}(고정 ${runs.filter((r) => has(r, FIXED)).length}·품질 ${runs.filter((r) => has(r, QUALITY)).length})`;
}

export const waivedText = (waived: string[] | undefined): string => (waived ?? []).map((c) => WAIVED_LABEL[c] ?? c).join("·");

// ---- hold(bead.hold.beads는 param_set geom_options, ①-2는 train/params hold_beads)
export function holdBeads(o: GeomOptions | null | undefined): string[] {
  const b = ((o?.bead as Record<string, unknown> | undefined)?.hold as Record<string, unknown> | undefined)?.beads;
  return Array.isArray(b) ? b.map(String) : [];
}
/** geom_options에서 hold 비드 목록만 바꾼다(ρ·b 등 다른 키는 보존, 빈 목록이면 beads 키를 지우고 빈 절은 없앤다) */
export function withHold(o: GeomOptions | null | undefined, beads: string[]): GeomOptions {
  const out: GeomOptions = JSON.parse(JSON.stringify(o ?? {}));
  const bead = { ...((out.bead as Record<string, unknown>) ?? {}) };
  const hold = { ...((bead.hold as Record<string, unknown>) ?? {}) };
  if (beads.length) hold.beads = beads;
  else delete hold.beads;
  if (Object.keys(hold).length) bead.hold = hold;
  else delete bead.hold;
  if (Object.keys(bead).length) out.bead = bead;
  else delete out.bead;
  return out;
}
/** 비드 하나 켜기·끄기(정렬·중복 없음) */
export const toggleHold = (beads: string[], bead: string, on: boolean): string[] => (on ? [...new Set([...beads, bead])].sort() : beads.filter((b) => b !== bead));
