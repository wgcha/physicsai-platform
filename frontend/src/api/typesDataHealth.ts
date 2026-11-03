// data-health.md §6.2 report.json·§6.1 jobs.result — openapi(DataHealthReport) 반영 전 로컬 모양(계약 그대로).
export interface DhWarning {
  code: string;
  message: string;
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

/** 지표 한 칸: v 원값(문자열 가능: term), na = 결측 사유 코드, fail = ① 판정 위반 */
export interface DhValue {
  v?: number | string | null;
  z?: number | null;
  zr?: number | null;
  s?: number | null;
  na?: string | null;
  fail?: boolean;
}

export interface DhMetric {
  id: string;
  label: string;
  unit?: string | null;
  group: string;
  n: number;
  mean?: number | null;
  std?: number | null;
  median?: number | null;
  mad?: number | null;
  skipped?: string | null;
}

export interface DhRun {
  file_rel: string;
  run_key?: string | null;
  /** 제외 필수(일관성 위반, 기본 선택) — recommended 포함 */
  required: boolean;
  recommended: boolean;
  score: number;
  sigma_only: boolean;
  /** ① 건전성: term·energy_err_pct·added_mass·hg_ratio·contact_ratio·frames·t_last */
  sound: Record<string, DhValue>;
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
  /** 기준 출처: 설정 기대값 | 같은 DOE 최빈 */
  ref_source?: "config" | "mode" | null;
  n_na_by_metric?: Record<string, number>;
  thresholds: { robust_z: number; knn_z: number; sigma_z: number };
  limited?: boolean;
  warnings: DhWarning[];
}

export interface DataHealthReport {
  summary: DhSummary;
  metrics: DhMetric[];
  runs: DhRun[];
  truncated?: boolean;
}
