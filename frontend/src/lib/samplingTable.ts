// ① 표 붙여넣기 미리 검사(doe-methods.md §4.1 table, DM-C3): 서버 `_table` 파서와 같은 규칙으로 머리줄·행 수·값을 보고, 값이 학습 범위 밖이면 TABLE_OUT_OF_RANGE로 막는다(④는 범위 밖 허용이라 이 검사를 쓰지 않는다). 순수 함수만(React 없음).
export interface TableProblem {
  code: "TEXT_TOO_LARGE" | "TABLE_HEADER" | "TOO_FEW_ROWS" | "TOO_MANY_ROWS" | "TABLE_VALUE" | "TABLE_OUT_OF_RANGE";
  message: string;
}
export interface TableCheck {
  /** 데이터 행 수(머리줄 제외, 읽은 만큼) */
  rows: number;
  problems: TableProblem[];
}
export type NameRanges = Record<string, [number, number]>;

/** 설정 predict_batch.table_max_bytes 기본값(서버 기본) */
export const DEFAULT_TABLE_MAX_BYTES = 1048576;
const MIN_ROWS = 2;

const finite = (s: string | undefined): number | null => (s !== undefined && s.trim() !== "" && Number.isFinite(Number(s)) ? Number(s) : null);

export function checkTable(text: string, names: string[], ranges: NameRanges | null, maxRuns: number, maxBytes = DEFAULT_TABLE_MAX_BYTES): TableCheck {
  const bad = (problems: TableProblem[], rows = 0): TableCheck => ({ rows, problems });
  if (new TextEncoder().encode(text).length > maxBytes) return bad([{ code: "TEXT_TOO_LARGE", message: `표 내용이 ${maxBytes} 바이트를 넘습니다` }]);
  const lines = text.replace(/^﻿/, "").split(/\r?\n/).filter((l) => l.trim());
  if (!lines.length) return bad([{ code: "TABLE_HEADER", message: "첫 줄에 파라미터 이름 헤더가 필요합니다" }]);
  const sep = lines[0].includes("\t") ? "\t" : ",";
  const split = (l: string) => l.split(sep).map((c) => c.trim());
  const head = split(lines[0]);
  const data = lines.slice(1).map(split);
  const problems: TableProblem[] = [];
  const seen = new Set<string>();
  for (const h of head) {
    if (h.toLowerCase() === "doe") continue;
    if (!names.includes(h)) problems.push({ code: "TABLE_HEADER", message: `'${h}'는 사용 파라미터가 아닙니다` });
    else if (seen.has(h)) problems.push({ code: "TABLE_HEADER", message: `'${h}' 열이 중복됩니다` });
    seen.add(h);
  }
  const missing = names.filter((n) => !seen.has(n));
  if (missing.length) problems.push({ code: "TABLE_HEADER", message: `파라미터 열이 없습니다: ${missing.join(", ")}` });
  if (problems.length) return bad(problems, data.length);
  if (data.length < MIN_ROWS) problems.push({ code: "TOO_FEW_ROWS", message: `데이터 행은 ${MIN_ROWS}개 이상이어야 합니다(현재 ${data.length}개)` });
  else if (data.length > maxRuns) problems.push({ code: "TOO_MANY_ROWS", message: `행은 최대 ${maxRuns}개입니다(현재 ${data.length}개)` });
  if (problems.length) return bad(problems, data.length);
  let oor = 0;
  data.forEach((cells, i) => {
    if (cells.length !== head.length) return problems.push({ code: "TABLE_VALUE", message: `${i + 1}행 열 수(${cells.length})가 헤더(${head.length})와 다릅니다` });
    const badCols = head.filter((h, j) => h.toLowerCase() !== "doe" && finite(cells[j]) === null);
    if (badCols.length) return problems.push({ code: "TABLE_VALUE", message: `${i + 1}행 값이 유한한 숫자가 아닙니다: ${badCols.join(", ")}` });
    if (!ranges || oor >= 1) return;
    for (const [j, h] of head.entries()) {
      const r = ranges[h];
      const v = finite(cells[j]);
      if (r && v !== null && (v < r[0] || v > r[1])) {
        oor++;
        return problems.push({ code: "TABLE_OUT_OF_RANGE", message: `'${h}' 값 ${v}가 학습 범위 ${r[0]}~${r[1]} 밖입니다` });
      }
    }
  });
  return { rows: data.length, problems };
}
