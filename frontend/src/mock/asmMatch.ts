// 조립 매칭 목(asm-match.md §6.3·AM-C2 9·10, 타입 api/typesAsmMatch.ts):
// POST·GET /studies/{id}/asm-matches(202 ASM_MATCH 작업 · 목록 `?source&latest&limit` → {items}) · GET /asm-matches/{id} · PUT .../rows(422 problems[]) · POST .../check(202) · POST .../confirm · GET /artifacts/{id}/media(GLB).
// 응답 가산 필드: last_job·warnings·rows_complete·use_bodies·created_at·updated_at, check.current·glb_artifact_id·worst.points[node_id].
// 시나리오는 조립 폴더 경로의 낱말로 고른다: (기본) 성공 · `offset` 원점 차이(CUSH_L 거리 FAIL + ASM_OFFSET_SUSPECT) · `shared` 노드 공유(CUSH_R FAIL + ASM_SHARED_NODES) · `nosolid` 목록 읽기 실패.
// 정답 매칭 = CUSH_L ↔ PART 3000001, CUSH_R ↔ PART 3000002+3000003(1:N). 추천은 CUSH_R에 3000002만 채운다(1:1 초안 — 사용자가 3000003을 더한다).
import type { Artifact, AsmBody, AsmCheck, AsmCheckRow, AsmMatch, AsmMatchRow, AsmPart, AsmRecommend, AsmRowProblem, AsmWorstPoint, Job, ParamSetDiscover } from "../api/types";
import { putKey } from "../lib/asmMatch";
import { asmMatchGlb } from "./geomViewData";
import { createJobFor } from "./jobs";
import { err, needPower, ok, type MockResp, type Route } from "./route";
import type { MockServer } from "./server";

export type AsmScenario = "ok" | "offset" | "shared" | "nosolid";

export interface AsmRec {
  match_id: string;
  study_id: string;
  source: AsmMatch["source"];
  assem: AsmMatch["assem"];
  bodies: AsmBody[];
  parts: AsmPart[];
  recommend: AsmRecommend[];
  rows: AsmMatchRow[];
  excluded_bodies: string[];
  check: AsmCheck | null;
  confirmed: AsmMatch["confirmed"];
  failed: { code: string; message: string } | null;
  scan_done: boolean;
  confirmed_flag: boolean;
  last_job_id: string | null;
  created_at: string;
  updated_at: string;
  scenario: AsmScenario;
  /** 진행 중 작업(완료 훅이 처리) */
  pending: { job_id: string; mode: "parts" | "check" } | null;
  seq: number;
}

const RECS = new WeakMap<MockServer, Map<string, AsmRec>>();
export const asmRecs = (srv: MockServer): Map<string, AsmRec> => {
  let m = RECS.get(srv);
  if (!m) RECS.set(srv, (m = new Map()));
  return m;
};

const EXPECT: Record<string, number[]> = { CUSH_L: [3000001], CUSH_R: [3000002, 3000003] };

const PARTS: AsmPart[] = [
  { pid: 3000001, title: "CUSH_L", elems: { TETRA4: 41230 }, nodes: 9120, volume: 812345.2, solid_ok: true },
  { pid: 3000002, title: "CUSH_R_A", elems: { TETRA4: 20100 }, nodes: 4600, volume: 410200.4, solid_ok: true },
  { pid: 3000003, title: "CUSH_R_B", elems: { TETRA4: 19800 }, nodes: 4500, volume: 402100.9, solid_ok: true },
  { pid: 3000009, title: "CUSH_SPARE", elems: { TETRA4: 5000 }, nodes: 1300, volume: 52000, solid_ok: true },
  { pid: 2001, title: "PRODUCT_TIE", elems: { SHELL: 1200 }, nodes: 1300, volume: null, solid_ok: false },
  { pid: 1, title: "BOX_TOP", elems: { SHELL: 8800 }, nodes: 9000, volume: null, solid_ok: false },
];

/** 조립 폴더 경로의 마지막 폴더 이름으로 고른다(앞쪽 `shared` 같은 루트 이름에 걸리지 않게) */
export const scenarioOf = (path: string): AsmScenario => {
  const last = path.split(/[\\/]/).filter(Boolean).pop() ?? "";
  return /nosolid/i.test(last) ? "nosolid" : /offset/i.test(last) ? "offset" : /shared/i.test(last) ? "shared" : "ok";
};

function scan(rec: AsmRec) {
  rec.updated_at = new Date().toISOString();
  if (rec.scenario === "nosolid") {
    rec.failed = { code: "ASM_NO_SOLID_PART", message: "조립에 TETRA4 PART가 없습니다" };
    return;
  }
  rec.scan_done = true;
  rec.parts = PARTS.map((p) => ({ ...p }));
  rec.bodies = [
    { body: "CUSH_L", volume: 812345.2, bbox: [0, 0, 0, 120, 80, 20.5] },
    { body: "CUSH_R", volume: 812301.3, bbox: [150, 0, 0, 270, 80, 20.5] },
  ];
  rec.recommend = [
    { body: "CUSH_L", pids: [3000001], score: 0.97 },
    { body: "CUSH_R", pids: [3000002], score: 0.81 },
  ];
}

function checkRow(rec: AsmRec, r: { body: string; pids: number[] }, worst: Record<string, AsmWorstPoint[]>): AsmCheckRow {
  const exact = [...r.pids].sort().join() === [...(EXPECT[r.body] ?? [])].sort().join();
  const base = { body: r.body, pids: r.pids, skin_nodes: 4210, tol_mm: 0.05, shared: { nodes: 0, parts: [] }, suggest: null, code: null as string | null };
  const w = (n: number) => ({ count: worst[r.body]?.length ?? n, points: worst[r.body] ?? [] });
  if (!exact) return { ...base, status: "FAIL", code: "ASM_BOUNDARY_MISMATCH", match_ratio: 0.312, dist_mm: { mean: 12.4, p95: 38.8, p99: 40.1, max: 41.2 }, worst: w(0) };
  if (rec.scenario === "offset" && r.body === "CUSH_L")
    return { ...base, status: "FAIL", code: "ASM_BOUNDARY_MISMATCH", match_ratio: 0.41, dist_mm: { mean: 9.8, p95: 10.0, p99: 10.0, max: 10.2 }, suggest: { code: "ASM_OFFSET_SUSPECT", translate_mm: [10, 0, 0], match_ratio_after: 0.9995 }, worst: w(0) };
  if (rec.scenario === "shared" && r.body === "CUSH_R")
    return { ...base, status: "FAIL", code: "ASM_SHARED_NODES", match_ratio: 0.9991, dist_mm: { mean: 0.004, p95: 0.012, p99: 0.02, max: 0.043 }, shared: { nodes: 37, parts: [{ pid: 2001, title: "PRODUCT_TIE", nodes: 37 }] }, worst: w(0) };
  return { ...base, status: "PASS", match_ratio: 0.9995, dist_mm: { mean: 0.003, p95: 0.011, p99: 0.019, max: 0.041 }, worst: w(0) };
}

function runCheck(srv: MockServer, rec: AsmRec) {
  rec.seq += 1;
  const hot: Record<string, [number, number, number]> = { CUSH_L: [120, 0, 12.5], CUSH_R: [270, 40, 12.5] };
  // 먼저 거리 크기를 정하고(행 판정) → GLB·worst 점 → 행에 붙인다
  const first = rec.rows.map((r) => checkRow(rec, r, {}));
  const g = asmMatchGlb(first.map((r) => ({ body: r.body, max: r.dist_mm?.max ?? 0.01, hot: hot[r.body] ?? [0, 0, 0] })));
  // 서버는 worst_<body>.npz를 읽어 거리 내림차순 상위 점 {node_id, xyz, dist_mm}를 준다
  const worst: Record<string, AsmWorstPoint[]> = Object.fromEntries(
    Object.entries(g.worst).map(([b, pts]) => [b, pts.map((p, i) => ({ node_id: (b === "CUSH_L" ? 710000 : 720000) + i * 37 + 1, xyz: p.xyz, dist_mm: p.dist_mm }))]),
  );
  const rows = rec.rows.map((r) => checkRow(rec, r, worst));
  const id = srv.nid("a");
  srv.artifacts.push({ id, study_id: rec.study_id, job_id: rec.pending?.job_id ?? "", kind: "ASM_MATCH_GLB" as Artifact["kind"], file_name: "match_fe.glb", size: 0, sha256: null, content_type: "model/gltf-binary", created_at: new Date().toISOString(), body: "", render: () => g.glb } as Artifact & { body: string; render: () => Uint8Array });
  const check: AsmCheck = {
    seq: rec.seq, status: rows.every((r) => r.status === "PASS") ? "PASS" : "FAIL", rows_sha256: putKey({ rows: rec.rows, excluded_bodies: rec.excluded_bodies }), rows,
    current: true, file_checks: { shared_nodes: rows.reduce((n, r) => n + r.shared.nodes, 0), duplicate_node_defs: 0 }, glb_url: `/physicsai/api/artifacts/${id}/media`, glb_artifact_id: id,
  };
  rec.check = check;
  rec.updated_at = new Date().toISOString();
}

/** 작업 종료 훅(engine.finishJob) */
export function finishAsmMatch(srv: MockServer, j: Job) {
  if (j.job_type !== "ASM_MATCH") return;
  const rec = asmRecs(srv).get(String((j.params as { match_id?: string }).match_id));
  if (!rec || rec.pending?.job_id !== j.id) return;
  if (rec.pending.mode === "parts") scan(rec);
  else runCheck(srv, rec);
  rec.pending = null;
}

const useBodiesOf = (srv: MockServer, rec: AsmRec): string[] => {
  if (rec.source.kind !== "train") return [];
  const used = (srv.p2.setups[rec.study_id]?.parameters ?? []).filter((p) => p.use).map((p) => p.name);
  return rec.bodies.map((b) => b.body).filter((b) => used.some((n) => n.startsWith(`${b}_`)));
};

const rowsComplete = (rec: AsmRec) => rec.rows.length > 0 && rec.bodies.every((b) => rec.rows.some((r) => r.body === b.body) || rec.excluded_bodies.includes(b.body));

/** 서버의 view(): 상태는 파일 + 최신 작업 + 입력 변경 판정에서 계산한다 */
export function asmOut(srv: MockServer, rec: AsmRec): AsmMatch {
  const sha = putKey({ rows: rec.rows, excluded_bodies: rec.excluded_bodies });
  const check = rec.check ? { ...structuredClone(rec.check), current: rec.check.rows_sha256 === sha } : null;
  const job = rec.last_job_id ? srv.jobs.find((j) => j.id === rec.last_job_id) : undefined;
  let state: AsmMatch["state"];
  if (rec.pending) state = rec.pending.mode === "parts" ? "SCANNING" : "CHECKING";
  else if (!rec.scan_done) state = "FAILED";
  else if (rec.confirmed_flag) state = "CONFIRMED";
  else if (check?.current && check.status === "PASS") state = "CHECKED";
  else state = "DRAFT";
  return {
    match_id: rec.match_id, study_id: rec.study_id, state, source: structuredClone(rec.source), assem: structuredClone(rec.assem),
    bodies: structuredClone(rec.bodies), parts: structuredClone(rec.parts), recommend: structuredClone(rec.recommend),
    rows: structuredClone(rec.rows), excluded_bodies: [...rec.excluded_bodies], check, confirmed: structuredClone(rec.confirmed), stale_reason: null,
    last_job: job
      ? { id: job.id, mode: rec.pending?.mode ?? (rec.check ? "check" : "parts"), state: job.state, failure_code: rec.failed?.code ?? null, failure_message: rec.failed?.message ?? null, progress_pct: job.progress_pct ?? null }
      : null,
    warnings: [], rows_complete: rowsComplete(rec), use_bodies: useBodiesOf(srv, rec), created_at: rec.created_at, updated_at: rec.updated_at,
  };
}

function create(srv: MockServer, sid: string, body: Record<string, unknown> | null): MockResp {
  const s = srv.studies.find((x) => x.id === sid);
  if (!s) return err(404, "NOT_FOUND", "Study를 찾을 수 없습니다.");
  const deny = needPower(srv, s.project_id);
  if (deny) return deny;
  const path = String(body?.radioss_assem_path ?? "").trim();
  const cad = (body?.cad ?? null) as { kind?: string; path?: string } | null;
  if (!path || !cad) return err(422, "INVALID_PARAMS", "조립 폴더와 CAD를 지정하세요.");
  if (cad.kind === "train" && !(srv.p2.setups[sid]?.engine === "native" && (srv.p2.setups[sid]?.parameters.length ?? 0) > 0))
    return err(409, "PREREQUISITE_MISSING", "①-1 Native 추출이 먼저 필요합니다.", { missing: ["TRAIN_FEATURES"] });
  const id = srv.nid("am");
  const r = createJobFor(srv, s, "ASM_MATCH", { mode: "parts", match_id: id, radioss_assem_path: path });
  if (r.status !== 201) return r;
  const j = r.body as Job;
  const now = new Date().toISOString();
  const rec: AsmRec = {
    match_id: id, study_id: sid, source: cad.kind === "path" ? { kind: "path", cad_name: (cad.path ?? "").split(/[\\/]/).pop() ?? null } : { kind: "train", cad_name: "cushion_base.step", features_rel: "01_train/parameter_features.json" },
    assem: { display_path: path, digest: "sha256:ab12", starter: "MODEL_0000.rad", files: 12 }, bodies: [], parts: [], recommend: [], rows: [], excluded_bodies: [], check: null, confirmed: null,
    failed: null, scan_done: false, confirmed_flag: false, last_job_id: j.id, created_at: now, updated_at: now,
    scenario: scenarioOf(path), pending: { job_id: j.id, mode: "parts" }, seq: 0,
  };
  asmRecs(srv).set(id, rec);
  return { status: 202, body: { match_id: id, job_id: j.id } };
}

/** PUT rows 검증(AM-C2 10): 422 ASM_ROW_INVALID + problems[{code, body, pid?}] */
function putRows(srv: MockServer, rec: AsmRec, body: Record<string, unknown> | null): MockResp {
  if (rec.confirmed_flag) return err(409, "ASM_MATCH_CONFIRMED", "이미 저장된 매칭입니다.");
  if (rec.pending) return err(409, "ASM_MATCH_BUSY", "조립 매칭 작업이 진행 중입니다.");
  const rows = (body?.rows ?? []) as { body: string; pids: number[] }[];
  const excluded = (body?.excluded_bodies ?? []) as string[];
  const probs: AsmRowProblem[] = [];
  const names = new Set(rec.bodies.map((b) => b.body));
  const useBodies = new Set(useBodiesOf(srv, rec));
  const seenBody = new Set<string>();
  const owner = new Map<number, string>();
  for (const r of rows) {
    if (!names.has(r.body)) {
      probs.push({ code: "UNKNOWN_BODY", body: r.body });
      continue;
    }
    if (seenBody.has(r.body)) {
      probs.push({ code: "BODY_DUPLICATE", body: r.body });
      continue;
    }
    seenBody.add(r.body);
    for (const pid of r.pids) {
      const p = rec.parts.find((x) => x.pid === pid);
      if (!p) probs.push({ code: "UNKNOWN_PID", body: r.body, pid });
      else if (!p.solid_ok) probs.push({ code: "NOT_SOLID", body: r.body, pid });
      else if (owner.has(pid)) probs.push({ code: "PID_DUPLICATE", body: r.body, pid });
      else owner.set(pid, r.body);
    }
  }
  for (const b of excluded) {
    if (!names.has(b)) probs.push({ code: "UNKNOWN_BODY", body: b });
    else if (seenBody.has(b)) probs.push({ code: "BODY_DUPLICATE", body: b });
    else if (useBodies.has(b)) probs.push({ code: "USE_PARAM", body: b });
  }
  for (const b of names) if (!seenBody.has(b) && !excluded.includes(b) && !probs.some((p) => p.body === b)) probs.push({ code: "BODY_MISSING", body: b });
  if (!rows.length && !probs.length) probs.push({ code: "ROWS_EMPTY" });
  if (probs.length) return err(422, "ASM_ROW_INVALID", "매칭 표가 올바르지 않습니다", { problems: probs, ...(probs[0].body ? { body: probs[0].body } : {}) });
  rec.rows = rows.map((r) => ({ body: r.body, pids: [...r.pids].sort((a, b) => a - b) }));
  rec.excluded_bodies = [...excluded];
  rec.updated_at = new Date().toISOString();
  return ok(asmOut(srv, rec)); // 검사 결과는 남지만 check.current=false
}

function list(srv: MockServer, sid: string, q: URLSearchParams): MockResp {
  if (!srv.studies.some((x) => x.id === sid)) return err(404, "NOT_FOUND", "Study를 찾을 수 없습니다.");
  const source = q.get("source");
  const limit = Number(q.get("limit") ?? 20);
  let recs = [...asmRecs(srv).values()].filter((r) => r.study_id === sid && (!source || r.source.kind === source)).sort((a, b) => b.created_at.localeCompare(a.created_at) || b.match_id.localeCompare(a.match_id));
  if (q.get("latest") === "true") recs = recs.slice(0, 1);
  return ok({ items: recs.slice(0, Math.max(1, limit)).map((r) => asmOut(srv, r)) });
}

export const asmMatchRoutes: Route = (srv, { method, seg, body, query }) => {
  if (seg[0] === "studies" && seg[2] === "asm-matches" && seg.length === 3 && method === "POST") return create(srv, seg[1], body);
  if (seg[0] === "studies" && seg[2] === "asm-matches" && seg.length === 3 && method === "GET") return list(srv, seg[1], query);
  if (seg[0] === "artifacts" && seg[2] === "media") {
    const a = srv.artifacts.find((x) => x.id === seg[1]) as (Artifact & { render?: () => Uint8Array }) | undefined;
    if (!a || (a.kind as string) !== "ASM_MATCH_GLB" || !a.render) return null;
    return { status: 200, bytes: a.render(), contentType: a.content_type, headers: { "Accept-Ranges": "bytes" } };
  }
  if (seg[0] !== "asm-matches" || !seg[1]) return null;
  const rec = asmRecs(srv).get(seg[1]);
  if (!rec) return err(404, "NOT_FOUND", "조립 매칭을 찾을 수 없습니다.");
  const s = srv.studies.find((x) => x.id === rec.study_id)!;
  if (method === "GET" && seg.length === 2) return ok(asmOut(srv, rec));
  const deny = needPower(srv, s.project_id);
  if (deny) return deny;
  if (method === "PUT" && seg[2] === "rows") return putRows(srv, rec, body);
  if (method === "POST" && seg[2] === "check") {
    if (rec.confirmed_flag) return err(409, "ASM_MATCH_CONFIRMED", "이미 저장된 매칭입니다.");
    if (rec.pending) return err(409, "ASM_MATCH_BUSY", "조립 매칭 작업이 진행 중입니다.");
    if (!rowsComplete(rec)) return err(409, "ASM_ROWS_INCOMPLETE", "모든 바디를 component에 연결하거나 '매칭 안 함'으로 두세요");
    const r = createJobFor(srv, s, "ASM_MATCH", { mode: "check", match_id: rec.match_id });
    if (r.status !== 201) return r;
    rec.pending = { job_id: (r.body as Job).id, mode: "check" };
    rec.last_job_id = (r.body as Job).id;
    return { status: 202, body: { job_id: (r.body as Job).id } };
  }
  if (method === "POST" && seg[2] === "confirm") {
    if (rec.pending) return err(409, "ASM_MATCH_BUSY", "조립 매칭 작업이 진행 중입니다.");
    const cur = asmOut(srv, rec).check;
    if (!cur || cur.status !== "PASS" || !cur.current) return err(409, "ASM_CHECK_REQUIRED", "경계 일치 검사를 통과해야 저장할 수 있습니다");
    rec.confirmed_flag = true;
    rec.confirmed = { sha256: "sha256:cd34", confirmed_at: new Date().toISOString() };
    return ok(asmOut(srv, rec));
  }
  return null;
};

const joinPath = (a: string, b: string) => `${a.replace(/[\\/]+$/, "")}/${b}`;
const normPath = (p: string) => p.replace(/\\/g, "/").replace(/\/+$/, "").toLowerCase();

/** ④ 세트 등록 게이트(asm_match_gate.require_for_set): 확정본 + source=path + 세트 STEP·조립 폴더 = 매칭 */
export function asmRegisterGate(srv: MockServer, studyId: string, id: string, path: string, choice: Record<string, string | null>, found: Pick<ParamSetDiscover, "cad" | "radioss_assem">): MockResp | null {
  const rec = asmRecs(srv).get(id);
  const cadRel = choice.cad ?? found.cad[0]?.rel ?? null;
  if (found.cad.find((c) => c.rel === cadRel)?.kind === "parts") return err(422, "ASM_MATCH_UNSUPPORTED", "조립 매칭은 STEP 파일 1개일 때만 쓸 수 있습니다(parts 폴더 불가)");
  if (!rec || rec.study_id !== studyId || !rec.confirmed_flag) return err(409, "PREREQUISITE_MISSING", "조립 매칭을 먼저 하세요 — 조립 매칭 카드에서 매칭해 저장하세요", { missing: ["ASM_MATCH"] });
  if (rec.source.kind !== "path") return err(409, "ASM_MATCH_STALE", "이 조립 매칭의 STEP 출처가 이 작업과 다릅니다 — 조립 매칭을 다시 하세요", { match_id: id });
  const assemRel = choice.radioss_assem ?? found.radioss_assem[0]?.rel ?? null;
  const same = assemRel != null && normPath(rec.assem.display_path) === normPath(joinPath(path, assemRel)) && cadRel != null && rec.source.cad_name === cadRel.split("/").pop();
  return same ? null : err(409, "ASM_MATCH_STALE", "등록하려는 STEP이 조립 매칭의 STEP과 다릅니다 — 조립 매칭을 다시 하세요", { match_id: id });
}
