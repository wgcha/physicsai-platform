// S14 어댑터 (b): 해석 DOE result-table API(§19.5) → 결과 표(source "solver"). 거의 그대로 옮기고, 영향도 사용 가능 여부·사유만 채운다.
import type { DoeResultTable } from "../../api/analysis";
import { NOT_LHS_TEXT } from "../influence";
import { finOrNull, NO_META, type ResultTable } from "../resultTable";

/** 서버 type = doe_type 원값(TYPE_LATINHYPERCUBE 등) — 영향도 사유 문구 선택에만 쓴다. 사용 가능 여부는 서버 influence_ok만 따른다 */
export const isLhsType = (t: string | null | undefined) => /LHS|LATIN/i.test(t ?? "");

export function fromDoe(t: DoeResultTable): ResultTable {
  const lhs = isLhsType(t.type);
  const p = t.parameters.length;
  const usable = t.counts.usable;
  const reason = t.influence_ok
    ? null
    : !lhs
      ? NOT_LHS_TEXT
      : !t.responses.length
        ? "응답이 없어 영향도를 계산할 수 없습니다"
        : `영향도에는 유효 run이 ${Math.max(5, p + 2)}개 이상 필요합니다(현재 ${usable}개)`;
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
    influence: { ok: t.influence_ok, lhs, reason },
    notes: [...t.notes],
    designMap: null,
  };
}
