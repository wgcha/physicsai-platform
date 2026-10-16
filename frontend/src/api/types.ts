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
  | "ENV_CHECK_DONE"
  | "HPC_CANCEL_FAILED";
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
  // S6 prepared 결과 키(phase3.md §11.5) — openapi에서 결과는 자유 형식이라 수동 유지
  input_mode?: PredictInputMode;
  input_path?: string | null;
}

// ---------------------------------------------------------------------------
// S6 ④ 준비된 입력 예측(phase3.md §11.5)
// openapi에서 Job params·inspect summary는 자유 형식(dict)이라 아래 타입은 수동 유지(백엔드 구현과 일치 확인)
// ---------------------------------------------------------------------------
export type PredictInputMode = "parametric" | "prepared";

/** PREDICT 요청 params — parametric(기본, input_mode 생략 = parametric) */
export interface PredictParamsParametric {
  input_mode?: "parametric";
  param_set_id: string | null;
  model_id: string | null;
  values: Record<string, number>;
  value_source: "nominal" | "run" | "manual";
  source_run_key: string | null;
  input_path?: null;
}
/** PREDICT 요청 params — prepared */
export interface PredictParamsPrepared {
  input_mode: "prepared";
  input_path: string;
  model_id?: string | null;
  param_set_id?: string | null;
}
export type PredictParams = PredictParamsParametric | PredictParamsPrepared;

/** 저장된 PREDICT `Job.params`(prepared는 정규화 경로·종류·starter 이름이 붙는다) */
export interface PredictJobParams {
  input_mode?: PredictInputMode;
  input_path?: string | null;
  input_kind?: "file" | "dir";
  starter_name?: string | null;
  model_id?: string | null;
  param_set_id?: string | null;
  values?: Record<string, number>;
}

export type PredictInputProblemCode = "INPUT_EXT" | "STARTER_COUNT" | "FILE_NAME_UNSAFE" | "TOO_MANY_FILES" | "TOO_LARGE";
export interface PredictInputProblem {
  code: PredictInputProblemCode | string;
  message: string;
}

/** paths/inspect `purpose:"PREDICT_INPUT"` 결과 — problems 외 키는 `summary` 안, problems는 응답 최상위(phase3 D3-30) */
export interface PredictInputInspect {
  kind: "file" | "dir";
  starter: string[];
  starter_ok: boolean;
  /** 최대 50개 */
  rad: string[];
  inc_count: number;
  file_count: number;
  total_bytes: number;
  /** 복사 대상 폴더의 직계 하위 폴더 수(복사 안 함), .hm이면 0 — phase3 D3-43 */
  subdir_count?: number;
  /** 폴더 직계에 starter가 0개일 때 1단계 하위 폴더의 starter 후보(상대경로, 최대 10) — 안내 전용, 실행에 안 씀(D3-44) */
  starter_hints?: string[];
  problems: PredictInputProblem[];
}

/** 422 `PREDICT_INPUT_INVALID` 오류 본문 */
export interface PredictInputInvalidDetail extends ApiErrorDetail {
  code: "PREDICT_INPUT_INVALID";
  problems: PredictInputProblem[];
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
export type ParamSetCreate = S["ParamSetCreate"];
export type ParamSetDiscover = S["ParamSetDiscoverResponse"];
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

/** phase3.md §5.6 Study 용량·정리 */
export type CategoryKey = S["StorageCategory"]["key"];
export type StorageItem = S["StorageItem"];
export type StorageCategory = S["StorageCategory"];
export type StorageScan = S["StorageScan"];
export type CleanupSummary = Override<S["CleanupSummary"], { state: JobState }>;
export type StorageReport = Override<S["StorageReport"], { last_cleanup?: CleanupSummary | null }>;
