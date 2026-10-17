// S14 어댑터 (a): 기존 일괄 예측 배치(GET /predict-batches/{bid} 결과 표 + GET …/design-map 의 커브 요약) → 결과 표(source "predict").
// 파라미터 값 = 반영값(applied_values), state가 SUCCEEDED가 아니면 응답 전부 null, curve = design-map run.curve(성공 run만). 새 API 없음(§19.2 A3).
import type { InfluenceClass, PredictBatch } from "../../api";
import { UNKNOWN_METHOD_TEXT } from "../influence";
import type { DesignMap } from "../../api/designMap";
import { finOrNull, NO_META, usableRowCount, type ResultTable, type RtMeta } from "../resultTable";

/** 영향도에 필요한 최소 유효 run(§19.6): max(5, p+2) */
export const minInfluenceRuns = (p: number) => Math.max(5, p + 2);

export function fromBatch(b: PredictBatch, dm: DesignMap | null, meta: RtMeta = NO_META): ResultTable {
  const ranges = new Map((dm?.parameters ?? []).map((p) => [p.name, p]));
  const curveOf = new Map((dm?.runs ?? []).map((r) => [r.doe_no, r.curve ?? null]));
  const ints = new Set((dm?.parameters ?? []).filter((p) => p.integer).map((p) => p.name));
  const rows = b.rows.map((r) => {
    const ok = r.state === "SUCCEEDED";
    return {
      run_id: r.run_key,
      no: r.doe_no,
      state: r.state,
      params: Object.fromEntries(b.parameters.map((n) => [n, finOrNull(r.applied_values?.[n] ?? r.values?.[n])])),
      responses: Object.fromEntries(b.responses.map((x) => [x.name, ok ? finOrNull(r.responses?.[x.name]) : null])),
      curve: ok ? (curveOf.get(r.doe_no) ?? null) : null,
    };
  });
  // S15 §20.7: 등급·안내는 서버 sampling이 정한다(없으면 알 수 없는 방식 = 참고용). n·응답 판정만 여기서 한다
  const cls: InfluenceClass = b.sampling?.influence_class ?? "reference";
  const note = cls === "reference" ? (b.sampling ? (b.sampling.influence_note ?? null) : UNKNOWN_METHOD_TEXT) : null;
  const rt: ResultTable = {
    source: "predict",
    origin: { kind: "predict_batch", id: b.id, label: b.label },
    parameters: b.parameters.map((n) => ({ name: n, integer: ints.has(n), min: finOrNull(ranges.get(n)?.min), max: finOrNull(ranges.get(n)?.max), unit: null })),
    responses: b.responses.map((x) => ({ name: x.name, unit: x.unit || null })),
    meta,
    rows,
    counts: { total: rows.length, usable: 0, no_response: 0 },
    influence: { ok: false, cls, note, reason: null },
    notes: [],
    designMap: dm,
  };
  const first = b.responses[0]?.name ?? null;
  rt.counts.usable = usableRowCount(rt, first);
  rt.counts.no_response = rows.length - rt.counts.usable;
  const need = minInfluenceRuns(rt.parameters.length);
  rt.influence.ok = !!first && rt.counts.usable >= need;
  rt.influence.reason = !first ? "응답 정의가 없어 영향도를 계산할 수 없습니다" : rt.counts.usable < need ? `영향도에는 유효 run이 ${need}개 이상 필요합니다(현재 ${rt.counts.usable}개)` : null;
  return rt;
}
