// phase3 §16 S11 SCX 목(D3-58): GET /jobs/{id}/hpc-jobs(run별 HPC 행 + scx 필드), POST .../hpc-jobs/{hid}/resolve(202, 요청만 기록),
// 다음 tick에 조치 처리(recheck·attach → QUEUED, mark_not_submitted → 행 FAILED·run SOLVE_FAILED). ?hpc=scx[&scx=unknown]로 켠다.
import type { HpcJob, Job } from "../api/types";
import type { MockServer } from "./server";
import type { RunRec } from "./stage1";
import { err, type Route } from "./route";

export const SCX_HOME = "/Users/vd.dashboard";
export const SCX_TS = "20261017T105700";
export const SCX_UNKNOWN_MSG = "SCX 제출 결과를 알 수 없습니다 — SCX에서 확인 필요";

/** 행 부가 정보(RunRec·Job에 붙인다) */
export interface ScxRow {
  id: string;
  version: number;
  remote_dir: string | null;
  request_id: string | null;
  submission_unknown: boolean;
  resolve: { action: string; external_job_id?: string } | null;
  error_message: string | null;
  /** ④ 검증 행 상태(작업이 WAITING_HPC일 때만 쓴다) */
  state?: string;
  external_job_id?: string | null;
}
type Host = { _scx?: ScxRow };

function project(srv: MockServer, studyId: string): string {
  return srv.studies.find((s) => s.id === studyId)?.folder_name ?? "study";
}

/** 행 정보(없으면 만든다) */
export function scxRowFor(srv: MockServer, host: Host, id: string, studyId: string, jobName: string): ScxRow {
  if (!host._scx) {
    const scx = srv.hpcMode === "scx";
    host._scx = {
      id, version: 1, remote_dir: scx ? `${SCX_HOME}/${project(srv, studyId)}/${jobName}` : null, request_id: scx ? `pai-${id}` : null,
      submission_unknown: false, resolve: null, error_message: null,
    };
  }
  return host._scx;
}

/** 결과 모름 행으로 표시(시드·시험용) */
export function markUnknown(srv: MockServer, j: Job, r: RunRec) {
  const row = scxRowFor(srv, r as Host, runRowId(j, r), j.study_id, runJobName(r));
  row.submission_unknown = true;
  row.error_message = SCX_UNKNOWN_MSG;
  r.hpc = { external_job_id: null, state: "UNKNOWN", attempt_no: r.hpc?.attempt_no ?? 1 };
  j.attention_code = "HPC_SUBMISSION_UNKNOWN";
}

const runRowId = (j: Job, r: RunRec) => `hj-${j.id}-${r.run_key}-${r.hpc?.attempt_no ?? 1}`;
const runJobName = (r: RunRec) => `01_D-001_${r.run_key}_${SCX_TS}`;

function collectState(j: Job, r: RunRec): string {
  if (r.state === "COLLECTED") return "COLLECTED";
  if (r.state === "COLLECT_FAILED") return "FAILED";
  if (r.state === "SOLVED") return j.state === "COLLECTING" ? "COLLECTING" : "PENDING";
  return "NONE";
}

function out(srv: MockServer, base: Omit<HpcJob, "gateway_mode" | "remote_dir" | "request_id" | "output_path" | "submission_unknown" | "resolve_pending" | "error_message" | "version">, row: ScxRow): HpcJob {
  return {
    ...base, gateway_mode: srv.hpcMode, remote_dir: row.remote_dir, request_id: row.request_id, output_path: row.remote_dir,
    submission_unknown: row.submission_unknown, resolve_pending: !!row.resolve, error_message: row.error_message, version: row.version,
  };
}

function solveRows(srv: MockServer, j: Job): { row: HpcJob; host: RunRec; scx: ScxRow }[] {
  const runs = (srv.p2.runs[j.params.doe_id as string] ?? []).filter((r) => r._job === j.id && r.hpc);
  return runs.map((r) => {
    const scx = scxRowFor(srv, r as Host, runRowId(j, r), j.study_id, runJobName(r));
    const row = out(srv, { id: scx.id, run_key: r.run_key, attempt_no: r.hpc!.attempt_no, external_job_id: r.hpc!.external_job_id ?? null, state: r.hpc!.state, external_state_raw: null, submitted_at: r.updated_at, elapsed_s: null, collect_state: collectState(j, r) }, scx);
    return { row, host: r, scx };
  });
}

function verifyRow(srv: MockServer, j: Job): { row: HpcJob; scx: ScxRow } | null {
  if (j.state === "QUEUED") return null;
  const scx = scxRowFor(srv, j as Host, `hj-${j.id}`, j.study_id, `04_V-001_${SCX_TS}`);
  const map: Record<string, [string, string]> = { RUNNING: ["RUNNING", "NONE"], COLLECTING: ["SUCCEEDED", "COLLECTING"], SUCCEEDED: ["SUCCEEDED", "COLLECTED"], FAILED: ["FAILED", "NONE"], CANCELED: ["CANCELED", "NONE"], INTERRUPTED: ["FAILED", "NONE"] };
  const [state, collect] = j.state === "WAITING_HPC" ? [scx.state ?? "RUNNING", "NONE"] : map[j.state] ?? ["RUNNING", "NONE"];
  const ext = j.state === "WAITING_HPC" && scx.state === "UNKNOWN" ? null : scx.external_job_id ?? `scx-${j.id}`;
  return { row: out(srv, { id: scx.id, run_key: "verify", attempt_no: 1, external_job_id: ext, state, external_state_raw: null, submitted_at: j.started_at, elapsed_s: null, collect_state: collect }, scx), scx };
}

function rowsFor(srv: MockServer, j: Job) {
  if (j.job_type === "TD_SOLVE") return solveRows(srv, j);
  if (j.job_type === "PREDICT_VERIFY") {
    const v = verifyRow(srv, j);
    return v ? [{ row: v.row, host: null, scx: v.scx }] : [];
  }
  return [];
}

/** §16.5 */
export const scxRoutes: Route = (srv, { method, seg, body, me }) => {
  if (seg[0] !== "jobs" || !seg[1] || seg[2] !== "hpc-jobs") return null;
  const j = srv.jobs.find((x) => x.id === seg[1]);
  if (!j) return err(404, "NOT_FOUND", "작업을 찾을 수 없습니다.");
  if (method === "GET" && !seg[3]) return { status: 200, body: rowsFor(srv, j).map((x) => x.row) };
  if (method === "POST" && seg[3] && seg[4] === "resolve") {
    const own = j.created_by === me.user_id;
    const role = srv.role(j.project_id);
    if (!(me.is_global_admin || (own && (role === "power" || role === "admin")))) return err(403, "PERMISSION_DENIED", "작업 등록자(power 이상) 또는 전역 관리자만 할 수 있습니다.", { required: "owner_power_or_global_admin" });
    const hit = rowsFor(srv, j).find((x) => x.row.id === seg[3]);
    if (!hit) return err(404, "NOT_FOUND", "HPC 행을 찾을 수 없습니다");
    const action = String(body?.action ?? "");
    const ext = body?.external_job_id as string | undefined;
    if (!["recheck", "attach", "mark_not_submitted"].includes(action)) return err(422, "INVALID_PARAMS", "action이 올바르지 않습니다");
    if (action === "attach" && !ext) return err(422, "INVALID_PARAMS", "attach에는 SCX 잡 ID가 필요합니다");
    if (!(hit.row.state === "UNKNOWN" && hit.row.submission_unknown)) return err(409, "HPC_NOT_UNKNOWN", "SCX 제출 결과 모름 상태인 행이 아닙니다");
    if (hit.scx.resolve) return err(409, "HPC_RESOLVE_PENDING", "이미 요청한 조치를 워커가 처리하는 중입니다");
    if (Number(body?.version) !== hit.scx.version) return err(409, "VERSION_CONFLICT", "행이 그 사이 바뀌었습니다. 새로 고친 뒤 다시 시도하세요");
    hit.scx.resolve = { action, ...(ext ? { external_job_id: ext } : {}) };
    hit.scx.version++;
    return { status: 202, body: rowsFor(srv, j).find((x) => x.row.id === seg[3])!.row };
  }
  return null;
};

/** 워커 폴러 흉내: 요청된 조치를 처리 */
export function tickScx(srv: MockServer) {
  for (const j of srv.jobs.filter((x) => x.state === "WAITING_HPC")) {
    let changed = false;
    for (const { host, scx } of rowsFor(srv, j)) {
      const req = scx.resolve;
      if (!req) continue;
      scx.resolve = null;
      scx.version++;
      changed = true;
      if (req.action === "mark_not_submitted") {
        scx.error_message = "제출되지 않음(사용자 확인)";
        if (host) {
          host.hpc = { ...host.hpc!, state: "FAILED" };
          host.state = "SOLVE_FAILED";
          host.updated_at = new Date().toISOString();
        } else {
          scx.state = "FAILED";
          j.state = "FAILED";
          j.failure_code = "HPC_SUBMIT_FAILED";
          j.failure_message = "제출되지 않음(사용자 확인)";
          j.finished_at = new Date().toISOString();
        }
      } else {
        const id = req.external_job_id ?? `scx-${srv.p2.hpcSeq++}`;
        scx.submission_unknown = false;
        scx.error_message = null;
        if (host) host.hpc = { ...host.hpc!, external_job_id: id, state: "QUEUED" };
        else {
          scx.state = "QUEUED";
          scx.external_job_id = id;
        }
      }
    }
    if (changed) {
      if (!rowsFor(srv, j).some((x) => x.row.state === "UNKNOWN" && x.row.submission_unknown) && j.attention_code === "HPC_SUBMISSION_UNKNOWN") j.attention_code = null;
      srv.bump(j);
    }
  }
}
