// API 타입: backend/openapi.json에서 생성한 generated/schema.d.ts(`npm run gen:api`)를 원천으로 쓴다.
// 백엔드 스키마가 `string`으로만 내보내는 열거형 필드는 계약(platform.md §6~§10) 값으로 좁혀서 재노출한다.
// 화면 코드는 이 파일만 import한다.
import type { ResultMedia } from "./typesMedia";
import type { PredictInputMode } from "./typesPredict";
import type { EnvCheckState } from "./typesPhase2";
import type { Override, S } from "./typesBase";

export type Role = "general" | "power" | "admin";

// S10: 다시 캡처 작업 CONTOUR_RECAPTURE는 POST /jobs/{id}/capture 전용이라 JobCreate 열거에 없다(phase3.md §15.4)
// S13: 내장 최적화 반복 SURROGATE_OPT는 종료 훅·서비스만 만든다(phase3.md §18.4)
// S16 V2: FEM_VERIFY는 FEM 검증 API·종료 훅만 만든다(POST /jobs 불가, phase3 §21.3.5)
// native 세트 등록·다시 준비 PARAM_SET_NATIVE는 param-sets API 전용(geometry-engine.md §7.3.4)
// 결과 3D 컨투어 CONTOUR_3D는 POST /contour3d 전용(geometry-view.md §13.5, CPU 대기열 — 대기열 화면에 표시, contour3d-default C3D-13)
// 형상 미리보기 GEOM_PREVIEW·조립 매칭 ASM_MATCH는 PREVIEW 레인(대기열 화면 밖, 작업 목록은 "미리보기 포함" 필터) — 화면 라벨·단계는 lib/format.ts
// ⑤ 등가성 판정 EQ_CHECK는 /studies/{id}/equiv-checks API 전용(equiv-check.md §4.5)
export type JobType = S["JobCreate"]["job_type"] | "CONTOUR_RECAPTURE" | "SURROGATE_OPT" | "FEM_VERIFY" | "PARAM_SET_NATIVE" | "EQ_CHECK" | "CONTOUR_3D" | "ASM_MATCH" | "GEOM_PREVIEW";
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
  | "FEM_VERIFY_DONE"
  // equiv-check.md §4.5
  | "EQ_CHECK_DONE";
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
  | "CONTOUR_VIDEO"
  // geometry-engine.md §7.5 피처 하이라이트 PNG
  | "FEATURE_PNG"
  // geometry-view.md §2.3: 형상 3D 뷰·미리보기·결과 3D 컨투어(GLB·manifest·프레임)
  | "GEOM_VIEW_GLB"
  | "GEOM_VIEW_MANIFEST"
  | "GEOM_PREVIEW_GLB"
  | "GEOM_PREVIEW_FE_GLB"
  | "GEOM_PREVIEW_MANIFEST"
  | "CONTOUR3D_GLB"
  | "CONTOUR3D_FRAMES"
  | "CONTOUR3D_MANIFEST"
  // contour3d-field §5.6(v0.2.10): 변위 파일·저해상도 메시
  | "CONTOUR3D_DISP"
  | "CONTOUR3D_LOD";

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
// opt-native §4.2: legacy는 true일 때만 온다(HyperStudy 레거시 기능 train_doe·optimize)
export type FeatureState = Override<S["FeatureState"], { legacy?: boolean }>;
/** C10: 비관리자 null, 이력 없으면 값이 모두 null */
export type EnvCheckBrief = Override<S["StatusEnvCheck"], { latest_state?: EnvCheckState | null }>;
export type StatusInfo = Override<
  S["StatusResponse"],
  {
    ui: UiPoll & Record<string, number>;
    auth: { mode?: string; login_url?: string } & Record<string, string>;
    hpc: Override<S["StatusHpc"], { collect_mode: "in_place" | "shared_folder" | "drive" | string }>;
    features?: Partial<Record<FeatureKey, FeatureState | null>> | null;
    env_check?: EnvCheckBrief | null;
  }
>;

/** phase2.md §12.9 PBS run 집계(C11): queued·running·succeeded·failed는 hpc 상태별, collected는 회수 완료(succeeded와 겹침) */
export type HpcSummary = S["HpcSummary"];
/** `JobSummary.batch`(phase3.md §14.5, params에서 계산). doe_no = 하위 PREDICT의 DOE 번호(부모 PREDICT_BATCH는 null) */
export type JobBatchRef = S["JobBatchRef"];
/** job-queues.md §8.1·JQ-10: 현재 대기열 CPU|GPU|LIGHT|PREVIEW(schema는 string — 좁힘). SLOT은 서버가 더 이상 내보내지 않는다(deprecated) — 목 엔진 내부 레인·옛 응답 호환용으로만 남긴다 */
export type JobLane = "SLOT" | "CPU" | "GPU" | "LIGHT" | "PREVIEW";
/** `resumed`·`segments`는 schema JobSummary 필드(T17 재진입 대기 표시, job-queues.md §8.1) */
export type JobSummary = Override<S["JobSummary"], { job_type: JobType; state: JobState; lane: JobLane }>;
export type JobStep = Override<S["JobStep"], { state: StepState; kind: "LOCAL" | "INTERNAL" | "HPC_SUBMIT" | "HPC_WAIT" | "COLLECT" }>;
export type Job = Override<
  S["Job"],
  {
    job_type: JobType;
    state: JobState;
    lane: JobLane;
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

// R-F 분할: 아래 파일의 타입을 그대로 재노출한다(옛 `import ... from "../api/types"` 경로 유지, 동작 불변)
export * from "./typesPredict";
export * from "./typesPhase2";
export * from "./typesBatch";
export * from "./typesAsmMatch";
export * from "./typesMedia";
export * from "./typesGeomView";
export * from "./typesVars";
export * from "./typesTokens";

/** 플랫폼 버전·버전 게시판(읽기 전용 — 배포 RELEASES.md로만 기록) */
export type VersionInfo = S["VersionInfo"];
export type ReleaseEntry = S["ReleaseEntry"];
export type ReleasesResponse = S["ReleasesResponse"];
