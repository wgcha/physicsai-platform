// v0.2.9 조립 매칭(docs/contracts/asm-match.md §4.2·§4.3·§6.3, AM-C2 9): 생성 스키마(schema.d.ts)의 AsmMatch는 내부 객체가 `Record<string, unknown>`이라
// 화면이 읽는 모양만 좁혀 둔다. 최상위 필드·요청 본문은 생성 타입 그대로다.
import type { Override, S } from "./typesBase";

export type AsmMatchState = S["AsmMatch"]["state"];

/** STEP 바디(`asm_parts.json bodies[]`): volume mm³, bbox = [xmin,ymin,zmin,xmax,ymax,zmax] mm */
export interface AsmBody {
  body: string;
  volume: number | null;
  bbox: number[];
}

/** 조립 component(`asm_parts.json parts[]`): TETRA4만 선택 가능(solid_ok) */
export interface AsmPart {
  pid: number;
  title: string;
  elems: Record<string, number>;
  nodes: number;
  volume: number | null;
  solid_ok: boolean;
}

export interface AsmRecommend {
  body: string;
  pids: number[];
  score: number;
}

export type AsmMatchRow = S["AsmRowIn"];

export interface AsmSharedPart {
  pid: number;
  title: string;
  nodes: number;
}

/** 원점·단위 진단(§4.3 판정 6) — 보정 적용 경로 없음, 진행 차단 */
export type AsmSuggest =
  | { code: "ASM_UNIT_SUSPECT"; factor: number }
  | { code: "ASM_OFFSET_SUSPECT"; translate_mm: [number, number, number]; match_ratio_after?: number };

/** worst 점: 거리 내림차순 상위 `asm_match.worst_nodes`점(AM-C2 9) */
export interface AsmWorstPoint {
  node_id: number;
  xyz: [number, number, number];
  dist_mm: number;
}

export interface AsmCheckRow {
  body: string;
  pids: number[];
  status: "PASS" | "FAIL";
  code: string | null;
  skin_nodes?: number;
  match_ratio: number | null;
  tol_mm: number | null;
  dist_mm: { mean: number; p95: number; p99: number; max: number } | null;
  shared: { nodes: number; parts: AsmSharedPart[] };
  suggest: AsmSuggest | null;
  worst?: { count: number; points?: AsmWorstPoint[] } | null;
}

export interface AsmCheck {
  seq: number;
  status: "PASS" | "FAIL";
  code?: string | null;
  message?: string | null;
  rows_sha256: string;
  /** 지금 표(행·제외)로 한 검사인가 — false면 "검사가 최신이 아님" */
  current: boolean;
  rows: AsmCheckRow[];
  file_checks?: { shared_nodes: number; duplicate_node_defs: number } | null;
  /** 검사 GLB 산출물(`/physicsai/api/artifacts/{id}/media`) */
  glb_url: string | null;
  glb_artifact_id: string | null;
}

export interface AsmLastJob {
  id: string;
  mode: "parts" | "check" | null;
  state: string;
  failure_code: string | null;
  failure_message: string | null;
  progress_pct: number | null;
  progress_label?: string | null;
}

/** `GET /asm-matches/{id}` · `GET /studies/{id}/asm-matches` 항목 */
export type AsmMatch = Override<
  S["AsmMatch"],
  {
    source: { kind: "train" | "path"; cad_name?: string | null; features_rel?: string | null };
    assem: { display_path: string; digest: string; starter: string; files: number };
    bodies: AsmBody[];
    parts: AsmPart[];
    recommend: AsmRecommend[];
    rows: AsmMatchRow[];
    excluded_bodies: string[];
    check: AsmCheck | null;
    confirmed: { sha256: string; confirmed_at: string } | null;
    stale_reason: string | null;
    last_job: AsmLastJob | null;
    warnings: { code?: string; message?: string }[];
    use_bodies: string[];
  }
>;

export type AsmMatchCreate = S["AsmMatchCreate"];
export type AsmRowsPut = Override<S["AsmRowsPut"], { excluded_bodies: string[] }>;

/** 422 ASM_ROW_INVALID problems[].code(AM-C2 10) */
export type AsmProblemCode = "USE_PARAM" | "UNKNOWN_BODY" | "BODY_DUPLICATE" | "UNKNOWN_PID" | "PID_DUPLICATE" | "NOT_SOLID" | "BODY_MISSING" | "ROWS_EMPTY";
export interface AsmRowProblem {
  code: AsmProblemCode | string;
  body?: string | null;
  message?: string | null;
  pid?: number | null;
}
