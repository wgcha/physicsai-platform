// phase3.md §14 S9 목(R-F 분할): 배치 기록(BatchRec·BatchRunRec)·상한 상수·라벨.
import type { BatchPreviewRow, InputKind, ParamSet } from "../api/types";

export const BATCH_MAX_RUNS = 200;
export const BATCH_TABLE_MAX_BYTES = 1048576;
export const CURVE_MAX_RUNS = 200;
export const MAX_MULTI = 8;
export const TERMINAL = ["SUCCEEDED", "FAILED", "CANCELED", "INTERRUPTED"];

type GenState = "PENDING" | "RUNNING" | "DONE" | "FAILED";
export interface BatchRunRec extends BatchPreviewRow {
  gen_state: GenState;
  gen_code: string | null;
  gen_message: string | null;
  predict_job_id: string | null;
}
export interface BatchRec {
  id: string;
  study_id: string;
  batch_no: number;
  job_id: string;
  param_set_id: string;
  model_id: string;
  input_kind: InputKind;
  /** DB source_kind(S15: 10종) */
  source_kind: string;
  /** source_meta(방식 인자·품질·이어서 추가 정보, §20.5) */
  meta: Record<string, unknown>;
  multi_execution: number;
  created_by: string;
  created_by_name: string;
  created_at: string;
  canceled: boolean;
  done_notified: boolean;
  runs: BatchRunRec[];
}

export const batchLabel = (no: number) => `B-${String(no).padStart(3, "0")}`;
export const batchRunKey = (n: number) => `run__${String(n).padStart(5, "0")}`;
export const round4 = (v: number) => Number(v.toPrecision(6));

export function inputKindOf(ps: ParamSet): InputKind {
  return ps.input_kind ?? "assembly";
}
