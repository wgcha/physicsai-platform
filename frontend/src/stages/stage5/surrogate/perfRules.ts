// S17 ⑥ 성능 표 규칙(phase3.md §22.3·§22.4·§22.12, 순수 함수): 템플릿 성능 행 · 역할(목적·제약·관찰) · 요청 본문 조각 · 저장 상태.
import type { ResponseSpec, TemplateResponse } from "../../../api";
import type { SoConstraint, SoObjective, SoObserve } from "../../../api/surrogateOpt";

export type Role = "none" | "min" | "max" | "le" | "ge" | "range" | "observe";

export const ROLE_LABEL: Record<Role, string> = {
  none: "사용 안 함",
  min: "목적 최소",
  max: "목적 최대",
  le: "제약 ≤",
  ge: "제약 ≥",
  range: "제약 범위",
  observe: "관찰",
};
export const ROLES = Object.keys(ROLE_LABEL) as Role[];
export const isObjectiveRole = (r: Role) => r === "min" || r === "max";
export const isConstraintRole = (r: Role) => r === "le" || r === "ge" || r === "range";

export const MAX_CONSTRAINTS = 5;
export const DEFAULT_MAX_OBJECTIVES = 3;
export const DEFAULT_MAX_OBSERVE = 10;

export const SAVE_FIRST_TEXT = "저장된 성능만 역할 지정";
export const MULTI_NOTE = "다목적: 파레토 전선을 찾고, 가중치는 마무리 캡처할 추천점에만 씁니다(결과 화면에서 바꿀 수 있음)";
export const SRC_LABEL: Record<string, string> = { H3D: "H3D", CURVE: "커브" };

export interface RoleSel {
  role: Role;
  /** 제약 ≤·≥의 값, 범위의 하한(문자열 그대로) */
  a: string;
  /** 범위의 상한 */
  b: string;
}
export const NO_ROLE: RoleSel = { role: "none", a: "", b: "" };

export interface PerfRow {
  name: string;
  unit: string;
  source: "H3D" | "CURVE";
  spec: ResponseSpec;
}

export const perfId = (name: string) => `perf:${name}`;

/** 템플릿 응답 중 추출 정의(spec)가 있는 행 = 성능. spec null(이름·단위만)은 성능이 아니다 */
export function perfRows(responses: TemplateResponse[] | null | undefined): PerfRow[] {
  return (responses ?? []).flatMap((r) => (r.spec && (r.spec.source === "H3D" || r.spec.source === "CURVE") ? [{ name: r.name, unit: r.unit ?? "", source: r.spec.source, spec: r.spec }] : []));
}

export interface SpecCells {
  subcase: string;
  datatype: string;
  component: string;
  layer: string;
  stat: string;
}
/** 표 열(원본 ResponseTable 열 순서): CURVE는 계열이 DataType 자리에 온다 */
export function specCells(spec: ResponseSpec): SpecCells {
  if (spec.source === "CURVE") return { subcase: "", datatype: spec.series ?? "(첫 계열)", component: "", layer: "", stat: spec.stat };
  return { subcase: String(spec.subcase), datatype: spec.datatype, component: spec.component, layer: spec.layer, stat: spec.stat };
}

const STAT_CURVE: Record<string, string> = { MAX: "최대", MIN: "최소", ABSMAX: "|최대|" };
/** "CornerStress (MAX)" · "AccelPeak (커브 |최대|, Node 100 / X)" — 서버 performance.perf_label과 같은 모양 */
export function perfLabel(r: PerfRow): string {
  if (r.spec.source === "CURVE") return `${r.name} (커브 ${STAT_CURVE[r.spec.stat] ?? r.spec.stat}${r.spec.series ? `, ${r.spec.series}` : ""})`;
  return `${r.name} (${r.spec.stat})`;
}

export type SaveState = "saved" | "new" | "removed";

const specKey = (r: { unit?: string; spec?: unknown }) => JSON.stringify(r.spec ?? null);
/** 저장본(ps.responses)과 비교한 행 상태. 저장 전(new)이거나 삭제 예정(removed)이면 역할을 고를 수 없다 */
export function rowSaveState(name: string, saved: TemplateResponse[], draft: TemplateResponse[]): SaveState {
  const s = saved.find((x) => x.name === name);
  const d = draft.find((x) => x.name === name);
  if (!d) return "removed";
  if (!s || specKey(s) !== specKey(d)) return "new";
  return "saved";
}

/** 저장본과 초안이 다른가(이름·단위·spec·순서) */
export function isDraftDirty(saved: TemplateResponse[], draft: TemplateResponse[]): boolean {
  const norm = (l: TemplateResponse[]) => JSON.stringify(l.map((r) => [r.name, r.unit ?? "", r.spec ?? null]));
  return norm(saved) !== norm(draft);
}

export interface RoleCounts {
  objectives: number;
  constraints: number;
  observe: number;
}
export function roleCounts(sels: Record<string, RoleSel>, names: string[]): RoleCounts {
  const c: RoleCounts = { objectives: 0, constraints: 0, observe: 0 };
  for (const n of names) {
    const r = sels[n]?.role ?? "none";
    if (isObjectiveRole(r)) c.objectives++;
    else if (isConstraintRole(r)) c.constraints++;
    else if (r === "observe") c.observe++;
  }
  return c;
}

export interface Limits {
  maxObjectives: number;
  maxObserve: number;
}

/** 드롭다운에서 막을 역할: 목적 > max, 제약 > 5, 관찰 > max (현재 행의 역할은 빼고 센다) */
export function roleBlocked(role: Role, current: Role, counts: RoleCounts, lim: Limits): boolean {
  if (role === current || role === "none") return false;
  if (isObjectiveRole(role)) return counts.objectives - (isObjectiveRole(current) ? 1 : 0) >= lim.maxObjectives;
  if (isConstraintRole(role)) return counts.constraints - (isConstraintRole(current) ? 1 : 0) >= MAX_CONSTRAINTS;
  return counts.observe - (current === "observe" ? 1 : 0) >= lim.maxObserve;
}

const num = (s: string) => (s.trim() === "" ? NaN : Number(s));

/** 역할 값 칸 검증(서버 CONSTRAINT_INVALID와 같은 규칙). 값이 비어 있으면 null이 아니라 문구 */
export function roleValueIssue(s: RoleSel): string | null {
  if (s.role === "le" || s.role === "ge") return Number.isFinite(num(s.a)) ? null : "값을 입력하세요";
  if (s.role === "range") {
    const lo = num(s.a);
    const hi = num(s.b);
    if (!Number.isFinite(lo) || !Number.isFinite(hi)) return "하한과 상한을 입력하세요";
    return lo < hi ? null : "하한 < 상한";
  }
  return null;
}

/** opt-native ON-C4: 다목적 가중치는 사용자가 목적마다 직접 입력한다(기본값·자동 채움 없음, 빈 칸 = 미입력) */
export const WEIGHT_HELP = "가중치 = 목적마다 0~100(상대값, 합 > 0). 마무리 추천점(가중합 최소)에만 쓰입니다";
export const CRITERIA_HELP = "목적 응답·방향(최소/최대)·제약 임계값·가중치는 직접 정합니다 — 시스템이 대신 채우지 않습니다";

/** 가중치 입력 문자열 → 값(빈 칸·숫자 아님 = undefined) */
export function parseWeight(s: string): number | undefined {
  const t = s.trim();
  if (t === "") return undefined;
  const v = Number(t);
  return Number.isFinite(v) ? v : undefined;
}

/** 목적 가중치 미입력·범위 오류 문구(다목적만). 값 제안 없음 */
export function weightsIssue(objNames: string[], weights: Record<string, number>): string | null {
  if (objNames.length < 2) return null;
  const missing = objNames.filter((n) => weights[n] === undefined);
  if (missing.length) return `가중치를 입력하세요: ${missing.join(", ")}`;
  const w = objNames.map((n) => weights[n]);
  if (w.some((x) => x < 0 || x > 100)) return "가중치는 0~100입니다";
  if (w.reduce((a, b) => a + b, 0) <= 0) return "가중치 합은 0보다 커야 합니다";
  return null;
}

export interface RoleBody {
  objectives: SoObjective[];
  constraints: SoConstraint[];
  observe: SoObserve[];
  weights: number[] | null;
}

/** 역할 선택 → 요청 본문 조각(§22.4.1). 표 순서가 목적 순서. 값이 덜 찬 제약은 보내지 않는다(화면이 시작을 막는다) */
export function rolesToBody(rows: PerfRow[], sels: Record<string, RoleSel>, weights: Record<string, number>): RoleBody {
  const objectives: SoObjective[] = [];
  const constraints: SoConstraint[] = [];
  const observe: SoObserve[] = [];
  const objNames: string[] = [];
  for (const r of rows) {
    const s = sels[r.name] ?? NO_ROLE;
    const metric = perfId(r.name);
    if (isObjectiveRole(s.role)) {
      objectives.push({ metric, series: null, sense: s.role === "max" ? "max" : "min" });
      objNames.push(r.name);
    } else if (isConstraintRole(s.role) && roleValueIssue(s) === null) {
      if (s.role === "range") constraints.push({ metric, series: null, op: "range", lo: Number(s.a), hi: Number(s.b) });
      else constraints.push({ metric, series: null, op: s.role === "le" ? "<=" : ">=", value: Number(s.a) });
    } else if (s.role === "observe") observe.push({ metric, series: null });
  }
  // ON-C4: 다목적이면 사용자가 모두 입력했을 때만 보낸다(빈 칸을 기본값으로 채우지 않음 — 서버가 422로 막는다)
  const w = objNames.map((n) => weights[n]);
  return { objectives, constraints, observe, weights: objectives.length > 1 && w.every((x) => x !== undefined) ? (w as number[]) : null };
}

/** 역할 오류(시작 막기): 목적 없음·제약 값 부족·다목적 가중치 미입력(ON-C4) */
export function rolesIssue(rows: PerfRow[], sels: Record<string, RoleSel>, weights: Record<string, number> = {}): string | null {
  const names = rows.map((r) => r.name);
  if (!roleCounts(sels, names).objectives) return "목적을 1개 이상 지정하세요";
  for (const r of rows) {
    const msg = roleValueIssue(sels[r.name] ?? NO_ROLE);
    if (msg) return `${r.name}: ${msg}`;
  }
  return weightsIssue(rows.filter((r) => isObjectiveRole(sels[r.name]?.role ?? "none")).map((r) => r.name), weights);
}

/** 기본 역할 선택(저장된 성능이 바뀌어 사라진 이름은 버린다) */
export function pruneSels(sels: Record<string, RoleSel>, rows: PerfRow[]): Record<string, RoleSel> {
  const names = new Set(rows.map((r) => r.name));
  return Object.fromEntries(Object.entries(sels).filter(([k]) => names.has(k)));
}
