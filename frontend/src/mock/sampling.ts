// S15 목(phase3.md §20): 표본 방식 7개 조합 계산(backend/physicsai_core/sampling 흉내 — 같은 run 수·같은 meta 모양, 값은 목용 간이 알고리즘)과
// 미리보기·상세·목록 `sampling`·영향도 등급(§20.7 문구). Sobol은 스크램블 Halton(서버는 scipy)이고 "이어서 추가 = 앞 2n개의 뒤 n개"는 같다.
import type { BatchNote, BatchProblem, BatchSampling, BatchSamplingBrief, BatchSource, ParamSet } from "../api/types";
import { SAMPLING_LABEL, expectedRuns, isSamplingKind, recommendedCount, sobolCounts } from "../lib/sampling";
import { rng } from "./base";

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

const round6 = (v: number) => Number(v.toPrecision(6));
const batchLabel = (no: number) => `B-${String(no).padStart(3, "0")}`;
const LETTERS = "ABCDEFGHJKL";

// ------------------------------------------------------------------ 품질·LHS 계열
function quality(U: number[][]): { min_dist: number; max_abs_corr: number } {
  const n = U.length;
  const k = U[0]?.length ?? 0;
  let md = Infinity;
  for (let i = 0; i < n; i++)
    for (let l = i + 1; l < n; l++) {
      let d = 0;
      for (let j = 0; j < k; j++) d += (U[i][j] - U[l][j]) ** 2;
      md = Math.min(md, Math.sqrt(d));
    }
  let mc = 0;
  for (let a = 0; a < k; a++)
    for (let b = a + 1; b < k; b++) {
      const ma = U.reduce((s, r) => s + r[a], 0) / n;
      const mb = U.reduce((s, r) => s + r[b], 0) / n;
      let sab = 0, saa = 0, sbb = 0;
      for (const r of U) (sab += (r[a] - ma) * (r[b] - mb)), (saa += (r[a] - ma) ** 2), (sbb += (r[b] - mb) ** 2);
      mc = Math.max(mc, saa > 0 && sbb > 0 ? Math.abs(sab / Math.sqrt(saa * sbb)) : 0);
    }
  return { min_dist: Number((isFinite(md) ? md / Math.sqrt(Math.max(1, k)) : 0).toFixed(4)), max_abs_corr: Number(mc.toFixed(4)) };
}

function lhsUnit(n: number, k: number, r: () => number): number[][] {
  const U = Array.from({ length: n }, () => new Array<number>(k).fill(0));
  for (let j = 0; j < k; j++) {
    const perm = Array.from({ length: n }, (_, i) => i);
    for (let i = n - 1; i > 0; i--) {
      const t = Math.floor(r() * (i + 1));
      [perm[i], perm[t]] = [perm[t], perm[i]];
    }
    for (let i = 0; i < n; i++) U[i][j] = (perm[i] + r()) / n;
  }
  return U;
}
function score(U: number[][], criterion: "maximin" | "corr"): number {
  if (criterion === "corr") {
    const q = quality(U);
    return q.max_abs_corr;
  }
  let s = 0;
  for (let i = 0; i < U.length; i++)
    for (let l = i + 1; l < U.length; l++) {
      let d = 0;
      for (let j = 0; j < U[0].length; j++) d += (U[i][j] - U[l][j]) ** 2;
      s += Math.sqrt(d) ** -15;
    }
  return s;
}

// ------------------------------------------------------------------ Sobol 대용(스크램블 Halton)
const PRIMES = [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31];
function radical(i: number, b: number): number {
  let f = 1, r = 0;
  for (let n = i; n > 0; n = Math.floor(n / b)) (f /= b), (r += f * (n % b));
  return r;
}
function sobolUnit(n: number, k: number, seed: number, offset: number): number[][] {
  const shift = Array.from({ length: k }, (_, j) => rng(seed * 101 + j * 7 + 3)());
  return Array.from({ length: n }, (_, i) => Array.from({ length: k }, (_, j) => (radical(offset + i + 1, PRIMES[j % PRIMES.length]) + shift[j]) % 1));
}

// ------------------------------------------------------------------ 요인 설계 (코드값 -1/0/+1)
const GEN_IV: Record<number, string> = {
  4: "D=ABC", 5: "E=ABCD", 6: "E=ABC F=BCD", 7: "E=ABC F=BCD G=ACD", 8: "E=BCD F=ACD G=ABC H=ABD",
  9: "F=BCDE G=ACDE H=ABDE J=ABCE", 10: "F=ABCD G=ABCE H=ABDE J=ACDE K=BCDE", 11: "F=ABC G=BCD H=CDE J=ACD K=ADE L=BDE",
};
const GEN_V: Record<number, string> = {
  5: "E=ABCD", 6: "F=ABCDE", 7: "G=ABCDEF", 8: "G=ABCD H=ABEF", 9: "H=ACDFG J=BCEFG", 10: "H=ABCG J=BCDE K=ACDF", 11: "H=ABCG J=BCDE K=ACDF L=ABCDEFG",
};
function yates(r: number): number[][] {
  return Array.from({ length: 2 ** r }, (_, i) => Array.from({ length: r }, (_, b) => ((i >> b) & 1 ? 1 : -1)));
}
function fractional(k: number, res: 4 | 5): { code: number[][]; generators: string[]; full: boolean } {
  const g = (res === 4 ? GEN_IV : GEN_V)[k];
  if (!g) return { code: yates(k), generators: [], full: true };
  const gens = g.split(" ");
  const r = k - gens.length;
  const base = yates(r);
  const code = base.map((row) => [...row, ...gens.map((gg) => [...gg.split("=")[1]].reduce((p, ch) => p * row[LETTERS.indexOf(ch)], 1))]);
  return { code, generators: gens, full: false };
}
const isPrime = (n: number) => n > 1 && Array.from({ length: Math.floor(Math.sqrt(n)) - 1 }, (_, i) => i + 2).every((d) => n % d !== 0);
/** N−1이 q ≡ 3 (mod 4)인 소수(q ≥ 7)이면 Paley 순환 */
const isPaley = (N: number) => N - 1 >= 7 && isPrime(N - 1) && (N - 1) % 4 === 3;
function pbCode(k: number, N: number): number[][] {
  const q = N - 1;
  if (isPaley(N)) {
    const resid = new Set<number>();
    for (let x = 1; x < q; x++) resid.add((x * x) % q);
    const g = Array.from({ length: q }, (_, j) => (j === 0 ? 1 : resid.has(j) ? 1 : -1));
    const rows = Array.from({ length: q }, (_, i) => Array.from({ length: q }, (_, j) => g[(((j - i) % q) + q) % q]));
    rows.push(new Array(q).fill(-1));
    return rows.map((r) => r.slice(0, k));
  }
  let H = [[1]];
  while (H.length < N) H = [...H.map((r) => [...r, ...r]), ...H.map((r) => [...r, ...r.map((v) => -v)])];
  return H.map((r) => r.slice(1, 1 + k));
}
function bbdCode(k: number): number[][] {
  const out: number[][] = [];
  for (let i = 0; i < k; i++)
    for (let j = i + 1; j < k; j++)
      for (const [a, b] of [[-1, -1], [1, -1], [-1, 1], [1, 1]]) {
        const row = new Array<number>(k).fill(0);
        row[i] = a;
        row[j] = b;
        out.push(row);
      }
  out.push(new Array<number>(k).fill(0));
  return out;
}
function ccdCode(k: number, alpha: "face" | "inscribed"): { code: number[][]; F: number; a: number } {
  const F = k <= 4 ? yates(k) : fractional(k, 5).code;
  const a = alpha === "face" ? 1 : F.length ** 0.25;
  const code = F.map((r) => r.map((v) => (alpha === "face" ? v : v / a)));
  for (let j = 0; j < k; j++)
    for (const s of [-1, 1]) {
      const row = new Array<number>(k).fill(0);
      row[j] = s;
      code.push(row);
    }
  code.push(new Array<number>(k).fill(0));
  return { code, F: F.length, a };
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
  if (["TYPE_LATINHYPERCUBE", "TYPE_SOBOL", "TYPE_FULLFACT"].includes(type)) return { cls: "formal", note: null };
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

export { recommendedCount };
