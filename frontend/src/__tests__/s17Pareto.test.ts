// V3-S17-10: pareto.ts 가중 추천이 서버 골든(backend/tests/data/s17_recommend.json)과 같은 값을 낸다(허용 오차 5e-5).
import { describe, expect, it } from "vitest";
import golden from "./fixtures/s17Recommend.json";
import { dominates, nonDominated, normalizeWeights, recommend, type Sense } from "../stages/stage5/surrogate/pareto";

interface Golden {
  front: { key: string; f: number[] }[];
  cases: { id: string; senses: Sense[]; weights: number[]; scores: number[]; recommended: string }[];
}

const TOL = 5e-5;

function check(g: Golden) {
  for (const c of g.cases) {
    const r = recommend(g.front, c.senses, c.weights);
    expect(r.scores).toHaveLength(c.scores.length);
    r.scores.forEach((s, i) => expect(Math.abs(s - c.scores[i]), `${c.id} S_${g.front[i].key}`).toBeLessThan(TOL));
    expect(r.key, c.id).toBe(c.recommended);
  }
}

describe("V3-S17-10 pareto.ts 가중 추천 골든", () => {
  it("fixtures 사본이 5건 모두 서버 골든과 일치", () => check(golden as Golden));

  it("백엔드 골든 파일이 있으면 그것과도 같은 값(사본 드리프트 방지)", () => {
    const live = import.meta.glob("../../../backend/tests/data/s17_recommend.json", { eager: true, import: "default" });
    const g = Object.values(live)[0] as Golden | undefined;
    if (!g) return;
    expect(g.cases.map((c) => c.id)).toEqual((golden as Golden).cases.map((c) => c.id));
    check(g);
  });

  it("가중치 정규화: 합 0이면 균등, 음수·비유한은 0", () => {
    expect(normalizeWeights([0, 0])).toEqual([0.5, 0.5]);
    expect(normalizeWeights([80, 20])).toEqual([0.8, 0.2]);
    expect(normalizeWeights([-5, Number.NaN, 10])).toEqual([0, 0, 1]);
  });

  it("동점이면 목적1 goodness가 큰 점, 그다음 (반복, DOE) 순서", () => {
    const front = [
      { key: "P", f: [1, 9], iter_no: 2, doe_no: 5 },
      { key: "Q", f: [3, 4], iter_no: 1, doe_no: 7 },
      { key: "R", f: [10, 1], iter_no: 1, doe_no: 2 },
    ];
    // 균등 가중 — A·D류 대칭이면 점수가 같다: P와 R의 점수가 같고 목적1 goodness는 P가 크다
    const r = recommend([front[0], front[2]], ["min", "min"], [50, 50]);
    expect(r.scores[0]).toBeCloseTo(r.scores[1], 9);
    expect(r.key).toBe("P");
    const same = recommend([{ key: "X", f: [1, 1], iter_no: 3, doe_no: 1 }, { key: "Y", f: [1, 1], iter_no: 1, doe_no: 9 }], ["min", "min"], [50, 50]);
    expect(same.key).toBe("Y");
    expect(recommend([], ["min", "min"], [50, 50]).index).toBe(-1);
  });

  it("지배·비지배 판정(방향별)", () => {
    expect(dominates([1, 1], [2, 2], ["min", "min"])).toBe(true);
    expect(dominates([1, 1], [0, 5], ["min", "max"])).toBe(false);
    expect(dominates([1, 3], [2, 2], ["min", "max"])).toBe(true);
    expect(nonDominated([[1, 9], [3, 4], [4, 5], [10, 1]], ["min", "min"])).toEqual([0, 1, 3]);
  });
});
