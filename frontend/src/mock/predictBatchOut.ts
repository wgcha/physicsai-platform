// phase3.md §14 S9 목(R-F 분할): 배치 상태·행 상태 계산(하위 작업 재시도 사슬에서 매번 계산)·PredictBatch 응답 모양.
import type { BatchSampling, BatchRowState, BatchStatus, Job, PredictBatch, PredictBatchRow } from "../api/types";
import { mockSampling } from "./sampling";
import type { MockServer } from "./server";
import { TERMINAL, batchLabel } from "./predictBatchRec";
import type { BatchRec, BatchRunRec } from "./predictBatchRec";

// ------------------------------------------------------------------ 배치 상태 계산
function latestJob(srv: MockServer, id: string | null): Job | null {
  let j = id ? srv.jobs.find((x) => x.id === id) ?? null : null;
  for (let k = 0; j && k < 20; k++) {
    const next = srv.jobs.find((x) => x.retry_of_job_id === j!.id);
    if (!next) break;
    j = next;
  }
  return j;
}

function rowState(srv: MockServer, b: BatchRec, r: BatchRunRec): { state: BatchRowState; job: Job | null } {
  const job = latestJob(srv, r.predict_job_id);
  if (job) {
    const s = job.state;
    return { state: s === "SUCCEEDED" ? "SUCCEEDED" : s === "RUNNING" || s === "COLLECTING" || s === "WAITING_HPC" ? "RUNNING" : s === "QUEUED" ? "QUEUED" : s === "CANCELED" ? "CANCELED" : "FAILED", job };
  }
  if (b.canceled && r.gen_state !== "FAILED") return { state: "CANCELED", job: null };
  return { state: r.gen_state === "RUNNING" ? "GENERATING" : r.gen_state === "FAILED" ? "GEN_FAILED" : r.gen_state === "DONE" ? "QUEUED" : "GEN_PENDING", job: null };
}

function parentJob(srv: MockServer, b: BatchRec): Job | undefined {
  return latestJob(srv, b.job_id) ?? undefined;
}

export function batchStatus(srv: MockServer, b: BatchRec): BatchStatus {
  if (b.canceled) return "CANCELED";
  const p = parentJob(srv, b);
  if (p && !TERMINAL.includes(p.state)) return "GENERATING";
  if (p && p.state !== "SUCCEEDED" && !b.runs.some((r) => r.predict_job_id)) return "FAILED";
  const states = b.runs.map((r) => rowState(srv, b, r).state);
  return states.some((s) => s === "QUEUED" || s === "RUNNING" || s === "GEN_PENDING" || s === "GENERATING") ? "PREDICTING" : "DONE";
}

function responsesOf(job: Job | null): Record<string, number | null> | null {
  if (!job || job.state !== "SUCCEEDED") return null;
  const t = (job.result as { response_table?: { name: string; predicted: number | null }[] } | null)?.response_table ?? [];
  return Object.fromEntries(t.map((x) => [x.name, x.predicted == null ? null : Number(x.predicted.toFixed(4))]));
}

/** §20.6 배치 상세·미리보기 sampling(등급은 서버가 정함 — 목은 §20.7 표 그대로) */
export function samplingOf(srv: MockServer, b: BatchRec): BatchSampling {
  const doe = b.source_kind === "TRAIN_DOE" ? srv.p2.does.find((d) => d.id === b.meta.doe_id) : undefined;
  // 최적화 소유 VERIFY·FINAL 배치는 kind보다 우선 reference(§20.7) — 목은 소유 배치를 만들지 않는다
  return mockSampling(b.source_kind, b.meta, { doeType: doe?.doe_type ?? null, doeOptions: doe?.options, });
}

export function batchOut(srv: MockServer, b: BatchRec): PredictBatch {
  const ps = srv.paramSets.find((p) => p.id === b.param_set_id)!;
  const model = srv.models.find((m) => m.id === b.model_id);
  const dir = srv.disp(b.study_id, `04_batch/${batchLabel(b.batch_no)}`);
  const rows: PredictBatchRow[] = b.runs.map((r) => {
    const { state, job } = rowState(srv, b, r);
    return {
      doe_no: r.doe_no, run_key: r.run_key, folder: `${dir}\\${r.run_key}`, values: r.values, applied_values: r.applied_values, out_of_range: r.out_of_range,
      state, code: state === "GEN_FAILED" ? r.gen_code : state === "FAILED" ? job?.failure_code ?? null : null,
      message: state === "GEN_FAILED" ? r.gen_message : state === "FAILED" ? job?.failure_message ?? null : null,
      job_id: job?.id ?? null, responses: responsesOf(job),
      media_views: job?.state === "SUCCEEDED" ? ((job.result as { media?: { view: string }[] | null } | null)?.media ?? []).map((m) => m.view) : [], // S10
    };
  });
  const cnt = (s: BatchRowState) => rows.filter((r) => r.state === s).length;
  const gen = { total: b.runs.length, done: b.runs.filter((r) => r.gen_state === "DONE").length, failed: b.runs.filter((r) => r.gen_state === "FAILED").length, running: b.runs.filter((r) => r.gen_state === "RUNNING").length, waiting: b.runs.filter((r) => r.gen_state === "PENDING").length };
  return {
    id: b.id, label: batchLabel(b.batch_no), status: batchStatus(srv, b), dir, input_kind: b.input_kind,
    param_set: { id: ps.id, label: ps.label ?? null }, model: { id: b.model_id, name: model ? `${model.name} v${model.version}` : b.model_id },
    job_id: parentJob(srv, b)?.id ?? b.job_id, multi_execution: b.multi_execution, gen,
    predict: { running: cnt("RUNNING"), queued: cnt("QUEUED"), succeeded: cnt("SUCCEEDED"), failed: cnt("FAILED"), canceled: cnt("CANCELED") },
    parameters: ps.parameters.map((p) => p.name), responses: ps.responses.map((r) => ({ name: r.name, unit: r.unit })), rows,
    source_kind: b.source_kind, sampling: samplingOf(srv, b), created_at: b.created_at, created_by_name: b.created_by_name, finished_at: null,
    can_cancel: ["GENERATING", "PREDICTING"].includes(batchStatus(srv, b)),
    can_retry_failed: rows.some((r) => r.state === "GEN_FAILED" || r.state === "FAILED" || r.state === "CANCELED"),
  };
}
