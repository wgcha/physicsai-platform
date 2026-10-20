// phase3.md §14 S9 목(R-F 분할): 시드 배치(s-cushion 끝난 B-002, 데모별 진행 중·Sobol·Box–Behnken B-003).
import type { BatchSource, Job } from "../api/types";
import { baseJob, iso, makeSteps } from "./data";
import { isNewKind, mockDesign } from "./sampling";
import type { MockServer } from "./server";
import { BATCH_MAX_RUNS } from "./predictBatchRec";
import type { BatchRec } from "./predictBatchRec";
import { applyRows, lhs } from "./predictBatchMatrix";
import { batchChildResult, finishBatchParent } from "./predictBatchJobs";

// ------------------------------------------------------------------ 시드
function seedBatch(srv: MockServer, no: number, count: number, opts: { running?: boolean; genFail?: number[]; predFail?: number[]; source?: BatchSource }) {
  const s = srv.studies.find((x) => x.id === "s-cushion")!;
  const ps = srv.paramSets.find((p) => p.id === "ps-1")!;
  // S15 시드: source를 주면 그 방식의 조합(mockDesign)으로 만든다(예: 화면 확인용 Sobol·Box–Behnken 배치)
  const design = opts.source && isNewKind(opts.source.kind) ? mockDesign(ps, opts.source, BATCH_MAX_RUNS, []) : null;
  const rows = design ? applyRows(ps, design.rows) : lhs(ps, count, no, {});
  const rec: BatchRec = {
    meta: design ? design.meta : { count, seed: no, ranges: Object.fromEntries(ps.parameters.map((p) => [p.name, [p.min, p.max]])) },
    id: `pb-${no}`, study_id: s.id, batch_no: no, job_id: `j-pb${no}`, param_set_id: ps.id, model_id: s.final_model_id ?? "m-2", input_kind: "assembly", source_kind: opts.source ? opts.source.kind.toUpperCase() : "LHS",
    multi_execution: 4, created_by: "u-power", created_by_name: "김연구", created_at: iso(opts.running ? 40 : 60 * 6), canceled: false, done_notified: true,
    runs: rows.map((r) => ({ ...r, gen_state: "DONE", gen_code: null, gen_message: null, predict_job_id: null })),
  };
  srv.batches.unshift(rec);
  const parent = baseJob({
    id: rec.job_id, study_id: s.id, project_id: s.project_id, study_title: s.title, job_type: "PREDICT_BATCH", state: "SUCCEEDED",
    created_at: rec.created_at, started_at: iso(opts.running ? 39 : 60 * 6 - 1), finished_at: iso(opts.running ? 27 : 60 * 6 - 13), progress_pct: 100,
    steps: makeSteps("PREDICT_BATCH", 3, null), params: { param_set_id: ps.id, model_id: null, multi_execution: 4, source: opts.source ?? { kind: "lhs", count, seed: no }, batch_id: rec.id, batch_no: no },
  });
  srv.jobs.push(parent);
  for (const n of opts.genFail ?? []) Object.assign(rec.runs[n - 1], { gen_state: "FAILED", gen_code: "OUTPUT_MISSING", gen_message: "m_1 EPS_mesh_0000.rad가 만들어지지 않았습니다" });
  finishBatchParent(srv, parent);
  const kids = rec.runs.map((r) => srv.jobs.find((x) => x.id === r.predict_job_id)).filter((x): x is Job => !!x);
  kids.forEach((c, i) => {
    srv.queueOrder.delete(c.id);
    const done = !opts.running || i < 7;
    c.created_at = iso(opts.running ? 27 - i * 0.01 : 60 * 6 - 13);
    if (done) {
      const fail = (opts.predFail ?? []).includes(rec.runs.find((r) => r.predict_job_id === c.id)!.doe_no);
      Object.assign(c, { state: fail ? "FAILED" : "SUCCEEDED", started_at: iso(60), finished_at: iso(59), progress_pct: 100, steps: makeSteps("PREDICT", fail ? 5 : 10, null, fail ? { failedIdx: 5 } : {}) });
      if (fail) Object.assign(c, { failure_code: "EXIT_NONZERO", failure_message: "edspy 종료코드 1" });
      else c.result = batchChildResult(srv, c);
    } else if (i === 7) Object.assign(c, { state: "RUNNING", started_at: iso(2), progress_pct: 40, steps: makeSteps("PREDICT", 5, 5) });
    else srv.queueOrder.set(c.id, ++srv.queueSeq);
  });
}

/** demo: "running" 진행 중 B-003 · "sobol" 끝난 Sobol 16개 B-003(이어서 추가 후보) · "bbd" 끝난 Box–Behnken B-003(⑤ 영향도 참고용 확인) */
export function seedBatches(srv: MockServer, demo?: "running" | "sobol" | "bbd") {
  seedBatch(srv, 2, 20, { genFail: [12], predFail: [5] });
  if (demo === "running") seedBatch(srv, 3, 20, { running: true });
  if (demo === "sobol") seedBatch(srv, 3, 16, { source: { kind: "sobol", count: 16, seed: 1, ranges: null, continue_from: null } });
  if (demo === "bbd") seedBatch(srv, 3, 25, { source: { kind: "bbd", ranges: null } });
}
