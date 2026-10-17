// V3-S14-2(phase3.md §19.9): influence.ts 골든 — numpy·scipy 참조값(JSON 픽스처, 허용 1e-6): PRCC(동순위 평균 순위), SRC·R², 특이 행렬 "계산 불가", n < p+2 비활성.
// 픽스처 생성: frontend/scripts/gen_influence_golden.py (PRCC = 순위 변수 잔차의 상관, SRC = z-점수 OLS) — 아래 코드는 역행렬 방식이라 정의가 서로 독립이다.
import { describe, expect, it } from "vitest";
import golden from "./fixtures/influenceGolden.json";
import { avgRanks, computeInfluence, influenceFor, influenceRows, invert, NOT_LHS_TEXT, WEAK_R2 } from "../analysis/influence";
import type { ResultTable, RtRow } from "../analysis/resultTable";

type Case = { name: string; names: string[]; cols: number[][]; y: number[]; prcc: (number | null)[]; src: (number | null)[]; r2: number | null };
const cases = golden.cases as Case[];
const tol = golden.tolerance;

describe("영향도 골든 (V3-S14-2)", () => {
  for (const c of cases) {
    it(`numpy·scipy 참조값과 1e-6 이내: ${c.name}`, () => {
      const r = computeInfluence(c.names, c.cols, c.y);
      expect(r.unavailable).toBeNull();
      c.prcc.forEach((v, i) => (v === null ? expect(r.prcc[i]).toBeNull() : expect(Math.abs((r.prcc[i] as number) - v)).toBeLessThan(tol)));
      c.src.forEach((v, i) => (v === null ? expect(r.src[i]).toBeNull() : expect(Math.abs((r.src[i] as number) - v)).toBeLessThan(tol)));
      if (c.r2 === null) expect(r.r2).toBeNull();
      else expect(Math.abs((r.r2 as number) - c.r2)).toBeLessThan(tol);
    });
  }

  it("동순위는 평균 순위", () => {
    expect(avgRanks([3, 1, 3, 2, 3])).toEqual([4, 1, 4, 2, 4]);
    expect(avgRanks([5, 5, 5])).toEqual([2, 2, 2]);
    expect(avgRanks([0.2, 0.1])).toEqual([2, 1]);
  });

  it("공선(C = 2A + 1, 순위도 같음)이면 PRCC·SRC 모두 null(계산 불가), invert는 특이 행렬에 null", () => {
    const c = cases.find((x) => x.name === "collinear")!;
    const r = computeInfluence(c.names, c.cols, c.y);
    expect(r.prcc).toEqual([null, null, null]);
    expect(r.src).toEqual([null, null, null]);
    expect(r.r2).toBeNull();
    expect(invert([[1, 2], [2, 4]])).toBeNull();
    expect(invert([[2, 0], [0, 4]])).toEqual([[0.5, 0], [0, 0.25]]);
  });

  it("n < p + 2면 비활성(사유 문구), 응답이 상수여도 계산 안 함", () => {
    const r = computeInfluence(["A", "B", "C"], [[1, 2, 3, 4], [2, 1, 4, 3], [1, 3, 2, 4]], [1, 2, 3, 4]);
    expect(r.unavailable).toBe("유효 run이 부족합니다(n 4 < 변수 3 + 2)");
    expect(r.prcc).toEqual([null, null, null]);
    expect(computeInfluence(["A"], [[1, 2, 3, 4, 5]], [7, 7, 7, 7, 7]).unavailable).toBe("응답 값이 모두 같아 계산할 수 없습니다");
  });

  it("상수 변수는 그 변수만 null, 나머지는 계산", () => {
    const g = cases[0];
    const r = computeInfluence([...g.names, "K"], [...g.cols, g.y.map(() => 3)], g.y);
    expect(r.prcc[4]).toBeNull();
    expect(r.src[4]).toBeNull();
    expect(r.prcc[0]).not.toBeNull();
    // 상수 변수를 빼고 계산한 값과 같다
    const base = computeInfluence(g.names, g.cols, g.y);
    expect(r.prcc[0]).toBeCloseTo(base.prcc[0] as number, 10);
  });

  it("행 정렬 |PRCC| 내림차순(계산 불가는 뒤), 부호 불일치 표시", () => {
    const rows = influenceRows({ n: 10, names: ["a", "b", "c", "d"], prcc: [0.1, null, -0.9, 0.5], src: [0.2, null, -0.8, -0.3], r2: 0.5, unavailable: null });
    expect(rows.map((r) => r.name)).toEqual(["c", "d", "a", "b"]);
    expect(rows.filter((r) => r.mismatch).map((r) => r.name)).toEqual(["d"]);
  });

  it("influenceFor: 비 LHS 해석 DOE는 비활성(문구), 출처 a는 유효 run ≥ max(5, p+2)", () => {
    const g = cases[0];
    const rows: RtRow[] = g.y.map((y, i) => ({ run_id: `run__${i}`, no: i + 1, state: "SUCCEEDED", params: Object.fromEntries(g.names.map((n, j) => [n, g.cols[j][i]])), responses: { R: y }, curve: null }));
    const rt: ResultTable = {
      source: "solver",
      origin: { kind: "train_doe", id: "d", label: "DOE-001" },
      parameters: g.names.map((n) => ({ name: n, integer: false, min: null, max: null, unit: null })),
      responses: [{ name: "R", unit: null }],
      meta: { engine_version: null, baseline_id: null, scene: null },
      rows,
      counts: { total: rows.length, usable: rows.length, no_response: 0 },
      influence: { ok: false, lhs: false, reason: NOT_LHS_TEXT },
      notes: [],
    };
    expect(influenceFor(rt, "R").disabled).toBe(NOT_LHS_TEXT);
    const ok = influenceFor({ ...rt, influence: { ok: true, lhs: true, reason: null } }, "R");
    expect(ok.disabled).toBeNull();
    expect(ok.rows).toHaveLength(4);
    expect(ok.weak).toBe((ok.result!.r2 as number) < WEAK_R2);
    const few = influenceFor({ ...rt, source: "predict", influence: { ok: true, lhs: true, reason: null }, rows: rows.slice(0, 5) }, "R");
    expect(few.disabled).toBe("영향도에는 유효 run이 6개 이상 필요합니다(현재 5개)");
    expect(influenceFor({ ...rt, source: "predict", influence: { ok: true, lhs: false, reason: null } }, "R").refOnly).toBe(true);
    expect(influenceFor({ ...rt, influence: { ok: true, lhs: true, reason: null } }, null).disabled).toContain("응답이 없어");
  });
});
