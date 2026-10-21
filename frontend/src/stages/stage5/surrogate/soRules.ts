// ⑤ 내장 최적화 화면 규칙(phase3.md §18.10, 순수 함수): 상태 문구·톤, 지표 목록, 변수 범위 행, 요청 본문, 품질 등급, 수렴 그래프 자료.
import type { ParamSet } from "../../../api";
import type { SoIteration, SoParameter, SoRun, SurrogateOpt, SurrogateOptCreate } from "../../../api/surrogateOpt";
import { fmtNum } from "../../../lib/format";
import { editOf, rowBounds, type NativeRow } from "../../../lib/nativeVars";
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
  /** opt-native §7: 다중 baseline 세트에서 이 변수가 N/A인 baseline id */
  na?: string[];
}

export function varRows(ps: ParamSet | null): VarRow[] {
  const ints = integerVars(ps);
  return (ps?.parameters ?? []).map((p) => {
    const per = (p as { baselines?: Record<string, unknown> | null }).baselines;
    const na = per ? Object.entries(per).filter(([, v]) => v == null).map(([k]) => k) : [];
    return { name: p.name, min: p.min, max: p.max, lo: String(p.min), hi: String(p.max), fixed: p.min === p.max, integer: ints.has(p.name), ...(na.length ? { na } : {}) };
  });
}

/** 다중 baseline 세트의 baseline id 목록(4B, 없으면 []) */
export function baselineIds(ps: ParamSet | null): string[] {
  return ((ps as { baselines?: { id: string }[] } | null)?.baselines ?? []).map((b) => b.id);
}

/** 변수 칸 표시: 범주 baseline은 수준 인덱스 → id(settings.levels.baseline) */
export function fmtVar(name: string, v: number | null | undefined, levels?: string[] | null): string {
  if (name === "baseline" && levels?.length && v != null && Number.isFinite(v)) return levels[Math.round(v)] ?? fmtNum(v);
  return fmtNum(v ?? null);
}
export const levelsOf = (o: Pick<SurrogateOpt, "settings">): string[] | null => ((o.settings as { levels?: { baseline?: string[] } }).levels?.baseline ?? null);

/** 행 검증 문구(화면 회색 줄). 서버도 같은 규칙(BOUNDS_*). native = Native 템플릿 — 학습 범위 밖은 막지 않고 경고만(native-vars.md NV-7) */
export function rowIssue(r: VarRow, native = false): string | null {
  const lo = Number(r.lo);
  const hi = r.fixed ? lo : Number(r.hi);
  if (r.lo.trim() === "" || !Number.isFinite(lo) || (!r.fixed && (r.hi.trim() === "" || !Number.isFinite(hi)))) return "숫자를 입력하세요";
  if (lo > hi) return "하한 ≤ 상한";
  if (!native && (lo < r.min || hi > r.max)) return `학습 범위 ${fmtNum(r.min)}~${fmtNum(r.max)} 안`;
  if (r.integer && !r.fixed && Math.ceil(lo) > Math.floor(hi)) return "정수가 없습니다";
  return null;
}

// ---- opt-native §6·§10: 알고리즘·검증 방식·고급 옵션 ------------------------------------------------------

export type Algorithm = "ego" | "ga" | "nsga2";
export type Verification = "loop" | "none";
export const ALGO_LABEL: Record<Algorithm, string> = { ego: "대리모델 EGO(기본)", ga: "유전 알고리즘 GA", nsga2: "NSGA-II" };
export const ALGO_SHORT: Record<string, string> = { ego: "EGO", ga: "GA", nsga2: "NSGA-II" };
export const ALGO_REVERT_NOTE = "목적 수가 바뀌어 알고리즘을 대리모델 EGO로 되돌렸습니다";
export const NONE_NOTE = "예측 run 없이 대리모델로만 탐색합니다. 결과의 후보는 미검증이며 '선택 해 예측 검증'으로 확인하세요";
export const UNVERIFIED_BADGE = "대리모델 예측(미검증)";

/** 목적 수에 맞는 알고리즘인지(§6.1) — 아니면 툴팁 문구 */
export function algoTip(a: Algorithm, nObj: number): string | null {
  if (a === "ga" && nObj > 1) return "GA는 단일 목적 전용";
  if (a === "nsga2" && nObj < 2) return "NSGA-II는 목적 2개 이상";
  return null;
}

/** 고급 옵션 입력(빈칸 = 기본) */
export interface AlgoForm {
  pop_size: string;
  generations: string;
  crossover_prob: string;
  mutation_prob: string;
  eta_c: string;
  eta_m: string;
}
export const EMPTY_ALGO: AlgoForm = { pop_size: "", generations: "", crossover_prob: "", mutation_prob: "", eta_c: "", eta_m: "" };
export interface AlgoDefaults {
  pop_size?: number | null;
  generations: number;
  crossover_prob: number;
  mutation_prob?: number | null;
  eta_c: number;
  eta_m: number;
}

/** §6.7 기본 집단 크기(서버 algo.default_pop_size와 같은 식) */
export function defaultPopSize(a: Algorithm, nG: number): number {
  if (a === "ga") {
    const p = Math.min(Math.max(10 * nG, 40), 200);
    return p + (p % 2);
  }
  const p = Math.ceil(Math.max(100, 10 * nG) / 4) * 4;
  return Math.min(Math.max(p, 100), 400);
}

/** 클라이언트 범위 검사(§6.7) — 서버 ALGO_OPTIONS_INVALID와 같은 문구 */
export function algoIssues(a: Algorithm, f: AlgoForm, nG: number, defs: AlgoDefaults | undefined, maxEvals: number): string[] {
  if (a === "ego") return [];
  const out: string[] = [];
  const num = (s: string) => (s.trim() === "" ? null : Number(s));
  const ps = num(f.pop_size);
  const step = a === "nsga2" ? 4 : 2;
  if (ps != null && (!Number.isInteger(ps) || ps < 8 || ps > 1000 || ps % step)) out.push(`집단 크기는 8~1000의 ${step === 4 ? "4의 배수" : "짝수"}입니다`);
  const g = num(f.generations);
  if (g != null && (!Number.isInteger(g) || g < 1 || g > 2000)) out.push("세대 수는 1~2000입니다");
  const pc = num(f.crossover_prob);
  if (pc != null && (!Number.isFinite(pc) || pc < 0 || pc > 1)) out.push("교차 확률은 0~1입니다");
  const pm = num(f.mutation_prob);
  if (pm != null && (!Number.isFinite(pm) || pm < 0 || pm > 1)) out.push("변이 확률은 0~1입니다");
  const ec = num(f.eta_c);
  if (ec != null && (!Number.isFinite(ec) || ec < 1 || ec > 100)) out.push("η_c는 1~100입니다");
  const em = num(f.eta_m);
  if (em != null && (!Number.isFinite(em) || em < 1 || em > 100)) out.push("η_m는 1~100입니다");
  if (!out.length) {
    const pop = ps ?? defs?.pop_size ?? defaultPopSize(a, Math.max(nG, 1));
    const gens = g ?? defs?.generations ?? (a === "ga" ? 150 : 200);
    if (pop * gens > maxEvals) out.push(`집단 크기 × 세대 수(${pop} × ${gens} = ${pop * gens})가 상한 ${maxEvals}을 넘습니다`);
  }
  return out;
}

/** 요청 algo_options(빈칸 = null). ego는 보내지 않는다 */
export function algoOptionsBody(f: AlgoForm): Record<string, number | null> {
  const n = (s: string) => (s.trim() === "" || !Number.isFinite(Number(s)) ? null : Number(s));
  return { pop_size: n(f.pop_size), generations: n(f.generations), crossover_prob: n(f.crossover_prob), mutation_prob: n(f.mutation_prob), eta_c: n(f.eta_c), eta_m: n(f.eta_m) };
}

/** fit.algo(§6.6) */
export interface AlgoRecord {
  name: string;
  pop_size?: number;
  generations?: number;
  generations_run?: number;
  evals?: number;
  stop?: string;
  seed?: number;
  best_pred?: number | null;
  hv_pred?: number | null;
}

/** 품질 표 "탐색기" 칸: "GA 150/150 최대 세대" · "NSGA-II 142/200 정체 종료" · "EGO" */
export function searcherText(a: AlgoRecord | null | undefined): string {
  if (!a?.name) return "—";
  const label = ALGO_SHORT[a.name] ?? a.name;
  if (a.name === "ego" || a.generations == null) return label;
  return `${label} ${a.generations_run ?? "?"}/${a.generations} ${a.stop === "STALL" ? "정체 종료" : "최대 세대"}`;
}

/** 상태 칸: "알고리즘: NSGA-II · 세대 200(정체 종료 142)" — 마지막 반복의 fit.algo(없으면 settings.algorithm) */
export function algoStatusText(o: Pick<SurrogateOpt, "iterations" | "settings">): string | null {
  const st = o.settings as { algorithm?: string; verification?: string };
  const last = [...((o.iterations ?? []) as SoIteration[])].reverse().map((it) => (it.fit as { algo?: AlgoRecord } | null | undefined)?.algo).find((a) => a?.name);
  const name = last?.name ?? st.algorithm;
  if (!name) return null;
  let txt = `알고리즘: ${ALGO_SHORT[name] ?? name}`;
  if (last && last.name !== "ego" && last.generations != null) {
    txt += ` · 세대 ${last.generations}`;
    if (last.stop === "STALL") txt += `(정체 종료 ${last.generations_run})`;
  }
  if (st.verification === "none") txt += " · 대리모델만(검증 없음)";
  return txt;
}

export const isSurrogateOnly = (o: Pick<SurrogateOpt, "settings">) => (o.settings as { verification?: string }).verification === "none";

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
  /** native-vars.md §7.2: Native 템플릿(단일 baseline) — 세트 정의 행 + 그 자리 추가·제외. null/없음 = 기존 표(rows) */
  nrows?: NativeRow[] | null;
  surrogate: "gp" | "rbf";
  iterations: string;
  candidates: string;
  tolPct: string;
  seed: string;
  multi: string;
  capture: boolean;
  /** opt-native §8 */
  algorithm?: Algorithm;
  verification?: Verification;
  algo?: AlgoForm;
  /** opt-native §7: 위상 변형 세트의 baseline 수준(null = 전부) */
  levels?: string[] | null;
}

const int = (s: string, d: number) => (s.trim() === "" || !Number.isFinite(Number(s)) ? d : Math.trunc(Number(s)));

/** 화면 상태 → 생성·미리보기 본문(§22.4.1). 범위는 바뀐 변수·고정 변수만 보낸다(생략 = 템플릿 min·max). 목적은 항상 `objectives` 배열 */
export function buildBody(f: SoForm, perfs: PerfRow[]): SurrogateOptCreate {
  const bounds: Record<string, number[]> = {};
  if (f.nrows) {
    // Native: 사용 행만, 기준 범위(세트 정의·추가 변수는 피처 기본 범위)와 다르거나 고정이면 보낸다. 제외 ≠ 고정(NV-6)
    for (const r of f.nrows.filter((x) => x.use)) {
      const b = rowBounds(r) ?? [Number(r.lo), Number(r.hi)];
      if (r.fixed || b[0] !== r.base.min || b[1] !== r.base.max) bounds[r.name] = [b[0], b[1]];
    }
  } else {
    for (const r of f.rows) {
      const lo = Number(r.lo);
      const hi = r.fixed ? lo : Number(r.hi);
      if (r.fixed || lo !== r.min || hi !== r.max) bounds[r.name] = [lo, hi];
    }
  }
  const vars = f.nrows ? editOf(f.nrows) : null;
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
    ...(vars ? { vars } : {}),
    surrogate: f.surrogate,
    iterations: int(f.iterations, 3),
    candidates: int(f.candidates, 4),
    tol_rel: Number(f.tolPct) / 100,
    seed: int(f.seed, 1),
    multi_execution: int(f.multi, 1),
    capture: f.capture,
    // opt-native §8: 알고리즘·검증 방식(기본 ego·loop도 명시), GA·NSGA-II만 고급 옵션
    ...(f.algorithm ? { algorithm: f.algorithm } : {}),
    ...(f.verification ? { verification: f.verification } : {}),
    ...(f.algorithm && f.algorithm !== "ego" ? { algo_options: algoOptionsBody(f.algo ?? EMPTY_ALGO) } : {}),
    ...(f.levels ? { levels: { baseline: f.levels } } : {}),
  };
}

/** 미리보기 한 줄: "예측 최대 32 run(탐색 20 + 3 × 4) · 예상 70분" */
export function previewText(p: { explore_count: number; max_total_runs: number; estimate_min?: number | null; verification?: string }, it: number, k: number, objectives = 1): string {
  const none = p.verification === "none";
  const parts = none ? (p.explore_count ? `탐색 ${p.explore_count} · 대리모델만` : "재사용 · 대리모델만")
    : p.explore_count ? `탐색 ${p.explore_count} + ${it} × ${k}` : `재사용 + ${it} × ${k}`;
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
