// 계약 §10을 흉내 내는 메모리 목 서버. fetch를 가로채 /physicsai/api/* 에 응답한다.
// F5: 1차 공유 상태·알림·라우터 등록(ROUTES, 한 곳)만 여기 두고, 경로 처리는 단계별 라우트 모듈(ops·stage1~5·studies·jobs·manage)에 있다.
import type { Artifact, Dataset, FeatureKey, Job, JobType, Me, Model, NotificationItem, ParamSet, SampleRow, Study } from "../api/types";
import {
  COMMANDS_TXT,
  USERS,
  baseJob,
  iso,
  makeSamples,
  makeSteps,
  seedDatasets,
  seedModels,
  seedNotifications,
  seedMeshOnlyParamSet,
  seedParamSet,
  seedStudies,
  STEP_LABEL,
  type MockUserKey,
} from "./data";
import { Phase2Mock } from "./phase2";
import { ManageMock } from "./manage";
import { JOB_TYPE_LABEL } from "../lib/format";
import { err, type MockResp, type Route, type RouteCtx } from "./route";
import { tickJobs } from "./engine";
import { createJobFor, jobRoutes } from "./jobs";
import { envCheckRoutes, notificationRoutes, opsRoutes } from "./ops";
import { fsRoutes } from "./fs";
import { trainRoutes } from "./stage1";
import { curationRoutes } from "./stage2";
import { datasetModelRoutes } from "./stage3";
import { paramSetRoutes, predictResult } from "./stage4";
import { preparedRoutes } from "./stage4Prepared";
import { optimizeRoutes } from "./stage5";
import { isBatchChild, predictBatchRoutes, seedBatches, type BatchRec } from "./predictBatch";
import { studyRoutes } from "./studies";

export type { MockResp } from "./route";

type Notif = NotificationItem & { user_id: string };
interface ArtifactRec extends Artifact {
  body: string;
}

export interface MockOptions {
  user?: MockUserKey;
  hpcConfigured?: boolean;
  /** 실행 중 작업이 tick마다 진행되는 정도(%) */
  speed?: number;
  /** /status.ui 값(B1). 시험에서 짧은 주기를 주입 */
  ui?: Record<string, number>;
  /** 2차: 비활성 기능(/status.features enabled=false). 기본 ["train_resp"](response_extract 템플릿 null) */
  disabledFeatures?: FeatureKey[];
  /** C18: PBS 취소 명령 실패 흉내 */
  hpcCancelFails?: boolean;
  /** /status.demo(시연 모드) */
  demo?: boolean;
  /** /status.config.warnings */
  configWarnings?: string[];
  /** /status.auth.login_url(auth.dashboard_public_login_url, 운영 대시보드 기본 "/home/" — phase3 D3-38) */
  loginUrl?: string;
  /** S9: "running"이면 진행 중 일괄 예측 B-003 시드(하위 PREDICT 12개가 대기열에 들어간다) */
  batchDemo?: "running";
}

export const MOCK_AI_ROOT = "E:\\shared\\AI_WORK";
export const DEFAULT_UI = {
  max_artifact_bytes: 20971520,
  poll_job_running_ms: 2000,
  poll_job_queued_ms: 5000,
  poll_job_waiting_hpc_ms: 15000,
  poll_log_ms: 2000,
  poll_queue_ms: 5000,
  poll_resources_ms: 10000,
  poll_notifications_ms: 10000,
  poll_status_ms: 30000,
};

const JOB_LABEL = JOB_TYPE_LABEL;

/** 라우터 등록(한 곳). 순서가 곧 우선순위 — 원래 handle의 if 순서 그대로 */
const ROUTES: Route[] = [
  opsRoutes, // §10.2 me·프로젝트·상태·대기열·자원
  (srv, c) => srv.manage.handle(c.method, c.seg, c.body, c.me), // 3차(phase3.md §3): Study 관리·재시도·용량
  envCheckRoutes, // 2차(phase2.md §12): 환경 점검
  trainRoutes, // ①
  curationRoutes, // ②
  optimizeRoutes, // ⑤
  preparedRoutes, // S6 ④ 준비된 입력 inspect(PREDICT_INPUT)
  predictBatchRoutes, // S9 ④ 일괄 예측·템플릿 응답(phase3.md §14.7)
  studyRoutes, // §10.3 Study(③·④ 하위 경로 포함)
  datasetModelRoutes, // §10.4 ③
  paramSetRoutes, // §10.4 ④
  jobRoutes, // §10.5
  notificationRoutes, // §10.7
  fsRoutes, // phase3 §12 S7 서버 경로 탐색
];

export class MockServer {
  user: MockUserKey;
  hpcConfigured: boolean;
  hpcCancelFails: boolean;
  demo: boolean;
  configWarnings: string[];
  loginUrl: string;
  ui: Record<string, number>;
  speed: number;
  studies: Study[] = seedStudies();
  datasets: Dataset[] = seedDatasets();
  models: Model[] = seedModels();
  paramSets: ParamSet[] = [seedParamSet(), seedMeshOnlyParamSet()];
  batches: BatchRec[] = [];
  samples: Record<string, SampleRow[]> = { "ps-1": makeSamples(120) };
  jobs: Job[] = [];
  artifacts: ArtifactRec[] = [];
  notifs: Notif[] = seedNotifications() as Notif[];
  seq = 0;
  queueSeq = 100;
  queueOrder = new Map<string, number>();
  idn = 1000;
  p2: Phase2Mock;
  manage: ManageMock;

  constructor(opts: MockOptions = {}) {
    this.user = opts.user ?? "admin";
    this.hpcConfigured = opts.hpcConfigured ?? false;
    this.hpcCancelFails = opts.hpcCancelFails ?? false;
    this.demo = opts.demo ?? false;
    this.configWarnings = opts.configWarnings ?? [];
    this.loginUrl = opts.loginUrl ?? "/";
    this.speed = opts.speed ?? 9;
    this.ui = { ...DEFAULT_UI, ...(opts.ui ?? {}) };
    this.seq = Math.max(...this.notifs.map((n) => n.seq));
    this.seedJobs();
    this.p2 = new Phase2Mock(this, opts.disabledFeatures);
    this.manage = new ManageMock(this);
    seedBatches(this, opts.batchDemo);
  }

  get me(): Me | null {
    return this.user === "anon" ? null : USERS[this.user];
  }

  nid(prefix: string) {
    return `${prefix}-${++this.idn}`;
  }

  private seedJobs() {
    const st = "쿠션 두께·리브 예측";
    const pred = baseJob({
      id: "j-pred", study_id: "s-cushion", project_id: "p-cushion", study_title: st, job_type: "PREDICT", state: "SUCCEEDED",
      created_at: iso(34), started_at: iso(33), finished_at: iso(30), steps: makeSteps("PREDICT", 10, null), progress_pct: 100,
      params: { param_set_id: "ps-1", model_id: null, values: { THK_TOP: 0.55, THK_FOAM: 2.2, E_FOAM: 9.5, RIB_N: 5 }, value_source: "manual", source_run_key: null },
    });
    pred.result = predictResult(this, pred, pred.params.values as Record<string, number>, "m-1", "ps-1");
    this.jobs.push(
      baseJob({ id: "j-ds1", study_id: "s-cushion", project_id: "p-cushion", study_title: st, job_type: "DATASET_CREATE", state: "FAILED", created_at: iso(60 * 30), finished_at: iso(60 * 30 - 4), steps: makeSteps("DATASET_CREATE", 2, null, { failedIdx: 2 }), failure_code: "EXIT_NONZERO", failure_message: "EDSPY_DATASET_TRAIN 종료코드 1", params: { input_path: "E:/shared/AI_WORK/cushion_v1/00_inbox/h3d" } }),
      baseJob({ id: "j-ds2", study_id: "s-cushion", project_id: "p-cushion", study_title: st, job_type: "DATASET_CREATE", state: "SUCCEEDED", created_at: iso(60 * 26 + 30), finished_at: iso(60 * 26), steps: makeSteps("DATASET_CREATE", 5, null), progress_pct: 100, params: { input_path: "E:/shared/AI_WORK/cushion_v1/00_inbox/h3d_r2" }, result: { dataset_id: "ds-2", h3d_count: 240, train_count: 216, eval_count: 24 } }),
      baseJob({ id: "j-pkg", study_id: "s-cushion", project_id: "p-cushion", study_title: st, job_type: "PACKAGE_EXPORT", state: "SUCCEEDED", created_at: iso(60 * 25 + 5), finished_at: iso(60 * 25), steps: makeSteps("PACKAGE_EXPORT", 2, null), progress_pct: 100, params: { dataset_id: "ds-2" } }),
      baseJob({ id: "j-mr", study_id: "s-cushion", project_id: "p-cushion", study_title: st, job_type: "MODEL_REGISTER", state: "SUCCEEDED", created_at: iso(52), finished_at: iso(50), steps: makeSteps("MODEL_REGISTER", 4, null), progress_pct: 100, params: { model_path: "E:/shared/AI_WORK/cushion_v1/00_inbox/model_gnn" }, result: { model_id: "m-3" } }),
      pred,
      baseJob({ id: "j-run", study_id: "s-hinge", project_id: "p-hinge", study_title: "힌지 반복 굽힘", job_type: "DATASET_CREATE", state: "RUNNING", lane: "SLOT", created_by: "u-other", created_by_name: "최해석", created_at: iso(30), started_at: iso(24), progress_pct: 62, progress_label: "Extracting results 148/240", steps: makeSteps("DATASET_CREATE", 2, 2) }),
      baseJob({ id: "j-q1", study_id: "s-cushion", project_id: "p-cushion", study_title: st, job_type: "EVALUATE", state: "QUEUED", created_at: iso(12), params: { model_id: "m-2" } }),
      baseJob({ id: "j-q2", study_id: "s-hinge", project_id: "p-hinge", study_title: "힌지 반복 굽힘", job_type: "PREDICT", state: "QUEUED", created_by: "u-other", created_by_name: "최해석", created_at: iso(6) }),
    );
    (this.jobs.find((j) => j.id === "j-run") as Job & { _speed?: number })._speed = 1;
    this.queueOrder.set("j-q1", ++this.queueSeq);
    this.queueOrder.set("j-q2", ++this.queueSeq);
    this.addArtifact("j-pkg", "s-cushion", "PACKAGE_COMMANDS", "03_package/ds-2/COMMANDS.txt", "text/plain", COMMANDS_TXT);
    this.models.find((m) => m.id === "m-2")!.eval_status = "DONE";
  }

  addArtifact(jobId: string, studyId: string, kind: Artifact["kind"], rel: string, ct: string, body: string): string {
    const id = this.nid("a");
    this.artifacts.push({ id, study_id: studyId, job_id: jobId, kind, file_name: rel.split("/").pop()!, size: body.length, sha256: null, content_type: ct, created_at: new Date().toISOString(), body });
    return id;
  }

  // ---------- 알림 ----------
  notify(userId: string, event: NotificationItem["event"], job: Job | null, title: string, body = "") {
    this.notifs.push({
      seq: ++this.seq, user_id: userId, event, job_id: job?.id ?? null, study_id: job?.study_id ?? null, project_id: job?.project_id ?? null,
      title, body, created_at: new Date().toISOString(), read_at: null,
    });
  }

  notifyJob(job: Job, event: NotificationItem["event"]) {
    // S9 §14.5: 일괄 예측 하위 PREDICT는 시작·완료·실패·차례 알림 억제, 부모는 성공 알림 없음(완료 알림은 배치 1건)
    if (isBatchChild(job) && ["JOB_STARTED", "JOB_SUCCEEDED", "JOB_FAILED", "MY_TURN_NEXT"].includes(event)) return;
    if (job.job_type === "PREDICT_BATCH" && event === "JOB_SUCCEEDED") return;
    const t = `${JOB_LABEL[job.job_type]} (${job.study_title})`;
    const title =
      event === "JOB_STARTED" ? `실행 시작: ${t}` :
      event === "JOB_SUCCEEDED" ? `완료: ${t}` :
      event === "JOB_FAILED" ? `실패: ${t} — ${job.failure_code}` :
      event === "JOB_CANCELED" ? "관리자가 작업을 취소했습니다" :
      event === "MY_TURN_NEXT" ? `다음 차례입니다: ${t}` : t;
    this.notify(job.created_by, event, job, title, event === "JOB_CANCELED" ? t : "");
  }

  bump(j: Job) {
    j.version++;
  }

  /** 시간 1단계 진행: claim → 진행 → 완료 */
  tick() {
    tickJobs(this);
  }

  /** 시험·데모용: 실행 중 작업을 바로 끝낸다 */
  finishAll() {
    for (let i = 0; i < 40 && this.jobs.some((j) => j.state === "RUNNING" || j.state === "QUEUED"); i++) {
      for (const j of this.jobs) if (j.state === "RUNNING") (j as Job & { _pct?: number })._pct = 100;
      this.tick();
    }
  }

  stepLabel(key: string): string {
    return STEP_LABEL[key] ?? key;
  }

  role(projectId: string) {
    const me = this.me!;
    if (me.is_global_admin) return "admin";
    return me.roles[projectId] ?? null;
  }

  disp(studyId: string, rel: string): string {
    const st = this.studies.find((x) => x.id === studyId);
    return [MOCK_AI_ROOT, st?.folder_name ?? studyId, ...rel.split("/").filter(Boolean)].join("\\");
  }

  studyOut(s: Study): Study {
    const r = this.role(s.project_id);
    return { ...s, can_execute: r === "power" || r === "admin", folder_display_path: this.disp(s.id, "") };
  }

  // ---------- 라우팅 ----------
  handle(method: string, path: string, query: URLSearchParams, body: Record<string, unknown> | null, headers: Headers): MockResp {
    if (path === "/health") return { status: 200, body: { status: "ok", version: "mock" } };
    const me = this.me;
    if (!me) return err(401, "AUTHENTICATION_REQUIRED", "로그인이 필요합니다.");
    if (method !== "GET" && headers.get("X-PhysicsAI-Request") !== "1") return err(403, "CSRF_HEADER_REQUIRED", "요청 헤더가 없습니다.");
    const seg = path.split("/").filter(Boolean);
    const c: RouteCtx = { method, path, seg, query, body, headers, me };
    for (const route of ROUTES) {
      const r = route(this, c);
      if (r) return r;
    }
    return err(404, "NOT_FOUND", `목 서버에 없는 경로: ${method} ${path}`);
  }

  createJob(s: Study, type: JobType, params: Record<string, unknown>): MockResp {
    return createJobFor(this, s, type, params);
  }
}

/** fetch 대체 함수 생성 */
export function createMockFetch(server: MockServer, realFetch?: typeof fetch): typeof fetch {
  return async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(typeof input === "string" ? input : input instanceof URL ? input.href : input.url, "http://mock.local");
    const prefix = "/physicsai/api";
    if (!url.pathname.startsWith(prefix)) {
      if (realFetch) return realFetch(input, init);
      return new Response("not found", { status: 404 });
    }
    const method = (init?.method ?? "GET").toUpperCase();
    const headers = new Headers(init?.headers);
    let body: Record<string, unknown> | null = null;
    if (typeof init?.body === "string") body = JSON.parse(init.body);
    const r = server.handle(method, url.pathname.slice(prefix.length) || "/", url.searchParams, body, headers);
    const h = new Headers(r.headers);
    if (r.status === 304) return new Response(null, { status: 304, headers: h });
    if (r.text !== undefined) {
      h.set("Content-Type", r.contentType ?? "text/plain");
      return new Response(r.text, { status: r.status, headers: h });
    }
    h.set("Content-Type", "application/json");
    return new Response(JSON.stringify(r.body ?? null), { status: r.status, headers: h });
  };
}
