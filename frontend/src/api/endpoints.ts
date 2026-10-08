// 계약 §10 엔드포인트 함수. 화면 코드는 fetch를 직접 쓰지 않고 이 객체만 쓴다.
import { fetchBlob, request } from "./client";
import type {
  Artifact,
  Dataset,
  Job,
  JobSummary,
  JobType,
  LogChunk,
  Me,
  Model,
  NotificationList,
  ParamSet,
  PathInspectResult,
  PathPurpose,
  PredictCheck,
  Project,
  QueueInfo,
  Resources,
  SamplePage,
  StatusInfo,
  Study,
  StudyDetail,
} from "./types";

export const api = {
  // §10.2 셸·상태
  me: () => request<Me>("GET", "/me"),
  projects: () => request<Project[]>("GET", "/projects"),
  status: () => request<StatusInfo>("GET", "/status"),
  queue: () => request<QueueInfo>("GET", "/queue"),
  moveQueue: (jobId: string, position: number) =>
    request<QueueInfo>("POST", `/queue/${jobId}/move`, { body: { position } }),
  resources: () => request<Resources>("GET", "/resources"),

  // §10.3 Study·경로
  studies: (projectId: string, status?: string) =>
    request<Study[]>("GET", "/studies", { query: { project_id: projectId, status } }),
  createStudy: (body: { project_id: string; folder_name: string; title: string }) =>
    request<Study>("POST", "/studies", { body }),
  study: (id: string) => request<StudyDetail>("GET", `/studies/${id}`),
  inspectPath: (studyId: string, purpose: PathPurpose, path: string) =>
    request<PathInspectResult>("POST", `/studies/${studyId}/paths/inspect`, { body: { purpose, path } }),

  // §10.4 데이터셋·모델·파라미터 세트
  datasets: (studyId: string) => request<Dataset[]>("GET", `/studies/${studyId}/datasets`),
  models: (studyId: string, status?: string) =>
    request<Model[]>("GET", `/studies/${studyId}/models`, { query: { status } }),
  model: (id: string) => request<Model>("GET", `/models/${id}`),
  setFinalModel: (studyId: string, modelId: string | null) =>
    request<Study>("PUT", `/studies/${studyId}/final-model`, { body: { model_id: modelId } }),
  registerParamSet: (studyId: string, path: string) =>
    request<ParamSet>("POST", `/studies/${studyId}/param-sets`, { body: { path } }),
  paramSets: (studyId: string) => request<ParamSet[]>("GET", `/studies/${studyId}/param-sets`),
  paramSet: (id: string) => request<ParamSet>("GET", `/param-sets/${id}`),
  samples: (id: string, limit = 200, cursor?: string | null) =>
    request<SamplePage>("GET", `/param-sets/${id}/samples`, { query: { limit, cursor } }),
  predictCheck: (studyId: string, body: { param_set_id?: string | null; values: Record<string, number> }) =>
    request<PredictCheck>("POST", `/studies/${studyId}/predict/check`, { body }),

  // §10.5 작업·로그·산출물
  createJob: (studyId: string, job_type: JobType, params: Record<string, unknown>) =>
    request<Job>("POST", `/studies/${studyId}/jobs`, { body: { job_type, params } }),
  jobs: (q: { study_id?: string; state?: string; mine?: boolean; job_type?: JobType; limit?: number }) =>
    request<JobSummary[]>("GET", "/jobs", { query: q }),
  job: (id: string) => request<Job>("GET", `/jobs/${id}`, { etag: true }),
  jobLog: (id: string, cursor = 0, limit = 65536) =>
    request<LogChunk>("GET", `/jobs/${id}/log`, { query: { cursor, limit } }),
  cancelJob: (id: string) => request<Job>("POST", `/jobs/${id}/cancel`),
  retryJob: (id: string, from_step?: number) =>
    request<Job>("POST", `/jobs/${id}/retry`, { body: from_step ? { from_step } : {} }),
  artifacts: (jobId: string) => request<Artifact[]>("GET", `/jobs/${jobId}/artifacts`),
  artifactBlob: (id: string) => fetchBlob(`/artifacts/${id}/content`),
  /** B16: ④ 입력파일 zip (409 INPUT_NOT_READY) */
  inputZip: (jobId: string) => fetchBlob(`/jobs/${jobId}/artifacts/input.zip`),

  // §10.7 알림
  notifications: (afterSeq?: number, limit = 50) =>
    request<NotificationList>("GET", "/notifications", { query: { after_seq: afterSeq, limit } }),
  unreadCount: () => request<{ unread_count: number; max_seq: number }>("GET", "/notifications/unread-count"),
  markRead: (body: { seqs: number[] } | { all: true }) =>
    request<{ unread_count: number }>("POST", "/notifications/read", { body }),
};

export type Api = typeof api;
