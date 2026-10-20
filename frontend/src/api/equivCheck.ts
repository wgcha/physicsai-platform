// ⑤ 해석 등가성 판정 API(equiv-check.md §6). 새 파일 — endpoints.ts·index.ts는 고치지 않는다.
import { fetchBlob, request, requestPage } from "./client";
import type { JobSummary } from "./types";

export type EqKind = "scalar" | "curve_corr" | "curve_nrmse" | "mesh_volume";
export type EqSourceType = "perf" | "h3d" | "curve" | "mesh_volume";

export type EqSource =
  | { type: "perf"; perf: string }
  | { type: "h3d"; name?: string | null; subcase?: number; datatype: string; component?: string; layer?: string; stat?: "MAX" | "MIN" | "ABSMAX" }
  | { type: "curve"; series: string | null; stat?: "MAX" | "MIN" | "ABSMAX"; t01?: { type: string; request: string; component: string } | null }
  | { type: "mesh_volume"; parts: "cushion" | string[]; origin?: "mesh" | "starter_mass" | "paicad" };

export interface EqTol {
  rel_pct?: number | null;
  abs?: number | null;
  corr_min?: number;
  nrmse_max_pct?: number;
}

export interface EqMetric {
  id: string;
  label: string;
  kind: EqKind;
  source: EqSource | null;
  tol: EqTol;
  required: boolean;
}

export interface EqDefinition {
  schema_version: number;
  metrics: EqMetric[];
  pair_rule: { mode: "all" | "min_ratio"; ratio?: number };
  verdict_rule: "required_all";
}

export interface EqRecipeListItem {
  key: string;
  version: number;
  name: string;
  description: string;
  scope: "system" | "study" | "global";
  study_id: string | null;
  metrics_count: number;
  updated_at: string | null;
  updated_by_name: string | null;
  readonly: boolean;
  deleted: boolean;
  can_edit: boolean;
}

export interface EqRecipe extends EqRecipeListItem {
  definition: EqDefinition;
  parent: { key: string; version: number } | null;
  versions: { version: number; created_at: string; created_by_name: string; name: string }[] | null;
}

export type EqSideReq =
  | { kind: "train_doe"; doe_id: string; label?: string | null }
  | { kind: "predict_batch"; batch_id: string; label?: string | null }
  | { kind: "fem_verify"; fv_id: string; attempt?: number | null; label?: string | null }
  | { kind: "folder"; paths: string[]; label?: string | null };

export type EqPairingMode = "by_name" | "by_params" | "manual";

export interface EqCheckCreate {
  side_a: EqSideReq;
  side_b: EqSideReq;
  pairing: { mode: EqPairingMode; pairs?: { a: string; b: string }[] | null };
  recipe?: { key: string; version?: number | null } | null;
  recipe_inline?: { definition: EqDefinition; base?: { key: string; version?: number | null } | null } | null;
  bindings?: Record<string, EqSource | null> | null;
  note?: string | null;
}

export interface EqProblem {
  code: string;
  message: string;
  metric_id?: string | null;
  side?: string | null;
  only_a?: string[] | null;
  only_b?: string[] | null;
}

export interface EqSideOut {
  kind: string;
  ref: string;
  label: string;
  run_count: number;
  ok_count: number;
  responses: string[];
  runs: { name: string; no: number | null; ok: boolean; state: string | null; has_h3d: boolean; has_t01: boolean; has_curve: boolean; has_mesh: boolean }[];
}

export interface EqPreviewMetric {
  id: string;
  label: string;
  kind: EqKind;
  required: boolean;
  source: EqSource | null;
  tol: EqTol;
  tol_text: string;
  bound: boolean;
  a: unknown;
  b: unknown;
  na: string | null;
}

export interface EqPreview {
  side_a: EqSideOut;
  side_b: EqSideOut;
  pairing: { mode: EqPairingMode; n_pairs: number; n_unmatched_a: number; n_unmatched_b: number };
  pairs: { no: number; a: string; b: string }[];
  unmatched_a: string[];
  unmatched_b: string[];
  metrics: EqPreviewMetric[];
  extract: { h3d_runs: number; t01_runs: number; copy_bytes: number };
  problems: EqProblem[];
  warnings: EqProblem[];
  can_run: boolean;
}

export type EqVerdict = "PASS" | "FAIL" | "INCOMPLETE";
export type EqStatus = "RUNNING" | "DONE" | "FAILED" | "CANCELED";

export interface EqRecipeRefOut {
  source: "system" | "user" | "adhoc";
  key: string | null;
  version: number | null;
  modified: boolean;
  name: string | null;
  deleted: boolean;
  current_version: number | null;
}

export interface EqCheckListItem {
  id: string;
  label: string;
  eq_no: number;
  status: EqStatus;
  status_text: string;
  verdict: EqVerdict | null;
  verdict_text: string | null;
  side_a: { kind: string; ref: string; label: string };
  side_b: { kind: string; ref: string; label: string };
  pairing: { mode: EqPairingMode; n_pairs: number; n_unmatched_a: number; n_unmatched_b: number };
  recipe: EqRecipeRefOut;
  summary_line: string | null;
  note: string | null;
  created_at: string;
  created_by: string;
  created_by_name: string;
  finished_at: string | null;
  job_id: string | null;
}

export interface EqMetricAgg {
  id: string;
  label: string;
  kind: EqKind;
  required: boolean;
  tol: EqTol;
  tol_text: string;
  source: EqSource | null;
  status: "PASS" | "FAIL" | "NA";
  n_pairs?: number;
  n_pass?: number;
  n_fail?: number;
  n_na?: number;
  a_mean?: number | null;
  b_mean?: number | null;
  max_abs_rel_pct?: number | null;
  max_abs_diff?: number | null;
  min_corr?: number | null;
  worst_pair?: string | null;
}

export interface EqRow {
  pair_no: number;
  a_run: string;
  b_run: string;
  metric_id: string;
  a: number | null;
  b: number | null;
  diff: number | null;
  rel_pct: number | null;
  corr: number | null;
  status: "PASS" | "FAIL" | "NA";
  reason: string | null;
  reason_text?: string | null;
}

export interface EqCheck extends EqCheckListItem {
  recipe_snapshot: EqDefinition & { recipe?: { name?: string | null }; system_version?: number; resolved?: Record<string, unknown> };
  summary: { verdict?: { required_total: number; required_pass: number; required_fail: number; reference_total: number; reference_fail: number }; n_pairs?: number } | null;
  metrics: EqMetricAgg[];
  rows: EqRow[];
  pairs: { no: number; a: string; b: string }[];
  unmatched_a: string[];
  unmatched_b: string[];
  warnings: EqProblem[];
  failure: EqProblem | null;
  job: JobSummary | null;
  dir: string | null;
  can_edit_note: boolean;
  can_cancel: boolean;
  can_retry: boolean;
}

export interface EqCurves {
  pair_no: number;
  metric_id: string;
  a_run: string;
  b_run: string;
  t: number[];
  a: number[];
  b: number[];
  corr: number | null;
  nrmse_pct: number | null;
  overlap_ratio: number | null;
  downsampled: boolean;
}

export const SYSTEM_RECIPE_KEY = "sys:default";

export const equivApi = {
  recipes: (studyId: string) => request<EqRecipeListItem[]>("GET", "/equiv/recipes", { query: { study_id: studyId } }),
  recipe: (key: string, version?: number | null) => request<EqRecipe>("GET", `/equiv/recipes/${encodeURIComponent(key)}`, { query: { version } }),
  recipeVersions: (key: string) => request<EqRecipe>("GET", `/equiv/recipes/${encodeURIComponent(key)}/versions`),
  createRecipe: (body: { name: string; description?: string; scope: "study" | "global"; study_id?: string | null; definition?: EqDefinition; clone_from?: { key: string; version?: number | null }; from_check?: string }) =>
    request<EqRecipe>("POST", "/equiv/recipes", { body }),
  updateRecipe: (key: string, body: { base_version: number; name?: string; description?: string; definition: EqDefinition }) => request<EqRecipe>("PUT", `/equiv/recipes/${encodeURIComponent(key)}`, { body }),
  deleteRecipe: (key: string) => request<void>("DELETE", `/equiv/recipes/${encodeURIComponent(key)}`),
  preview: (studyId: string, body: EqCheckCreate) => request<EqPreview>("POST", `/studies/${studyId}/equiv-checks/preview`, { body }),
  create: (studyId: string, body: EqCheckCreate) => request<{ eq_id: string; eq_no: number; label: string; job_id: string }>("POST", `/studies/${studyId}/equiv-checks`, { body }),
  list: (studyId: string, q: { side_kind?: string; side_ref?: string; verdict?: string; recipe_key?: string; limit?: number; cursor?: string | null } = {}) =>
    requestPage<EqCheckListItem[]>(`/studies/${studyId}/equiv-checks`, { ...q }),
  get: (eqId: string) => request<EqCheck>("GET", `/equiv-checks/${eqId}`),
  curves: (eqId: string, pair: number, metric: string, maxPoints = 1000) => request<EqCurves>("GET", `/equiv-checks/${eqId}/curves`, { query: { pair, metric, max_points: maxPoints } }),
  tableCsv: (eqId: string) => fetchBlob(`/equiv-checks/${eqId}/table.csv`),
  patchNote: (eqId: string, note: string | null) => request<EqCheckListItem>("PATCH", `/equiv-checks/${eqId}`, { body: { note } }),
};
