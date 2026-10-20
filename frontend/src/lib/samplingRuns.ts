// S15 표본 방식(phase3.md §20, D3-63): 권장 run 계산식(프런트 `recommendedCount` = 서버 `sampling.recommended_count`)·설계별 run 수 `expectedRuns`(§20.5.9 표). 순수 함수·상수만(React 없음). 옛 import 경로 `lib/sampling`은 이 파일들을 재노출한다(R-F 분할, 동작 불변).
import { DEFAULT_MAX_RUNS } from "./samplingKinds";
import type { DescId, SamplingKind } from "./samplingKinds";

// ---------------------------------------------------------------- run 수 (§20.4 권장식·§20.5.9 표)

/** 부분 요인 기본 요인 수 r(run = 2^r), 인덱스 = 변수 수 k. 해상도 IV·V (§20.5.5 생성자 표) */
const FRAC_R: Record<4 | 5, Record<number, number>> = {
  4: { 2: 2, 3: 3, 4: 3, 5: 4, 6: 4, 7: 4, 8: 4, 9: 5, 10: 5, 11: 5 },
  5: { 2: 2, 3: 3, 4: 4, 5: 4, 6: 5, 7: 6, 8: 6, 9: 7, 10: 7, 11: 7 },
};
export const FRAC_MIN_K = 2;
export const FRAC_MAX_K = 11;

export function fracRuns(k: number, resolution: 4 | 5): number | null {
  const r = FRAC_R[resolution][k];
  return r === undefined ? null : 2 ** r;
}

const isPrime = (n: number) => {
  if (n < 2) return false;
  for (let d = 2; d * d <= n; d++) if (n % d === 0) return false;
  return true;
};
/** Plackett–Burman 크기 집합(≤ max): {q+1 : q 소수, q ≡ 3 (mod 4), q+1 ≥ 8} ∪ {2^m : m ≥ 3} */
export function pbSizes(max: number): number[] {
  const set = new Set<number>();
  for (let q = 3; q + 1 <= max; q++) if (isPrime(q) && q % 4 === 3 && q + 1 >= 8) set.add(q + 1);
  for (let n = 8; n <= max; n *= 2) set.add(n);
  return [...set].sort((a, b) => a - b);
}
/** k+1 이상인 가장 작은 PB 크기. k < 2이거나 R을 넘으면 null */
export function pbRuns(k: number, maxRuns = DEFAULT_MAX_RUNS): number | null {
  if (k < 2) return null;
  return pbSizes(maxRuns).find((n) => n >= k + 1) ?? null;
}

const bbdRuns = (k: number, maxRuns: number) => (k < 3 ? null : 2 * k * (k - 1) + 1 <= maxRuns ? 2 * k * (k - 1) + 1 : null);
function ccdRuns(k: number, maxRuns: number): number | null {
  if (k < FRAC_MIN_K || k > FRAC_MAX_K) return null;
  const f = k <= 4 ? 2 ** k : fracRuns(k, 5);
  const n = f === null ? null : f + 2 * k + 1;
  return n !== null && n <= maxRuns ? n : null;
}

/** Sobol 허용 run 수: 4·8·…·2^m ≤ R */
export function sobolCounts(maxRuns = DEFAULT_MAX_RUNS): number[] {
  const out: number[] = [];
  for (let n = 4; n <= maxRuns; n *= 2) out.push(n);
  return out;
}

/** 권장 run 수(§20.4): 서버 `sampling.recommended_count`와 같은 값. 설계로 정해지는 방식은 null */
export function recommendedCount(kind: SamplingKind, k: number, maxRuns = DEFAULT_MAX_RUNS): number | null {
  if (k < 1) return null;
  if (kind === "lhs" || kind === "lhs_opt") return Math.min(maxRuns, Math.max(10, 10 * k));
  if (kind === "sobol") {
    const opts = sobolCounts(maxRuns);
    if (!opts.length) return null;
    return opts.find((n) => n >= 10 * k) ?? opts[opts.length - 1];
  }
  return null;
}

export interface RunOptions {
  resolution?: 4 | 5;
  /** 전체 요인 수준(활성 변수 순서, 길이 k) */
  levels?: number[];
  maxRuns?: number;
}
/** 설계가 정하는 run 수(§20.5.9). 지원 범위 밖·상한 초과는 null. 자유 run 수 방식(lhs·lhs_opt·sobol)·표·① DOE도 null */
export function expectedRuns(kind: SamplingKind, k: number, o: RunOptions = {}): number | null {
  const R = o.maxRuns ?? DEFAULT_MAX_RUNS;
  if (k < 1) return null;
  const within = (n: number | null) => (n !== null && n <= R ? n : null);
  switch (kind) {
    case "fullfact": {
      const lv = o.levels ?? Array.from({ length: k }, () => 2);
      return within(lv.reduce((a, b) => a * b, 1));
    }
    case "fracfact":
      return within(fracRuns(k, o.resolution ?? 5));
    case "pb":
      return pbRuns(k, R);
    case "bbd":
      return bbdRuns(k, R);
    case "ccd":
      return ccdRuns(k, R);
    default:
      return null;
  }
}

/** 전체 요인 기본 수준: 3^k ≤ R이면 3, 아니면 2 (§20.10) */
export const defaultLevel = (k: number, maxRuns = DEFAULT_MAX_RUNS) => (3 ** k <= maxRuns ? 3 : 2);

/** 설명 상자 4번째 줄에 덧붙이는 계산값("현재 변수 4개 → 권장 40"). 값이 없으면 null */
export function calcNote(kind: SamplingKind, k: number, o: RunOptions = {}): string | null {
  if (k < 1) return null;
  const R = o.maxRuns ?? DEFAULT_MAX_RUNS;
  if (kind === "lhs" || kind === "lhs_opt" || kind === "sobol") {
    const n = recommendedCount(kind, k, R);
    return n === null ? null : `현재 변수 ${k}개 → 권장 ${n}`;
  }
  const n = expectedRuns(kind, k, o);
  if (n === null) return null;
  if (kind === "fullfact" && o.levels) return `현재 수준 ${o.levels.join("×")} → ${n} run`;
  if (kind === "fracfact") return `현재 변수 ${k}개 · 해상도 ${o.resolution === 4 ? "IV" : "V"} → ${n} run`;
  return `현재 변수 ${k}개 → ${n} run`;
}

/** ① 설명 상자의 계산값: hs_lhs·hs_sobol만 "권장 10 × 변수 수"(그 밖 null) */
export function hsCalcNote(descId: DescId, k: number): string | null {
  return k >= 1 && (descId === "hs_lhs" || descId === "hs_sobol") ? `현재 변수 ${k}개 → 권장 ${10 * k}` : null;
}
