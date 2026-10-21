// phase3.md §22.4.2 S17 목(R-F 분할): 요청 정규화(problems)·새 기록 만들기.
import type { ParamSet } from "../api/types";
import { err } from "./route";
import type { MockServer } from "./server";
import { perfId, perfLabel, perfRows } from "../stages/stage5/surrogate/perfRules";
import { fin } from "./surrogateOptRec";
import { runNotes, runVars, snapshotOf } from "./nativeVars";
import type { Cons, Obj, Obs, SoRec } from "./surrogateOptRec";

/** 요청 정규화 + problems(§22.4.2). 목은 서버 규칙의 핵심만 흉내 */
export function normalize(srv: MockServer, sid: string, body: Record<string, unknown>) {
  const ps = (body.param_set_id ? srv.paramSets.find((p) => p.id === body.param_set_id) : srv.paramSets.find((p) => p.study_id === sid && p.is_current)) as ParamSet | undefined;
  const problems: { code: string; field: string | null; message: string; action?: string; batch_id?: string; performance?: string }[] = [];
  if (!ps) return { error: err(409, "PREREQUISITE_MISSING", "사전 조건이 충족되지 않았습니다", { missing: ["PARAM_SET"] }) };
  // native-vars.md §6.2: Native는 vars{add,exclude}로 유효 변수를 정하고 범위 밖은 경고만(BOUNDS_OUT_OF_RANGE 미발행). Altair는 vars → NATIVE_VARS_UNSUPPORTED
  const native = ps.engine === "native";
  const rv = runVars(srv, ps, body.vars as { add?: string[]; exclude?: string[] } | null | undefined, body.model_id as string | null | undefined);
  if (rv.error) problems.push({ code: rv.error === "NATIVE_VARS_UNSUPPORTED" ? "NATIVE_VARS_UNSUPPORTED" : "BOUNDS_INVALID", field: rv.error === "NATIVE_VARS_UNSUPPORTED" ? "vars" : rv.error, message: rv.error === "NATIVE_VARS_UNSUPPORTED" ? "변수 추가·제외는 Native 템플릿에서만 쓸 수 있습니다" : `vars 이름이 올바르지 않습니다(${rv.error})` });
  const params = rv.out.ps.parameters;
  const integer = ps.tpl_params.filter((t) => /[id]$/.test(t.format)).map((t) => t.name);
  const given = (body.bounds ?? {}) as Record<string, [number, number]>;
  const bounds: Record<string, [number, number]> = {};
  for (const p of params) {
    const b = given[p.name] ?? [p.min, p.max];
    if (b[0] > b[1]) problems.push({ code: "BOUNDS_INVALID", field: `bounds.${p.name}`, message: `'${p.name}' 범위는 하한 ≤ 상한이어야 합니다` });
    else if (!native && (b[0] < p.min || b[1] > p.max)) problems.push({ code: "BOUNDS_OUT_OF_RANGE", field: `bounds.${p.name}`, message: `'${p.name}' 범위는 학습 범위 ${p.min}~${p.max} 안이어야 합니다` });
    bounds[p.name] = [b[0], b[1]];
  }
  const free = params.filter((p) => bounds[p.name][0] < bounds[p.name][1]).map((p) => p.name);
  const fixed = Object.fromEntries(params.filter((p) => bounds[p.name][0] === bounds[p.name][1]).map((p) => [p.name, bounds[p.name][0]]));
  if (!free.length) problems.push({ code: "NO_FREE_VARIABLE", field: "bounds", message: "범위가 있는 자유 변수가 1개 이상 필요합니다" });
  const need = Math.max(5, free.length + 2);
  const ex = body.explore as { kind: "new"; count?: number | null; seed?: number } | { kind: "reuse"; batch_id: string };
  const count = ex.kind === "new" ? ex.count ?? Math.min(200, Math.max(10, 4 * free.length)) : 0;
  if (ex.kind === "new" && count < need) problems.push({ code: "EXPLORE_TOO_FEW", field: "explore.count", message: `탐색 run은 최소 ${need}개입니다(자유 변수 ${free.length}개)` });

  // 목적: objectives 또는 단수 objective(S17 §22.4.1)
  if (body.objective && body.objectives) problems.push({ code: "OBJECTIVES_CONFLICT", field: "objectives", message: "objective와 objectives는 함께 보낼 수 없습니다" });
  const objectives = ((body.objectives as Obj[] | undefined) ?? (body.objective ? [body.objective as Obj] : [])).map((x) => ({ metric: x.metric, series: x.series ?? null, sense: x.sense }));
  if (objectives.length > 3) problems.push({ code: "OBJECTIVES_RANGE", field: "objectives", message: "목적은 1~3개여야 합니다" });
  const constraints = ((body.constraints ?? []) as Cons[]).map((c) => ({ ...c, series: c.series ?? null }));
  const observe = ((body.observe ?? []) as Obs[]).map((c) => ({ metric: c.metric, series: c.series ?? null }));
  const seen = new Set<string>();
  for (const x of [...objectives, ...constraints, ...observe]) {
    const key = `${x.metric}|${x.series ?? ""}`;
    if (seen.has(key)) problems.push({ code: "OBJECTIVE_DUPLICATE", field: "objectives", message: `'${x.metric.replace(/^perf:/, "")}'이(가) 목적·제약·관찰에 겹칩니다` });
    seen.add(key);
  }
  // opt-native ON-C4: 응답·방향·임계값·가중치는 사용자가 정한다 — 빈 항목 = OPT_CRITERIA_REQUIRED(자동 채움 없음)
  const w = (body.weights ?? null) as number[] | null;
  const missing = criteriaMissing(objectives, constraints, w, body.objectives == null && body.objective != null);
  for (const f of missing) problems.push({ code: "OPT_CRITERIA_REQUIRED", field: f, message: `기준이 비어 있습니다: ${f}` });
  for (const c of constraints) if (c.op === "range" ? c.lo != null && c.hi != null && !(fin(c.lo) && fin(c.hi) && c.lo < c.hi) : c.value != null && !fin(c.value)) problems.push({ code: "CONSTRAINT_INVALID", field: "constraints", message: "제약 값이 올바르지 않습니다" });
  if (observe.length > 10) problems.push({ code: "OBSERVE_INVALID", field: "observe", message: "관찰은 10개까지입니다" });
  if (w && (w.length !== objectives.length || w.some((x) => !fin(x) || x < 0) || w.reduce((a, b) => a + b, 0) <= 0)) problems.push({ code: "WEIGHTS_INVALID", field: "weights", message: "가중치는 목적 수와 같은 길이, 0 이상, 합 > 0이어야 합니다" });

  // 성능 스냅샷·재사용 배치의 값 있는 run 수
  const defs = new Map(perfRows(ps.responses).map((r) => [perfId(r.name), r]));
  const used = [...new Set([...objectives, ...constraints, ...observe].map((x) => x.metric).filter((m) => m.startsWith("perf:")))];
  const performances: Record<string, { unit: string; spec: unknown }> = {};
  const info: { id: string; name: string; unit: string; source: string; stat: string; label: string; available: number | null; total: number | null; spec_changed: number | null }[] = [];
  const batch = ex.kind === "reuse" ? srv.batches.find((b) => b.id === ex.batch_id) : null;
  const okRows = batch ? batch.runs.filter((r) => r.predict_job_id && srv.jobs.find((j) => j.id === r.predict_job_id)?.state === "SUCCEEDED") : [];
  for (const m of used) {
    const d = defs.get(m);
    if (!d) {
      problems.push({ code: "PERF_UNDEFINED", field: "objectives", message: `성능 '${m.slice(5)}'이(가) 템플릿에 정의되어 있지 않습니다` });
      continue;
    }
    performances[d.name] = { unit: d.unit, spec: d.spec };
    let available: number | null = null;
    if (batch) {
      available = d.source === "CURVE" ? okRows.length : okRows.filter((r) => {
        const rt = (srv.jobs.find((j) => j.id === r.predict_job_id)?.result as { response_table?: { name: string; predicted: number | null }[] } | null)?.response_table ?? [];
        return rt.some((q) => q.name === d.name && fin(q.predicted));
      }).length;
      if (available < need) problems.push({ code: "PERF_MISSING_IN_BATCH", field: "explore.batch_id", message: `재사용 배치에 성능 '${d.name}' 값이 있는 성공 run이 ${available}개뿐입니다(최소 ${need}개) — 성능을 다시 추출하세요`, action: "extract", batch_id: batch.id, performance: d.name });
    }
    info.push({ id: m, name: d.name, unit: d.unit, source: d.source, stat: d.spec.stat, label: perfLabel(d), available, total: batch ? okRows.length : null, spec_changed: batch ? 0 : null });
  }
  const iterations = Number(body.iterations ?? 3);
  const candidates = Number(body.candidates ?? 4);
  if (iterations < 1 || iterations > 10) problems.push({ code: "ITERATIONS_RANGE", field: "iterations", message: "반복은 1~10회입니다" });
  if (candidates < 1 || candidates > 10) problems.push({ code: "CANDIDATES_RANGE", field: "candidates", message: "후보는 1~10개입니다" });
  // opt-native §6.1·§6.7·§8(목은 핵심만)
  const algorithm = String(body.algorithm ?? "ego");
  const verification = String(body.verification ?? "loop");
  const ao = (body.algo_options ?? null) as Record<string, number | null> | null;
  if (!["ego", "ga", "nsga2"].includes(algorithm)) problems.push({ code: "ALGORITHM_INVALID", field: "algorithm", message: "알고리즘은 ego · ga · nsga2 중 하나입니다" });
  else if ((algorithm === "ga" && objectives.length > 1) || (algorithm === "nsga2" && objectives.length < 2)) problems.push({ code: "ALGORITHM_MISMATCH", field: "algorithm", message: "GA는 단일 목적, NSGA-II는 다목적 전용입니다" });
  if (!["loop", "none"].includes(verification)) problems.push({ code: "VERIFICATION_INVALID", field: "verification", message: "검증 방식은 loop · none 중 하나입니다" });
  const ps0 = ao?.pop_size;
  if (ps0 != null && (ps0 < 8 || ps0 > 1000 || ps0 % (algorithm === "nsga2" ? 4 : 2))) problems.push({ code: "ALGO_OPTIONS_INVALID", field: "algo_options.pop_size", message: `집단 크기는 8~1000의 ${algorithm === "nsga2" ? "4의 배수" : "짝수"}입니다` });
  if (algorithm === "ego" && ao && Object.values(ao).some((v) => v != null)) problems.push({ code: "ALGO_OPTIONS_INVALID", field: "algo_options", message: "EGO는 고급 옵션(집단 크기·세대 등)을 쓰지 않습니다" });
  const sum = (w ?? []).reduce((a, b) => a + b, 0);
  const weights = w && sum > 0 ? w.map((x) => x / sum) : objectives.length === 1 ? [1] : [];
  const settings: SoRec["settings"] = {
    names: params.map((p) => p.name), integer, bounds, ...(native ? { vars: snapshotOf(ps, rv.out) } : {}),
    objective: (objectives[0] ?? { metric: "", series: null, sense: null }) as Obj, objectives, constraints, observe, weights, mode: objectives.length > 1 ? "multi" : "single", performances,
    surrogate: String(body.surrogate ?? "gp"), iterations: verification === "none" ? 1 : iterations, candidates, tol_rel: Number(body.tol_rel ?? 0.01), seed: Number(body.seed ?? 1),
    algorithm, verification, algo_options: algorithm === "ego" ? {} : { pop_size: null, generations: null, crossover_prob: null, mutation_prob: null, eta_c: null, eta_m: null, ...(ao ?? {}) },
    multi_execution: Number(body.multi_execution ?? 1), capture: !!body.capture,
    explore: ex.kind === "new" ? { kind: "new", count, seed: ex.seed ?? 1 } : { kind: "reuse", batch_id: ex.batch_id },
  };
  // opt-native §7(목): 다중 baseline 세트 = 위상 변형 범주 baseline(수준 = body.levels 또는 전부)
  const bids = (ps.baselines ?? []).map((b) => b.id);
  const levels = bids.length > 1 ? ((body.levels as { baseline?: string[] } | undefined)?.baseline ?? bids) : null;
  if (levels) {
    if (!levels.length || levels.some((b) => !bids.includes(b))) problems.push({ code: "LEVELS_INVALID", field: "levels.baseline", message: "매칭표에 없는 baseline이거나 빈 목록입니다" });
    settings.levels = { baseline: levels };
  }
  const varNotes = native ? runNotes(srv, rv.out, bounds, body.model_id as string | null | undefined) : [];
  return { ps, settings, problems, missing, varNotes, varRows: native ? rv.out.rows : [], excluded: rv.out.excluded, free: levels && levels.length > 1 ? [...free, "baseline"] : free, fixed, integer: integer.filter((n) => free.includes(n)), count, info, levels };
}

/** 서버 criteria.missing과 같은 규칙(목적 없음·방향·제약 임계값·다목적 가중치) */
export function criteriaMissing(objs: { sense?: string | null }[], cons: Partial<Cons>[], w: number[] | null, single: boolean): string[] {
  const out: string[] = [];
  if (!objs.length) out.push("objectives");
  objs.forEach((o, i) => { if (o.sense !== "min" && o.sense !== "max") out.push(single ? "objective.sense" : `objectives.${i}.sense`); });
  cons.forEach((c, i) => {
    if (c.op === "range") (["lo", "hi"] as const).forEach((k) => { if (c[k] == null) out.push(`constraints.${i}.${k}`); });
    else if (c.value == null) out.push(`constraints.${i}.value`);
  });
  if (objs.length >= 2 && objs.length <= 3 && w == null) out.push("weights");
  return out;
}

export function newRec(id: string, studyId: string, no: number, psId: string, settings: SoRec["settings"], by: { id: string; name: string }, createdAt: string, batchNo: number, status = "EXPLORING"): SoRec {
  return { id, study_id: studyId, opt_no: no, param_set_id: psId, settings, status, iter_no: 0, iters: [], runs: [], stop_reason: null, created_by: by.id, created_by_name: by.name, created_at: createdAt, finished_at: null, batch_no: batchNo };
}
