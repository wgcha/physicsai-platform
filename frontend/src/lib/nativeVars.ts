// Native 템플릿 변수 정의(native-vars.md §3·§5·§7) 화면 규칙 — 순수 함수만(시험 대상).
// 경고는 막지 않는다(D2): 학습 범위 밖 · 모핑 가능 범위(feasible) 밖 · 양면 접촉 · 공칭 밖. 허용오차는 서버와 같다(학습 1e-9·max(1,|x|), feasible 1e-9).
import type { NativeVarPoolRow, NativeVars, ParamSet, VarFeasible, VarNote, VarRange, VarRow, VarsEdit, VarsSnapshot } from "../api/types";
import { fmtNum } from "./format";

export type VarOrigin = "set" | "added" | "pool";

/** 표 한 행 — lo·hi는 입력 문자열(편집 중 값). use=false 행은 값을 유지한다 */
export interface NativeRow {
  name: string;
  type: string;
  body: string;
  nominal: number | null;
  unit: string;
  position: boolean;
  group: string | null;
  refLocked: boolean;
  /** Altair: tpl 형식이 정수(%i·%d)인 파라미터 — 하한·상한도 정수만 */
  integer: boolean;
  /** Altair: 범위를 알 수 없어(고정 선언·표 값 없음) 빈칸으로 시작한 행 */
  rangeUnset: boolean;
  /** 기준 범위: 세트 정의(세트 행) 또는 피처 기본 범위(추가·미사용 행) — 요청 bounds는 이것과 다를 때만 보낸다 */
  base: VarRange;
  defaultRange: VarRange;
  train: VarRange | null;
  feasible: VarFeasible | null;
  use: boolean;
  lo: string;
  hi: string;
  /** ⑥ 고정(하한 = 상한) — 제외와 다르다(NV-6): 변수 목록·결과 표에 남는다 */
  fixed: boolean;
  origin: VarOrigin;
}

export const NOTE_TEXT: Record<string, string> = {
  VAR_OUT_OF_TRAIN: "학습 형상 분포 밖 — 외삽 주의",
  VAR_OUT_OF_FEASIBLE: "모핑 실패 가능",
  VAR_REF_LOCKED: "양면 접촉 피처 — 형상 생성이 실패할 수 있습니다",
  VAR_NOMINAL_OUTSIDE: "공칭이 범위 밖입니다(기존안은 범위 밖 점으로 표시)",
  VAR_OUT_OF_BOUNDS: "최적화 범위 밖 점입니다",
  TRAIN_RANGE_UNKNOWN: "모델의 학습 범위를 알 수 없어 외삽 경고를 생략합니다(모델의 데이터셋이 ① DOE 결과가 아님)",
  TRAIN_RANGE_UNMATCHED: "학습 때의 피처와 같은지 확인할 수 없어 일부 변수의 학습 범위를 생략합니다",
  VARS_FROM_DOE: "① DOE의 변수 구성을 그대로 씁니다",
};

/** Altair 전체 tpl 세트의 머리 안내(altair-vars.md §5.3) — GET 변수 정의 reason 코드를 문구로 */
export const TPL_PARTIAL_TEXT = "옛 tpl(① 사용 파라미터만 포함) — 변수 추가·제외는 ①-2에서 tpl을 다시 생성해 새 템플릿으로 등록한 뒤 쓰세요";
export const reasonText = (reason: string | null | undefined): string | null => (!reason ? null : reason === "TPL_SCOPE_PARTIAL" ? TPL_PARTIAL_TEXT : reason);

/** Altair 전체 tpl(변수 정의 편집 가능)인가 — 변수 표·그 자리 편집을 Native와 같이 쓴다 */
export const usesVarTable = (ps: Pick<ParamSet, "engine" | "vars_scope"> | null | undefined): boolean => ps?.engine === "native" || (ps?.engine === "altair" && ps.vars_scope === "full");
/** 변수 정의 리비전(Native는 native 요약, Altair는 ParamSet.vars_revision) */
export const varsRevisionOf = (ps: ParamSet): number => ps.native?.vars_revision ?? ps.vars_revision ?? 0;
/** 서버 문구가 한국어면 그대로, 아니면 코드 표 */
export const noteText = (n: { code: string; message?: string | null }) => (n.message && /[가-힣]/.test(n.message) ? n.message : NOTE_TEXT[n.code] ?? n.message ?? n.code);

export const NV_ERROR_TEXT: Record<string, string> = {
  NATIVE_VARS_UNSUPPORTED: "변수 추가·제외는 Native 템플릿에서만 쓸 수 있습니다",
  NATIVE_VARS_CONFLICT: "다른 사용자가 먼저 저장했습니다 — 새로 불러온 뒤 다시 저장하세요",
  NATIVE_VARS_MULTI_UNSUPPORTED: "다중 baseline 템플릿은 변수 추가·제외를 아직 지원하지 않습니다",
  NATIVE_VARS_GEOMETRY_OFF: "쉘 두께 설정에서 형상 파라미터를 켠 뒤 편집하세요",
  VAR_UNKNOWN: "이 템플릿의 형상 변수가 아닙니다",
  VAR_DUPLICATE: "변수가 중복되었습니다",
  VAR_RANGE_INVALID: "하한·상한은 유한한 숫자이고 하한 ≤ 상한이어야 합니다(정수 파라미터는 정수 범위)",
  TPL_SCOPE_PARTIAL: TPL_PARTIAL_TEXT,
  VARS_EMPTY: "변수를 하나 이상 고르세요",
};

const tolTrain = (x: number) => 1e-9 * Math.max(1, Math.abs(x));
const FEAS_TOL = 1e-9;

export const toNum = (s: string): number | null => (s.trim() !== "" && Number.isFinite(Number(s)) ? Number(s) : null);

/** 행의 [lo, hi] — 숫자가 아니면 null. fixed(하한 = 상한)는 lo만 쓰는 화면용으로 hi를 lo에 맞춘 값을 넘겨도 된다 */
export function rowBounds(r: Pick<NativeRow, "lo" | "hi"> & { fixed?: boolean }): [number, number] | null {
  const lo = toNum(r.lo);
  const hi = r.fixed ? lo : toNum(r.hi);
  return lo === null || hi === null ? null : [lo, hi];
}

/** 학습 범위 밖인가(경고) — train이 없으면 판단 불가 = false */
export function exceedsTrain(lo: number, hi: number, train: VarRange | null | undefined): boolean {
  return !!train && (lo < train.min - tolTrain(train.min) || hi > train.max + tolTrain(train.max));
}
export function exceedsFeasibleRange(lo: number, hi: number, f: VarFeasible | null | undefined): boolean {
  if (!f) return false;
  return (f.min != null && lo < f.min - FEAS_TOL) || (f.max != null && hi > f.max + FEAS_TOL);
}

/** 행 경고(사용 중인 행만). 서버와 같은 코드·문구 */
export function rowWarnings(r: NativeRow): { code: string; message: string }[] {
  if (!r.use) return [];
  const b = rowBounds(r);
  const out: { code: string; message: string }[] = [];
  const w = (code: string, message = NOTE_TEXT[code]) => out.push({ code, message });
  if (b) {
    const [lo, hi] = b;
    if (exceedsTrain(lo, hi, r.train)) w("VAR_OUT_OF_TRAIN", `${NOTE_TEXT.VAR_OUT_OF_TRAIN}(학습 ${fmtNum(r.train!.min)}~${fmtNum(r.train!.max)})`);
    if (exceedsFeasibleRange(lo, hi, r.feasible)) w("VAR_OUT_OF_FEASIBLE", `${NOTE_TEXT.VAR_OUT_OF_FEASIBLE}(모핑 가능 ${r.feasible?.min ?? "–"}~${r.feasible?.max ?? "–"})`);
    if (r.nominal != null && (r.nominal < lo - tolTrain(lo) || r.nominal > hi + tolTrain(hi))) w("VAR_NOMINAL_OUTSIDE");
  }
  if (r.refLocked) w("VAR_REF_LOCKED");
  return out;
}

/** 서버 경고(var_notes·warnings)를 이름별로 — 클라이언트 계산과 같은 코드는 중복으로 보지 않는다 */
export function notesByName(notes: VarNote[] | null | undefined): Record<string, VarNote[]> {
  const out: Record<string, VarNote[]> = {};
  for (const n of notes ?? []) if (n.name) (out[n.name] ??= []).push(n);
  return out;
}
export const generalNotes = (notes: VarNote[] | null | undefined): VarNote[] => (notes ?? []).filter((n) => !n.name);

/** 행 경고 = 클라이언트 계산 + 서버 경고 중 코드가 겹치지 않는 것 */
export function mergedWarnings(r: NativeRow, server?: VarNote[]): { code: string; message: string }[] {
  const mine = rowWarnings(r);
  const have = new Set(mine.map((x) => x.code));
  const extra = (server ?? []).filter((n) => !have.has(n.code)).map((n) => ({ code: n.code, message: noteText(n) }));
  return [...mine, ...extra];
}

const rangeOf = (r: { min: number; max: number }): VarRange => ({ min: r.min, max: r.max });

function fromPool(p: NativeVarPoolRow, origin: VarOrigin, use: boolean, def?: VarRange): NativeRow {
  const base = def ?? rangeOf(p.default_range);
  const blank = !def && !!p.range_unset; // 범위를 모르는 풀 행은 빈칸으로 시작(채워야 쓸 수 있다)
  return {
    name: p.name, type: p.type ?? "", body: p.body ?? "", nominal: p.nominal ?? null, unit: p.unit, position: p.position, group: p.group ?? null, refLocked: !!p.ref_locked,
    integer: !!p.integer, rangeUnset: !!p.range_unset,
    base, defaultRange: rangeOf(p.default_range), train: p.train ? rangeOf(p.train) : null, feasible: p.feasible ?? null,
    use, lo: blank ? "" : String(base.min), hi: blank ? "" : String(base.max), fixed: use && origin === "set" && base.min === base.max, origin,
  };
}

/** ④ 세트 상세: 풀 전체. 사용 = 세트 정의에 있는 행, 아니면 피처 기본 범위(처음 켜면 그 값) */
export function detailRows(d: NativeVars): NativeRow[] {
  const def = new Map(d.variables.map((v) => [v.name, v]));
  return d.pool.map((p) => {
    const v = def.get(p.name);
    return fromPool(p, v ? "set" : "pool", !!v, v ? { min: v.min, max: v.max } : undefined);
  });
}

/** ⑥·④ 일괄: 유효 변수 = (세트 정의 − 제외) + 추가. 제외된 세트 행은 사용 해제로 남겨 다시 켤 수 있게 한다 */
export function runRows(d: NativeVars, edit: Required<VarsEdit>, props: NativeRow[] = []): NativeRow[] {
  const pool = new Map(d.pool.map((p) => [p.name, p]));
  const out: NativeRow[] = [];
  for (const v of d.variables) {
    const p = pool.get(v.name);
    if (p) out.push(fromPool(p, "set", !(edit.exclude ?? []).includes(v.name), { min: v.min, max: v.max }));
  }
  out.push(...props.map((r) => ({ ...r, use: !(edit.exclude ?? []).includes(r.name) })));
  for (const n of edit.add ?? []) {
    const p = pool.get(n);
    if (p && !d.variables.some((v) => v.name === n)) out.push(fromPool(p, "added", true));
  }
  return out;
}

/** 쉘 두께 PROP 행(세트 파라미터 `source: "prop"`) — 풀(형상 피처)에는 없지만 실행 변수다. 범위·제외만(선택은 ④ 쉘 두께 설정) */
export function propRows(ps: ParamSet): NativeRow[] {
  return ps.parameters
    .filter((p) => p.source === "prop")
    .map((p) => ({
      name: p.name, type: "SHELL_T", body: "", nominal: p.nominal ?? null, unit: p.unit ?? "mm", position: false, group: null, refLocked: false, integer: false, rangeUnset: false,
      base: { min: p.min, max: p.max }, defaultRange: { min: p.min, max: p.max }, train: null, feasible: null,
      use: true, lo: String(p.min), hi: String(p.max), fixed: p.min === p.max, origin: "set" as const,
    }));
}

export const NO_EDIT: Required<VarsEdit> = { add: [], exclude: [] };

/** 표 행 → 요청 vars(비어 있으면 null) */
export function editOf(rows: NativeRow[]): { add: string[]; exclude: string[] } | null {
  const add = rows.filter((r) => r.origin === "added" && r.use).map((r) => r.name);
  const exclude = rows.filter((r) => r.origin === "set" && !r.use).map((r) => r.name);
  return add.length || exclude.length ? { add, exclude } : null;
}

/** 풀 − 현재 행 = "변수 추가" 후보 */
export const addable = (d: NativeVars | null, rows: NativeRow[]): NativeVarPoolRow[] => (d ? d.pool.filter((p) => !rows.some((r) => r.name === p.name)) : []);

export const addRow = (d: NativeVars, name: string, rows: NativeRow[]): NativeRow[] => {
  const p = d.pool.find((x) => x.name === name);
  return p && !rows.some((r) => r.name === name) ? [...rows, fromPool(p, "added", true)] : rows;
};

/** ④ 세트 상세 저장 본문: 사용 행 전체(풀 순서) */
export const putBody = (rows: NativeRow[], baseRevision: number) => ({
  base_revision: baseRevision,
  variables: rows.filter((r) => r.use).map((r) => ({ name: r.name, min: Number(r.lo), max: Number(r.hi) })),
});

/** 편집 중 값이 저장된 정의와 같은가(저장 버튼 활성 판정) */
export const signature = (rows: NativeRow[]) => JSON.stringify(rows.filter((r) => r.use).map((r) => [r.name, toNum(r.lo) ?? r.lo, toNum(r.hi) ?? r.hi]));

/** 행 입력 검사(차단): 숫자·하한 ≤ 상한·(정수 파라미터는 정수)만 — 범위 밖은 경고일 뿐이다(NV-7) */
export function rowError(r: Pick<NativeRow, "lo" | "hi" | "use" | "fixed"> & { integer?: boolean; rangeUnset?: boolean }): string | null {
  if (!r.use) return null;
  const b = rowBounds(r);
  if (!b) return r.rangeUnset && (r.lo.trim() === "" || r.hi.trim() === "") ? "범위를 입력하세요" : "숫자를 입력하세요";
  const ie = integerError(r);
  if (ie) return ie;
  return b[0] > b[1] ? "하한 ≤ 상한" : null;
}

/** 정수(%i·%d) 파라미터의 하한·상한이 정수가 아니면 문구(숫자가 아닌 칸은 다른 검사 소관) */
export function integerError(r: Pick<NativeRow, "lo" | "hi" | "use" | "fixed"> & { integer?: boolean }): string | null {
  if (!r.use || !r.integer) return null;
  const b = rowBounds(r);
  return b && !(Number.isInteger(b[0]) && Number.isInteger(b[1])) ? "정수만 입력하세요" : null;
}

/** 위치형: 공칭 대비 Δ 표기(mm) — "−5 / +5" */
export function deltaText(r: Pick<NativeRow, "nominal" | "lo" | "hi" | "position" | "fixed">): string | null {
  const b = rowBounds(r);
  if (!r.position || r.nominal == null || !b) return null;
  const f = (v: number) => (v > 0 ? "+" : v < 0 ? "−" : "") + fmtNum(Math.abs(Number(v.toFixed(4))));
  return `${f(b[0] - r.nominal)} / ${f(b[1] - r.nominal)}`;
}

/** 미리보기 var_rows(서버) → 표 행 보정(서버가 준 학습·모핑 가능 범위를 우선) */
export function applyVarRows(rows: NativeRow[], varRows: VarRow[] | null | undefined): NativeRow[] {
  if (!varRows?.length) return rows;
  const m = new Map(varRows.map((v) => [v.name, v]));
  return rows.map((r) => {
    const v = m.get(r.name);
    return v ? { ...r, train: v.train ? rangeOf(v.train) : null, feasible: v.feasible ?? r.feasible } : r;
  });
}

/** ParamSet.native 요약 한 줄용: 정의 리비전·사용 변수 수 */
export const setDefText = (ps: ParamSet): string | null => (ps.native ? `변수 정의 rev ${ps.native.vars_revision ?? 0} · 사용 ${ps.native.vars_count ?? ps.parameters.length}개` : null);

/** 결과·배치 상세의 사용 변수 스냅숏 요약 한 줄(§4.1). 스냅숏이 없으면 null */
export function snapshotText(v: unknown): string | null {
  const s = v as VarsSnapshot | null | undefined;
  if (!s || !Array.isArray(s.variables)) return null;
  const added = s.variables.filter((x) => x.origin === "added").length;
  const excluded = s.excluded?.length ?? 0;
  const parts = [`변수 ${s.variables.length}개`];
  if (s.set_revision != null) parts.push(`세트 정의 rev ${s.set_revision}`);
  if (added) parts.push(`추가 ${added}`);
  if (excluded) parts.push(`제외 ${excluded}`);
  if (s.edited) parts.push("이 실행에서 편집");
  return parts.join(" · ");
}

/** ④ 일괄용 유효 템플릿: parameters = 사용 행(기준 범위) — 표본 계산 코드가 그대로 쓴다 */
export function effectiveParamSet(ps: ParamSet, rows: NativeRow[]): ParamSet {
  const base = new Map(ps.parameters.map((p) => [p.name, p]));
  return {
    ...ps,
    parameters: rows.filter((r) => r.use).map((r) => ({ ...(base.get(r.name) ?? { unit: r.unit }), name: r.name, nominal: r.nominal ?? 0, min: r.base.min, max: r.base.max, unit: r.unit }) as ParamSet["parameters"][number]),
  };
}
