// S18 ①-3 DOE 생성 카드: 화면 상태 → 작업 params(phase3 §23.4). 순수 함수만(React 없음).
// 플랫폼 = {generator:"platform", sampling, multi_execution, radioss_assem_path, on_run_failure}. HyperStudy(호환) = 기존 body 그대로(generator 키를 보내지 않는다).
import type { DoeGenerator } from "../../api";
import {
  DEFAULT_PLATFORM_MAX_RUNS, DEFAULT_PLATFORM_PARALLEL, defaultLevel, expectedRuns, recommendedCount, type PlatformKind,
} from "../../lib/sampling";


/** 플랫폼 방식 화면 상태. count가 null이면 권장값을 따라간다(변수 수가 바뀌면 같이 바뀜) */
export interface PlatformState {
  kind: PlatformKind;
  count: string | null;
  seed: string;
  criterion: "maximin" | "corr";
  /** 전체 요인 수준(변수 이름 → 입력 문자열, 없으면 기본) */
  levels: Record<string, string>;
  resolution: 4 | 5;
  alpha: "face" | "inscribed";
}

export const initialPlatform = (): PlatformState => ({ kind: "lhs_opt", count: null, seed: "1", criterion: "maximin", levels: {}, resolution: 5, alpha: "face" });

/** /status.limits.configured 에서 읽는 ①-3 값(없으면 설정 기본값) */
export interface DoeLimits {
  generatorDefault: DoeGenerator;
  parallelDefault: number;
  maxRuns: number;
  maxMulti: number;
}
type StatusLike = { limits?: { configured?: Record<string, unknown> } } | null | undefined;
const posInt = (v: unknown): number | null => (typeof v === "number" && Number.isInteger(v) && v >= 1 ? v : null);

export function doeLimits(status: StatusLike): DoeLimits {
  const c = status?.limits?.configured ?? {};
  const maxMulti = posInt(c.max_multi_execution) ?? 8;
  return {
    generatorDefault: c.doe_generator_default === "hyperstudy" ? "hyperstudy" : "platform",
    parallelDefault: Math.min(posInt(c.doe_platform_parallel_default) ?? DEFAULT_PLATFORM_PARALLEL, maxMulti),
    maxRuns: posInt(c.doe_platform_max_runs) ?? DEFAULT_PLATFORM_MAX_RUNS,
    maxMulti,
  };
}

const parseNum = (s: string): number | null => (s.trim() !== "" && Number.isFinite(Number(s)) ? Number(s) : null);
const parseInt0 = (s: string): number | null => {
  const v = parseNum(s);
  return v !== null && Number.isInteger(v) ? v : null;
};

/** 자유 run 수 방식의 최소 run 수(lhs·lhs_opt 2, sobol 4) */
export const minCount = (kind: PlatformKind): number => (kind === "sobol" ? 4 : 2);
export const isFreeCount = (kind: PlatformKind): boolean => kind === "lhs" || kind === "lhs_opt" || kind === "sobol";

/** 입력란에 보일 run 수 문자열: 직접 고친 값 또는 권장값 */
export function countText(s: PlatformState, k: number, maxRuns: number): string {
  if (s.count !== null) return s.count;
  return String(recommendedCount(s.kind, k, maxRuns) ?? 20);
}

/** 전체 요인 수준(변수 순서) — 입력이 정수가 아니면 기본 수준 */
export function levelOf(s: PlatformState, name: string, k: number, maxRuns: number): number {
  const v = parseInt0(s.levels[name] ?? "");
  return v !== null ? v : defaultLevel(k, maxRuns);
}
export const fullfactLevels = (s: PlatformState, names: string[], maxRuns: number): number[] => names.map((n) => levelOf(s, n, names.length, maxRuns));

export interface RunsInfo {
  /** 실제 run 수. 입력이 올바르지 않거나 변수 수가 방식의 지원 범위 밖이면 null */
  n: number | null;
  /** 상한(R) 초과(자유 run 수·전체 요인만 값을 보이고 알린다) */
  over: boolean;
}
/** "실제 run N개"(§23.9). 설계가 정하는 방식은 lib/sampling.ts `expectedRuns`(R = 플랫폼 상한), 자유 run 수 방식은 입력값 */
export function platformRuns(s: PlatformState, names: string[], maxRuns: number): RunsInfo {
  const k = names.length;
  if (k < 1) return { n: null, over: false };
  if (isFreeCount(s.kind)) {
    const n = parseInt0(countText(s, k, maxRuns));
    return n === null || n < minCount(s.kind) ? { n: null, over: false } : { n, over: n > maxRuns };
  }
  if (s.kind === "fullfact") {
    const n = fullfactLevels(s, names, maxRuns).reduce((a, b) => a * b, 1);
    return { n, over: n > maxRuns };
  }
  return { n: expectedRuns(s.kind, k, { resolution: s.resolution, maxRuns }), over: false };
}

/** 요청 `sampling`(§23.4). 시드·run 수가 숫자가 아니면 null(실행 버튼 비활성) */
export function buildSampling(s: PlatformState, names: string[], maxRuns: number): Record<string, unknown> | null {
  const k = names.length;
  switch (s.kind) {
    case "lhs":
    case "lhs_opt":
    case "sobol": {
      const count = parseInt0(countText(s, k, maxRuns));
      const seed = parseInt0(s.seed);
      if (count === null || count < minCount(s.kind) || seed === null || seed < 0) return null;
      return s.kind === "lhs_opt" ? { kind: s.kind, count, seed, criterion: s.criterion } : { kind: s.kind, count, seed };
    }
    case "fullfact":
      return { kind: "fullfact", levels: Object.fromEntries(names.map((n) => [n, levelOf(s, n, k, maxRuns)])) };
    case "fracfact":
      return { kind: "fracfact", resolution: s.resolution };
    case "ccd":
      return { kind: "ccd", alpha: s.alpha };
    case "pb":
    case "bbd":
      return { kind: s.kind };
  }
}

/** 플랫폼 모드 작업 params. 입력이 올바르지 않으면 null */
export function buildPlatformParams(s: PlatformState, names: string[], o: { multi: number; assemPath: string; maxRuns: number; continueOnFailure: boolean }): Record<string, unknown> | null {
  const sampling = buildSampling(s, names, o.maxRuns);
  if (!sampling) return null;
  return {
    generator: "platform",
    sampling,
    multi_execution: o.multi,
    radioss_assem_path: o.assemPath,
    on_run_failure: o.continueOnFailure ? "continue" : "fail",
  };
}

/** 원본 HyperStudy(호환) 모드 params — S15 이전 body와 같아야 한다(generator 키 없음, V3-S18-10) */
export function buildHyperstudyParams(o: { label: string; options: Record<string, string | number | boolean>; multi: number; assemPath: string; runsEditable: boolean; runs: string }): Record<string, unknown> {
  const params: Record<string, unknown> = { doe_label: o.label, options: o.options, multi_execution: o.multi, radioss_assem_path: o.assemPath };
  if (o.runsEditable) params.num_runs = Number(o.runs);
  return params;
}

/** 결과 줄(§23.9): `<doe_label> · <플랫폼|HyperStudy> · run N개 · 상태` — platform이고 gen이 있으면 `· 생성 완료 d · 실패 f / 전체 t`를 덧붙인다 */
export function genText(gen: { total: number; done: number; failed: number } | null | undefined): string | null {
  return gen ? `생성 완료 ${gen.done} · 실패 ${gen.failed} / 전체 ${gen.total}` : null;
}

// ---------------------------------------------------------------- native(geometry-engine.md §7.3.3·§7.3.8, S18 플랫폼 생성의 한 경로)

/** native 입력 상태 — 표본 방식은 LHS 고정(doe_type NATIVE_LHS, 표시 "LHS(Native)") */
export interface NativeDoeState {
  count: string;
  seed: string;
  /** 실패한 run(형상 생성 스킵)이 있어도 계속(서버 기본 continue) */
  continueOnFailure: boolean;
}
export const NATIVE_DOE_LABEL = "LHS(Native)";
export const initialNative = (): NativeDoeState => ({ count: "20", seed: "1", continueOnFailure: true });

/** native params: generator platform + sampling {kind:"lhs", count, seed}. 세트 기준이면 param_set_id(조립 폴더 생략), 아니면 radioss_assem_path */
export function buildNativeParams(s: NativeDoeState, o: { multi: number; maxRuns: number; assemPath: string; paramSetId: string | null }): Record<string, unknown> | null {
  const count = parseInt0(s.count);
  const seed = parseInt0(s.seed);
  if (count === null || count < 2 || count > o.maxRuns || seed === null || seed < 0) return null;
  const base = { generator: "platform", sampling: { kind: "lhs", count, seed }, multi_execution: o.multi, on_run_failure: s.continueOnFailure ? "continue" : "fail" };
  return o.paramSetId ? { ...base, param_set_id: o.paramSetId } : { ...base, radioss_assem_path: o.assemPath };
}

/** 층화 LHS baseline별 run 수(백엔드 baselines.stratum_counts: ⌊N/B⌋ + 앞쪽부터 나머지 1씩, 차 ≤ 1) */
export function stratumCounts(n: number, b: number): number[] {
  if (!(b >= 1) || !(n >= 0)) return [];
  const q = Math.floor(n / b);
  const r = n % b;
  return Array.from({ length: b }, (_, k) => q + (k < r ? 1 : 0));
}

/** TD_DOE_GEN 결과 skipped_runs[] 한 행(native = SKIPPED.json 해석: reason = 코드, category = §6.5) */
export interface SkippedRun {
  run_key: string;
  reason?: string;
  category?: string;
  message?: string;
}
export function skippedRuns(result: unknown, doeId: string | null | undefined): SkippedRun[] {
  const r = result as { doe_id?: string; skipped_runs?: unknown } | null | undefined;
  if (!r || !doeId || r.doe_id !== doeId || !Array.isArray(r.skipped_runs)) return [];
  return r.skipped_runs.filter((x): x is SkippedRun => !!x && typeof (x as SkippedRun).run_key === "string");
}

// ---------------------------------------------------------------- 다른 DOE 표본표 재사용(equiv-check.md EQ-C1 4: sampling.kind = train_doe)

/** 샘플 표 columns → 파라미터 이름(run_key·resp: 응답 열 제외) */
export const reuseParamNames = (columns: readonly string[]): string[] => columns.filter((c) => c !== "run_key" && !c.startsWith("resp:"));

/** 두 이름 집합이 같은가(백엔드 doe_reuse.name_mismatch와 같은 규칙: 순서 무관) */
export function sameNameSet(a: readonly string[], b: readonly string[]): boolean {
  const sa = new Set(a);
  const sb = new Set(b);
  return sa.size === sb.size && [...sa].every((x) => sb.has(x));
}

/** 후보 DOE 한 줄의 선택 가능 여부와 사유. cols = 샘플 표 파라미터 이름(undefined = 아직 못 읽음, null = 샘플 표 없음) */
export function reuseState(d: { status: string; sample_status: string }, cols: string[] | null | undefined, names: readonly string[]): { ok: boolean; reason: string | null } {
  if (d.status !== "READY" || !(d.sample_status === "PARSED" || d.sample_status === "PARTIAL")) return { ok: false, reason: "표본표가 준비되지 않았습니다" };
  if (cols === undefined) return { ok: false, reason: "표본표를 확인하는 중입니다" };
  if (cols === null) return { ok: false, reason: "표본표를 읽을 수 없습니다" };
  if (!sameNameSet(cols, names)) return { ok: false, reason: "파라미터 이름이 다릅니다" };
  return { ok: true, reason: null };
}

/** 재사용 params: sampling {kind:"train_doe", doe_id}. run 수·시드는 보내지 않는다(원본 표본표 그대로, run 이름 유지).
 * 세트 기준이면 param_set_id(조립 폴더 생략), 아니면 radioss_assem_path */
export function buildReuseParams(o: { doeId: string; multi: number; assemPath: string; paramSetId: string | null; continueOnFailure: boolean }): Record<string, unknown> | null {
  if (!o.doeId) return null;
  const base = { generator: "platform", sampling: { kind: "train_doe", doe_id: o.doeId }, multi_execution: o.multi, on_run_failure: o.continueOnFailure ? "continue" : "fail" };
  return o.paramSetId ? { ...base, param_set_id: o.paramSetId } : { ...base, radioss_assem_path: o.assemPath };
}
