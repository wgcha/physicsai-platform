// S14 어댑터 (a): 기존 일괄 예측 배치(GET /predict-batches/{bid} 결과 표 + GET …/design-map 의 커브 요약) → 결과 표(source "predict").
// 파라미터 값 = 반영값(applied_values), state가 SUCCEEDED가 아니면 응답 전부 null, curve = design-map run.curve(성공 run만). 새 API 없음(§19.2 A3).
import type { InfluenceClass, PredictBatch, TemplateResponse } from "../../api";
import { UNKNOWN_METHOD_TEXT } from "../influence";
import type { DesignMap, DesignMapRun } from "../../api/designMap";
import { perfRows } from "../../stages/stage5/surrogate/perfRules";
import { finOrNull, isFin, NO_META, usableRowCount, type ResultTable, type RtMeta, type RtResponse } from "../resultTable";
import { curveColumns, curveValue, NO_RESP_HINT } from "../perfColumns";

/** 영향도에 필요한 최소 유효 run(§19.6): max(5, p+2) */
export const minInfluenceRuns = (p: number) => Math.max(5, p + 2);

/**
 * S17 D3-65 보강 2: 응답 열 = 결과 표 열(b.responses) + 템플릿 성능(perf:<NAME> — 배치에 열이 없는 성능) + 커브 대표값(curve:max|min|absmax × 계열).
 * perfs = 템플릿 응답 정의(성능은 spec이 있는 행). S19 §24.5: 성능 값 = 서버 design-map `runs[].perf[name]`(프런트 계산 없음),
 * design-map이 없을 때(null)만 배치 표 값. 추가 성능 열 = design-map `perf:` 지표 중 배치 표에 없는 이름. null 값의 사유는 `rows[].why`.
 */
export function fromBatch(b: PredictBatch, dm: DesignMap | null, meta: RtMeta = NO_META, perfs: TemplateResponse[] | null = null): ResultTable {
  const ranges = new Map((dm?.parameters ?? []).map((p) => [p.name, p]));
  const dmRun = new Map((dm?.runs ?? []).map((r) => [r.doe_no, r]));
  const curveOf = new Map((dm?.runs ?? []).map((r) => [r.doe_no, r.curve ?? null]));
  const ints = new Set((dm?.parameters ?? []).filter((p) => p.integer).map((p) => p.name));
  const defs = perfRows(perfs);
  const baseNames = new Set(b.responses.map((x) => x.name));
  const dmPerf = (dm?.metrics ?? []).filter((m) => m.id.startsWith("perf:")).map((m) => ({ name: m.id.slice("perf:".length), unit: m.unit ?? null }));
  const perfNames = new Set([...defs.map((d) => d.name), ...dmPerf.map((m) => m.name)]);
  const extraPerf: RtResponse[] = dmPerf.filter((m) => !baseNames.has(m.name)).map((m) => ({ name: m.name, unit: m.unit, kind: "perf" }));
  /** 성능 값: 서버 값(키가 있으면 null도 그대로 — SPEC_CHANGED가 옛 표 값으로 되돌아가면 안 된다), 서버 값이 없으면 표 값 */
  const perfOf = (name: string, table: unknown, run: DesignMapRun | undefined): number | null => (run?.perf && name in run.perf ? finOrNull(run.perf[name]) : finOrNull(table));
  const curveCols = curveColumns(dm);
  const rows = b.rows.map((r) => {
    const ok = r.state === "SUCCEEDED";
    const run = dmRun.get(r.doe_no);
    const resp: Record<string, number | null> = {};
    for (const x of b.responses) resp[x.name] = !ok ? null : perfNames.has(x.name) ? perfOf(x.name, r.responses?.[x.name], run) : finOrNull(r.responses?.[x.name]);
    for (const x of extraPerf) resp[x.name] = ok ? perfOf(x.name, r.responses?.[x.name], run) : null;
    for (const x of curveCols) resp[x.name] = ok ? curveValue(x.name, run) : null;
    const why: Record<string, string> = {};
    if (ok) for (const n of perfNames) if (n in resp && resp[n] === null && run?.perf_reason?.[n]) why[n] = run.perf_reason[n];
    return {
      run_id: r.run_key,
      no: r.doe_no,
      state: r.state,
      params: Object.fromEntries(b.parameters.map((n) => [n, finOrNull(r.applied_values?.[n] ?? r.values?.[n])])),
      responses: resp,
      curve: ok ? (curveOf.get(r.doe_no) ?? null) : null,
      ...(Object.keys(why).length ? { why } : {}),
    };
  });
  const respCols: RtResponse[] = [
    ...b.responses.map((x) => (perfNames.has(x.name) ? { name: x.name, unit: x.unit || null, kind: "perf" as const } : { name: x.name, unit: x.unit || null })),
    ...extraPerf.filter((x) => rows.some((r) => isFin(r.responses[x.name]))),
    ...curveCols.filter((x) => rows.some((r) => isFin(r.responses[x.name]))),
  ];
  // S15 §20.7: 등급·안내는 서버 sampling이 정한다(없으면 알 수 없는 방식 = 참고용). n·응답 판정만 여기서 한다
  const cls: InfluenceClass = b.sampling?.influence_class ?? "reference";
  const note = cls === "reference" ? (b.sampling ? (b.sampling.influence_note ?? null) : UNKNOWN_METHOD_TEXT) : null;
  const rt: ResultTable = {
    source: "predict",
    origin: { kind: "predict_batch", id: b.id, label: b.label },
    parameters: b.parameters.map((n) => ({ name: n, integer: ints.has(n), min: finOrNull(ranges.get(n)?.min), max: finOrNull(ranges.get(n)?.max), unit: null })),
    responses: respCols,
    meta,
    rows,
    counts: { total: rows.length, usable: 0, no_response: 0 },
    influence: { ok: false, cls, note, reason: null },
    notes: [],
    designMap: dm,
    ...(dm?.reason_text ? { reasonText: dm.reason_text } : {}),
  };
  const stale = dm?.counts?.spec_changed ?? 0;
  if (stale > 0) rt.notes.push(`성능 정의가 바뀐 뒤 다시 추출하지 않은 run ${stale}개는 성능 값이 비어 있습니다 — ⑥ 최적화 설정의 성능 표에서 '다시 추출'`);
  const first = respCols[0]?.name ?? null;
  rt.counts.usable = usableRowCount(rt, first);
  rt.counts.no_response = rows.length - rt.counts.usable;
  const need = minInfluenceRuns(rt.parameters.length);
  const anyData = respCols.some((x) => rows.some((r) => isFin(r.responses[x.name])));
  const hint = anyData ? "" : ` — ${NO_RESP_HINT}`; // 응답 열이 모두 비면 off 사유에 안내를 덧붙인다
  rt.influence.ok = !!first && rt.counts.usable >= need;
  rt.influence.reason = !first ? `응답 정의가 없어 영향도를 계산할 수 없습니다${hint}` : rt.counts.usable < need ? `영향도에는 유효 run이 ${need}개 이상 필요합니다(현재 ${rt.counts.usable}개)${hint}` : null;
  return rt;
}
