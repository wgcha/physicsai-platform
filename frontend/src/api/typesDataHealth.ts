// data-health.md §6.2 report.json·§6.1 jobs.result — openapi(DataHealthReport) 반영 전 로컬 모양(계약 그대로).
export interface DhWarning {
  code: string;
  message: string;
  count?: number | null;
}

/** 사유(§3.5): 코드는 툴팁, message는 한국어 */
export interface DhReason {
  code: string;
  metric?: string | null;
  value?: number | null;
  z?: number | null;
  zr?: number | null;
  s?: number | null;
  message: string;
}

/** ② 지표 한 칸: fail = 견고 z 또는 이웃 점수가 기준 초과, na = 결측 사유 코드 */
export interface DhValue {
  v?: number | null;
  z?: number | null;
  zr?: number | null;
  s?: number | null;
  na?: string | null;
  fail?: boolean;
  knn_dist?: number | null;
}

/** ① 건전성 칸(절대 기준): 표시는 "값 / 기준" */
export interface DhSound {
  status: "OK" | "FAIL" | "NA";
  value?: number | string | null;
  limit?: number | null;
  code?: string | null;
  v?: number | null;
  na?: string | null;
  fail?: boolean;
}

/** 일관성(프레임·종료 시각): 값 / 기준(ref) */
export interface DhConsistency {
  status: "OK" | "FAIL" | "NA";
  value?: number | null;
  ref?: number | null;
  code?: string | null;
}

export interface DhMetric {
  id: string;
  label: string;
  unit?: string;
  group: string;
  n: number;
  mean?: number | null;
  std?: number | null;
  median?: number | null;
  mad?: number | null;
  skipped?: boolean;
  knn_skipped?: boolean;
}

export interface DhRun {
  file_rel: string;
  run_key?: string | null;
  /** 제외 필수(일관성 위반, 기본 선택) — recommended 포함 */
  required: boolean;
  recommended: boolean;
  score: number;
  sigma_only: boolean;
  doe_id?: string | null;
  t_end?: number | null;
  /** ① 건전성: term·energy_err_pct·added_mass·hg_ratio·contact_ratio */
  sound: Record<string, DhSound>;
  consistency: Record<string, DhConsistency>;
  values: Record<string, DhValue>;
  reasons: DhReason[];
}

export interface DhSummary {
  n_runs: number;
  n_required: number;
  n_frames_unknown: number;
  n_recommended: number;
  n_sigma_only: number;
  n_sound_fail: number;
  frames_ref?: number | null;
  t_end_ref?: number | null;
  ref_source?: string | null;
  /** 기준값 출처 표시: "설정" | "최빈" */
  frames_ref_source?: string | null;
  t_end_ref_source?: string | null;
  refs_by_doe?: Record<string, Record<string, number | null>>;
  preview_frames?: number | null;
  metrics_used?: string[];
  /** 점검 입력 식별: 폴더는 서버 normpath, 큐레이션은 `curation:<id>` */
  input_key?: string | null;
  n_na_by_metric?: Record<string, number>;
  thresholds: Record<string, number | null>;
  limited?: boolean;
  warnings: DhWarning[];
}

export interface DataHealthReport {
  summary: DhSummary;
  metrics: DhMetric[];
  runs: DhRun[];
  truncated?: boolean;
}
