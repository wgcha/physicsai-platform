// S15 목(phase3.md §20, R-F 분할): 설계 코드값 간이 알고리즘 — 품질·LHS·스크램블 Halton(Sobol 대용)·부분 요인·PB·BBD·CCD.
import { rng } from "./base";

export const round6 = (v: number) => Number(v.toPrecision(6));
export const batchLabel = (no: number) => `B-${String(no).padStart(3, "0")}`;
export const LETTERS = "ABCDEFGHJKL";

// ------------------------------------------------------------------ 품질·LHS 계열
export function quality(U: number[][]): { min_dist: number; max_abs_corr: number } {
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

export function lhsUnit(n: number, k: number, r: () => number): number[][] {
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
export function score(U: number[][], criterion: "maximin" | "corr"): number {
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
export function sobolUnit(n: number, k: number, seed: number, offset: number): number[][] {
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
export function fractional(k: number, res: 4 | 5): { code: number[][]; generators: string[]; full: boolean } {
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
export const isPaley = (N: number) => N - 1 >= 7 && isPrime(N - 1) && (N - 1) % 4 === 3;
export function pbCode(k: number, N: number): number[][] {
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
export function bbdCode(k: number): number[][] {
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
export function ccdCode(k: number, alpha: "face" | "inscribed"): { code: number[][]; F: number; a: number } {
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
