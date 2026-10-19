// native 형상 엔진 화면 공용(geometry-engine.md §4.3·§4.9·§6.2·§8·§11.4) — 순수 함수만(시험 대상).
import type { Engine, GeomOptions, MapGrade, MapRow, NativeFeature, NativeInfo, ParamMap } from "../api/types";

export const ENGINE_LABEL: Record<Engine, string> = { altair: "SimLab", native: "native" };

/** §6.2 피처 종류(+ 3S 쉘 두께) 한국어 */
export const FEATURE_TYPE_LABEL: Record<string, string> = {
  THICKNESS: "두께",
  POCKET_DEPTH: "포켓 깊이",
  POCKET_WIDTH: "포켓 폭",
  RIB_THICKNESS: "리브 두께",
  RIB_HEIGHT: "리브 높이",
  HOLE_RADIUS: "구멍 반경",
  HOLE_POS_U: "구멍 위치 U",
  HOLE_POS_V: "구멍 위치 V",
  FILLET_RADIUS: "필렛 반경",
  SHELL_T: "쉘 두께",
};

/** §4.3 이름 약어(GE-C4) → 종류. 이름 = `<COMP>_<약어>_<k>`(64자 초과 시 `_<4자 해시>`), 3S = `<PROP>_SHELL_T` */
const ABBR: [string, string][] = [
  ["POCKET_D", "POCKET_DEPTH"],
  ["POCKET_W", "POCKET_WIDTH"],
  ["FILLET_R", "FILLET_RADIUS"],
  ["HOLE_R", "HOLE_RADIUS"],
  ["HOLE_U", "HOLE_POS_U"],
  ["HOLE_V", "HOLE_POS_V"],
  ["RIB_T", "RIB_THICKNESS"],
  ["RIB_H", "RIB_HEIGHT"],
  ["THK", "THICKNESS"],
];

export function featureTypeFromName(name: string): string | null {
  if (/_SHELL_T(_\d+)?$/.test(name)) return "SHELL_T";
  for (const [a, t] of ABBR) if (new RegExp(`(^|_)${a}_\\d+(_[0-9a-f]{4})?$`).test(name)) return t;
  return null;
}

export const isPositionType = (type: string | null | undefined) => type === "HOLE_POS_U" || type === "HOLE_POS_V";

export function typeLabel(type: string | null | undefined): string {
  return type ? FEATURE_TYPE_LABEL[type] ?? type : "–";
}

const r3 = (v: number) => String(Number(v.toFixed(3)));

/** 범위 표기: 위치형은 공칭 ∓ mm(절대), 치수형은 ±%(§4.3 range) */
export function rangeText(nominal: number | null | undefined, min: number | null | undefined, max: number | null | undefined, type: string | null | undefined): string {
  if (min == null || max == null) return "–";
  const base = `${r3(min)} ~ ${r3(max)}`;
  if (nominal == null || !Number.isFinite(nominal)) return base;
  const d = Math.max(nominal - min, max - nominal);
  if (isPositionType(type)) return `${base} (∓${r3(d)} mm)`;
  if (nominal === 0) return base;
  return `${base} (±${r3((d / Math.abs(nominal)) * 100)}%)`;
}

/** 사용자 범위가 모핑 가능 범위(feasible)를 넘는가 — 경고만, 저장은 허용(§8·§11.2) */
export function exceedsFeasible(min: number | null | undefined, max: number | null | undefined, feasible: NativeFeature["feasible"]): boolean {
  if (!feasible) return false;
  if (min != null && feasible.min != null && min < feasible.min - 1e-9) return true;
  if (max != null && feasible.max != null && max > feasible.max + 1e-9) return true;
  return false;
}

export const PREP_LABEL: Record<NativeInfo["prep_status"], string> = { READY: "형상 준비됨", STALE: "형상 다시 준비 필요", MISSING: "형상 준비본 없음" };
export const PREP_TONE: Record<NativeInfo["prep_status"], string> = { READY: "ok", STALE: "warn", MISSING: "bad" };

/** 형상 엔진 오류 코드 한국어(§6 표·§7.6·§7.7·§11.4). 서버 문구가 한국어면 그대로 쓴다 */
export const GEOM_ERROR_TEXT: Record<string, string> = {
  GEOM_NATIVE_UNAVAILABLE: "native 형상 엔진을 쓸 수 없습니다(관리자 설정 확인)",
  GEOM_PREP_STALE: "형상 준비본이 오래되었습니다 — '형상 준비 다시'를 실행하세요",
  GEOM_OPTIONS_INVALID: "검사 기준 값이 허용 범위를 벗어났습니다",
  ENGINE_MISMATCH: "모델과 템플릿의 형상 엔진이 다릅니다(SimLab·native 혼용 불가)",
  ENGINE_MIXED: "SimLab·native 학습데이터를 한 데이터셋에 섞을 수 없습니다",
  ENGINE_NATIVE_NO_TPL: "native 엔진은 tpl을 만들지 않습니다",
  ENGINE_NATIVE_UNSUPPORTED: "원본 최적화는 SimLab 템플릿에서만 — 플랫폼 내장 최적화를 쓰세요",
  ENGINE_UNKNOWN: "모델의 형상 엔진을 알 수 없습니다(확인 후 사용)",
  PARAM_FEATURE_MISMATCH: "파라미터 이름이 형상 피처와 맞지 않습니다",
  PARAM_NAME_CONFLICT: "공통 변수 이름이 겹칩니다(타입·단위가 다르거나 중복, 예약어 baseline)",
  PARAM_MAP_UNCONFIRMED: "매칭표 확정 필요",
  BASELINE_NO_COVER: "어느 baseline 범위에도 들지 않습니다",
  BASELINE_INC_MISSING: "기준 메시 104_replace_node_elem.inc가 없습니다",
  PROP_SHARED_BY_PARTS: "여러 PART가 이 PROP을 공유합니다 — 모두 함께 바뀝니다",
  PROP_UNSUPPORTED_TYPE: "미지원 PROP 형식(TYPE9·10·11)",
  PROP_OVERRIDDEN_BY_ELEMENT: "요소별 두께가 PROP 두께를 덮어써 변경이 적용되지 않습니다",
  PROP_THICKNESS_INVALID: "쉘 두께가 0 이하이거나 범위 밖입니다",
  REF_BOTH_CONTACT: "양면 접촉 — 두께 변경 불가(기본 제외)",
  PNG_RENDER_FAILED: "하이라이트 그림을 만들지 못했습니다",
  MAP_LOW_SCORE: "매칭 점수가 낮습니다 — 확인하세요",
};

const HANGUL = /[가-힣]/;
export function geomErrorText(code: string | null | undefined, message: string | null | undefined): string {
  if (message && HANGUL.test(message)) return message;
  return (code && GEOM_ERROR_TEXT[code]) || message || code || "";
}

/** §6.5 category → 표시(일괄 예측·DOE 스킵 행 배지) */
export const GEN_CATEGORY_LABEL: Record<string, string> = {
  CAD: "CAD 생성 불가",
  COLLISION: "간섭",
  QUALITY: "품질 미달",
  DEVIATION: "편차 초과",
  TIE: "tie 투영 실패",
  PROP: "쉘 두께 적용 실패",
  BASELINE: "baseline 범위 밖",
};

// ---------------------------------------------------------------- 고급 옵션(§4.9, §8 "검사 기준(고급)")

export interface OptField {
  path: string[];
  label: string;
  kind: "number" | "select" | "bool";
  options?: [string, string][];
  /** 값 검사 — 문제면 문구 */
  check?: (v: number) => string | null;
  /** null 허용(빈칸 = null이 아니라 키 제거) */
  nullable?: boolean;
}

const pos = (v: number) => (v > 0 ? null : "0보다 커야 합니다");
const unit01 = (v: number) => (v > 0 && v <= 1 ? null : "0 초과 1 이하");

/** 고급 옵션에서 바꾸는 절 = quality·position_ref·position_range_mm·interference·deviation(+tie.required) */
export const GEOM_OPT_FIELDS: { group: string; fields: OptField[] }[] = [
  {
    group: "품질",
    fields: [
      { path: ["quality", "min_edge_ratio"], label: "최소 엣지 비(기준 대비)", kind: "number", check: unit01 },
      { path: ["quality", "dt_ratio_min"], label: "Δt 비 최소(기준 대비)", kind: "number", check: unit01 },
      { path: ["quality", "min_stretch"], label: "min stretch", kind: "number", check: unit01 },
      { path: ["quality", "max_aspect"], label: "max aspect", kind: "number", check: (v) => (v >= 1 ? null : "1 이상") },
      { path: ["quality", "min_edge_mm"], label: "최소 엣지 mm(선택)", kind: "number", check: pos, nullable: true },
    ],
  },
  {
    group: "위치형 파라미터",
    fields: [
      { path: ["position_ref"], label: "위치 기준", kind: "select", options: [["nearest_fixed", "가장 가까운 고정 면 거리 유지"], ["proportional", "바디 길이 비례"]] },
      { path: ["extract", "position_range_mm"], label: "기본 범위 ∓mm", kind: "number", check: pos },
    ],
  },
  {
    group: "간섭",
    fields: [
      { path: ["interference", "body_mm"], label: "바디 간 mm", kind: "number", check: pos },
      { path: ["interference", "product_mm"], label: "제품 mm", kind: "number", check: pos },
    ],
  },
  {
    group: "편차",
    fields: [
      { path: ["deviation", "boundary_max_mm"], label: "경계 mm", kind: "number", check: pos },
      { path: ["deviation", "param_abs_mm"], label: "파라미터 abs mm", kind: "number", check: pos },
      { path: ["deviation", "param_rel"], label: "파라미터 rel", kind: "number", check: pos },
    ],
  },
  { group: "tie", fields: [{ path: ["tie", "required"], label: "tie 필수", kind: "bool" }] },
];

export const optKey = (path: string[]) => path.join(".");

export function getOpt(o: GeomOptions | null | undefined, path: string[]): unknown {
  let cur: unknown = o;
  for (const k of path) {
    if (!cur || typeof cur !== "object") return undefined;
    cur = (cur as Record<string, unknown>)[k];
  }
  return cur;
}

/** 덮어쓰기 객체에서 한 키를 넣거나(value) 지운다(undefined = "기본값으로"). 빈 절은 없앤다 */
export function setOpt(o: GeomOptions | null | undefined, path: string[], value: unknown): GeomOptions {
  const out: GeomOptions = JSON.parse(JSON.stringify(o ?? {}));
  if (path.length === 1) {
    if (value === undefined) delete out[path[0]];
    else out[path[0]] = value;
    return out;
  }
  const [sec, key] = path;
  const s = { ...((out[sec] as Record<string, unknown>) ?? {}) };
  if (value === undefined) delete s[key];
  else s[key] = value;
  if (Object.keys(s).length) out[sec] = s;
  else delete out[sec];
  return out;
}

/** 편집 칸 문자열 → 저장 값. 빈칸 = 키 제거(undefined), 숫자 오류는 {error} */
export function parseOpt(f: OptField, raw: string): { value: unknown } | { error: string } {
  if (f.kind === "select") return { value: raw === "" ? undefined : raw };
  if (f.kind === "bool") return { value: raw === "" ? undefined : raw === "true" };
  if (raw.trim() === "") return { value: undefined };
  const n = Number(raw);
  if (!Number.isFinite(n)) return { error: "숫자를 입력하세요" };
  const msg = f.check?.(n);
  return msg ? { error: msg } : { value: n };
}

/** 422 GEOM_OPTIONS_INVALID problems → 키별 문구. problems 형식 {path|key|field, message} 중 있는 것 */
export function optProblems(detail: Record<string, unknown> | null | undefined): Record<string, string> {
  const out: Record<string, string> = {};
  const list = detail && Array.isArray(detail.problems) ? (detail.problems as Record<string, unknown>[]) : [];
  for (const p of list) {
    const raw = p.path ?? p.key ?? p.field ?? p.loc;
    const k = Array.isArray(raw) ? raw.join(".") : String(raw ?? "");
    out[k] = String(p.message ?? p.msg ?? "허용 범위 밖");
  }
  return out;
}

/** 대칭 그룹 분리·묶기(§6.2 symmetry_split, 세트 단위 — STALE 아님) */
export function toggleSplit(o: GeomOptions | null | undefined, groupId: string): GeomOptions {
  const cur = Array.isArray(getOpt(o, ["symmetry_split"])) ? (getOpt(o, ["symmetry_split"]) as string[]) : [];
  const next = cur.includes(groupId) ? cur.filter((g) => g !== groupId) : [...cur, groupId];
  return setOpt(o, ["symmetry_split"], next.length ? next : undefined);
}

export function isSplit(o: GeomOptions | null | undefined, groupId: string | null | undefined): boolean {
  const cur = getOpt(o, ["symmetry_split"]);
  return !!groupId && Array.isArray(cur) && cur.includes(groupId);
}

// ---------------------------------------------------------------- 다중 baseline 매칭표(§4.10·§11.4)

export const GRADE_LABEL: Record<MapGrade, string> = { recommend: "추천", check: "확인 필요", unmatched: "미매칭 제안" };
/** 등급 색: 추천 녹(pill ok)·확인 필요 황(pill warn)·미매칭 제안 회(기본 pill) */
export const GRADE_TONE: Record<MapGrade, string> = { recommend: "ok", check: "warn", unmatched: "" };

export const effectiveMap = (r: MapRow) => r.decision?.map ?? r.proposed.map;
export const effectiveName = (r: MapRow) => r.decision?.name ?? r.proposed.name;

/** 확정 전에 사용자가 반드시 결정해야 하는 행(재확인·확인 필요 등급 중 미결정) — 서버 confirm 422 조건과 같음 */
export function pendingRows(m: ParamMap): MapRow[] {
  return m.common.filter((r) => !r.decision && (r.needs_review || r.proposed.grade === "check"));
}

/** 이름 충돌(클라이언트 사전 표시): 같은 공통 이름 중복·예약어 baseline·한 baseline에서 같은 원 파라미터 중복 */
export function nameConflicts(m: ParamMap): Set<string> {
  const bad = new Set<string>();
  const seen = new Map<string, string>();
  for (const r of m.common) {
    const n = effectiveName(r);
    if (n === "baseline") bad.add(r.row_id);
    const prev = seen.get(n);
    if (prev) {
      bad.add(prev);
      bad.add(r.row_id);
    } else seen.set(n, r.row_id);
  }
  for (const b of m.baselines) {
    const used = new Map<string, string>();
    for (const r of m.common) {
      const v = effectiveMap(r)[b.id];
      if (!v) continue;
      const prev = used.get(v);
      if (prev) {
        bad.add(prev);
        bad.add(r.row_id);
      } else used.set(v, r.row_id);
    }
  }
  return bad;
}

export function fmtScore(s: number | null | undefined): string {
  return s == null || !Number.isFinite(s) ? "–" : s.toFixed(2);
}
