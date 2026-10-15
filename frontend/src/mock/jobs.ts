// §10.5 작업 목: 요약·상세 변환, 작업 생성(사전 검사·데이터셋 행), 로그, 작업·산출물 라우트.
import type { Dataset, Job, JobSummary, JobType, Study } from "../api/types";
import { SKIPPED_BY_DEFAULT, STEP_CHAINS, baseJob } from "./data";
import { err, needAdmin, type MockResp, type Route } from "./route";
import type { MockServer } from "./server";
import { refreshPositions } from "./engine";
import { predictParams } from "./stage4Prepared";

export function summary(srv: MockServer, j: Job): JobSummary {
  const { id, study_id, project_id, study_title, job_type, stage, lane, state, created_by, created_by_name, queue_position, progress_pct, progress_label, cancel_requested, created_at, started_at } = j;
  return { id, study_id, project_id, study_title, job_type, stage, lane, state, created_by, created_by_name, queue_position, progress_pct, progress_label, cancel_requested, created_at, started_at, ...srv.p2.summaryExtra(j) };
}

export function inputReady(j: Job): boolean {
  return j.job_type === "PREDICT" && j.steps.some((x) => x.step_key === "RAD_ASSEMBLE" && (x.state === "SUCCEEDED" || x.state === "SKIPPED"));
}

function jobOut(srv: MockServer, j: Job): Job {
  const me = srv.me;
  const failedish = ["FAILED", "CANCELED", "INTERRUPTED"].includes(j.state) || !!j.attention_code;
  return {
    ...j,
    ...srv.p2.summaryExtra(j),
    attention_code: j.attention_code ?? null,
    input_display_path: inputReady(j) ? srv.disp(j.study_id, `04_predict/${j.id}/INPUT`) : null,
    can_download_error_bundle: !!me && failedish && (me.is_global_admin || j.created_by === me.user_id),
  };
}

export function createJobFor(srv: MockServer, s: Study, type: JobType, params: Record<string, unknown>): MockResp {
  if (s.status !== "ACTIVE") return err(409, "STUDY_ARCHIVED", "보관된 Study입니다.");
  if (!STEP_CHAINS[type]) return err(422, "INVALID_PARAMS", "알 수 없는 작업 유형입니다.");
  if (srv.jobs.some((j) => j.study_id === s.id && j.job_type === type && !["SUCCEEDED", "FAILED", "CANCELED", "INTERRUPTED"].includes(j.state)))
    return err(409, "STUDY_JOB_BUSY", "같은 종류의 작업이 이미 실행 중이거나 대기 중입니다.");
  if (type === "PREDICT") {
    const r = predictParams(srv, s, params); // S6 §11.5: input_mode별 검증(422 INVALID_PARAMS·PREDICT_INPUT_INVALID, 409)
    if ("error" in r) return r.error;
    params = r.params;
  }
  if (type === "PREDICT" && !params.model_id && !s.final_model_id) return err(409, "FINAL_MODEL_REQUIRED", "Final 모델을 먼저 지정하세요.");
  if (type === "PREDICT_VERIFY" && !srv.hpcConfigured) return err(409, "HPC_NOT_CONFIGURED", "PBS 연결이 설정되지 않았습니다.");
  const pre = srv.p2.precheck(s, type, params);
  if (pre) return pre;
  if (type === "DATASET_CREATE" && params.curation_id && params.input_path) return err(422, "INVALID_PARAMS", "curation_id와 input_path는 함께 쓸 수 없습니다.");
  if (type === "PACKAGE_EXPORT" && !srv.datasets.some((d) => d.id === params.dataset_id && d.status === "READY"))
    return err(409, "PREREQUISITE_MISSING", "준비된 데이터셋이 필요합니다.", { missing: ["dataset"] });
  const me = srv.me!;
  const j = baseJob({
    id: srv.nid("j"), study_id: s.id, project_id: s.project_id, study_title: s.title, job_type: type, state: "QUEUED",
    created_by: me.user_id, created_by_name: me.display_name, created_at: new Date().toISOString(), params,
  });
  srv.jobs.push(j);
  srv.queueOrder.set(j.id, ++srv.queueSeq);
  srv.p2.onCreate(j, me);
  if (type === "DATASET_CREATE") {
    const cur = srv.p2.curations.find((c) => c.id === params.curation_id);
    srv.datasets.unshift({
      id: srv.nid("ds"), study_id: s.id, job_id: j.id, status: "BUILDING", source_path: cur ? cur.output_display_path ?? "" : String(params.input_path), curation_id: cur?.id ?? null, h3d_count: null, train_count: null, eval_count: null,
      holdout_ratio: 0.1, seed: Number(params.seed ?? 20261008), split_group: (params.split_group as "file") ?? "file",
      options: (params.options as Dataset["options"]) ?? { extract_faces: true, extract_mdi: false, extract_time_history_vectors: false },
      package_ready: false, created_by_name: me.display_name, created_at: j.created_at,
    });
  }
  refreshPositions(srv);
  return { status: 201, body: j };
}

function jobLog(j: Job, cursor: number) {
  const lines = j.steps
    .filter((s) => s.state !== "PENDING")
    .map((s) => `[${s.step_no.toString().padStart(2, "0")} ${s.step_key}] ${s.state}${SKIPPED_BY_DEFAULT.has(s.step_key) && s.state === "SKIPPED" ? " (템플릿 미구성)" : ""}`);
  const text = lines.join("\n") + (lines.length ? "\n" : "");
  const slice = text.slice(cursor);
  return { text: slice, next_cursor: text.length, eof: true, size: text.length };
}

/** §10.5 작업 목록·상세·오류 묶음·로그·산출물·취소, 산출물 본문 */
export const jobRoutes: Route = (srv, { method, path, seg, query, headers, me }) => {
  if (method === "GET" && path === "/jobs") {
    let list = [...srv.jobs];
    const sid = query.get("study_id");
    const jt = query.get("job_type");
    const st = query.get("state");
    if (sid) list = list.filter((j) => j.study_id === sid);
    if (jt) list = list.filter((j) => j.job_type === jt);
    if (st) list = list.filter((j) => j.state === st);
    if (query.get("mine") === "true") list = list.filter((j) => j.created_by === me.user_id);
    list.sort((a, b) => b.created_at.localeCompare(a.created_at));
    return { status: 200, body: list.slice(0, Number(query.get("limit") ?? 50)).map((j) => summary(srv, j)) };
  }
  if (seg[0] === "jobs" && seg[1]) {
    const j = srv.jobs.find((x) => x.id === seg[1]);
    if (!j) return err(404, "NOT_FOUND", "작업을 찾을 수 없습니다.");
    if (method === "GET" && !seg[2]) {
      const etag = `"${j.id}:${j.version}:0"`;
      if (headers.get("If-None-Match") === etag) return { status: 304, headers: { ETag: etag } };
      const own = j.created_by === me.user_id;
      return {
        status: 200,
        headers: { ETag: etag },
        body: { ...jobOut(srv, j), can_cancel: me.is_global_admin && !["SUCCEEDED", "FAILED", "CANCELED", "INTERRUPTED"].includes(j.state), can_retry: ((own && ["power", "admin"].includes(srv.role(j.project_id) ?? "")) || me.is_global_admin) && ["FAILED", "CANCELED", "INTERRUPTED"].includes(j.state) && !j.job_type.startsWith("STUDY_") },
      };
    }
    if (method === "GET" && seg[2] === "error-bundle.zip") {
      if (!(me.is_global_admin || j.created_by === me.user_id)) return err(403, "PERMISSION_DENIED", "작업 등록자 또는 전역 관리자만 받을 수 있습니다.", { required: "owner_or_global_admin" });
      if (!(["FAILED", "CANCELED", "INTERRUPTED"].includes(j.state) || j.attention_code)) return err(409, "ERROR_BUNDLE_NOT_AVAILABLE", "실패·중단된 작업만 오류 묶음을 받을 수 있습니다.");
      return { status: 200, text: "PK\u0003\u0004 (mock error bundle)", contentType: "application/zip" };
    }
    if (method === "GET" && seg[2] === "log") return { status: 200, body: jobLog(j, Number(query.get("cursor") ?? 0)) };
    if (method === "GET" && seg[2] === "artifacts" && seg[3] === "input.zip") {
      if (!inputReady(j)) return err(409, "INPUT_NOT_READY", "입력파일이 아직 준비되지 않았습니다.");
      return { status: 200, text: "PK\u0003\u0004 (mock zip)", contentType: "application/zip" };
    }
    if (method === "GET" && seg[2] === "artifacts") return { status: 200, body: srv.artifacts.filter((a) => a.job_id === j.id).map(({ body: _b, ...a }) => a) };
    if (method === "POST" && seg[2] === "cancel") {
      const d = needAdmin(me);
      if (d) return d;
      if (["SUCCEEDED", "FAILED", "CANCELED", "INTERRUPTED"].includes(j.state)) return err(409, "JOB_TERMINAL", "이미 끝난 작업입니다.");
      if (j.state === "QUEUED") {
        j.state = "CANCELED";
        j.finished_at = new Date().toISOString();
        srv.queueOrder.delete(j.id);
        srv.notifyJob(j, "JOB_CANCELED");
      } else j.cancel_requested = true;
      srv.bump(j);
      refreshPositions(srv);
      return { status: 202, body: j };
    }
  }
  if (method === "GET" && seg[0] === "artifacts" && seg[2] === "content") {
    const a = srv.artifacts.find((x) => x.id === seg[1]);
    return a ? { status: 200, text: a.body, contentType: a.content_type } : err(404, "NOT_FOUND", "산출물을 찾을 수 없습니다.");
  }
  return null;
};
