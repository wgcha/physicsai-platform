// 2차 ① 작업 훅: 사전 검사·DOE 행 생성·완료 처리·PBS run 진행(tick)·hpc_summary.
import type { HpcSummary, Job, JobType, Study, TrainRunState } from "../api/types";
import { makeSteps, rng } from "./data";
import { DOE_TYPES } from "./catalog";
import { err, type MockResp } from "./route";
import type { Phase2Mock } from "./phase2";
import { runKey, trainParams, type RunRec } from "./stage1";
import { nativeTrainParams } from "./geometry";

export function hpcSummary(p2: Phase2Mock, j: Job): HpcSummary | null {
  if (j.job_type !== "TD_SOLVE" && j.job_type !== "PREDICT_VERIFY") return null;
  if (j.job_type === "PREDICT_VERIFY") return null;
  const doe = j.params.doe_id as string;
  const runs = (p2.runs[doe] ?? []).filter((r) => r._job === j.id);
  if (!runs.length) return null;
  const h: HpcSummary = { total: runs.length, queued: 0, running: 0, succeeded: 0, failed: 0, collected: 0 };
  for (const r of runs) {
    if (r.state === "SUBMITTED") r.hpc?.state === "QUEUED" ? h.queued++ : h.running++; // C11: CANCEL_REQUESTED는 running
    else if (r.state === "SOLVED") h.succeeded++;
    else if (r.state === "COLLECTED") {
      h.succeeded++; // C11: collected는 succeeded와 겹친다
      h.collected++;
    }
    else if (r.state === "SOLVE_FAILED" || r.state === "COLLECT_FAILED") h.failed++;
  }
  return h;
}

export function precheckTrain(p2: Phase2Mock, s: Study, type: JobType, params: Record<string, unknown>): MockResp | null {
  if (type === "TD_DOE_GEN" && p2.setups[s.id]?.engine !== "native") {
    const t = p2.setups[s.id]?.tpl;
    if (!t) return err(409, "TPL_REQUIRED", "tpl을 먼저 생성하세요.");
    if (t.stale) return err(409, "TPL_STALE", "파라미터 표가 바뀌었습니다 — tpl을 다시 생성하세요.");
  }
  if (type === "TD_SOLVE" || type === "TD_RESULT_IMPORT") {
    const d = p2.does.find((x) => x.id === params.doe_id && x.study_id === s.id);
    if (!d || d.status !== "READY") return err(409, "DOE_NOT_READY", "준비된 DOE가 필요합니다.");
  }
  return null;
}

export function onCreateTrain(p2: Phase2Mock, j: Job, me: { display_name: string }) {
  const p = j.params as Record<string, unknown>;
  const sid = j.study_id;
  const now = j.created_at;
  if (j.job_type === "TD_DOE_GEN") {
    const id = p2.s.nid("doe");
    p.doe_id = id;
    const t = DOE_TYPES.find((x) => x.label === p.doe_label) ?? DOE_TYPES[0];
    p2.does.unshift({
      id, study_id: sid, job_id: j.id, engine: p.engine === "native" ? "native" : "altair", status: "BUILDING", doe_label: t.label, doe_type: t.value, num_runs_requested: t.runs_editable ? Number(p.num_runs ?? t.default_runs) : null,
      options: (p.options as Record<string, unknown>) ?? {}, multi_execution: Number(p.multi_execution ?? 1), radioss_assem_source_path: String(p.radioss_assem_path ?? ""),
      run_count: null, sample_status: "PENDING", collected_count: 0, solve_failed_count: 0, has_run_responses: false,
      dir_display_path: p2.s.disp(sid, `01_train/doe/${id}`), results_display_path: p2.s.disp(sid, `01_train/results/${id}`), created_by_name: me.display_name, created_at: now,
      run_state_counts: { GENERATED: 0, SUBMITTED: 0, SOLVED: 0, SOLVE_FAILED: 0, COLLECTED: 0, COLLECT_FAILED: 0 },
    });
  }
}

/** ① 완료 처리. ① 작업이 아니면 undefined */
export function finishTrain(p2: Phase2Mock, j: Job): "done" | "waiting" | undefined {
  const p = j.params as Record<string, unknown>;
  const sid = j.study_id;
  switch (j.job_type) {
    case "TD_EXTRACT_PARAMS": {
      const native = p.engine === "native";
      const params = native ? nativeTrainParams() : trainParams().map((x) => ({ ...x }));
      const old = p2.setups[sid];
      const file = String(p.cad_path ?? "").split(/[\\/]/).pop() ?? "model.prt";
      p2.setups[sid] = {
        study_id: sid, engine: native ? "native" : "altair", cad: { source_path: String(p.cad_path), file_name: file, sha256: "…", display_path: p2.s.disp(sid, `01_train/cad/${file}`) },
        extract_job_id: j.id, parameters: params, used_count: params.filter((x) => x.use).length,
        tpl: old?.tpl ? { ...old.tpl, stale: true } : null, version: (old?.version ?? 0) + 1, updated_by_name: j.created_by_name, updated_at: new Date().toISOString(),
      };
      j.result = { param_count: params.length, valid_count: params.filter((x) => x.valid).length, cad_file_name: file };
      return "done";
    }
    case "TD_DOE_GEN": {
      const d = p2.does.find((x) => x.id === p.doe_id)!;
      const n = d.num_runs_requested ?? (DOE_TYPES.find((t) => t.label === d.doe_label)?.default_runs ?? 9);
      d.status = "READY";
      d.run_count = n;
      d.sample_status = "PARSED";
      const r = rng(n);
      p2.runs[d.id] = Array.from({ length: n }, (_, i) => ({ run_key: runKey(i + 1), state: "GENERATED" as TrainRunState, starter_name: "cushion_0000.rad", input_display_path: p2.s.disp(sid, `01_train/doe/${d.id}/approaches/doe_1/${runKey(i + 1)}/m_3`), hpc: null, result: null, updated_at: new Date().toISOString() }));
      p2.doeSamples[d.id] = p2.runs[d.id].map((x) => ({ run_key: x.run_key, values: { THK_TOP: Number((0.3 + r() * 0.9).toFixed(4)), THK_FOAM: Number((1 + r() * 2).toFixed(4)), RIB_H: 12, RIB_N: 2 + Math.floor(r() * 7) }, measured: {} }));
      j.result = { doe_id: d.id, run_count: n, sample_status: "PARSED", skipped_runs: [] };
      return "done";
    }
    case "TD_SOLVE": {
      const runs = targetRuns(p2, j);
      for (const r of runs) {
        r.state = "SUBMITTED";
        r._job = j.id;
        r.hpc = { external_job_id: p2.s.hpcMode === "scx" ? `scx-${p2.hpcSeq++}` : `${p2.hpcSeq++}.pbs01`, state: "QUEUED", attempt_no: (r.hpc?.attempt_no ?? 0) + 1 };
        delete (r as RunRec & { _scx?: unknown })._scx; // 새 시도 = 새 행·새 잡 폴더(§16.3)
        r.updated_at = new Date().toISOString();
      }
      j.steps = makeSteps("TD_SOLVE", 2, 2);
      j.progress_label = "PBS 대기";
      return "waiting";
    }
    case "TD_RESULT_IMPORT": {
      const runs = p2.runs[p.doe_id as string] ?? [];
      let n = 0;
      runs.forEach((r, i) => {
        if (i < Math.max(1, runs.length - 2)) {
          r.state = "COLLECTED";
          r.result = { h3d: 1, t01: 1, files: 4, total_bytes: 180_000_000 };
          n++;
        }
      });
      j.result = { matched: n, copied_files: n * 4, total_bytes: n * 180_000_000, unmatched_dirs: [], missing_runs: runs.filter((r) => r.state !== "COLLECTED").map((r) => r.run_key) };
      return "done";
    }
    case "TD_RESP_EXTRACT": {
      const d = p2.does.find((x) => x.id === p.doe_id);
      if (d) d.has_run_responses = true;
      return "done";
    }
    default:
      return undefined;
  }
}

function targetRuns(p2: Phase2Mock, j: Job): RunRec[] {
  const p = j.params as Record<string, unknown>;
  const runs = p2.runs[p.doe_id as string] ?? [];
  const keys = p.run_keys as string[] | null | undefined;
  if (keys && keys.length) return runs.filter((r) => keys.includes(r.run_key));
  return runs.filter((r) => r.state === "GENERATED" || r.state === "SOLVE_FAILED" || r.state === "COLLECT_FAILED");
}

/** 시간 1단계: TD_SOLVE PBS run 진행·취소·회수 */
export function tickSolve(p2: Phase2Mock) {
  for (const j of p2.s.jobs.filter((x) => x.job_type === "TD_SOLVE" && (x.state === "WAITING_HPC" || x.state === "COLLECTING"))) {
    const runs = (p2.runs[j.params.doe_id as string] ?? []).filter((r) => r._job === j.id);
    if (j.cancel_requested && p2.s.hpcCancelFails) {
      // C18: PBS 취소 명령 실패 → CANCEL_REQUESTED 유지, 작업은 WAITING_HPC + attention_code, 알림 1회
      runs.filter((r) => r.state === "SUBMITTED").forEach((r) => r.hpc && (r.hpc.state = "CANCEL_REQUESTED"));
      if (j.attention_code !== "HPC_CANCEL_FAILED") {
        j.attention_code = "HPC_CANCEL_FAILED";
        p2.s.notify(j.created_by, "HPC_CANCEL_FAILED", j, `PBS 취소 실패: PBS 해석 (${j.study_title}) — 자동 재시도 중`);
        p2.s.bump(j);
      }
      continue;
    }
    if (j.cancel_requested) {
      runs.filter((r) => r.state === "SUBMITTED").forEach((r) => (r.state = "SOLVE_FAILED"));
      j.state = "CANCELED";
      j.finished_at = new Date().toISOString();
      p2.s.bump(j);
      p2.s.notifyJob(j, "JOB_CANCELED");
      continue;
    }
    if (j.state === "WAITING_HPC") {
      const pending = runs.filter((r) => r.state === "SUBMITTED" && r.hpc?.state !== "UNKNOWN"); // §16.5 결과 모름은 사용자 조치까지 그대로
      pending.slice(0, 2).forEach((r, i) => {
        if (r.hpc?.state === "QUEUED") r.hpc.state = "RUNNING";
        else {
          r.state = i === 0 && r.run_key.endsWith("7") ? "SOLVE_FAILED" : "SOLVED";
          if (r.hpc) r.hpc.state = r.state === "SOLVED" ? "SUCCEEDED" : "FAILED";
        }
        r.updated_at = new Date().toISOString();
      });
      if (!runs.some((r) => r.state === "SUBMITTED")) {
        const solved = runs.filter((r) => r.state === "SOLVED").length;
        const failed = runs.filter((r) => r.state === "SOLVE_FAILED").length;
        if (!solved) {
          j.state = "FAILED";
          j.failure_code = "HPC_RUN_FAILED";
          j.failure_message = `PBS 해석 ${failed}개 모두 실패`;
          j.finished_at = new Date().toISOString();
          p2.s.notifyJob(j, "JOB_FAILED");
        } else {
          j.state = "COLLECTING";
          j.steps = makeSteps("TD_SOLVE", 3, 3);
          if (failed) {
            j.attention_code = "HPC_RUN_FAILED";
            j.warnings = [{ code: "HPC_PARTIAL_FAILED", message: `${runs.length}개 중 ${failed}개 실패` }];
            p2.s.notify(j.created_by, "HPC_PARTIAL_FAILED", j, `PBS 해석 일부 실패 — ${runs.length}개 중 ${failed}개 실패, 나머지 회수 진행`);
          }
        }
      }
    } else {
      const solved = runs.filter((r) => r.state === "SOLVED");
      solved.forEach((r) => {
        r.state = "COLLECTED";
        r.result = { h3d: 1, t01: 1, files: 4, total_bytes: 180_000_000 };
      });
      j.state = "SUCCEEDED";
      j.finished_at = new Date().toISOString();
      j.steps = makeSteps("TD_SOLVE", 5, null);
      j.progress_pct = 100;
      j.progress_label = null;
      const collected = runs.filter((r) => r.state === "COLLECTED").length;
      j.result = { submitted: runs.length, solved: collected, failed: runs.length - collected, collected };
      p2.s.notify(j.created_by, "HPC_COLLECTED", j, `PBS 결과 회수 완료 — ${runs.length}개 중 ${collected}개 회수`);
    }
    p2.s.bump(j);
  }
}
