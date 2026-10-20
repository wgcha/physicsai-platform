// 커브 열 규칙(성능 값은 서버 design-map): ⑤ 결과분석의 응답 선택지에 커브 대표값(curve:max|min|absmax + 계열)을 싣는 순수 규칙.
// S19 §24.5: 성능(perf:<NAME>) 값·사유는 서버가 performance.perf_value로 계산해 design-map `runs[].perf`·`perf_reason`으로 준다 — 프런트는 계산하지 않는다.
import type { DesignMap, DesignMapRun } from "../api/designMap";
import { finOrNull, type RtResponse } from "./resultTable";

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
