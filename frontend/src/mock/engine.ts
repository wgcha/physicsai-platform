// 목 작업 진행 엔진: 대기열 순서·위치, tick(claim → 진행 → 완료), 완료 처리(③·④는 stage3·stage4, 2차는 p2).
import type { Job } from "../api/types";
import { STEP_CHAINS, makeSteps } from "./data";
import type { MockServer } from "./server";
import { finishStage3 } from "./stage3";
import { finishStage4 } from "./stage4";
import { adjustPreparedSteps } from "./stage4Prepared";
import { batchAfterChild, batchOnProgress, isBatchChild } from "./predictBatch";
import { tickScx } from "./scx";
import { tickSurrogate } from "./surrogateOpt";

export function queued(srv: MockServer, lane: "SLOT" | "LIGHT") {
  return srv.jobs
    .filter((j) => j.state === "QUEUED" && j.lane === lane)
    .sort((a, b) => (srv.queueOrder.get(a.id) ?? 0) - (srv.queueOrder.get(b.id) ?? 0));
}

export function refreshPositions(srv: MockServer) {
  for (const lane of ["SLOT", "LIGHT"] as const) queued(srv, lane).forEach((j, i) => (j.queue_position = i + 1));
  for (const j of srv.jobs) if (j.state !== "QUEUED") j.queue_position = null;
}

/** 시간 1단계 진행: claim → 진행 → 완료 */
export function tickJobs(srv: MockServer) {
  for (const j of srv.jobs.filter((x) => x.state === "RUNNING")) {
    if (j.cancel_requested) {
      j.state = "CANCELED";
      j.finished_at = new Date().toISOString();
      j.steps.forEach((s) => s.state === "RUNNING" && (s.state = "CANCELED"));
      srv.bump(j);
      srv.notifyJob(j, "JOB_CANCELED");
      if (isBatchChild(j)) batchAfterChild(srv, j);
      continue;
    }
    const sp = (j as Job & { _speed?: number })._speed ?? (j.lane === "LIGHT" ? 50 : srv.speed);
    const prev = (j as Job & { _pct?: number })._pct ?? j.progress_pct ?? 0;
    j.progress_pct = Math.min(100, prev + sp);
    (j as Job & { _pct?: number })._pct = j.progress_pct;
    const chain = STEP_CHAINS[j.job_type];
    const done = Math.min(chain.length, Math.floor(((j.progress_pct ?? 0) / 100) * chain.length));
    j.steps = makeSteps(j.job_type, done, done < chain.length ? done : null);
    adjustPreparedSteps(srv, j);
    const cur = chain[done];
    j.progress_label = cur ? `${cur.key} …` : null;
    batchOnProgress(srv, j);
    srv.p2.onProgress(j);
    if (((j as Job & { _pct?: number })._pct ?? 0) >= 100) finishJob(srv, j);
    srv.bump(j);
  }
  // claim
  for (const lane of ["SLOT", "LIGHT"] as const) {
    if (srv.jobs.some((j) => j.state === "RUNNING" && j.lane === lane)) continue;
    const next = queued(srv, lane)[0];
    if (!next) continue;
    next.state = "RUNNING";
    next.started_at = new Date().toISOString();
    next.progress_pct = 0;
    next.steps = makeSteps(next.job_type, 0, 0);
    srv.queueOrder.delete(next.id);
    srv.bump(next);
    if (next.job_type !== "STUDY_STORAGE_SCAN") srv.notifyJob(next, "JOB_STARTED"); // phase3 R3-3
    if (next.job_type === "EVALUATE") {
      const m = srv.models.find((x) => x.id === (next.params.model_id as string));
      if (m) m.eval_status = "RUNNING";
    }
    if (lane === "SLOT") {
      const first = queued(srv, "SLOT")[0] as (Job & { _notified?: boolean }) | undefined;
      if (first && !first._notified) {
        first._notified = true;
        srv.notifyJob(first, "MY_TURN_NEXT");
      }
    }
  }
  tickScx(srv);
  tickSurrogate(srv); // S13 ⑤ 내장 최적화 한 단계
  srv.p2.tick();
  refreshPositions(srv);
}

function finishJob(srv: MockServer, j: Job) {
  const r2 = srv.p2.finish(j);
  if (r2 === "waiting") {
    j.state = "WAITING_HPC";
    j.progress_pct = null;
    return;
  }
  j.state = "SUCCEEDED";
  j.finished_at = new Date().toISOString();
  j.progress_pct = 100;
  j.progress_label = null;
  j.steps = makeSteps(j.job_type, STEP_CHAINS[j.job_type].length, null);
  adjustPreparedSteps(srv, j);
  finishStage3(srv, j);
  finishStage4(srv, j);
  if (srv.manage.storage.onFinish(j)) srv.notifyJob(j, "JOB_SUCCEEDED");
  if (isBatchChild(j)) batchAfterChild(srv, j);
}
