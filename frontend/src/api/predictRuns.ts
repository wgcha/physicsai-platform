// S16 V1(phase3 §21.2): ④ 단일 예측 실행 목록. GET /studies/{id}/predict-runs · GET /predict-runs/{job_id}.
// openapi 반영(BE-V1) 뒤에는 생성 타입과 같은 모양인지 `lint`로 확인한다(여기는 계약 모양을 손으로 고정).
import { request, requestPage } from "./client";
import type { ContourDisplay, JobState, PredictInput } from "./types";

export type PredictRunMode = "all" | "template" | "prepared";

export interface PredictRunSummary {
  job_id: string;
  root_job_id: string;
  /** 재시도 묶음 시도 수(1 = 재시도 없음) */
  attempts: number;
  state: JobState;
  /** manual = 사용자 예측, fem_verify = FEM 검증 동반 예측(V2) */
  origin: "manual" | "fem_verify";
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  duration_s: number | null;
  created_by_name: string;
  input_mode: "template" | "prepared";
  /** input-kind.md IK-10: 이 실행의 입력 종류(조립|쿠션). prepared는 starter로 판정한 값 */
  input: PredictInput;
  template: { id: string; label: string | null; input_kind: string } | null;
  model: { id: string; name: string; version: number } | null;
  values: Record<string, number>;
  applied_values: Record<string, number>;
  out_of_range: string[];
  input_path: string | null;
  starter: string | null;
  /** 최대 5개 */
  responses: { name: string; unit: string | null; predicted: number | null }[];
  capture: { status: string; views: string[] } | null;
  has_curve: boolean;
  warnings_count: number;
  failure: { code: string; message: string } | null;
  /** 기존 PREDICT_VERIFY만 */
  verify: { job_id: string; state: JobState } | null;
}

export interface PredictRunDetail extends PredictRunSummary {
  nearest: { run_key: string; distance: number } | null;
  response_table: { name: string; unit: string | null; predicted: number | null; nearest_measured: number | null; diff_pct: number | null }[];
  /** 폴더·파일이 없으면 그 키 null */
  paths: {
    dir: string | null;
    input_dir: string | null;
    result_dir: string | null;
    pred_h3d: string | null;
    media_dir: string | null;
    geom_dir: string | null;
  };
  display: ContourDisplay | null;
  /** 예측에 실제로 넣은 입력(수치만): 종류·starter·크기·파일 수. 실행 전이면 null */
  predict_input: { input?: PredictInput | null; starter?: string | null; bytes?: number | null; files?: number | null } | null;
  /** 쿠션 입력에서 값이 없는 응답만(INPUT_CUSHION_RESPONSES, 차단 없음) */
  input_warnings: { code: string; message: string }[];
}

export interface PredictRunQuery {
  mode?: PredictRunMode;
  /** 쉼표 구분 job state */
  state?: string;
  limit?: number;
  cursor?: string | null;
}

export const predictRunsApi = {
  list: (studyId: string, q: PredictRunQuery = {}) =>
    requestPage<PredictRunSummary[]>(`/studies/${studyId}/predict-runs`, { mode: q.mode, state: q.state, limit: q.limit, cursor: q.cursor }),
  detail: (jobId: string) => request<PredictRunDetail>("GET", `/predict-runs/${jobId}`),
};
