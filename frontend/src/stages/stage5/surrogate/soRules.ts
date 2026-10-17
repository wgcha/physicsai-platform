// ⑤ 내장 최적화 화면 규칙(phase3.md §18.10, 순수 함수): 상태 문구·톤, 지표 목록, 변수 범위 행, 요청 본문, 품질 등급, 수렴 그래프 자료.
import type { ParamSet } from "../../../api";
import type { DesignMapMetric, SoIteration, SoRun, SurrogateOpt, SurrogateOptCreate } from "../../../api/surrogateOpt";
import { fmtNum } from "../../../lib/format";

export const SO_STATUS_LABEL: Record<string, string> = {
  EXPLORING: "탐색 중",
  FITTING: "대리모델 학습",
  VERIFYING: "검증 중",
  DONE: "완료",
  FAILED: "실패",
  CANCELED: "취소",
};
export const soTone = (s: string) => (s === "DONE" ? "ok" : s === "FAILED" ? "bad" : ["EXPLORING", "FITTING", "VERIFYING"].includes(s) ? "run" : "");

const CURVE_LABEL: Record<string, string> = { "curve:max": "커브 최대값", "curve:min": "커브 최소값", "curve:absmax": "커브 |최대|" };

/** 새 DOE: 템플릿 응답 이름 → resp:<NAME>_MAX|_MIN + curve:* (값이 있는지는 실행 뒤 판정, §18.6) */
export function newDoeMetrics(ps: ParamSet | null): DesignMapMetric[] {
  const out: DesignMapMetric[] = [];
  for (const r of ps?.responses ?? []) {
    if (!/^[A-Za-z][A-Za-z0-9_]{0,63}$/.test(r.name)) continue;
    out.push({ id: `resp:${r.name}_MAX`, label: `${r.name} 최대(RESP)`, unit: r.unit || null, needs_series: false });
    out.push({ id: `resp:${r.name}_MIN`, label: `${r.name} 최소(RESP)`, unit: r.unit || null, needs_series: false });
  }
  for (const id of Object.keys(CURVE_LABEL)) out.push({ id, label: CURVE_LABEL[id], unit: null, needs_series: true });
  return out;
}

export function metricLabel(id: string, series?: string | null): string {
  if (CURVE_LABEL[id]) return series ? `${CURVE_LABEL[id]}(${series})` : CURVE_LABEL[id];
  return id.replace(/^(resp|tbl):/, "");
}

/** 정수 변수 = tpl 형식 %Ni/%Nd(nearest.integer_vars) */
export function integerVars(ps: ParamSet | null): Set<string> {
  return new Set((ps?.tpl_params ?? []).filter((t) => /[id]$/.test(t.format ?? "")).map((t) => t.name));
}

export interface VarRow {
  name: string;
  min: number;
  max: number;
  lo: string;
  hi: string;
  fixed: boolean;
  integer: boolean;
}

export function varRows(ps: ParamSet | null): VarRow[] {
  const ints = integerVars(ps);
  return (ps?.parameters ?? []).map((p) => ({ name: p.name, min: p.min, max: p.max, lo: String(p.min), hi: String(p.max), fixed: p.min === p.max, integer: ints.has(p.name) }));
}

/** 행 검증 문구(화면 회색 줄). 서버도 같은 규칙(BOUNDS_*) */
export function rowIssue(r: VarRow): string | null {
  const lo = Number(r.lo);
  const hi = r.fixed ? lo : Number(r.hi);
  if (r.lo.trim() === "" || !Number.isFinite(lo) || (!r.fixed && (r.hi.trim() === "" || !Number.isFinite(hi)))) return "숫자를 입력하세요";
  if (lo > hi) return "하한 ≤ 상한";
  if (lo < r.min || hi > r.max) return `학습 범위 ${fmtNum(r.min)}~${fmtNum(r.max)} 안`;
  if (r.integer && !r.fixed && Math.ceil(lo) > Math.floor(hi)) return "정수가 없습니다";
  return null;
}

export interface Constraint {
  metric: string;
  op: "<=" | ">=";
  value: string;
}

export interface SoForm {
  paramSetId: string | null;
  modelId: string | null;
  explore: "new" | "reuse";
  count: string;
  exploreSeed: string;
  batchId: string;
  metric: string;
  series: string | null;
  sense: "min" | "max";
  constraints: Constraint[];
  rows: VarRow[];
  surrogate: "gp" | "rbf";
  iterations: string;
  candidates: string;
  tolPct: string;
  seed: string;
  multi: string;
  capture: boolean;
}

const int = (s: string, d: number) => (s.trim() === "" || !Number.isFinite(Number(s)) ? d : Math.trunc(Number(s)));

/** 화면 상태 → 생성·미리보기 본문(§18.6). 범위는 바뀐 변수·고정 변수만 보낸다(생략 = 템플릿 min·max) */
export function buildBody(f: SoForm): SurrogateOptCreate {
  const bounds: Record<string, number[]> = {};
  for (const r of f.rows) {
    const lo = Number(r.lo);
    const hi = r.fixed ? lo : Number(r.hi);
    if (r.fixed || lo !== r.min || hi !== r.max) bounds[r.name] = [lo, hi];
  }
  return {
    param_set_id: f.paramSetId,
    model_id: f.modelId,
    explore: f.explore === "new"
      ? { kind: "new", count: f.count.trim() === "" ? null : int(f.count, 10), seed: int(f.exploreSeed, 1) }
      : { kind: "reuse", batch_id: f.batchId },
    objective: { metric: f.metric, series: f.series, sense: f.sense },
    constraints: f.constraints.filter((c) => c.metric && c.value.trim() !== "").map((c) => ({ metric: c.metric, series: null, op: c.op, value: Number(c.value) })),
    bounds: Object.keys(bounds).length ? bounds : null,
    surrogate: f.surrogate,
    iterations: int(f.iterations, 3),
    candidates: int(f.candidates, 4),
    tol_rel: Number(f.tolPct) / 100,
    seed: int(f.seed, 1),
    multi_execution: int(f.multi, 1),
    capture: f.capture,
  };
}

/** 미리보기 한 줄: "예측 최대 32 run(탐색 20 + 3 × 4) · 예상 70분" */
export function previewText(p: { explore_count: number; max_total_runs: number; estimate_min?: number | null }, it: number, k: number): string {
  const parts = p.explore_count ? `탐색 ${p.explore_count} + ${it} × ${k}` : `재사용 + ${it} × ${k}`;
  const est = p.estimate_min != null ? ` · 예상 ${Math.round(p.estimate_min)}분` : "";
  return `예측 최대 ${p.max_total_runs} run(${parts})${est}`;
}

/** 품질 등급(§18.5): Q² ≥ 0.9 좋음 · 0.7~0.9 보통 · < 0.7 낮음 */
export function qualityGrade(q2: number | null | undefined): { label: string; tone: string; hint: string | null } {
  if (q2 == null || !Number.isFinite(q2)) return { label: "—", tone: "", hint: null };
  if (q2 >= 0.9) return { label: "좋음", tone: "ok", hint: null };
  if (q2 >= 0.7) return { label: "보통", tone: "warn", hint: null };
  return { label: "낮음", tone: "bad", hint: "탐색 run을 늘리세요" };
}

export interface ConvergenceData {
  verified: { x: number; y: number; title: string }[];
  predicted: { x: number; y: number; title: string }[];
  best: [number, number][];
  xMax: number;
}

/** 수렴 그래프: x = 반복 0..T, 회색 점 = 검증 run 값, 속 빈 점 = 대리모델 예측, 선 = 지금까지 최선 */
export function convergence(o: Pick<SurrogateOpt, "runs" | "iterations" | "settings">): ConvergenceData {
  const runs = (o.runs ?? []) as SoRun[];
  const verified = runs.filter((r) => r.objective != null && Number.isFinite(r.objective)).map((r) => ({
    x: r.iter_no, y: r.objective as number, title: `반복 ${r.iter_no} · ${r.batch_label} DOE #${r.doe_no} · ${fmtNum(r.objective)}`,
  }));
  const predicted = (o.iterations as SoIteration[]).flatMap((it) => (it.candidates ?? []).filter((c) => c.predicted != null).map((c) => ({
    x: it.iter_no, y: c.predicted as number, title: `반복 ${it.iter_no} 후보 DOE #${c.doe_no} 예측 ${fmtNum(c.predicted)}`,
  })));
  const best = (o.iterations as SoIteration[]).filter((it) => it.best_value != null).map((it) => [it.iter_no, it.best_value as number] as [number, number]);
  const T = Number((o.settings as { iterations?: number }).iterations ?? 0);
  return { verified, predicted, best, xMax: Math.max(T, ...(o.iterations as SoIteration[]).map((i) => i.iter_no), 1) };
}

export const SO_MODE_KEY = "physicsai.stage5.mode";
export type OptMode = "builtin" | "original";
export function readMode(): OptMode {
  try {
    const v = globalThis.localStorage?.getItem(SO_MODE_KEY);
    return v === "original" ? "original" : "builtin";
  } catch {
    return "builtin";
  }
}
export function writeMode(m: OptMode) {
  try {
    globalThis.localStorage?.setItem(SO_MODE_KEY, m);
  } catch {
    /* 저장 실패는 무시 */
  }
}
export const SO_TAB_KEY = "physicsai.stage5.surrogateTab";
