// S15 목(phase3.md §20): 표본 방식 7개 조합 계산(backend/physicsai_core/sampling 흉내 — 같은 run 수·같은 meta 모양, 값은 목용 간이 알고리즘)과
// 미리보기·상세·목록 `sampling`·영향도 등급(§20.7 문구). Sobol은 스크램블 Halton(서버는 scipy)이고 "이어서 추가 = 앞 2n개의 뒤 n개"는 같다.
// R-F 분할(동작 불변): 설계 코드값(LHS·Halton·요인·PB·BBD·CCD) samplingCodes · sampling 응답·영향도 등급 samplingInfo. 옛 import 경로는 아래에서 재노출한다.
import type { BatchNote, BatchProblem, BatchSource, ParamSet } from "../api/types";
import { expectedRuns, recommendedCount, sobolCounts } from "../lib/sampling";
import { rng } from "./base";
import { LETTERS, batchLabel, bbdCode, ccdCode, fractional, isPaley, lhsUnit, pbCode, quality, round6, score, sobolUnit } from "./samplingCodes";
export { REF_NOTES, doeInfluence, mockSampling, mockBrief } from "./samplingInfo";

export const NEW_KINDS = ["lhs_opt", "sobol", "fullfact", "fracfact", "pb", "bbd", "ccd"] as const;
export type NewKind = (typeof NEW_KINDS)[number];
export const isNewKind = (k: string): k is NewKind => (NEW_KINDS as readonly string[]).includes(k);

export interface PriorBatch {
  id: string;
  study_id: string;
  batch_no: number;
  param_set_id: string;
  source_kind: string;
  meta: Record<string, unknown>;
  runs: { values: Record<string, number> }[];
}
export interface MockDesign {
  rows: { doe_no: number; values: Record<string, number> }[];
  problems: BatchProblem[];
  notes: BatchNote[];
  meta: Record<string, unknown>;
}

// ------------------------------------------------------------------ 조합 계산
export function mockDesign(ps: ParamSet, source: BatchSource, maxRuns: number, prior: PriorBatch[]): MockDesign {
  const problems: BatchProblem[] = [];
  const notes: BatchNote[] = [];
  const done = (rows: MockDesign["rows"], meta: Record<string, unknown>): MockDesign => ({ rows, problems, notes, meta });
  const none = (meta: Record<string, unknown> = {}) => done([], meta);
  const src = source as Record<string, unknown>;
  const ranges = (src.ranges ?? {}) as Record<string, number[]>;
  const bad = Object.entries(ranges).filter(([n, r]) => !ps.parameters.some((p) => p.name === n) || !Array.isArray(r) || !Number.isFinite(r[0]) || !Number.isFinite(r[1]) || !(r[0] < r[1]));
  if (bad.length) {
    problems.push(...bad.map(([n]) => ({ code: "RANGE_INVALID", message: `${n} 범위는 최소 < 최대인 유한한 값이어야 합니다` })));
    return none();
  }
  let cont: PriorBatch | null = null;
  let seedIn = src.seed == null ? 1 : Number(src.seed);
  let rangesUsed = ranges;
  if (source.kind === "sobol" && source.continue_from) {
    cont = prior.find((b) => b.id === source.continue_from) ?? null;
    const m = cont?.meta ?? {};
    if (!cont || cont.source_kind !== "SOBOL") problems.push({ code: "CONTINUE_INVALID", message: "Sobol 배치가 아닙니다" });
    else if (cont.param_set_id !== ps.id) problems.push({ code: "CONTINUE_INVALID", message: "다른 템플릿의 배치입니다" });
    else if (source.seed != null || (source.ranges && Object.keys(source.ranges).length)) problems.push({ code: "CONTINUE_INVALID", message: "이어서 추가는 이전 배치의 시드·범위를 그대로 씁니다" });
    if (problems.length) return none();
    seedIn = Number(m.seed ?? 1);
    rangesUsed = (m.ranges ?? {}) as Record<string, number[]>;
  }
  const bounds = (n: string): [number, number] => {
    const p = ps.parameters.find((x) => x.name === n)!;
    const r = rangesUsed[n];
    return r ? [r[0], r[1]] : [p.min, p.max];
  };
  const active = ps.parameters.filter((p) => bounds(p.name)[0] < bounds(p.name)[1]).map((p) => p.name);
  const fixed = ps.parameters.filter((p) => !active.includes(p.name)).map((p) => p.name);
  const k = active.length;
  const base = { ranges: Object.fromEntries(ps.parameters.map((p) => [p.name, bounds(p.name)])), active, fixed };
  if (k === 0) {
    problems.push({ code: "DESIGN_UNSUPPORTED", message: "범위가 있는 변수가 없습니다" });
    return none(base);
  }
  if (fixed.length) notes.push({ code: "FIXED_EXCLUDED", message: `고정 변수 ${fixed.join("·")}는 설계에서 빼고 고정값을 씁니다` });
  const toValues = (get: (i: number, j: number) => number, n: number) =>
    Array.from({ length: n }, (_, i) => ({
      doe_no: i + 1,
      values: Object.fromEntries(
        ps.parameters.map((p) => {
          const j = active.indexOf(p.name);
          const [lo, hi] = bounds(p.name);
          return [p.name, j < 0 ? lo : round6(get(i, j) === 0 ? (lo + hi) / 2 : (lo + hi) / 2 + get(i, j) * ((hi - lo) / 2))] as const;
        }),
      ),
    }));
  const unitValues = (U: number[][]) =>
    U.map((row, i) => ({ doe_no: i + 1, values: Object.fromEntries(ps.parameters.map((p) => { const j = active.indexOf(p.name); const [lo, hi] = bounds(p.name); return [p.name, j < 0 ? lo : round6(lo + row[j] * (hi - lo))] as const; })) }));
  const checkCount = (n: number): boolean => {
    if (!Number.isInteger(n) || n < 2) return (problems.push({ code: "TOO_FEW_ROWS", message: "조합 수는 2개 이상입니다" }), false);
    if (n > maxRuns) return (problems.push({ code: "TOO_MANY_ROWS", message: `조합 수는 ${maxRuns}개까지입니다` }), false);
    return true;
  };

  switch (source.kind) {
    case "lhs_opt": {
      const n = Number(source.count);
      if (!checkCount(n)) return none(base);
      const r = rng(seedIn * 7919 + 17);
      let best: number[][] | null = null;
      let bs = Infinity;
      for (let c = 0; c < 5; c++) {
        const U = lhsUnit(n, k, r);
        const sc = score(U, source.criterion);
        if (sc < bs) ((best = U), (bs = sc));
      }
      return done(unitValues(best!), { count: n, seed: seedIn, criterion: source.criterion, candidates: 5, iterations: 2000, ...base, quality: quality(best!) });
    }
    case "sobol": {
      const n = Number(source.count);
      if (!sobolCounts(maxRuns).includes(n)) {
        problems.push({ code: "COUNT_NOT_POW2", message: "Sobol은 run 수가 2의 거듭제곱이어야 합니다(4·8·16·32·64·128)" });
        return none(base);
      }
      let offset = 0;
      if (cont) {
        offset = Number(cont.meta.offset ?? 0) + Number(cont.meta.count ?? cont.runs.length);
        const names = (cont.meta.active ?? []) as string[];
        if (names.join() !== active.join()) problems.push({ code: "CONTINUE_INVALID", message: "변수 구성이 다릅니다" });
        else if (offset % n !== 0) problems.push({ code: "CONTINUE_INVALID", message: `이어서 추가할 run 수는 ${offset}을 나누어떨어지게 하는 2의 거듭제곱이어야 합니다(권장 ${offset})` });
        if (problems.length) return none(base);
        const total = offset + n;
        const pow2 = (total & (total - 1)) === 0;
        notes.push({ code: "SEQUENCE_CONTINUED", message: `${batchLabel(cont.batch_no)}과 합치면 ${total}개${pow2 ? "(균형 유지)" : "(합계는 균형 아님)"}` });
      }
      const U = sobolUnit(n, k, seedIn, offset);
      return done(unitValues(U), {
        count: n, m: Math.log2(n), seed: seedIn, scramble: true, offset, continue_from: cont ? { batch_id: cont.id, label: batchLabel(cont.batch_no) } : null,
        generator: "scipy 1.17.1", ...base, quality: quality(U),
      });
    }
    case "fullfact": {
      const lv = (source.levels ?? {}) as Record<string, number>;
      const levels = Object.fromEntries(active.map((n) => [n, lv[n] ?? 2]));
      for (const [n, v] of Object.entries(lv)) {
        if (!active.includes(n)) problems.push({ code: "LEVELS_INVALID", message: `'${n}'는 범위가 있는 변수가 아닙니다` });
        else if (!Number.isInteger(v) || v < 2 || v > 10) problems.push({ code: "LEVELS_INVALID", message: "수준은 2~10입니다" });
      }
      if (problems.length) return none(base);
      const total = active.reduce((a, n) => a * levels[n], 1);
      if (total > maxRuns) {
        problems.push({ code: "TOO_MANY_ROWS", message: `전체 요인 run 수 ${total}개가 상한 ${maxRuns}개를 넘습니다 — 수준 수를 줄이세요` });
        return none({ levels, ...base });
      }
      const idx = (i: number, j: number) => {
        let rest = i;
        for (let q = k - 1; q > j; q--) rest = Math.floor(rest / levels[active[q]]);
        return rest % levels[active[j]];
      };
      return done(toValues((i, j) => (levels[active[j]] === 1 ? 0 : -1 + (2 * idx(i, j)) / (levels[active[j]] - 1)), total), { levels, ...base });
    }
    case "fracfact": {
      if (k < 2 || k > 11) {
        problems.push({ code: "DESIGN_UNSUPPORTED", message: "부분 요인은 범위가 있는 변수 2~11개에서만 만들 수 있습니다" });
        return none(base);
      }
      const f = fractional(k, source.resolution);
      if (f.full) notes.push({ code: "FULL_FACTORIAL_USED", message: `변수 ${k}개에서는 부분 요인 대신 전체 2수준 요인(2^${k})을 씁니다` });
      return done(toValues((i, j) => f.code[i][j], f.code.length), { resolution: source.resolution, letters: Object.fromEntries(active.map((n, j) => [LETTERS[j], n])), generators: f.generators, runs: f.code.length, full: f.full, ...base });
    }
    case "pb": {
      const N = expectedRuns("pb", k, { maxRuns });
      if (k < 2) problems.push({ code: "DESIGN_UNSUPPORTED", message: "Plackett–Burman은 범위가 있는 변수가 2개 이상이어야 합니다" });
      else if (N === null) problems.push({ code: "TOO_MANY_ROWS", message: `Plackett–Burman run 수가 상한 ${maxRuns}개를 넘습니다` });
      if (problems.length || N === null) return none(base);
      const code = pbCode(k, N);
      return done(toValues((i, j) => code[i][j], N), { runs: N, construction: isPaley(N) ? "paley" : "sylvester", ...base });
    }
    case "bbd": {
      if (k < 3) problems.push({ code: "DESIGN_UNSUPPORTED", message: "Box–Behnken은 범위가 있는 변수가 3개 이상이어야 합니다" });
      else if (2 * k * (k - 1) + 1 > maxRuns) problems.push({ code: "TOO_MANY_ROWS", message: `Box–Behnken run 수 ${2 * k * (k - 1) + 1}개가 상한 ${maxRuns}개를 넘습니다` });
      if (problems.length) return none(base);
      if (k >= 6) notes.push({ code: "BBD_PAIRWISE", message: "변수 6개 이상은 쌍 방식 Box–Behnken입니다(표준 블록 설계보다 run이 많습니다)" });
      const code = bbdCode(k);
      return done(toValues((i, j) => code[i][j], code.length), { center: 1, pairwise: k >= 6, ...base });
    }
    case "ccd": {
      if (k < 2 || k > 11) problems.push({ code: "DESIGN_UNSUPPORTED", message: "CCD는 범위가 있는 변수 2~11개에서만 만들 수 있습니다" });
      if (problems.length) return none(base);
      const c = ccdCode(k, source.alpha);
      if (c.code.length > maxRuns) {
        problems.push({ code: "TOO_MANY_ROWS", message: `CCD run 수 ${c.code.length}개가 상한 ${maxRuns}개를 넘습니다` });
        return none(base);
      }
      return done(toValues((i, j) => c.code[i][j], c.code.length), { alpha_kind: source.alpha, alpha: Number(c.a.toFixed(4)), factorial: k <= 4 ? "full" : "fracV", generators: [], center: 1, ...base });
    }
    default:
      return none();
  }
}

export { recommendedCount };
