// native ①-1·④ 추출 조건(extract-filter.md §3.1·§4.2·§6·§7.2·§8) — 순수 함수만(시험 대상).
// 그룹 키·조건 키는 서버(physicsai_core/geometry/extract_filter.py)와 같은 값. 정규화·최종 검증은 서버가 한다.
import type { ApiErrorDetail, ExtractFilter, ExtractGroup, ExtractProblem } from "../api/types";
import { typeLabel } from "./geometry";

/** rib-gap.md §8 체크박스 도움말(ⓘ 툴팁) */
export const RIB_PITCH_HELP = "같은 방향으로 나란한 독립 리브의 중심 간 거리(리브 두께 유지, 가운데 리브 고정). 고르면 열의 가운데 리브만 위치 변수로 남습니다. 벽에 붙은 리브·격자는 대상이 아닙니다.";

/** §3.1 표 순서(= 서버 GROUP_ORDER) · 화면 문구 */
export const EXTRACT_GROUPS: { key: ExtractGroup; label: string; help?: string }[] = [
  { key: "thickness", label: "두께" },
  { key: "height", label: "높이·깊이" },
  { key: "position", label: "위치(구멍·리브)" },
  { key: "rib_pitch", label: "리브 간격(피치)", help: RIB_PITCH_HELP },
  { key: "hole_radius", label: "구멍 반경" },
  { key: "fillet", label: "필렛" },
];

/** 조건 칸(행) — id = 서버 조건 키. range = {min,max} 두 칸 */
export interface CondField {
  id: "thickness_mm" | "face_area_min_mm2" | "height_mm" | "position_min_size_mm" | "hole_radius_min_mm" | "fillet_radius_min_mm";
  group: ExtractGroup;
  kind: "range" | "scalar";
  label: string;
}
export const COND_FIELDS: CondField[] = [
  { id: "thickness_mm", group: "thickness", kind: "range", label: "두께 범위 (mm)" },
  { id: "face_area_min_mm2", group: "thickness", kind: "scalar", label: "최소 면 면적 (mm²)" },
  { id: "height_mm", group: "height", kind: "range", label: "높이·깊이 범위 (mm)" },
  { id: "position_min_size_mm", group: "position", kind: "scalar", label: "최소 크기 (mm) — 구멍 지름·리브 폭" },
  { id: "hole_radius_min_mm", group: "hole_radius", kind: "scalar", label: "구멍 반경 하한 r ≥ (mm)" },
  { id: "fillet_radius_min_mm", group: "fillet", kind: "scalar", label: "필렛 반경 하한 r ≥ (mm)" },
];
export const DRAFT_LABEL = "구배 허용각 (°)";
export const DRAFT_NOTE = "리브 측면 구배가 이 값보다 크면 리브로 인식되지 않습니다. 바꾸면 모든 종류의 인식 결과가 달라질 수 있습니다.";

export const MSG = {
  noGroup: "찾을 종류를 하나 이상 고르세요",
  positive: "0보다 큰 값을 넣으세요",
  nonNegative: "0 이상의 값을 넣으세요",
  minMax: "최솟값이 최댓값보다 큽니다",
  draft: "구배 허용각은 0°보다 크고 45°보다 작아야 합니다",
} as const;

/** 입력 상태: 체크한 그룹 + 칸별 문자열(키: `thickness_mm.min`·`face_area_min_mm2`·`draft_max_deg` 등). 빈칸 = 제한 없음 */
export interface FilterForm {
  groups: ExtractGroup[];
  v: Record<string, string>;
}

/** U1 프리셋: 모든 그룹(6개) 체크·조건 빈칸 */
export const presetForm = (): FilterForm => ({ groups: EXTRACT_GROUPS.map((g) => g.key), v: {} });

const txt = (n: number | null | undefined) => (n == null ? "" : String(n));

/** U1: 저장된(정규화) 조건이 있으면 그것으로, 없으면 프리셋 */
export function fromFilter(f: ExtractFilter | null | undefined): FilterForm {
  if (!f) return presetForm();
  const v: Record<string, string> = {};
  const c = (f.conditions ?? {}) as Record<string, unknown>;
  for (const fd of COND_FIELDS) {
    const x = c[fd.id];
    if (x == null) continue;
    if (fd.kind === "range") {
      const r = x as { min?: number | null; max?: number | null };
      v[`${fd.id}.min`] = txt(r.min);
      v[`${fd.id}.max`] = txt(r.max);
    } else v[fd.id] = txt(x as number);
  }
  if (f.draft_max_deg != null) v.draft_max_deg = String(f.draft_max_deg);
  return { groups: EXTRACT_GROUPS.map((g) => g.key).filter((k) => f.groups.includes(k)), v };
}

/** 칸 문자열 → 수. 빈칸 = null, 숫자가 아니면 NaN */
export function parseCell(s: string | undefined): number | null {
  const t = (s ?? "").trim();
  if (t === "") return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : Number.NaN;
}

/** 체크한 그룹에 속한 칸 */
const activeFields = (form: FilterForm) => COND_FIELDS.filter((f) => form.groups.includes(f.group));

/** 요청 본문용 — 체크한 그룹의 비어 있지 않은 조건만(서버가 다시 정규화). 검증을 통과한 폼에서만 호출 */
export function toFilter(form: FilterForm): ExtractFilter {
  const conditions: Record<string, unknown> = {};
  for (const fd of activeFields(form)) {
    if (fd.kind === "range") {
      const lo = parseCell(form.v[`${fd.id}.min`]);
      const hi = parseCell(form.v[`${fd.id}.max`]);
      if (lo != null || hi != null) conditions[fd.id] = { min: lo, max: hi };
    } else {
      const x = parseCell(form.v[fd.id]);
      if (x != null) conditions[fd.id] = x;
    }
  }
  return {
    groups: EXTRACT_GROUPS.map((g) => g.key).filter((k) => form.groups.includes(k)),
    conditions: conditions as ExtractFilter["conditions"],
    draft_max_deg: parseCell(form.v.draft_max_deg),
  };
}

/** 클라이언트 검증 — 서버 422 EXTRACT_FILTER_INVALID와 같은 키·문구(§6.1). 체크하지 않은 그룹의 칸은 보지 않는다 */
export function validateForm(form: FilterForm): ExtractProblem[] {
  const out: ExtractProblem[] = [];
  if (!form.groups.length) out.push({ key: "groups", message: MSG.noGroup });
  for (const fd of activeFields(form)) {
    if (fd.kind === "range") {
      const lo = parseCell(form.v[`${fd.id}.min`]);
      const hi = parseCell(form.v[`${fd.id}.max`]);
      let ok = true;
      if (lo != null && !(lo >= 0)) (out.push({ key: `conditions.${fd.id}.min`, message: MSG.nonNegative }), (ok = false));
      if (hi != null && !(hi > 0)) (out.push({ key: `conditions.${fd.id}.max`, message: MSG.positive }), (ok = false));
      if (ok && lo != null && hi != null && lo > hi) out.push({ key: `conditions.${fd.id}`, message: MSG.minMax });
    } else {
      const x = parseCell(form.v[fd.id]);
      if (x != null && !(x > 0)) out.push({ key: `conditions.${fd.id}`, message: MSG.positive });
    }
  }
  const d = parseCell(form.v.draft_max_deg);
  if (d != null && !(d > 0 && d < 45)) out.push({ key: "draft_max_deg", message: MSG.draft });
  return out;
}

/** 서버 422 본문에서 problems[{key,message}] 추출(EXTRACT_FILTER_INVALID). 아니면 [] */
export function extractProblems(detail: ApiErrorDetail | null | undefined): ExtractProblem[] {
  if (!detail || detail.code !== "EXTRACT_FILTER_INVALID") return [];
  const list = (detail as unknown as { problems?: unknown }).problems;
  if (!Array.isArray(list)) return [];
  return list
    .filter((p): p is { key?: unknown; message?: unknown } => !!p && typeof p === "object")
    .map((p) => ({ key: String(p.key ?? ""), message: String(p.message ?? "") }))
    .filter((p) => p.message);
}

/** 한 행(조건 id·groups·draft_max_deg)에 걸리는 문제 문구 */
export function problemsFor(problems: ExtractProblem[], row: string): string[] {
  const isCond = row !== "groups" && row !== "draft_max_deg";
  const base = isCond ? `conditions.${row}` : row;
  return problems.filter((p) => p.key === base || p.key.startsWith(`${base}.`)).map((p) => p.message);
}

/** 조건 입력 개수(체크한 그룹의 비어 있지 않은 칸 + 구배) */
export function conditionCount(form: FilterForm): number {
  const t = toFilter(form);
  return Object.keys(t.conditions).length + (t.draft_max_deg != null ? 1 : 0);
}

// ---------------------------------------------------------------- 같은 조건 비교(U2)

/** 비교용 표준형(서버 정규화와 같은 규칙: 그룹 순서·선택한 그룹의 조건만·null 제거). 없음 = null */
export function canonicalFilter(f: ExtractFilter | null | undefined): string | null {
  if (!f) return null;
  const form = fromFilter(f);
  const t = toFilter(form);
  return JSON.stringify(t);
}
export const sameFilter = (a: ExtractFilter | null | undefined, b: ExtractFilter | null | undefined) => canonicalFilter(a) === canonicalFilter(b);

// ---------------------------------------------------------------- 표시 문구(§6.4)

const n = (x: number) => String(Number(x.toFixed(6)));
function rangeTxt(label: string, r: { min?: number | null; max?: number | null } | null | undefined, unit: string): string | null {
  const lo = r?.min ?? null;
  const hi = r?.max ?? null;
  if (lo == null && hi == null) return null;
  if (lo != null && hi != null) return `${label} ${n(lo)}~${n(hi)} ${unit}`;
  return lo != null ? `${label} ≥ ${n(lo)} ${unit}` : `${label} ≤ ${n(hi!)} ${unit}`;
}

/** "두께 2~30 mm · 면적 ≥ 50 mm² · 위치 최소 3 mm · 필렛 r ≥ 1 mm · 구배 3° · 제외: 높이·깊이" — 필터 없음·전체 = "전체 종류(조건 없음)" */
export function filterText(f: ExtractFilter | null | undefined): string {
  if (!f) return "전체 종류(조건 없음)";
  const c = (f.conditions ?? {}) as Record<string, unknown>;
  const parts: string[] = [];
  const add = (s: string | null) => s && parts.push(s);
  add(rangeTxt("두께", c.thickness_mm as never, "mm"));
  if (typeof c.face_area_min_mm2 === "number") add(`면적 ≥ ${n(c.face_area_min_mm2)} mm²`);
  add(rangeTxt("높이·깊이", c.height_mm as never, "mm"));
  if (typeof c.position_min_size_mm === "number") add(`위치 최소 ${n(c.position_min_size_mm)} mm`);
  if (typeof c.hole_radius_min_mm === "number") add(`구멍 반경 r ≥ ${n(c.hole_radius_min_mm)} mm`);
  if (typeof c.fillet_radius_min_mm === "number") add(`필렛 r ≥ ${n(c.fillet_radius_min_mm)} mm`);
  if (f.draft_max_deg != null) add(`구배 ${n(f.draft_max_deg)}°`);
  const off = EXTRACT_GROUPS.filter((g) => !f.groups.includes(g.key)).map((g) => g.label);
  if (!parts.length && !off.length) return "전체 종류(조건 없음)";
  const all = parts.length ? parts.join(" · ") : "조건 없음";
  return off.length ? `${all} · 제외: ${off.join(", ")}` : all;
}

// ---------------------------------------------------------------- 추출 요약(§7.2 extract_summary)

/** excluded 사유 키 표기(EF-C1 §5) — 모르는 키는 원래 이름 */
export const EXCLUDED_LABEL: Record<string, string> = {
  face_area: "면적", thickness_range: "범위", not_mutual: "비상호", no_overlap: "겹침 없음", not_thinner_than_height: "높이보다 두꺼움",
  height_range: "범위", hole_radius_min: "반경", fillet_radius_min: "반경", position_min_size: "최소 크기", shape: "측면 형상", base_axis: "축 비정렬",
  // rib-gap.md §8(리브 간격 열 인식)
  not_slender: "기둥형", row_branch: "열 분기", row_single: "이웃 없음", row_member: "간격 열 소속",
};
/** 리브 후보 탈락 사유 7키(EF-C1) */
export const RIB_REJECT_LABEL: Record<string, string> = {
  cap_inner_wire: "윗면 내부 구멍", cap_not_convex: "윗면 볼록 아님", lateral_not_plane: "측면 곡면", lateral_draft: "측면 구배",
  lateral_count: "측면 3개 미만", base_mismatch: "밑면 불일치", height_not_positive: "높이 0 이하",
};
/** 종류 표시 순서(서버 TYPE_ORDER) */
const TYPE_ORDER = ["THICKNESS", "RIB_THICKNESS", "POCKET_WIDTH", "RIB_HEIGHT", "POCKET_DEPTH", "HOLE_POS_U", "HOLE_POS_V", "RIB_POS_U", "RIB_POS_V", "RIB_PITCH_U", "RIB_PITCH_V", "HOLE_RADIUS", "FILLET_RADIUS"];

export interface SummaryReason {
  key: string;
  label: string;
  count: number;
}
export interface SummaryRow {
  type: string;
  label: string;
  kept: number;
  excluded: number;
  reasons: SummaryReason[];
}
export interface ExtractSummaryView {
  rows: SummaryRow[];
  ribTotal: number;
  ribRejects: SummaryReason[];
}

const num = (x: unknown) => (typeof x === "number" && Number.isFinite(x) ? x : 0);
const reasons = (o: unknown, labels: Record<string, string>): SummaryReason[] => {
  const e = o && typeof o === "object" ? Object.entries(o as Record<string, unknown>).filter(([, v]) => num(v) > 0) : [];
  const known = Object.keys(labels);
  const keys = [...known.filter((k) => e.some(([x]) => x === k)), ...e.map(([k]) => k).filter((k) => !known.includes(k)).sort()];
  return keys.map((k) => ({ key: k, label: labels[k] ?? k, count: num((o as Record<string, unknown>)[k]) }));
};

/** `TrainSetup.extract_summary`(자유 형식 dict) → 표시용. 구조가 아니면 null */
export function summaryView(raw: unknown): ExtractSummaryView | null {
  if (!raw || typeof raw !== "object") return null;
  const types = (raw as { types?: unknown }).types;
  if (!types || typeof types !== "object") return null;
  const rows: SummaryRow[] = [];
  const names = Object.keys(types as object);
  const order = [...TYPE_ORDER.filter((t) => names.includes(t)), ...names.filter((t) => !TYPE_ORDER.includes(t)).sort()];
  for (const t of order) {
    const v = (types as Record<string, { selected?: unknown; kept?: unknown; excluded?: unknown }>)[t];
    if (!v || !v.selected) continue;
    const rs = reasons(v.excluded, EXCLUDED_LABEL);
    rows.push({ type: t, label: typeLabel(t), kept: num(v.kept), excluded: rs.reduce((a, r) => a + r.count, 0), reasons: rs });
  }
  const rib = reasons((raw as { rib_rejects?: unknown }).rib_rejects, RIB_REJECT_LABEL);
  return { rows, ribTotal: rib.reduce((a, r) => a + r.count, 0), ribRejects: rib };
}

export const reasonText = (rs: SummaryReason[]) => rs.map((r) => `${r.label} ${r.count}`).join(", ");
