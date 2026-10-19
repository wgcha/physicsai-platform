// S14 어댑터 (b): 해석 DOE result-table API(§19.5) → 결과 표(source "solver"). 거의 그대로 옮기고, 영향도 사용 가능 여부·사유만 채운다.
import type { DoeResultTable } from "../../api/analysis";
import type { InfluenceClass } from "../../api";
import { OFF_FALLBACK_TEXT } from "../influence";
import { finOrNull, NO_META, type ResultTable } from "../resultTable";

/** 영향도 사용 가능 여부·등급·문구는 서버(influence_class·influence_note, S15 §20.7)를 따른다 */
export function fromDoe(t: DoeResultTable): ResultTable {
  const cls: InfluenceClass = t.influence_class;
  const ok = cls !== "off";
  const note = t.influence_note ?? null;
  return {
    source: "solver",
    origin: { kind: "train_doe", id: t.doe_id, label: t.label },
    parameters: t.parameters.map((x) => ({ name: x.name, integer: x.integer, min: finOrNull(x.min), max: finOrNull(x.max), unit: x.unit ?? null })),
    responses: t.responses.map((x) => ({ name: x.name, unit: x.unit ?? null })),
    meta: { ...NO_META, engine_version: t.meta?.engine_version ?? null, baseline_id: t.meta?.baseline_id ?? null, scene: t.meta?.scene ?? null },
    rows: t.rows.map((r) => ({
      run_id: r.run_id,
      no: r.no,
      state: r.state,
      params: Object.fromEntries(Object.entries(r.params).map(([k, v]) => [k, finOrNull(v)])),
      responses: Object.fromEntries(Object.entries(r.responses).map(([k, v]) => [k, finOrNull(v)])),
      curve: null,
    })),
    counts: { ...t.counts },
    influence: { ok, cls, note: cls === "reference" ? note : null, reason: ok ? null : (note ?? OFF_FALLBACK_TEXT) },
    notes: [...t.notes],
    designMap: null,
  };
}
