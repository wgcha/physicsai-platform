// 목: native 추출 조건(extract-filter.md §6) — 서버 physicsai_core/geometry/extract_filter.py normalize·summarize의 축소판.
// 요청 검사(422 EXTRACT_FILTER_INVALID problems[{key,message}]·EXTRACT_FILTER_UNSUPPORTED)와 응답용 정규화본·추출 요약·종류별 피처 걸러내기.
import type { ExtractFilter } from "../api/types";
import { err, type MockResp } from "./route";

const GROUP_ORDER = ["thickness", "height", "position", "hole_radius", "fillet"] as const;
const GROUP_COND: Record<string, string[]> = { thickness: ["thickness_mm", "face_area_min_mm2"], height: ["height_mm"], position: ["position_min_size_mm"], hole_radius: ["hole_radius_min_mm"], fillet: ["fillet_radius_min_mm"] };
const RANGE = ["thickness_mm", "height_mm"];
const SCALAR = ["face_area_min_mm2", "position_min_size_mm", "hole_radius_min_mm", "fillet_radius_min_mm"];
/** 피처 종류 → 그룹(§3.1) */
export const TYPE_GROUP: Record<string, string> = {
  THICKNESS: "thickness", RIB_THICKNESS: "thickness", POCKET_WIDTH: "thickness", RIB_HEIGHT: "height", POCKET_DEPTH: "height",
  HOLE_POS_U: "position", HOLE_POS_V: "position", RIB_POS_U: "position", RIB_POS_V: "position", HOLE_RADIUS: "hole_radius", FILLET_RADIUS: "fillet",
};
const isNum = (x: unknown): x is number => typeof x === "number" && Number.isFinite(x);

export type Problem = { key: string; message: string };

export function normalizeFilter(raw: unknown): { norm: ExtractFilter | null; problems: Problem[] } {
  if (raw == null) return { norm: null, problems: [] };
  const r = raw as { groups?: unknown; conditions?: Record<string, unknown> | null; draft_max_deg?: unknown };
  const problems: Problem[] = [];
  const groups: string[] = [];
  if (!Array.isArray(r.groups) || !r.groups.length) problems.push({ key: "groups", message: "찾을 종류를 하나 이상 고르세요" });
  else for (const g of r.groups) (GROUP_ORDER as readonly string[]).includes(g) && !groups.includes(g) ? groups.push(g) : problems.push({ key: "groups", message: `알 수 없거나 중복된 종류 그룹입니다: ${g}` });
  const cond = r.conditions ?? {};
  const kept: Record<string, unknown> = {};
  for (const k of RANGE) {
    const v = cond[k] as { min?: number | null; max?: number | null } | null | undefined;
    if (v == null) continue;
    const lo = v.min ?? null;
    const hi = v.max ?? null;
    let ok = true;
    if (lo !== null && !(isNum(lo) && lo >= 0)) (problems.push({ key: `conditions.${k}.min`, message: "0 이상의 값을 넣으세요" }), (ok = false));
    if (hi !== null && !(isNum(hi) && hi > 0)) (problems.push({ key: `conditions.${k}.max`, message: "0보다 큰 값을 넣으세요" }), (ok = false));
    if (ok && lo !== null && hi !== null && lo > hi) (problems.push({ key: `conditions.${k}`, message: "최솟값이 최댓값보다 큽니다" }), (ok = false));
    if (ok && (lo !== null || hi !== null)) kept[k] = { min: lo, max: hi };
  }
  for (const k of SCALAR) {
    const v = cond[k];
    if (v == null) continue;
    if (!(isNum(v) && v > 0)) problems.push({ key: `conditions.${k}`, message: "0보다 큰 값을 넣으세요" });
    else kept[k] = v;
  }
  const d = r.draft_max_deg ?? null;
  if (d !== null && !(isNum(d) && d > 0 && d < 45)) problems.push({ key: "draft_max_deg", message: "구배 허용각은 0°보다 크고 45°보다 작아야 합니다" });
  if (problems.length) return { norm: null, problems };
  const ordered = GROUP_ORDER.filter((g) => groups.includes(g));
  const allowed = new Set(ordered.flatMap((g) => GROUP_COND[g]));
  const conditions = Object.fromEntries([...RANGE, ...SCALAR].filter((k) => k in kept && allowed.has(k)).map((k) => [k, kept[k]]));
  return { norm: { groups: [...ordered], conditions, draft_max_deg: d } as ExtractFilter, problems: [] };
}

/** 요청 검사: 거부 응답 또는 정규화본(없으면 null). altair·쉘이면 422 UNSUPPORTED */
export function checkFilter(raw: unknown, opts: { native: boolean; shell?: boolean }): MockResp | { norm: ExtractFilter | null } {
  if (raw == null) return { norm: null };
  if (!opts.native || opts.shell) return err(422, "EXTRACT_FILTER_UNSUPPORTED", "찾을 종류 선택은 native 솔리드 추출에서만 쓸 수 있습니다");
  const { norm, problems } = normalizeFilter(raw);
  if (problems.length) return err(422, "EXTRACT_FILTER_INVALID", "추출 조건을 확인하세요", { problems });
  return { norm };
}

/** 선택한 그룹에 속한 종류인가(필터 없음 = 모두). 종류를 모르는 행은 유지 */
export const typeSelected = (type: string | undefined, f: ExtractFilter | null | undefined) => !f || !type || !TYPE_GROUP[type] || f.groups.includes(TYPE_GROUP[type] as never);

/** 추출 요약(§7.2 extract_summary) — 선택한 종류마다 채택 수와 제외 사유 몇 건 */
export function mockSummary(kinds: { type: string }[], f: ExtractFilter | null): Record<string, unknown> {
  const types: Record<string, unknown> = {};
  for (const t of Object.keys(TYPE_GROUP)) {
    const sel = typeSelected(t, f);
    const kept = kinds.filter((k) => k.type === t).length;
    types[t] = sel ? { selected: true, kept, excluded: t === "THICKNESS" ? { face_area: 180, thickness_range: 9, not_mutual: 21 } : t === "FILLET_RADIUS" ? { fillet_radius_min: 26 } : t === "RIB_POS_U" ? { shape: 2 } : {} } : { selected: false, kept: 0, excluded: {} };
  }
  return { filter_applied: !!f, types, png_rendered: kinds.length, png_elapsed_s: 8.2, elapsed_s: 72.5, rib_rejects: { cap_not_convex: 14, lateral_draft: 3, base_mismatch: 2, new_reason_x: 1 } };
}
