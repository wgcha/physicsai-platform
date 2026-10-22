// S16 V2(phase3 §21.3.8): 조립 상태 FEM 검증 API. 새 파일 — endpoints.ts·index.ts는 고치지 않는다(§21.7).
// 타입은 계약 모양으로 고정한다(BE-V2 openapi 반영 뒤 `lint`로 생성 타입과의 차이를 확인).
import { fetchBlob, request, requestPage } from "./client";
import type { ContourDisplay, FsRoots, JobSummary, MediaFile, PathInspectResult, PredictInput } from "./types";

export type FvStatus = "WAITING_PREDICT" | "RUNNING" | "DONE" | "FAILED" | "CANCELED";
export const FV_ACTIVE: FvStatus[] = ["WAITING_PREDICT", "RUNNING"];
export const isFvActive = (s: string) => (FV_ACTIVE as string[]).includes(s);

export type FemSourceReq =
  | { kind: "predict_job"; job_id: string }
  | { kind: "batch_run"; batch_id: string; doe_no: number }
  | { kind: "values"; param_set_id: string; model_id?: string | null; values: Record<string, number>; reuse_existing?: boolean; origin?: { kind: "optimize"; job_id: string } | null; input?: PredictInput }
  | { kind: "opt_design"; opt_id: string; pick: "best" | "final_optimum" | "surrogate_optimum" | "run"; iter_no?: number; doe_no?: number };

/** template = 출처 템플릿의 조립 폴더(input-kind.md §8 — 조립 가능 템플릿의 쿠션 실행 기본값) */
export type FemAssemblyReq = { kind: "predict_input" } | { kind: "train_doe"; doe_id: string } | { kind: "custom"; path: string } | { kind: "template" };

export interface FemVerifyCreate {
  source: FemSourceReq;
  /** null = 기본(§21.3.3) */
  assembly: FemAssemblyReq | null;
  fem?: { field: string | null; component: string | null; comps: string[] | null };
  display?: Partial<ContourDisplay> | null;
  hpc?: { queue: string | null; ncpus: number | null; walltime: string | null; version?: string | null } | null;
}

export interface FemProblem {
  code: string;
  message: string;
}

/** plan_assembly 요약(preview.assembly · paths/inspect FEM_ASSEMBLY summary 공통) */
export interface AssemblyPlan {
  kind?: string;
  label?: string;
  path?: string;
  starter: string | null;
  rad: string[];
  inc_count: number;
  renum_csv: boolean;
  include_baseline: boolean;
  include_referenced: boolean | null;
  file_count: number;
  total_bytes: number;
  starter_candidates?: string[];
  problems?: FemProblem[];
  warnings?: FemProblem[];
}

export interface FemDesign {
  param_set: { id: string; label: string | null; input_kind: string } | null;
  /** input-kind.md IK-8: 검증 대상 설계의 입력 종류 */
  input?: PredictInput;
  model: { id: string; name: string; version: number } | null;
  values: Record<string, number>;
  applied_values: Record<string, number>;
  out_of_range: string[];
}

export interface FemPreview {
  source_label: string;
  design: FemDesign;
  predict: { job_id: string | null; state: string | null; reuse: boolean; will_run: boolean; created_at?: string | null };
  input_mode: "reuse" | "rebuild";
  mesh: { path: string; available: boolean } | null;
  assembly: AssemblyPlan | null;
  fem_field: string | null;
  comps_auto: string[];
  hpc_mode: "command" | "scx";
  problems: FemProblem[];
  warnings: FemProblem[];
}

export interface FemVerifySummary {
  id: string;
  /** FV-003 */
  label: string;
  status: FvStatus;
  source_label: string;
  source_kind: "PREDICT_JOB" | "BATCH_RUN" | "VALUES" | "OPT_DESIGN";
  links: { predict_job_id: string | null; batch_id: string | null; doe_no: number | null; opt_id: string | null };
  max_abs_diff_pct: number | null;
  worst: string | null;
  created_at: string;
  created_by_name: string;
  finished_at: string | null;
  /** 목록 표용 설계점 값(서버는 없으면 {}) */
  values: Record<string, number>;
}

export interface FemResponseRow {
  name: string;
  unit: string;
  stat: "MAX" | "MIN" | "ABSMAX" | string;
  pred_min: number | null;
  pred_max: number | null;
  fem_min: number | null;
  fem_max: number | null;
  pred_value: number | null;
  fem_value: number | null;
  diff: number | null;
  diff_pct: number | null;
  note: string | null;
}

export interface FemLegend {
  mode: "auto" | "fixed";
  min: number | null;
  max: number | null;
  source: string | null;
  note: string | null;
}

export interface FemCompare {
  responses: FemResponseRow[];
  max_abs_diff_pct: number | null;
  worst: string | null;
  legend: FemLegend | null;
  curve: { status: "OK" | "SKIPPED" | "FAILED"; message: string | null; names: string[]; unmatched_pred: string[]; unmatched_fem: string[] };
  media: { pred_status: string; fem_status: string };
}

export interface FemVerification extends Omit<FemVerifySummary, "source_label" | "source_kind"> {
  status_text: string;
  source: { kind: FemVerifySummary["source_kind"]; label: string };
  design: FemDesign;
  predict: { job_id: string | null; state: string | null; companion: boolean; reuse: boolean; will_run: boolean };
  assembly: { kind: "PREDICT_INPUT" | "TRAIN_DOE" | "CUSTOM"; label: string; path: string | null; snapshot_dir: string | null };
  input_mode: "reuse" | "rebuild";
  attempt_no: number;
  dir: string | null;
  paths: { input_dir: string | null; result_dir: string | null; starter: string | null; remote_dir: string | null };
  job: JobSummary | null;
  compare: FemCompare | null;
  warnings: FemProblem[];
  failure: FemProblem | null;
  can_cancel: boolean;
  can_rerun: boolean;
  /** 사용한 hpc 모드(진행 4단·SCX 상태 표시용) */
  hpc_mode?: "command" | "scx";
}

export interface FemMediaSide {
  image: MediaFile;
  video: MediaFile | null;
  video_error: string | null;
}
export interface FemMedia {
  status: string;
  display: ContourDisplay | null;
  legend: FemLegend | null;
  items: { view: string; label: string; pred: FemMediaSide | null; fem: FemMediaSide | null }[];
}

export interface FemCurves {
  names: string[];
  name: string | null;
  pred: { x: number[]; y: number[] } | null;
  fem: { x: number[]; y: number[] } | null;
  downsampled: boolean;
}

export interface FemListQuery {
  predict_job_id?: string;
  batch_id?: string;
  opt_id?: string;
  status?: string;
  limit?: number;
  cursor?: string | null;
}

export const femVerifyApi = {
  preview: (studyId: string, body: FemVerifyCreate) => request<FemPreview>("POST", `/studies/${studyId}/fem-verifications/preview`, { body }),
  create: (studyId: string, body: FemVerifyCreate) => request<FemVerification>("POST", `/studies/${studyId}/fem-verifications`, { body }),
  list: (studyId: string, q: FemListQuery = {}) => requestPage<FemVerifySummary[]>(`/studies/${studyId}/fem-verifications`, { ...q }),
  get: (fid: string) => request<FemVerification>("GET", `/fem-verifications/${fid}`),
  media: (fid: string) => request<FemMedia>("GET", `/fem-verifications/${fid}/media`),
  curves: (fid: string, name?: string, maxPoints = 500) => request<FemCurves>("GET", `/fem-verifications/${fid}/curves`, { query: { name, max_points: maxPoints } }),
  tableCsv: (fid: string) => fetchBlob(`/fem-verifications/${fid}/table.csv`),
  cancel: (fid: string) => request<FemVerification>("POST", `/fem-verifications/${fid}/cancel`),
  rerun: (fid: string) => request<FemVerification>("POST", `/fem-verifications/${fid}/rerun`),
  /** 조립 원본 폴더 확인(paths/inspect FEM_ASSEMBLY) — summary가 AssemblyPlan */
  inspectAssembly: (studyId: string, path: string) =>
    request<PathInspectResult>("POST", `/studies/${studyId}/paths/inspect`, { body: { purpose: "FEM_ASSEMBLY", path } }),
  /** 경로 탐색 루트(SPDM 읽기 전용 루트 포함) */
  fsRootsSpdm: () => request<FsRoots>("GET", "/fs/roots", { query: { include_spdm: true } }),
};
