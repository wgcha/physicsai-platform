// S10 컨투어 캡처 방향(HyperView 뷰). 서버 media 응답의 label이 우선이고, 이 표는 설정·다시 캡처 체크 목록용.
import type { ViewKey } from "../api";

export const DEFAULT_VIEWS: ViewKey[] = ["iso", "front", "top", "right"];
export const VIEW_KEYS: ViewKey[] = ["iso", "front", "back", "top", "bottom", "left", "right"];
export const VIEW_LABEL: Record<string, string> = {
  iso: "등각(iso)",
  front: "정면",
  back: "뒷면",
  top: "윗면",
  bottom: "아랫면",
  left: "왼쪽",
  right: "오른쪽",
};
export const viewLabel = (v: string) => VIEW_LABEL[v] ?? v;

/** HyperView 평균 방식(avgmode) */
export const AVG_MODES: { key: string; label: string }[] = [
  // phase3.md §15.3 avgmode(""|simple|maximum|minimum|difference) — 서버가 그 밖 값은 422
  { key: "", label: "평균 없음" },
  { key: "simple", label: "단순 평균" },
  { key: "maximum", label: "최댓값" },
  { key: "minimum", label: "최솟값" },
  { key: "difference", label: "차이" },
];
