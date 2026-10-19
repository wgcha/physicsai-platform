// 2차 ①(phase2.md §6) 학습 데이터: 파라미터·tpl·DOE·run 시드, DOE 출력, ① 라우트, 파라미터 표 저장.
import type { SampleRow, Study, TrainDoe, TrainParam, TrainRun, TrainRunState } from "../api/types";
import { iso, makeSteps, rng } from "./data";
import { DOE_TYPES, FEATURE_MISSING } from "./catalog";
import { err, ok, type MockResp, type Route } from "./route";
import type { Phase2Mock, SeedJob } from "./phase2";
import { addParamSetFromTrain } from "./stage4";
import { markUnknown } from "./scx";
import { doeResultTable } from "./trainDoe";

export const runKey = (i: number) => `run__${String(i).padStart(5, "0")}`;

export function trainParams(): TrainParam[] {
  const p = (name: string, raw: string, nominal: number | null, min: number | null, max: number | null, format: string, unit: string, use = true, valid = true, problems: string[] = []): TrainParam => ({
    name, raw_nominal: raw, nominal, min, max, use, format, unit, valid, problems,
  });
  return [
    p("THK_TOP", "0.6 mm", 0.6, 0.3, 1.2, "%.4f", "mm"),
    p("THK_FOAM", "2 mm", 2, 1, 3, "%.4f", "mm"),
    p("RIB_H", "12.5", 12.5, 11.875, 13.125, "%3i", "mm"),
    p("RIB_N", "4", 4, 2, 8, "%3i", ""),
    p("FILLET_R", "0.5 mm", 0.5, 0.475, 0.525, "%.4f", "mm", false),
    p("bad name", "x", null, null, null, "%3i", "", false, false, ["이름 형식이 맞지 않습니다", "숫자가 아닙니다"]),
  ];
}

export interface RunRec extends TrainRun {
  _job?: string;
}

/** ① 시드: setup·추출·DOE·run·샘플·PBS/결과 가져오기(원래 seed 순서 그대로) */
export function seedTrain(p2: Phase2Mock, J: SeedJob, sid: string): { doeId: string; runs: RunRec[] } {
  const params = trainParams();
  const used = params.filter((p) => p.use);
  p2.setups[sid] = {
    study_id: sid,
    cad: { source_path: "E:/shared/AI_WORK/cushion_v1/00_inbox/cad/cushion_parametric_modeling.prt", file_name: "cushion_parametric_modeling.prt", sha256: "9f2c…", display_path: p2.s.disp(sid, "01_train/cad/cushion_parametric_modeling.prt") },
    extract_job_id: "j-tx",
    parameters: params,
    used_count: used.length,
    tpl: {
      generated_at: iso(60 * 6), sha256: "41ab…", display_path: p2.s.disp(sid, "01_train/tpl/simlab_parametered_mesh.tpl"),
      params: used.map((p, i) => ({ var: `var_${i + 1}`, name: p.name, format: p.format })),
      warnings: [{ code: "TPL_INTEGER_FORMAT", message: "정수 형식(%3i)이라 HyperStudy 샘플 값이 정수로 반영됩니다: RIB_H" }],
      stale: false,
    },
    version: 4, updated_by_name: "김연구", updated_at: iso(60 * 6),
  };
  J({ id: "j-tx", job_type: "TD_EXTRACT_PARAMS", state: "SUCCEEDED", created_at: iso(60 * 7), params: { cad_path: p2.setups[sid].cad!.source_path }, result: { param_count: 6, valid_count: 5, cad_file_name: "cushion_parametric_modeling.prt" } });

  // DOE
  const doeId = "doe-1";
  J({ id: "j-doe", job_type: "TD_DOE_GEN", state: "SUCCEEDED", created_at: iso(60 * 5), params: { doe_id: doeId, doe_label: "LatinHyperCube", num_runs: 30, options: { RANDOM_SEED: 1, INCLUDE_NOMINAL: true }, multi_execution: 2, radioss_assem_path: "E:/shared/AI_WORK/cushion_v1/00_inbox/radioss_assem" }, result: { doe_id: doeId, run_count: 30, sample_status: "PARSED", skipped_runs: [] } });
  p2.does.push({
    id: doeId, study_id: sid, job_id: "j-doe", status: "READY", doe_label: "LatinHyperCube", doe_type: "TYPE_LATINHYPERCUBE", num_runs_requested: 30,
    options: { RANDOM_SEED: 1, INCLUDE_NOMINAL: true }, multi_execution: 2, generator: "hyperstudy", sampling: null, gen: null, radioss_assem_source_path: "E:/shared/AI_WORK/cushion_v1/00_inbox/radioss_assem",
    run_count: 30, sample_status: "PARSED", collected_count: 0, solve_failed_count: 0, has_run_responses: false,
    dir_display_path: p2.s.disp(sid, `01_train/doe/${doeId}`), results_display_path: p2.s.disp(sid, `01_train/results/${doeId}`),
    created_by_name: "김연구", created_at: iso(60 * 5),
    run_state_counts: { GENERATED: 0, SUBMITTED: 0, SOLVED: 0, SOLVE_FAILED: 0, COLLECTED: 0, COLLECT_FAILED: 0 },
  });
  const r = rng(7);
  const runs: RunRec[] = [];
  const samples: SampleRow[] = [];
  for (let i = 1; i <= 30; i++) {
    runs.push({ run_key: runKey(i), state: "GENERATED", starter_name: "cushion_0000.rad", input_display_path: p2.s.disp(sid, `01_train/doe/${doeId}/approaches/doe_1/${runKey(i)}/m_3`), hpc: null, result: null, updated_at: iso(60 * 5) });
    samples.push({ run_key: runKey(i), values: { THK_TOP: Number((0.3 + r() * 0.9).toFixed(4)), THK_FOAM: Number((1 + r() * 2).toFixed(4)), RIB_H: Math.round(11.875 + r() * 1.25), RIB_N: 2 + Math.floor(r() * 7) }, measured: {} });
  }
  p2.runs[doeId] = runs;
  p2.doeSamples[doeId] = samples;
  const collect = (rr: RunRec, i: number) => {
    rr.state = "COLLECTED";
    rr.result = { h3d: 1, t01: 1, files: 4, total_bytes: 180_000_000 + i * 1_300_000 };
    rr.updated_at = iso(60 * 3);
  };
  if (p2.s.hpcConfigured) {
    J({ id: "j-solve0", job_type: "TD_SOLVE", state: "SUCCEEDED", created_at: iso(60 * 4 + 30), params: { doe_id: doeId, run_keys: runs.slice(0, 24).map((x) => x.run_key), hpc: { queue: null, ncpus: null, walltime: null }, on_run_failure: "collect_partial" }, steps: makeSteps("TD_SOLVE", 5, null), result: { submitted: 24, solved: 24, failed: 0, collected: 24 } });
    runs.slice(0, 24).forEach((rr, i) => {
      collect(rr, i);
      rr.hpc = { external_job_id: `${12200 + i}.pbs01`, state: "SUCCEEDED", attempt_no: 1 };
      rr._job = "j-solve0";
    });
    const solve = J({ id: "j-solve", job_type: "TD_SOLVE", state: "WAITING_HPC", created_at: iso(38), started_at: iso(37), finished_at: null, params: { doe_id: doeId, run_keys: null, hpc: { queue: null, ncpus: null, walltime: null }, on_run_failure: "collect_partial" }, steps: makeSteps("TD_SOLVE", 2, 2), progress_pct: null, progress_label: "PBS 대기" });
    const states: [TrainRunState, string, number][] = [["SOLVED", "SUCCEEDED", 35], ["SOLVED", "SUCCEEDED", 31], ["SOLVE_FAILED", "FAILED", 28], ["SUBMITTED", "RUNNING", 36], ["SUBMITTED", "RUNNING", 36], ["SUBMITTED", "QUEUED", 36]];
    runs.slice(24).forEach((rr, i) => {
      rr.state = states[i][0];
      rr.hpc = { external_job_id: `${p2.hpcSeq++}.pbs01`, state: states[i][1], attempt_no: 1 };
      rr.updated_at = iso(states[i][2]);
      rr._job = solve.id;
    });
    if (p2.s.hpcMode === "scx") {
      runs.slice(24).forEach((rr) => rr.hpc?.external_job_id && (rr.hpc.external_job_id = `scx-${rr.hpc.external_job_id.split(".")[0]}`));
      if (p2.s.scxUnknown) markUnknown(p2.s, solve, runs[runs.length - 1]);
    }
  } else {
    J({ id: "j-ri", job_type: "TD_RESULT_IMPORT", state: "SUCCEEDED", created_at: iso(60 * 3 + 10), params: { doe_id: doeId, source_path: "E:/shared/AI_WORK/cushion_v1/00_inbox/pbs_results" }, result: { matched: 24, copied_files: 96, total_bytes: 4_400_000_000, unmatched_dirs: [], missing_runs: runs.slice(24).map((x) => x.run_key) } });
    runs.slice(0, 24).forEach(collect);
  }
  return { doeId, runs };
}

export function doeOut(p2: Phase2Mock, d: TrainDoe): TrainDoe {
  const runs = p2.runs[d.id] ?? [];
  const counts: Record<TrainRunState, number> = { GENERATED: 0, SUBMITTED: 0, SOLVED: 0, SOLVE_FAILED: 0, COLLECTED: 0, COLLECT_FAILED: 0 };
  for (const r of runs) counts[r.state]++;
  return { ...d, run_state_counts: counts, collected_count: counts.COLLECTED, solve_failed_count: counts.SOLVE_FAILED, run_count: d.status === "READY" ? runs.length : d.run_count };
}

/** ① 라우트: DOE 유형, DOE·run·샘플, Study ① 설정, 파라미터 표·tpl·① 결과 파라미터 세트 */
export const trainRoutes: Route = (srv, { method, path, seg, query, body }) => {
  const p2 = srv.p2;
  if (method === "GET" && path === "/train/doe-types") {
    if (p2.disabled.has("train_doe")) return err(409, "RESOURCE_NOT_CONFIGURED", "DOE 유형 파일이 설정되지 않았습니다.", { missing: ["resources.doe_design_type_json"] });
    return ok(DOE_TYPES);
  }
  if (seg[0] === "train-does" && seg[1]) {
    const d = p2.does.find((x) => x.id === seg[1]);
    if (!d) return err(404, "NOT_FOUND", "DOE를 찾을 수 없습니다.");
    if (method === "GET" && !seg[2]) return ok(doeOut(p2, d));
    if (method === "GET" && seg[2] === "runs") {
      let runs = p2.runs[d.id] ?? [];
      const st = query.get("state");
      if (st) runs = runs.filter((r) => r.state === st);
      const limit = Number(query.get("limit") ?? 200);
      const start = Number(query.get("cursor") ?? 0);
      const next = start + limit < runs.length ? String(start + limit) : null;
      return { status: 200, body: runs.slice(start, start + limit).map(({ _job: _j, ...r }) => r), headers: next ? { "X-Next-Cursor": next } : {} };
    }
    if (method === "GET" && seg[2] === "result-table") return doeResultTable(p2, d); // S14 §19.5
    if (method === "GET" && seg[2] === "samples") {
      const rows = p2.doeSamples[d.id];
      if (!rows) return err(404, "SAMPLES_MISSING", "샘플 표가 없습니다.");
      return ok({ columns: ["run_key", ...Object.keys(rows[0]?.values ?? {})], rows, next_cursor: null });
    }
  }
  if (seg[0] === "studies" && seg[1]) {
    const s = p2.s.studies.find((x) => x.id === seg[1]);
    if (!s) return null;
    const sub = seg.slice(2).join("/");
    if (method === "GET" && sub === "train") return ok(p2.setups[s.id] ?? { study_id: s.id, cad: null, extract_job_id: null, parameters: [], used_count: 0, tpl: null, version: 1, updated_by_name: null, updated_at: null });
    if (method === "GET" && sub === "train/does") return ok(p2.does.filter((d) => d.study_id === s.id).map((d) => doeOut(p2, d)));
    // 쓰기(power)
    const r = p2.s.role(s.project_id);
    const power = r === "power" || r === "admin";
    if (method === "PUT" && sub === "train/params") {
      if (!power) return err(403, "PERMISSION_DENIED", "실행 권한(power 이상)이 필요합니다.", { required: "power" });
      return saveParams(p2, s, body ?? {});
    }
    if (method === "POST" && sub === "train/tpl") {
      if (!power) return err(403, "PERMISSION_DENIED", "실행 권한(power 이상)이 필요합니다.", { required: "power" });
      const t = p2.setups[s.id];
      if (!t || !t.parameters.length) return err(409, "TRAIN_PARAMS_REQUIRED", "파라미터를 먼저 추출하세요.");
      if (p2.disabled.has("train_tpl")) return err(409, "RESOURCE_NOT_CONFIGURED", "tpl 템플릿이 설정되지 않았습니다.", { missing: FEATURE_MISSING.train_tpl });
      if (Number(body?.version) !== t.version) return err(409, "VERSION_CONFLICT", "다른 사용자가 먼저 바꿨습니다. 새로고침하세요.");
      const used = t.parameters.filter((p) => p.use);
      const warnings = used
        .filter((p) => /^%[-0-9.]*[id]$/.test(p.format) && [p.nominal, p.min, p.max].some((v) => v != null && !Number.isInteger(v)))
        .map((p) => ({ code: "TPL_INTEGER_FORMAT", message: `정수 형식(${p.format})이라 HyperStudy 샘플 값이 정수로 반영됩니다: ${p.name}` }));
      t.tpl = { generated_at: new Date().toISOString(), sha256: "77de…", display_path: p2.s.disp(s.id, "01_train/tpl/simlab_parametered_mesh.tpl"), params: used.map((p, i) => ({ var: `var_${i + 1}`, name: p.name, format: p.format })), warnings, stale: false };
      t.version++;
      return ok(t);
    }
    if (method === "POST" && sub === "param-sets/from-train") {
      if (!power) return err(403, "PERMISSION_DENIED", "실행 권한(power 이상)이 필요합니다.", { required: "power" });
      const d = p2.does.find((x) => x.id === body?.doe_id && x.study_id === s.id);
      if (!d || d.status !== "READY") return err(409, "DOE_NOT_READY", "준비된 DOE가 필요합니다.");
      if (d.sample_status !== "PARSED" && d.sample_status !== "PARTIAL") return err(409, "SAMPLES_MISSING", "DOE 샘플 표가 없습니다.");
      const runs = (p2.runs[d.id] ?? []).filter((x) => body?.runs === "all" || x.state === "COLLECTED");
      if (!runs.length) return err(409, "DOE_NOT_READY", "회수된 run이 없습니다.");
      const ps = addParamSetFromTrain(p2.s, s, d.id, runs.length);
      ps.label = String(body?.label ?? "").trim() || null;
      return { status: 201, body: ps };
    }
  }
  return null;
};

export function saveParams(p2: Phase2Mock, s: Study, body: Record<string, unknown>): MockResp {
  const t = p2.setups[s.id];
  if (!t || !t.parameters.length) return err(409, "TRAIN_PARAMS_REQUIRED", "파라미터를 먼저 추출하세요.");
  if (Number(body.version) !== t.version) return err(409, "VERSION_CONFLICT", "다른 사용자가 먼저 바꿨습니다. 새로고침하세요.");
  const rows = (body.parameters as { name: string; min: number | null; max: number | null; use: boolean; format?: string; unit?: string }[]) ?? [];
  const problems: { name: string; code: string; message: string }[] = [];
  const next = t.parameters.map((p) => {
    const r = rows.find((x) => x.name === p.name);
    if (!r) return p;
    const q = { ...p, min: r.min, max: r.max, use: r.use, format: r.format ?? p.format, unit: r.unit ?? p.unit };
    if (q.use) {
      if (!q.valid || q.nominal == null) problems.push({ name: q.name, code: "PARAM_INVALID", message: "사용할 수 없는 파라미터입니다" });
      else if (q.min == null || q.max == null || !(q.min < q.max)) problems.push({ name: q.name, code: "RANGE_INVALID", message: "하한 < 상한이어야 합니다" });
      else if (q.nominal < q.min || q.nominal > q.max) problems.push({ name: q.name, code: "NOMINAL_OUT_OF_RANGE", message: "공칭값이 범위 밖입니다" });
      if (!/^%[-0-9.]*[idfeEgG]$/.test(q.format)) problems.push({ name: q.name, code: "FORMAT_INVALID", message: "형식이 올바르지 않습니다" });
    }
    return q;
  });
  if (!next.some((p) => p.use)) problems.push({ name: "", code: "NO_PARAM_USED", message: "사용 파라미터가 1개 이상 필요합니다" });
  if (problems.length) return err(422, "TRAIN_PARAMS_INVALID", "파라미터 표를 확인하세요.", { problems });
  const usedNow = next.filter((p) => p.use);
  const tplNames = t.tpl?.params.map((x) => `${x.name}:${x.format}`).join(",");
  t.parameters = next;
  t.used_count = usedNow.length;
  if (t.tpl) t.tpl.stale = tplNames !== usedNow.map((x) => `${x.name}:${x.format}`).join(",") || t.tpl.stale;
  t.version++;
  t.updated_by_name = p2.s.me!.display_name;
  t.updated_at = new Date().toISOString();
  return ok(t);
}
