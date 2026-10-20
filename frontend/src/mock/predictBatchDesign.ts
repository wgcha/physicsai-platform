// phase3.md §17.4 S12 목(R-F 분할): GET /predict-batches/{bid}/design-map — 완료 run의 curve.json 계열별 max·min·|max|, RESP, 결과 표 값.
import type { PredictBatch, TemplateResponse } from "../api/types";
import { isIntegerFormat } from "../lib/format";
import { responseFn } from "./data";
import { addMockPerf } from "./designMapPerf";
import type { MockServer } from "./server";
import type { DesignMap, DesignMapCurveStats, DesignMapMetric, DesignMapRun } from "../api/designMap";
import { round4 } from "./predictBatchRec";

// ------------------------------------------------------------------ S12 설계공간 지도(백엔드 run_metrics·design_map 흉내)
const fin = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

export function curveStatsOf(series: { name: string; x: number[]; y: number[] }[]): Record<string, DesignMapCurveStats> {
  const out: Record<string, DesignMapCurveStats> = {};
  for (const s of series) {
    if (Object.keys(out).length >= 50) break;
    if (!s?.name || out[s.name] || !Array.isArray(s.y) || s.y.length !== s.x?.length || !s.y.length || ![...s.x, ...s.y].every(fin)) continue;
    let iMax = 0;
    let iMin = 0;
    s.y.forEach((v, i) => {
      if (v > s.y[iMax]) iMax = i;
      if (v < s.y[iMin]) iMin = i;
    });
    const [hi, lo] = [s.y[iMax], s.y[iMin]];
    out[s.name] = { max: hi, min: lo, absmax: Math.max(Math.abs(hi), Math.abs(lo)), x_at_max: s.x[iMax], x_at_min: s.x[iMin], n: s.y.length };
  }
  return out;
}

export function designMapOut(srv: MockServer, b: PredictBatch): DesignMap {
  const ps = srv.paramSets.find((p) => p.id === b.param_set.id)!;
  const ints = new Set(ps.tpl_params.filter((t) => isIntegerFormat(t.format)).map((t) => t.name));
  const h3d = ps.responses.filter((r) => r.spec);
  const units = Object.fromEntries(ps.responses.map((r) => [r.name, r.unit || null]));
  const series: string[] = [];
  const respKeys = new Set<string>();
  const counts = { total: b.rows.length, succeeded: 0, no_curve: 0, no_resp: 0 };
  const runs: DesignMapRun[] = b.rows.map((r) => {
    const values = Object.fromEntries(b.parameters.filter((n) => fin(r.applied_values[n])).map((n) => [n, r.applied_values[n]]));
    const row: DesignMapRun = { doe_no: r.doe_no, run_key: r.run_key, state: r.state, values, curve: null, resp: null, tbl: null };
    if (r.state !== "SUCCEEDED" || !r.job_id) return row;
    counts.succeeded++;
    const j = srv.jobs.find((x) => x.id === r.job_id);
    const a = srv.artifacts.find((x) => x.id === (j?.result as { curve_artifact_id?: string } | null)?.curve_artifact_id);
    const cs = a ? curveStatsOf((JSON.parse(a.body) as { series: { name: string; x: number[]; y: number[] }[] }).series) : {};
    if (Object.keys(cs).length) {
      row.curve = cs;
      for (const k of Object.keys(cs)) if (!series.includes(k)) series.push(k);
    } else counts.no_curve++;
    if (h3d.length) {
      const pred = responseFn(r.applied_values);
      row.resp = Object.fromEntries(h3d.flatMap((x) => (fin(pred[x.name]) ? [[`${x.name}_MAX`, round4(pred[x.name])], [`${x.name}_MIN`, round4(pred[x.name] * 0.04)]] : [])));
      Object.keys(row.resp).forEach((k) => respKeys.add(k));
    } else counts.no_resp++;
    row.tbl = r.responses ?? {};
    return row;
  });
  const metrics: DesignMapMetric[] = [];
  if (series.length)
    metrics.push(
      { id: "curve:max", label: "커브 최대값", unit: null, needs_series: true },
      { id: "curve:min", label: "커브 최소값", unit: null, needs_series: true },
      { id: "curve:absmax", label: "커브 |최대|", unit: null, needs_series: true },
    );
  for (const k of [...respKeys].sort()) {
    const name = k.slice(0, k.lastIndexOf("_"));
    metrics.push({ id: `resp:${k}`, label: `${name} ${k.endsWith("_MAX") ? "최대" : "최소"}(RESP)`, unit: units[name] ?? null, needs_series: false });
  }
  if (!runs.some((x) => x.resp))
    for (const r of ps.responses)
      if (runs.some((x) => fin(x.tbl?.[r.name]))) metrics.push({ id: `tbl:${r.name}`, label: `${r.name}(결과 표)`, unit: r.unit || null, needs_series: false });
  const perf = addMockPerf(runs, ps.responses as TemplateResponse[]); // S19 §24.5: curve → resp → tbl → perf(끝)
  return {
    batch_id: b.id, label: b.label, status: b.status,
    parameters: ps.parameters.map((p) => ({ name: p.name, integer: ints.has(p.name), min: p.min, max: p.max })),
    series, metrics: [...metrics, ...perf.metrics], runs, counts: (perf.metrics.length || perf.specChanged ? { ...counts, spec_changed: perf.specChanged } : counts) as DesignMap["counts"], reason_text: perf.reasonText, // 서버: spec_changed는 perf 지표가 있거나 > 0일 때만 응답에 있다
  };
}
