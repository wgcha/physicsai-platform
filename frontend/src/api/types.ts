// 계약 platform.md §10 기준 수작업 타입.
// backend/openapi.json이 생기면 `openapi-typescript`로 src/api/generated/에 생성하고
// 이 파일의 타입을 생성 타입의 별칭으로 바꾼다(화면 코드는 이 파일만 import).

export type Role = "general" | "power" | "admin";

export interface Me {
  user_id: string;
  username: string;
  display_name: string;
  is_global_admin: boolean;
  roles: Record<string, Role>;
}

export interface Project {
  id: string;
  name: string;
  product_name: string | null;
}

export interface StatusInfo {
  config: { ok: boolean; errors: string[] };
  worker: { online: boolean; worker_id: string | null; last_seen_at: string | null; limiter: string | null };
  hpc: { mode: "none" | "command" | "adapter"; configured: boolean; message: string };
  altair: { key: string; ok: boolean }[];
  templates: { key: string; configured: boolean }[];
  limits: { configured: unknown; detected: unknown; effective: unknown };
}

export type JobType =
  | "DATASET_CREATE"
  | "PACKAGE_EXPORT"
  | "MODEL_REGISTER"
  | "EVALUATE"
  | "PREDICT"
  | "PREDICT_VERIFY";

export type JobState =
  | "QUEUED"
  | "RUNNING"
  | "WAITING_HPC"
  | "COLLECTING"
  | "SUCCEEDED"
  | "FAILED"
  | "CANCELED"
  | "INTERRUPTED";

export const TERMINAL_STATES: JobState[] = ["SUCCEEDED", "FAILED", "CANCELED", "INTERRUPTED"];

export interface JobSummary {
  id: string;
  study_id: string;
  project_id: string;
  study_title: string;
  job_type: JobType;
  stage: number;
  lane: "SLOT" | "LIGHT";
  state: JobState;
  created_by: string;
  created_by_name: string;
  queue_position: number | null;
  progress_pct: number | null;
  progress_label: string | null;
  cancel_requested: boolean;
  created_at: string;
  started_at: string | null;
}

export type StepState = "PENDING" | "RUNNING" | "SUCCEEDED" | "FAILED" | "SKIPPED" | "CANCELED";

export interface JobStep {
  step_no: number;
  step_key: string;
  kind: "LOCAL" | "INTERNAL" | "HPC_SUBMIT" | "HPC_WAIT" | "COLLECT";
  state: StepState;
  progress_pct: number | null;
  progress_label: string | null;
  started_at: string | null;
  finished_at: string | null;
  exit_code: number | null;
  failure_code: string | null;
  failure_message: string | null;
}

export interface ResponseRow {
  name: string;
  unit: string | null;
  predicted: number | null;
  nearest_measured: number | null;
  diff_pct: number | null;
}

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
  response_table: ResponseRow[];
  /** 계약에 없는 선택 필드: 입력파일 묶음 artifact(백엔드 확정 시 사용) */
  input_artifact_id?: string | null;
}

export interface Job extends JobSummary {
  params: Record<string, unknown>;
  result: Record<string, unknown> | null;
  warnings: { code: string; message: string }[];
  steps: JobStep[];
  failure_code: string | null;
  failure_message: string | null;
  finished_at: string | null;
  retry_of_job_id: string | null;
  version: number;
  can_cancel: boolean;
  can_retry: boolean;
}

export interface QueueInfo {
  slot: { holder_job_id: string | null; since: string | null };
  running: JobSummary | null;
  queued: JobSummary[];
  light: { running: JobSummary | null; queued: JobSummary[] };
  waiting_hpc: JobSummary[];
  collecting: JobSummary[];
}

export interface Resources {
  sampled_at: string;
  cpu_pct: number;
  ram_used_gb: number;
  ram_total_gb: number;
  gpu: { name: string; util_pct: number; mem_used_mb: number; mem_total_mb: number }[];
  job: { job_id: string; cpu_time_s: number; peak_memory_gb: number } | null;
  limits: { cores: number; cpu_rate: number; memory_gb: number; priority: string; cpu_cap_enforced: boolean };
}

export interface StageStatus {
  last_job_state?: JobState | null;
  [k: string]: unknown;
}

export interface Study {
  id: string;
  project_id: string;
  folder_name: string;
  title: string;
  status: "ACTIVE" | "ARCHIVED";
  final_model_id: string | null;
  created_by: string;
  created_by_name: string;
  created_at: string;
  updated_at: string;
  version: number;
  can_execute: boolean;
  final_model?: Model | null;
  stage_status?: Record<string, StageStatus>;
  current_param_set_id?: string | null;
}

export type PathPurpose = "DATASET_INPUT" | "MODEL_FOLDER" | "PARAM_SET";

export interface PathInspectResult {
  normalized_path: string;
  ok: boolean;
  problems: { code: string; file?: string; message?: string }[];
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

export interface Dataset {
  id: string;
  study_id: string;
  job_id: string;
  status: "BUILDING" | "READY" | "FAILED";
  source_path: string;
  h3d_count: number | null;
  train_count: number | null;
  eval_count: number | null;
  holdout_ratio: number;
  seed: number;
  split_group: "file" | "parent_dir";
  options: { extract_faces: boolean; extract_mdi: boolean; extract_time_history_vectors: boolean };
  package_ready: boolean;
  created_by_name: string;
  created_at: string;
}

export interface EvalScore {
  status: "PARSED" | "UNRECOGNIZED";
  metrics: Record<string, number>;
  score_rel: string;
}

export interface Model {
  id: string;
  study_id: string;
  name: string;
  version: number;
  label: string | null;
  dataset_id: string | null;
  source_path: string;
  log_status: "PARSED" | "UNRECOGNIZED" | "MISSING";
  log_parser: string | null;
  epochs_total: number | null;
  last_epoch: number | null;
  final_loss: number | null;
  min_loss: number | null;
  min_loss_epoch: number | null;
  loss_curve?: [number, number][] | null;
  curve_points?: number;
  eval_status: "NONE" | "RUNNING" | "DONE" | "FAILED";
  eval_score: EvalScore | null;
  status: "ACTIVE" | "ARCHIVED" | "INVALID";
  is_final: boolean;
  registered_by_name: string;
  registered_at: string;
  row_version: number;
}

export interface ParamDef {
  name: string;
  nominal: number;
  min: number;
  max: number;
  unit: string | null;
}

export interface ParamSet {
  id: string;
  study_id: string;
  source_path: string;
  unit_system: string;
  parameters: ParamDef[];
  responses: { name: string; unit: string | null }[];
  sample_count: number;
  sample_has_measured: boolean;
  cad_file_name: string;
  starter_name: string;
  tpl_params: { var: string; name: string; format: string }[];
  is_current: boolean;
  registered_by_name: string;
  registered_at: string;
}

export interface SampleRow {
  run_key: string;
  values: Record<string, number>;
  measured: Record<string, number>;
}

export interface SamplePage {
  columns: string[];
  rows: SampleRow[];
  next_cursor: string | null;
}

export interface PredictCheck {
  out_of_range: { name: string; value: number; min: number; max: number }[];
  rounded: { name: string; value: number; applied: number }[];
  nearest: {
    run_key: string;
    distance: number;
    values: Record<string, number>;
    measured: Record<string, number> | null;
  } | null;
}

export interface Artifact {
  id: string;
  study_id: string;
  job_id: string | null;
  kind:
    | "PREVIEW_JSON"
    | "PREVIEW_IMAGE"
    | "CURVE_JSON"
    | "RESPONSE_TABLE"
    | "SCORE_FILE"
    | "PACKAGE_COMMANDS"
    | "SPLIT_JSON";
  rel_path: string;
  size: number;
  sha256: string | null;
  content_type: string;
  created_at: string;
}

export interface CurveJson {
  file: string;
  series: { name: string; x: number[]; y: number[] }[];
  note?: string | null;
}

export type NotificationEvent =
  | "JOB_STARTED"
  | "JOB_SUCCEEDED"
  | "JOB_FAILED"
  | "JOB_CANCELED"
  | "JOB_INTERRUPTED"
  | "MY_TURN_NEXT"
  | "HPC_COLLECTED";

export interface NotificationItem {
  seq: number;
  event: NotificationEvent;
  job_id: string | null;
  study_id: string | null;
  project_id: string | null;
  title: string;
  body: string;
  created_at: string;
  read_at: string | null;
}

export interface NotificationList {
  items: NotificationItem[];
  max_seq: number;
  unread_count: number;
}

export interface LogChunk {
  text: string;
  next_cursor: number;
  eof: boolean;
  size: number;
}

export interface ApiErrorDetail {
  code: string;
  message: string;
  [k: string]: unknown;
}
