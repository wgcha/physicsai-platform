// DOE 형상 그리드 미리보기 모델(doe-preview.md §5.2·§7) — 순수 함수만(시험 대상).
import type { DoePreview, DoePreviewCell, DoePreviewGen, DoePreviewReq, DoePreviewSelect, DoePreviewSource } from "../../../api/types";
import { failureBadge } from "../../stage4/geomview/viewerCore";

/** 한 페이지 = 6열 × 4행(DP-C3) */
export const PAGE_SIZE = 24;
export const GRID_COLUMNS = 6;

export const MSG = {
  tagNone: "태그 전 미리보기 — 기준면은 추출 기본값이라 실제 생성 형상과 조금 다를 수 있습니다. 형상 갱신만 확인하며 품질(morph·check) 실패는 생성 후에만 보입니다.",
  stale: "설정이 바뀌었습니다",
  legendTitle: "공칭 형상과의 거리(mm) — 모든 셀 같은 범위",
  unsupportedMulti: "다중 baseline DOE는 형상 미리보기를 지원하지 않습니다",
  unsupportedEngine: "형상 미리보기는 Native 형상 엔진에서만 쓸 수 있습니다",
  reuse: "표본표 재사용은 형상 미리보기 대상이 아닙니다",
  errorCell: "미리보기 오류 — 다시",
  genDiff: "미리보기는 형상 갱신(update)만 확인합니다 — 생성 때의 morph·check 실패는 배지로만 겹쳐 보입니다",
} as const;

export const ORDER_LABEL = { change: "변화 큰 순", doe: "DOE 순서", var: "변수 값" } as const;

/** 요청 본문(첫 페이지 offset 0) */
export function buildReq(source: DoePreviewSource, sampling: Record<string, unknown> | null | undefined, select: Partial<DoePreviewSelect> & Pick<DoePreviewSelect, "order">): DoePreviewReq {
  const sel: DoePreviewSelect = { order: select.order, offset: select.offset ?? 0, limit: select.limit ?? PAGE_SIZE };
  if (select.order === "var") {
    sel.var = select.var ?? null;
    if (select.desc) sel.desc = true;
  }
  return source.kind === "train_doe" ? { source, select: sel } : { source, sampling: sampling ?? null, select: sel };
}

/** 입력(출처·표본) 비교 키 — 선택(정렬·페이지)은 낡음 판정에 넣지 않는다(셀 캐시 키가 출처·정렬과 무관한 것과 같은 취지) */
export const inputKey = (source: DoePreviewSource, sampling: Record<string, unknown> | null | undefined): string => JSON.stringify([source, source.kind === "train_doe" ? null : sampling ?? null]);

export const isActive = (p: Pick<DoePreview, "status"> | null | undefined): boolean => !!p && (p.status === "QUEUED" || p.status === "RUNNING");

const num = (v: number) => String(Number(v.toPrecision(4)));

/** 변수 이름 줄임: 바디 접두 2토큰을 뺀다(CUSH_L_THK_1 → THK_1). 전체 이름은 툴팁 */
export function shortVarName(name: string): string {
  const t = name.split("_");
  return t.length >= 4 ? t.slice(2).join("_") : name;
}

export function relPct(rel: number): string {
  const p = Math.round(Math.abs(rel) * 100);
  return `${rel < 0 ? "−" : "+"}${p}%`;
}

/** 캡션 2줄째: "THK_1 13.1(+5%) · HOLE_R 4.2(−8%) · 외 9" (공칭 셀은 빈 문자열) */
export function changeText(c: DoePreviewCell): string {
  if (c.nominal) return "";
  const top = c.top_changes ?? [];
  const total = Object.keys(c.values ?? {}).length;
  const parts = top.map((t) => `${shortVarName(t.name)} ${num(t.value)}(${relPct(t.rel)})`);
  const rest = Math.max(0, total - top.length);
  if (rest > 0 && top.length) parts.push(`외 ${rest}`);
  return parts.join(" · ");
}

/** 마우스 올림 툴팁: 전체 값 표(이름 = 값) */
export function valuesTip(c: DoePreviewCell): string {
  const rows = Object.entries(c.values ?? {}).map(([k, v]) => `${k} = ${num(v)}`);
  return rows.length ? rows.join("\n") : "공칭(변경 없음)";
}

/** 캡션 1줄째 앞부분: 생성 전 `#17`(doe_no), 갤러리 `run 17` */
export function cellLabel(c: DoePreviewCell, gallery: boolean): string {
  if (c.nominal) return "공칭";
  if (c.doe_no == null) return "–";
  return gallery ? `run ${c.doe_no}` : `#${c.doe_no}`;
}

export type CellTone = "nominal" | "ok" | "fail" | "error" | "pending";
export function cellTone(c: DoePreviewCell): CellTone {
  if (c.status === "FAIL") return "fail";
  if (c.status === "ERROR") return "error";
  if (c.status === "PENDING") return "pending";
  return c.nominal ? "nominal" : "ok";
}

/** 실패 셀 배지 + 한 줄 사유(category 묶음은 GV §7.3 문구) */
export function failInfo(c: DoePreviewCell): { badge: string; text: string } | null {
  if (c.status !== "FAIL") return null;
  return { badge: failureBadge(c.category, c.code), text: c.message_ko ?? c.code ?? "형상을 만들 수 없습니다" };
}

/** 색 범위를 넘은 셀(▲범위 초과) */
export const overRange = (c: DoePreviewCell, range: [number, number] | undefined): boolean => !!range && c.max_disp_mm != null && c.max_disp_mm > range[1] + 1e-9;

export const GEN_STEP_LABEL: Record<string, string> = {
  GEN_PREP: "준비", UPDATE: "형상 갱신", MORPH: "morph", CHECK: "검사", TIE: "tie", WRITE: "입력 작성", EXTRACT: "추출",
};
/** 생성 후 겹침 배지(train_doe): 스킵 = 코드·단계, 대기 = "대기", OK = 없음 */
export function genBadge(g: DoePreviewGen | null | undefined): { tone: "bad" | "muted"; text: string } | null {
  if (!g || g.status === "OK") return null;
  if (g.status === "PENDING") return { tone: "muted", text: "대기" };
  const step = g.step ? GEN_STEP_LABEL[g.step] ?? g.step : null;
  return { tone: "bad", text: `스킵 ${g.code ?? ""}${step ? ` · ${step}` : ""}`.trim() };
}

export interface GridProgress {
  total: number;
  done: number;
  fail: number;
  error: number;
}
export function progressOf(cells: DoePreviewCell[]): GridProgress {
  return { total: cells.length, done: cells.filter((c) => c.status !== "PENDING").length, fail: cells.filter((c) => c.status === "FAIL").length, error: cells.filter((c) => c.status === "ERROR").length };
}
export const progressText = (p: GridProgress): string => `${p.done}/${p.total} 완료 · 실패 ${p.fail} · 오류 ${p.error}`;

/** 페이지들의 셀을 이어 붙인다(첫 페이지 = 공칭 + 표본, 이후 표본만) */
export const mergeCells = (pages: Pick<DoePreview, "cells">[]): DoePreviewCell[] => pages.flatMap((p) => p.cells);

/** [실패만] — 이미 렌더된 셀(PENDING 제외)에만 적용(§5.2) */
export const filterFailed = (cells: DoePreviewCell[], on: boolean): DoePreviewCell[] => (on ? cells.filter((c) => c.status === "FAIL" || c.status === "ERROR") : cells);

/** [다음 24개]가 있는가(이미 불러온 표본 수 < n_total) */
export function hasMore(pages: Pick<DoePreview, "n_total" | "cells">[]): boolean {
  if (!pages.length) return false;
  const loaded = mergeCells(pages).filter((c) => !c.nominal).length;
  return loaded < pages[0].n_total;
}

/** 요청 전 안내/상태 문구(서버 409 코드 → 한국어) */
export const PREVIEW_ERROR_TEXT: Record<string, string> = {
  DOE_PREVIEW_UNSUPPORTED: MSG.unsupportedMulti,
  DOE_PREVIEW_UNAVAILABLE: "형상 미리보기가 꺼져 있습니다(관리자 설정)",
  GEOM_PREP_STALE: "형상 준비본이 오래되었습니다 — '형상 준비 다시'를 실행하세요",
  PREVIEW_BUSY: "앞선 미리보기가 끝나면 다시 요청하세요",
};

/** paicad `render.TURBO16`(16색 이산 팔레트, 서버 썸네일과 같은 색) — 격자 공통 범례용. 0번 = 범위 0, 15번 = 범위 최댓값 */
export const TURBO16: readonly (readonly [number, number, number])[] = [
  [62, 42, 114], [74, 84, 215], [60, 128, 248], [42, 170, 239], [37, 206, 207], [50, 233, 166], [81, 250, 127], [126, 253, 93],
  [175, 244, 68], [220, 223, 51], [251, 190, 40], [255, 150, 33], [252, 106, 25], [221, 63, 17], [180, 29, 7], [148, 12, 0],
];
/** 가로 범례 CSS(16칸 계단, 보간 없음) */
export function turbo16Gradient(): string {
  const n = TURBO16.length;
  const stops = TURBO16.map(([r, g, b], i) => `rgb(${r} ${g} ${b}) ${(i / n) * 100}% ${((i + 1) / n) * 100}%`);
  return `linear-gradient(to right, ${stops.join(", ")})`;
}
