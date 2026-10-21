// 표 ↔ 3D 양방향 다중 선택 상태(geometry-view.md §7.2): 행 클릭 = 단일(다시 = 해제), Ctrl/⌘ = 토글 추가, Shift = 범위.
// 면 클릭 = 그 면을 쓰는 행 선택(Ctrl이면 토글 추가, 여럿이면 선택 목록).
import { useCallback, useEffect, useMemo, useRef, useState, type MouseEvent, type RefObject } from "react";
import { faceKey, selectionColor } from "./viewerCore";

export interface RowSel {
  /** 선택 행(선택한 순서 = 색 순서) */
  rows: string[];
  /** Shift 범위의 기준 행 */
  anchor: string | null;
}
export const NO_SELECTION: RowSel = { rows: [], anchor: null };

export interface ClickMods {
  ctrl?: boolean;
  shift?: boolean;
}

/** 표 행 클릭. order = 표에 보이는 행 순서(Shift 범위용) */
export function clickRow(s: RowSel, order: string[], row: string, mods: ClickMods = {}): RowSel {
  if (mods.shift && s.anchor && order.includes(s.anchor) && order.includes(row)) {
    const a = order.indexOf(s.anchor);
    const b = order.indexOf(row);
    const range = order.slice(Math.min(a, b), Math.max(a, b) + 1);
    // 기준 행이 앞에 오도록(색 순서 안정) 정렬
    const ordered = a <= b ? range : [...range].reverse();
    const rows = mods.ctrl ? [...s.rows, ...ordered.filter((r) => !s.rows.includes(r))] : ordered;
    return { rows, anchor: s.anchor };
  }
  if (mods.ctrl || mods.shift) {
    // Shift인데 기준이 없으면 Ctrl처럼 추가
    return s.rows.includes(row) ? { rows: s.rows.filter((r) => r !== row), anchor: row } : { rows: [...s.rows, row], anchor: row };
  }
  if (s.rows.length === 1 && s.rows[0] === row) return NO_SELECTION;
  return { rows: [row], anchor: row };
}

/** 면 클릭(raycast → 삼각형 → _FACE_ID)이 가리키는 행 후보 */
export function faceCandidates(faceRows: Map<string, string[]>, hit: { body: string; face: number } | null): string[] {
  return hit ? faceRows.get(faceKey(hit.body, hit.face)) ?? [] : [];
}

export type FacePick =
  | { kind: "set"; rows: string[]; focus: string | null }
  /** 한 면을 여러 피처가 쓸 때 — 선택 목록을 띄운다 */
  | { kind: "choices"; choices: string[] };

/** 면 클릭 결과. 빈 곳·피처 없는 면: 일반 = 해제, Ctrl = 변화 없음. 1개 = 그 행(Ctrl이면 토글 추가).
 *  여럿: 이미 선택에 있으면(일반) 그 행만 유지, 아니면 선택 목록 */
export function pickFace(rows: string[], faceRows: Map<string, string[]>, hit: { body: string; face: number } | null, additive = false): FacePick {
  const cands = faceCandidates(faceRows, hit);
  if (!cands.length) return { kind: "set", rows: additive ? rows : [], focus: null };
  if (cands.length === 1) {
    const r = cands[0];
    if (additive) return rows.includes(r) ? { kind: "set", rows: rows.filter((x) => x !== r), focus: null } : { kind: "set", rows: [...rows, r], focus: r };
    return { kind: "set", rows: [r], focus: r };
  }
  const kept = cands.find((r) => rows.includes(r));
  if (kept && !additive) return { kind: "set", rows: [kept], focus: kept };
  return { kind: "choices", choices: cands };
}

/** 선택 목록에서 행 고르기(Ctrl로 열었으면 추가) */
export function chooseRow(rows: string[], row: string, additive = false): string[] {
  if (!additive) return [row];
  return rows.includes(row) ? rows : [...rows, row];
}

export interface RowSelection {
  rows: string[];
  hover: string | null;
  setHover: (row: string | null) => void;
  clear: () => void;
  /** 3D에서 선택이 바뀜 → 반영 + focus 행으로 표 스크롤 */
  from3d: (rows: string[], focus?: string | null) => void;
  tableRef: RefObject<HTMLDivElement>;
  /** <tr>에 펼친다: 클릭·호버·선택 표시 */
  rowProps: (row: string) => {
    "data-row": string;
    "aria-selected": boolean;
    className: string;
    style?: Record<string, string>;
    onClick: (e: MouseEvent<HTMLTableRowElement>) => void;
    onMouseDown: (e: MouseEvent<HTMLTableRowElement>) => void;
    onMouseEnter: () => void;
    onMouseLeave: () => void;
  };
}

/** 표 스크롤 상자 안에서만 그 행이 보이게 스크롤(페이지 스크롤을 일으키지 않는다 — scrollIntoView 대신 scrollTop 직접 조정). 머리글(sticky) 높이만큼 비운다 */
export function scrollRowIntoView(box: HTMLElement | null, row: string) {
  const tr = Array.from(box?.querySelectorAll<HTMLElement>("tr[data-row]") ?? []).find((el) => el.dataset.row === row);
  if (!box || !tr) return;
  const head = box.querySelector("thead")?.getBoundingClientRect().height ?? 0;
  const b = box.getBoundingClientRect();
  const r = tr.getBoundingClientRect();
  if (r.top < b.top + head) box.scrollTop += r.top - (b.top + head);
  else if (r.bottom > b.bottom) box.scrollTop += r.bottom - b.bottom;
}

const INTERACTIVE = "input,button,select,textarea,a,label";

/** 표 행 다중 선택 + 호버 상태. order = 표 행 순서. 행 색 = 선택 순서의 팔레트 색(CSS 변수 --sel-color) */
export function useRowSelection(order: string[]): RowSelection {
  const [sel, setSel] = useState<RowSel>(NO_SELECTION);
  const [hover, setHoverNow] = useState<string | null>(null);
  const hoverTimer = useRef(0);
  /** 호버는 잠깐(50ms) 머문 뒤에만 반영 — 표를 훑을 때마다 3D·행 전체를 다시 그리지 않게(대형 표 성능) */
  const setHover = useCallback((row: string | null) => {
    window.clearTimeout(hoverTimer.current);
    if (row == null) return setHoverNow(null);
    hoverTimer.current = window.setTimeout(() => setHoverNow(row), 50);
  }, []);
  useEffect(() => () => window.clearTimeout(hoverTimer.current), []);
  const tableRef = useRef<HTMLDivElement>(null);
  const orderRef = useRef(order);
  orderRef.current = order;
  const valid = useMemo(() => sel.rows.filter((r) => order.includes(r)), [sel.rows, order]);
  const from3d = useCallback((rows: string[], focus?: string | null) => {
    setSel({ rows, anchor: focus ?? rows[rows.length - 1] ?? null });
    if (focus) requestAnimationFrame(() => scrollRowIntoView(tableRef.current, focus));
  }, []);
  const rowProps: RowSelection["rowProps"] = (row) => {
    const i = valid.indexOf(row);
    return {
      "data-row": row,
      "aria-selected": i >= 0,
      className: i >= 0 ? "picked" : "",
      style: i >= 0 ? { "--sel-color": selectionColor(i) } : undefined,
      onClick: (e) => {
        if ((e.target as HTMLElement).closest(INTERACTIVE)) return;
        setSel((s) => clickRow(s, orderRef.current, row, { ctrl: e.ctrlKey || e.metaKey, shift: e.shiftKey }));
      },
      // Shift+클릭이 글자 드래그 선택으로 번지지 않게
      onMouseDown: (e) => {
        if (e.shiftKey && !(e.target as HTMLElement).closest(INTERACTIVE)) e.preventDefault();
      },
      onMouseEnter: () => setHover(row),
      onMouseLeave: () => setHover(null),
    };
  };
  return { rows: valid, hover, setHover, clear: () => setSel(NO_SELECTION), from3d, tableRef, rowProps };
}
