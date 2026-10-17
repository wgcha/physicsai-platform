// phase3.md §18 S13 목: 플랫폼 내장 최적화(미리보기·생성·목록·상세·runs.csv·취소·이어서 실행). 재사용 배치 지표는 S12 목(predictBatch design-map). 진행은 엔진 tick마다 한 단계(탐색 → 학습 → 검증 → … → 완료). 목적 값 = seed.responseFn(예측 흉내).
import type { ParamSet } from "../api/types";
import type { SoIteration, SoRun, SurrogateOpt } from "../api/surrogateOpt";
import { err, needPower, ok, type Route } from "./route";
import type { MockServer } from "./server";
import { baseJob, iso, makeSteps, rng, responseFn } from "./data";
import { captureMedia } from "./capture";

interface SoRec {
  id: string;
  study_id: string;
  opt_no: number;
  param_set_id: string;
  settings: Record<string, unknown> & {
    names: string[]; integer: string[]; bounds: Record<string, [number, number]>;
    objective: { metric: string; series: string | null; sense: "min" | "max" };
    constraints: { metric: string; series: string | null; op: "<=" | ">="; value: number }[];
    surrogate: string; iterations: number; candidates: number; tol_rel: number; seed: number; multi_execution: number; capture: boolean;
    explore: { kind: "new"; count: number; seed: number } | { kind: "reuse"; batch_id: string };
  };
  status: string;
  iter_no: number;
  iters: SoIteration[];
  runs: SoRun[];
  stop_reason: string | null;
  created_by: string;
  created_by_name: string;
  created_at: string;
  finished_at: string | null;
  batch_no: number;
  /** D3-61 마무리 캡처 */
  final?: SurrogateOpt["final"];
}

export const soLabel = (n: number) => `SO-${String(n).padStart(3, "0")}`;
const ACTIVE = ["EXPLORING", "FITTING", "VERIFYING", "FINALIZING"];

function metricValue(metric: string, v: Record<string, number>): number {
  const r = responseFn(v) as Record<string, number>;
  const m = /^resp:(.+)_(MIN|MAX)$/.exec(metric);
  if (m) return m[2] === "MAX" ? r[m[1]] ?? r.MaxStress : (r[m[1]] ?? r.MaxStress) * -0.02;
  if (metric.startsWith("curve:")) return r.MaxStress * 1.08;
  return r[metric.slice(4)] ?? r.MaxStress;
}

function sample(o: SoRec, rnd: () => number, near?: Record<string, number>, spread = 1): Record<string, number> {
  const v: Record<string, number> = {};
  for (const n of o.settings.names) {
    const [lo, hi] = o.settings.bounds[n];
    let x = near ? near[n] + (rnd() - 0.5) * (hi - lo) * 0.25 * spread : lo + rnd() * (hi - lo);
    x = Math.min(hi, Math.max(lo, x));
    v[n] = o.settings.integer.includes(n) ? Math.round(x) : Number(x.toPrecision(5));
  }
  return v;
}

function feasible(o: SoRec, cons: (number | null)[]): boolean {
  return o.settings.constraints.every((c, i) => cons[i] != null && (c.op === "<=" ? cons[i]! <= c.value : cons[i]! >= c.value));
}

function addRun(o: SoRec, iter: number, doe: number, v: Record<string, number>, predicted: number | null, fail = false) {
  const objective = fail ? null : Number(metricValue(o.settings.objective.metric, v).toPrecision(6));
  const cons = o.settings.constraints.map((c) => (fail ? null : Number(metricValue(c.metric, v).toPrecision(6))));
  o.runs.push({
    iter_no: iter, batch_id: `b-so-${o.id}-${iter}`, batch_label: `B-${String(o.batch_no + iter).padStart(3, "0")}`, doe_no: doe,
    run_key: `run__${String(doe).padStart(5, "0")}`, job_id: fail ? null : `j-so-${o.id}-${iter}-${doe}`, values: v, objective, constraints: cons,
    predicted, feasible: fail ? null : feasible(o, cons), state: fail ? "FAILED" : "SUCCEEDED",
  });
}

function bestRun(o: SoRec, upto: number): SoRun | null {
  const s = o.settings.objective.sense === "max" ? -1 : 1;
  const ok_ = o.runs.filter((r) => r.iter_no <= upto && r.objective != null);
  const feas = ok_.filter((r) => r.feasible);
  const pool = feas.length ? feas : ok_;
  return pool.length ? pool.reduce((a, b) => (s * (b.objective as number) < s * (a.objective as number) ? b : a)) : null;
}

function updateBest(o: SoRec, t: number) {
  const b = bestRun(o, t);
  const prev = t >= 1 ? bestRun(o, t - 1) : null;
  const it = o.iters.find((x) => x.iter_no === t);
  if (!it) return;
  it.best_value = b?.objective ?? null;
  it.best_feasible = b ? !!b.feasible : null;
  if (prev && b) {
    const s = o.settings.objective.sense === "max" ? -1 : 1;
    const a = s * (prev.objective as number), c = s * (b.objective as number);
    it.improvement_rel = (a - c) / Math.max(Math.abs(a), 1e-12);
  }
}

function batchRef(o: SoRec, it: number, n: number, done: boolean) {
  return {
    id: `b-so-${o.id}-${it}`, label: `B-${String(o.batch_no + it).padStart(3, "0")}`, status: done ? "DONE" : "PREDICTING",
    gen: { total: n, done: n, failed: 0, running: 0, waiting: 0 }, predict: { running: done ? 0 : 1, queued: done ? 0 : n - 1, succeeded: done ? n : 0, failed: 0, canceled: 0 },
  };
}

/** 한 단계 진행(엔진 tick) */
export function advance(o: SoRec, srv?: MockServer) {
  const rnd = rng(o.opt_no * 97 + o.iter_no + o.runs.length);
  const s = o.settings;
  if (o.status === "EXPLORING") {
    const n = s.explore.kind === "new" ? s.explore.count : 12;
    for (let i = 1; i <= n; i++) addRun(o, 0, i, sample(o, rnd), null);
    o.iters.push({ iter_no: 0, kind: s.explore.kind === "new" ? "EXPLORE" : "REUSE", batch: batchRef(o, 0, n, true), fit: null, candidates: null, best_value: null, best_feasible: null, improvement_rel: null });
    updateBest(o, 0);
    o.status = "FITTING";
    return;
  }
  if (o.status === "FITTING") {
    const r = o.iter_no + 1;
    const best = bestRun(o, o.iter_no);
    const nTrain = o.runs.filter((x) => x.objective != null).length;
    const cands = Array.from({ length: s.candidates }, (_, i) => {
      const v = sample(o, rnd, best?.values as Record<string, number> | undefined, 1 / r);
      const pred = Number((metricValue(s.objective.metric, v) * (1 + (rnd() - 0.5) * 0.04)).toPrecision(6));
      return { doe_no: i + 1, values: v, predicted: pred, ei: i === 0 ? null : Number((rnd() * 3).toFixed(3)), constraints_pred: s.constraints.map((c) => metricValue(c.metric, v)) };
    });
    const q2 = Math.min(0.98, 0.72 + 0.08 * r + rnd() * 0.04);
    o.iters.push({
      iter_no: r, kind: "VERIFY", batch: batchRef(o, r, s.candidates, false),
      fit: { kind: s.surrogate, n_train: nTrain, d_free: s.names.length, loo_rmse: Number((6 / r).toFixed(3)), loo_nrmse: Number((0.4 / r).toFixed(3)), q2: Number(q2.toFixed(3)), pred_vs_verified_mae: null },
      candidates: cands, best_value: null, best_feasible: null, improvement_rel: null,
    });
    o.iter_no = r;
    o.status = "VERIFYING";
    return;
  }
  if (o.status === "VERIFYING") {
    const it = o.iters.find((x) => x.iter_no === o.iter_no)!;
    for (const c of it.candidates ?? []) addRun(o, it.iter_no, c.doe_no, c.values, c.predicted ?? null);
    const errs = (it.candidates ?? []).map((c) => Math.abs((c.predicted ?? 0) - (o.runs.find((x) => x.iter_no === it.iter_no && x.doe_no === c.doe_no)?.objective ?? 0)));
    it.fit = { ...it.fit!, pred_vs_verified_mae: Number((errs.reduce((a, b) => a + b, 0) / Math.max(1, errs.length)).toPrecision(4)) };
    it.batch = batchRef(o, it.iter_no, s.candidates, true);
    updateBest(o, it.iter_no);
    if (it.improvement_rel != null && it.iter_no >= 1 && it.improvement_rel < s.tol_rel && it.iter_no > 1) finish(o, "CONVERGED", srv);
    else if (it.iter_no >= s.iterations) finish(o, "MAX_ITER", srv);
    else o.status = "FITTING";
  }
}

function finish(o: SoRec, reason: string, srv?: MockServer) {
  o.status = "DONE";
  o.stop_reason = reason;
  o.finished_at = new Date().toISOString();
  if (srv) makeFinal(srv, o);
}

/** D3-61 마무리 캡처 흉내: 기준안(nominal)·최적안 2 run(예측 작업 + 컨투어 media), 같은 범례 0~max */
function makeFinal(srv: MockServer, o: SoRec) {
  const ps = srv.paramSets.find((p) => p.id === o.param_set_id);
  const base = Object.fromEntries((ps?.parameters ?? []).map((p) => [p.name, p.nominal ?? p.min]));
  const b = bestRun(o, Math.max(...o.iters.map((x) => x.iter_no), 0));
  if (!b) {
    o.final = { status: "SKIPPED", reason: "최적안이 없어 캡처하지 않았습니다", baseline_values: base };
    return;
  }
  // 예측 작업·media는 화면이 처음 볼 때 만든다(ensureFinalJobs) — 시드 때 목 id 순서를 바꾸지 않으려고
  const mk = (doe: number, v: Record<string, number>) => {
    const objective = Number(metricValue(o.settings.objective.metric, v).toPrecision(6));
    return { doe_no: doe, job_id: null as string | null, values: v, objective, constraints: o.settings.constraints.map((c) => Number(metricValue(c.metric, v).toPrecision(6))), state: "SUCCEEDED" };
  };
  const baseline = mk(1, base);
  const best = mk(2, b.values as Record<string, number>);
  o.final = {
    status: "DONE", reason: null, legend: { min: 0, max: Number((Math.max(baseline.objective, best.objective) * 1.05).toPrecision(4)) }, legend_note: "같은 범례(여유 5%)", baseline_values: base, baseline_predicted: baseline.objective,
    batch: { ...batchRef(o, 9, 2, true), label: `B-${String(o.batch_no + o.iters.length).padStart(3, "0")}` }, baseline, best,
  };
}

function ensureFinalJobs(srv: MockServer, o: SoRec) {
  for (const run of [o.final?.baseline, o.final?.best]) {
    if (!run || run.job_id) continue;
    const v = run.values as Record<string, number>;
    const job = baseJob({ id: srv.nid("j"), study_id: o.study_id, project_id: "p-cushion", study_title: "쿠션 두께·리브 예측", job_type: "PREDICT", state: "SUCCEEDED",
      created_at: iso(5), finished_at: iso(1), steps: makeSteps("PREDICT", 11, null), progress_pct: 100, params: { param_set_id: o.param_set_id, values: v } });
    job.result = { values: v, applied_values: v, media: captureMedia(srv, job, v, null, "OK") };
    srv.jobs.push(job);
    run.job_id = job.id;
  }
}

function progressText(o: SoRec): string {
  const T = o.settings.iterations;
  const it = o.iters.find((x) => x.iter_no === o.iter_no);
  if (o.status === "EXPLORING") return `탐색 B-${String(o.batch_no).padStart(3, "0")} · 예측 완료 0/${o.settings.explore.kind === "new" ? o.settings.explore.count : 12}`;
  if (o.status === "FITTING") return `반복 ${o.iter_no + 1}/${T} · 대리모델 학습`;
  if (o.status === "VERIFYING") return `반복 ${o.iter_no}/${T} · 검증 ${it?.batch?.label} 예측 0/${o.settings.candidates}`;
  if (o.status === "DONE") {
    const imp = [...o.iters].reverse().find((x) => x.improvement_rel != null)?.improvement_rel;
    return o.stop_reason === "CONVERGED" && imp != null ? `완료 — 수렴(개선 ${(imp * 100).toFixed(1)}% < ${o.settings.tol_rel * 100}%)` : `완료 — ${o.stop_reason === "MAX_ITER" ? "최대 반복" : "새 후보 없음"}`;
  }
  if (o.status === "FAILED") return "실패 — 반복 작업이 실패했습니다";
  return "취소됨";
}

function detail(srv: MockServer, o: SoRec): SurrogateOpt {
  ensureFinalJobs(srv, o);
  const me = srv.me!;
  const s = srv.studies.find((x) => x.id === o.study_id)!;
  const ps = srv.paramSets.find((p) => p.id === o.param_set_id);
  const r = srv.role(s.project_id);
  const canExec = r === "power" || r === "admin";
  const b = (() => {
    const t = Math.max(...o.iters.map((x) => x.iter_no), 0);
    const x = bestRun(o, t);
    if (!x) return null;
    return {
      iter_no: x.iter_no, batch_id: x.batch_id, batch_label: x.batch_label, doe_no: x.doe_no, run_key: x.run_key, job_id: x.job_id, values: x.values,
      objective: x.objective, constraints: Object.fromEntries(o.settings.constraints.map((c, i) => [c.metric, x.constraints?.[i] ?? null])), feasible: !!x.feasible,
    };
  })();
  return {
    id: o.id, label: soLabel(o.opt_no), status: o.status, dir: srv.disp(o.study_id, `05_opt/surrogate/${soLabel(o.opt_no)}`),
    param_set: { id: o.param_set_id, label: ps?.label ?? null, input_kind: ps?.input_kind ?? "assembly" }, model: { id: "m-2", name: "cushion_gnn v2" },
    settings: o.settings, iter_no: o.iter_no, progress_text: progressText(o),
    iterations: o.iters.map((it) => ({
      ...it, candidates: it.candidates?.map((c) => {
        const run = o.runs.find((x) => x.iter_no === it.iter_no && x.doe_no === c.doe_no);
        return { ...c, verified: run?.objective ?? null, state: run ? run.state : "QUEUED" };
      }) ?? null,
    })),
    runs: o.runs, best: b, stop_reason: o.stop_reason,
    can_cancel: ACTIVE.includes(o.status) && canExec && (me.is_global_admin || o.created_by === me.user_id), can_resume: o.status === "FAILED" && canExec,
    warnings: [], current_job_id: null, created_at: o.created_at, created_by_name: o.created_by_name, finished_at: o.finished_at,
    final: o.final ?? null,
    parameters: (ps?.parameters ?? []).map((p) => ({ name: p.name, nominal: p.nominal ?? null, min: p.min, max: p.max, unit: p.unit ?? "" })),
  };
}

function normalize(srv: MockServer, sid: string, body: Record<string, unknown>) {
  const ps = (body.param_set_id ? srv.paramSets.find((p) => p.id === body.param_set_id) : srv.paramSets.find((p) => p.study_id === sid && p.is_current)) as ParamSet | undefined;
  const problems: { code: string; field: string | null; message: string }[] = [];
  if (!ps) return { error: err(409, "PREREQUISITE_MISSING", "사전 조건이 충족되지 않았습니다", { missing: ["PARAM_SET"] }) };
  const integer = ps.tpl_params.filter((t) => /[id]$/.test(t.format)).map((t) => t.name);
  const given = (body.bounds ?? {}) as Record<string, [number, number]>;
  const bounds: Record<string, [number, number]> = {};
  for (const p of ps.parameters) {
    const b = given[p.name] ?? [p.min, p.max];
    if (b[0] > b[1]) problems.push({ code: "BOUNDS_INVALID", field: `bounds.${p.name}`, message: `'${p.name}' 범위는 하한 ≤ 상한이어야 합니다` });
    else if (b[0] < p.min || b[1] > p.max) problems.push({ code: "BOUNDS_OUT_OF_RANGE", field: `bounds.${p.name}`, message: `'${p.name}' 범위는 학습 범위 ${p.min}~${p.max} 안이어야 합니다` });
    bounds[p.name] = [b[0], b[1]];
  }
  const free = ps.parameters.filter((p) => bounds[p.name][0] < bounds[p.name][1]).map((p) => p.name);
  const fixed = Object.fromEntries(ps.parameters.filter((p) => bounds[p.name][0] === bounds[p.name][1]).map((p) => [p.name, bounds[p.name][0]]));
  if (!free.length) problems.push({ code: "NO_FREE_VARIABLE", field: "bounds", message: "범위가 있는 자유 변수가 1개 이상 필요합니다" });
  const need = Math.max(5, free.length + 2);
  const ex = body.explore as { kind: "new"; count?: number | null; seed?: number } | { kind: "reuse"; batch_id: string };
  const count = ex.kind === "new" ? ex.count ?? Math.min(200, Math.max(10, 4 * free.length)) : 0;
  if (ex.kind === "new" && count < need) problems.push({ code: "EXPLORE_TOO_FEW", field: "explore.count", message: `탐색 run은 최소 ${need}개입니다(자유 변수 ${free.length}개)` });
  const obj = body.objective as { metric: string; series?: string | null; sense?: "min" | "max" };
  if (!obj?.metric) problems.push({ code: "METRIC_UNKNOWN", field: "objective.metric", message: "목적 지표를 고르세요" });
  const iterations = Number(body.iterations ?? 3);
  const candidates = Number(body.candidates ?? 4);
  if (iterations < 1 || iterations > 10) problems.push({ code: "ITERATIONS_RANGE", field: "iterations", message: "반복은 1~10회입니다" });
  if (candidates < 1 || candidates > 10) problems.push({ code: "CANDIDATES_RANGE", field: "candidates", message: "후보는 1~10개입니다" });
  const settings: SoRec["settings"] = {
    names: ps.parameters.map((p) => p.name), integer, bounds, objective: { metric: obj?.metric ?? "", series: obj?.series ?? null, sense: obj?.sense ?? "min" },
    constraints: ((body.constraints ?? []) as SoRec["settings"]["constraints"]).map((c) => ({ ...c, series: c.series ?? null })),
    surrogate: String(body.surrogate ?? "gp"), iterations, candidates, tol_rel: Number(body.tol_rel ?? 0.01), seed: Number(body.seed ?? 1),
    multi_execution: Number(body.multi_execution ?? 1), capture: !!body.capture,
    explore: ex.kind === "new" ? { kind: "new", count, seed: ex.seed ?? 1 } : { kind: "reuse", batch_id: ex.batch_id },
  };
  return { ps, settings, problems, free, fixed, integer: integer.filter((n) => free.includes(n)), count };
}

/** 시드: s-cushion에 완료된 SO-001(쿠션 단독 템플릿, 3회 × 4후보) */
export function seedSurrogate(srv: MockServer) {
  const n = normalize(srv, "s-cushion", {
    param_set_id: "ps-2", explore: { kind: "new", count: 16, seed: 1 }, objective: { metric: "resp:MaxStress_MAX", sense: "min" },
    constraints: [{ metric: "resp:MaxDisp_MAX", op: "<=", value: 14 }], iterations: 3, candidates: 4, tol_rel: 0.01, multi_execution: 4,
  });
  if ("error" in n) return;
  const o: SoRec = { id: "so-1", study_id: "s-cushion", opt_no: 1, param_set_id: "ps-2", settings: n.settings, status: "EXPLORING", iter_no: 0, iters: [], runs: [], stop_reason: null,
    created_by: "u-power", created_by_name: "김연구", created_at: iso(60 * 3), finished_at: null, batch_no: 10 };
  for (let i = 0; i < 20 && o.status !== "DONE"; i++) advance(o, srv);
  o.finished_at = iso(20);
  srv.surrogate.push(o);
}

export function tickSurrogate(srv: MockServer) {
  for (const o of srv.surrogate) if (ACTIVE.includes(o.status)) advance(o, srv);
}

export const surrogateRoutes: Route = (srv, { method, seg, body, me }) => {
  if (seg[0] === "studies" && seg[2] === "surrogate-opts") {
    const s = srv.studies.find((x) => x.id === seg[1]);
    if (!s) return err(404, "NOT_FOUND", "Study를 찾을 수 없습니다.");
    if (method === "GET" && !seg[3])
      return ok(srv.surrogate.filter((o) => o.study_id === s.id).sort((a, b) => b.opt_no - a.opt_no).map((o) => ({
        id: o.id, label: soLabel(o.opt_no), status: o.status, objective: o.settings.objective, best_value: detail(srv, o).best?.objective ?? null,
        iter_no: o.iter_no, iterations: o.settings.iterations, created_at: o.created_at, created_by_name: o.created_by_name,
      })));
    if (method === "POST" && seg[3] === "preview") {
      const n = normalize(srv, s.id, body ?? {});
      if ("error" in n) return n.error!;
      const st = n.settings;
      return ok({ free_variables: n.free, integer_variables: n.integer, fixed: n.fixed, explore_count: n.count,
        max_total_runs: n.count + st.iterations * st.candidates, estimate_min: Math.round((n.count + st.iterations * st.candidates) * 2.2),
        objective_available: true, problems: n.problems });
    }
    if (method === "POST" && !seg[3]) {
      const deny = needPower(srv, s.project_id);
      if (deny) return deny;
      const n = normalize(srv, s.id, body ?? {});
      if ("error" in n) return n.error!;
      if (n.problems.length) return err(422, "SURROGATE_OPT_INVALID", "내장 최적화 설정이 올바르지 않습니다", { problems: n.problems });
      if (srv.surrogate.some((o) => o.study_id === s.id && ACTIVE.includes(o.status))) return err(409, "SURROGATE_OPT_ACTIVE", "이 Study에 진행 중인 내장 최적화가 있습니다 — 끝나거나 취소한 뒤 시작하세요");
      const no = Math.max(0, ...srv.surrogate.filter((o) => o.study_id === s.id).map((o) => o.opt_no)) + 1;
      const o: SoRec = { id: srv.nid("so"), study_id: s.id, opt_no: no, param_set_id: n.ps.id, settings: n.settings, status: n.settings.explore.kind === "new" ? "EXPLORING" : "FITTING",
        iter_no: 0, iters: [], runs: [], stop_reason: null, created_by: me.user_id, created_by_name: me.display_name, created_at: new Date().toISOString(), finished_at: null, batch_no: 20 + no * 5 };
      if (o.status === "FITTING") {
        const keep = o.status;
        o.status = "EXPLORING";
        advance(o);
        o.iters[0].kind = "REUSE";
        o.status = keep;
      }
      srv.surrogate.push(o);
      return ok(detail(srv, o), 201);
    }
  }
  if (seg[0] === "surrogate-opts" && seg[1]) {
    const o = srv.surrogate.find((x) => x.id === seg[1]);
    if (!o) return err(404, "SURROGATE_OPT_NOT_FOUND", "내장 최적화를 찾을 수 없습니다");
    const s = srv.studies.find((x) => x.id === o.study_id)!;
    if (method === "GET" && !seg[2]) return ok(detail(srv, o));
    if (method === "GET" && seg[2] === "runs.csv") {
      const head = ["iter", "batch", "doe_no", "run_key", ...o.settings.names, "objective", ...o.settings.constraints.map((c) => c.metric), "predicted", "feasible", "state"];
      const lines = o.runs.map((r) => [r.iter_no, r.batch_label, r.doe_no, r.run_key, ...o.settings.names.map((n) => (r.values as Record<string, number>)[n]), r.objective ?? "", ...(r.constraints ?? []).map((v) => v ?? ""), r.predicted ?? "", r.feasible == null ? "" : String(r.feasible), r.state].join(","));
      return { status: 200, text: "﻿" + [head.join(","), ...lines].join("\r\n") + "\r\n", contentType: "text/csv" };
    }
    if (method === "POST" && seg[2] === "cancel") {
      const deny = needPower(srv, s.project_id);
      if (deny) return deny;
      if (!me.is_global_admin && o.created_by !== me.user_id) return err(403, "PERMISSION_DENIED", "내장 최적화 등록자 또는 관리자만 취소할 수 있습니다", { required: "owner_or_global_admin" });
      if (ACTIVE.includes(o.status)) {
        o.status = "CANCELED";
        o.stop_reason = "CANCELED";
        o.finished_at = new Date().toISOString();
      }
      return ok(detail(srv, o), 202);
    }
    if (method === "POST" && seg[2] === "resume") {
      const deny = needPower(srv, s.project_id);
      if (deny) return deny;
      if (o.status !== "FAILED") return err(409, "SURROGATE_OPT_NOT_RESUMABLE", "실패한 내장 최적화만 이어서 실행할 수 있습니다");
      o.status = "FITTING";
      o.stop_reason = null;
      return ok({ job_id: srv.nid("j"), batch_retry: null }, 201);
    }
  }
  return null;
};

export type { SoRec };
