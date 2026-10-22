// API 타입(R-F 분할) — S6 준비된 입력 예측·모델·스터디·파라미터 세트·표본. 화면 코드는 `api/types`만 import한다(거기서 재노출).
import type { S, Override } from "./typesBase";
import type { ArtifactKind, ContourDisplay, InputKind, JobState, JobSummary, JobType, NotificationEvent, TemplateResponse } from "./types";

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
  /** input-kind.md IK-1: 생략 = 서버 기본 */
  input?: "assembly" | "cushion";
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

/** job-queues.md §8.1 `GET /queue`의 `gpu`·`cpu`. schema.d.ts 재생성 전까지 로컬 정의 — 재생성 때 이 두 타입을 schema 것으로 바꾼다 */
export interface GpuQueue {
  limit: number;
  running: JobSummary[];
  queued: JobSummary[];
  since?: string | null;
}
export interface CpuQueue {
  limit: number;
  running: JobSummary[];
  queued: JobSummary[];
  min_free_memory_gb?: number | null;
  /** low = 여유 메모리 부족으로 대기, null = 워커 표본 없음 */
  memory_gate?: "ok" | "low" | null;
}

export type QueueInfo = Override<
  S["QueueResponse"],
  {
    /** v0.2.9 추가(옛 서버 응답에는 없음 — 화면은 없으면 옛 단일 대기열 표시). 아래 running·queued·slot은 deprecated */
    gpu?: GpuQueue;
    cpu?: CpuQueue;
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
/** 세트 파라미터 행: source "prop" = 3S 쉘 두께(prop_id), baselines = 4B baseline별 원 이름·범위 */
export type ParamSetParameter = S["ParamSetParameter"];
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
export type ParamSetCreate = Omit<S["ParamSetCreate"], "shell_only"> & { shell_only?: boolean }; // 서버 기본 false(geometry-engine.md §11.1)
/** discover CAD 후보 — openapi는 dict라 계약(geometry-engine.md §7.4) 키로 좁힌다. native = STEP 파일 또는 parts/ 폴더 */
export interface DiscoverCad {
  rel: string;
  name?: string;
  kind?: string;
  [k: string]: unknown;
}
export type ParamSetDiscover = Override<S["ParamSetDiscoverResponse"], { cad: DiscoverCad[] }>;

// ---------------------------------------------------------------------------
// native 형상 엔진(geometry-engine.md §7.6·§8)
// ---------------------------------------------------------------------------
export type Engine = "altair" | "native";
export type StatusGeometry = S["StatusGeometry"];
export type NativeInfo = S["NativeInfo"];
export type NativeGroup = S["NativeGroup"];
export type NativeWarning = S["NativeWarning"];
/** feasible = {min, max, limited_by?, source?}(§4.3·§11.2) — openapi는 dict라 좁힌다 */
export type NativeFeature = Override<S["NativeFeature"], { feasible?: { min?: number | null; max?: number | null; limited_by?: string | null; source?: string | null } | null }>;
export type NativeFeatures = Override<S["NativeFeatures"], { features: NativeFeature[] }>;
/** geom_options(§4.9) 부분 객체 — 절 이름 → 키 → 값(최상위 문자열 키도 있음) */
export type GeomOptions = Record<string, unknown>;

// ---- 단계 3S 쉘 두께(§11.1)·4B 다중 baseline(§4.10·§7.3.8) — 생성 타입 ----
export type ShellProp = S["ShellProp"];
/** GET /param-sets/{id}/props — 스캔 전이면 scanned=false·빈 목록 */
export type ShellProps = S["ShellProps"];
/** PUT /param-sets/{id}/props 본문(선택 = 파라미터 이름 + min·max, 응답 = ParamSet) */
export type ShellPropsUpdate = S["ShellPropsUpdate"];
export type ShellPropSelect = S["ShellPropSelect"];
export type BaselineInfo = S["BaselineInfo"];
export type BaselineAddRequest = S["BaselineAddRequest"];
export type ParamMapRemapRequest = S["ParamMapRemapRequest"];
export type MapGrade = NonNullable<S["ParamMapProposed"]["grade"]>;
export type MapAction = S["ParamMapDecision"]["action"];
export type MapDecision = S["ParamMapDecision"];
export type MapRowDecision = S["ParamMapRowDecision"];
/** decision은 openapi에서 dict라 ParamMapDecision 모양으로 좁힌다 */
export type MapRow = Override<S["ParamMapRow"], { decision?: MapDecision | null }>;
/** range_split(§4.10 usage=range일 때만) — openapi dict를 계약 모양으로 좁힌다 */
export interface RangeSplit {
  param: string;
  intervals: { baseline: string; nominal: number | null }[];
}
export type ParamMap = Override<S["ParamMap"], { common: MapRow[]; range_split?: RangeSplit | null }>;
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
