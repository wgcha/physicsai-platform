// S15 ④ 방식 화면 상태 → BatchSource(phase3.md §20.6·§20.10). 순수 함수 — 입력이 숫자가 아니면 null(조합 만들기 비활성), 조합 문제는 서버 problems가 말한다.
// 새 7개 kind의 `ranges`는 템플릿(세트) 범위와 다르게 고친 변수만 보낸다(생략 = 세트 min·max — 고정 변수가 RANGE_INVALID가 되지 않게). 기존 `lhs`는 지금처럼 전부 보낸다(V3-S9-14 body 불변).
import type { BatchSource, ParamSet } from "../../../api";
import { DEFAULT_MAX_RUNS, RECOMMENDED_KIND, SITE_DEFAULT, SITE_KINDS, defaultLevel, expectedRuns, recommendedCount, sobolCounts, type SamplingKind } from "../../../lib/sampling";

export type Ranges = Record<string, [string, string]>;

export interface SamplingState {
  /** 이 상태가 만들어진 템플릿(바뀌면 범위·run 수를 새 템플릿 기준으로 되돌린다 — 같으면 건드리지 않는다) */
  psId: string | null;
  kind: SamplingKind;
  ranges: Ranges;
  /** null = 권장값을 따라간다(변수 수·범위가 바뀌면 같이 바뀜) */
  count: string | null;
  seed: string;
  criterion: "maximin" | "corr";
  /** Sobol 이어서 추가 */
  cont: boolean;
  contId: string;
  /** 전체 요인 수준(없으면 기본) */
  levels: Record<string, string>;
  resolution: 4 | 5;
  alpha: "face" | "inscribed";
}

/** 템플릿이 바뀌었을 때만 새 템플릿 기준으로 초기화(같은 템플릿이면 같은 객체를 돌려 사용자의 입력을 지우지 않는다) */
export function resetForTemplate(s: SamplingState, ps: ParamSet | null): SamplingState {
  if (s.psId === (ps?.id ?? null)) return s;
  return { ...s, psId: ps?.id ?? null, kind: kindForTemplate(s.kind, ps), ranges: defaultRanges(ps), count: null, cont: false, contId: "", levels: {} };
}

/** 다중 baseline 세트는 층 안 생성기만 되고 화면 기본은 lhs(DM-C4·registry.SITE_DEFAULT batch_multi): 단일 baseline 기본(최적화 LHS)이거나 허용 밖이면 lhs로 */
export function kindForTemplate(kind: SamplingKind, ps: ParamSet | null): SamplingKind {
  if (!isMultiBaseline(ps)) return kind;
  return kind === RECOMMENDED_KIND || !SITE_KINDS.batch_multi.includes(kind) ? SITE_DEFAULT.batch_multi : kind;
}
export const isMultiBaseline = (ps: ParamSet | null): boolean => (ps?.baselines?.length ?? 0) > 1;

export const defaultRanges = (ps: ParamSet | null): Ranges => Object.fromEntries((ps?.parameters ?? []).map((p) => [p.name, [String(p.min), String(p.max)]]));

export const initialSampling = (ps: ParamSet | null): SamplingState => ({
  psId: ps?.id ?? null,
  kind: kindForTemplate(RECOMMENDED_KIND, ps),
  ranges: defaultRanges(ps),
  count: null,
  seed: "1",
  criterion: "maximin",
  cont: false,
  contId: "",
  levels: {},
  resolution: 5,
  alpha: "face",
});

const parse = (s: string): number | null => (s.trim() !== "" && Number.isFinite(Number(s)) ? Number(s) : null);

/** 범위가 있는(최소 < 최대) 변수 이름, 템플릿 순서 */
export function activeNames(ps: ParamSet | null, ranges: Ranges): string[] {
  return (ps?.parameters ?? []).filter((p) => {
    const lo = parse(ranges[p.name]?.[0] ?? "");
    const hi = parse(ranges[p.name]?.[1] ?? "");
    return lo !== null && hi !== null && lo < hi;
  }).map((p) => p.name);
}

/** 이어서 추가 후보(같은 템플릿의 Sobol 배치 요약) */
export interface ContinueCand {
  id: string;
  label: string;
  count: number;
  seed: number | null;
  offset: number | null;
}
/** 이전 합계 = offset + count (§20.5.3) */
export const contTotal = (c: ContinueCand) => (c.offset ?? 0) + c.count;

export function levelOf(s: SamplingState, name: string, k: number, maxRuns = DEFAULT_MAX_RUNS): number {
  const v = parse(s.levels[name] ?? "");
  return v !== null && Number.isInteger(v) ? v : defaultLevel(k, maxRuns);
}

/** 화면에 보일 run 수(자유 run 방식) 문자열: 직접 고친 값 또는 권장값 */
export function countText(s: SamplingState, k: number, cand?: ContinueCand | null, maxRuns = DEFAULT_MAX_RUNS): string {
  if (s.count !== null) return s.count;
  if (s.kind === "sobol" && s.cont && cand) return String(sobolDefaultCont(cand, maxRuns));
  const r = recommendedCount(s.kind, k, maxRuns);
  return String(r ?? 20);
}
/** 이어서 추가 기본 run 수: 이전 합계(2배). 합계가 허용 목록에 없으면 가장 큰 약수 */
export function sobolDefaultCont(c: ContinueCand, maxRuns = DEFAULT_MAX_RUNS): number {
  const t = contTotal(c);
  const ok = sobolCounts(maxRuns).filter((n) => t % n === 0);
  return ok.includes(t) ? t : (ok[ok.length - 1] ?? 4);
}

function changedRanges(ps: ParamSet, s: SamplingState): Record<string, number[]> | null {
  const out: Record<string, number[]> = {};
  for (const p of ps.parameters) {
    const [a, b] = s.ranges[p.name] ?? [String(p.min), String(p.max)];
    const lo = parse(a);
    const hi = parse(b);
    if (lo === null || hi === null) {
      out[p.name] = [Number.NaN, Number.NaN]; // 숫자가 아님 → 서버가 RANGE_INVALID (아래에서 null 처리)
      continue;
    }
    if (lo !== p.min || hi !== p.max) out[p.name] = [lo, hi];
  }
  return Object.keys(out).length ? out : null;
}
const hasNaN = (r: Record<string, number[]> | null) => !!r && Object.values(r).some((v) => v.some((x) => Number.isNaN(x)));

/** 방식 7+1개 → body. table·train_doe는 BatchSetup이 만든다 */
export function buildSource(s: SamplingState, ps: ParamSet | null, cand?: ContinueCand | null, maxRuns = DEFAULT_MAX_RUNS): BatchSource | null {
  if (!ps) return null;
  const k = activeNames(ps, s.ranges).length;
  if (s.kind === "lhs") {
    const r: Record<string, [number, number]> = {};
    for (const [n, [lo, hi]] of Object.entries(s.ranges)) r[n] = [Number(lo), Number(hi)];
    const count = parse(countText(s, k, null, maxRuns));
    const seed = parse(s.seed);
    return count === null || seed === null ? null : { kind: "lhs", count, seed, ranges: r };
  }
  if (s.kind === "table" || s.kind === "train_doe") return null;
  if (s.kind === "sobol" && s.cont) {
    const count = parse(countText(s, k, cand, maxRuns));
    return !cand || count === null ? null : { kind: "sobol", count, seed: null, ranges: null, continue_from: cand.id };
  }
  const ranges = changedRanges(ps, s);
  if (hasNaN(ranges)) return null;
  switch (s.kind) {
    case "lhs_opt": {
      const count = parse(countText(s, k, null, maxRuns));
      const seed = parse(s.seed);
      return count === null || seed === null ? null : { kind: "lhs_opt", count, seed, ranges, criterion: s.criterion };
    }
    case "halton":
    case "random": {
      const count = parse(countText(s, k, null, maxRuns));
      const seed = parse(s.seed);
      return count === null || seed === null ? null : { kind: s.kind, count, seed, ranges }; // schema BatchSourceHalton·BatchSourceRandom
    }
    case "sobol": {
      const count = parse(countText(s, k, null, maxRuns));
      const seed = parse(s.seed);
      return count === null || seed === null ? null : { kind: "sobol", count, seed, ranges, continue_from: null };
    }
    case "fullfact": {
      const names = activeNames(ps, s.ranges);
      return { kind: "fullfact", levels: Object.fromEntries(names.map((n) => [n, levelOf(s, n, k, maxRuns)])), ranges };
    }
    case "fracfact":
      return { kind: "fracfact", resolution: s.resolution, ranges };
    case "pb":
      return { kind: "pb", ranges };
    case "bbd":
      return { kind: "bbd", ranges };
    case "ccd":
      return { kind: "ccd", alpha: s.alpha, ranges };
  }
}

/** 전체 요인 곱(활성 변수 수준) — 화면 "N run" 표시 */
export function fullfactRuns(s: SamplingState, ps: ParamSet | null, maxRuns = DEFAULT_MAX_RUNS): { levels: number[]; product: number } {
  const names = activeNames(ps, s.ranges);
  const levels = names.map((n) => levelOf(s, n, names.length, maxRuns));
  return { levels, product: levels.reduce((a, b) => a * b, 1) };
}

/** 설계로 정해지는 run 수(fullfact·fracfact·pb·bbd·ccd) */
export function designRuns(s: SamplingState, ps: ParamSet | null, maxRuns = DEFAULT_MAX_RUNS): number | null {
  const k = activeNames(ps, s.ranges).length;
  return expectedRuns(s.kind, k, { resolution: s.resolution, levels: s.kind === "fullfact" ? fullfactRuns(s, ps, maxRuns).levels : undefined, maxRuns });
}
