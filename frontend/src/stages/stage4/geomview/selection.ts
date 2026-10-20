// 표 ↔ 3D 양방향 선택 상태(geometry-view.md §7.2): 행 선택 = 하이라이트, 면 클릭 = 그 면을 쓰는 행 선택(여럿이면 선택 목록).
import { faceKey } from "./viewerCore";

export interface Selection {
  /** 선택 행(parameter) */
  row: string | null;
  /** 한 면을 여러 피처가 쓸 때 고를 행 목록(없으면 null) */
  choices: string[] | null;
}

export const NO_SELECTION: Selection = { row: null, choices: null };

/** 표 행 클릭: 같은 행이면 해제 */
export function pickRow(s: Selection, row: string): Selection {
  return { row: s.row === row ? null : row, choices: null };
}

/** 면 클릭(raycast → 삼각형 → _FACE_ID). 피처 없는 면·빈 곳 = 해제, 1개 = 그 행, 여럿 = 선택 목록(현재 행이 그 안이면 유지) */
export function pickFace(s: Selection, faceRows: Map<string, string[]>, hit: { body: string; face: number } | null): Selection {
  if (!hit) return NO_SELECTION;
  const rows = faceRows.get(faceKey(hit.body, hit.face)) ?? [];
  if (!rows.length) return NO_SELECTION;
  if (rows.length === 1) return { row: rows[0], choices: null };
  return { row: s.row && rows.includes(s.row) ? s.row : null, choices: rows };
}

/** 선택 목록에서 행 고르기 */
export function chooseRow(_s: Selection, row: string): Selection {
  return { row, choices: null };
}
