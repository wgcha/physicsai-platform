// 2차(phase2.md §12) 목 서버 부분. MockServer가 위임한다. 백엔드 openapi.json이 갱신되기 전까지 계약 문서 기준.
import type {
  Curation,
  CurationFile,
  CurationSourceRef,
  DoeType,
  EnvCheck,
  EnvCheckItem,
  FeatureKey,
  FeatureState,
  HpcSummary,
  Job,
  JobType,
  OptResponse,
  Optimization,
  SampleRow,
  SpdmImport,
  Study,
  TrainDoe,
  TrainParam,
  TrainRun,
  TrainRunState,
  TrainSetup,
} from "../api/types";
import { baseJob, iso, makeSteps, rng } from "./data";
import type { MockResp, MockServer } from "./server";

const err = (status: number, code: string, message: string, extra: Record<string, unknown> = {}): MockResp => ({
  status,
  body: { detail: { code, message, ...extra } },
});
const ok = (body: unknown, status = 200): MockResp => ({ status, body });

export const STAGE_LABEL: Record<JobType, string> = {
  DATASET_CREATE: "③-1",
  PACKAGE_EXPORT: "③-2",
  MODEL_REGISTER: "③-4",
  EVALUATE: "③-5",
  PREDICT: "④",
  PREDICT_VERIFY: "④",
  TD_EXTRACT_PARAMS: "①-1",
  TD_DOE_GEN: "①-3",
  TD_SOLVE: "①-4",
  TD_RESULT_IMPORT: "①-5",
  TD_RESP_EXTRACT: "①-6",
  SPDM_IMPORT: "②-0",
  CU_H3D_PREVIEW: "②-1",
  CU_H3D_CURATE: "②-2",
  CU_T01_PREVIEW: "②-3",
  CU_T01_CURVES: "②-4",
  OPTIMIZE: "⑤",
};

/** 기능 → 비활성일 때 missing 키(phase2.md §12.1) */
export const FEATURE_MISSING: Record<FeatureKey, string[]> = {
  train_extract: ["resources.pyd_dir", "commands.simlab_extract_params"],
  train_tpl: ["resources.simlab_tpl_template"],
  train_doe: ["resources.doe_design_type_json", "resources.hypermesh_include_tcl", "resources.launchers.gen_radioss"],
  train_solve: ["hpc.mode"],
  train_import: ["hpc.transfer.collect_patterns"],
  train_resp: ["commands.response_extract"],
  curation_h3d: ["resources.preview_h3d_tcl", "altair.hvtrans_exe_path"],
  curation_t01: ["resources.preview_hg_tcl", "resources.curate_hg_tcl"],
  spdm_import: ["storage.spdm_roots"],
  optimize: ["resources.extract_minmax_tcl", "resources.launchers.optimization", "altair.hstpy_path"],
  dataset_create: ["altair.edspy_path"],
  evaluate: ["altair.edspy_path"],
  predict: ["altair.edspy_path", "commands.geom_update"],
};
export const ALL_FEATURES = Object.keys(FEATURE_MISSING) as FeatureKey[];

const FEATURE_OF: Partial<Record<JobType, FeatureKey>> = {
  DATASET_CREATE: "dataset_create",
  EVALUATE: "evaluate",
  PREDICT: "predict",
  TD_EXTRACT_PARAMS: "train_extract",
  TD_DOE_GEN: "train_doe",
  TD_SOLVE: "train_solve",
  TD_RESULT_IMPORT: "train_import",
  TD_RESP_EXTRACT: "train_resp",
  CU_H3D_PREVIEW: "curation_h3d",
  CU_H3D_CURATE: "curation_h3d",
  CU_T01_PREVIEW: "curation_t01",
  CU_T01_CURVES: "curation_t01",
  SPDM_IMPORT: "spdm_import",
  OPTIMIZE: "optimize",
};

export const DOE_TYPES: DoeType[] = [
  {
    label: "LatinHyperCube", value: "TYPE_LATINHYPERCUBE", default_runs: 30, runs_editable: true,
    fields: [
      { key: "RANDOM_SEED", label: "Random Seed", type: "int", default: 1, min: 1, max: 99999 },
      { key: "INCLUDE_NOMINAL", label: "Nominal run 포함", type: "bool", default: true },
    ],
  },
  { label: "Hammersley", value: "TYPE_HAMMERSLEY", default_runs: 30, runs_editable: true, fields: [] },
  {
    label: "FullFactorial", value: "TYPE_FULLFACT", default_runs: 9, runs_editable: false,
    fields: [{ key: "LEVELS", label: "Levels", type: "combo", items: ["2", "3"], default: "3" }],
  },
];

const H3D_INFO: Record<string, string[]> = {
  Stress: ["vonMises", "P1 (major)", "Max Abs Principal"],
  Displacement: ["X", "Y", "Z", "Mag"],
  "Plastic Strain": ["Plastic Strain"],
  "Element Energy": ["Total Energy Density", "Extreme Value"],
};

/** 원본 to_cfg_datacomp(GUI:711-734) 사용 가능 판정: 1~2단어, Extreme 시작 제외 */
export function usableComponent(c: string): boolean {
  const w = c.trim().split(/\s+/);
  return !c.startsWith("Extreme") && w.length >= 1 && w.length <= 2;
}

const T01_PREVIEW = {
  dataTypes: [
    { name: "Rigid Body", requests: [{ name: "RBODY 1", components: ["F-Mag", "F-X", "F-Y", "F-Z"] }, { name: "RBODY 2", components: ["F-Mag", "M-Mag"] }] },
    { name: "Nodal", requests: [{ name: "Node 100", components: ["DX", "DY", "DZ"] }] },
  ],
};

const runKey = (i: number) => `run__${String(i).padStart(5, "0")}`;

function trainParams(): TrainParam[] {
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

function envItems(variant: number, pendingWorker = false): EnvCheckItem[] {
  const it = (key: string, category: EnvCheckItem["category"], label: string, status: EnvCheckItem["status"], message: string, source: "API" | "WORKER", detail: Record<string, unknown> | null = null): EnvCheckItem => ({
    key, category, label, status, message, source, detail,
  });
  const api: EnvCheckItem[] = [
    it("config.valid", "CONFIG", "설정 검증", "OK", "설정 오류 없음", "API"),
    it("db.connection", "DATABASE", "DB 연결", "OK", "SELECT 1 성공", "API", { latency_ms: 3 }),
    it("db.migration_head", "DATABASE", "마이그레이션 버전", "OK", "0002_phase2", "API", { current: "0002_phase2", head: "0002_phase2" }),
    it("auth.dashboard", "AUTH", "대시보드 인증", "OK", "introspection 200", "API", { latency_ms: 41 }),
    it("auth.projects", "AUTH", "대시보드 프로젝트", "OK", "프로젝트 3개", "API", { count: 3 }),
    it("hpc.gateway", "HPC", "PBS 연결", "WARN", "PBS 연결 안 됨", "API", { mode: "none" }),
    it("worker.heartbeat", "WORKER", "워커 heartbeat", "OK", "PHYSICS-PC:4412 · 4초 전", "API", { worker_id: "PHYSICS-PC:4412", age_s: 4, limiter: "windows_job" }),
  ];
  const W = (key: string, category: EnvCheckItem["category"], label: string, status: EnvCheckItem["status"], message: string, detail: Record<string, unknown> | null = null) =>
    pendingWorker ? it(key, category, label, "PENDING", "대기 중", "WORKER") : it(key, category, label, status, message, "WORKER", detail);
  const worker: EnvCheckItem[] = [
    W("altair.hyperstudy_path", "EXECUTABLE", "HyperStudy", "OK", "D:/Altair/2025/hwdesktop/hst/bin/win64/hstbatch.exe", { size: 512000, mtime: "2025-11-02T10:00:00Z" }),
    W("altair.simlab_path", "EXECUTABLE", "SimLab", "OK", "D:/Altair/2025/SimLab/SimLab.bat"),
    W("altair.edspy_path", "EXECUTABLE", "edspy", "OK", "D:/Altair/2025/PhysicsAI/edspy.exe"),
    W("altair.hw_exe_path", "EXECUTABLE", "HyperWorks", "OK", "D:/Altair/2025/hwdesktop/hw/bin/win64/hw.exe"),
    W("altair.hvtrans_exe_path", "EXECUTABLE", "hvtrans", variant ? "FAIL" : "OK", variant ? "파일이 없습니다: D:/Altair/2025/hwdesktop/io/hvtrans.exe" : "D:/Altair/2025/hwdesktop/io/hvtrans.exe"),
    W("altair.hstpy_path", "EXECUTABLE", "hstpy", "OK", "hstbatch 폴더에서 파생: hstpy.bat"),
    W("probe.edspy", "EXECUTABLE", "edspy 실행 시험", "SKIP", "존재 확인만(인자 미확인)"),
    W("resource.pyd_dir", "RESOURCE", "pyd 폴더", variant ? "FAIL" : "OK", variant ? "hst_gen_radioss_core*.pyd가 정확히 1개가 아닙니다: 0개" : "pyd 3개"),
    W("resource.preview_h3d_tcl", "RESOURCE", "h3d 미리보기 TCL", "OK", "BATCHRUN_preview_h3d.tcl"),
    W("resource.extract_minmax_tcl", "RESOURCE", "MinMax TCL", "WARN", "미설정(해당 기능 비활성)"),
    W("storage.ai_root.write", "STORAGE", "AI 루트 쓰기", "OK", "쓰기 시험 성공"),
    W("storage.ai_root.free", "STORAGE", "AI 루트 여유 공간", "OK", "여유 1.8 TB", { free_gb: 1843 }),
    W("storage.roots_overlap", "STORAGE", "루트 겹침", "OK", "겹침 없음"),
    W("storage.spdm_roots", "STORAGE", "SPDM 루트", "OK", "\\\\spdm\\master 읽기 가능"),
    W("worker.limiter", "WORKER", "자원 제한기", "OK", "windows_job · CPU 상한 적용", { name: "windows_job", cpu_cap_enforced: true }),
    W("worker.job_object", "WORKER", "Job Object 자체 시험", "OK", "CPU 50% · 64GB · below_normal", { cpu_rate: 5000, memory_gb: 64, priority: "below_normal" }),
    W("gpu.detect", "GPU", "GPU", "OK", "NVIDIA RTX A6000 (49152 MB)", { gpus: [{ name: "NVIDIA RTX A6000", memory_total_mb: 49152 }] }),
  ];
  return [...api, ...worker];
}

function summarize(items: EnvCheckItem[]) {
  const s = { ok: 0, warn: 0, fail: 0, skip: 0 };
  for (const i of items) {
    if (i.status === "OK") s.ok++;
    else if (i.status === "WARN") s.warn++;
    else if (i.status === "FAIL") s.fail++;
    else if (i.status === "SKIP") s.skip++;
  }
  return s;
}

function optSummary(seed: number, n: number) {
  const r = rng(seed);
  const rows: (number | string)[][] = [];
  let best = 240;
  for (let i = 1; i <= n; i++) {
    const t = 0.3 + r() * 0.9;
    const f = 1 + r() * 2;
    const vm = Math.max(118, best - r() * 18 + (r() - 0.6) * 22);
    best = Math.min(best, vm + 6);
    const dx = 2.4 + r() * 3.4;
    rows.push([i, Number(t.toFixed(4)), Number(f.toFixed(4)), Math.round(11.9 + r() * 1.2), 2 + Math.floor(r() * 7), Number(vm.toFixed(2)), Number(dx.toFixed(3)), dx <= 5 ? "Yes" : "No"]);
  }
  return { columns: ["Design", "THK_TOP", "THK_FOAM", "RIB_H", "RIB_N", "MAX_VM", "DISP_X", "Feasible"], rows };
}

/** ⑤ summary.json(C14 csv_table): rows는 문자열 배열 */
function summaryJson(t: { columns: string[]; rows: (number | string)[][] }, fileRel: string) {
  return { parser: "hst_csv", kind: "csv_table", file_rel: fileRel, columns: t.columns, rows: t.rows.map((r) => r.map(String)) };
}

function curveSeries() {
  const x: number[] = [];
  const y: number[] = [];
  for (let i = 0; i <= 50; i++) {
    x.push(Number((i * 0.0002).toFixed(4)));
    y.push(Number((1850 * Math.sin((i / 50) * Math.PI) * (1 - Math.exp(-i / 6))).toFixed(1)));
  }
  return { series: [{ name: "RBODY 1 F-Mag [N]", x, y }] };
}

interface RunRec extends TrainRun {
  _job?: string;
}

export class Phase2Mock {
  s: MockServer;
  disabled: Set<FeatureKey>;
  spdmEnabled: boolean;
  setups: Record<string, TrainSetup> = {};
  does: TrainDoe[] = [];
  runs: Record<string, RunRec[]> = {};
  doeSamples: Record<string, SampleRow[]> = {};
  imports: SpdmImport[] = [];
  curations: Curation[] = [];
  curationFiles: Record<string, CurationFile[]> = {};
  opts: Optimization[] = [];
  envChecks: EnvCheck[] = [];
  hpcSeq = 12345;

  constructor(server: MockServer, disabled: FeatureKey[] = ["train_resp"]) {
    this.s = server;
    this.disabled = new Set(disabled);
    this.spdmEnabled = !this.disabled.has("spdm_import");
    this.seed();
  }

  feature(k: FeatureKey): FeatureState {
    if (k === "train_solve" && !this.s.hpcConfigured) return { enabled: false, missing: ["hpc.mode"] };
    return this.disabled.has(k) ? { enabled: false, missing: FEATURE_MISSING[k] } : { enabled: true, missing: [] };
  }

  // ---------------- seed ----------------
  private seed() {
    const sid = "s-cushion";
    const st = "쿠션 두께·리브 예측";
    const params = trainParams();
    const used = params.filter((p) => p.use);
    this.setups[sid] = {
      study_id: sid,
      cad: { source_path: "E:/shared/AI_WORK/cushion_v1/00_inbox/cad/cushion_parametric_modeling.prt", file_name: "cushion_parametric_modeling.prt", sha256: "9f2c…", display_path: this.s.disp(sid, "01_train/cad/cushion_parametric_modeling.prt") },
      extract_job_id: "j-tx",
      parameters: params,
      used_count: used.length,
      tpl: {
        generated_at: iso(60 * 6), sha256: "41ab…", display_path: this.s.disp(sid, "01_train/tpl/simlab_parametered_mesh.tpl"),
        params: used.map((p, i) => ({ var: `var_${i + 1}`, name: p.name, format: p.format })),
        warnings: [{ code: "TPL_INTEGER_FORMAT", message: "정수 형식(%3i)이라 HyperStudy 샘플 값이 정수로 반영됩니다: RIB_H" }],
        stale: false,
      },
      version: 4, updated_by_name: "김연구", updated_at: iso(60 * 6),
    };
    const J = (p: Partial<Job> & Pick<Job, "id" | "job_type" | "state">) => {
      const done = p.state === "SUCCEEDED";
      const j = baseJob({
        study_id: sid, project_id: "p-cushion", study_title: st, created_at: iso(60 * 8), started_at: iso(60 * 8 - 1), finished_at: done ? iso(60 * 8 - 3) : null,
        progress_pct: done ? 100 : null, ...p,
        steps: p.steps ?? makeSteps(p.job_type, done ? 3 : 0, null),
      });
      this.s.jobs.push(j);
      return j;
    };
    J({ id: "j-tx", job_type: "TD_EXTRACT_PARAMS", state: "SUCCEEDED", created_at: iso(60 * 7), params: { cad_path: this.setups[sid].cad!.source_path }, result: { param_count: 6, valid_count: 5, cad_file_name: "cushion_parametric_modeling.prt" } });

    // DOE
    const doeId = "doe-1";
    J({ id: "j-doe", job_type: "TD_DOE_GEN", state: "SUCCEEDED", created_at: iso(60 * 5), params: { doe_id: doeId, doe_label: "LatinHyperCube", num_runs: 30, options: { RANDOM_SEED: 1, INCLUDE_NOMINAL: true }, multi_execution: 2, radioss_assem_path: "E:/shared/AI_WORK/cushion_v1/00_inbox/radioss_assem" }, result: { doe_id: doeId, run_count: 30, sample_status: "PARSED", skipped_runs: [] } });
    this.does.push({
      id: doeId, study_id: sid, job_id: "j-doe", status: "READY", doe_label: "LatinHyperCube", doe_type: "TYPE_LATINHYPERCUBE", num_runs_requested: 30,
      options: { RANDOM_SEED: 1, INCLUDE_NOMINAL: true }, multi_execution: 2, radioss_assem_source_path: "E:/shared/AI_WORK/cushion_v1/00_inbox/radioss_assem",
      run_count: 30, sample_status: "PARSED", collected_count: 0, solve_failed_count: 0, has_run_responses: false,
      dir_display_path: this.s.disp(sid, `01_train/doe/${doeId}`), results_display_path: this.s.disp(sid, `01_train/results/${doeId}`),
      created_by_name: "김연구", created_at: iso(60 * 5),
      run_state_counts: { GENERATED: 0, SUBMITTED: 0, SOLVED: 0, SOLVE_FAILED: 0, COLLECTED: 0, COLLECT_FAILED: 0 },
    });
    const r = rng(7);
    const runs: RunRec[] = [];
    const samples: SampleRow[] = [];
    for (let i = 1; i <= 30; i++) {
      runs.push({ run_key: runKey(i), state: "GENERATED", starter_name: "cushion_0000.rad", input_display_path: this.s.disp(sid, `01_train/doe/${doeId}/approaches/doe_1/${runKey(i)}/m_3`), hpc: null, result: null, updated_at: iso(60 * 5) });
      samples.push({ run_key: runKey(i), values: { THK_TOP: Number((0.3 + r() * 0.9).toFixed(4)), THK_FOAM: Number((1 + r() * 2).toFixed(4)), RIB_H: Math.round(11.875 + r() * 1.25), RIB_N: 2 + Math.floor(r() * 7) }, measured: {} });
    }
    this.runs[doeId] = runs;
    this.doeSamples[doeId] = samples;
    const collect = (rr: RunRec, i: number) => {
      rr.state = "COLLECTED";
      rr.result = { h3d: 1, t01: 1, files: 4, total_bytes: 180_000_000 + i * 1_300_000 };
      rr.updated_at = iso(60 * 3);
    };
    if (this.s.hpcConfigured) {
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
        rr.hpc = { external_job_id: `${this.hpcSeq++}.pbs01`, state: states[i][1], attempt_no: 1 };
        rr.updated_at = iso(states[i][2]);
        rr._job = solve.id;
      });
    } else {
      J({ id: "j-ri", job_type: "TD_RESULT_IMPORT", state: "SUCCEEDED", created_at: iso(60 * 3 + 10), params: { doe_id: doeId, source_path: "E:/shared/AI_WORK/cushion_v1/00_inbox/pbs_results" }, result: { matched: 24, copied_files: 96, total_bytes: 4_400_000_000, unmatched_dirs: [], missing_runs: runs.slice(24).map((x) => x.run_key) } });
      runs.slice(0, 24).forEach(collect);
    }

    // SPDM 가져오기
    this.imports.push({
      id: "imp-1", study_id: sid, job_id: "j-spdm", status: "READY", spdm_path: "\\\\spdm\\master\\FD-X\\Case_0012\\Scene 03", file_count: 48, total_bytes: 9_800_000_000, renamed_count: 2,
      dest_display_path: this.s.disp(sid, "02_import/imp-1"), created_by_name: "김연구", created_at: iso(60 * 2 + 40),
    });
    J({ id: "j-spdm", job_type: "SPDM_IMPORT", state: "SUCCEEDED", created_at: iso(60 * 2 + 40), params: { spdm_path: "\\\\spdm\\master\\FD-X\\Case_0012\\Scene 03" } });

    // ② 미리보기·큐레이션
    const src: CurationSourceRef = { kind: "TRAIN_DOE", doe_id: doeId };
    J({ id: "j-h3dprev", job_type: "CU_H3D_PREVIEW", state: "SUCCEEDED", created_at: iso(60 * 2 + 20), params: { source: src, sample_file: null } });
    this.previewArtifacts("j-h3dprev", sid, src);
    J({ id: "j-cur1", job_type: "CU_H3D_CURATE", state: "SUCCEEDED", created_at: iso(60 * 2), params: { source: src, preview_job_id: "j-h3dprev", selection: { items: [{ datatype: "Stress", component: "vonMises" }], parts: { shell: [1, 2], solid: [], rbody: [] }, time_increment: 2 }, exclude_files: [] }, warnings: [{ code: "PARTIAL_OUTPUT", message: "24개 중 1개 실패" }] });
    this.curations.push({
      id: "cur-1", study_id: sid, job_id: "j-cur1", kind: "H3D", status: "READY", source: src, source_label: "① DOE doe-1 · LatinHyperCube 30", preview_job_id: "j-h3dprev",
      selection: { items: [{ datatype: "Stress", component: "vonMises" }], parts: { shell: [1, 2], solid: [], rbody: [] }, time_increment: 2, time_steps_count: 21 },
      target_count: 24, ok_count: 23, failed_count: 1, missing_runs: runs.slice(24).map((x) => x.run_key),
      output_display_path: this.s.disp(sid, "02_curated/cur-1/CURATED_DATA"), used_by_dataset_ids: [], created_by_name: "김연구", created_at: iso(60 * 2),
    });
    this.curationFiles["cur-1"] = runs.slice(0, 24).map((rr, i) => ({
      run_folder: rr.run_key, run_key: rr.run_key, input_name: "cushion_0000.h3d", output_name: i === 16 ? null : "cushion_0000.h3d", size: i === 16 ? null : 38_000_000 + i * 120_000, ok: i !== 16, exit_code: i === 16 ? 1 : 0,
    }));
    J({ id: "j-t01prev", job_type: "CU_T01_PREVIEW", state: "SUCCEEDED", created_at: iso(60 + 50), params: { source: src, sample_file: null } });
    this.s.addArtifact("j-t01prev", sid, "PREVIEW_JSON", "02_preview/j-t01prev/PREVIEW_T01.json", "application/json", JSON.stringify(T01_PREVIEW));
    J({ id: "j-cur2", job_type: "CU_T01_CURVES", state: "SUCCEEDED", created_at: iso(60 + 40), params: { source: src, curves: [{ type: "Rigid Body", request: "RBODY 1", component: "F-Mag" }], exclude_files: [] } });
    this.curations.push({
      id: "cur-2", study_id: sid, job_id: "j-cur2", kind: "T01", status: "READY", source: src, source_label: "① DOE doe-1 · LatinHyperCube 30", preview_job_id: null,
      selection: { curves: [{ type: "Rigid Body", request: "RBODY 1", component: "F-Mag" }] }, target_count: 24, ok_count: 24, failed_count: 0, missing_runs: [],
      output_display_path: this.s.disp(sid, "02_curated/cur-2/CURVES"), used_by_dataset_ids: [], created_by_name: "김연구", created_at: iso(60 + 40),
    });
    this.s.addArtifact("j-cur2", sid, "CURVE_JSON", "02_curated/cur-2/CURVES/run__00001/cushion_0000_curves.json", "application/json", JSON.stringify(curveSeries()));

    // ⑤ 최적화
    const responses: OptResponse[] = [
      { name: "MAX_VM", source: "H3D", subcase: 1, datatype: "Stress", component: "vonMises", layer: "", stat: "MAX", goal: "MINIMIZE" },
      { name: "DISP_X", source: "XYDATA", request: "Node 100", component: "X", stat: "ABSMAX", goal: "CONSTRAINT", bound: "<=", value: 5 },
    ];
    J({ id: "j-opt", job_type: "OPTIMIZE", state: "SUCCEEDED", created_at: iso(60 + 10), started_at: iso(60 + 9), finished_at: iso(22), params: { approach: "OPT", opt_method: "ARSM", max_designs: 25, run_nominal: true, study_folder: "HST_PHYSICSAI_OPTIMIZATION", responses }, result: { runs_started: 25, log_error_lines: 0 } });
    const summary = optSummary(3, 25);
    const sumId = this.s.addArtifact("j-opt", sid, "OPT_SUMMARY", "05_opt/j-opt/summary.json", "application/json", JSON.stringify(summaryJson(summary, "HST_PHYSICSAI_OPTIMIZATION/approaches/opt_1/opt_summary.csv")));
    const csv = [summary.columns.join(","), ...summary.rows.map((r) => r.join(","))].join("\n") + "\n";
    this.s.addArtifact("j-opt", sid, "OPT_FILE", "05_opt/j-opt/HST_PHYSICSAI_OPTIMIZATION/approaches/opt_1/opt_summary.csv", "text/csv", csv);
    this.s.addArtifact("j-opt", sid, "OPT_FILE", "05_opt/j-opt/HST_PHYSICSAI_OPTIMIZATION/run_log.txt", "text/plain", "HyperStudy optimization log (목)\nStarted run (1), model (m_1)\n…\nStarted run (25), model (m_1)\nFinished.\n");
    const fl = this.s.addArtifact("j-opt", sid, "FILE_LIST", "05_opt/j-opt/file_list.json", "application/json", JSON.stringify({
      root: "HST_PHYSICSAI_OPTIMIZATION",
      truncated: false,
      files: [
        { rel: "HST_PHYSICSAI_OPTIMIZATION/approaches/opt_1/opt_summary.csv", size: csv.length },
        { rel: "HST_PHYSICSAI_OPTIMIZATION/run_log.txt", size: 2140 },
        { rel: "HST_PHYSICSAI_OPTIMIZATION/approaches/opt_1/study.hstx", size: 912_400 },
        { rel: "HST_PHYSICSAI_OPTIMIZATION/approaches/opt_1/run__00001/m_1/cushion_0000_pred.h3d", size: 41_200_000 },
      ],
    }));
    this.opts.push({
      id: "opt-1", study_id: sid, job_id: "j-opt", status: "DONE", approach: "OPT", opt_method: "ARSM", max_designs: 25, model_id: "m-1", model_name: "cushion_TNS v1", param_set_id: "ps-1",
      study_folder: "HST_PHYSICSAI_OPTIMIZATION", runs_started: 25, responses, summary_status: "PARSED",
      summary_meta: { parser: "hst_csv", file_rel: "05_opt/j-opt/HST_PHYSICSAI_OPTIMIZATION/approaches/opt_1/opt_summary.csv", row_count: 25, columns: summary.columns },
      summary_artifact_id: sumId, file_count: 4, file_list_artifact_id: fl, folder_display_path: this.s.disp(sid, "05_opt/j-opt"), created_by_name: "김연구", created_at: iso(60 + 10),
    });

    // 환경 점검 이력
    const mk = (id: string, minAgo: number, variant: number): EnvCheck => {
      const items = envItems(variant);
      return {
        id, state: "DONE", requested_by_name: "박관리", created_at: iso(minAgo), finished_at: iso(minAgo - 1), started_at: iso(minAgo), expires_at: iso(minAgo - 15),
        worker_id: "PHYSICS-PC:4412", items, failure_message: null, summary: summarize(items), report_display_path: `E:\\shared\\AI_WORK\\_platform\\env_checks\\${id}\\report.json`,
      };
    };
    this.envChecks.push(mk("ec-3", 95, 1), mk("ec-2", 60 * 26, 0), mk("ec-1", 60 * 24 * 3, 0));
  }

  private previewArtifacts(jobId: string, studyId: string, source: CurationSourceRef) {
    const files = this.sourceFiles(studyId, source);
    const raw = { datatype_info: H3D_INFO, lst_cid_shell: [1, 2, 5, 7], lst_cid_solid: [3, 4], lst_cid_rbody: [9], num_time_step: 41 };
    const usable = Object.fromEntries(Object.entries(H3D_INFO).map(([k, v]) => [k, v.filter(usableComponent)]));
    this.s.addArtifact(jobId, studyId, "PREVIEW_JSON", `02_preview/${jobId}/PREVIEW_H3D.json`, "application/json", JSON.stringify(raw));
    // 변경 메모 C14 형식
    const summary = {
      datatypes: Object.entries(H3D_INFO).map(([name, components]) => ({ name, components, usable: usable[name] })),
      parts: { shell: raw.lst_cid_shell, solid: raw.lst_cid_solid, rbody: raw.lst_cid_rbody },
      num_time_step: raw.num_time_step,
      sample_file: files[0] ?? null,
      source_file_count: files.length,
      files: files.map((rel) => ({ rel, run_folder: rel.split("/")[0], size: 38_000_000 })),
    };
    this.s.addArtifact(jobId, studyId, "PREVIEW_JSON", `02_preview/${jobId}/preview_summary.json`, "application/json", JSON.stringify(summary));
  }

  private sourceFiles(studyId: string, source: CurationSourceRef): string[] {
    if (source.kind === "TRAIN_DOE") return (this.runs[source.doe_id] ?? []).filter((r) => r.state === "COLLECTED").map((r) => `${r.run_key}/m_3/cushion_0000.h3d`);
    if (source.kind === "SPDM_IMPORT") return Array.from({ length: 12 }, (_, i) => `Case_0012/Scene_03/sub_${String(i + 1).padStart(2, "0")}/result.h3d`);
    void studyId;
    return Array.from({ length: 8 }, (_, i) => `case_${i + 1}/model.h3d`);
  }

  // ---------------- 출력 변환 ----------------
  private doeOut(d: TrainDoe): TrainDoe {
    const runs = this.runs[d.id] ?? [];
    const counts: Record<TrainRunState, number> = { GENERATED: 0, SUBMITTED: 0, SOLVED: 0, SOLVE_FAILED: 0, COLLECTED: 0, COLLECT_FAILED: 0 };
    for (const r of runs) counts[r.state]++;
    return { ...d, run_state_counts: counts, collected_count: counts.COLLECTED, solve_failed_count: counts.SOLVE_FAILED, run_count: d.status === "READY" ? runs.length : d.run_count };
  }

  hpcSummary(j: Job): HpcSummary | null {
    if (j.job_type !== "TD_SOLVE" && j.job_type !== "PREDICT_VERIFY") return null;
    if (j.job_type === "PREDICT_VERIFY") return null;
    const doe = j.params.doe_id as string;
    const runs = (this.runs[doe] ?? []).filter((r) => r._job === j.id);
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

  summaryExtra(j: Job) {
    const cur = j.steps.find((x) => x.state === "RUNNING") ?? (j.state === "WAITING_HPC" ? j.steps.find((x) => x.step_key === "HPC_WAIT") : undefined);
    return {
      stage_label: STAGE_LABEL[j.job_type],
      current_step_key: cur?.step_key ?? null,
      current_step_label: cur ? this.s.stepLabel(cur.step_key) : null,
      hpc_summary: this.hpcSummary(j),
      attention_code: j.attention_code ?? null,
    };
  }

  status(isAdmin: boolean) {
    const latest = this.envChecks[0];
    return {
      features: Object.fromEntries(ALL_FEATURES.map((k) => [k, this.feature(k)])),
      resources: [
        { key: "batchrun_dir", configured: true, ok: true },
        { key: "pyd_dir", configured: !this.disabled.has("train_extract"), ok: !this.disabled.has("train_extract") },
        { key: "extract_minmax_tcl", configured: !this.disabled.has("optimize"), ok: !this.disabled.has("optimize") },
      ],
      env_check: isAdmin && latest
        ? { latest_id: latest.id, latest_state: latest.state, finished_at: latest.finished_at, fail: latest.summary.fail, warn: latest.summary.warn }
        : null,
    };
  }

  // ---------------- 작업 생성·진행 ----------------
  precheck(s: Study, type: JobType, params: Record<string, unknown>): MockResp | null {
    const f = FEATURE_OF[type];
    if (type === "TD_SOLVE" && !this.s.hpcConfigured) return err(409, "HPC_NOT_CONFIGURED", "PBS 연결이 설정되지 않았습니다.");
    if (type === "SPDM_IMPORT" && this.disabled.has("spdm_import")) return err(409, "SPDM_IMPORT_DISABLED", "SPDM 가져오기가 설정되지 않았습니다.");
    if (f && this.disabled.has(f)) return err(409, f === "train_resp" ? "TEMPLATE_NOT_CONFIGURED" : "RESOURCE_NOT_CONFIGURED", "관리자 설정이 필요합니다.", { missing: FEATURE_MISSING[f] });
    if (type === "TD_DOE_GEN") {
      const t = this.setups[s.id]?.tpl;
      if (!t) return err(409, "TPL_REQUIRED", "tpl을 먼저 생성하세요.");
      if (t.stale) return err(409, "TPL_STALE", "파라미터 표가 바뀌었습니다 — tpl을 다시 생성하세요.");
    }
    if (type === "TD_SOLVE" || type === "TD_RESULT_IMPORT") {
      const d = this.does.find((x) => x.id === params.doe_id && x.study_id === s.id);
      if (!d || d.status !== "READY") return err(409, "DOE_NOT_READY", "준비된 DOE가 필요합니다.");
    }
    if (type === "CU_H3D_CURATE") {
      const pj = this.s.jobs.find((x) => x.id === params.preview_job_id && x.job_type === "CU_H3D_PREVIEW" && x.state === "SUCCEEDED");
      if (!pj) return err(409, "CURATION_PREVIEW_REQUIRED", "h3d 미리보기를 먼저 실행하세요.");
    }
    if (type === "OPTIMIZE") {
      if (!params.model_id && !s.final_model_id) return err(409, "FINAL_MODEL_REQUIRED", "Final 모델을 먼저 지정하세요.");
      const rs = (params.responses as OptResponse[]) ?? [];
      if (!rs.length) return err(422, "RESPONSES_INVALID", "응답을 1개 이상 추가하세요.", { problems: [] });
      if (params.approach === "OPT" && !rs.some((r) => r.goal === "MINIMIZE" || r.goal === "MAXIMIZE"))
        return err(422, "OBJECTIVE_REQUIRED", "최적화에는 MINIMIZE 또는 MAXIMIZE 응답이 1개 이상 필요합니다.");
    }
    return null;
  }

  onCreate(j: Job, me: { display_name: string }) {
    const p = j.params as Record<string, unknown>;
    const sid = j.study_id;
    const now = j.created_at;
    if (j.job_type === "TD_DOE_GEN") {
      const id = this.s.nid("doe");
      p.doe_id = id;
      const t = DOE_TYPES.find((x) => x.label === p.doe_label) ?? DOE_TYPES[0];
      this.does.unshift({
        id, study_id: sid, job_id: j.id, status: "BUILDING", doe_label: t.label, doe_type: t.value, num_runs_requested: t.runs_editable ? Number(p.num_runs ?? t.default_runs) : null,
        options: (p.options as Record<string, unknown>) ?? {}, multi_execution: Number(p.multi_execution ?? 1), radioss_assem_source_path: String(p.radioss_assem_path ?? ""),
        run_count: null, sample_status: "PENDING", collected_count: 0, solve_failed_count: 0, has_run_responses: false,
        dir_display_path: this.s.disp(sid, `01_train/doe/${id}`), results_display_path: this.s.disp(sid, `01_train/results/${id}`), created_by_name: me.display_name, created_at: now,
        run_state_counts: { GENERATED: 0, SUBMITTED: 0, SOLVED: 0, SOLVE_FAILED: 0, COLLECTED: 0, COLLECT_FAILED: 0 },
      });
    }
    if (j.job_type === "CU_H3D_CURATE" || j.job_type === "CU_T01_CURVES") {
      const id = this.s.nid("cur");
      p.curation_id = id;
      this.curations.unshift({
        id, study_id: sid, job_id: j.id, kind: j.job_type === "CU_H3D_CURATE" ? "H3D" : "T01", status: "BUILDING", source: p.source as CurationSourceRef, source_label: this.sourceLabel(p.source as CurationSourceRef),
        preview_job_id: (p.preview_job_id as string) ?? null, selection: (p.selection as Record<string, unknown>) ?? { curves: p.curves }, target_count: 0, ok_count: 0, failed_count: 0, missing_runs: [],
        output_display_path: this.s.disp(sid, `02_curated/${id}/${j.job_type === "CU_H3D_CURATE" ? "CURATED_DATA" : "CURVES"}`), used_by_dataset_ids: [], created_by_name: me.display_name, created_at: now,
      });
    }
    if (j.job_type === "SPDM_IMPORT") {
      const id = this.s.nid("imp");
      p.import_id = id;
      this.imports.unshift({ id, study_id: sid, job_id: j.id, status: "BUILDING", spdm_path: String(p.spdm_path), file_count: null, total_bytes: null, renamed_count: null, dest_display_path: this.s.disp(sid, `02_import/${id}`), created_by_name: me.display_name, created_at: now });
    }
    if (j.job_type === "OPTIMIZE") {
      const id = this.s.nid("opt");
      p.optimization_id = id;
      const st = this.s.studies.find((x) => x.id === sid)!;
      const mid = (p.model_id as string) || st.final_model_id || "m-1";
      const m = this.s.models.find((x) => x.id === mid);
      this.opts.unshift({
        id, study_id: sid, job_id: j.id, status: "RUNNING", approach: (p.approach as "OPT") ?? "OPT", opt_method: (p.opt_method as "ARSM") ?? "ARSM", max_designs: Number(p.max_designs ?? 25),
        model_id: mid, model_name: m ? `${m.name} v${m.version}` : mid, param_set_id: (p.param_set_id as string) || "ps-1", study_folder: String(p.study_folder ?? "HST_PHYSICSAI_OPTIMIZATION"),
        runs_started: null, responses: (p.responses as OptResponse[]) ?? [], summary_status: "NONE", summary_meta: null, summary_artifact_id: null, file_count: null, file_list_artifact_id: null,
        folder_display_path: this.s.disp(sid, `05_opt/${j.id}`), created_by_name: me.display_name, created_at: now,
      });
    }
  }

  private sourceLabel(src: CurationSourceRef): string {
    if (src.kind === "TRAIN_DOE") {
      const d = this.does.find((x) => x.id === src.doe_id);
      return `① DOE ${src.doe_id} · ${d?.doe_label ?? ""} ${d?.run_count ?? ""}`.trim();
    }
    if (src.kind === "SPDM_IMPORT") return `SPDM 가져오기 ${src.import_id}`;
    return src.path;
  }

  /** RUNNING 중 진행 표시 보정 */
  onProgress(j: Job) {
    if (j.job_type === "OPTIMIZE") {
      const o = this.opts.find((x) => x.job_id === j.id);
      if (o) {
        const n = Math.max(1, Math.floor(((j.progress_pct ?? 0) / 100) * o.max_designs));
        o.runs_started = n;
        j.progress_label = o.approach === "DOE" ? `run ${n} 시작` : `run ${n} / ${o.max_designs} 시작`;
        if (o.approach === "DOE") j.progress_pct = null;
      }
    }
  }

  /** 완료 처리. "waiting"이면 WAITING_HPC로 전환(TD_SOLVE) */
  finish(j: Job): "done" | "waiting" | "failed" {
    const p = j.params as Record<string, unknown>;
    const sid = j.study_id;
    switch (j.job_type) {
      case "TD_EXTRACT_PARAMS": {
        const params = trainParams().map((x) => ({ ...x }));
        const old = this.setups[sid];
        const file = String(p.cad_path ?? "").split(/[\\/]/).pop() ?? "model.prt";
        this.setups[sid] = {
          study_id: sid, cad: { source_path: String(p.cad_path), file_name: file, sha256: "…", display_path: this.s.disp(sid, `01_train/cad/${file}`) },
          extract_job_id: j.id, parameters: params, used_count: params.filter((x) => x.use).length,
          tpl: old?.tpl ? { ...old.tpl, stale: true } : null, version: (old?.version ?? 0) + 1, updated_by_name: j.created_by_name, updated_at: new Date().toISOString(),
        };
        j.result = { param_count: params.length, valid_count: params.filter((x) => x.valid).length, cad_file_name: file };
        return "done";
      }
      case "TD_DOE_GEN": {
        const d = this.does.find((x) => x.id === p.doe_id)!;
        const n = d.num_runs_requested ?? (DOE_TYPES.find((t) => t.label === d.doe_label)?.default_runs ?? 9);
        d.status = "READY";
        d.run_count = n;
        d.sample_status = "PARSED";
        const r = rng(n);
        this.runs[d.id] = Array.from({ length: n }, (_, i) => ({ run_key: runKey(i + 1), state: "GENERATED" as TrainRunState, starter_name: "cushion_0000.rad", input_display_path: this.s.disp(sid, `01_train/doe/${d.id}/approaches/doe_1/${runKey(i + 1)}/m_3`), hpc: null, result: null, updated_at: new Date().toISOString() }));
        this.doeSamples[d.id] = this.runs[d.id].map((x) => ({ run_key: x.run_key, values: { THK_TOP: Number((0.3 + r() * 0.9).toFixed(4)), THK_FOAM: Number((1 + r() * 2).toFixed(4)), RIB_H: 12, RIB_N: 2 + Math.floor(r() * 7) }, measured: {} }));
        j.result = { doe_id: d.id, run_count: n, sample_status: "PARSED", skipped_runs: [] };
        return "done";
      }
      case "TD_SOLVE": {
        const runs = this.targetRuns(j);
        for (const r of runs) {
          r.state = "SUBMITTED";
          r._job = j.id;
          r.hpc = { external_job_id: `${this.hpcSeq++}.pbs01`, state: "QUEUED", attempt_no: (r.hpc?.attempt_no ?? 0) + 1 };
          r.updated_at = new Date().toISOString();
        }
        j.steps = makeSteps("TD_SOLVE", 2, 2);
        j.progress_label = "PBS 대기";
        return "waiting";
      }
      case "TD_RESULT_IMPORT": {
        const runs = this.runs[p.doe_id as string] ?? [];
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
        const d = this.does.find((x) => x.id === p.doe_id);
        if (d) d.has_run_responses = true;
        return "done";
      }
      case "CU_H3D_PREVIEW": {
        this.previewArtifacts(j.id, sid, p.source as CurationSourceRef);
        j.result = { sample_file: null, datatype_count: 4, part_counts: { shell: 4, solid: 2, rbody: 1 }, num_time_step: 41, source_file_count: this.sourceFiles(sid, p.source as CurationSourceRef).length };
        return "done";
      }
      case "CU_T01_PREVIEW": {
        this.s.addArtifact(j.id, sid, "PREVIEW_JSON", `02_preview/${j.id}/PREVIEW_T01.json`, "application/json", JSON.stringify(T01_PREVIEW));
        return "done";
      }
      case "CU_H3D_CURATE":
      case "CU_T01_CURVES": {
        const c = this.curations.find((x) => x.id === p.curation_id)!;
        const files = this.sourceFiles(sid, c.source).filter((f) => !((p.exclude_files as string[]) ?? []).includes(f));
        const failIdx = c.kind === "H3D" && files.length > 3 ? 2 : -1;
        this.curationFiles[c.id] = files.map((f, i) => {
          const rf = f.split("/")[0];
          return { run_folder: rf, run_key: /^run__/.test(rf) ? rf : null, input_name: f.split("/").pop()!, output_name: i === failIdx ? null : c.kind === "H3D" ? f.split("/").pop()! : `${rf}_curves.json`, size: i === failIdx ? null : 30_000_000, ok: i !== failIdx, exit_code: i === failIdx ? 1 : 0 };
        });
        Object.assign(c, {
          status: "READY", target_count: files.length, ok_count: files.length - (failIdx >= 0 ? 1 : 0), failed_count: failIdx >= 0 ? 1 : 0,
          missing_runs: c.source.kind === "TRAIN_DOE" ? (this.runs[c.source.doe_id] ?? []).filter((r) => r.state !== "COLLECTED").map((r) => r.run_key) : [],
        });
        if (failIdx >= 0) j.warnings = [{ code: "PARTIAL_OUTPUT", message: `${files.length}개 중 1개 실패` }];
        if (c.kind === "T01") this.s.addArtifact(j.id, sid, "CURVE_JSON", `02_curated/${c.id}/CURVES/first_curves.json`, "application/json", JSON.stringify(curveSeries()));
        j.result = { curation_id: c.id, target_count: c.target_count, ok_count: c.ok_count, failed_count: c.failed_count, missing_run_count: c.missing_runs.length, output_display_path: c.output_display_path };
        return "done";
      }
      case "SPDM_IMPORT": {
        const im = this.imports.find((x) => x.id === p.import_id);
        if (im) Object.assign(im, { status: "READY", file_count: 12, total_bytes: 2_400_000_000, renamed_count: 1 });
        return "done";
      }
      case "OPTIMIZE": {
        const o = this.opts.find((x) => x.job_id === j.id)!;
        const sm = optSummary(this.s.idn, o.approach === "DOE" ? 12 : o.max_designs);
        o.status = "DONE";
        o.runs_started = sm.rows.length;
        o.summary_status = "PARSED";
        o.summary_artifact_id = this.s.addArtifact(j.id, sid, "OPT_SUMMARY", `05_opt/${j.id}/summary.json`, "application/json", JSON.stringify(summaryJson(sm, "opt_summary.csv")));
        o.summary_meta = { parser: "hst_csv", file_rel: "opt_summary.csv", row_count: sm.rows.length, columns: sm.columns };
        o.file_list_artifact_id = this.s.addArtifact(j.id, sid, "FILE_LIST", `05_opt/${j.id}/file_list.json`, "application/json", JSON.stringify({ root: o.study_folder, files: [{ rel: `${o.study_folder}/run_log.txt`, size: 900 }], truncated: false }));
        this.s.addArtifact(j.id, sid, "OPT_FILE", `05_opt/${j.id}/${o.study_folder}/run_log.txt`, "text/plain", "Started run (1), model (m_1)\n");
        o.file_count = 1;
        j.progress_label = null;
        j.result = { runs_started: sm.rows.length, log_error_lines: 0 };
        return "done";
      }
      default:
        return "done";
    }
  }

  private targetRuns(j: Job): RunRec[] {
    const p = j.params as Record<string, unknown>;
    const runs = this.runs[p.doe_id as string] ?? [];
    const keys = p.run_keys as string[] | null | undefined;
    if (keys && keys.length) return runs.filter((r) => keys.includes(r.run_key));
    return runs.filter((r) => r.state === "GENERATED" || r.state === "SOLVE_FAILED" || r.state === "COLLECT_FAILED");
  }

  /** 시간 1단계: PBS run 진행, 환경 점검 진행 */
  tick() {
    for (const j of this.s.jobs.filter((x) => x.job_type === "TD_SOLVE" && (x.state === "WAITING_HPC" || x.state === "COLLECTING"))) {
      const runs = (this.runs[j.params.doe_id as string] ?? []).filter((r) => r._job === j.id);
      if (j.cancel_requested && this.s.hpcCancelFails) {
        // C18: PBS 취소 명령 실패 → CANCEL_REQUESTED 유지, 작업은 WAITING_HPC + attention_code, 알림 1회
        runs.filter((r) => r.state === "SUBMITTED").forEach((r) => r.hpc && (r.hpc.state = "CANCEL_REQUESTED"));
        if (j.attention_code !== "HPC_CANCEL_FAILED") {
          j.attention_code = "HPC_CANCEL_FAILED";
          this.s.notify(j.created_by, "HPC_CANCEL_FAILED", j, `PBS 취소 실패: PBS 해석 (${j.study_title}) — 자동 재시도 중`);
          this.s.bump(j);
        }
        continue;
      }
      if (j.cancel_requested) {
        runs.filter((r) => r.state === "SUBMITTED").forEach((r) => (r.state = "SOLVE_FAILED"));
        j.state = "CANCELED";
        j.finished_at = new Date().toISOString();
        this.s.bump(j);
        this.s.notifyJob(j, "JOB_CANCELED");
        continue;
      }
      if (j.state === "WAITING_HPC") {
        const pending = runs.filter((r) => r.state === "SUBMITTED");
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
            this.s.notifyJob(j, "JOB_FAILED");
          } else {
            j.state = "COLLECTING";
            j.steps = makeSteps("TD_SOLVE", 3, 3);
            if (failed) {
              j.attention_code = "HPC_RUN_FAILED";
              j.warnings = [{ code: "HPC_PARTIAL_FAILED", message: `${runs.length}개 중 ${failed}개 실패` }];
              this.s.notify(j.created_by, "HPC_PARTIAL_FAILED", j, `PBS 해석 일부 실패 — ${runs.length}개 중 ${failed}개 실패, 나머지 회수 진행`);
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
        this.s.notify(j.created_by, "HPC_COLLECTED", j, `PBS 결과 회수 완료 — ${runs.length}개 중 ${collected}개 회수`);
      }
      this.s.bump(j);
    }
    // 환경 점검: PENDING → RUNNING → DONE
    for (const ec of this.envChecks) {
      if (ec.state === "PENDING") {
        ec.state = "RUNNING";
        ec.started_at = new Date().toISOString();
        ec.worker_id = "PHYSICS-PC:4412:mock";
      } else if (ec.state === "RUNNING") {
        ec.items = envItems(1);
        ec.summary = summarize(ec.items);
        ec.state = "DONE";
        ec.finished_at = new Date().toISOString();
        ec.report_display_path = `E:\\shared\\AI_WORK\\_platform\\env_checks\\${ec.id}\\report.json`;
        this.s.notify((ec as EnvCheck & { _uid?: string })._uid ?? "u-admin", "ENV_CHECK_DONE", null, `환경 점검 완료 — 실패 ${ec.summary.fail} · 경고 ${ec.summary.warn}`);
      }
    }
  }

  // ---------------- 라우팅 ----------------
  handle(method: string, path: string, query: URLSearchParams, body: Record<string, unknown> | null): MockResp | null {
    const seg = path.split("/").filter(Boolean);
    const me = this.s.me!;

    // 환경 점검(전역 관리자)
    if (seg[0] === "admin" && seg[1] === "env-checks") {
      if (!me.is_global_admin) return err(403, "PERMISSION_DENIED", "전역 관리자만 할 수 있습니다.", { required: "global_admin" });
      if (method === "POST" && !seg[2]) {
        if (this.envChecks.some((e) => e.state === "PENDING" || e.state === "RUNNING")) return err(409, "ENV_CHECK_BUSY", "이미 진행 중인 환경 점검이 있습니다.");
        const items = envItems(1, true);
        const ec: EnvCheck & { _uid?: string } = {
          id: this.s.nid("ec"), state: "PENDING", requested_by_name: me.display_name, created_at: new Date().toISOString(), finished_at: null, started_at: null,
          expires_at: new Date(Date.now() + 900_000).toISOString(), worker_id: null, items, failure_message: null, summary: summarize(items), report_display_path: null, _uid: me.user_id,
        };
        this.envChecks.unshift(ec);
        return ok(this.ecOut(ec), 202);
      }
      if (method === "GET" && !seg[2]) {
        const limit = Number(query.get("limit") ?? 20);
        const list = this.envChecks.slice(0, limit).map(({ id, state, requested_by_name, created_at, finished_at, summary }) => ({ id, state, requested_by_name, created_at, finished_at, summary }));
        return ok(list);
      }
      if (method === "GET" && seg[2] === "latest") return this.envChecks[0] ? ok(this.ecOut(this.envChecks[0])) : err(404, "NOT_FOUND", "환경 점검 이력이 없습니다.");
      if (method === "GET" && seg[2]) {
        const ec = this.envChecks.find((e) => e.id === seg[2]);
        return ec ? ok(this.ecOut(ec)) : err(404, "NOT_FOUND", "환경 점검을 찾을 수 없습니다.");
      }
    }

    if (method === "GET" && path === "/train/doe-types") {
      if (this.disabled.has("train_doe")) return err(409, "RESOURCE_NOT_CONFIGURED", "DOE 유형 파일이 설정되지 않았습니다.", { missing: ["resources.doe_design_type_json"] });
      return ok(DOE_TYPES);
    }
    if (seg[0] === "train-does" && seg[1]) {
      const d = this.does.find((x) => x.id === seg[1]);
      if (!d) return err(404, "NOT_FOUND", "DOE를 찾을 수 없습니다.");
      if (method === "GET" && !seg[2]) return ok(this.doeOut(d));
      if (method === "GET" && seg[2] === "runs") {
        let runs = this.runs[d.id] ?? [];
        const st = query.get("state");
        if (st) runs = runs.filter((r) => r.state === st);
        const limit = Number(query.get("limit") ?? 200);
        const start = Number(query.get("cursor") ?? 0);
        const next = start + limit < runs.length ? String(start + limit) : null;
        return { status: 200, body: runs.slice(start, start + limit).map(({ _job: _j, ...r }) => r), headers: next ? { "X-Next-Cursor": next } : {} };
      }
      if (method === "GET" && seg[2] === "samples") {
        const rows = this.doeSamples[d.id];
        if (!rows) return err(404, "SAMPLES_MISSING", "샘플 표가 없습니다.");
        return ok({ columns: ["run_key", ...Object.keys(rows[0]?.values ?? {})], rows, next_cursor: null });
      }
    }
    if (seg[0] === "curations" && seg[1]) {
      const c = this.curations.find((x) => x.id === seg[1]);
      if (!c) return err(404, "NOT_FOUND", "큐레이션을 찾을 수 없습니다.");
      if (method === "GET" && !seg[2]) return ok(c);
      if (method === "GET" && seg[2] === "files") {
        let files = this.curationFiles[c.id] ?? [];
        const okq = query.get("ok");
        if (okq !== null) files = files.filter((f) => String(f.ok) === okq);
        return ok({ items: files.slice(0, Number(query.get("limit") ?? 200)), next_cursor: null });
      }
    }
    if (method === "GET" && seg[0] === "optimizations" && seg[1]) {
      const o = this.opts.find((x) => x.id === seg[1]);
      return o ? ok(o) : err(404, "NOT_FOUND", "최적화를 찾을 수 없습니다.");
    }

    if (seg[0] === "studies" && seg[1]) {
      const s = this.s.studies.find((x) => x.id === seg[1]);
      if (!s) return null;
      const sub = seg.slice(2).join("/");
      if (method === "GET" && sub === "train") return ok(this.setups[s.id] ?? { study_id: s.id, cad: null, extract_job_id: null, parameters: [], used_count: 0, tpl: null, version: 1, updated_by_name: null, updated_at: null });
      if (method === "GET" && sub === "train/does") return ok(this.does.filter((d) => d.study_id === s.id).map((d) => this.doeOut(d)));
      if (method === "GET" && sub === "curation-sources") {
        const out: unknown[] = [];
        for (const d of this.does.filter((x) => x.study_id === s.id && x.status === "READY")) {
          const n = (this.runs[d.id] ?? []).filter((r) => r.state === "COLLECTED").length;
          if (n) out.push({ kind: "TRAIN_DOE", ref_id: d.id, label: `① DOE ${d.doe_label} · ${d.run_count} run`, display_path: d.results_display_path, h3d_count: n, t01_count: n, runs_expected: d.run_count, created_at: d.created_at });
        }
        for (const im of this.imports.filter((x) => x.study_id === s.id && x.status === "READY"))
          out.push({ kind: "SPDM_IMPORT", ref_id: im.id, label: `SPDM ${im.spdm_path.split("\\").slice(-2).join("\\")}`, display_path: im.dest_display_path, h3d_count: 12, t01_count: 12, runs_expected: null, created_at: im.created_at });
        return ok(out);
      }
      if (method === "GET" && sub === "curations") {
        const kind = query.get("kind");
        return ok(this.curations.filter((c) => c.study_id === s.id && (!kind || c.kind === kind)));
      }
      if (method === "GET" && sub === "spdm-imports") return ok(this.imports.filter((x) => x.study_id === s.id));
      if (method === "GET" && sub === "optimizations") return ok(this.opts.filter((x) => x.study_id === s.id));
      if (method === "GET" && sub === "optimize/response-candidates")
        return ok({
          source_job_id: "j-pred",
          h3d: { subcases: [{ id: 1, label: "Subcase 1", datatypes: [{ name: "Stress", components: ["vonMises", "P1 (major)"], layers: ["", "Max", "Min"], format: "tensor" }, { name: "Displacement", components: ["X", "Y", "Z", "Mag"], layers: [""], format: "vector" }] }] },
          xydata: { requests: { "Node 100": ["X", "Y", "Z"], "RBODY 1": ["F-Mag"] } },
        });
      // 쓰기(power)
      const r = this.s.role(s.project_id);
      const power = r === "power" || r === "admin";
      if (method === "PUT" && sub === "train/params") {
        if (!power) return err(403, "PERMISSION_DENIED", "실행 권한(power 이상)이 필요합니다.", { required: "power" });
        return this.saveParams(s, body ?? {});
      }
      if (method === "POST" && sub === "train/tpl") {
        if (!power) return err(403, "PERMISSION_DENIED", "실행 권한(power 이상)이 필요합니다.", { required: "power" });
        const t = this.setups[s.id];
        if (!t || !t.parameters.length) return err(409, "TRAIN_PARAMS_REQUIRED", "파라미터를 먼저 추출하세요.");
        if (this.disabled.has("train_tpl")) return err(409, "RESOURCE_NOT_CONFIGURED", "tpl 템플릿이 설정되지 않았습니다.", { missing: FEATURE_MISSING.train_tpl });
        if (Number(body?.version) !== t.version) return err(409, "VERSION_CONFLICT", "다른 사용자가 먼저 바꿨습니다. 새로고침하세요.");
        const used = t.parameters.filter((p) => p.use);
        const warnings = used
          .filter((p) => /^%[-0-9.]*[id]$/.test(p.format) && [p.nominal, p.min, p.max].some((v) => v != null && !Number.isInteger(v)))
          .map((p) => ({ code: "TPL_INTEGER_FORMAT", message: `정수 형식(${p.format})이라 HyperStudy 샘플 값이 정수로 반영됩니다: ${p.name}` }));
        t.tpl = { generated_at: new Date().toISOString(), sha256: "77de…", display_path: this.s.disp(s.id, "01_train/tpl/simlab_parametered_mesh.tpl"), params: used.map((p, i) => ({ var: `var_${i + 1}`, name: p.name, format: p.format })), warnings, stale: false };
        t.version++;
        return ok(t);
      }
      if (method === "POST" && sub === "param-sets/from-train") {
        if (!power) return err(403, "PERMISSION_DENIED", "실행 권한(power 이상)이 필요합니다.", { required: "power" });
        const d = this.does.find((x) => x.id === body?.doe_id && x.study_id === s.id);
        if (!d || d.status !== "READY") return err(409, "DOE_NOT_READY", "준비된 DOE가 필요합니다.");
        if (d.sample_status !== "PARSED" && d.sample_status !== "PARTIAL") return err(409, "SAMPLES_MISSING", "DOE 샘플 표가 없습니다.");
        const runs = (this.runs[d.id] ?? []).filter((x) => body?.runs === "all" || x.state === "COLLECTED");
        if (!runs.length) return err(409, "DOE_NOT_READY", "회수된 run이 없습니다.");
        return { status: 201, body: this.s.addParamSetFromTrain(s, d.id, runs.length) };
      }
    }
    return null;
  }

  private ecOut(ec: EnvCheck): EnvCheck {
    const { _uid: _u, ...rest } = ec as EnvCheck & { _uid?: string };
    return rest;
  }

  private saveParams(s: Study, body: Record<string, unknown>): MockResp {
    const t = this.setups[s.id];
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
    t.updated_by_name = this.s.me!.display_name;
    t.updated_at = new Date().toISOString();
    return ok(t);
  }

  inspect(purpose: string, path: string, doeId?: string): MockResp | null {
    if (purpose === "SPDM_IMPORT") {
      if (this.disabled.has("spdm_import")) return err(409, "SPDM_IMPORT_DISABLED", "SPDM 가져오기가 설정되지 않았습니다.");
      if (!/^\\\\spdm\\master\\/i.test(path)) return err(422, "PATH_OUTSIDE_ROOT", "SPDM 루트(\\\\spdm\\master) 하위 경로만 지정할 수 있습니다.");
      return ok({ normalized_path: path, ok: true, problems: [], summary: { h3d_count: 12, t01_count: 12, total_bytes: 2_400_000_000, renamed_count: /\s|&/.test(path) ? 1 : 0, sample_files: ["sub_01/result.h3d", "sub_01/resultT01"] } });
    }
    if (!["CAD_FILE", "RADIOSS_ASSEM", "RESULT_FOLDER", "CURATION_INPUT"].includes(purpose)) return null;
    if (/\s|[&|<>^%!"]/.test(path)) return err(422, "PATH_UNSAFE", "경로에 공백이나 특수문자를 쓸 수 없습니다.");
    if (!/AI_WORK/i.test(path)) return err(422, "PATH_OUTSIDE_ROOT", "AI 루트 하위 경로만 지정할 수 있습니다.");
    const last = path.split(/[\\/]/).filter(Boolean).pop() ?? "";
    if (purpose === "CAD_FILE") {
      const extOk = /\.prt$/i.test(last);
      return ok({ normalized_path: path, ok: extOk, problems: extOk ? [] : [{ code: "EXTENSION_NOT_ALLOWED", message: "허용 확장자: .prt" }], summary: { file_name: last, size: 4_812_000, extension_ok: extOk } });
    }
    if (purpose === "RADIOSS_ASSEM") {
      const many = /multi/i.test(path);
      return ok({ normalized_path: path, ok: !many, problems: many ? [{ code: "STARTER_NOT_UNIQUE", message: "starter가 2개입니다" }] : [], summary: { rad: ["cushion_0000.rad", "cushion_0001.rad"], inc_count: 6, starter: many ? ["a_0000.rad", "b_0000.rad"] : ["cushion_0000.rad"], starter_ok: !many } });
    }
    if (purpose === "RESULT_FOLDER") {
      const runs = doeId ? (this.runs[doeId] ?? []) : [];
      const matched = Math.max(0, runs.length - 2);
      return ok({ normalized_path: path, ok: matched > 0, problems: matched ? [] : [{ code: "NO_RUN_MATCHED", message: "run 폴더를 찾지 못했습니다" }], summary: { doe_id: doeId ?? null, matched_runs: matched, unmatched_dirs: ["logs"], file_count: matched * 4 } });
    }
    return ok({ normalized_path: path, ok: true, problems: [], summary: { h3d_count: 8, t01_count: 8, run_folders: ["case_1", "case_2", "case_3"] } });
  }
}
