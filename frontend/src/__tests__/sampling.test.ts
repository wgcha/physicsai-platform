// V3-S15-11(phase3.md §20.12): lib/sampling.ts — 모든 desc_id 설명문 4줄·빈 줄 없음·§20.4와 글자 단위 일치(fixtures/samplingText.json은 계약 문서에서 뽑은 것),
// expectedRuns·recommendedCount = §20.5.9 표(fixtures/samplingRuns.json), 배치 머리 요약.
import { describe, expect, it } from "vitest";
import text from "./fixtures/samplingText.json";
import runs from "./fixtures/samplingRuns.json";
import {
  DESCRIPTIONS, HS_COMPAT_NOTE, HS_NOTE, PLATFORM_GROUPS, PLATFORM_KINDS, RECOMMENDED_KIND, SAMPLING_GROUPS, SAMPLING_LABEL, calcNote, defaultLevel, descIdOf, expectedRuns, hsCalcNote, methodShortLabel,
  pbSizes, recommendedCount, samplingSummary, sobolCounts,
} from "../lib/sampling";
import type { BatchSampling, ParamSet } from "../api/types";
import { activeNames, buildSource, fullfactRuns, initialSampling, resetForTemplate, sobolDefaultCont } from "../stages/stage4/batch/samplingSource";

const fx = text.descriptions as Record<string, { name: string; lines: string[] }>;

describe("표본 방식 설명문 (V3-S15-11)", () => {
  it("계약 §20.4·§23.10 설명 id 전부(④ 10 + ① 4 + 일반 1 + ① 플랫폼 td_ 8) — 이름·4줄이 글자 단위로 같고 빈 줄이 없다", () => {
    expect(Object.keys(DESCRIPTIONS).sort()).toEqual(Object.keys(fx).sort());
    expect(Object.keys(fx)).toHaveLength(23);
    for (const [id, d] of Object.entries(DESCRIPTIONS)) {
      expect(d.name, id).toBe(fx[id].name);
      expect(d.lines, id).toEqual(fx[id].lines);
      expect(d.lines, id).toHaveLength(4);
      expect(d.lines.every((l) => l.trim().length > 0), id).toBe(true);
    }
    expect(HS_NOTE).toBe(text.hsNote);
    expect(HS_COMPAT_NOTE).toBe(text.hsCompatNote);
  });

  it("묶음·순서·추천: 4묶음 10방식, 기본 추천 = 최적화 LHS, 기존 라벨 LHS(무작위 층화)", () => {
    expect(SAMPLING_GROUPS.map((g) => [g.label, g.kinds])).toEqual([
      ["공간 채움(AI 학습·대리모델)", ["lhs_opt", "sobol", "lhs"]],
      ["요인 설계(경향·선별)", ["fullfact", "fracfact", "pb"]],
      ["2차 응답면", ["bbd", "ccd"]],
      ["직접 지정", ["table", "train_doe"]],
    ]);
    expect(RECOMMENDED_KIND).toBe("lhs_opt");
    expect(SAMPLING_LABEL.lhs).toBe("LHS(무작위 층화)");
    expect(SAMPLING_LABEL.fracfact).toBe("부분 요인(2수준)");
    expect(SAMPLING_LABEL.train_doe).toBe("① 학습 DOE 그대로 재사용");
  });

  it("① desc_id: 모르는 값·null은 일반 문구", () => {
    expect(descIdOf("hs_sobol")).toBe("hs_sobol");
    expect(descIdOf(null)).toBe("generic");
    expect(descIdOf("hs_unknown")).toBe("generic");
    expect(descIdOf(undefined)).toBe("generic");
  });
});

describe("run 수 (V3-S15-11, §20.5.9 표)", () => {
  it("k = 2~11: fracfact IV·V, pb, bbd, ccd 설계 run 수와 sobol·lhs 권장 run 수가 표와 같다", () => {
    for (const [k, fIV, fV, pb, bbd, ccd, sobol, lhs] of runs.rows as (number | null)[][]) {
      const kk = k as number;
      expect(expectedRuns("fracfact", kk, { resolution: 4 }), `fracIV k=${kk}`).toBe(fIV);
      expect(expectedRuns("fracfact", kk, { resolution: 5 }), `fracV k=${kk}`).toBe(fV);
      expect(expectedRuns("pb", kk), `pb k=${kk}`).toBe(pb);
      expect(expectedRuns("bbd", kk), `bbd k=${kk}`).toBe(bbd);
      expect(expectedRuns("ccd", kk), `ccd k=${kk}`).toBe(ccd);
      expect(recommendedCount("sobol", kk), `sobol k=${kk}`).toBe(sobol);
      expect(recommendedCount("lhs", kk), `lhs k=${kk}`).toBe(lhs);
      expect(recommendedCount("lhs_opt", kk), `lhs_opt k=${kk}`).toBe(lhs);
    }
  });

  it("권장식 경계: lhs 최소 10·상한 R, sobol 10k 이상의 2^m(R 초과면 R 이하 최대), 그 밖 kind는 null", () => {
    expect(recommendedCount("lhs_opt", 1)).toBe(10);
    expect(recommendedCount("lhs", 25)).toBe(200);
    expect(recommendedCount("sobol", 1)).toBe(16);
    expect(recommendedCount("sobol", 13)).toBe(128); // 130 → 256 > R → 128
    expect(recommendedCount("sobol", 3, 64)).toBe(32);
    expect(recommendedCount("lhs", 0)).toBeNull();
    for (const kind of ["fullfact", "fracfact", "pb", "bbd", "ccd", "table", "train_doe"] as const) expect(recommendedCount(kind, 4)).toBeNull();
    expect(sobolCounts()).toEqual([4, 8, 16, 32, 64, 128]);
  });

  it("전체 요인: 수준의 곱(상한 초과 null), 기본 수준 3^k ≤ R이면 3", () => {
    for (const f of runs.fullfact) expect(expectedRuns("fullfact", f.levels.length, { levels: f.levels }), f.levels.join("x")).toBe(f.runs);
    expect(defaultLevel(4)).toBe(3);
    expect(defaultLevel(5)).toBe(2); // 243 > 200
  });

  it("Plackett–Burman 크기 집합 = 계약 목록, 설계 지원 범위 밖은 null", () => {
    expect(pbSizes(200)).toEqual(runs.pbSizes);
    expect(expectedRuns("pb", 1)).toBeNull();
    expect(expectedRuns("pb", 47)).toBe(48);
    expect(expectedRuns("bbd", 2)).toBeNull();
    expect(expectedRuns("ccd", 12)).toBeNull();
    expect(expectedRuns("fracfact", 12)).toBeNull();
    expect(expectedRuns("lhs", 4)).toBeNull();
    expect(expectedRuns("bbd", 4, { maxRuns: 20 })).toBeNull(); // 25 > R
  });

  it("설명 상자 계산값: 'k개 → 권장 N' 식, ① hs_lhs·hs_sobol만 10×k", () => {
    expect(calcNote("lhs_opt", 4)).toBe("현재 변수 4개 → 권장 40");
    expect(calcNote("sobol", 4)).toBe("현재 변수 4개 → 권장 64");
    expect(calcNote("bbd", 4)).toBe("현재 변수 4개 → 25 run");
    expect(calcNote("fracfact", 6, { resolution: 4 })).toBe("현재 변수 6개 · 해상도 IV → 16 run");
    expect(calcNote("fullfact", 3, { levels: [3, 3, 2] })).toBe("현재 수준 3×3×2 → 18 run");
    expect(calcNote("table", 4)).toBeNull();
    expect(calcNote("lhs_opt", 0)).toBeNull();
    expect(hsCalcNote("hs_lhs", 5)).toBe("현재 변수 5개 → 권장 50");
    expect(hsCalcNote("hs_fullfact", 5)).toBeNull();
  });
});

describe("배치 머리 요약 (V3-S15-12)", () => {
  const s = (kind: string, meta: Record<string, unknown>): BatchSampling => ({ kind, method: kind.toUpperCase(), desc_id: kind, label: SAMPLING_LABEL[kind as never] ?? kind, influence_class: "formal", influence_note: null, recommended_count: null, meta });
  it("계약 예: Sobol 16개 · 시드 1 · B-003에 이어서 / 부분 요인 해상도 IV · 16개", () => {
    expect(samplingSummary(s("sobol", { count: 16, seed: 1, continue_from: { batch_id: "x", label: "B-003" } }), 16)).toBe("Sobol 16개 · 시드 1 · B-003에 이어서");
    expect(samplingSummary(s("sobol", { count: 16, seed: 1, continue_from: null }), 16)).toBe("Sobol 16개 · 시드 1");
    expect(samplingSummary(s("fracfact", { resolution: 4, runs: 16 }), 16)).toBe("부분 요인 해상도 IV · 16개");
    expect(samplingSummary(s("lhs_opt", { count: 20, seed: 3, criterion: "corr" }), 20)).toBe("최적화 LHS 20개 · 시드 3 · 상관 최소");
    expect(samplingSummary(s("ccd", { alpha_kind: "inscribed" }), 27)).toBe("CCD 내접 · 27개");
    expect(samplingSummary(s("fullfact", { levels: { A: 3, B: 2 } }), 6)).toBe("전체 요인 6개 · 수준 3×2");
    expect(samplingSummary(s("lhs", { count: 12, seed: 7 }), 12)).toBe("LHS 12개 · 시드 7");
    expect(samplingSummary(s("table", {}), 5)).toBe("표 붙여넣기 5개");
    expect(samplingSummary(s("train_doe", {}), 30)).toBe("① 학습 DOE 30개");
    expect(samplingSummary(null, 5)).toBeNull();
  });
  it("⑤ 출처 라벨의 방식 이름", () => {
    expect(methodShortLabel({ kind: "sobol", label: "Sobol(스크램블 QMC)" })).toBe("Sobol");
    expect(methodShortLabel({ kind: "xyz", label: "새 방식" })).toBe("새 방식");
    expect(methodShortLabel(null)).toBeNull();
  });
});

describe("화면 상태 → source (samplingSource.ts, V3-S15-12)", () => {
  const ps = { id: "ps-x", parameters: [{ name: "A", min: 1, max: 2 }, { name: "B", min: 0, max: 10 }, { name: "C", min: 5, max: 5 }] } as unknown as ParamSet;
  it("활성 변수 = 최소 < 최대인 변수(고정 변수 제외), 새 kind의 ranges는 템플릿과 다른 변수만, 기존 lhs는 전부", () => {
    const s = initialSampling(ps);
    expect(activeNames(ps, s.ranges)).toEqual(["A", "B"]);
    expect(buildSource({ ...s, kind: "pb" }, ps)).toEqual({ kind: "pb", ranges: null });
    const edited = { ...s, kind: "lhs_opt" as const, ranges: { ...s.ranges, B: ["0", "8"] as [string, string] } };
    expect(buildSource(edited, ps)).toEqual({ kind: "lhs_opt", count: 20, seed: 1, ranges: { B: [0, 8] }, criterion: "maximin" }); // k = 2 → 권장 20
    expect(buildSource({ ...edited, kind: "lhs" }, ps)).toEqual({ kind: "lhs", count: 20, seed: 1, ranges: { A: [1, 2], B: [0, 8], C: [5, 5] } });
  });
  it("숫자가 아닌 입력은 null(조합 만들기 비활성), 직접 입력한 조합 수는 권장값보다 우선", () => {
    const s = initialSampling(ps);
    expect(buildSource({ ...s, seed: "x" }, ps)).toBeNull();
    expect(buildSource({ ...s, count: "" }, ps)).toBeNull();
    expect(buildSource({ ...s, count: "12" }, ps)).toMatchObject({ count: 12 });
    expect(buildSource({ ...s, ranges: { ...s.ranges, A: ["a", "2"] } }, ps)).toBeNull();
    expect(buildSource({ ...s, kind: "table" }, ps)).toBeNull(); // 표·① DOE는 BatchSetup이 만든다
  });
  it("Sobol: run 수 기본 = 권장 2^m, 이어서 추가는 시드·범위를 보내지 않고 기본 run 수 = 이전 합계", () => {
    const s = { ...initialSampling(ps), kind: "sobol" as const };
    expect(buildSource(s, ps)).toEqual({ kind: "sobol", count: 32, seed: 1, ranges: null, continue_from: null });
    const cand = { id: "pb-9", label: "B-009", count: 16, seed: 3, offset: 16 };
    expect(sobolDefaultCont(cand)).toBe(32);
    expect(buildSource({ ...s, cont: true, contId: "pb-9", seed: "7" }, ps, cand)).toEqual({ kind: "sobol", count: 32, seed: null, ranges: null, continue_from: "pb-9" });
    expect(buildSource({ ...s, cont: true, contId: "none" }, ps, null)).toBeNull();
    expect(sobolDefaultCont({ ...cand, count: 12, offset: 0 })).toBe(4); // 합계 12 → 12를 나누는 가장 큰 2^m = 4
  });
  it("전체 요인: 수준 기본(3^k ≤ R이면 3), 곱, 고친 수준", () => {
    const s = { ...initialSampling(ps), kind: "fullfact" as const, levels: { B: "4" } };
    expect(fullfactRuns(s, ps)).toEqual({ levels: [3, 4], product: 12 });
    expect(buildSource(s, ps)).toEqual({ kind: "fullfact", levels: { A: 3, B: 4 }, ranges: null });
  });
  it("템플릿이 같으면 입력을 지우지 않고, 바뀌면 새 템플릿 기준으로 초기화", () => {
    const s = { ...initialSampling(ps), count: "7" };
    expect(resetForTemplate(s, ps)).toBe(s);
    const ps2 = { id: "ps-y", parameters: [{ name: "Z", min: 0, max: 1 }] } as unknown as ParamSet;
    expect(resetForTemplate(s, ps2)).toMatchObject({ psId: "ps-y", count: null, ranges: { Z: ["0", "1"] } });
  });
});

describe("S18 ① 플랫폼 방식(§23.9·§23.10)", () => {
  it("드롭다운 = ④ 묶음·순서에서 table·train_doe를 뺀 8개, 첫 항목이 추천", () => {
    expect(PLATFORM_GROUPS.map((g) => [g.label, g.kinds])).toEqual([
      ["공간 채움(AI 학습·대리모델)", ["lhs_opt", "sobol", "lhs"]],
      ["요인 설계(경향·선별)", ["fullfact", "fracfact", "pb"]],
      ["2차 응답면", ["bbd", "ccd"]],
    ]);
    expect(PLATFORM_KINDS).toHaveLength(8);
    expect(PLATFORM_KINDS[0]).toBe(RECOMMENDED_KIND);
  });

  it("상한 R = 500: sobol 허용 4~256, 권장 run 수와 설계 run 수가 R에 맞는다", () => {
    expect(sobolCounts(500)).toEqual([4, 8, 16, 32, 64, 128, 256]);
    expect(recommendedCount("lhs_opt", 25, 500)).toBe(250);
    expect(recommendedCount("lhs", 60, 500)).toBe(500);
    expect(recommendedCount("sobol", 13, 500)).toBe(256);
    expect(expectedRuns("bbd", 4, { maxRuns: 500 })).toBe(25);
    expect(expectedRuns("fullfact", 4, { levels: [3, 3, 3, 3], maxRuns: 500 })).toBe(81);
    expect(expectedRuns("fullfact", 4, { levels: [10, 10, 10, 10], maxRuns: 500 })).toBeNull();
    expect(defaultLevel(5, 500)).toBe(3); // 3^5 = 243 ≤ 500
    expect(defaultLevel(6, 500)).toBe(2); // 729 > 500
  });
});
