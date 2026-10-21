// upload-report.md §4 업로드 세션·§9.4 보고서 목: GET /uploads/config, POST/GET /studies/{id}/uploads, /uploads/{id}(GET·DELETE)·files(POST·PUT)·complete, GET /reports/*.
// 청크 본문은 저장하지 않고 크기만 센다(offset 순서·received 규칙은 서버와 같다). 시험은 uploadFaults 로 다음 PUT 응답을 바꾼다(409 OFFSET_MISMATCH·5xx 등).
import { inspectPath } from "./studies";
import { MOCK_AI_ROOT } from "./serverOptions";
import { err, needPower, ok, type MockResp, type Route } from "./route";
import type { MockServer } from "./server";

export const MOCK_CHUNK = 16 * 1024 ** 2;

export interface UpFile {
  index: number;
  rel: string;
  size: number;
  received: number;
  done: boolean;
  sha256: string | null;
  sha256_expected: string | null;
}
export interface UpRec {
  upload_id: string;
  study_id: string;
  purpose: string;
  engine: string | null;
  name: string;
  state: "OPEN" | "COMPLETED" | "CANCELED" | "STALE";
  dir: string;
  files: UpFile[];
  created_at: string;
}

export interface UploadMockState {
  enabled: boolean;
  items: UpRec[];
  /** 다음 PUT 청크 요청에 차례로 돌려줄 응답(비면 정상) */
  faults: MockResp[];
  /** 받은 청크 기록(순서·sha 헤더 시험용) */
  chunks: { id: string; index: number; offset: number; size: number; sha: string | null }[];
  /** 마지막 complete 에서 inspect 가 실패하는 purpose 시험용: 다음 complete 1회를 ok=false 로 */
  failNextComplete: boolean;
  chunkSize: number;
  reports: { path: string; query: string }[];
  /** 보고서 409 REPORT_NOT_READY 흉내 */
  reportNotReady: boolean;
}

export const newUploadState = (enabled: boolean): UploadMockState => ({ enabled, items: [], faults: [], chunks: [], failNextComplete: false, chunkSize: MOCK_CHUNK, reports: [], reportNotReady: false });

const CAD = { native: ["*.stp", "*.step"], altair: ["*.prt"] };
const RAD = ["*.rad", "*.inc", "*.k", "*.key", "*.csv", "*.txt", "*.json", "*.dat"];
const COMMON = ["*.csv", "*.json", "*.txt"];
const PARAM_SET = ["*.tpl", "*.prt", "*.stp", "*.step", ...COMMON, "*.rad", "*.inc", "*.k", "*.hm", "*.tcl"];
const PURPOSES: Record<string, { patterns: string[]; mode: "file" | "dir" | "dir_or_file"; engine_patterns?: Record<string, string[]> }> = {
  CAD_FILE: { patterns: CAD.altair, mode: "file", engine_patterns: CAD },
  RADIOSS_ASSEM: { patterns: RAD, mode: "dir" },
  RESULT_FOLDER: { patterns: ["*.h3d", "*t01", "*_0000.out", "*_0001.out", ...COMMON], mode: "dir" },
  CURATION_INPUT: { patterns: ["*.h3d", "*t01", ...COMMON], mode: "dir" },
  DATASET_INPUT: { patterns: ["*.h3d", ...COMMON], mode: "dir" },
  MODEL_FOLDER: { patterns: ["*.psmdl", "*.log", "*.txt", "*.json", "*.csv"], mode: "dir" },
  PARAM_SET: { patterns: PARAM_SET, mode: "dir" },
  PREDICT_INPUT: { patterns: ["*.rad", "*.inc", "*.hm", "*.k", ...COMMON], mode: "dir_or_file" },
  DISCOVER: { patterns: [...PARAM_SET, ...RAD], mode: "dir" },
  FEM_ASSEMBLY: { patterns: RAD, mode: "dir" },
};
export const MOCK_DENIED = ["*.pscfg", "*.psdata", "*.exe", "*.dll", "*.pyd", "*.so", "*.bat", "*.cmd", "*.ps1", "*.vbs", "*.js", "*.py", "*.lnk", "*.scr", "*.msi", "*.part"];

const total = (u: UpRec) => u.files.reduce((s, f) => s + f.size, 0);
const out = (srv: MockServer, u: UpRec) => {
  const dir = u.dir;
  return {
    upload_id: u.upload_id, study_id: u.study_id, purpose: u.purpose, engine: u.engine, name: u.name, state: u.state, path: dir, display_path: dir,
    chunk_size: srv.up.chunkSize, total_bytes: total(u), received_bytes: u.files.reduce((s, f) => s + f.received, 0), files: u.files, inspect: null,
    backup_display_path: u.state === "CANCELED" ? `${MOCK_AI_ROOT}\\uploads\\_backup\\mock\\${u.name}` : null, created_by: "mock", created_at: u.created_at, updated_at: u.created_at, completed_at: null,
  };
};
const pad = (n: number) => String(n).padStart(2, "0");

export const uploadRoutes: Route = (srv, { method, path, seg, query, body, me, raw, headers }) => {
  if (seg[0] !== "uploads" && !(seg[0] === "studies" && seg[2] === "uploads")) return null;
  const up = srv.up;
  if (method === "GET" && path === "/uploads/config")
    return ok({ enabled: up.enabled, chunk_size: up.chunkSize, max_file_bytes: 64 * 1024 ** 3, max_upload_bytes: 200 * 1024 ** 3, max_files: 20000, max_concurrent_per_user: 2, purposes: PURPOSES, always_denied: MOCK_DENIED, free_bytes: 900 * 1024 ** 3 });
  if (!up.enabled) return err(503, "UPLOAD_DISABLED", "업로드가 꺼져 있습니다.");
  if (seg[0] === "studies") {
    const st = srv.studies.find((s) => s.id === seg[1]);
    if (!st) return err(404, "STUDY_NOT_FOUND", "Study를 찾을 수 없습니다.");
    if (method === "GET") return ok(up.items.filter((u) => u.study_id === st.id).map((u) => out(srv, u)));
    if (method !== "POST") return null;
    const denied = needPower(srv, st.project_id);
    if (denied) return denied;
    const purpose = String(body?.purpose ?? "");
    const info = PURPOSES[purpose];
    if (!info || purpose === "FEM_ASSEMBLY") return err(422, "UPLOAD_PURPOSE_INVALID", `업로드할 수 없는 용도입니다: ${purpose}`);
    const files = (body?.files as { rel: string; size: number; sha256?: string | null }[] | undefined) ?? [];
    if (!files.length) return err(422, "UPLOAD_NAME_INVALID", "파일이 없습니다.");
    if (info.mode === "file" && (files.length !== 1 || files[0].rel.includes("/"))) return err(422, "UPLOAD_SHAPE_INVALID", "이 용도는 파일 1개만 올릴 수 있습니다(폴더·여러 파일 불가)");
    const bad = files.find((f) => /[\s&|<>^%!"';,=()]/.test(f.rel) || f.rel.split("/").includes(".."));
    if (bad) return err(422, "UPLOAD_NAME_INVALID", `이름에 쓸 수 없는 문자가 있습니다: ${bad.rel}`, { rel: bad.rel });
    const d = new Date();
    const stamp = `${d.getUTCFullYear()}${pad(d.getUTCMonth() + 1)}${pad(d.getUTCDate())}-${pad(d.getUTCHours())}${pad(d.getUTCMinutes())}${pad(d.getUTCSeconds())}`;
    const name = String(body?.name ?? "upload");
    const dir = `${MOCK_AI_ROOT}\\uploads\\${me.user_id}\\${stamp}_${name}`;
    const rec: UpRec = {
      upload_id: srv.nid("up"), study_id: st.id, purpose, engine: (body?.engine as string | null | undefined) ?? null, name, state: "OPEN", dir,
      files: files.map((f, i) => ({ index: i, rel: f.rel, size: f.size, received: 0, done: false, sha256: null, sha256_expected: f.sha256 ?? null })), created_at: d.toISOString(),
    };
    up.items.unshift(rec);
    return ok(out(srv, rec), 201);
  }
  const rec = up.items.find((u) => u.upload_id === seg[1]);
  if (!rec) return err(404, "UPLOAD_NOT_FOUND", "업로드 세션을 찾을 수 없습니다.");
  if (seg.length === 2) {
    if (method === "GET") return ok(out(srv, rec));
    if (method === "DELETE") {
      if (rec.state === "COMPLETED") return err(409, "UPLOAD_CLOSED", "완료된 업로드는 취소할 수 없습니다(입력 원본 보호).");
      rec.state = "CANCELED";
      return { status: 204 };
    }
    return null;
  }
  if (seg[2] === "files" && seg.length === 3 && method === "POST") {
    if (rec.state !== "OPEN") return err(409, "UPLOAD_CLOSED", "닫힌 업로드입니다.");
    for (const f of (body?.files as { rel: string; size: number }[]) ?? []) {
      if (rec.files.some((x) => x.rel.toLowerCase() === f.rel.toLowerCase())) return err(409, "UPLOAD_FILE_DUPLICATE", `이미 있는 파일입니다: ${f.rel}`);
      rec.files.push({ index: rec.files.length, rel: f.rel, size: f.size, received: 0, done: false, sha256: null, sha256_expected: null });
    }
    return ok(out(srv, rec));
  }
  if (seg[2] === "files" && seg.length === 4 && method === "PUT") {
    const fault = up.faults.shift();
    if (fault) return fault;
    if (rec.state !== "OPEN") return err(409, "UPLOAD_CLOSED", "닫힌 업로드입니다.");
    const f = rec.files[Number(seg[3])];
    if (!f) return err(404, "UPLOAD_FILE_NOT_FOUND", "업로드 파일 번호가 없습니다.");
    if (f.done) return err(409, "UPLOAD_FILE_DONE", "이미 다 받은 파일입니다.", { received: f.size });
    const offset = Number(query.get("offset"));
    if (offset !== f.received) return err(409, "UPLOAD_OFFSET_MISMATCH", `offset ${offset}이 받은 크기 ${f.received}와 다릅니다`, { received: f.received });
    const size = raw?.size ?? 0;
    if (size > up.chunkSize) return err(413, "CHUNK_TOO_LARGE", "청크가 너무 큽니다.");
    if (offset + size > f.size) return err(422, "CHUNK_OVERFLOW", "선언한 파일 크기를 넘는 청크입니다.", { received: f.received });
    up.chunks.push({ id: rec.upload_id, index: f.index, offset, size, sha: headers.get("X-Chunk-Sha256") });
    f.received += size;
    if (f.received === f.size) {
      f.done = true;
      f.sha256 = "0".repeat(64);
    }
    return ok({ index: f.index, received: f.received, done: f.done, sha256: f.sha256 });
  }
  if (seg[2] === "complete" && method === "POST") {
    if (rec.state !== "OPEN") return err(409, "UPLOAD_CLOSED", "닫힌 업로드입니다.");
    if (rec.files.some((f) => !f.done)) return err(409, "UPLOAD_INCOMPLETE", "아직 다 받지 못한 파일이 있습니다.");
    const insp = rec.purpose === "DISCOVER" ? null : inspectPath(rec.purpose, rec.dir).body;
    if (up.failNextComplete && insp) {
      up.failNextComplete = false;
      const bad = { ...(insp as Record<string, unknown>), ok: false, problems: [{ code: "MODEL_PSMDL_MISSING", message: "psmdl 파일이 없습니다 — 빠진 파일을 추가하세요.", file: null }] };
      return ok({ upload_id: rec.upload_id, state: "OPEN", path: rec.dir, display_path: rec.dir, purpose: rec.purpose, inspect: bad, problems: [] });
    }
    rec.state = "COMPLETED";
    const file1 = rec.purpose === "CAD_FILE" || (rec.purpose === "PREDICT_INPUT" && rec.files.length === 1 && !rec.files[0].rel.includes("/"));
    const p = file1 ? `${rec.dir}\\${rec.files[0].rel}` : rec.dir;
    return ok({ upload_id: rec.upload_id, state: "COMPLETED", path: p, display_path: p, purpose: rec.purpose, inspect: insp ? { ...(insp as Record<string, unknown>), normalized_path: p } : null, problems: [] });
  }
  return null;
};

const TARGETS = ["surrogate-opt", "optimization", "equiv-check"];
/** GET /reports/analysis·/reports/{target}/{id}: 단일 HTML 파일(Content-Disposition). 시험은 srv.up.reports 로 쿼리를 확인 */
export const reportRoutes: Route = (srv, { method, path, seg, query }) => {
  if (method !== "GET" || seg[0] !== "reports") return null;
  srv.up.reports.push({ path, query: query.toString() });
  const stamp = "20261022-1030";
  if (seg[1] === "analysis" && seg.length === 2) {
    const src = query.get("source");
    if (src !== "batch" && src !== "doe") return err(422, "REPORT_SOURCE_INVALID", "source 는 batch 또는 doe 입니다.");
    if (srv.up.reportNotReady) return err(409, "REPORT_NOT_READY", "진행 중인 대상은 끝난 뒤 받을 수 있습니다.");
    return reportFile(`PAI_cushion_analysis-${src}_${String(query.get("id")).slice(0, 8)}_${stamp}.html`, `analysis ${query.toString()}`);
  }
  if (seg.length !== 3) return null;
  if (!TARGETS.includes(seg[1])) return err(404, "REPORT_TARGET_UNKNOWN", `보고서 대상이 아닙니다: ${seg[1]}`);
  if (srv.up.reportNotReady) return err(409, "REPORT_NOT_READY", "진행 중인 대상은 끝난 뒤 받을 수 있습니다.");
  return reportFile(`PAI_cushion_${seg[1]}_${seg[2].slice(0, 8)}_${stamp}.html`, `${seg[1]} ${seg[2]}`);
};

function reportFile(name: string, title: string): MockResp {
  return {
    status: 200,
    text: `<!doctype html><meta charset="utf-8"><title>${title}</title><body><h1>목 보고서</h1><p>${title}</p>`,
    contentType: "text/html; charset=utf-8",
    headers: { "Content-Disposition": `attachment; filename*=UTF-8''${encodeURIComponent(name)}` },
  };
}
