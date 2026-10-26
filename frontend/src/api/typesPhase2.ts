// API 타입(R-F 분할) — 2차(phase2.md §12) 학습·DOE·HPC·큐레이션·최적화·환경 점검·저장소·파일 탐색. `api/types`가 재노출.
import type { S, Override } from "./typesBase";
import type { JobState } from "./types";

// ---------------------------------------------------------------------------
// 2차(phase2.md §12) — 생성 타입에서 문자열로만 나오는 열거형을 계약 값으로 좁힌다
// ---------------------------------------------------------------------------
type EntityStatus = "BUILDING" | "READY" | "FAILED";

export type TrainParam = S["TrainParamOut"];
export type TrainSetup = Override<S["TrainSetup"], { parameters: TrainParam[]; extract_filter?: ExtractFilter | null; tpl?: (Override<S["TrainTpl"], { warnings: { code: string; message: string; names?: string[] }[] }>) | null }>;
export type TplSummary = S["TplSummary"];
/** extract-filter.md §6.1: native ①-1·④ 추출 조건(찾을 종류 그룹 + 조건 mm·mm²·°). 응답에서는 서버 정규화본 */
// rib-gap.md RG-10: 그룹 `rib_pitch`(리브 간격)는 생성 스키마 열거값에 있다
export type ExtractGroup = S["ExtractFilter"]["groups"][number];
export type ExtractFilter = S["ExtractFilter"];
/** 422 EXTRACT_FILTER_INVALID problems[] — key = groups | conditions.<키>[.min|.max] | draft_max_deg */
export interface ExtractProblem {
  key: string;
  message: string;
}
export type DoeField = S["DoeField"];
/** S15(§20.6): desc_id = 설명문 id(없으면 null), recommended = 설정 train_data.recommended_doe_type 항목 하나, influence_class = 영향도 등급 */
export type DoeType = S["DoeType"];
export type TrainRunState = keyof S["RunStateCounts"];
export type SampleStatus = "PARSED" | "PARTIAL" | "MISSING" | "PENDING";
/** S18(§23.4): generator = 생성 방식(기본 hyperstudy), sampling = 플랫폼 표본 요약(desc_id `td_<kind>`), gen = run별 생성 상태 집계(platform만) */
export type DoeGenerator = S["TrainDoe"]["generator"];
export type DoeGenCounts = S["TrainDoeGenCounts"];
export type DoeSamplingBrief = S["TrainDoeSampling"];
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
