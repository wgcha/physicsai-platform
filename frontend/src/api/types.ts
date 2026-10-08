// API 타입: backend/openapi.json에서 생성한 generated/schema.d.ts(`npm run gen:api`)를 원천으로 쓴다.
// 백엔드 스키마가 `string`으로만 내보내는 열거형 필드는 계약(platform.md §6~§10) 값으로 좁혀서 재노출한다.
// 화면 코드는 이 파일만 import한다.
import type { components } from "./generated/schema";

type S = components["schemas"];
type Override<T, U> = Omit<T, keyof U> & U;

export type Role = "general" | "power" | "admin";

/** 2차 작업 유형(phase2.md §6.1). TODO(openapi): backend/openapi.json 갱신 후 생성 타입에 포함되면 이 합집합 제거 */
export type Phase2JobType =
  | "TD_EXTRACT_PARAMS"
  | "TD_DOE_GEN"
  | "TD_SOLVE"
  | "TD_RESULT_IMPORT"
  | "TD_RESP_EXTRACT"
  | "CU_H3D_PREVIEW"
  | "CU_H3D_CURATE"
  | "CU_T01_PREVIEW"
  | "CU_T01_CURVES"
  | "SPDM_IMPORT"
  | "OPTIMIZE";
export type JobType = S["JobCreate"]["job_type"] | Phase2JobType;
export type JobState =
  | "QUEUED"
  | "RUNNING"
  | "WAITING_HPC"
  | "COLLECTING"
  | "SUCCEEDED"
  | "FAILED"
  | "CANCELED"
  | "INTERRUPTED";
export type StepState = "PENDING" | "RUNNING" | "SUCCEEDED" | "FAILED" | "SKIPPED" | "CANCELED";
/** TODO(openapi): phase2.md §12.4 purpose 추가분 */
export type PathPurpose =
  | S["PathInspectRequest"]["purpose"]
  | "CAD_FILE"
  | "RADIOSS_ASSEM"
  | "RESULT_FOLDER"
  | "CURATION_INPUT"
  | "SPDM_IMPORT";
export type NotificationEvent =
  | "JOB_STARTED"
  | "JOB_SUCCEEDED"
  | "JOB_FAILED"
  | "JOB_CANCELED"
  | "JOB_INTERRUPTED"
  | "MY_TURN_NEXT"
  | "HPC_COLLECTED"
  | "HPC_PARTIAL_FAILED"
  | "ENV_CHECK_DONE";
export type ArtifactKind =
  | "PREVIEW_JSON"
  | "PREVIEW_IMAGE"
  | "CURVE_JSON"
  | "RESPONSE_TABLE"
  | "SCORE_FILE"
  | "PACKAGE_COMMANDS"
  | "SPLIT_JSON"
  | "CURATION_CFG"
  | "FILE_LIST"
  | "DOE_SAMPLES"
  | "RUN_CONFIG"
  | "OPT_SUMMARY"
  | "OPT_FILE";

export const TERMINAL_STATES: JobState[] = ["SUCCEEDED", "FAILED", "CANCELED", "INTERRUPTED"];

export type Me = Override<S["Me"], { roles: Record<string, Role> }>;
export type Project = S["Project"];
export type Health = S["Health"];

/** B1: /status.ui 폴링 주기(ms), /status.auth.login_url */
export interface UiPoll {
  max_artifact_bytes?: number;
  poll_job_running_ms?: number;
  poll_job_queued_ms?: number;
  poll_job_waiting_hpc_ms?: number;
  poll_log_ms?: number;
  poll_queue_ms?: number;
  poll_resources_ms?: number;
  poll_notifications_ms?: number;
  poll_status_ms?: number;
}
/** phase2.md §12.1 `/status.features` 키 */
export type FeatureKey =
  | "train_extract"
  | "train_tpl"
  | "train_doe"
  | "train_solve"
  | "train_import"
  | "train_resp"
  | "curation_h3d"
  | "curation_t01"
  | "spdm_import"
  | "optimize";
export interface FeatureState {
  enabled: boolean;
  missing: string[];
}
export interface EnvCheckBrief {
  latest_id: string | null;
  latest_state: EnvCheckState | null;
  finished_at: string | null;
  fail: number;
  warn: number;
}
// TODO(openapi): features·resources·env_check·hpc.collect_mode는 phase2.md §12.1 기준 임시 정의
export type StatusInfo = Override<
  S["StatusResponse"],
  {
    ui: UiPoll & Record<string, number>;
    auth: { mode?: string; login_url?: string } & Record<string, string>;
    hpc: S["StatusHpc"] & { collect_mode?: "in_place" | "shared_folder" | "drive" | string };
    features?: Partial<Record<FeatureKey, FeatureState>>;
    resources?: { key: string; configured: boolean; ok: boolean }[];
    env_check?: EnvCheckBrief | null;
  }
>;

/** phase2.md §12.9 PBS run 집계 */
export interface HpcSummary {
  total: number;
  queued: number;
  running: number;
  succeeded: number;
  failed: number;
  collected: number;
}
// TODO(openapi): stage_label·current_step_*·hpc_summary는 phase2.md §12.9 기준 임시 정의
export type JobSummary = Override<
  S["JobSummary"],
  {
    job_type: JobType;
    state: JobState;
    lane: "SLOT" | "LIGHT";
    stage_label?: string | null;
    current_step_key?: string | null;
    current_step_label?: string | null;
    hpc_summary?: HpcSummary | null;
  }
>;
export type JobStep = Override<S["JobStep"], { state: StepState; kind: "LOCAL" | "INTERNAL" | "HPC_SUBMIT" | "HPC_WAIT" | "COLLECT" }>;
export type Job = Override<
  S["Job"],
  {
    job_type: JobType;
    state: JobState;
    lane: "SLOT" | "LIGHT";
    steps: JobStep[];
    warnings: { code?: string; message?: string }[];
    /** TODO(openapi): phase2.md §12.3 */
    can_download_error_bundle?: boolean;
    stage_label?: string | null;
    current_step_label?: string | null;
    hpc_summary?: HpcSummary | null;
  }
>;

export interface ResponseRow {
  name: string;
  unit: string | null;
  predicted: number | null;
  nearest_measured: number | null;
  diff_pct: number | null;
}

/** PREDICT `Job.result` (계약 §8.9 + B18) */
export interface PredictResult {
  model_id: string;
  param_set_id: string;
  values: Record<string, number>;
  applied_values: Record<string, number>;
  out_of_range: string[];
  nearest: { run_key: string; distance: number } | null;
  preview_json_artifact_id: string | null;
  image_artifact_ids: string[];
  curve_artifact_id: string | null;
  response_table_artifact_id?: string | null;
  response_table: ResponseRow[];
}

export type QueueInfo = Override<
  S["QueueResponse"],
  {
    running?: JobSummary | null;
    queued: JobSummary[];
    light: { running?: JobSummary | null; queued: JobSummary[] };
    waiting_hpc: JobSummary[];
    collecting: JobSummary[];
  }
>;
export type Resources = S["ResourcesResponse"];

/** B4: stage_status["3"|"4"] */
export interface StageStatus {
  latest_job_id: string | null;
  latest_job_type: JobType | null;
  latest_state: JobState | null;
}

export type Model = Override<
  S["Model"],
  {
    log_status: "PARSED" | "UNRECOGNIZED" | "MISSING";
    eval_status: "NONE" | "RUNNING" | "DONE" | "FAILED";
    eval_score?: EvalScore | null;
    status: "ACTIVE" | "ARCHIVED" | "INVALID";
    loss_curve?: [number, number][] | null;
  }
>;
export interface EvalScore {
  status: "PARSED" | "UNRECOGNIZED";
  metrics: Record<string, number>;
  score_rel: string;
}

export type Study = Override<S["Study"], { status: "ACTIVE" | "ARCHIVED" }>;
export type StudyDetail = Override<
  S["StudyDetail"],
  { status: "ACTIVE" | "ARCHIVED"; final_model?: Model | null; stage_status: Record<string, StageStatus> }
>;

export type PathInspectResult = Override<
  S["PathInspectResponse"],
  {
    summary: {
      h3d_count?: number;
      sample_files?: string[];
      expected_train?: number;
      expected_eval?: number;
      psmdl?: string[];
      pscfg?: string[];
      logs?: string[];
      [k: string]: unknown;
    };
  }
>;

export type Dataset = Override<
  S["Dataset"],
  {
    /** TODO(openapi): phase2.md §12.9 */
    curation_id?: string | null;
    status: "BUILDING" | "READY" | "FAILED";
    split_group: "file" | "parent_dir";
    options: { extract_faces: boolean; extract_mdi: boolean; extract_time_history_vectors: boolean };
  }
>;

export type ParamDef = S["Parameter"];
// TODO(openapi): origin·train_doe_id (phase2.md §12.9)
export type ParamSet = S["ParamSet"] & { origin?: "FOLDER" | "TRAIN_DOE" | null; train_doe_id?: string | null };
export type SampleRow = S["SampleRow"];
export type SamplePage = S["SamplesPage"];
export type PredictCheck = S["PredictCheckResponse"];
export type Artifact = Override<S["Artifact"], { kind: ArtifactKind }>;

export interface CurveJson {
  file: string;
  series: { name: string; x: number[]; y: number[] }[];
  note?: string | null;
}

export type NotificationItem = Override<S["Notification"], { event: NotificationEvent }>;
export type NotificationList = Override<S["NotificationList"], { items: NotificationItem[] }>;
export type LogChunk = S["LogChunk"];

export interface ApiErrorDetail {
  code: string;
  message: string;
  [k: string]: unknown;
}

// ---------------------------------------------------------------------------
// 2차(phase2.md §12) 타입 — TODO(openapi): backend/openapi.json 갱신 후 generated 타입으로 교체
// ---------------------------------------------------------------------------

/** §5.1.1 */
export interface TrainParam {
  name: string;
  raw_nominal: string;
  nominal: number | null;
  min: number | null;
  max: number | null;
  use: boolean;
  format: string;
  unit: string;
  valid: boolean;
  problems: { code?: string; message: string }[] | string[];
}
export interface TrainSetup {
  study_id: string;
  cad: { source_path: string; file_name: string; sha256: string | null; display_path: string } | null;
  extract_job_id: string | null;
  parameters: TrainParam[];
  used_count: number;
  tpl: {
    generated_at: string;
    sha256: string;
    display_path: string;
    params: { var: string; name: string; format: string }[];
    warnings: { code: string; message: string }[];
    stale: boolean;
  } | null;
  version: number;
  updated_by_name: string | null;
  updated_at: string | null;
}
export interface DoeField {
  key: string;
  label: string;
  type: "combo" | "int" | "bool";
  items?: string[];
  default: string | number | boolean;
  min?: number;
  max?: number;
}
export interface DoeType {
  label: string;
  value: string;
  default_runs: number;
  runs_editable: boolean;
  fields: DoeField[];
}
export type TrainRunState = "GENERATED" | "SUBMITTED" | "SOLVED" | "SOLVE_FAILED" | "COLLECTED" | "COLLECT_FAILED";
export type SampleStatus = "PARSED" | "PARTIAL" | "MISSING" | "PENDING";
export interface TrainDoe {
  id: string;
  study_id: string;
  job_id: string;
  status: "BUILDING" | "READY" | "FAILED";
  doe_label: string;
  doe_type: string;
  num_runs_requested: number | null;
  options: Record<string, unknown>;
  multi_execution: number;
  radioss_assem_source_path: string;
  run_count: number | null;
  sample_status: SampleStatus;
  collected_count: number;
  solve_failed_count: number;
  has_run_responses: boolean;
  dir_display_path: string;
  results_display_path: string;
  created_by_name: string;
  created_at: string;
  run_state_counts: Record<TrainRunState, number>;
}
export interface TrainRun {
  run_key: string;
  state: TrainRunState;
  starter_name: string;
  input_display_path: string;
  hpc: { external_job_id: string | null; state: string; attempt_no: number } | null;
  result: { h3d: number; t01: number; files: number; total_bytes: number } | null;
  updated_at: string;
}

/** §4.4 */
export type CurationSourceRef =
  | { kind: "TRAIN_DOE"; doe_id: string }
  | { kind: "SPDM_IMPORT"; import_id: string }
  | { kind: "FOLDER"; path: string };
export interface CurationSource {
  kind: "TRAIN_DOE" | "SPDM_IMPORT";
  ref_id: string;
  label: string;
  display_path: string;
  h3d_count: number;
  t01_count: number;
  runs_expected: number | null;
  created_at: string;
}
export interface Curation {
  id: string;
  study_id: string;
  job_id: string;
  kind: "H3D" | "T01";
  status: "BUILDING" | "READY" | "FAILED";
  source: CurationSourceRef;
  source_label: string;
  preview_job_id: string | null;
  selection: Record<string, unknown>;
  target_count: number;
  ok_count: number;
  failed_count: number;
  missing_runs: string[];
  output_display_path: string;
  used_by_dataset_ids: string[];
  created_by_name: string;
  created_at: string;
}
export interface CurationFile {
  run_folder: string;
  run_key: string | null;
  input_name: string;
  output_name: string | null;
  size: number | null;
  ok: boolean;
  exit_code: number | null;
}
export interface SpdmImport {
  id: string;
  study_id: string;
  job_id: string;
  status: "BUILDING" | "READY" | "FAILED";
  spdm_path: string;
  file_count: number | null;
  total_bytes: number | null;
  renamed_count: number | null;
  dest_display_path: string;
  created_by_name: string;
  created_at: string;
}

/** §6.12 RESPONSES 행 */
export type OptGoal = "NONE" | "MINIMIZE" | "MAXIMIZE" | "CONSTRAINT";
export interface OptResponse {
  name: string;
  source: "H3D" | "XYDATA";
  subcase?: number;
  datatype?: string;
  layer?: string;
  request?: string;
  component: string;
  stat: "MAX" | "MIN" | "ABSMAX";
  goal: OptGoal;
  bound?: "<=" | ">=" | "==";
  value?: number;
}
export interface Optimization {
  id: string;
  study_id: string;
  job_id: string;
  status: "RUNNING" | "DONE" | "FAILED";
  approach: "OPT" | "DOE";
  opt_method: "ARSM" | "GRSM" | "SQP";
  max_designs: number;
  model_id: string;
  model_name: string;
  param_set_id: string;
  study_folder: string;
  runs_started: number | null;
  responses: OptResponse[];
  summary_status: "NONE" | "PARSED" | "UNRECOGNIZED";
  summary_meta: { parser: string; file_rel: string; row_count: number; columns: string[] } | null;
  summary_artifact_id: string | null;
  file_count: number | null;
  file_list_artifact_id: string | null;
  folder_display_path: string;
  created_by_name: string;
  created_at: string;
}
export interface ResponseCandidates {
  source_job_id: string | null;
  h3d: {
    subcases: { id: number; label: string; datatypes: { name: string; components: string[]; layers: string[]; format: string }[] }[];
  } | null;
  xydata: { requests: Record<string, string[]> } | null;
}

/** §12.2 환경 점검 */
export type EnvCheckState = "PENDING" | "RUNNING" | "DONE" | "FAILED" | "EXPIRED";
export type EnvItemStatus = "OK" | "WARN" | "FAIL" | "SKIP" | "PENDING";
export type EnvCategory = "CONFIG" | "DATABASE" | "AUTH" | "HPC" | "WORKER" | "EXECUTABLE" | "RESOURCE" | "STORAGE" | "GPU";
export interface EnvCheckItem {
  key: string;
  category: EnvCategory;
  label: string;
  status: EnvItemStatus;
  message: string;
  source: "API" | "WORKER";
  detail: Record<string, unknown> | null;
}
export interface EnvCheckSummary {
  id: string;
  state: EnvCheckState;
  requested_by_name: string;
  created_at: string;
  finished_at: string | null;
  summary: { ok: number; warn: number; fail: number; skip: number };
}
export interface EnvCheck extends EnvCheckSummary {
  started_at: string | null;
  expires_at: string;
  worker_id: string | null;
  items: EnvCheckItem[];
  failure_message: string | null;
  report_display_path: string | null;
}
