// phase3.md §18 S13·§22 S17 목: 플랫폼 내장 최적화(미리보기·생성·목록·상세·runs.csv·취소·이어서 실행·추가 검증 verify). 재사용 배치 지표는 S12 목(predictBatch design-map).
// 진행은 엔진 tick마다 한 단계(탐색 → 학습 → 검증 → … → 완료). 목적 값 = seed.responseFn(예측 흉내). S17: 목적 1~3·제약 ≤/≥/범위·관찰·가중치, 파레토·HV·예측 전선(상세 계산은 서버 몫 — 목은 흉내).
import type { ParamSet } from "../api/types";
import type { SoIteration, SoRun, SurrogateOpt } from "../api/surrogateOpt";
import { err, needPower, ok, type Route } from "./route";
import type { MockServer } from "./server";
import { baseJob, iso, makeSteps, rng, responseFn } from "./data";
import { captureMedia } from "./capture";
import { nonDominated, recommend, type Sense } from "../stages/stage5/surrogate/pareto";
import { perfId, perfLabel, perfRows } from "../stages/stage5/surrogate/perfRules";
import { metricLabel } from "../stages/stage5/surrogate/soRules";

interface Obj { metric: string; series: string | null; sense: "min" | "max" }
interface Cons { metric: string; series: string | null; op: "<=" | ">=" | "range"; value?: number | null; lo?: number | null; hi?: number | null }
interface Obs { metric: string; series: string | null }
interface ExtraRec { iter_no: number; points: Record<string, number>[]; capture: boolean; ticks: number }

interface SoRec {
  id: string;
  study_id: string;
  opt_no: number;
  param_set_id: string;
  settings: Record<string, unknown> & {
    names: string[]; integer: string[]; bounds: Record<string, [number, number]>;
    objective: Obj;
    objectives: Obj[];
    constraints: Cons[];
    observe: Obs[];
    weights: number[];
    mode: "single" | "multi";
    performances: Record<string, { unit: string; spec: unknown }>;
    surrogate: string; iterations: number; candidates: number; tol_rel: number; seed: number; multi_execution: number; capture: boolean;
    explore: { kind: "new"; count: number; seed: number } | { kind: "reuse"; batch_id: string };
    algorithm?: string; verification?: string; algo_options?: Record<string, number | null>;
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
  /** S17 HV 정규화 틀(반복 0 자료로 고정) */
  frame?: { ideal: number[]; nadir: number[] };
  /** S17 추가 검증(EXTRA) 진행 */
  extra?: ExtraRec | null;
}

export const soLabel = (n: number) => `SO-${String(n).padStart(3, "0")}`;
const ACTIVE = ["EXPLORING", "FITTING", "VERIFYING", "FINALIZING"];
const fin = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

/** 지표 값(목 함수). perf:NAME = 템플릿 응답 이름(없으면 가속도 흉내 — 두께가 클수록 커져 응력과 상충) */
function metricValue(metric: string, v: Record<string, number>): number {
  const r = responseFn(v) as Record<string, number>;
  const m = /^resp:(.+)_(MIN|MAX)$/.exec(metric);
  if (m) return m[2] === "MAX" ? r[m[1]] ?? r.MaxStress : (r[m[1]] ?? r.MaxStress) * -0.02;
  if (metric.startsWith("curve:")) return r.MaxStress * 1.08;
  if (metric.startsWith("perf:")) {
    const name = metric.slice(5);
    if (r[name] != null) return r[name];
    return 28 * (v.THK_TOP ?? 0.6) + 0.9 * (v.E_FOAM ?? 8) + 55 / ((v.THK_FOAM ?? 2) + 0.5);
  }
  return r[metric.slice(4)] ?? r.MaxStress;
}
const val = (metric: string, v: Record<string, number>) => Number(metricValue(metric, v).toPrecision(6));

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

function consOk(c: Cons, v: number | null): boolean {
  if (v == null) return false;
  if (c.op === "range") return v >= (c.lo ?? -Infinity) && v <= (c.hi ?? Infinity);
  return c.op === "<=" ? v <= (c.value ?? Infinity) : v >= (c.value ?? -Infinity);
}
const feasible = (o: SoRec, cons: (number | null)[]) => o.settings.constraints.every((c, i) => consOk(c, cons[i]));

function addRun(o: SoRec, iter: number, doe: number, v: Record<string, number>, predicted: number | null, kind: string, fail = false) {
  const s = o.settings;
  const objectives = s.objectives.map((x) => (fail ? null : val(x.metric, v)));
  const cons = s.constraints.map((c) => (fail ? null : val(c.metric, v)));
  const observed = Object.fromEntries(s.observe.map((x) => [x.metric, fail ? null : val(x.metric, v)]));
  o.runs.push({
    iter_no: iter, batch_id: `b-so-${o.id}-${iter}`, batch_label: `B-${String(o.batch_no + iter).padStart(3, "0")}`, doe_no: doe,
    run_key: `run__${String(doe).padStart(5, "0")}`, job_id: fail ? null : `j-so-${o.id}-${iter}-${doe}`, values: v, objective: objectives[0] ?? null, objectives, observed,
    constraints: cons, predicted, feasible: fail ? null : feasible(o, cons), state: fail ? "FAILED" : "SUCCEEDED", kind, on_front: false, reason: null,
  });
}

const senseOf = (o: SoRec): Sense[] => o.settings.objectives.map((x) => x.sense);
const okRuns = (o: SoRec, upto = Infinity) => o.runs.filter((r) => r.iter_no <= upto && (r.objectives ?? []).length && (r.objectives ?? []).every(fin));

/** 다목적: 만족 유효 run의 비지배 집합 */
function frontRuns(o: SoRec, upto = Infinity): SoRun[] {
  const pool = okRuns(o, upto).filter((r) => r.feasible);
  const idx = nonDominated(pool.map((r) => r.objectives as number[]), senseOf(o));
  return idx.map((i) => pool[i]);
}

function bestRun(o: SoRec, upto: number): SoRun | null {
  if (o.settings.mode === "multi") {
    const f = frontRuns(o, upto);
    if (!f.length) return null;
    const rec = recommend(f.map((r) => ({ key: `${r.iter_no}:${r.doe_no}`, f: r.objectives as number[], iter_no: r.iter_no, doe_no: r.doe_no })), senseOf(o), o.settings.weights);
    return rec.index >= 0 ? f[rec.index] : null;
  }
  const s = o.settings.objective.sense === "max" ? -1 : 1;
  const ok_ = o.runs.filter((r) => r.iter_no <= upto && r.objective != null);
  const feas = ok_.filter((r) => r.feasible);
  const pool = feas.length ? feas : ok_;
  return pool.length ? pool.reduce((a, b) => (s * (b.objective as number) < s * (a.objective as number) ? b : a)) : null;
}

/** HV(정규화 틀: 반복 0 자료의 ideal·nadir, 기준점 1.1). 2D 정확, 3D는 고정 격자 근사(목 전용) */
function hvOf(o: SoRec, runs: SoRun[]): number {
  const fr = o.frame;
  if (!fr) return 0;
  const m = fr.ideal.length;
  const pts = runs.map((r) => (r.objectives as number[]).map((x, i) => {
    const q = senseOf(o)[i] === "max" ? -x : x;
    const lo = senseOf(o)[i] === "max" ? -fr.nadir[i] : fr.ideal[i];
    const hi = senseOf(o)[i] === "max" ? -fr.ideal[i] : fr.nadir[i];
    return (q - lo) / Math.max(1e-12, hi - lo);
  })).filter((p) => p.every((x) => x <= 1.1));
  const R = 1.1;
  if (m === 2) {
    const s = [...pts].sort((a, b) => a[0] - b[0]);
    let area = 0;
    let bestY = R;
    let prevX = 0;
    for (const p of s) {
      if (p[1] < bestY) {
        if (prevX) area += (p[0] - prevX) * (R - bestY);
        bestY = p[1];
        prevX = p[0];
      }
    }
    area += prevX ? (R - prevX) * (R - bestY) : 0;
    return Number(area.toFixed(4));
  }
  const N = 14;
  let hit = 0;
  for (let a = 0; a < N; a++) for (let b = 0; b < N; b++) for (let c = 0; c < N; c++) {
    const q = [((a + 0.5) / N) * R, ((b + 0.5) / N) * R, ((c + 0.5) / N) * R];
    if (pts.some((p) => p[0] <= q[0] && p[1] <= q[1] && p[2] <= q[2])) hit++;
  }
  return Number(((hit / N ** 3) * R ** 3).toFixed(4));
}

function updateBest(o: SoRec, t: number) {
  const it = o.iters.find((x) => x.iter_no === t);
  if (!it) return;
  const b = bestRun(o, t);
  it.best_value = b?.objective ?? null;
  it.best_feasible = b ? !!b.feasible : null;
  if (o.settings.mode === "multi") {
    if (t === 0) {
      const pool = okRuns(o, 0);
      o.frame = {
        ideal: o.settings.objectives.map((x, i) => (x.sense === "max" ? Math.max : Math.min)(...pool.map((r) => r.objectives![i] as number))),
        nadir: o.settings.objectives.map((x, i) => (x.sense === "max" ? Math.min : Math.max)(...pool.map((r) => r.objectives![i] as number))),
      };
    }
    const f = frontRuns(o, t);
    it.hv = hvOf(o, f);
    it.front_size = f.length;
    const prev = o.iters.find((x) => x.iter_no === t - 1);
    it.improvement_rel = t >= 1 && prev?.hv ? (it.hv - prev.hv) / prev.hv : null;
    return;
  }
  const prev = t >= 1 ? bestRun(o, t - 1) : null;
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
  const multi = s.mode === "multi";
  if (o.status === "EXPLORING") {
    const n = s.explore.kind === "new" ? s.explore.count : 12;
    for (let i = 1; i <= n; i++) addRun(o, 0, i, sample(o, rnd), null, s.explore.kind === "new" ? "EXPLORE" : "REUSE");
    o.iters.push({ iter_no: 0, kind: s.explore.kind === "new" ? "EXPLORE" : "REUSE", batch: batchRef(o, 0, n, true), fit: null, candidates: null, best_value: null, best_feasible: null, improvement_rel: null });
    updateBest(o, 0);
    o.status = "FITTING";
    return;
  }
  if (o.status === "FITTING") {
    const r = o.iter_no + 1;
    const nTrain = o.runs.filter((x) => x.objective != null).length;
    const fr = multi ? frontRuns(o, o.iter_no) : [];
    const best = multi ? (fr.length ? fr[Math.floor(rnd() * fr.length)] : null) : bestRun(o, o.iter_no);
    const alg = s.algorithm ?? "ego";
    const cands = Array.from({ length: s.candidates }, (_, i) => {
      const near = multi && fr.length ? fr[Math.floor(rnd() * fr.length)] : best;
      const v = sample(o, rnd, near?.values as Record<string, number> | undefined, 1 / r);
      const objs = s.objectives.map((x) => Number((metricValue(x.metric, v) * (1 + (rnd() - 0.5) * 0.04)).toPrecision(6)));
      const w = s.objectives.map(() => rnd() + 0.2);
      const wsum = w.reduce((a, b) => a + b, 0);
      return {
        doe_no: i + 1, values: v, predicted: objs[0], ei: i === 0 ? null : Number((rnd() * 3).toFixed(3)), constraints_pred: s.constraints.map((c) => metricValue(c.metric, v)),
        ...(multi ? { predicted_objectives: objs, predicted_std: objs.map((x) => Number((Math.abs(x) * 0.03).toPrecision(3))), role: i === 0 ? "HVI" : "ParEGO", weight: i === 0 ? null : w.map((x) => Number((x / wsum).toFixed(3))) } : {}),
        ...(alg === "ga" ? { role: i === 0 ? "ga" : "ga_ei", predicted_objectives: [objs[0]], predicted_std: [Number((Math.abs(objs[0]) * 0.03).toPrecision(3))] } : {}),
        ...(alg === "nsga2" ? { role: "nsga2", weight: null } : {}),
      };
    });
    const ao = s.algo_options ?? {};
    const gens = Number(ao.generations ?? (alg === "ga" ? 150 : 200));
    const algo = alg === "ego" ? { name: "ego" } : {
      name: alg, pop_size: Number(ao.pop_size ?? (alg === "ga" ? 40 : 100)), generations: gens, generations_run: alg === "nsga2" ? Math.min(gens, 142) : gens,
      evals: 0, stop: alg === "nsga2" && gens > 142 ? "STALL" : "MAX_GEN", seed: s.seed * 100000 + r * 1000 + 900, best_pred: multi ? null : cands[0]?.predicted ?? null, hv_pred: multi ? 0.71 : null,
    };
    const q2 = Math.min(0.98, 0.72 + 0.08 * r + rnd() * 0.04);
    const kind = s.surrogate;
    if (s.verification === "none") {
      // opt-native ON-4: 검증 배치 없이 마무리 — 후보는 반복 0 행에 UNVERIFIED
      const it0 = o.iters[0];
      it0.candidates = cands.map((c) => ({ ...c, state: "UNVERIFIED", verified: null }));
      it0.fit = { kind, n_train: nTrain, d_free: s.names.length, loo_rmse: 6, loo_nrmse: 0.4, q2: multi ? null : Number(q2.toFixed(3)), pred_vs_verified_mae: null, algo } as never;
      o.status = "DONE";
      o.stop_reason = "SURROGATE_ONLY";
      o.finished_at = new Date().toISOString();
      o.final = { status: "SKIPPED", reason: "대리모델만(검증 없음) 모드는 마무리 캡처를 하지 않습니다" };
      return;
    }
    o.iters.push({
      iter_no: r, kind: "VERIFY", batch: batchRef(o, r, s.candidates, false),
      fit: {
        kind, n_train: nTrain, d_free: s.names.length, loo_rmse: Number((6 / r).toFixed(3)), loo_nrmse: Number((0.4 / r).toFixed(3)), q2: multi ? null : Number(q2.toFixed(3)), pred_vs_verified_mae: null,
        per_objective: multi ? s.objectives.map((x, i) => ({ metric: x.metric, kind, n_train: nTrain, loo_rmse: Number(((5 + i) / r).toFixed(3)), loo_nrmse: Number(((0.3 + 0.05 * i) / r).toFixed(3)) })) : null,
        algo,
      },
      candidates: cands, best_value: null, best_feasible: null, improvement_rel: null,
    });
    o.iter_no = r;
    o.status = "VERIFYING";
    return;
  }
  if (o.status === "VERIFYING") {
    const it = o.iters.find((x) => x.iter_no === o.iter_no)!;
    for (const c of it.candidates ?? []) addRun(o, it.iter_no, c.doe_no, c.values, c.predicted ?? null, "VERIFY");
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

/** D3-61 마무리 캡처 흉내: 기준안(nominal)·최적안(다목적은 가중 추천점) 2 run(예측 작업 + 컨투어 media), 같은 범례 0~max */
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
    const objective = val(o.settings.objective.metric, v);
    return { doe_no: doe, job_id: null as string | null, values: v, objective, constraints: o.settings.constraints.map((c) => val(c.metric, v)), state: "SUCCEEDED" };
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
    if (o.stop_reason === "SURROGATE_ONLY") return "완료 — 대리모델만(검증 없음) — 미검증 후보";
    return o.stop_reason === "CONVERGED" && imp != null ? `완료 — 수렴(개선 ${(imp * 100).toFixed(1)}% < ${o.settings.tol_rel * 100}%)` : `완료 — ${o.stop_reason === "MAX_ITER" ? "최대 반복" : "새 후보 없음"}`;
  }
  if (o.status === "FAILED") return "실패 — 반복 작업이 실패했습니다";
  return "취소됨";
}

const objLabel = (o: SoRec, x: { metric: string; series: string | null }) => {
  const nm = x.metric.startsWith("perf:") ? x.metric.slice(5) : null;
  const def = nm ? o.settings.performances[nm] : null;
  if (nm && def) return perfLabel({ name: nm, unit: (def.unit as string) ?? "", source: (def.spec as { source: "H3D" | "CURVE" }).source, spec: def.spec as never });
  return metricLabel(x.metric, x.series);
};
const unitOf = (o: SoRec, metric: string) => (metric.startsWith("perf:") ? ((o.settings.performances[metric.slice(5)]?.unit as string) ?? "") : "");

/** 예측 전선 흉내: 마지막 전선 주변을 약간 좋은 쪽으로 이동한 점들의 비지배 집합(≤ 12점) */
function predictedFront(o: SoRec) {
  const fr = frontRuns(o);
  if (!fr.length) return [];
  const rnd = rng(o.opt_no * 31 + o.runs.length);
  const sn = senseOf(o);
  const pts = Array.from({ length: 36 }, () => {
    const base = fr[Math.floor(rnd() * fr.length)];
    const v = sample(o, rnd, base.values as Record<string, number>, 0.5);
    const mean = o.settings.objectives.map((x, i) => Number((metricValue(x.metric, v) * (sn[i] === "min" ? 0.985 : 1.015)).toPrecision(6)));
    return { values: v, mean, std: mean.map((m) => Number((Math.abs(m) * 0.03).toPrecision(3))), pof: Number((0.85 + rnd() * 0.14).toFixed(2)) };
  });
  return nonDominated(pts.map((p) => p.mean), sn).slice(0, 12).map((i) => pts[i]);
}

function detail(srv: MockServer, o: SoRec): SurrogateOpt {
  ensureFinalJobs(srv, o);
  const me = srv.me!;
  const s = srv.studies.find((x) => x.id === o.study_id)!;
  const ps = srv.paramSets.find((p) => p.id === o.param_set_id);
  const r = srv.role(s.project_id);
  const canExec = r === "power" || r === "admin";
  const st = o.settings;
  const multi = st.mode === "multi";
  const t = Math.max(...o.iters.map((x) => x.iter_no), 0);
  const x = bestRun(o, t);
  const consDict = (run: SoRun) => Object.fromEntries(st.constraints.map((c, i) => [c.metric, run.constraints?.[i] ?? null]));
  const frontIdx = multi ? new Set(frontRuns(o).map((q) => `${q.iter_no}:${q.doe_no}`)) : new Set<string>();
  const front = multi ? frontRuns(o) : [];
  const rec = multi && front.length ? recommend(front.map((q) => ({ key: `${q.iter_no}:${q.doe_no}`, f: q.objectives as number[], iter_no: q.iter_no, doe_no: q.doe_no })), senseOf(o), st.weights) : null;
  const b = !x ? null : {
    iter_no: x.iter_no, batch_id: x.batch_id, batch_label: x.batch_label, doe_no: x.doe_no, run_key: x.run_key, job_id: x.job_id, values: x.values,
    objective: x.objective, constraints: consDict(x), feasible: !!x.feasible,
    ...(multi ? { objectives: Object.fromEntries(st.objectives.map((q, i) => [q.metric, x.objectives?.[i] ?? null])), score: rec ? rec.scores[rec.index] : null, weights: rec?.weights ?? null } : {}),
  };
  const extraActive = !!o.extra;
  return {
    id: o.id, label: soLabel(o.opt_no), status: o.status, dir: srv.disp(o.study_id, `05_opt/surrogate/${soLabel(o.opt_no)}`),
    param_set: { id: o.param_set_id, label: ps?.label ?? null, input_kind: ps?.input_kind ?? "assembly" }, model: { id: "m-2", name: "cushion_gnn v2" },
    settings: o.settings, iter_no: o.iter_no, progress_text: progressText(o),
    iterations: o.iters.map((it) => ({
      ...it, candidates: it.candidates?.map((c) => {
        if (c.state === "UNVERIFIED") return c;
        const run = o.runs.find((q) => q.iter_no === it.iter_no && q.doe_no === c.doe_no);
        return { ...c, verified: run?.objective ?? null, verified_objectives: run?.objectives ?? null, state: run ? run.state : "QUEUED" };
      }) ?? null,
    })),
    runs: o.runs.map((q) => ({ ...q, on_front: frontIdx.has(`${q.iter_no}:${q.doe_no}`) })), best: b, stop_reason: o.stop_reason,
    can_cancel: ACTIVE.includes(o.status) && canExec && (me.is_global_admin || o.created_by === me.user_id), can_resume: o.status === "FAILED" && canExec,
    warnings: [], current_job_id: null, created_at: o.created_at, created_by_name: o.created_by_name, finished_at: o.finished_at,
    final: o.final ?? null,
    parameters: (ps?.parameters ?? []).map((p) => ({ name: p.name, nominal: p.nominal ?? null, min: p.min, max: p.max, unit: p.unit ?? "" })),
    mode: st.mode,
    objectives: st.objectives.map((q) => ({ metric: q.metric, series: q.series, sense: q.sense, label: objLabel(o, q), unit: unitOf(o, q.metric) })),
    constraints_def: st.constraints.map((c) => ({ metric: c.metric, series: c.series, op: c.op, value: c.value ?? null, lo: c.lo ?? null, hi: c.hi ?? null, label: objLabel(o, c), unit: unitOf(o, c.metric) })),
    observe: st.observe.map((c) => ({ metric: c.metric, series: c.series, label: objLabel(o, c), unit: unitOf(o, c.metric) })),
    weights: rec?.weights ?? (() => { const sum = st.weights.reduce((a, q) => a + q, 0) || 1; return st.weights.map((q) => q / sum); })(),
    pareto: multi ? {
      hv: o.iters.find((q) => q.iter_no === t)?.hv ?? null,
      frame: o.frame ? { ...o.frame, ref_offset: 0.1 } : null,
      front: front.map((q) => ({
        key: `${q.iter_no}:${q.doe_no}`, iter_no: q.iter_no, doe_no: q.doe_no, run_key: q.run_key, job_id: q.job_id ?? null, batch_label: q.batch_label, values: q.values,
        objectives: q.objectives as number[], constraints: consDict(q), observed: q.observed ?? {},
      })),
      recommended_key: rec?.key ?? null,
      predicted_iter: o.iters.length ? t : null,
      predicted: o.status === "DONE" || o.iters.length > 1 ? predictedFront(o) : [],
    } : null,
    hv_history: multi ? o.iters.filter((it) => it.hv != null).map((it) => ({ iter_no: it.iter_no, hv: it.hv ?? null, front_size: it.front_size ?? null, improvement_rel: it.improvement_rel ?? null })) : null,
    can_verify_more: o.status === "DONE" && canExec && !extraActive,
  };
}

/** 요청 정규화 + problems(§22.4.2). 목은 서버 규칙의 핵심만 흉내 */
function normalize(srv: MockServer, sid: string, body: Record<string, unknown>) {
  const ps = (body.param_set_id ? srv.paramSets.find((p) => p.id === body.param_set_id) : srv.paramSets.find((p) => p.study_id === sid && p.is_current)) as ParamSet | undefined;
  const problems: { code: string; field: string | null; message: string; action?: string; batch_id?: string; performance?: string }[] = [];
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

  // 목적: objectives 또는 단수 objective(S17 §22.4.1)
  if (body.objective && body.objectives) problems.push({ code: "OBJECTIVES_CONFLICT", field: "objectives", message: "objective와 objectives는 함께 보낼 수 없습니다" });
  const objectives = ((body.objectives as Obj[] | undefined) ?? (body.objective ? [body.objective as Obj] : [])).map((x) => ({ metric: x.metric, series: x.series ?? null, sense: x.sense ?? "min" }));
  if (objectives.length < 1 || objectives.length > 3) problems.push({ code: "OBJECTIVES_RANGE", field: "objectives", message: "목적은 1~3개여야 합니다" });
  const constraints = ((body.constraints ?? []) as Cons[]).map((c) => ({ ...c, series: c.series ?? null }));
  const observe = ((body.observe ?? []) as Obs[]).map((c) => ({ metric: c.metric, series: c.series ?? null }));
  const seen = new Set<string>();
  for (const x of [...objectives, ...constraints, ...observe]) {
    const key = `${x.metric}|${x.series ?? ""}`;
    if (seen.has(key)) problems.push({ code: "OBJECTIVE_DUPLICATE", field: "objectives", message: `'${x.metric.replace(/^perf:/, "")}'이(가) 목적·제약·관찰에 겹칩니다` });
    seen.add(key);
  }
  for (const c of constraints) if (c.op === "range" ? !(fin(c.lo) && fin(c.hi) && c.lo < c.hi) : !fin(c.value)) problems.push({ code: "CONSTRAINT_INVALID", field: "constraints", message: "제약 값이 올바르지 않습니다" });
  if (observe.length > 10) problems.push({ code: "OBSERVE_INVALID", field: "observe", message: "관찰은 10개까지입니다" });
  const w = (body.weights ?? null) as number[] | null;
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
  const weights = w && sum > 0 ? w.map((x) => x / sum) : objectives.map(() => 1 / Math.max(1, objectives.length));
  const settings: SoRec["settings"] = {
    names: ps.parameters.map((p) => p.name), integer, bounds,
    objective: objectives[0] ?? { metric: "", series: null, sense: "min" }, objectives, constraints, observe, weights, mode: objectives.length > 1 ? "multi" : "single", performances,
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
  return { ps, settings, problems, free: levels && levels.length > 1 ? [...free, "baseline"] : free, fixed, integer: integer.filter((n) => free.includes(n)), count, info, levels };
}

function newRec(id: string, studyId: string, no: number, psId: string, settings: SoRec["settings"], by: { id: string; name: string }, createdAt: string, batchNo: number, status = "EXPLORING"): SoRec {
  return { id, study_id: studyId, opt_no: no, param_set_id: psId, settings, status, iter_no: 0, iters: [], runs: [], stop_reason: null, created_by: by.id, created_by_name: by.name, created_at: createdAt, finished_at: null, batch_no: batchNo };
}

/** 시드: s-cushion에 완료된 SO-001(단일 목적) · SO-002(2목적) · SO-003(3목적, 커브 성능 포함) — 모두 쿠션 단독 템플릿(ps-2) */
export function seedSurrogate(srv: MockServer) {
  const power = { id: "u-power", name: "김연구" };
  const n = normalize(srv, "s-cushion", {
    param_set_id: "ps-2", explore: { kind: "new", count: 16, seed: 1 }, objective: { metric: "resp:MaxStress_MAX", sense: "min" },
    constraints: [{ metric: "resp:MaxDisp_MAX", op: "<=", value: 14 }], iterations: 3, candidates: 4, tol_rel: 0.01, multi_execution: 4,
  });
  if ("error" in n) return;
  const o = newRec("so-1", "s-cushion", 1, "ps-2", n.settings, power, iso(60 * 3), 10);
  for (let i = 0; i < 20 && o.status !== "DONE"; i++) advance(o, srv);
  o.finished_at = iso(20);
  srv.surrogate.push(o);

  const two = normalize(srv, "s-cushion", {
    param_set_id: "ps-2", explore: { kind: "new", count: 16, seed: 2 },
    objectives: [{ metric: "perf:MaxStress", series: null, sense: "min" }, { metric: "perf:MaxDisp", series: null, sense: "min" }],
    iterations: 3, candidates: 4, tol_rel: 0.001, multi_execution: 4, weights: [50, 50],
  });
  if (!("error" in two)) {
    const o2 = newRec("so-2", "s-cushion", 2, "ps-2", two.settings, power, iso(60 * 2), 30);
    for (let i = 0; i < 20 && o2.status !== "DONE"; i++) advance(o2, srv);
    o2.finished_at = iso(15);
    srv.surrogate.push(o2);
  }
  const three = normalize(srv, "s-cushion", {
    param_set_id: "ps-2", explore: { kind: "new", count: 20, seed: 3 },
    objectives: [{ metric: "perf:MaxStress", series: null, sense: "min" }, { metric: "perf:MaxDisp", series: null, sense: "min" }, { metric: "perf:AccelPeak", series: null, sense: "min" }],
    iterations: 3, candidates: 4, tol_rel: 0.001, multi_execution: 4,
  });
  if (!("error" in three)) {
    three.settings.performances.AccelPeak = { unit: "g", spec: { source: "CURVE", series: "Node 100 / X", stat: "ABSMAX" } };
    const o3 = newRec("so-3", "s-cushion", 3, "ps-2", three.settings, power, iso(60), 50);
    for (let i = 0; i < 20 && o3.status !== "DONE"; i++) advance(o3, srv);
    o3.finished_at = iso(10);
    srv.surrogate.push(o3);
  }
}

export function tickSurrogate(srv: MockServer) {
  for (const o of srv.surrogate) {
    if (ACTIVE.includes(o.status)) advance(o, srv);
    if (o.extra) finishExtra(o);
  }
  // S17 PB_RESP_EXTRACT 완료 → 배치 하위 예측의 응답 표에 H3D 성능 값을 채운다(멱등)
  for (const j of srv.jobs) {
    if (j.job_type !== "PB_RESP_EXTRACT" || j.state !== "SUCCEEDED" || (j as { _applied?: boolean })._applied) continue;
    (j as { _applied?: boolean })._applied = true;
    const b = srv.batches.find((x) => x.id === (j.params as { batch_id?: string }).batch_id);
    const ps = b && srv.paramSets.find((p) => p.id === b.param_set_id);
    if (!b || !ps) continue;
    for (const r of b.runs) {
      const pj = srv.jobs.find((x) => x.id === r.predict_job_id);
      const res = pj?.result as { response_table?: { name: string; unit: string; predicted: number | null; nearest_measured: number | null; diff_pct: number | null }[]; applied_values?: Record<string, number> } | null;
      if (!pj || !res || pj.state !== "SUCCEEDED") continue;
      const pred = responseFn({ ...(res.applied_values ?? r.applied_values), RIB_N: Math.round((res.applied_values ?? r.applied_values).RIB_N ?? 4) }) as Record<string, number>;
      res.response_table = res.response_table ?? [];
      for (const d of perfRows(ps.responses)) {
        if (d.source !== "H3D" || res.response_table.some((q) => q.name === d.name)) continue;
        res.response_table.push({ name: d.name, unit: d.unit, predicted: Number((pred[d.name] ?? metricValue(`perf:${d.name}`, r.applied_values)).toFixed(4)), nearest_measured: null, diff_pct: null });
      }
    }
  }
}

function finishExtra(o: SoRec) {
  const ex = o.extra!;
  if (--ex.ticks > 0) return;
  ex.points.forEach((v, i) => addRun(o, ex.iter_no, i + 1, v, null, "EXTRA"));
  const it = o.iters.find((x) => x.iter_no === ex.iter_no);
  if (it) it.batch = batchRef(o, ex.iter_no, ex.points.length, true);
  o.extra = null;
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
      const none = st.verification === "none";
      const total = n.count + (none ? 0 : st.iterations * st.candidates);
      return ok({ free_variables: n.free, integer_variables: n.integer, fixed: n.fixed, explore_count: n.count,
        max_total_runs: total, estimate_min: Math.round(total * 2.2),
        objective_available: true, problems: n.problems, mode: st.mode, performances: n.info,
        algorithm: st.algorithm, algo_options: st.algo_options, verification: st.verification,
        variables_kind: Object.fromEntries(n.free.map((v) => [v, v === "baseline" ? "categorical" : n.integer.includes(v) ? "integer" : "continuous"])),
        levels: n.levels ? { baseline: n.levels } : null });
    }
    if (method === "POST" && !seg[3]) {
      const deny = needPower(srv, s.project_id);
      if (deny) return deny;
      const n = normalize(srv, s.id, body ?? {});
      if ("error" in n) return n.error!;
      if (n.problems.length) return err(422, "SURROGATE_OPT_INVALID", "내장 최적화 설정이 올바르지 않습니다", { problems: n.problems });
      if (srv.surrogate.some((o) => o.study_id === s.id && ACTIVE.includes(o.status))) return err(409, "SURROGATE_OPT_ACTIVE", "이 Study에 진행 중인 내장 최적화가 있습니다 — 끝나거나 취소한 뒤 시작하세요");
      const no = Math.max(0, ...srv.surrogate.filter((o) => o.study_id === s.id).map((o) => o.opt_no)) + 1;
      const o = newRec(srv.nid("so"), s.id, no, n.ps.id, n.settings, { id: me.user_id, name: me.display_name }, new Date().toISOString(), 20 + no * 5,
        n.settings.explore.kind === "new" ? "EXPLORING" : "FITTING");
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
      const st = o.settings;
      const multi = st.mode === "multi";
      const head = ["iter", "batch", "doe_no", "run_key", ...st.names, ...(multi ? st.objectives.map((_, i) => `objective_${i + 1}`) : ["objective"]), ...st.constraints.map((c) => c.metric), ...st.observe.map((c) => `obs:${c.metric}`), "predicted", "feasible", "state"];
      const lines = o.runs.map((r) => [r.iter_no, r.batch_label, r.doe_no, r.run_key, ...st.names.map((n) => (r.values as Record<string, number>)[n]), ...(multi ? (r.objectives ?? []).map((v) => v ?? "") : [r.objective ?? ""]), ...(r.constraints ?? []).map((v) => v ?? ""), ...st.observe.map((c) => r.observed?.[c.metric] ?? ""), r.predicted ?? "", r.feasible == null ? "" : String(r.feasible), r.state].join(","));
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
    if (method === "POST" && seg[2] === "verify") {
      const deny = needPower(srv, s.project_id);
      if (deny) return deny;
      if (o.status !== "DONE") return err(409, "SURROGATE_OPT_NOT_DONE", "끝난 내장 최적화만 추가 검증할 수 있습니다");
      if (o.extra) return err(409, "SURROGATE_OPT_EXTRA_ACTIVE", "진행 중인 추가 검증이 있습니다");
      const pts = ((body?.points ?? []) as { values: Record<string, number> }[]).map((p) => p.values);
      if (pts.length < 1 || pts.length > 10) return err(422, "SURROGATE_OPT_INVALID", "추가 검증은 1~10개 점입니다", { problems: [{ code: "POINTS_RANGE", field: "points", message: "점은 1~10개입니다" }] });
      const bad = pts.flatMap((v) => o.settings.names.filter((n) => !(v[n] >= o.settings.bounds[n][0] && v[n] <= o.settings.bounds[n][1])));
      if (bad.length) return err(422, "SURROGATE_OPT_INVALID", "점이 변수 범위 밖입니다", { problems: [{ code: "BOUNDS_OUT_OF_RANGE", field: "points", message: `범위 밖 변수: ${[...new Set(bad)].join(", ")}` }] });
      const iter = Math.max(...o.iters.map((x) => x.iter_no), 0) + 1;
      o.iters.push({ iter_no: iter, kind: "EXTRA", batch: batchRef(o, iter, pts.length, false), fit: null, candidates: null, best_value: null, best_feasible: null, improvement_rel: null });
      o.extra = { iter_no: iter, points: pts, capture: !!body?.capture, ticks: 2 };
      return ok({ batch_id: `b-so-${o.id}-${iter}`, batch_label: `B-${String(o.batch_no + iter).padStart(3, "0")}`, job_id: srv.nid("j"), iter_no: iter }, 201);
    }
  }
  return null;
};

export type { SoRec };
