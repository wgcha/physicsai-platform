// S12 설계공간 지도 자료 규칙(phase3.md §17.5) — 순수 함수: 유효 run·유효 변수, 투영(PLS·PCA·1D), 경계 조건 문구,
// 평행 좌표 축, 툴팁 줄, 화면 선택 저장(localStorage, try/catch).
import { niceTicks } from "../../../components/Chart";
import { fmtNum } from "../../../lib/format";
import type { DesignMap, DesignMapMetric, DesignMapParameter, DesignMapRun } from "../../../api/designMap";
import { DEFAULT_METRIC } from "../../../api/designMap";
import { pca, plsNipals, standardize, structureArrows, zscore, type Mat } from "./linalg";

export type Method = "pls" | "pca" | "pc";
export const METHODS: { key: Method; label: string }[] = [
  { key: "pls", label: "PLS" },
  { key: "pca", label: "PCA" },
  { key: "pc", label: "평행 좌표" },
];

export const TEXT = {
  few: (n: number) => `점이 3개 이상 필요합니다(현재 ${n}개)`,
  allConst: "모든 변수가 상수입니다",
  oneVar: "변수 1개 — 변수–값 산점도로 표시",
  yConst: "값이 모두 같아 PLS를 계산할 수 없습니다 — PCA로 표시",
  noPls: "PLS 성분을 계산할 수 없습니다 — PCA로 표시",
  pls1d: "두 번째 PLS 성분 없음",
  footer: "PLS: 색 값에 맞춰 축을 정합니다 · PCA: 변수 분포만으로 정합니다",
  noMetric: "색으로 쓸 값이 없습니다 — 완료된 run의 커브나 응답 값이 필요합니다",
  noRun: "표시할 run이 없습니다",
  pcaTip: "X 분산 % = 그 성분의 고유값 ÷ 유효 변수 수 × 100(표준화 변수 분산 중 이 축이 설명하는 비율)",
  plsTip:
    "X % = 그 성분이 설명한 표준화 변수 분산 비율 (tᵀt·‖p‖² / ‖Z₀‖²_F × 100) · 값 % = 그 성분이 설명한 색 값 분산 비율 (q²·tᵀt / ‖y₀‖² × 100)",
};

const finite = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

/** run 1개의 지표 값(§17.2). curve:* 는 series 계열, 없으면 null */
export function runValue(run: DesignMapRun, metricId: string, series: string | null): number | null {
  const [kind, key] = [metricId.slice(0, metricId.indexOf(":")), metricId.slice(metricId.indexOf(":") + 1)];
  let v: unknown = null;
  if (kind === "curve") v = series ? (run.curve?.[series] as Record<string, unknown> | undefined)?.[key] : null;
  else if (kind === "resp") v = run.resp?.[key];
  else if (kind === "tbl") v = run.tbl?.[key];
  else if (kind === "perf") v = run.perf?.[key]; // S19 §24.5: 성능(서버 design-map이 runs[].perf로 준다)
  return finite(v) ? v : null;
}

export interface MapRun {
  doe_no: number;
  run_key: string;
  values: Record<string, number>;
  v: number;
  /** S14 겹쳐 보기(§19.6): 비교 표의 run(선택 불가) / 해석(solver) 출처 = 속 빈 원·점선. 단독 보기에서는 둘 다 없음 */
  other?: boolean;
  hollow?: boolean;
}

export interface MapData {
  params: DesignMapParameter[];
  runs: MapRun[];
  excluded: { notDone: number; noValue: number };
  effVars: string[];
  constVars: string[];
  vmin: number;
  vmax: number;
}

/** 유효 run(성공 + 값 유한 + 변수 값 전부) · 유효 변수(표준편차 > 1e-12·max(1,|평균|)) */
export function buildMapData(dm: DesignMap, metricId: string, series: string | null): MapData {
  const runs: MapRun[] = [];
  const excluded = { notDone: 0, noValue: 0 };
  for (const r of dm.runs) {
    if (r.state !== "SUCCEEDED") {
      excluded.notDone++;
      continue;
    }
    const v = runValue(r, metricId, series);
    if (v === null || dm.parameters.some((p) => !finite(r.values[p.name]))) {
      excluded.noValue++;
      continue;
    }
    runs.push({ doe_no: r.doe_no, run_key: r.run_key, values: r.values, v });
  }
  const effVars: string[] = [];
  const constVars: string[] = [];
  for (const p of dm.parameters) {
    const z = zscore(runs.map((r) => r.values[p.name]));
    (runs.length >= 2 && z.sd > 1e-12 * Math.max(1, Math.abs(z.mean)) ? effVars : constVars).push(p.name);
  }
  const vs = runs.map((r) => r.v);
  return { params: dm.parameters, runs, excluded, effVars, constVars, vmin: vs.length ? Math.min(...vs) : NaN, vmax: vs.length ? Math.max(...vs) : NaN };
}

export interface PlotPoint {
  run: MapRun;
  x: number;
  y: number;
}
export interface Arrow {
  name: string;
  x: number;
  y: number;
}
export type Projection =
  | { kind: "message"; message: string }
  | { kind: "scatter1d"; xLabel: string; xTip: string | null; yLabel: string; points: PlotPoint[]; note: string; disableMethods: boolean }
  | { kind: "biplot"; method: "pls" | "pca"; xLabel: string; yLabel: string; tip: string; points: PlotPoint[]; arrows: Arrow[]; note: string | null };

const pcaLabel = (c: number, pct: number) => `PC${c} (X 분산 ${pct.toFixed(1)}%)`;
const plsLabel = (c: number, x: number, y: number) => `PLS${c} (X ${Math.round(x)}% · 값 ${Math.round(y)}%)`;

/** §17.5 투영 + 경계 조건 표(PLS·PCA 열). valueLabel = 색 값 지표 라벨(1D y축) */
export function project(data: MapData, method: "pls" | "pca", valueLabel: string): Projection {
  const n = data.runs.length;
  if (n < 3) return { kind: "message", message: TEXT.few(n) };
  if (!data.effVars.length) return { kind: "message", message: TEXT.allConst };
  if (data.effVars.length === 1) {
    const name = data.effVars[0];
    return { kind: "scatter1d", xLabel: name, xTip: null, yLabel: valueLabel, note: TEXT.oneVar, disableMethods: true, points: data.runs.map((r) => ({ run: r, x: r.values[name], y: r.v })) };
  }
  const X: Mat = data.runs.map((r) => data.effVars.map((p) => r.values[p]));
  const { Z } = standardize(X);
  const ys = data.runs.map((r) => r.v);
  const yz = zscore(ys);
  const doPca = (note: string | null): Projection => {
    const res = pca(Z, 2);
    return {
      kind: "biplot", method: "pca", xLabel: pcaLabel(1, res.pct[0]), yLabel: pcaLabel(2, res.pct[1]), tip: TEXT.pcaTip, note,
      points: data.runs.map((r, i) => ({ run: r, x: res.scores[i][0], y: res.scores[i][1] })),
      arrows: structureArrows(Z, res.scores).map(([x, y], j) => ({ name: data.effVars[j], x, y })),
    };
  };
  if (method === "pca") return doPca(null);
  if (!(yz.sd > 0)) return doPca(TEXT.yConst);
  const a = Math.min(2, data.effVars.length, n - 1);
  const res = plsNipals(Z, yz.z, a);
  if (res.ncomp === 0) return doPca(TEXT.noPls);
  if (res.ncomp < 2)
    return {
      kind: "scatter1d", xLabel: plsLabel(1, res.xPct[0], res.yPct[0]), xTip: TEXT.plsTip, yLabel: valueLabel, note: TEXT.pls1d, disableMethods: false,
      points: data.runs.map((r, i) => ({ run: r, x: res.scores[i][0], y: r.v })),
    };
  return {
    kind: "biplot", method: "pls", xLabel: plsLabel(1, res.xPct[0], res.yPct[0]), yLabel: plsLabel(2, res.xPct[1], res.yPct[1]), tip: TEXT.plsTip, note: null,
    points: data.runs.map((r, i) => ({ run: r, x: res.scores[i][0], y: res.scores[i][1] })),
    arrows: structureArrows(Z, res.scores).map(([x, y], j) => ({ name: data.effVars[j], x, y })),
  };
}

/** 지도 아래 회색 줄(제외 사유·상수 변수). 상수 변수는 PLS·PCA에서만 */
export function noteLines(data: MapData, method: Method): string[] {
  const out: string[] = [];
  const ex = [data.excluded.notDone ? `실패·미완료 ${data.excluded.notDone}` : "", data.excluded.noValue ? `값 없음 ${data.excluded.noValue}` : ""].filter(Boolean);
  if (ex.length) out.push(`제외: ${ex.join(" · ")}`);
  if (method !== "pc" && data.runs.length >= 3 && data.constVars.length && data.effVars.length) out.push(`상수 변수 제외: ${data.constVars.join(", ")}`);
  return out;
}

// ---- 평행 좌표 --------------------------------------------------------------------------------

export interface PcAxis {
  key: string;
  label: string;
  integer: boolean;
  isValue: boolean;
  lo: number;
  hi: number;
  ticks: number[];
}

function axisRange(vals: number[], integer: boolean): { lo: number; hi: number; ticks: number[] } {
  let lo = Math.min(...vals);
  let hi = Math.max(...vals);
  if (!(hi > lo)) [lo, hi] = [lo - 0.5, hi + 0.5];
  else {
    const pad = (hi - lo) * 0.05;
    [lo, hi] = [lo - pad, hi + pad];
  }
  let ticks: number[];
  if (integer) {
    const all: number[] = [];
    for (let k = Math.ceil(lo); k <= Math.floor(hi); k++) all.push(k);
    const step = Math.max(1, Math.ceil(all.length / 6));
    ticks = all.filter((_, i) => i % step === 0);
  } else ticks = niceTicks(lo, hi, 4).filter((t) => t >= lo && t <= hi);
  return { lo, hi, ticks };
}

/** 축 = 파라미터 전부(원 단위, 템플릿 순서) + 오른쪽 끝 값 축. 범위 = 유효 run 최소~최대 ±5%(범위 0이면 ±0.5) */
export function parallelAxes(data: MapData, valueLabel: string): PcAxis[] {
  if (!data.runs.length) return [];
  const axes: PcAxis[] = data.params.map((p) => ({ key: p.name, label: p.name, integer: p.integer, isValue: false, ...axisRange(data.runs.map((r) => r.values[p.name]), p.integer) }));
  axes.push({ key: "__value__", label: valueLabel, integer: false, isValue: true, ...axisRange(data.runs.map((r) => r.v), false) });
  return axes;
}

export function axisValue(run: MapRun, a: PcAxis): number {
  return a.isValue ? run.v : run.values[a.key];
}

/** 값 축 브러싱 머리: "값 120 ~ 150 · 7개 run" */
export function brushText(lo: number, hi: number, count: number): string {
  return `값 ${fmtNum(lo)} ~ ${fmtNum(hi)} · ${count}개 run`;
}

// ---- 툴팁·라벨 ---------------------------------------------------------------------------------

export function metricLabel(m: DesignMapMetric | undefined): string {
  if (!m) return "";
  return m.unit ? `${m.label} [${m.unit}]` : m.label;
}

/** 툴팁 3줄: DOE #7 · run__00007 / THK_1 2.31 · RIB_N 6 / 커브 최대값 152.3 */
export function tipLines(run: MapRun, params: DesignMapParameter[], m: DesignMapMetric | undefined): [string, string, string] {
  return [
    `DOE #${run.doe_no} · ${run.run_key}`,
    params.map((p) => `${p.name} ${fmtNum(run.values[p.name])}`).join(" · "),
    `${m?.label ?? "값"} ${fmtNum(run.v)}${m?.unit ? ` ${m.unit}` : ""}`,
  ];
}

// ---- 선택 저장(localStorage) --------------------------------------------------------------------

export const TAB_KEY = "physicsai.stage4.batchGraphTab";
export const PREFS_KEY = "physicsai.stage4.designMap";
/** S14: ⑤ 결과분석 탭(변수–응답·설계공간 지도·영향도·커브). 저장 키·옛 값(response|map)은 그대로 */
export type GraphTab = "response" | "map" | "influence" | "curve";
const GRAPH_TABS: GraphTab[] = ["response", "map", "influence", "curve"];
export interface Prefs {
  method: Method;
  metric: string;
  series: string | null;
  arrows: boolean;
}

export function readTab(): GraphTab {
  try {
    const v = globalThis.localStorage?.getItem(TAB_KEY);
    return GRAPH_TABS.includes(v as GraphTab) ? (v as GraphTab) : "response";
  } catch {
    return "response";
  }
}

export function writeTab(t: GraphTab) {
  try {
    globalThis.localStorage?.setItem(TAB_KEY, t);
  } catch {
    /* 저장 실패는 무시 */
  }
}

export function readPrefs(): Partial<Prefs> {
  try {
    const raw = globalThis.localStorage?.getItem(PREFS_KEY);
    const v = raw ? (JSON.parse(raw) as Record<string, unknown>) : null;
    if (!v || typeof v !== "object") return {};
    return {
      method: METHODS.some((m) => m.key === v.method) ? (v.method as Method) : undefined,
      metric: typeof v.metric === "string" ? v.metric : undefined,
      series: typeof v.series === "string" ? v.series : undefined,
      arrows: typeof v.arrows === "boolean" ? v.arrows : undefined,
    };
  } catch {
    return {};
  }
}

export function writePrefs(p: Prefs) {
  try {
    globalThis.localStorage?.setItem(PREFS_KEY, JSON.stringify(p));
  } catch {
    /* 저장 실패는 무시 */
  }
}

/** 목록에 없는 지표는 기본(curve:max, 없으면 첫 지표) */
export function pickMetric(metrics: DesignMapMetric[], want: string | undefined): DesignMapMetric | undefined {
  return metrics.find((m) => m.id === want) ?? metrics.find((m) => m.id === DEFAULT_METRIC) ?? metrics[0];
}

