// phase3.md §18 S13·§22 S17 목(R-F 분할): 엔진 tick 한 단계 진행(탐색 → 학습 → 검증 → 완료)·최종 후보 작업.
import type { MockServer } from "./server";
import { baseJob, iso, makeSteps, rng } from "./data";
import { captureMedia } from "./capture";
import type { SoRec } from "./surrogateOptRec";
import { addRun, bestRun, frontRuns, metricValue, sample, updateBest, val } from "./surrogateOptMath";

export function batchRef(o: SoRec, it: number, n: number, done: boolean) {
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

export function ensureFinalJobs(srv: MockServer, o: SoRec) {
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
