// S17 D3-65 보강 2: ⑤ 결과분석의 응답 선택지에 커브 대표값(curve:max|min|absmax + 계열)과 성능(perf:<NAME>)을 싣는 순수 규칙.
// 서버 변경 없음 — 일괄 예측 배치 표(`predict_batch_runs.responses`)와 design-map(run별 curve 요약·RESPONSES.txt `<NAME>_MAX|_MIN`)에서 프런트가 값을 읽는다.
// 서버 performance.perf_value와 같은 규칙(MAX = _MAX, MIN = _MIN, ABSMAX = max(|min|,|max|), CURVE = 계열 stat). 단 H3D 정의 변경 감지(SPEC_CHANGED)는 서버 몫이라 여기엔 없다.
import type { DesignMap, DesignMapRun } from "../api/designMap";
import type { PerfRow } from "../stages/stage5/surrogate/perfRules";
import { perfId, perfLabel } from "../stages/stage5/surrogate/perfRules";
import { finOrNull, isFin, type RtResponse } from "./resultTable";

export const NO_RESP_HINT = "④ 템플릿에 성능을 정의하거나 커브 대표값을 고르세요";
/** 커브 열은 계열이 많을 때 앞의 N개까지만 열로 둔다(표 폭) */
export const MAX_CURVE_SERIES = 12;

export const CURVE_STATS = [
  { key: "max", label: "최대" },
  { key: "min", label: "최소" },
  { key: "absmax", label: "|최대|" },
] as const;
type CurveStat = (typeof CURVE_STATS)[number]["key"];

/** 열 이름(= 결과 표 responses 키): `curve:absmax|Node 100 / X` */
export const curveColumn = (stat: CurveStat, series: string) => `curve:${stat}|${series}`;

export function curveColumns(dm: DesignMap | null): RtResponse[] {
  const out: RtResponse[] = [];
  for (const s of (dm?.series ?? []).slice(0, MAX_CURVE_SERIES))
    for (const st of CURVE_STATS) out.push({ name: curveColumn(st.key, s), unit: null, label: `${s} ${st.label}(커브)`, kind: "curve" });
  return out;
}

/** 열 이름 → run의 커브 대표값 */
export function curveValue(name: string, run: DesignMapRun | undefined): number | null {
  const m = /^curve:(max|min|absmax)\|(.*)$/s.exec(name);
  if (!m || !run?.curve) return null;
  return finOrNull((run.curve[m[2]] as Record<string, unknown> | undefined)?.[m[1]]);
}

const STAT_KEY = { MAX: "max", MIN: "min", ABSMAX: "absmax" } as const;

/** 성능(perf:<NAME>) 값: 배치 표 값이 있으면 그것, 없으면 design-map에서(커브 = curve.json 계열 stat, H3D = RESPONSES.txt) */
export function perfValue(def: PerfRow, tableValue: unknown, run: DesignMapRun | undefined): number | null {
  const t = finOrNull(tableValue);
  if (t !== null) return t;
  if (!run) return null;
  if (def.spec.source === "CURVE") {
    const series = def.spec.series ?? Object.keys(run.curve ?? {})[0];
    return series ? finOrNull((run.curve?.[series] as Record<string, unknown> | undefined)?.[STAT_KEY[def.spec.stat]]) : null;
  }
  const hi = run.resp?.[`${def.name}_MAX`];
  const lo = run.resp?.[`${def.name}_MIN`];
  if (def.spec.stat === "MAX") return finOrNull(hi);
  if (def.spec.stat === "MIN") return finOrNull(lo);
  return isFin(hi) && isFin(lo) ? Math.max(Math.abs(hi), Math.abs(lo)) : null;
}

export type PerfDesignRun = DesignMapRun & { perf?: Record<string, number | null> };

/** design-map 원본에 `perf:<NAME>` 지표를 더한 사본(값이 하나도 없는 성능은 뺀다). 성능이 없으면 원본 그대로 */
export function withPerfMetrics(dm: DesignMap | null, perfs: PerfRow[], tableOf: (doe_no: number, name: string) => unknown): DesignMap | null {
  if (!dm || !perfs.length) return dm;
  const runs: PerfDesignRun[] = dm.runs.map((r) => ({ ...r, perf: Object.fromEntries(perfs.map((p) => [p.name, r.state === "SUCCEEDED" ? perfValue(p, tableOf(r.doe_no, p.name), r) : null])) }));
  const metrics = perfs
    .filter((p) => runs.some((r) => isFin(r.perf?.[p.name])))
    .map((p) => ({ id: perfId(p.name), label: perfLabel(p), unit: p.unit || null, needs_series: false }));
  return metrics.length ? { ...dm, runs, metrics: [...dm.metrics, ...metrics] } : dm;
}
