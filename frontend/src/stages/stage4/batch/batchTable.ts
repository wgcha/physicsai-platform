// ④ 일괄 예측 결과 표·그래프 공용 규칙(phase3.md §14.8): 행 상태 문구·정렬·그래프 종류 선택·진행 여부.
import type { BatchRowState, BatchStatus, PredictBatchRow } from "../../../api";

/** 행 상태 → 화면 문구(§14.7 state 주석 그대로) */
export const ROW_STATE_LABEL: Record<BatchRowState, string> = {
  GEN_PENDING: "생성 대기",
  GENERATING: "생성 중",
  GEN_FAILED: "생성 실패",
  QUEUED: "예측 대기",
  RUNNING: "실행 중",
  SUCCEEDED: "완료",
  FAILED: "실패",
  CANCELED: "취소",
};

export const BATCH_STATUS_LABEL: Record<BatchStatus, string> = {
  GENERATING: "입력 생성 중",
  PREDICTING: "예측 중",
  DONE: "완료",
  FAILED: "실패",
  CANCELED: "취소",
};

export const isBatchActive = (s: BatchStatus) => s === "GENERATING" || s === "PREDICTING";
export const isRowFailed = (s: BatchRowState) => s === "GEN_FAILED" || s === "FAILED" || s === "CANCELED";

/** 정렬 키: "doe" 또는 "<응답 이름>:asc|desc" */
export type SortKey = "doe" | `${string}:asc` | `${string}:desc`;

export function sortOptions(responses: string[]): { key: SortKey; label: string }[] {
  return [
    ...responses.flatMap((r) => [
      { key: `${r}:asc` as SortKey, label: `${r} 낮은 순` },
      { key: `${r}:desc` as SortKey, label: `${r} 높은 순` },
    ]),
    { key: "doe", label: "DOE # 순" },
  ];
}

/** 응답 정렬은 값 없는 행(진행 중·실패)을 뒤로, 같으면 DOE # 순 */
export function sortRows(rows: PredictBatchRow[], key: SortKey): PredictBatchRow[] {
  const out = [...rows];
  if (key === "doe") return out.sort((a, b) => a.doe_no - b.doe_no);
  const i = key.lastIndexOf(":");
  const name = key.slice(0, i);
  const dir = key.slice(i + 1) === "desc" ? -1 : 1;
  const val = (r: PredictBatchRow) => {
    const v = r.responses?.[name];
    return typeof v === "number" && Number.isFinite(v) ? v : null;
  };
  return out.sort((a, b) => {
    const va = val(a);
    const vb = val(b);
    if (va === null && vb === null) return a.doe_no - b.doe_no;
    if (va === null) return 1;
    if (vb === null) return -1;
    return va === vb ? a.doe_no - b.doe_no : (va - vb) * dir;
  });
}

/** 그래프 선택 규칙: 변수 1 + 응답 1 → 2D, 변수 2 + 응답 1 → 3D, 그 밖 → 안내 */
export type PlotKind = "2d" | "3d" | "none";
export function plotKind(vars: string[], resps: string[]): PlotKind {
  if (resps.length !== 1) return "none";
  if (vars.length === 1) return "2d";
  if (vars.length === 2) return "3d";
  return "none";
}
export const PLOT_HINT = "변수 1~2개와 응답 1개를 고르세요";

/** 그래프 점: 반영값(정수 반올림 후) 기준, 응답 값이 있는 행만 */
export function plotPoints(rows: PredictBatchRow[], vars: string[], resp: string) {
  const out: { doe_no: number; run_key: string; v: number[]; r: number }[] = [];
  for (const row of rows) {
    const r = row.responses?.[resp];
    if (typeof r !== "number" || !Number.isFinite(r)) continue;
    const v = vars.map((n) => row.applied_values?.[n] ?? row.values[n]);
    if (v.some((x) => typeof x !== "number" || !Number.isFinite(x))) continue;
    out.push({ doe_no: row.doe_no, run_key: row.run_key, v, r });
  }
  return out;
}

/** "B-003 run__00007" 폴더 이름 → 짧은 표시 */
export function runFolderName(folder: string, runKey: string): string {
  return folder.split(/[\\/]/).filter(Boolean).pop() || runKey;
}
