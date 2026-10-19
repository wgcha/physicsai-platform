// V3-S12-3·4(phase3.md §17.5·§17.7): linalg.ts 골든(고정 12×4 자료, numpy 참조값 fixtures/designMapGolden.json, 허용 1e-6) —
// 표준화·PCA 고유값·%·점수(부호 규칙)·PLS X%·값%·점수·부호·구조 상관 화살표, 경계 조건 표 6행(문구 포함)·상수 변수 안내·색지도.
import { describe, expect, it } from "vitest";
import golden from "./fixtures/designMapGolden.json";
import { corr, jacobiEigen, pca, plsNipals, standardize, structureArrows, zscore } from "../analysis/viz/designMap/linalg";
import { buildMapData, noteLines, parallelAxes, project, runValue, TEXT, brushText, tipLines, pickMetric } from "../analysis/viz/designMap/designMapData";
import { VIRIDIS, colorScale, viridis } from "../analysis/viz/designMap/colormap";
import type { DesignMap, DesignMapRun } from "../api/designMap";
import { METRIC_RE } from "../api/designMap";

const TOL = 1e-6;
function close(a: number[] | number[][], b: number[] | number[][], tol = TOL) {
  const fa = (a as unknown[]).flat() as number[];
  const fb = (b as unknown[]).flat() as number[];
  expect(fa.length).toBe(fb.length);
  fa.forEach((v, i) => expect(Math.abs(v - fb[i]), `index ${i}: ${v} vs ${fb[i]}`).toBeLessThanOrEqual(tol));
}

describe("linalg 골든(numpy 참조, V3-S12-3)", () => {
  const { Z, mean, sd } = standardize(golden.X);
  const yz = zscore(golden.y).z;

  it("표준화: 평균·표준편차(ddof=1)·Z", () => {
    close(mean, golden.mean);
    close(sd, golden.sd);
    close(Z, golden.Z);
    close(yz, golden.yz);
  });

  it("Jacobi: 2×2 알려진 값, 대칭 4×4 R = V Λ Vᵀ 재구성", () => {
    const e = jacobiEigen([
      [2, 1],
      [1, 2],
    ]);
    close(e.values, [3, 1], 1e-12);
    expect(Math.abs(Math.abs(e.vectors[0][0]) - Math.SQRT1_2)).toBeLessThan(1e-12);
    const R = [
      [4, 1, 2, 0.5],
      [1, 3, 0, 1],
      [2, 0, 5, 1.5],
      [0.5, 1, 1.5, 2],
    ];
    const r = jacobiEigen(R);
    expect(r.sweeps).toBeLessThan(100);
    for (let i = 0; i < 4; i++) for (let j = 0; j < 4; j++) expect(Math.abs(r.vectors[i].reduce((s, v, c) => s + v * r.values[c] * r.vectors[j][c], 0) - R[i][j])).toBeLessThan(1e-10);
    expect([...r.values].sort((a, b) => b - a)).toEqual(r.values);
  });

  it("PCA: 고유값 내림차순·X 분산 %·고유벡터(|최대| 성분 양수)·점수", () => {
    const res = pca(Z, 2);
    close(res.eigenvalues, golden.pca.eigenvalues);
    close(res.pct, golden.pca.pct);
    close(res.vectors, golden.pca.vectors.map((r) => r.slice(0, 2)));
    close(res.scores, golden.pca.scores);
    for (let c = 0; c < 2; c++) {
      const v = res.vectors.map((r) => r[c]);
      const k = v.reduce((b, x, j) => (Math.abs(x) > Math.abs(v[b]) ? j : b), 0);
      expect(v[k]).toBeGreaterThan(0);
    }
    close(structureArrows(Z, res.scores), golden.pca.arrows);
  });

  it("PLS1 NIPALS: 점수·가중치·적재·q·X%·값%·구조 상관 화살표, corr(t, y) ≥ 0", () => {
    const res = plsNipals(Z, yz, 2);
    expect(res.ncomp).toBe(2);
    expect(res.short).toBe(false);
    close(res.scores, golden.pls.scores);
    close(res.weights, golden.pls.weights);
    close(res.xLoadings, golden.pls.xLoadings);
    close(res.q, golden.pls.q);
    close(res.xPct, golden.pls.xPct);
    close(res.yPct, golden.pls.yPct);
    close(structureArrows(Z, res.scores), golden.pls.arrows);
    for (let c = 0; c < 2; c++) expect(corr(res.scores.map((r) => r[c]), yz)).toBeGreaterThanOrEqual(0);
    // 값 부호를 뒤집으면 점수 부호가 같이 뒤집혀 "오른쪽·위 = 값 큼"이 유지된다
    const neg = plsNipals(Z, yz.map((v) => -v), 2);
    close(neg.scores, res.scores.map((r) => r.map((v) => -v)));
    for (let c = 0; c < 2; c++) expect(corr(neg.scores.map((r) => r[c]), yz.map((v) => -v))).toBeGreaterThanOrEqual(0);
    // 성분이 설명한 분산 %의 합 ≤ 100
    expect(res.yPct[0] + res.yPct[1]).toBeLessThanOrEqual(100 + 1e-9);
  });
});

// ---- 자료 규칙·경계 조건 ----------------------------------------------------------------------------

const PARAMS = [
  { name: "THK_1", integer: false, min: 2, max: 5 },
  { name: "RIB_N", integer: true, min: 3, max: 8 },
  { name: "E", integer: false, min: 1, max: 9 },
];

function run(doe: number, values: Record<string, number>, v: number | null, state = "SUCCEEDED"): DesignMapRun {
  return {
    doe_no: doe, run_key: `run__${String(doe).padStart(5, "0")}`, state, values,
    curve: v === null || state !== "SUCCEEDED" ? null : { S: { max: v, min: -v, absmax: Math.abs(v), x_at_max: 0, x_at_min: 0, n: 2 } },
    resp: null, tbl: state === "SUCCEEDED" ? { MaxStress: v } : null,
  };
}

function dm(runs: DesignMapRun[], params = PARAMS): DesignMap {
  return {
    batch_id: "b", label: "B-001", status: "DONE", parameters: params, series: ["S"],
    metrics: [{ id: "curve:max", label: "커브 최대값", unit: null, needs_series: true }, { id: "tbl:MaxStress", label: "MaxStress(결과 표)", unit: "MPa", needs_series: false }],
    runs, counts: { total: runs.length, succeeded: runs.filter((r) => r.state === "SUCCEEDED").length, no_curve: 0, no_resp: 0 },
  };
}

const vals = (t: number, n: number, e: number) => ({ THK_1: t, RIB_N: n, E: e });

describe("자료 규칙·경계 조건 표(V3-S12-4)", () => {
  it("유효 run·제외 사유·상수 변수 안내, runValue(curve·tbl)", () => {
    const d = dm([
      run(1, vals(2, 4, 1), 10), run(2, vals(3, 4, 5), 20), run(3, vals(4, 4, 2), null), run(4, vals(5, 4, 7), 30),
      run(5, vals(2.5, 4, 3), null, "FAILED"), run(6, vals(2.5, 4, 3), null, "GEN_FAILED"), run(7, vals(4.5, 4, 8), 25),
    ]);
    expect(runValue(d.runs[0], "curve:max", "S")).toBe(10);
    expect(runValue(d.runs[0], "curve:min", "S")).toBe(-10);
    expect(runValue(d.runs[0], "curve:max", "없음")).toBeNull();
    expect(runValue(d.runs[0], "tbl:MaxStress", null)).toBe(10);
    expect(runValue(d.runs[0], "resp:A_MAX", null)).toBeNull();
    const data = buildMapData(d, "curve:max", "S");
    expect(data.runs.map((r) => r.doe_no)).toEqual([1, 2, 4, 7]);
    expect(data.excluded).toEqual({ notDone: 2, noValue: 1 });
    expect(data.effVars).toEqual(["THK_1", "E"]);
    expect(data.constVars).toEqual(["RIB_N"]);
    expect(noteLines(data, "pls")).toEqual(["제외: 실패·미완료 2 · 값 없음 1", "상수 변수 제외: RIB_N"]);
    expect(noteLines(data, "pc")).toEqual(["제외: 실패·미완료 2 · 값 없음 1"]); // 평행 좌표에는 평평한 축으로 남김
    const ax = parallelAxes(data, "커브 최대값");
    expect(ax.map((a) => a.key)).toEqual(["THK_1", "RIB_N", "E", "__value__"]);
    const rib = ax[1];
    expect([rib.lo, rib.hi]).toEqual([3.5, 4.5]); // 범위 0 → ±0.5
    expect(rib.ticks).toEqual([4]); // 정수 눈금
    const thk = ax[0];
    expect(thk.lo).toBeCloseTo(2 - 0.15, 12); // 유효 run(1,2,4,7) 2~5, 위아래 5% 여백
    expect(thk.hi).toBeCloseTo(5 + 0.15, 12);
    expect(ax[3].isValue && ax[3].lo).toBeCloseTo(10 - 1, 12);
  });

  it("행 1: 유효 run < 3 → 회색 문구(PLS·PCA), 평행 좌표는 n ≥ 1이면 그림", () => {
    const data = buildMapData(dm([run(1, vals(2, 4, 1), 10), run(2, vals(3, 5, 2), 20)]), "curve:max", "S");
    expect(project(data, "pls", "v")).toEqual({ kind: "message", message: "점이 3개 이상 필요합니다(현재 2개)" });
    expect(project(data, "pca", "v")).toEqual({ kind: "message", message: TEXT.few(2) });
    expect(parallelAxes(data, "v")).toHaveLength(4);
    const one = buildMapData(dm([run(1, vals(2, 4, 1), 10)]), "curve:max", "S");
    expect(parallelAxes(one, "v")).toHaveLength(4);
    expect(parallelAxes(buildMapData(dm([]), "curve:max", "S"), "v")).toEqual([]);
  });

  it("행 2: 유효 변수 0 → '모든 변수가 상수입니다'", () => {
    const data = buildMapData(dm([1, 2, 3].map((i) => run(i, vals(2, 4, 1), i * 10))), "curve:max", "S");
    expect(project(data, "pls", "v")).toEqual({ kind: "message", message: "모든 변수가 상수입니다" });
    expect(project(data, "pca", "v")).toEqual({ kind: "message", message: "모든 변수가 상수입니다" });
    expect(noteLines(data, "pls")).toEqual([]);
  });

  it("행 3: 유효 변수 1 → 1D 산점(x = 변수 원 단위, y = 값) + 방법 버튼 비활성 + 문구", () => {
    const data = buildMapData(dm([1, 2, 3].map((i) => run(i, vals(i, 4, 1), i * 10))), "curve:max", "S");
    const p = project(data, "pls", "커브 최대값");
    expect(p.kind).toBe("scatter1d");
    if (p.kind !== "scatter1d") return;
    expect([p.xLabel, p.yLabel, p.note, p.disableMethods]).toEqual(["THK_1", "커브 최대값", "변수 1개 — 변수–값 산점도로 표시", true]);
    expect(p.points.map((q) => [q.x, q.y])).toEqual([[1, 10], [2, 20], [3, 30]]);
    expect(project(data, "pca", "v").kind).toBe("scatter1d");
  });

  it("행 4: PLS에서 값 상수 → PCA로 그림 + 문구, 행 6: 값 전부 같음 → 색 1개(중간색)", () => {
    const data = buildMapData(dm([run(1, vals(2, 4, 1), 7), run(2, vals(3, 5, 4), 7), run(3, vals(4, 3, 2), 7), run(4, vals(2.5, 6, 3), 7)]), "curve:max", "S");
    const p = project(data, "pls", "v");
    expect(p.kind === "biplot" && p.method).toBe("pca");
    expect(p.kind === "biplot" && p.note).toBe("값이 모두 같아 PLS를 계산할 수 없습니다 — PCA로 표시");
    expect(p.kind === "biplot" && p.xLabel).toMatch(/^PC1 \(X 분산 \d+\.\d%\)$/);
    const c = colorScale(data.vmin, data.vmax);
    expect(new Set(data.runs.map((r) => c(r.v)))).toEqual(new Set([viridis(0.5)]));
  });

  it("행 5: PLS 두 번째 성분 없음(‖Zcᵀyc‖ < 1e-10·첫 성분) → 1D(x = PLS1, y = 값) + 문구", () => {
    // 값 = z(THK_1) + z(E)(정확한 선형, [1,1]이 상관행렬의 고유벡터) → 첫 성분 뒤 잔차 0
    const xs = [
      [1, 2],
      [2, 1],
      [3, 4],
      [4, 3],
      [5, 6],
    ];
    const z1 = zscore(xs.map((r) => r[0])).z;
    const z2 = zscore(xs.map((r) => r[1])).z;
    const d = dm(xs.map((r, i) => run(i + 1, vals(r[0], 4, r[1]), z1[i] + z2[i])));
    const data = buildMapData(d, "curve:max", "S");
    const p = project(data, "pls", "커브 최대값");
    expect(p.kind).toBe("scatter1d");
    if (p.kind !== "scatter1d") return;
    expect(p.note).toBe("두 번째 PLS 성분 없음");
    // 첫 성분 X % = (1 + r)/2(두 변수, [1,1] 방향), 값 % = 100
    expect(Math.round(((1 + corr(z1, z2)) / 2) * 100)).toBe(91);
    expect(p.xLabel).toBe("PLS1 (X 91% · 값 100%)");
    expect(p.xTip).toBe(TEXT.plsTip);
    expect(p.disableMethods).toBe(false);
    expect(corr(p.points.map((q) => q.x), p.points.map((q) => q.y))).toBeGreaterThan(0.999999);
    // PCA는 2D 그대로
    expect(project(data, "pca", "v").kind).toBe("biplot");
  });

  it("2D 라벨 형식: PLS1 (X a% · 값 b%) · PC1 (X 분산 c%), 화살표 = 유효 변수", () => {
    const g = golden.X.map((r, i) => run(i + 1, { THK_1: r[0], RIB_N: r[2], E: r[1] }, golden.y[i]));
    const data = buildMapData(dm(g), "curve:max", "S");
    const p = project(data, "pls", "v");
    expect(p.kind === "biplot" && [p.xLabel, p.yLabel]).toEqual([expect.stringMatching(/^PLS1 \(X \d+% · 값 \d+%\)$/), expect.stringMatching(/^PLS2 \(X \d+% · 값 \d+%\)$/)]);
    expect(p.kind === "biplot" && p.arrows.map((a) => a.name)).toEqual(["THK_1", "RIB_N", "E"]);
    const q = project(data, "pca", "v");
    expect(q.kind === "biplot" && q.yLabel).toMatch(/^PC2 \(X 분산 \d+\.\d%\)$/);
    expect(q.kind === "biplot" && q.tip).toBe(TEXT.pcaTip);
  });
});

describe("색지도·툴팁·지표(§17.6)", () => {
  it("viridis 9점 보간: 끝점·중간·범위 밖 자름, colorScale 최소 → 첫 색·최대 → 끝 색", () => {
    expect(viridis(0)).toBe(VIRIDIS[0]);
    expect(viridis(1)).toBe(VIRIDIS[8]);
    expect(viridis(0.5)).toBe(VIRIDIS[4]);
    expect(viridis(-3)).toBe(VIRIDIS[0]);
    expect(viridis(NaN)).toBe(VIRIDIS[0]);
    expect(viridis(1 / 16)).toMatch(/^#[0-9a-f]{6}$/);
    const c = colorScale(10, 30);
    expect([c(10), c(30), c(20)]).toEqual([VIRIDIS[0], VIRIDIS[8], VIRIDIS[4]]);
  });

  it("툴팁 3줄·브러싱 머리·지표 기본값·METRIC_RE", () => {
    const r = { doe_no: 7, run_key: "run__00007", values: { THK_1: 2.31, RIB_N: 6, E: 4 }, v: 152.3 };
    expect(tipLines(r, PARAMS, { id: "curve:max", label: "커브 최대값", unit: null, needs_series: true })).toEqual(["DOE #7 · run__00007", "THK_1 2.31 · RIB_N 6 · E 4", "커브 최대값 152.3"]);
    expect(tipLines(r, PARAMS, { id: "resp:A_MAX", label: "A 최대(RESP)", unit: "MPa", needs_series: false })[2]).toBe("A 최대(RESP) 152.3 MPa");
    expect(brushText(120, 150, 7)).toBe("값 120 ~ 150 · 7개 run");
    const ms = [{ id: "resp:A_MAX", label: "a", unit: null, needs_series: false }, { id: "curve:max", label: "b", unit: null, needs_series: true }];
    expect(pickMetric(ms, undefined)?.id).toBe("curve:max");
    expect(pickMetric(ms, "resp:A_MAX")?.id).toBe("resp:A_MAX");
    expect(pickMetric(ms, "tbl:gone")?.id).toBe("curve:max");
    expect(pickMetric([], "x")).toBeUndefined();
    for (const ok of ["curve:max", "curve:absmax", "resp:Corner_MIN", "tbl:MaxStress"]) expect(METRIC_RE.test(ok)).toBe(true);
    for (const bad of ["curve:mean", "resp:응력_MAX", "tbl:", "resp:A"]) expect(METRIC_RE.test(bad)).toBe(false);
  });
});
