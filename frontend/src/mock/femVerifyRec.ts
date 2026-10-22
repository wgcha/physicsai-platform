// S16 V2 목(phase3 §21.3, R-F 분할): FEM 검증 기록(FemRec)·라벨·작업 사슬(재시도 따라가기·작업 만들기).
import type { Job, Study } from "../api/types";
import type { FemCompare, FemProblem, FemVerifySummary, FvStatus } from "../api/femVerify";
import { baseJob } from "./data";
import type { MockServer } from "./server";

export type SourceKind = FemVerifySummary["source_kind"];
export const MAX_ACTIVE = 4;
export const MOCK_SPDM_ROOT = "S:\\SPDM\\cushion";

export interface FemRec {
  id: string;
  study_id: string;
  fv_no: number;
  source_kind: SourceKind;
  source_label: string;
  links: FemVerifySummary["links"];
  predict_job_id: string | null;
  companion: boolean;
  param_set_id: string | null;
  model_id: string | null;
  values: Record<string, number>;
  applied_values: Record<string, number>;
  out_of_range: string[];
  assem_kind: "PREDICT_INPUT" | "TRAIN_DOE" | "CUSTOM";
  assem_label: string;
  assem_path: string | null;
  input_mode: "reuse" | "rebuild";
  hpc_mode: "command" | "scx";
  status: FvStatus;
  job_id: string | null;
  attempt_no: number;
  compare: FemCompare | null;
  failure: FemProblem | null;
  warnings: FemProblem[];
  media: { view: string; pred: [string, string | null]; fem: [string, string | null] }[];
  created_by: string;
  created_by_name: string;
  created_at: string;
  finished_at: string | null;
  notified: boolean;
  /** input-kind.md IK-8: 검증 대상 설계의 입력 종류(없으면 조립) */
  input?: "assembly" | "cushion";
}

export const fvLabel = (no: number) => `FV-${String(no).padStart(3, "0")}`;
export const TERMINAL = ["SUCCEEDED", "FAILED", "CANCELED", "INTERRUPTED"];
export const md = (iso_: string) => {
  const d = new Date(iso_);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
};

// ------------------------------------------------------------------ 작업 사슬
export function latest(srv: MockServer, id: string | null): Job | null {
  let j = id ? srv.jobs.find((x) => x.id === id) ?? null : null;
  for (let k = 0; j && k < 50; k++) {
    const next = srv.jobs.find((x) => x.retry_of_job_id === j!.id);
    if (!next) break;
    j = next;
  }
  return j;
}

export function newJob(srv: MockServer, s: Study, type: "PREDICT" | "FEM_VERIFY", params: Record<string, unknown>, by: { id: string; name: string }, retryOf: string | null = null): Job {
  const j = baseJob({ id: srv.nid("j"), study_id: s.id, project_id: s.project_id, study_title: s.title, job_type: type, state: "QUEUED", created_by: by.id, created_by_name: by.name, created_at: new Date().toISOString(), params, retry_of_job_id: retryOf });
  srv.jobs.push(j);
  srv.queueOrder.set(j.id, ++srv.queueSeq);
  return j;
}
