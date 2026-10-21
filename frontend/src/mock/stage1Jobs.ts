// 2차 ① 작업 훅: 사전 검사·DOE 행 생성·완료 처리·PBS run 진행(tick)·hpc_summary.
import type { HpcSummary, Job, JobType, Study, TrainRunState } from "../api/types";
import { makeSteps, rng } from "./data";
import { DOE_TYPES } from "./catalog";
import { err, type MockResp } from "./route";
import type { Phase2Mock } from "./phase2";
import { runKey, trainParams, type RunRec } from "./stage1";
import { mapGate, nativeTrainParams, seedFeatures } from "./geometry";
import { checkFilter, mockSummary, normalizeFilter, typeSelected } from "./extractFilter";
import { checkSampling, generatorOf, platformLabel } from "./doePlatform";
import { isPlatformKind } from "../lib/sampling";

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

/** ①-3 표본표 재사용(EQ-C1 4): 같은 Study READY DOE·파라미터 이름 집합 같음. 오류는 422 DOE_SAMPLING_INVALID(problems) */
function reuseCheck(p2: Phase2Mock, s: Study, sp: { doe_id?: string }, names: string[]): MockResp | null {
  const bad = (code: string, message: string) => err(422, "DOE_SAMPLING_INVALID", "표본을 만들 수 없습니다", { problems: [{ code, message }] });
  const src = p2.does.find((x) => x.id === sp.doe_id && x.study_id === s.id);
  if (!src) return bad("SOURCE_DOE_NOT_FOUND", "표본표를 재사용할 DOE를 이 Study에서 찾을 수 없습니다");
  const rows = p2.doeSamples[src.id] ?? [];
  if (src.status !== "READY" || !rows.length) return bad("SOURCE_DOE_NOT_READY", `DOE ${src.doe_label}의 표본표가 준비되지 않았습니다(READY·PARSED/PARTIAL 필요)`);
  const cols = Object.keys(rows[0].values);
  const extra = cols.filter((c) => !names.includes(c));
  const miss = names.filter((n) => !cols.includes(n));
  if (extra.length || miss.length) {
    const detail = [extra.length ? `원본 DOE에만: ${extra.join(", ")}` : "", miss.length ? `원본 DOE에 없음: ${miss.join(", ")}` : ""].filter(Boolean).join("; ");
    return bad("DOE_PARAM_MISMATCH", `파라미터 이름이 다릅니다(${detail})`);
  }
  return null;
}

/** native DOE(geometry-engine.md §7.3.3·§7.3.8 + S18 통합): LHS만, options 금지, 세트 기준이면 매칭표 확정 게이트 */
function precheckNativeDoe(p2: Phase2Mock, s: Study, params: Record<string, unknown>): MockResp | null {
  if (params.generator === "hyperstudy") return err(422, "INVALID_PARAMS", "Native 형상 엔진 DOE는 플랫폼 생성(LHS)만 됩니다");
  if (params.options && Object.keys(params.options as object).length) return err(422, "DOE_OPTIONS_INVALID", "Native DOE는 options를 쓸 수 없습니다(seed 사용)");
  const sp = params.sampling as { kind?: string; count?: number; doe_id?: string } | undefined;
  if (sp?.kind === "train_doe") {
    const ps0 = params.param_set_id ? p2.s.paramSets.find((x) => x.id === params.param_set_id && x.study_id === s.id) : null;
    const names = ps0 ? (ps0.parameters ?? []).map((x) => x.name) : (p2.setups[s.id]?.parameters ?? []).filter((x) => x.use).map((x) => x.name);
    const e = reuseCheck(p2, s, sp, names);
    if (e) return e;
  } else if (sp && sp.kind !== "lhs")
    return err(422, "DOE_SAMPLING_INVALID", "표본을 만들 수 없습니다", { problems: [{ code: "DESIGN_UNSUPPORTED", message: "Native 형상 엔진 DOE는 표본 방식 LHS만 지원합니다" }] });
  const n = sp?.kind === "train_doe" ? 2 : Number(sp ? sp.count : params.num_runs);
  if (!(n >= 2 && n <= 5000)) return err(422, "DOE_OPTIONS_INVALID", "run 수는 2~5000");
  if (params.param_set_id) {
    const ps = p2.s.paramSets.find((x) => x.id === params.param_set_id && x.study_id === s.id);
    if (!ps) return err(409, "PREREQUISITE_MISSING", "파라미터 세트를 찾을 수 없습니다", { missing: ["PARAM_SET"] });
    if (ps.engine !== "native") return err(409, "ENGINE_MISMATCH", "세트 기준 DOE는 Native 형상 엔진 세트에서만 만듭니다");
    if (ps.native?.prep_status !== "READY") return err(409, "GEOM_PREP_STALE", "형상 준비본이 오래되었습니다 — '형상 준비 다시'를 실행하세요");
    if (params.radioss_assem_path != null) return err(422, "INVALID_PARAMS", "세트 기준 DOE는 세트의 조립 폴더를 씁니다(radioss_assem_path 생략)");
    return mapGate(p2.s, ps.id);
  }
  if (!params.radioss_assem_path) return err(422, "INVALID_PARAMS", "조립 폴더 경로가 필요합니다");
  return null;
}

export function precheckTrain(p2: Phase2Mock, s: Study, type: JobType, params: Record<string, unknown>): MockResp | null {
  if (type === "TD_DOE_GEN" && (params.param_set_id || p2.setups[s.id]?.engine === "native")) {
    const e = precheckNativeDoe(p2, s, params);
    if (e) return e;
  } else if (type === "TD_DOE_GEN") {
    const t = p2.setups[s.id]?.tpl;
    if (!t) return err(409, "TPL_REQUIRED", "tpl을 먼저 생성하세요.");
    if (t.stale) return err(409, "TPL_STALE", "파라미터 표가 바뀌었습니다 — tpl을 다시 생성하세요.");
    // S18 §23.4: 플랫폼 표본 조합 검증(422 DOE_SAMPLING_INVALID + problems)
    if (generatorOf(params) === "platform" && (params.sampling as { kind?: string } | undefined)?.kind === "train_doe") {
      const e = reuseCheck(p2, s, params.sampling as { doe_id?: string }, (p2.setups[s.id]?.parameters ?? []).filter((x) => x.use).map((x) => x.name));
      if (e) return e;
    } else if (generatorOf(params) === "platform") {
      const c = checkSampling(p2.setups[s.id], (params.sampling ?? {}) as Record<string, unknown>);
      if (c.problems.length) return err(422, "DOE_SAMPLING_INVALID", "표본 설정을 확인하세요.", { problems: c.problems });
    }
  }
  if (type === "TD_EXTRACT_PARAMS" && params.extract_filter !== undefined) {
    // extract-filter.md §6.1: altair → 422 EXTRACT_FILTER_UNSUPPORTED, 잘못된 값 → 422 EXTRACT_FILTER_INVALID problems[{key,message}]
    const c = checkFilter(params.extract_filter, { native: params.engine === "native" });
    if ("status" in c) return c;
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
    const common = {
      id, study_id: sid, job_id: j.id, engine: (p.engine === "native" || p2.setups[sid]?.engine === "native" ? "native" : "altair") as "native" | "altair", status: "BUILDING" as const, radioss_assem_source_path: String(p.radioss_assem_path ?? ""),
      run_count: null, sample_status: "PENDING" as const, collected_count: 0, solve_failed_count: 0, has_run_responses: false,
      dir_display_path: p2.s.disp(sid, `01_train/doe/${id}`), results_display_path: p2.s.disp(sid, `01_train/results/${id}`), created_by_name: me.display_name, created_at: now,
      run_state_counts: { GENERATED: 0, SUBMITTED: 0, SOLVED: 0, SOLVE_FAILED: 0, COLLECTED: 0, COLLECT_FAILED: 0 },
    };
    if (common.engine === "native" || p.param_set_id) {
      // native(§7.3.3): 서버가 확정 기록하는 params(doe_type NATIVE_LHS·options {}·seed)
      const sp = p.sampling as { kind?: string; doe_id?: string; count?: number; seed?: number } | undefined;
      const reuseSrc = sp?.kind === "train_doe" ? p2.does.find((x) => x.id === sp.doe_id) : undefined;
      if (reuseSrc) p.reuse_doe_id = reuseSrc.id;
      const n = reuseSrc ? Number(reuseSrc.run_count ?? 0) : Number(sp?.count ?? p.num_runs);
      Object.assign(p, { engine: "native", generator: "platform", doe_label: reuseSrc ? "표본표 재사용(Native)" : "LHS(Native)", doe_type: "NATIVE_LHS", num_runs: n, default_runs: n, options: {}, seed: Number(sp?.seed ?? p.seed ?? 1), multi_execution: Number(p.multi_execution ?? 4), on_run_failure: p.on_run_failure ?? "continue" });
      delete p.sampling;
      p2.does.unshift({
        ...common, engine: "native", doe_label: reuseSrc ? "표본표 재사용(Native)" : "LHS(Native)", doe_type: "NATIVE_LHS", num_runs_requested: n, options: { seed: p.seed, ...(p.param_set_id ? { param_set_id: p.param_set_id } : {}) },
        multi_execution: Number(p.multi_execution), generator: "platform", sampling: null, gen: { total: n, pending: n, running: 0, done: 0, failed: 0 },
      });
      return;
    }
    if (generatorOf(p) === "platform" && (p.sampling as { kind?: string } | undefined)?.kind === "train_doe") {
      // EQ-C1 4: 표본표 재사용 — 원본 run 이름·값 그대로(워커 DG_PREP이 samples를 복사)
      const src = p2.does.find((x) => x.id === (p.sampling as { doe_id?: string }).doe_id)!;
      const n = Number(src.run_count ?? 0);
      Object.assign(p, { generator: "platform", doe_label: "표본표 재사용", doe_type: "TRAIN_DOE", num_runs: n, multi_execution: Number(p.multi_execution ?? 4), on_run_failure: p.on_run_failure ?? "fail", reuse_doe_id: src.id });
      p2.does.unshift({
        ...common, doe_label: "표본표 재사용", doe_type: "TRAIN_DOE", num_runs_requested: n, options: { doe_id: src.id },
        multi_execution: Number(p.multi_execution), generator: "platform", sampling: { kind: "train_doe", label: "표본표 재사용", desc_id: "td_train_doe", meta: { source_label: src.doe_label } }, gen: { total: n, pending: n, running: 0, done: 0, failed: 0 },
      });
      return;
    }
    if (generatorOf(p) === "platform") {
      // S18 §23.4 B8: 서버가 확정 기록하는 params + train_does 행(generator·doe_type = 방식 이름·options = kind를 뺀 입력·sampling·gen)
      const { kind: k0, ...input } = (p.sampling ?? {}) as Record<string, unknown>;
      const kind = isPlatformKind(String(k0)) ? (String(k0) as Parameters<typeof platformLabel>[0]) : "lhs_opt";
      const chk = checkSampling(p2.setups[sid], { kind, ...input });
      const n = chk.runs ?? 0;
      const label = platformLabel(kind);
      p.generator = "platform";
      p.doe_label = label;
      p.doe_type = kind.toUpperCase();
      p.num_runs = n;
      p.multi_execution = Number(p.multi_execution ?? 4);
      p.on_run_failure = p.on_run_failure ?? "fail";
      if (chk.notes.length) j.warnings = chk.notes.map((x) => ({ code: x.code, message: x.message }));
      p2.does.unshift({
        ...common, doe_label: label, doe_type: kind.toUpperCase(), num_runs_requested: n, options: input, multi_execution: Number(p.multi_execution),
        generator: "platform", sampling: { kind, label, desc_id: `td_${kind}`, meta: null }, gen: { total: n, pending: n, running: 0, done: 0, failed: 0 },
      });
      return;
    }
    const t = DOE_TYPES.find((x) => x.label === p.doe_label) ?? DOE_TYPES[0];
    p2.does.unshift({
      ...common, doe_label: t.label, doe_type: t.value, num_runs_requested: t.runs_editable ? Number(p.num_runs ?? t.default_runs) : null,
      options: (p.options as Record<string, unknown>) ?? {}, multi_execution: Number(p.multi_execution ?? 1), generator: "hyperstudy", sampling: null, gen: null,
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
      // native: 선택한 그룹의 종류만(extract-filter.md §5) — 정규화본을 train_setups.extract_filter로 기록하고 요약을 붙인다
      const norm = native && p.extract_filter != null ? normalizeFilter(p.extract_filter).norm : null;
      const kinds = new Map(seedFeatures().map((f) => [f.name, f.type]));
      const params = native ? nativeTrainParams().filter((x) => typeSelected(kinds.get(x.name), norm)) : trainParams().map((x) => ({ ...x }));
      const old = p2.setups[sid];
      const file = String(p.cad_path ?? "").split(/[\\/]/).pop() ?? "model.prt";
      p2.setups[sid] = {
        study_id: sid, engine: native ? "native" : "altair", cad: { source_path: String(p.cad_path), file_name: file, sha256: "…", display_path: p2.s.disp(sid, `01_train/cad/${file}`) },
        extract_job_id: j.id, parameters: params, used_count: params.filter((x) => x.use).length,
        tpl: old?.tpl ? { ...old.tpl, stale: true } : null, version: (old?.version ?? 0) + 1, updated_by_name: j.created_by_name, updated_at: new Date().toISOString(),
        extract_filter: norm, extract_summary: native ? mockSummary(params.map((x) => ({ type: kinds.get(x.name) ?? "" })), norm) : null,
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
      const reuseRows = p.reuse_doe_id ? p2.doeSamples[String(p.reuse_doe_id)] : undefined;
      p2.doeSamples[d.id] = reuseRows ? reuseRows.map((x) => ({ ...x, values: { ...x.values }, measured: {} })) : p2.runs[d.id].map((x) => ({ run_key: x.run_key, values: { THK_TOP: Number((0.3 + r() * 0.9).toFixed(4)), THK_FOAM: Number((1 + r() * 2).toFixed(4)), RIB_H: 12, RIB_N: 2 + Math.floor(r() * 7) }, measured: {} }));
      if (d.engine === "native") {
        // native: 형상 생성 실패 run은 SKIPPED.json → skipped_runs[{run_key, reason, category, message}], run 목록에서 빠진다
        const skipped = !p.reuse_doe_id && n >= 6 ? [{ run_key: runKey(n), reason: "GEOM_QUALITY", category: "QUALITY", message: "min stretch 0.06 < 기준 0.1" }] : [];
        p2.runs[d.id] = p2.runs[d.id].filter((x) => !skipped.some((k) => k.run_key === x.run_key));
        d.run_count = p2.runs[d.id].length;
        d.gen = { total: n, pending: 0, running: 0, done: n - skipped.length, failed: skipped.length };
        j.result = { doe_id: d.id, run_count: d.run_count, sample_status: "PARSED", skipped_runs: skipped, gen_ok: n - skipped.length, gen_skipped: skipped.length };
        return "done";
      }
      if (d.generator === "platform") {
        // S18: run별 생성 상태 집계(전부 완료)·표본 meta(§20.5 — 목은 run 수만)
        d.gen = { total: n, pending: 0, running: 0, done: n, failed: 0 };
        if (d.sampling) d.sampling.meta = { count: n, ...d.options };
        j.result = { doe_id: d.id, run_count: n, sample_status: "PARSED", skipped_runs: [], gen_done: n, gen_failed: [], multi_execution: d.multi_execution };
        return "done";
      }
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
