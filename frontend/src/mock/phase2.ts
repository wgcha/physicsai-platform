// 2차(phase2.md §12) 목 공유 상태(Phase2Mock): ①②⑤·환경 점검의 상태 배열과 작업 훅 분배. MockServer가 위임한다.
// F5: 단계별 동작은 stage1·stage1Jobs(①)·stage2(②)·stage5(⑤)·ops(환경 점검)에, 라우트 등록은 server.ts ROUTES 한 곳에 있다.
import type {
  Curation,
  CurationFile,
  EnvCheck,
  FeatureKey,
  FeatureState,
  Job,
  JobType,
  Optimization,
  SampleRow,
  SpdmImport,
  Study,
  TrainDoe,
  TrainSetup,
} from "../api/types";
import { baseJob, iso, makeSteps } from "./data";
import { ALL_FEATURES, FEATURE_MISSING, FEATURE_OF, STAGE_LABEL } from "./catalog";
import { err, ok, type MockResp } from "./route";
import type { MockServer } from "./server";
import { seedTrain, type RunRec } from "./stage1";
import { finishTrain, hpcSummary, onCreateTrain, precheckTrain, tickSolve } from "./stage1Jobs";
import { finishCuration, onCreateCuration, precheckCuration, seedCuration } from "./stage2";
import { finishOptimize, onCreateOptimize, onProgressOptimize, precheckOptimize, seedOptimize } from "./stage5";
import { seedEnvChecks, tickEnvChecks } from "./ops";
import { checkGeneratorShape, generatorOf } from "./doePlatform";

export { ALL_FEATURES, DOE_TYPES, FEATURE_MISSING, STAGE_LABEL } from "./catalog";
export { usableComponent } from "./stage2";

/** 시드 작업 생성기(s-cushion, s.jobs에 추가) */
export type SeedJob = (p: Partial<Job> & Pick<Job, "id" | "job_type" | "state">) => Job;

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
    if ((k === "train_solve" || k === "fem_verify" || k === "fem_verify_rebuild") && !this.s.hpcConfigured) return { enabled: false, missing: ["hpc.mode"] };
    const f: FeatureState = this.disabled.has(k) ? { enabled: false, missing: FEATURE_MISSING[k] } : { enabled: true, missing: [] };
    return k === "train_doe" || k === "optimize" ? { ...f, legacy: true } : f; // opt-native §4.2 HyperStudy 레거시
  }

  // ---------------- seed(원래 순서: ① → SPDM·② → ⑤ → 환경 점검) ----------------
  private seed() {
    const sid = "s-cushion";
    const st = "쿠션 두께·리브 예측";
    const J: SeedJob = (p: Partial<Job> & Pick<Job, "id" | "job_type" | "state">) => {
      const done = p.state === "SUCCEEDED";
      const j = baseJob({
        study_id: sid, project_id: "p-cushion", study_title: st, created_at: iso(60 * 8), started_at: iso(60 * 8 - 1), finished_at: done ? iso(60 * 8 - 3) : null,
        progress_pct: done ? 100 : null, ...p,
        steps: p.steps ?? makeSteps(p.job_type, done ? 3 : 0, null),
      });
      this.s.jobs.push(j);
      return j;
    };
    const { doeId, runs } = seedTrain(this, J, sid);
    seedCuration(this, J, sid, doeId, runs);
    seedOptimize(this, J, sid);
    seedEnvChecks(this);
  }

  hpcSummary(j: Job) {
    return hpcSummary(this, j);
  }

  summaryExtra(j: Job) {
    const cur = j.steps.find((x) => x.state === "RUNNING") ?? (j.state === "WAITING_HPC" ? j.steps.find((x) => x.step_key === "HPC_WAIT") : undefined);
    return {
      stage_label: STAGE_LABEL[j.job_type],
      current_step_key: cur?.step_key ?? null,
      current_step_label: cur ? this.s.stepLabel(cur.step_key, j.job_type === "PARAM_SET_NATIVE" ? "native" : (j.params as { engine?: string } | null)?.engine) : null,
      hpc_summary: this.hpcSummary(j),
      attention_code: j.attention_code ?? null,
    };
  }

  status(isAdmin: boolean) {
    const latest = this.envChecks[0];
    return {
      features: Object.fromEntries(ALL_FEATURES.map((k) => [k, this.feature(k)])),
      // phase3 §18.6 + opt-native §4.2·§9: 내장 최적화 기본값·알고리즘
      surrogate_opt: {
        defaults: { iterations: 3, candidates: 4, tol_rel: 0.01, surrogate: "gp" }, max_variables: 20, max_iterations: 10, max_candidates: 10,
        max_objectives: 3, max_observe: 10, max_extra_points: 10, algorithms: ["ego", "ga", "nsga2"], default_algorithm: "ego",
        algo_defaults: {
          ga: { pop_size: null, generations: 150, crossover_prob: 0.9, mutation_prob: null, eta_c: 15, eta_m: 20 },
          nsga2: { pop_size: null, generations: 200, crossover_prob: 0.9, mutation_prob: null, eta_c: 20, eta_m: 20 },
        },
        ga_max_evals: 100000, verifications: ["loop", "none"], max_levels: 8,
      },
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
    // S18 §23.8: TD_DOE_GEN은 방식별 기능 판정(platform = train_doe_platform, hyperstudy = train_doe)
    if (type === "TD_DOE_GEN") {
      const bad = checkGeneratorShape(params);
      if (bad) return bad;
    }
    const f = type === "TD_DOE_GEN" && generatorOf(params) === "platform" ? "train_doe_platform" : FEATURE_OF[type];
    if (type === "TD_SOLVE" && !this.s.hpcConfigured) return err(409, "HPC_NOT_CONFIGURED", "PBS 연결이 설정되지 않았습니다.");
    if (type === "SPDM_IMPORT" && this.disabled.has("spdm_import")) return err(409, "SPDM_IMPORT_DISABLED", "SPDM 가져오기가 설정되지 않았습니다.");
    if (f && this.disabled.has(f)) return err(409, f === "train_resp" ? "TEMPLATE_NOT_CONFIGURED" : "RESOURCE_NOT_CONFIGURED", "관리자 설정이 필요합니다.", { missing: FEATURE_MISSING[f] });
    return precheckTrain(this, s, type, params) ?? precheckCuration(this, type, params) ?? precheckOptimize(s, type, params);
  }

  onCreate(j: Job, me: { display_name: string }) {
    onCreateTrain(this, j, me);
    onCreateCuration(this, j, me);
    onCreateOptimize(this, j, me);
  }

  /** RUNNING 중 진행 표시 보정 */
  onProgress(j: Job) {
    onProgressOptimize(this, j);
  }

  /** 완료 처리. "waiting"이면 WAITING_HPC로 전환(TD_SOLVE) */
  finish(j: Job): "done" | "waiting" | "failed" {
    return finishTrain(this, j) ?? finishCuration(this, j) ?? finishOptimize(this, j) ?? "done";
  }

  /** 시간 1단계: PBS run 진행, 환경 점검 진행 */
  tick() {
    tickSolve(this);
    tickEnvChecks(this);
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
