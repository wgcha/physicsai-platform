// S14 두 출처 겹쳐 보기 규칙(phase3.md §19.6, A6): 파라미터 이름 집합 판정(대소문자 구분·순서 무관), 공통 응답, 색 막대 합집합 범위, 메타 비교. 순수 함수.
import { isFin, type ResultTable, type RtMeta } from "./resultTable";

export interface NameDiff {
  same: boolean;
  /** 기본(A)에만 있는 이름 / 비교(B)에만 있는 이름 */
  onlyA: string[];
  onlyB: string[];
}

export function nameSetDiff(a: ResultTable, b: ResultTable): NameDiff {
  const sa = new Set(a.parameters.map((p) => p.name));
  const sb = new Set(b.parameters.map((p) => p.name));
  const onlyA = [...sa].filter((n) => !sb.has(n));
  const onlyB = [...sb].filter((n) => !sa.has(n));
  return { same: !onlyA.length && !onlyB.length, onlyA, onlyB };
}

export const mismatchText = (d: NameDiff) => `파라미터 이름이 달라 겹쳐 볼 수 없습니다 — 다른 쪽에만 있음: ${[...d.onlyA, ...d.onlyB].join(", ")}`;
export const NO_COMMON_RESP_TEXT = "두 표에 같은 이름의 응답이 없어 값을 겹쳐 볼 수 없습니다";
export const META_DIFF_TEXT = "메타 다름";

/** 두 표에 모두 있는 응답 이름(기본 표 순서) */
export function commonResponses(a: ResultTable, b: ResultTable): string[] {
  const sb = new Set(b.responses.map((r) => r.name));
  return a.responses.map((r) => r.name).filter((n) => sb.has(n));
}

/** 두 값 목록의 합집합 범위(색 막대 공용). 값이 없으면 null */
export function unionRange(...lists: (number | null | undefined)[][]): [number, number] | null {
  const vs = lists.flat().filter(isFin);
  return vs.length ? [Math.min(...vs), Math.max(...vs)] : null;
}

export function metaChips(m: RtMeta): { key: keyof RtMeta; label: string; value: string }[] {
  return [
    { key: "engine_version", label: "엔진", value: m.engine_version ?? "—" },
    { key: "baseline_id", label: "기존안", value: m.baseline_id ?? "—" },
    { key: "scene", label: "scene", value: m.scene ?? "—" },
  ];
}

/** 둘 다 값이 있는 칸이 하나라도 다르면 "메타 다름" */
export function metaDiffers(a: RtMeta, b: RtMeta): boolean {
  return (["engine_version", "baseline_id", "scene"] as const).some((k) => a[k] !== null && b[k] !== null && a[k] !== b[k]);
}
