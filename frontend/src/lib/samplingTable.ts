// ① 표 붙여넣기 미리 검사(doe-methods.md §4.1 table, DM-C3): 서버 `sampling/matrix_basic._table` + `stage1_train_data/doe_platform._finish`와 같은 규칙·코드·문구.
// 구분자 = 첫 줄에 탭이 있으면 탭 아니면 쉼표 · 크기 table_max_bytes(기본 1 MiB, 넘으면 TEXT_TOO_LARGE) · 행 수 2~platform_max_runs(TOO_FEW_ROWS·TOO_MANY_ROWS)
// · 헤더는 대소문자 구분 정확 일치, doe 열(대소문자 무시)은 무시, 모르는·중복·누락 열은 TABLE_HEADER · 값은 float로 읽어 유한해야 함(TABLE_VALUE, row) · 학습 범위 밖이면 TABLE_OUT_OF_RANGE(경계값 허용, row).
// ④는 범위 밖을 허용하고 1행도 되므로 이 검사를 쓰지 않는다. 순수 함수만(React 없음).
export interface TableProblem {
  code: "TEXT_TOO_LARGE" | "TABLE_HEADER" | "TOO_FEW_ROWS" | "TOO_MANY_ROWS" | "TABLE_VALUE" | "TABLE_OUT_OF_RANGE";
  message: string;
  /** 1부터 세는 데이터 행(TABLE_VALUE·TABLE_OUT_OF_RANGE) — 서버 problems[].row */
  row?: number;
}
export interface TableCheck {
  /** 데이터 행 수(머리줄 제외, 읽은 만큼) */
  rows: number;
  problems: TableProblem[];
}
export type NameRanges = Record<string, [number, number]>;

/** 설정 predict_batch.table_max_bytes 기본값(서버 기본) */
export const DEFAULT_TABLE_MAX_BYTES = 1048576;
/** ①은 2행 이상(서버 doe_platform._finish) */
const MIN_ROWS = 2;
/** 서버가 행 오류를 모으는 상한(MAX_PROBLEMS) */
const MAX_PROBLEMS = 100;

// Python float()가 받는 십진 표기(밑줄 숫자 구분 포함)만 읽는다 — JS Number()의 0x·0b·0o는 서버가 거부한다
const NUM = /^[+-]?(?:\d+(?:_\d+)*(?:\.(?:\d+(?:_\d+)*)?)?|\.\d+(?:_\d+)*)(?:[eE][+-]?\d+(?:_\d+)*)?$/;
const finite = (s: string | undefined): number | null => {
  const t = s?.trim() ?? "";
  if (!NUM.test(t)) return null;
  const v = Number(t.replace(/_/g, ""));
  return Number.isFinite(v) ? v : null;
};

/** Python `%g`(유효 6자리) — 서버 TABLE_OUT_OF_RANGE 문구와 같은 숫자 표기 */
export function fmtG(x: number): string {
  if (x === 0) return Object.is(x, -0) ? "-0" : "0";
  const exp = Number(x.toExponential(5).split("e")[1]);
  if (exp < -4 || exp >= 6) {
    const [m, e] = x.toExponential(5).split("e");
    const mant = m.includes(".") ? m.replace(/0+$/, "").replace(/\.$/, "") : m;
    const n = Math.abs(Number(e));
    return `${mant}e${Number(e) < 0 ? "-" : "+"}${n < 10 ? "0" : ""}${n}`;
  }
  const f = x.toFixed(Math.max(0, 5 - exp));
  return f.includes(".") ? f.replace(/0+$/, "").replace(/\.$/, "") : f;
}

/** Python `str.splitlines()`와 같은 줄 나눔 */
const LINE_BREAK = /\r\n|[\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029]/;

/** Python csv.reader(기본 방언) 한 줄 읽기: 필드 맨 앞의 "만 따옴표 시작, ""는 따옴표 하나 */
function splitRow(line: string, sep: string): string[] {
  const out: string[] = [];
  let cur = "";
  let q = false;
  let atStart = true;
  for (let i = 0; i < line.length; i++) {
    const c = line[i];
    if (q) {
      if (c === '"') {
        if (line[i + 1] === '"') (cur += '"', i++);
        else q = false;
      } else cur += c;
    } else if (c === '"' && atStart) {
      q = true;
      atStart = false;
    } else if (c === sep) {
      out.push(cur);
      cur = "";
      atStart = true;
    } else {
      cur += c;
      atStart = false;
    }
  }
  out.push(cur);
  return out;
}

export function checkTable(text: string, names: string[], ranges: NameRanges | null, maxRuns: number, maxBytes = DEFAULT_TABLE_MAX_BYTES): TableCheck {
  const problems: TableProblem[] = [];
  const add = (code: TableProblem["code"], message: string, row?: number) => {
    if (problems.length < MAX_PROBLEMS) problems.push(row === undefined ? { code, message } : { code, message, row });
  };
  if (new TextEncoder().encode(text).length > maxBytes) {
    add("TEXT_TOO_LARGE", `표 내용이 ${maxBytes} 바이트를 넘습니다`);
    return { rows: 0, problems };
  }
  const lines = text.replace(/^﻿+/, "").split(LINE_BREAK).filter((l) => l.trim());
  if (!lines.length) {
    add("TABLE_HEADER", "첫 줄에 파라미터 이름 헤더가 필요합니다");
    return { rows: 0, problems };
  }
  const sep = lines[0].includes("\t") ? "\t" : ",";
  const parsed = lines.map((l) => splitRow(l, sep));
  const head = parsed[0].map((h) => h.trim());
  const data = parsed.slice(1);
  const want = new Set(names);
  const seen = new Set<string>();
  for (const h of head) {
    if (h.toLowerCase() === "doe") continue;
    if (!want.has(h)) add("TABLE_HEADER", `'${h}'는 템플릿 파라미터가 아닙니다`);
    else if (seen.has(h)) add("TABLE_HEADER", `'${h}' 열이 중복됩니다`);
    seen.add(h);
  }
  const missing = names.filter((n) => !seen.has(n));
  if (missing.length) add("TABLE_HEADER", `파라미터 열이 없습니다: ${missing.join(", ")}`);
  if (problems.length) return { rows: data.length, problems };
  if (!data.length) add("TOO_FEW_ROWS", "데이터 행이 1개 이상 필요합니다");
  else if (data.length > maxRuns) add("TOO_MANY_ROWS", `행은 최대 ${maxRuns}개입니다(현재 ${data.length}개)`);
  if (problems.length) return { rows: data.length, problems };
  const vals: Record<string, number>[] = [];
  data.forEach((cells, idx) => {
    const i = idx + 1;
    if (cells.length !== head.length) return add("TABLE_VALUE", `${i}행 열 수(${cells.length})가 헤더(${head.length})와 다릅니다`, i);
    const badCols = head.filter((h, j) => h.toLowerCase() !== "doe" && finite(cells[j]) === null);
    if (badCols.length) return add("TABLE_VALUE", `${i}행 값이 유한한 숫자가 아닙니다: ${badCols.join(", ")}`, i);
    const row: Record<string, number> = {};
    head.forEach((h, j) => {
      if (h.toLowerCase() !== "doe") row[h] = finite(cells[j]) as number;
    });
    vals.push(row);
  });
  // 서버는 값 문제가 하나라도 있으면 행 수·범위 검사를 하지 않는다(doe_platform._finish: plan.problems가 비었을 때만)
  if (problems.length) return { rows: data.length, problems };
  if (data.length < MIN_ROWS) {
    add("TOO_FEW_ROWS", `행은 ${MIN_ROWS}개 이상이어야 합니다(현재 ${data.length}개)`);
    return { rows: data.length, problems };
  }
  if (ranges) {
    // 범위 판정 순서 = 학습 범위(파라미터) 순서, 경계값은 허용
    vals.forEach((row, idx) => {
      for (const n of names) {
        const r = ranges[n];
        const v = row[n];
        if (r && v !== undefined && (v < r[0] || v > r[1])) add("TABLE_OUT_OF_RANGE", `'${n}' 값 ${fmtG(v)}가 학습 범위 ${fmtG(r[0])}~${fmtG(r[1])} 밖입니다`, idx + 1);
      }
    });
  }
  return { rows: data.length, problems };
}
