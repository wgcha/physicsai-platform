// S18 목(phase3.md §23.4): ① TD_DOE_GEN 플랫폼 모드 — params 검증(G10 추론·금지 조합 422 INVALID_PARAMS)·표본 조합 검증(422 DOE_SAMPLING_INVALID) 흉내.
// backend `doe_platform.check`와 같은 run 수·problems 코드(S15 §20.9) — lhs_opt는 같은 count·seed의 lhs로 대신 검증한다(G5). 값 계산은 하지 않는다(워커 DG_PREP 몫).
import type { BatchNote, BatchProblem, ParamSet, TrainSetup } from "../api/types";
import { MULTI_BASELINE_REASON, SAMPLING_LABEL, SITE_KINDS, checkTable, isPlatformKind, type NameRanges, type PlatformKind, type SamplingKind } from "../lib/sampling";
import { mockDesign } from "./sampling";
import { err, type MockResp } from "./route";

export const PLATFORM_MAX_RUNS = 500;
export const MAX_MULTI_EXECUTION = 8;

/** G10: generator가 없으면 sampling이 있을 때 platform, 없으면 hyperstudy */
export const generatorOf = (p: Record<string, unknown>): "platform" | "hyperstudy" =>
  p.generator === "platform" || p.generator === "hyperstudy" ? p.generator : p.sampling !== undefined && p.sampling !== null ? "platform" : "hyperstudy";

export function invalidParams(message: string): MockResp {
  return err(422, "INVALID_PARAMS", message);
}

/** §23.4 검증 — 금지 조합(422 INVALID_PARAMS). 문제 없으면 null */
export function checkGeneratorShape(p: Record<string, unknown>): MockResp | null {
  const gen = generatorOf(p);
  const multi = p.multi_execution;
  if (multi !== undefined && multi !== null && !(Number.isInteger(multi) && (multi as number) >= 1 && (multi as number) <= MAX_MULTI_EXECUTION)) return invalidParams(`multi_execution은 1~${MAX_MULTI_EXECUTION}입니다.`);
  if (gen === "platform") {
    if (p.sampling === undefined || p.sampling === null) return invalidParams("플랫폼 생성에는 sampling이 필요합니다.");
    for (const k of ["doe_label", "num_runs", "options"]) if (p[k] !== undefined) return invalidParams(`플랫폼 생성에는 ${k}를 쓸 수 없습니다.`);
    if (p.on_run_failure !== undefined && p.on_run_failure !== "fail" && p.on_run_failure !== "continue") return invalidParams("on_run_failure는 fail 또는 continue입니다.");
  } else {
    for (const k of ["sampling", "on_run_failure"]) if (p[k] !== undefined) return invalidParams(`HyperStudy 호환 생성에는 ${k}를 쓸 수 없습니다.`);
  }
  return null;
}

export interface PlatformCheck {
  kind: PlatformKind;
  runs: number | null;
  problems: BatchProblem[];
  notes: BatchNote[];
}

/** 표본 조합 검증: run 수·problems·notes. ①-2 사용 행이 범위(min < max) */
export function checkSampling(setup: TrainSetup, sampling: Record<string, unknown>, maxRuns = PLATFORM_MAX_RUNS): PlatformCheck {
  const kind = String(sampling.kind ?? "");
  if (!isPlatformKind(kind)) return { kind: "lhs_opt", runs: null, problems: [{ code: "DESIGN_UNSUPPORTED", message: `지원하지 않는 표본 방식입니다: ${kind}` }], notes: [] };
  if (kind === "table") {
    // ①은 값이 학습 범위(①-2 사용 행) 밖이면 TABLE_OUT_OF_RANGE로 막는다(doe-methods.md §4.1, ④와 다름)
    const used = setup.parameters.filter((p) => p.use);
    const c = checkTable(String(sampling.text ?? ""), used.map((p) => p.name), Object.fromEntries(used.filter((p) => p.min != null && p.max != null).map((p) => [p.name, [p.min as number, p.max as number] as [number, number]])), maxRuns);
    return { kind, runs: c.problems.length ? null : c.rows, problems: c.problems, notes: [] };
  }
  if (kind === "lhs" || kind === "lhs_opt" || kind === "halton" || kind === "random") {
    const n = Number(sampling.count);
    const problems: BatchProblem[] = [];
    if (!Number.isInteger(n) || n < 2) problems.push({ code: "TOO_FEW_ROWS", message: "run 수는 2개 이상입니다" });
    else if (n > maxRuns) problems.push({ code: "TOO_MANY_ROWS", message: `run 수는 ${maxRuns}개까지입니다` });
    return { kind, runs: problems.length ? null : n, problems, notes: [] };
  }
  const used = setup.parameters.filter((p) => p.use);
  const ps = { id: "train-setup", parameters: used.map((p) => ({ name: p.name, min: p.min, max: p.max, nominal: p.nominal, unit: p.unit })) } as unknown as ParamSet;
  const d = mockDesign(ps, { ...sampling, ranges: null } as never, maxRuns, []);
  return { kind, runs: d.problems.length ? null : d.rows.length, problems: d.problems, notes: d.notes };
}

/** 플랫폼 DOE의 표시 이름(§23.4 train_does.doe_label) */
export const platformLabel = (kind: PlatformKind): string => SAMPLING_LABEL[kind];

/** ①-3 Native 표본 검사(doe-methods.md §5.1): 방식 목록 = SITE_KINDS(다중 baseline 세트면 층 안 생성기만), lhs 밖은 플랫폼과 같은 run 수·problems. 문제 없으면 null */
export function checkNativeSampling(sampling: { kind?: string; [k: string]: unknown }, o: { names: string[]; ranges: NameRanges; multi: boolean; maxRuns?: number }): BatchProblem[] | null {
  const kind = String(sampling.kind ?? "lhs");
  const ok = (o.multi ? SITE_KINDS.train_native_multi : SITE_KINDS.train_native) as string[];
  if (!ok.includes(kind)) return [{ code: "DESIGN_UNSUPPORTED", message: o.multi ? MULTI_BASELINE_REASON : `지원하지 않는 표본 방식입니다: ${kind}` }];
  if (kind === "lhs" || kind === "train_doe") return null;
  const max = o.maxRuns ?? PLATFORM_MAX_RUNS;
  if (kind === "table") {
    const c = checkTable(String(sampling.text ?? ""), o.names, o.ranges, max);
    return c.problems.length ? c.problems : null;
  }
  const n = Number(sampling.count);
  if (kind === "lhs_opt" || kind === "halton" || kind === "random" || kind === "sobol") {
    if (!Number.isInteger(n) || n < 2) return [{ code: "TOO_FEW_ROWS", message: "run 수는 2개 이상입니다" }];
    if (n > max) return [{ code: "TOO_MANY_ROWS", message: `run 수는 ${max}개까지입니다` }];
    return null;
  }
  // 요인·응답면: 플랫폼과 같은 코드값 계산(목)
  const ps = { id: "native-set", parameters: o.names.map((name) => ({ name, min: o.ranges[name]?.[0] ?? 0, max: o.ranges[name]?.[1] ?? 1, nominal: 0, unit: "" })) } as unknown as ParamSet;
  const d = mockDesign(ps, { ...sampling, ranges: null } as never, max, []);
  return d.problems.length ? d.problems : null;
}

/** Native 새 방식 run 수(목): 요청 sampling → 개수. 설계 방식은 같은 mockDesign 행 수 */
export function nativeRuns(sampling: { kind?: string; [k: string]: unknown }, o: { names: string[]; ranges: NameRanges }): number {
  const kind = String(sampling.kind ?? "lhs") as SamplingKind;
  if (kind === "table") return checkTable(String(sampling.text ?? ""), o.names, null, 1e9).rows;
  if (kind === "lhs" || kind === "lhs_opt" || kind === "halton" || kind === "random" || kind === "sobol") return Number(sampling.count);
  const ps = { id: "native-set", parameters: o.names.map((name) => ({ name, min: o.ranges[name]?.[0] ?? 0, max: o.ranges[name]?.[1] ?? 1, nominal: 0, unit: "" })) } as unknown as ParamSet;
  return mockDesign(ps, { ...sampling, ranges: null } as never, 1e9, []).rows.length;
}
