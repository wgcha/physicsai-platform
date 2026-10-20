// S19 §24.5 목: design-map의 성능(perf:) 값·사유·지표 — 서버 performance.perf_value·REASON_TEXT 흉내(프런트 화면 코드는 계산하지 않는다).
import type { TemplateResponse } from "../api";
import type { DesignMapMetric, DesignMapRun } from "../api/designMap";
import { perfId, perfLabel, perfRows, type PerfRow } from "../stages/stage5/surrogate/perfRules";

const fin = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
const KEY = { MAX: "max", MIN: "min", ABSMAX: "absmax" } as const;

export const MOCK_REASON_TEXT: Record<string, string> = {
  NO_VALUE: "값 없음(NO_VALUE)",
  SPEC_CHANGED: "정의가 바뀐 뒤 추출하지 않음 — 다시 추출 필요",
  NOT_EXTRACTED: "추출 결과 없음",
  NO_CURVE: "커브 없음",
  SERIES_MISSING: "커브 계열 없음",
};

/** (값, 사유) — 성공 run 1개의 성능 1개 */
function perfOne(d: PerfRow, run: DesignMapRun, table: unknown): [number | null, string | null] {
  if (d.spec.source === "CURVE") {
    if (!run.curve) return [null, "NO_CURVE"];
    const series = d.spec.series ?? Object.keys(run.curve)[0];
    const st = series ? (run.curve[series] as Record<string, unknown> | undefined) : undefined;
    if (!st) return [null, "SERIES_MISSING"];
    const v = st[KEY[d.spec.stat]];
    return fin(v) ? [v, null] : [null, "NO_VALUE"];
  }
  if (!run.resp) return fin(table) ? [table, null] : [null, "NOT_EXTRACTED"]; // 옛 추출 run은 결과 표 값(Q11)
  const hi = run.resp[`${d.name}_MAX`];
  const lo = run.resp[`${d.name}_MIN`];
  const v = d.spec.stat === "MAX" ? hi : d.spec.stat === "MIN" ? lo : fin(hi) && fin(lo) ? Math.max(Math.abs(hi), Math.abs(lo)) : null;
  return fin(v) ? [v, null] : [null, "NO_VALUE"];
}

/** runs(성공 run은 curve·resp·tbl 채워진 상태)에 perf·perf_reason을 더하고, 지표·spec_changed·reason_text를 돌려준다 */
export function addMockPerf(runs: DesignMapRun[], responses: TemplateResponse[]): { metrics: DesignMapMetric[]; specChanged: number; reasonText: Record<string, string> } {
  const defs = perfRows(responses);
  const reasonText: Record<string, string> = {};
  let specChanged = 0;
  if (!defs.length) return { metrics: [], specChanged, reasonText };
  for (const r of runs) {
    if (r.state !== "SUCCEEDED") continue;
    const perf: Record<string, number | null> = {};
    const why: Record<string, string> = {};
    for (const d of defs) {
      const [v, w] = perfOne(d, r, r.tbl?.[d.name]);
      perf[d.name] = v;
      if (w) {
        why[d.name] = w;
        reasonText[w] = MOCK_REASON_TEXT[w] ?? w;
      }
    }
    r.perf = perf;
    r.perf_reason = why;
    if (Object.values(why).includes("SPEC_CHANGED")) specChanged++;
  }
  const metrics = defs
    .filter((d) => runs.some((r) => fin(r.perf?.[d.name])))
    .map((d) => ({ id: perfId(d.name), label: perfLabel(d), unit: d.unit || null, needs_series: false, spec_changed: runs.filter((r) => r.perf_reason?.[d.name] === "SPEC_CHANGED").length }));
  return { metrics, specChanged, reasonText };
}
