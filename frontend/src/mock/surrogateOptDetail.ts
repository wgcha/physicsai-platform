// phase3.md §18 S13·§22 S17 목(R-F 분할): 진행 문구·예측 전선·상세 응답(SurrogateOpt).
import type { SoRun, SurrogateOpt } from "../api/surrogateOpt";
import type { MockServer } from "./server";
import { rng } from "./data";
import { nonDominated, recommend } from "../stages/stage5/surrogate/pareto";
import { perfLabel } from "../stages/stage5/surrogate/perfRules";
import { metricLabel } from "../stages/stage5/surrogate/soRules";
import { ACTIVE, soInput, soLabel } from "./surrogateOptRec";
import type { SoRec } from "./surrogateOptRec";
import { bestRun, frontRuns, metricValue, sample, senseOf } from "./surrogateOptMath";
import { ensureFinalJobs } from "./surrogateOptAdvance";

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

export function detail(srv: MockServer, o: SoRec): SurrogateOpt {
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
    id: o.id, label: soLabel(o.opt_no), input: soInput(o, ps), status: o.status, dir: srv.disp(o.study_id, `05_opt/surrogate/${soLabel(o.opt_no)}`),
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
    parameters: ((o.settings.vars as { variables?: { name: string; nominal: number | null; min: number; max: number; unit: string }[] } | undefined)?.variables ?? ps?.parameters ?? []).map((p) => ({ name: p.name, nominal: p.nominal ?? null, min: p.min, max: p.max, unit: p.unit ?? "" })),
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
