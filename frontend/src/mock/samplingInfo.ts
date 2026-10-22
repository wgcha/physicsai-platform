// S15 목(phase3.md §20, R-F 분할): 미리보기·상세·목록 `sampling` 응답과 영향도 등급(§20.7 문구).
import type { BatchSampling, BatchSamplingBrief } from "../api/types";
import { SAMPLING_LABEL, isSamplingKind } from "../lib/sampling";
import type { PriorBatch } from "./sampling";

// ------------------------------------------------------------------ sampling(미리보기·상세·목록)·영향도 등급(§20.7)
const REF_TEXT = {
  table: "직접 만든 표 — 표본 분포를 알 수 없어 영향도는 참고용입니다",
  pb: "Plackett–Burman — 주효과가 2인자 교호작용과 부분적으로 교락되어 영향도는 참고용입니다",
  quad: "2차 응답면 설계 — 점이 중심·모서리에 몰려 곡률 효과가 선형 영향도에 작게 보일 수 있어 참고용입니다. 변수–응답 그래프로 확인하세요",
  fracIV: "부분 요인(해상도 IV) — 2인자 교호작용끼리 교락되어 영향도는 참고용입니다(주효과는 2인자 교호작용과 교락 없음)",
  fracV: "부분 요인(해상도 V) — 3인자 이상 교호작용과 교락되어 영향도는 참고용입니다",
  fracIII: "부분 요인(해상도 III) — 주효과가 2인자 교호작용과 교락되어 영향도는 참고용입니다",
  unknown: "표본 방식을 알 수 없어 영향도는 참고용입니다",
  noDoe: "원본 ① DOE 정보를 찾을 수 없어 영향도는 참고용입니다",
};
export const REF_NOTES = REF_TEXT;

/** ① doe_type(+options) → 등급·문구 */
export function doeInfluence(type: string, options: Record<string, unknown> = {}): { cls: "formal" | "reference"; note: string | null } {
  // S18 §23.4: 플랫폼 DOE의 doe_type = 방식 이름(LHS_OPT 등) → ④ 배치와 같은 등급(fracfact 해상도는 options.resolution)
  if (isSamplingKind(type.toLowerCase())) {
    const m = mockSampling(type, { resolution: options.resolution ?? 5 });
    return { cls: m.influence_class as "formal" | "reference", note: m.influence_note ?? null };
  }
  if (["TYPE_LATINHYPERCUBE", "TYPE_SOBOL", "TYPE_FULLFACT", "NATIVE_LHS"].includes(type)) return { cls: "formal", note: null };
  if (type === "TYPE_FRACFACT") {
    const r = String(options.RESOLUTION ?? "3");
    return { cls: "reference", note: r === "4" ? REF_TEXT.fracIV : r === "5" ? REF_TEXT.fracV : REF_TEXT.fracIII };
  }
  return { cls: "reference", note: REF_TEXT.unknown };
}

/** 배치 DB source_kind(+meta) → sampling. doeType = TRAIN_DOE가 따르는 ① 유형(없으면 DOE 없음) */
export function mockSampling(sourceKind: string, meta: Record<string, unknown>, opts: { doeType?: string | null; doeOptions?: Record<string, unknown>; recommended?: number | null; label?: string } = {}): BatchSampling {
  const kind = sourceKind.toLowerCase();
  const label = isSamplingKind(kind) ? SAMPLING_LABEL[kind] : (opts.label ?? sourceKind);
  let cls: "formal" | "reference" = "formal";
  let note: string | null = null;
  if (kind === "table") ((cls = "reference"), (note = REF_TEXT.table));
  else if (kind === "pb") ((cls = "reference"), (note = REF_TEXT.pb));
  else if (kind === "bbd" || kind === "ccd") ((cls = "reference"), (note = REF_TEXT.quad));
  else if (kind === "fracfact") ((cls = "reference"), (note = (meta.resolution as number) === 4 ? REF_TEXT.fracIV : REF_TEXT.fracV));
  else if (kind === "train_doe") {
    if (!opts.doeType) ((cls = "reference"), (note = REF_TEXT.noDoe));
    else ({ cls, note } = doeInfluence(opts.doeType, opts.doeOptions));
  }
  return { kind, method: sourceKind.toUpperCase(), desc_id: kind, label, influence_class: cls, influence_note: note, recommended_count: opts.recommended ?? null, meta };
}

export function mockBrief(b: PriorBatch): BatchSamplingBrief {
  const kind = b.source_kind.toLowerCase();
  return {
    kind, method: b.source_kind, label: isSamplingKind(kind) ? SAMPLING_LABEL[kind] : b.source_kind, count: Number(b.meta.count ?? b.runs.length),
    seed: typeof b.meta.seed === "number" ? b.meta.seed : null, offset: typeof b.meta.offset === "number" ? b.meta.offset : null,
  };
}
