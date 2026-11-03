// data-health.md §9 화면 모델: 선택(제외 필수 기본 선택·추천은 기본 선택 없음)·필터·정렬·제출 params. 순수 함수만.
import type { DataHealthReport, DhReason, DhRun, DhValue, Job } from "../../../api";

export const CONFIRM_KEEP = "프레임 수 또는 종료 시각이 다른 run입니다. 포함하면 데이터셋 일관성이 깨집니다. 그래도 포함할까요?";

/** 입력 식별 키: ② 큐레이션 기본 입력이면 curation_id, 아니면 정리한 폴더 경로 */
export const inputKey = (curationId: string | null, path: string): string => (curationId ? `cur:${curationId}` : `path:${path.trim()}`);

/** 점검 작업이 지금 입력에 대한 것인지(params 비교). 다르면 "다른 입력" */
export function jobInputKey(job: Pick<Job, "params"> | null | undefined): string | null {
  const p = (job?.params ?? {}) as { curation_id?: string; input_path?: string };
  if (p.curation_id) return `cur:${p.curation_id}`;
  if (p.input_path) return `path:${String(p.input_path).trim()}`;
  return null;
}

/** 제외 필수 run이 기본 선택. 통계 추천은 선택하지 않는다(DH-1) */
export const initialSelection = (runs: DhRun[]): Set<string> => new Set(runs.filter((r) => r.required).map((r) => r.file_rel));

/** [추천 항목 선택]: 지금 선택에 추천 run을 더한다 */
export const selectRecommended = (sel: Set<string>, runs: DhRun[]): Set<string> => new Set([...sel, ...runs.filter((r) => r.recommended).map((r) => r.file_rel)]);

/** [선택 해제]: 제외 필수는 남긴다 */
export const clearSelection = (_sel: Set<string>, runs: DhRun[]): Set<string> => initialSelection(runs);

export function toggle(sel: Set<string>, file: string, on: boolean): Set<string> {
  const n = new Set(sel);
  if (on) n.add(file);
  else n.delete(file);
  return n;
}

/** 표 정렬: 제외 필수 맨 위, 이어서 점수 내림차순(동점은 경로순) */
export const sortRuns = (runs: DhRun[]): DhRun[] =>
  [...runs].sort((a, b) => Number(b.required) - Number(a.required) || b.score - a.score || a.file_rel.localeCompare(b.file_rel));

/** 기본 필터 [추천만]: 추천(제외 필수 포함)과 "3σ만"이 아닌 선택된 행. 선택된 행은 필터와 무관하게 보인다 */
export const visibleRuns = (runs: DhRun[], onlyRecommended: boolean, sel: Set<string>): DhRun[] =>
  sortRuns(onlyRecommended ? runs.filter((r) => r.recommended || sel.has(r.file_rel)) : runs);

/** 제외 필수인데 선택이 풀린 행(경고 아이콘·kept_required) */
export const keptRequired = (runs: DhRun[], sel: Set<string>): string[] => runs.filter((r) => r.required && !sel.has(r.file_rel)).map((r) => r.file_rel);

/** 데이터셋 생성 params 추가분(§7·§9). 점검이 현재 입력의 것이 아니면 호출하지 않는다 */
export function submitExtras(report: DataHealthReport, sel: Set<string>, healthJobId: string): Record<string, unknown> {
  const known = new Set(report.runs.map((r) => r.file_rel));
  const out: Record<string, unknown> = { health_job_id: healthJobId, exclude_files: [...sel].filter((f) => known.has(f)).sort() };
  const kept = keptRequired(report.runs, sel);
  if (kept.length) out.kept_required = kept.sort();
  return out;
}

/** 사유 칸: 첫 2개 + "외 n"(전체는 툴팁) */
export function reasonCell(reasons: DhReason[]): { text: string; tip: string } {
  const head = reasons.slice(0, 2).map((r) => r.message).join(" · ");
  const rest = reasons.length - 2;
  return { text: rest > 0 ? `${head} 외 ${rest}` : head, tip: reasons.map((r) => `${r.code}: ${r.message}`).join("\n") };
}

/** 최대 견고 z(지표): |zr| 최대 */
export function maxRobust(run: DhRun): { id: string; zr: number } | null {
  let best: { id: string; zr: number } | null = null;
  for (const [id, v] of Object.entries(run.values)) {
    if (typeof v.zr !== "number") continue;
    if (!best || Math.abs(v.zr) > Math.abs(best.zr)) best = { id, zr: v.zr };
  }
  return best;
}

/** 3σ 태그 대상(일반 |z| > sigma_z) — 추천이 아니면 "3σ만" */
export const hasSigma = (run: DhRun, sigma: number): boolean => Object.values(run.values).some((v) => typeof v.z === "number" && Math.abs(v.z) > sigma);

export const sigmaOnly = (run: DhRun): boolean => run.sigma_only && !run.recommended;

/** 프레임 확인 불가: frames 칸이 NA(원천 없음·조회 실패) */
export const framesUnknown = (run: DhRun): boolean => run.sound.frames?.v == null && !!run.sound.frames?.na;

export function fmtVal(v: DhValue | undefined, digits = 3): string {
  if (!v || v.v == null) return "–";
  if (typeof v.v === "string") return v.v;
  if (!Number.isFinite(v.v)) return "–";
  const a = Math.abs(v.v);
  return a !== 0 && (a >= 1e5 || a < 1e-3) ? v.v.toExponential(2) : String(Number(v.v.toFixed(digits)));
}

export const fmtZ = (z: number | null | undefined): string => (typeof z === "number" ? z.toFixed(1) : "–");

const TERM_LABEL: Record<string, string> = { NORMAL: "정상", ERROR: "오류 종료", UNKNOWN: "중단·잘림" };
export const termText = (v: DhValue | undefined): string => (v?.v == null ? "–" : (TERM_LABEL[String(v.v)] ?? String(v.v)));

/** 머리 줄 기준 문구: "프레임 22 · 종료 0.012 s · 출처: 설정/최빈" */
export function refText(s: DataHealthReport["summary"]): string | null {
  if (s.frames_ref == null && s.t_end_ref == null) return null;
  const src = s.ref_source === "config" ? "설정" : s.ref_source === "mode" ? "최빈" : "–";
  return `기준 프레임 ${s.frames_ref ?? "–"} · 종료 ${s.t_end_ref ?? "–"} s · 출처: ${src}`;
}

/** NA가 많은 지표(run 수의 절반 이상) 이름들 */
export function naHeavy(report: DataHealthReport): string[] {
  const n = report.summary.n_runs;
  const label = new Map(report.metrics.map((m) => [m.id, m.label]));
  return Object.entries(report.summary.n_na_by_metric ?? {})
    .filter(([, c]) => n > 0 && c * 2 >= n)
    .map(([id]) => label.get(id) ?? id);
}

/** 상태 한 줄: "최근 점검 11/3 14:20 · 추천 3 / 120" */
export const statusText = (when: string, s: DataHealthReport["summary"] | null): string =>
  `최근 점검 ${when}${s ? ` · 추천 ${s.n_recommended} / ${s.n_runs}` : ""}`;

export const WARN_TIP: Record<string, string> = {
  DH_RESP_NOT_EXTRACTED: "①-6 run 응답 추출을 먼저 실행하면 응답 지표를 함께 봅니다",
  DH_NO_DOE_LINK: "DOE 연결이 없는 입력 — 건전성만 점검했습니다",
  DH_PARAMS_MIXED: "DOE마다 파라미터 이름이 달라 이웃 대비 튐(kNN)을 생략했습니다",
};
