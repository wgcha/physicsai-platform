// ⑤ 등가성 판정 레시피 편집 상태(equiv-check.md §3·§7) — 순수 함수(React 없음).
// 편집 표 행 = 지표 + 사용 여부. 실행 body는 "불러온 정의"와 비교해 (a) 빈 원천만 채웠으면 bindings(레시피 그대로),
// (b) 그 밖이 바뀌었으면 recipe_inline(수정됨, base = 원 레시피)로 보낸다 — 판정 실행은 항상 사용자가 선택·확인한 레시피로.
import type { EqCheckCreate, EqDefinition, EqMetric, EqSource, EqVerdict } from "../../api/equivCheck";

export const RECIPE_KEY = "physicsai.analysis.equiv.recipe";

export interface EditRow extends EqMetric {
  use: boolean;
}

export function readRecipeKey(): string | null {
  try {
    return localStorage.getItem(RECIPE_KEY);
  } catch {
    return null;
  }
}

export function writeRecipeKey(key: string): void {
  try {
    localStorage.setItem(RECIPE_KEY, key);
  } catch {
    /* 저장 불가 무시 */
  }
}

export const toRows = (d: EqDefinition): EditRow[] => d.metrics.map((m) => ({ ...m, tol: { ...m.tol }, source: m.source ? ({ ...m.source } as EqSource) : null, use: true }));

export function toDefinition(rows: EditRow[], base: EqDefinition): EqDefinition {
  return { ...base, metrics: rows.filter((r) => r.use).map(({ use: _u, ...m }) => m) };
}

const same = (a: unknown, b: unknown) => JSON.stringify(a ?? null) === JSON.stringify(b ?? null);

/** 불러온 정의와 비교해 실행 body의 레시피 부분을 만든다(위 설명). */
export function recipeBody(loaded: EqDefinition, rows: EditRow[], ref: { key: string; version: number } | null, pairRule?: EqDefinition["pair_rule"]): Pick<EqCheckCreate, "recipe" | "recipe_inline" | "bindings"> {
  const edited = { ...toDefinition(rows, loaded), pair_rule: pairRule ?? loaded.pair_rule };
  const bindings: Record<string, EqSource | null> = {};
  let modified = edited.metrics.length !== loaded.metrics.length || !same(edited.pair_rule, loaded.pair_rule);
  for (const m of edited.metrics) {
    const o = loaded.metrics.find((x) => x.id === m.id);
    if (!o) {
      modified = true;
      continue;
    }
    const { source: ms, ...mRest } = m;
    const { source: os, ...oRest } = o;
    if (!same(mRest, oRest)) modified = true;
    if (!same(ms, os)) {
      if (os === null && ms !== null) bindings[m.id] = ms;
      else modified = true;
    }
  }
  // ref 없음 = 1회용(adhoc) 이력 스냅숏 → 항상 정의 그대로 보낸다(base 없음)
  if (modified || !ref) {
    const def = { ...edited, metrics: edited.metrics.map((m) => ({ ...m })) };
    return { recipe_inline: { definition: def, base: ref }, bindings: null };
  }
  return { recipe: ref, bindings: Object.keys(bindings).length ? bindings : null };
}

/** 사용 중인 지표(필수·참고 모두) 중 응답 원천이 비어 있는 것 — 사용자가 연결(또는 지표를 빼기) 전엔 실행 불가.
 * mesh_volume은 원천 불필요(기본 include 적분, 레시피에서 원천 선택) */
export const unboundMetrics = (rows: EditRow[]): EditRow[] => rows.filter((r) => r.use && r.kind !== "mesh_volume" && r.source === null);

/** 시스템 기본(제안값)은 그대로 실행할 수 없다 — 복제(다른 이름으로 저장)해 확인한 사용자 레시피만 실행 */
export const isSystemRef = (ref: { key: string } | null, systemKey: string): boolean => ref?.key === systemKey;

export const KIND_LABEL: Record<EqMetric["kind"], string> = { scalar: "스칼라", curve_corr: "곡선 상관", curve_nrmse: "곡선 NRMSE", mesh_volume: "메시 부피" };

export function tolText(m: EqMetric): string {
  const t = m.tol;
  if (m.kind === "scalar" || m.kind === "mesh_volume") {
    const parts: string[] = [];
    if (t.rel_pct != null) parts.push(`상대 ${t.rel_pct}%`);
    if (t.abs != null) parts.push(`절대 ${t.abs}`);
    return parts.join(" 또는 ") || "—";
  }
  if (m.kind === "curve_corr") return `r ≥ ${t.corr_min ?? 0}`;
  return `NRMSE ≤ ${t.nrmse_max_pct ?? 0}%`;
}

export function sourceText(s: EqSource | null): string {
  if (!s) return "연결 필요";
  switch (s.type) {
    case "perf":
      return `성능 ${s.perf}`;
    case "h3d":
      return `H3D ${s.datatype}${s.component ? `/${s.component}` : ""} ${s.stat ?? "MAX"}`;
    case "curve":
      return `곡선 ${s.series ?? "(첫 계열)"}${s.stat ? ` ${s.stat}` : ""}`;
    case "mesh_volume":
      return `메시 부피 ${Array.isArray(s.parts) ? `part ${s.parts.join(",")}` : "쿠션"}${s.origin && s.origin !== "mesh" ? ` · ${s.origin}` : ""}`;
  }
}

export const VERDICT_TEXT: Record<EqVerdict, string> = { PASS: "통과", FAIL: "미달", INCOMPLETE: "판정 불가" };
export const VERDICT_CLASS: Record<EqVerdict, string> = { PASS: "ok", FAIL: "bad", INCOMPLETE: "muted" };
export const STATUS_TEXT: Record<string, string> = { PASS: "통과", FAIL: "미달", NA: "NA" };

/** 수정 허용오차 입력(문자열) → 숫자 또는 null(빈칸) */
export const numOrNull = (s: string): number | null => (s.trim() === "" ? null : Number.isFinite(Number(s)) ? Number(s) : null);

/** 이력에서 레시피 불러올 때 안내: 원 레시피가 더 새 버전이면 "현재 v5 · 이력 v3" */
export function versionNote(hist: { version: number | null; current_version: number | null; deleted: boolean; source: string }): string | null {
  if (hist.source === "adhoc") return "1회용(저장되지 않은) 레시피 스냅숏";
  if (hist.deleted) return "삭제된 레시피(스냅숏으로 불러옵니다)";
  if (hist.current_version != null && hist.version != null && hist.current_version > hist.version) return `현재 v${hist.current_version} · 이력 v${hist.version}`;
  return null;
}
