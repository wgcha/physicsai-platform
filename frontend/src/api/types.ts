// API 타입: backend/openapi.json에서 생성한 generated/schema.d.ts(`npm run gen:api`)를 원천으로 쓴다.
// 백엔드 스키마가 `string`으로만 내보내는 열거형 필드는 계약(platform.md §6~§10) 값으로 좁혀서 재노출한다.
// 화면 코드는 이 파일만 import한다.
import type { components } from "./generated/schema";

type S = components["schemas"];
type Override<T, U> = Omit<T, keyof U> & U;

export type Role = "general" | "power" | "admin";

export type JobType = S["JobCreate"]["job_type"];
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
export type PathPurpose = S["PathInspectRequest"]["purpose"];
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
export type FeatureKey = keyof S["StatusFeatures"];
export type FeatureState = S["FeatureState"];
/** C10: 비관리자 null, 이력 없으면 값이 모두 null */
export type EnvCheckBrief = Override<S["StatusEnvCheck"], { latest_state?: EnvCheckState | null }>;
export type StatusInfo = Override<
  S["StatusResponse"],
  {
    ui: UiPoll & Record<string, number>;
    auth: { mode?: string; login_url?: string } & Record<string, string>;
    hpc: Override<S["StatusHpc"], { collect_mode: "in_place" | "shared_folder" | "drive" | string }>;
    features?: Partial<S["StatusFeatures"]> | null;
    env_check?: EnvCheckBrief | null;
  }
>;

/** phase2.md §12.9 PBS run 집계(C11): queued·running·succeeded·failed는 hpc 상태별, collected는 회수 완료(succeeded와 겹침) */
export type HpcSummary = S["HpcSummary"];
export type JobSummary = Override<S["JobSummary"], { job_type: JobType; state: JobState; lane: "SLOT" | "LIGHT" }>;
export type JobStep = Override<S["JobStep"], { state: StepState; kind: "LOCAL" | "INTERNAL" | "HPC_SUBMIT" | "HPC_WAIT" | "COLLECT" }>;
export type Job = Override<
  S["Job"],
  {
    job_type: JobType;
    state: JobState;
    lane: "SLOT" | "LIGHT";
    steps: JobStep[];
    warnings: { code?: string; message?: string }[];
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
    status: "BUILDING" | "READY" | "FAILED";
    split_group: "file" | "parent_dir";
    options: { extract_faces: boolean; extract_mdi: boolean; extract_time_history_vectors: boolean };
  }
>;

export type ParamDef = S["Parameter"];
export type ParamSet = Override<S["ParamSet"], { origin: "FOLDER" | "TRAIN_DOE" }>;
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
// 2차(phase2.md §12) — 생성 타입에서 문자열로만 나오는 열거형을 계약 값으로 좁힌다
// ---------------------------------------------------------------------------
type EntityStatus = "BUILDING" | "READY" | "FAILED";

export type TrainParam = S["TrainParamOut"];
export type TrainSetup = Override<S["TrainSetup"], { parameters: TrainParam[]; tpl?: (Override<S["TrainTpl"], { warnings: { code: string; message: string }[] }>) | null }>;
export type DoeField = S["DoeField"];
export type DoeType = S["DoeType"];
export type TrainRunState = keyof S["RunStateCounts"];
export type SampleStatus = "PARSED" | "PARTIAL" | "MISSING" | "PENDING";
export type TrainDoe = Override<S["TrainDoe"], { status: EntityStatus; sample_status: SampleStatus }>;
export type TrainRun = Override<S["TrainRun"], { state: TrainRunState }>;

/** §4.4 */
export type CurationSourceRef =
  | { kind: "TRAIN_DOE"; doe_id: string }
  | { kind: "SPDM_IMPORT"; import_id: string }
  | { kind: "FOLDER"; path: string };
export type CurationSource = Override<S["CurationSource"], { kind: "TRAIN_DOE" | "SPDM_IMPORT" }>;
export type Curation = Override<S["Curation"], { kind: "H3D" | "T01"; status: EntityStatus; source: CurationSourceRef }>;
export type CurationFile = S["CurationFile"];
export type SpdmImport = Override<S["SpdmImport"], { status: EntityStatus }>;

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
export type Optimization = Override<
  S["Optimization"],
  { status: "RUNNING" | "DONE" | "FAILED"; approach: "OPT" | "DOE"; opt_method: "ARSM" | "GRSM" | "SQP"; responses: OptResponse[]; summary_status: "NONE" | "PARSED" | "UNRECOGNIZED" }
>;
export type ResponseCandidates = S["ResponseCandidates"];

/** §12.2 환경 점검 */
export type EnvCheckState = "PENDING" | "RUNNING" | "DONE" | "FAILED" | "EXPIRED";
export type EnvCheckItem = Override<S["EnvCheckItem"], { detail?: Record<string, unknown> | null }>;
export type EnvItemStatus = EnvCheckItem["status"];
export type EnvCategory = EnvCheckItem["category"];
export type EnvCheckSummary = Override<S["EnvCheckSummary"], { state: EnvCheckState }>;
export type EnvCheck = Override<S["EnvCheck"], { state: EnvCheckState; items: EnvCheckItem[] }>;
