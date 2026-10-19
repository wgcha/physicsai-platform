// API 타입: backend/openapi.json에서 생성한 generated/schema.d.ts(`npm run gen:api`)를 원천으로 쓴다.
// 백엔드 스키마가 `string`으로만 내보내는 열거형 필드는 계약(platform.md §6~§10) 값으로 좁혀서 재노출한다.
// 화면 코드는 이 파일만 import한다.
import type { components } from "./generated/schema";

type S = components["schemas"];
type Override<T, U> = Omit<T, keyof U> & U;

export type Role = "general" | "power" | "admin";

// S10: 다시 캡처 작업 CONTOUR_RECAPTURE는 POST /jobs/{id}/capture 전용이라 JobCreate 열거에 없다(phase3.md §15.4)
// S13: 내장 최적화 반복 SURROGATE_OPT는 종료 훅·서비스만 만든다(phase3.md §18.4)
// S16 V2: FEM_VERIFY는 FEM 검증 API·종료 훅만 만든다(POST /jobs 불가, phase3 §21.3.5)
export type JobType = S["JobCreate"]["job_type"] | "CONTOUR_RECAPTURE" | "SURROGATE_OPT" | "FEM_VERIFY";
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
// S16 V2: FEM_ASSEMBLY(조립 원본 폴더 확인, phase3 §21.3.8) — BE-V2 openapi 반영 전에도 같은 값으로 보낸다
export type PathPurpose = S["PathInspectRequest"]["purpose"] | "FEM_ASSEMBLY";
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
  | "HPC_CANCEL_FAILED"
  // S9(phase3.md §14.3) — 알림 event는 백엔드 스키마가 string이라 계약 값으로 좁힌다
  | "PREDICT_BATCH_DONE"
  // S16 V2(phase3.md §21.3.9)
  | "FEM_VERIFY_DONE";
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
  | "OPT_FILE"
  // S10(phase3.md §15.2) — 산출물 kind는 백엔드 스키마가 string
  | "CONTOUR_IMAGE"
  | "CONTOUR_VIDEO";

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
// S16 V2(phase3 §21.3.8): /status.features.fem_verify·fem_verify_rebuild — BE-V2 openapi 반영 전에도 같은 키로 읽는다
export type FeatureKey = keyof S["StatusFeatures"] | "fem_verify" | "fem_verify_rebuild";
export type FeatureState = S["FeatureState"];
/** C10: 비관리자 null, 이력 없으면 값이 모두 null */
export type EnvCheckBrief = Override<S["StatusEnvCheck"], { latest_state?: EnvCheckState | null }>;
export type StatusInfo = Override<
  S["StatusResponse"],
  {
    ui: UiPoll & Record<string, number>;
    auth: { mode?: string; login_url?: string } & Record<string, string>;
    hpc: Override<S["StatusHpc"], { collect_mode: "in_place" | "shared_folder" | "drive" | string }>;
    features?: Partial<Record<FeatureKey, S["FeatureState"] | null>> | null;
    env_check?: EnvCheckBrief | null;
  }
>;

/** phase2.md §12.9 PBS run 집계(C11): queued·running·succeeded·failed는 hpc 상태별, collected는 회수 완료(succeeded와 겹침) */
export type HpcSummary = S["HpcSummary"];
/** `JobSummary.batch`(phase3.md §14.5, params에서 계산). doe_no = 하위 PREDICT의 DOE 번호(부모 PREDICT_BATCH는 null) */
export type JobBatchRef = S["JobBatchRef"];
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
  /** S10 방향별 캡처(§15.2, 없으면 캡처 전 결과) — 결과는 자유 형식이라 수동 유지 */
  media?: ResultMedia[] | null;
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
  /** prepared 입력 종류(§11.5) */
  input_kind?: "file" | "dir";
  /** S9 템플릿 종류(§14.4, 서버 확정 기록, D3-51: 키 이름 template_kind) — params는 자유 형식이라 수동 유지 */
  template_kind?: InputKind | null;
  starter_name?: string | null;
  model_id?: string | null;
  /** S9 일괄 예측 하위(워커만 기록) */
  batch_run?: { batch_id: string; doe_no: number } | null;
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
// responses[].spec(§14.6)·display(§15.3)는 백엔드 스키마가 dict라 계약 형식으로 좁힌다
export type ParamSet = Override<
  S["ParamSet"],
  {
    origin: "FOLDER" | "TRAIN_DOE";
    starter_name: string | null;
    /** 등록 응답에만(SIMLAB_EXPORT_NAME 등), 조회는 [] */
    warnings?: S["ParamSet"]["warnings"];
    responses: TemplateResponse[];
    /** S10 컨투어 표시 설정(없으면 서버 기본) */
    display?: ContourDisplay | null;
  }
>;
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
/** S15(§20.6): desc_id = 설명문 id(없으면 null), recommended = 설정 train_data.recommended_doe_type 항목 하나, influence_class = 영향도 등급 */
export type DoeType = S["DoeType"];
export type TrainRunState = keyof S["RunStateCounts"];
export type SampleStatus = "PARSED" | "PARTIAL" | "MISSING" | "PENDING";
export type TrainDoe = Override<S["TrainDoe"], { status: EntityStatus; sample_status: SampleStatus }>;
export type TrainRun = Override<S["TrainRun"], { state: TrainRunState }>;

/** phase3 §16.5·§16.9: HPC 행(GET /jobs/{id}/hpc-jobs). scx 필드(gateway_mode·remote_dir·submission_unknown·resolve_pending)는 선택 */
export type HpcJob = S["HpcJob"];
export type HpcResolveAction = S["HpcResolveRequest"]["action"];

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

// phase3.md §12 S7(D3-46) 서버 경로 탐색
export type FsRoot = S["FsRoot"];
export type FsRoots = S["FsRoots"];
export type FsEntry = S["FsEntry"];
export type FsList = S["FsList"];

// ---------------------------------------------------------------------------
// S9 템플릿 예측·DOE 일괄 예측·응답 추출(phase3.md §14) — 생성 타입 기반, 열거형·dict 필드만 계약 값으로 좁힘
// ---------------------------------------------------------------------------

/** 템플릿 입력 종류: 조립 폴더 포함(assembly) / 쿠션 단독 메시(mesh_only) */
export type InputKind = "mesh_only" | "assembly";
/** ④ 화면 입력 방식(localStorage `physicsai.stage4.inputMode`) */
export type InputMode = "template" | "batch" | "prepared";

export type ResponseStat = "MAX" | "MIN" | "ABSMAX";
/** 응답 정의 spec(§14.6, ⑤ OPTIMIZE.responses의 H3D 형식, goal·bound 없음) */
export interface H3dResponseSpec {
  source: "H3D";
  subcase: number;
  datatype: string;
  component: string;
  layer: string;
  stat: ResponseStat;
}
/** S17 §22.3.1 성능 정의 CURVE: 예측 run curve.json 계열 1개의 대표값. series null = 그 run의 첫 계열 */
export interface CurveResponseSpec {
  source: "CURVE";
  series: string | null;
  stat: ResponseStat;
}
export type ResponseSpec = H3dResponseSpec | CurveResponseSpec;
/** spec은 백엔드 스키마가 dict라 계약 형식으로 좁힌다. spec null = 이름·단위만(추출 안 함, D3-51) */
export type TemplateResponse = Override<S["ResponseDef"], { unit: string; spec?: ResponseSpec | null }>;
/** PUT /param-sets/{id}/responses 본문(백엔드 스키마는 dict 목록). spec null = 이름·단위만(추출 안 함) */
export interface ParamSetResponsesPut {
  responses: { name: string; unit: string; spec: ResponseSpec | null }[];
}

/** S15(§20.6): 10개 kind(기존 lhs·table·train_doe + 7개) — 생성 타입의 discriminated union */
export type BatchSource = S["PredictBatchPreviewRequest"]["source"];
export type BatchSourceKind = BatchSource["kind"];

/** 영향도 등급(§20.7): formal 정식 · reference 참고용(회색 안내) · off 비활성(사유) */
export type InfluenceClass = S["DoeResultTable"]["influence_class"];
/** 표본 방식 요약(미리보기·배치 상세 `sampling`). 서버가 등급을 정한다(formal·reference) */
export type BatchSampling = S["SamplingInfo"];
/** GET /studies/{id}/predict-batches 행의 `sampling` */
export type BatchSamplingBrief = S["SamplingSummary"];
/** 미리보기 `notes[]`(막지 않는 안내, §20.9) */
export type BatchNote = S["BatchNote"];

/** POST /studies/{id}/predict-batches/preview 본문 */
export type BatchPreviewRequest = Override<S["PredictBatchPreviewRequest"], { param_set_id: string; source: BatchSource }>;
export type BatchPreviewRow = S["BatchPreviewRow"];
export type BatchProblemCode =
  | "TABLE_HEADER" | "TABLE_VALUE" | "TEXT_TOO_LARGE" | "TOO_MANY_ROWS" | "TOO_FEW_ROWS" | "RANGE_INVALID" | "DOE_PARAM_MISMATCH"
  | "COUNT_NOT_POW2" | "CONTINUE_INVALID" | "SEQUENCE_MISMATCH" | "LEVELS_INVALID" | "DESIGN_UNSUPPORTED" | "GENERATOR_UNAVAILABLE";
export type BatchProblem = S["BatchProblem"];
/** estimate_min = 최근 성공 PREDICT 5개 중앙값×N(분), 없으면 null */
export type BatchPreview = S["PredictBatchPreview"];
/** PREDICT_BATCH 생성 params(POST /studies/{id}/jobs) — 작업 params는 dict라 생성 타입 없음(phase3.md §14.5·§15.3) */
export interface PredictBatchParams {
  param_set_id: string;
  model_id: string | null;
  multi_execution: number;
  source: BatchSource;
  /** S10 §15.3: 배치 단위 표시 설정(범례 fixed로 run끼리 비교) */
  display?: { legend: ContourLegend } | null;
  /** D3-53: 하위 예측 컨투어 캡처 옵션(없으면 기본 — 템플릿 display.views·config capture) */
  capture?: PredictBatchCapture | null;
}
/** D3-53: enabled false → 하위 CONTOUR_CAPTURE SKIPPED. views·video 생략 = 기본 */
export interface PredictBatchCapture {
  enabled: boolean;
  views?: ViewKey[];
  video?: boolean;
}

export type BatchStatus = "GENERATING" | "PREDICTING" | "DONE" | "FAILED" | "CANCELED";
export type PredictBatchSummary = Override<S["PredictBatchSummary"], { status: BatchStatus }>;
export type BatchRowState = "GEN_PENDING" | "GENERATING" | "GEN_FAILED" | "QUEUED" | "RUNNING" | "SUCCEEDED" | "FAILED" | "CANCELED";
/** media_views = S10 캡처된 방향(없으면 빈 배열) */
export type PredictBatchRow = Override<S["BatchRunRow"], { state: BatchRowState; media_views?: ViewKey[] }>;
export type PredictBatch = Override<S["PredictBatch"], { status: BatchStatus; rows: PredictBatchRow[] }>;
/** GET /predict-batches/{bid}/curves */
export type BatchCurves = S["BatchCurves"];
/** POST /predict-batches/{bid}/retry-failed → 201 */
export type BatchRetryFailed = S["BatchRetryFailed"];

// ---------------------------------------------------------------------------
// S10 컨투어 캡처(HyperView 방향별 PNG + 애니메이션 동영상, phase3.md §15) — 생성 타입 기반
// ---------------------------------------------------------------------------

/** 방향 키(기본 iso·front·top·right). 서버가 더 주면 그대로 표시 */
export type ViewKey = "iso" | "front" | "back" | "top" | "bottom" | "left" | "right" | (string & {});

/** PREDICT `result.media[]`(§15.2 — result는 dict라 생성 타입 없음) */
export interface ResultMedia {
  view: ViewKey;
  image_artifact_id: string;
  video_artifact_id: string | null;
}

/** 파일 1개(url = 표시용 Range 지원, download_url = 내려받기) */
// S16 V3(§21.4.5): playable·codec·transcoded·video_error — BE-V3 openapi 반영 전에도 같은 모양으로 읽는다
export type MediaFile = Omit<S["MediaFile"], "playable" | "codec" | "transcoded"> & { playable?: boolean | null; codec?: string | null; transcoded?: boolean };
export type MediaItem = Override<S["MediaItem"], { view: ViewKey; image: MediaFile; video?: MediaFile | null; video_error?: string | null }>;
/** NONE(캡처 전·step 없음) · SKIPPED(미구성) · OK · PARTIAL · FAILED */
export type MediaStatus = "NONE" | "SKIPPED" | "OK" | "PARTIAL" | "FAILED";
export type ContourLegend = S["CaptureLegendOut"];
/** 템플릿(파라미터 세트) 컨투어 표시 설정(PUT /param-sets/{id}/display 본문 `display`) */
export type ContourDisplay = Override<S["CaptureDisplayOut"], { views: ViewKey[] }>;
/** GET /jobs/{id}/media */
export type JobMedia = Override<S["JobMedia"], { status: MediaStatus; items: MediaItem[]; display?: ContourDisplay | null }>;
/** POST /jobs/{id}/capture 본문(→ 201 Job CONTOUR_RECAPTURE) */
export type CaptureRequest = S["RecaptureRequest"];
