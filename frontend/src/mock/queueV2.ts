// job-queues.md §8 GPU·CPU 대기열 분리 목. 엔진(engine.ts)은 옛 단일 SLOT 레인 그대로 두고, `/queue` 응답과 순서 이동만 새 모양으로 낸다.
// 규칙: lane GPU → GPU 대기열, lane LIGHT·PREVIEW → 가벼운 작업, 그 밖(CPU·옛 SLOT) → CPU 대기열.
// 구간 전환(T17)은 `moveToLane`이 흉내: 다른 대기열에 QUEUED로 다시 세우고 `resumed` 표시.
import type { Job, JobSummary } from "../api/types";
import { STEP_CHAINS, baseJob, iso, makeSteps } from "./data";
import type { MockServer } from "./server";

export type QKey = "GPU" | "CPU" | "LIGHT";

export interface QueueV2State {
  /** true면 옛 서버 응답(gpu·cpu 없음, lane = SLOT) */
  legacy: boolean;
  cpuLimit: number;
  memoryGate: "ok" | "low" | null;
  resumed: Set<string>;
}

export function newQueueV2State(): QueueV2State {
  return { legacy: false, cpuLimit: 4, memoryGate: null, resumed: new Set() };
}

export function qkey(j: Pick<Job, "lane">): QKey {
  return j.lane === "GPU" ? "GPU" : j.lane === "LIGHT" || j.lane === "PREVIEW" ? "LIGHT" : "CPU";
}

export function queuedIn(srv: MockServer, key: QKey): Job[] {
  return srv.jobs
    .filter((j) => j.state === "QUEUED" && qkey(j) === key)
    .sort((a, b) => (srv.queueOrder.get(a.id) ?? 0) - (srv.queueOrder.get(b.id) ?? 0));
}

type Sum = (srv: MockServer, j: Job) => JobSummary;

/** `GET /queue` 본문. deprecated 필드(slot·running·queued)도 §8.1대로 채운다 */
export function queueBody(srv: MockServer, summary: Sum) {
  const q = srv.qv2;
  // 재진입 대기는 다음 step을 current_step_*로 낸다(목의 가정 — 서버 값 확정 전)
  const nextStep = (j: Job) => {
    const s = j.steps.find((x) => x.state === "PENDING");
    return s ? { current_step_key: s.step_key, current_step_label: srv.stepLabel(s.step_key) } : {};
  };
  const out = (j: Job): JobSummary => ({
    ...summary(srv, j),
    lane: q.legacy ? "SLOT" : j.lane === "SLOT" ? "CPU" : j.lane,
    ...(q.resumed.has(j.id) && !q.legacy ? { resumed: true, ...(j.state === "QUEUED" ? nextStep(j) : {}) } : {}),
  });
  const running = (key: QKey) => srv.jobs.filter((j) => j.state === "RUNNING" && qkey(j) === key);
  const lightRun = running("LIGHT")[0] ?? null;
  const gpuRun = running("GPU");
  const cpuRun = running("CPU");
  const gpuQ = queuedIn(srv, "GPU");
  const cpuQ = queuedIn(srv, "CPU");
  const holder = gpuRun[0] ?? null;
  const merged = [...gpuQ, ...cpuQ].sort((a, b) => (srv.queueOrder.get(a.id) ?? 0) - (srv.queueOrder.get(b.id) ?? 0));
  const first = holder ?? cpuRun[0] ?? null;
  return {
    ...(q.legacy
      ? {}
      : {
          gpu: { limit: 1, running: gpuRun.map(out), queued: gpuQ.map(out), since: holder?.started_at ?? null },
          cpu: { limit: q.cpuLimit, running: cpuRun.map(out), queued: cpuQ.map(out), min_free_memory_gb: 8, memory_gate: q.memoryGate },
        }),
    slot: { holder_job_id: holder?.id ?? null, since: holder?.started_at ?? null },
    running: first ? out(first) : null,
    queued: merged.map(out),
    light: { running: lightRun ? out(lightRun) : null, queued: queuedIn(srv, "LIGHT").map(out) },
    waiting_hpc: srv.jobs.filter((j) => j.state === "WAITING_HPC").map(out),
    collecting: srv.jobs.filter((j) => j.state === "COLLECTING").map(out),
  };
}

/** 구간 전환 흉내(T17): 지금 슬롯을 놓고 다른 대기열에 원래 순번으로 다시 선다. resumed = 진행률 > 0 */
export function moveToLane(srv: MockServer, id: string, lane: "GPU" | "CPU") {
  const j = srv.jobs.find((x) => x.id === id);
  if (!j) return;
  j.lane = lane;
  j.state = "QUEUED";
  srv.queueOrder.set(j.id, ++srv.queueSeq);
  if ((j.progress_pct ?? 0) > 0) srv.qv2.resumed.add(j.id);
  srv.bump(j);
}

function stepIdx(type: Job["job_type"], key: string): number {
  return STEP_CHAINS[type].findIndex((s) => s.key === key);
}

/** 화면 시연·시험용 시드: GPU 실행 1·대기 2(1건은 재진입), CPU 실행 3/4·대기 3(1건은 재진입), 메모리 문 low */
export function seedQueueDemo(srv: MockServer) {
  const st = "쿠션 두께·리브 예측";
  const mk = (id: string, type: Job["job_type"], lane: "GPU" | "CPU", state: Job["state"], at: string | null, pct: number | null, extra: Partial<Job> = {}) => {
    const k = at ? stepIdx(type, at) : 0;
    const j = baseJob({
      id, study_id: "s-cushion", project_id: "p-cushion", study_title: st, job_type: type, state, lane, created_at: iso(20),
      progress_pct: pct, started_at: state === "RUNNING" ? iso(8) : pct ? iso(15) : null,
      steps: makeSteps(type, k, state === "RUNNING" ? k : null), ...extra,
    });
    srv.jobs.push(j);
    if (state === "QUEUED") srv.queueOrder.set(id, ++srv.queueSeq);
    return j;
  };
  // 옛 시드의 평가(j-q1)는 GPU 대기열로
  const q1 = srv.jobs.find((j) => j.id === "j-q1");
  if (q1) q1.lane = "GPU";
  mk("g-run", "PREDICT", "GPU", "RUNNING", "EDSPY_PREDICT", 55, { created_by: "u-other", created_by_name: "최해석" });
  mk("g-q1", "PREDICT", "GPU", "QUEUED", "EDSPY_PREDICT", 40, { created_by: "u-other", created_by_name: "최해석" });
  srv.qv2.resumed.add("g-q1");
  mk("c-run1", "PREDICT", "CPU", "RUNNING", "MESH", 30);
  mk("c-run2", "FEM_VERIFY", "CPU", "RUNNING", "FV_MESH", 20, { created_by: "u-other", created_by_name: "최해석" });
  mk("c-q1", "PREDICT", "CPU", "QUEUED", "RAD_ASSEMBLE", 60);
  srv.qv2.resumed.add("c-q1");
  mk("c-q2", "PREDICT", "CPU", "QUEUED", null, null);
  srv.qv2.memoryGate = "low";
}
