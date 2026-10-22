// v0.2.9 조립 매칭(docs/contracts/asm-match.md §4.2·§4.3·§6.3): schema.d.ts(재생성 전)에 아직 없는 API의 로컬 타입.
// BE openapi 반영 후 `npm run gen:api`로 schema.d.ts가 따라오면 이 파일의 타입을 생성 타입으로 바꾸고 지운다. 계약 그대로 옮긴 것이다.

export type AsmMatchState = "SCANNING" | "DRAFT" | "CHECKING" | "CHECKED" | "CONFIRMED" | "FAILED" | "STALE";

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

export interface AsmMatchRow {
  body: string;
  pids: number[];
}

export interface AsmSharedPart {
  pid: number;
  title: string;
  nodes: number;
}

/** 원점·단위 진단(§4.3 판정 6) — 보정 적용 경로 없음, 진행 차단 */
export type AsmSuggest =
  | { code: "ASM_UNIT_SUSPECT"; factor: number }
  | { code: "ASM_OFFSET_SUSPECT"; translate_mm: [number, number, number]; match_ratio_after?: number };

/** worst 위치 점(UI 표시용 — 계약의 worst_<body>.npz 상위 노드. API 필드명은 BE 확정 후 맞춘다) */
export interface AsmWorstPoint {
  node_id?: number;
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
  rows: AsmCheckRow[];
  file_checks?: { shared_nodes: number; duplicate_node_defs: number };
  /** 검사 GLB(`ASM_MATCH_GLB` 산출물): 미디어 URL(`/artifacts/{id}/media`) 또는 산출물 id */
  glb_url: string | null;
}

/** `GET /asm-matches/{id}` */
export interface AsmMatch {
  match_id: string;
  study_id: string;
  state: AsmMatchState;
  source: { kind: "train" | "path"; cad_rel?: string | null };
  assem: { display_path: string; digest: string; starter: string; files: number };
  bodies: AsmBody[];
  parts: AsmPart[];
  recommend: AsmRecommend[];
  rows: AsmMatchRow[];
  excluded_bodies: string[];
  check: AsmCheck | null;
  confirmed: { sha256: string; confirmed_at: string } | null;
  stale_reason: string | null;
  /** FAILED(목록 작업 실패)일 때 코드·문구 */
  code?: string | null;
  message?: string | null;
}

export interface AsmMatchCreate {
  radioss_assem_path: string;
  cad: { kind: "train" } | { kind: "path"; path: string };
}
export interface AsmRowsPut {
  rows: AsmMatchRow[];
  excluded_bodies: string[];
}
