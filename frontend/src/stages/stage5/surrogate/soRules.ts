// ⑤ 내장 최적화 화면 규칙(phase3.md §18.10, 순수 함수): 상태 문구·톤, 지표 목록, 변수 범위 행, 요청 본문, 품질 등급, 수렴 그래프 자료.
import type { ParamSet } from "../../../api";
import type { SoIteration, SoParameter, SoRun, SurrogateOpt, SurrogateOptCreate } from "../../../api/surrogateOpt";
import { fmtNum } from "../../../lib/format";
import { rolesToBody, type PerfRow, type RoleSel } from "./perfRules";

export const SO_STATUS_LABEL: Record<string, string> = {
  EXPLORING: "탐색 중",
  FITTING: "대리모델 학습",
  VERIFYING: "검증 중",
  FINALIZING: "마무리(캡처)",
  DONE: "완료",
  FAILED: "실패",
  CANCELED: "취소",
};
export const soTone = (s: string) => (s === "DONE" ? "ok" : s === "FAILED" ? "bad" : ["EXPLORING", "FITTING", "VERIFYING", "FINALIZING"].includes(s) ? "run" : "");

const CURVE_LABEL: Record<string, string> = { "curve:max": "커브 최대값", "curve:min": "커브 최소값", "curve:absmax": "커브 |최대|" };

export function metricLabel(id: string, series?: string | null): string {
  if (CURVE_LABEL[id]) return series ? `${CURVE_LABEL[id]}(${series})` : CURVE_LABEL[id];
  return id.replace(/^(resp|tbl|perf):/, "");
}

/** 목적 정의(서버 상세 objectives[].label — 없으면 settings.objective 한 개로) */
export interface ObjDef {
  metric: string;
  sense: "min" | "max";
  label: string;
  unit: string;
}
export function objectiveDefs(o: Pick<SurrogateOpt, "objectives" | "settings">): ObjDef[] {
  if (o.objectives?.length) return o.objectives.map((x) => ({ metric: x.metric, sense: x.sense === "max" ? "max" : "min", label: x.label || metricLabel(x.metric, x.series), unit: x.unit ?? "" }));
  const s = (o.settings as { objective?: { metric: string; series?: string | null; sense: string } }).objective;
  return s ? [{ metric: s.metric, sense: s.sense === "max" ? "max" : "min", label: metricLabel(s.metric, s.series), unit: "" }] : [];
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

export interface SoForm {
  paramSetId: string | null;
  modelId: string | null;
  explore: "new" | "reuse";
  count: string;
  exploreSeed: string;
  batchId: string;
  /** 성능 이름 → 역할(S17 §22.12). 저장된 성능만 */
  sels: Record<string, RoleSel>;
  /** 성능 이름 → 가중치 슬라이더 0~100(목적일 때만 쓴다) */
  weights: Record<string, number>;
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

/** 화면 상태 → 생성·미리보기 본문(§22.4.1). 범위는 바뀐 변수·고정 변수만 보낸다(생략 = 템플릿 min·max). 목적은 항상 `objectives` 배열 */
export function buildBody(f: SoForm, perfs: PerfRow[]): SurrogateOptCreate {
  const bounds: Record<string, number[]> = {};
  for (const r of f.rows) {
    const lo = Number(r.lo);
    const hi = r.fixed ? lo : Number(r.hi);
    if (r.fixed || lo !== r.min || hi !== r.max) bounds[r.name] = [lo, hi];
  }
  const roles = rolesToBody(perfs, f.sels, f.weights);
  return {
    param_set_id: f.paramSetId,
    model_id: f.modelId,
    explore: f.explore === "new"
      ? { kind: "new", count: f.count.trim() === "" ? null : int(f.count, 10), seed: int(f.exploreSeed, 1) }
      : { kind: "reuse", batch_id: f.batchId },
    objectives: roles.objectives,
    constraints: roles.constraints,
    observe: roles.observe,
    ...(roles.weights ? { weights: roles.weights } : {}),
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
export function previewText(p: { explore_count: number; max_total_runs: number; estimate_min?: number | null }, it: number, k: number, objectives = 1): string {
  const parts = p.explore_count ? `탐색 ${p.explore_count} + ${it} × ${k}` : `재사용 + ${it} × ${k}`;
  const est = p.estimate_min != null ? ` · 예상 ${Math.round(p.estimate_min)}분` : "";
  const multi = objectives > 1 ? ` · 목적 ${objectives}개(다목적)` : "";
  return `예측 최대 ${p.max_total_runs} run(${parts})${est}${multi}`;
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

// ---- D3-61 결과 화면: 최적안 — 기준안 대비 · 결과 요약 ---------------------------------------------------

export interface CompareRow {
  name: string;
  unit: string;
  min: number;
  max: number;
  base: number | null;
  opt: number | null;
  delta: number | null;
  /** 최적안이 학습 범위 끝에 닿음 */
  bound: "upper" | "lower" | null;
  /** 트랙 위 위치(0~1) */
  basePos: number | null;
  optPos: number | null;
}

/** 변수마다 학습 범위·기준안(템플릿 nominal)·최적안·변화·범위 끝 도달 */
export function compareRows(params: SoParameter[], base: Record<string, number> | null | undefined, opt: Record<string, number> | null | undefined): CompareRow[] {
  return params.map((p) => {
    const b = base?.[p.name] ?? p.nominal ?? null;
    const o = opt?.[p.name] ?? null;
    const span = p.max - p.min;
    const pos = (v: number | null) => (v == null || span <= 0 ? null : Math.min(1, Math.max(0, (v - p.min) / span)));
    const tol = 1e-9 * Math.max(1, Math.abs(span));
    const bound = o == null || span <= 0 ? null : o >= p.max - tol ? "upper" : o <= p.min + tol ? "lower" : null;
    return { name: p.name, unit: p.unit ?? "", min: p.min, max: p.max, base: b, opt: o, delta: b != null && o != null ? o - b : null, bound, basePos: pos(b), optPos: pos(o) };
  });
}

/** 범위 끝 도달 안내 한 줄(없으면 null) */
export function boundNote(rows: CompareRow[]): string | null {
  const hit = rows.filter((r) => r.bound);
  if (!hit.length) return null;
  const names = hit.map((r) => `${r.name}(${r.bound === "upper" ? "상한" : "하한"})`).join(", ");
  return `${names}이(가) 학습 범위 끝에 닿았습니다 — 범위를 넓혀 학습하면 추가 개선 여지가 있습니다`;
}

export interface Kpi {
  label: string;
  value: string;
  unit: string;
  sub: string;
  tone: string;
}

/** 결과 요약 타일: 목적(최적 vs 기준안 절대·%), 제약(만족·기준안), 대리모델 품질(마지막 Q²), 예측 수·소요 */
export function kpis(o: SurrogateOpt): Kpi[] {
  if (o.mode === "multi") return kpisMulti(o);
  const s = o.settings as { objective: { metric: string; series?: string | null; sense: string }; constraints: { metric: string; series?: string | null; op: string; value: number }[]; multi_execution?: number };
  const best = o.best;
  const fin = o.final;
  const baseObj = fin?.baseline?.objective ?? fin?.baseline_predicted ?? null;
  const out: Kpi[] = [];
  const objLabel = metricLabel(s.objective.metric, s.objective.series);
  let sub = "기준안 값 없음";
  let tone = "";
  if (best?.objective != null && baseObj != null) {
    const d = best.objective - baseObj;
    const pct = baseObj !== 0 ? (d / Math.abs(baseObj)) * 100 : null;
    const good = s.objective.sense === "max" ? d >= 0 : d <= 0;
    sub = `${d >= 0 ? "+" : ""}${fmtNum(d)}${pct != null ? ` (${pct >= 0 ? "+" : ""}${pct.toFixed(1)}%)` : ""} vs 기준안${fin?.baseline?.objective == null ? "(예측)" : ""}`;
    tone = good ? "ok" : "bad";
  }
  out.push({ label: `${objLabel} ${s.objective.sense === "max" ? "최대화" : "최소화"}`, value: fmtNum(best?.objective ?? null), unit: "", sub, tone });
  s.constraints.forEach((c, i) => {
    const key = c.series ? `${c.metric}@${c.series}` : c.metric;
    const v = (best?.constraints as Record<string, number | null> | undefined)?.[key] ?? (best?.constraints as Record<string, number | null> | undefined)?.[c.metric] ?? null;
    const ok = v != null && (c.op === "<=" ? v <= c.value : v >= c.value);
    const bv = fin?.baseline?.constraints?.[i];
    out.push({ label: `${metricLabel(c.metric, c.series)} (제약 ${c.op === "<=" ? "≤" : "≥"} ${fmtNum(c.value)})`, value: fmtNum(v), unit: "",
      sub: `${ok ? "만족" : "위반"}${bv != null ? ` · 기준안 ${fmtNum(bv)}` : ""}`, tone: ok ? "ok" : "bad" });
  });
  const lastFit = [...(o.iterations as SoIteration[])].reverse().find((it) => it.fit)?.fit;
  const g = qualityGrade(lastFit?.q2);
  out.push({ label: `대리모델 품질${lastFit ? `(${lastFit.kind === "rbf" ? "RBF" : "GP"})` : ""}`, value: lastFit?.q2 != null ? `Q² ${fmtNum(lastFit.q2, 3)}` : "—", unit: "",
    sub: `${g.label}${lastFit?.loo_rmse != null ? ` · LOO RMSE ${fmtNum(lastFit.loo_rmse)}` : ""}`, tone: g.tone });
  const n = (o.runs ?? []).length + (fin?.baseline ? 1 : 0) + (fin?.best ? 1 : 0);
  const mins = o.finished_at ? Math.round((Date.parse(o.finished_at) - Date.parse(o.created_at)) / 60000) : null;
  out.push({ label: "소요", value: String(n), unit: "예측", sub: `${mins != null ? `약 ${mins >= 60 ? `${Math.floor(mins / 60)}시간 ${mins % 60}분` : `${mins}분`}` : "진행 중"} · 동시 ${s.multi_execution ?? 1}`, tone: "" });
  return out;
}

/** key로 못 찾으면 순서(positional)로 — 서버 best.objectives는 지표 id 키(§22.10) */
function pickByMetric(dict: Record<string, number | null> | null | undefined, metric: string, i: number): number | null {
  if (!dict) return null;
  if (metric in dict) return dict[metric];
  const vals = Object.values(dict);
  return vals[i] ?? null;
}

/** 다목적 결과 요약 타일(§22.12): 파레토 해·HV, 추천점 목적별 값, 제약 만족, 품질, 소요 */
export function kpisMulti(o: SurrogateOpt): Kpi[] {
  const defs = objectiveDefs(o);
  const best = o.best;
  const out: Kpi[] = [];
  const front = o.pareto?.front ?? [];
  out.push({ label: "검증된 파레토 해", value: String(front.length), unit: "개", sub: o.pareto?.hv != null ? `HV ${fmtNum(o.pareto.hv, 3)}` : "HV —", tone: front.length ? "ok" : "" });
  defs.forEach((d, i) => {
    const v = pickByMetric(best?.objectives as Record<string, number | null> | null | undefined, d.metric, i);
    out.push({ label: `${d.label} ${d.sense === "max" ? "최대화" : "최소화"}`, value: fmtNum(v), unit: d.unit, sub: best ? "가중 추천점" : "추천점 없음", tone: "" });
  });
  for (const c of o.constraints_def ?? []) {
    const v = (best?.constraints as Record<string, number | null> | undefined)?.[c.metric] ?? null;
    const ok = v != null && (c.op === "range" ? c.lo != null && c.hi != null && v >= c.lo && v <= c.hi : c.op === "<=" ? v <= (c.value ?? Infinity) : v >= (c.value ?? -Infinity));
    const bound = c.op === "range" ? `${fmtNum(c.lo)} ~ ${fmtNum(c.hi)}` : `${c.op === "<=" ? "≤" : "≥"} ${fmtNum(c.value)}`;
    out.push({ label: `${c.label} (제약 ${bound})`, value: fmtNum(v), unit: c.unit, sub: v == null ? "값 없음" : ok ? "만족" : "위반", tone: v == null ? "" : ok ? "ok" : "bad" });
  }
  const lastFit = [...(o.iterations as SoIteration[])].reverse().find((it) => it.fit)?.fit;
  const worst = Math.max(...(lastFit?.per_objective ?? []).map((x) => x.loo_nrmse ?? 0), 0);
  out.push({ label: `대리모델 품질${lastFit ? `(${lastFit.kind === "rbf" ? "RBF" : "GP"})` : ""}`, value: lastFit ? (lastFit.q2 != null ? `Q² ${fmtNum(lastFit.q2, 3)}` : `NRMSE ${fmtNum(worst, 3)}`) : "—", unit: "", sub: lastFit?.per_objective?.length ? "목적 중 최대 오차" : "", tone: "" });
  const n = (o.runs ?? []).length;
  const mins = o.finished_at ? Math.round((Date.parse(o.finished_at) - Date.parse(o.created_at)) / 60000) : null;
  const multi = (o.settings as { multi_execution?: number }).multi_execution ?? 1;
  out.push({ label: "소요", value: String(n), unit: "예측", sub: `${mins != null ? `약 ${mins >= 60 ? `${Math.floor(mins / 60)}시간 ${mins % 60}분` : `${mins}분`}` : "진행 중"} · 동시 ${multi}`, tone: "" });
  return out;
}
