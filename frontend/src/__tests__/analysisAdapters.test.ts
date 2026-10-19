// V3-S14-4(phase3.md §19.9): 어댑터 — fromBatch(applied_values·실패 run null·curve 요약), fromDoe(solver), 메타 null 허용, 두 출처 같은 ResultTable 모양. + 겹쳐 보기 순수 규칙(compare.ts).
import { describe, expect, it } from "vitest";
import { fromBatch } from "../analysis/adapters/fromBatch";
import { fromDoe } from "../analysis/adapters/fromDoe";
import { commonResponses, metaChips, metaDiffers, nameSetDiff, unionRange } from "../analysis/compare";
import { OFF_FALLBACK_TEXT, UNKNOWN_METHOD_TEXT } from "../analysis/influence";
import { NO_META } from "../analysis/resultTable";
import type { PredictBatch } from "../api";
import type { DesignMap } from "../api/designMap";
import type { DoeResultTable } from "../api/analysis";

const batch = {
  id: "pb-9", label: "B-009", status: "DONE", source_kind: "LHS", parameters: ["THK", "RIB_N"], responses: [{ name: "Stress", unit: "MPa" }],
  rows: [
    { doe_no: 1, run_key: "run__00001", state: "SUCCEEDED", values: { THK: 2.3, RIB_N: 6.4 }, applied_values: { THK: 2.31, RIB_N: 6 }, responses: { Stress: 151.9 } },
    { doe_no: 2, run_key: "run__00002", state: "FAILED", values: { THK: 3, RIB_N: 4 }, applied_values: { THK: 3, RIB_N: 4 }, responses: { Stress: 99 } },
    { doe_no: 3, run_key: "run__00003", state: "SUCCEEDED", values: { THK: 4, RIB_N: 5 }, applied_values: { THK: 4, RIB_N: 5 }, responses: { Stress: Number.NaN } },
  ],
} as unknown as PredictBatch;
const dm = {
  parameters: [{ name: "THK", integer: false, min: 2, max: 5 }, { name: "RIB_N", integer: true, min: 3, max: 8 }],
  runs: [{ doe_no: 1, run_key: "run__00001", state: "SUCCEEDED", values: {}, curve: { S1: { max: 152.3, min: -3.1, absmax: 152.3, x_at_max: 0.012, x_at_min: 0.002, n: 1200 } }, resp: null, tbl: null }],
} as unknown as DesignMap;

const doe: DoeResultTable = {
  doe_id: "doe-1", label: "DOE-001", study_id: "s", type: "LHS",
  parameters: [{ name: "THK", integer: false, min: 2, max: 5, unit: null }, { name: "RIB_N", integer: true, min: 3, max: 8 }],
  responses: [{ name: "Stress", unit: null }],
  meta: { engine_version: null, baseline_id: null, scene: null },
  rows: [{ run_id: "run__00014", no: 14, state: "SUCCEEDED", params: { THK: 2.31, RIB_N: 6 }, responses: { Stress: 151.9 } }, { run_id: "run__00015", no: 15, state: "SOLVE_FAILED", params: { THK: 3, RIB_N: 5 }, responses: { Stress: null } }],
  counts: { total: 2, usable: 1, no_response: 1 }, influence_ok: false, notes: ["응답 파일이 없습니다"],
  influence_class: "off", influence_note: "영향도에는 유효 run이 5개 이상 필요합니다(현재 1개)",
  sampling: { method: "TYPE_LATINHYPERCUBE", label: "LatinHyperCube", desc_id: "hs_lhs", options: {} },
};
/** S15 §20.6: 서버가 정한 표본 방식 등급 */
const samp = (kind: string, cls: "formal" | "reference", note: string | null) => ({ kind, method: kind.toUpperCase(), desc_id: kind, label: kind, influence_class: cls, influence_note: note, recommended_count: null, meta: {} });

describe("어댑터 (V3-S14-4)", () => {
  it("fromBatch: 반영값·실패 run 응답 null·비유한 null·curve 요약·메타 null", () => {
    const t = fromBatch(batch, dm);
    expect(t.source).toBe("predict");
    expect(t.origin).toEqual({ kind: "predict_batch", id: "pb-9", label: "B-009" });
    expect(t.parameters).toEqual([
      { name: "THK", integer: false, min: 2, max: 5, unit: null },
      { name: "RIB_N", integer: true, min: 3, max: 8, unit: null },
    ]);
    expect(t.responses).toEqual([{ name: "Stress", unit: "MPa" }]);
    expect(t.rows[0]).toEqual({ run_id: "run__00001", no: 1, state: "SUCCEEDED", params: { THK: 2.31, RIB_N: 6 }, responses: { Stress: 151.9 }, curve: dm.runs[0].curve });
    expect(t.rows[1].responses).toEqual({ Stress: null }); // 성공이 아닌 run
    expect(t.rows[1].curve).toBeNull();
    expect(t.rows[2].responses).toEqual({ Stress: null }); // NaN → null
    expect(t.meta).toEqual(NO_META);
    expect(t.counts).toEqual({ total: 3, usable: 1, no_response: 2 });
    expect(t.designMap).toBe(dm);
  });

  it("fromBatch: design-map 없이도(null) 동작 — 범위·curve 없음, 등급·문구는 서버 sampling(reference), n 부족은 프런트가 판정", () => {
    const note = "직접 만든 표 — 표본 분포를 알 수 없어 영향도는 참고용입니다";
    const t = fromBatch({ ...batch, source_kind: "TABLE", sampling: samp("table", "reference", note) } as PredictBatch, null);
    expect(t.parameters.map((p) => [p.min, p.max])).toEqual([[null, null], [null, null]]);
    expect(t.rows.every((r) => r.curve === null)).toBe(true);
    expect(t.influence.cls).toBe("reference");
    expect(t.influence.note).toBe(note);
    expect(t.influence.ok).toBe(false); // 유효 1개 < max(5, p+2)
    expect(t.influence.reason).toBe("영향도에는 유효 run이 5개 이상 필요합니다(현재 1개)");
    // formal은 안내 없음, sampling이 없으면(옛 응답) 알 수 없는 방식 = 참고용
    expect(fromBatch({ ...batch, sampling: samp("sobol", "formal", null) } as PredictBatch, null).influence).toMatchObject({ cls: "formal", note: null });
    expect(fromBatch(batch, null).influence).toMatchObject({ cls: "reference", note: UNKNOWN_METHOD_TEXT });
  });

  it("fromDoe: solver 출처, curve 없음, 영향도 등급·사유는 서버(influence_class·influence_note), 메타 null 허용", () => {
    const t = fromDoe(doe);
    expect(t.source).toBe("solver");
    expect(t.origin).toEqual({ kind: "train_doe", id: "doe-1", label: "DOE-001" });
    expect(t.parameters[1]).toEqual({ name: "RIB_N", integer: true, min: 3, max: 8, unit: null });
    expect(t.rows.every((r) => r.curve === null)).toBe(true);
    expect(t.rows[1].responses).toEqual({ Stress: null });
    expect(t.meta).toEqual(NO_META);
    expect(t.notes).toEqual(["응답 파일이 없습니다"]);
    expect(t.influence).toEqual({ ok: false, cls: "off", note: null, reason: "영향도에는 유효 run이 5개 이상 필요합니다(현재 1개)" });
    const ref = "부분 요인(해상도 IV) — 2인자 교호작용끼리 교락되어 영향도는 참고용입니다(주효과는 2인자 교호작용과 교락 없음)";
    expect(fromDoe({ ...doe, influence_ok: true, influence_class: "reference", influence_note: ref }).influence).toEqual({ ok: true, cls: "reference", note: ref, reason: null });
    expect(fromDoe({ ...doe, influence_ok: true, influence_class: "formal", influence_note: null }).influence).toEqual({ ok: true, cls: "formal", note: null, reason: null });
    // off인데 사유가 없으면 대체 문구
    expect(fromDoe({ ...doe, influence_note: null }).influence.reason).toBe(OFF_FALLBACK_TEXT);
  });

  it("두 출처는 같은 ResultTable 모양(키 집합 동일, designMap만 선택)", () => {
    const a = Object.keys(fromBatch(batch, dm)).sort();
    const b = Object.keys(fromDoe(doe)).sort();
    expect(a).toEqual(b);
    expect(Object.keys(fromBatch(batch, dm).rows[0]).sort()).toEqual(Object.keys(fromDoe(doe).rows[0]).sort());
  });
});

describe("겹쳐 보기 규칙 (compare.ts, V3-S14-6)", () => {
  const t1 = fromBatch(batch, dm);
  const t2 = fromDoe(doe);
  it("파라미터 이름 집합: 대소문자 구분·순서 무관, 차이 이름 좌우로", () => {
    expect(nameSetDiff(t1, t2)).toEqual({ same: true, onlyA: [], onlyB: [] });
    const rev = { ...t2, parameters: [...t2.parameters].reverse() };
    expect(nameSetDiff(t1, rev).same).toBe(true);
    const diff = nameSetDiff(t1, { ...t2, parameters: [{ ...t2.parameters[0], name: "thk" }, t2.parameters[1], { ...t2.parameters[1], name: "X" }] });
    expect(diff).toEqual({ same: false, onlyA: ["THK"], onlyB: ["thk", "X"] });
  });
  it("공통 응답·합집합 범위·메타 비교", () => {
    expect(commonResponses(t1, t2)).toEqual(["Stress"]);
    expect(commonResponses(t1, { ...t2, responses: [{ name: "Disp", unit: null }] })).toEqual([]);
    expect(unionRange([1, 5, null], [0, 3, Number.NaN])).toEqual([0, 5]);
    expect(unionRange([], [null])).toBeNull();
    expect(metaDiffers({ engine_version: "a", baseline_id: null, scene: null }, { engine_version: "b", baseline_id: "x", scene: null })).toBe(true);
    expect(metaDiffers({ engine_version: "a", baseline_id: null, scene: null }, { engine_version: null, baseline_id: "x", scene: null })).toBe(false);
    expect(metaChips(NO_META).map((c) => c.value)).toEqual(["—", "—", "—"]);
  });
});
