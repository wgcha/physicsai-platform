// API 타입(doe-preview.md §6.6) — DOE 표본 형상 그리드 미리보기. **로컬 타입**: backend/openapi.json 반영 전이라 generated/schema.d.ts에는 없다.
// 계약의 DoePreviewReq·DoePreview 모양 그대로 둔다(openapi 갱신 뒤 `S["DoePreview"]`로 바꿀 자리 = 이 파일 하나).
export type DoePreviewSourceKind = "train" | "param_set" | "train_doe";
export type DoePreviewOrder = "change" | "doe" | "var";
export type DoePreviewStatus = "QUEUED" | "RUNNING" | "DONE" | "FAILED" | "CANCELED";
export type DoePreviewCellStatus = "PENDING" | "OK" | "FAIL" | "ERROR";

export interface DoePreviewSource {
  kind: DoePreviewSourceKind;
  param_set_id?: string | null;
  doe_id?: string | null;
}
export interface DoePreviewSelect {
  order: DoePreviewOrder;
  var?: string | null;
  desc?: boolean;
  offset: number;
  limit: number;
}
/** POST /studies/{id}/doe-previews 본문. sampling = TD_DOE_GEN native params의 sampling과 같은 모양(train_doe면 생략) */
export interface DoePreviewReq {
  source: DoePreviewSource;
  sampling?: Record<string, unknown> | null;
  select: DoePreviewSelect;
}
export interface DoePreviewTopChange {
  name: string;
  value: number;
  /** (v − 공칭)/(max − min) */
  rel: number;
}
/** train_doe만: 생성 후 결과(SKIPPED 코드·단계) */
export interface DoePreviewGen {
  status: "OK" | "SKIPPED" | "PENDING";
  code?: string | null;
  step?: string | null;
}
export interface DoePreviewCell {
  /** 공칭 셀은 null */
  doe_no: number | null;
  nominal?: boolean;
  status: DoePreviewCellStatus;
  values: Record<string, number>;
  top_changes?: DoePreviewTopChange[];
  code?: string | null;
  category?: string | null;
  message_ko?: string | null;
  max_disp_mm?: number | null;
  clipped?: boolean;
  png_artifact_id?: string | null;
  glb_artifact_id?: string | null;
  manifest_artifact_id?: string | null;
  gen?: DoePreviewGen | null;
}
export interface DoePreview {
  id: string;
  job_id?: string | null;
  status: DoePreviewStatus;
  cache_hit?: boolean;
  queue?: { lane: string; position: number } | null;
  n_total: number;
  /** 정렬된 전체 doe_no */
  order?: number[];
  tag_state: "none" | "tagged";
  disp_range_mm: [number, number];
  colormap?: string;
  cells: DoePreviewCell[];
  warnings?: { code: string; message?: string | null }[];
  timing?: { total_s?: number | null } | null;
}
