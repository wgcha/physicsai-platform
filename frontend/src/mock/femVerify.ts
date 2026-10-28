// S16 V2 목(phase3 §21.3): 조립 상태 FEM 검증. fem-verifications preview·create·list·get·media·curves·table.csv·cancel·rerun.
// 상태 갱신은 작업 상태(PREDICT 동반 예측·FEM_VERIFY)에서 syncFem이 계산한다(틱·조회 때마다, 멱등) — 종료 훅 흉내.
// 경로 이름으로 조립 원본 시나리오를 고른다: nostarter → starter 0개, two → 2개(ASSEM_STARTER_COUNT), huge → ASSEM_TOO_LARGE,
//   nocsv·noinc·noref → 경고 RENUM_CSV_MISSING·MESH_INCLUDE_NOT_IN_ASSEM·MESH_INCLUDE_NOT_REFERENCED. 허용 루트 = AI_WORK 또는 SPDM 루트(S:\SPDM, 읽기 전용).
// MockOptions.femVerify = "demo" → FV-001 완료(⑤ 배치 run)·FV-002 실패(starter 2개)·FV-003 동반 예측 대기.
// R-F 분할(동작 불변): 기록·작업 사슬 femVerifyRec · 출처 해석·조립 원본 femVerifySource · 미리보기·생성 femVerifyCreate · 상태 동기화·비교 femVerifySync · 출력·재실행 femVerifyOut. 옛 import 경로는 아래에서 재노출한다.
import { baseJob, iso, makeSteps } from "./data";
import { err, needPower, ok, type Route } from "./route";
import type { MockServer } from "./server";
import { batchLabel } from "./predictBatch";
import { latest } from "./femVerifyRec";
import type { FemRec } from "./femVerifyRec";
import { assemblyPlanFor, checkCustomPath } from "./femVerifySource";
import { createRec, previewOf } from "./femVerifyCreate";
import { buildCompare, makeMedia, syncFem } from "./femVerifySync";
import { cancelJob, csvOf, curvesOf, detailOf, mediaOf, rerun, summaryOf } from "./femVerifyOut";
export { MOCK_SPDM_ROOT, fvLabel } from "./femVerifyRec";
export type { FemRec } from "./femVerifyRec";
export { assemblyPlanFor } from "./femVerifySource";
export { syncFem, buildCompare } from "./femVerifySync";

// ------------------------------------------------------------------ 라우트
export const femVerifyRoutes: Route = (srv, { method, seg, query, body, me }) => {
  if (seg[0] === "studies" && seg[1] && seg[2] === "fem-verifications") {
    const s = srv.studies.find((x) => x.id === seg[1]);
    if (!s) return err(404, "NOT_FOUND", "Study를 찾을 수 없습니다.");
    syncFem(srv);
    if (method === "GET" && !seg[3]) {
      const lim = Math.max(1, Math.min(200, Number(query.get("limit") ?? 50)));
      const st = (query.get("status") ?? "").split(",").filter(Boolean);
      const cursor = query.get("cursor");
      let list = srv.fems.filter((r) => r.study_id === s.id).sort((a, b) => b.created_at.localeCompare(a.created_at) || b.fv_no - a.fv_no);
      const pj = query.get("predict_job_id");
      const bid = query.get("batch_id");
      const oid = query.get("opt_id");
      if (pj) list = list.filter((r) => r.predict_job_id === pj || r.links.predict_job_id === pj);
      if (bid) list = list.filter((r) => r.links.batch_id === bid);
      if (oid) list = list.filter((r) => r.links.opt_id === oid);
      if (st.length) list = list.filter((r) => st.includes(r.status));
      if (cursor) {
        const [c, id] = cursor.split("|");
        list = list.filter((r) => r.created_at < c || (r.created_at === c && r.id < id));
      }
      const page = list.slice(0, lim);
      const last = page[page.length - 1];
      return { status: 200, body: page.map((r) => summaryOf(r, srv)), headers: list.length > lim && last ? { "X-Next-Cursor": `${last.created_at}|${last.id}` } : undefined };
    }
    if (method === "POST" && (seg[3] === "preview" || !seg[3])) {
      const d = needPower(srv, s.project_id);
      if (d) return d;
      if (seg[3] === "preview") {
        const p = previewOf(srv, s, body ?? {});
        return "error" in p ? p.error : ok(p.out);
      }
      return createRec(srv, s, body ?? {}, { id: me.user_id, name: me.display_name });
    }
    return null;
  }
  if (seg[0] === "fem-verifications" && seg[1]) {
    syncFem(srv);
    const r = srv.fems.find((x) => x.id === seg[1]);
    if (!r) return err(404, "FEM_VERIFY_NOT_FOUND", "FEM 검증을 찾을 수 없습니다.");
    const s = srv.studies.find((x) => x.id === r.study_id)!;
    if (method === "GET" && !seg[2]) return ok(detailOf(srv, r));
    if (method === "GET" && seg[2] === "media") return ok(mediaOf(srv, r));
    if (method === "GET" && seg[2] === "curves") return ok(curvesOf(r, query.get("name")));
    if (method === "GET" && seg[2] === "table.csv") return { status: 200, text: csvOf(r), contentType: "text/csv" };
    if (method === "POST" && (seg[2] === "cancel" || seg[2] === "rerun")) {
      const d = needPower(srv, s.project_id);
      if (d) return d;
      if (seg[2] === "cancel") {
        if (!(me.is_global_admin || me.user_id === r.created_by)) return err(403, "PERMISSION_DENIED", "등록자 또는 관리자만 취소할 수 있습니다.", { required: "owner_or_admin" });
        if (r.status === "WAITING_PREDICT") cancelJob(srv, latest(srv, r.predict_job_id));
        else if (r.status === "RUNNING") cancelJob(srv, latest(srv, r.job_id));
        syncFem(srv);
        return { status: 202, body: detailOf(srv, r) };
      }
      if (r.status !== "FAILED" && r.status !== "CANCELED") return err(409, "FEM_VERIFY_NOT_RERUNNABLE", "실패하거나 취소된 검증만 다시 실행할 수 있습니다.");
      return rerun(srv, r, { id: me.user_id, name: me.display_name });
    }
    return null;
  }
  // paths/inspect FEM_ASSEMBLY(조립 원본 폴더 확인)
  if (method === "POST" && seg[0] === "studies" && seg[2] === "paths" && seg[3] === "inspect" && body?.purpose === "FEM_ASSEMBLY") {
    const s = srv.studies.find((x) => x.id === seg[1]);
    if (!s) return err(404, "NOT_FOUND", "Study를 찾을 수 없습니다.");
    const d = needPower(srv, s.project_id);
    if (d) return d;
    const path = String(body.path ?? "");
    const bad = checkCustomPath(path);
    if (bad) return bad;
    const { plan: pl } = assemblyPlanFor(path);
    const { problems, warnings, ...summary } = pl;
    return ok({ normalized_path: path.replace(/\//g, "\\"), ok: problems.length === 0, problems, summary: { ...summary, warnings } });
  }
  return null;
};

// ------------------------------------------------------------------ 시드
export function seedFemVerify(srv: MockServer) {
  const s = srv.studies.find((x) => x.id === "s-cushion")!;
  const by = { id: "u-power", name: "김연구" };
  const b = srv.batches.find((x) => x.id === "pb-2");
  const run = b?.runs.find((r) => r.doe_no === 7);
  const pj = latest(srv, run?.predict_job_id ?? null);
  const ps = srv.paramSets[0];
  // FV-001: 완료(⑤ 배치 run)
  if (b && run && pj) {
    const vals = (run.values ?? (pj.params as { values?: Record<string, number> }).values ?? {}) as Record<string, number>;
    const fj = baseJob({ id: "j-fv1", study_id: s.id, project_id: s.project_id, study_title: s.title, job_type: "FEM_VERIFY", state: "SUCCEEDED", created_at: iso(60 * 5), started_at: iso(60 * 5 - 1), finished_at: iso(60 * 2), steps: makeSteps("FEM_VERIFY", 10, null), progress_pct: 100, params: { fem_verify_id: "fv-1", fv_no: 1, hpc: null } });
    srv.jobs.push(fj);
    const r: FemRec = {
      id: "fv-1", study_id: s.id, fv_no: 1, source_kind: "BATCH_RUN", source_label: `${batchLabel(b.batch_no)} DOE #7`, links: { predict_job_id: pj.id, batch_id: b.id, doe_no: 7, opt_id: null }, predict_job_id: pj.id, companion: false,
      param_set_id: ps.id, model_id: s.final_model_id ?? null, values: vals, applied_values: vals, out_of_range: [], assem_kind: "TRAIN_DOE", assem_label: "DOE-001", assem_path: srv.disp(s.id, "01_train/doe/doe-1/radioss_assem"),
      input_mode: "rebuild", hpc_mode: srv.hpcMode === "scx" ? "scx" : "command", status: "DONE", job_id: fj.id, attempt_no: 1, compare: null, failure: null,
      warnings: [{ code: "DOE_PARAM_MISMATCH", message: "① DOE 파라미터가 템플릿 파라미터와 다릅니다(조립 폴더만 사용)" }], media: [], created_by: by.id, created_by_name: by.name, created_at: iso(60 * 5), finished_at: iso(60 * 2), notified: true,
    };
    r.compare = buildCompare(srv, r);
    makeMedia(srv, r, fj);
    srv.fems.push(r);
  }
  // FV-002: 실패(starter 2개)
  const fj2 = baseJob({ id: "j-fv2", study_id: s.id, project_id: s.project_id, study_title: s.title, job_type: "FEM_VERIFY", state: "FAILED", created_at: iso(60 * 3), started_at: iso(60 * 3 - 1), finished_at: iso(60 * 3 - 2), steps: makeSteps("FEM_VERIFY", 0, null, { failedIdx: 0 }), failure_code: "ASSEM_STARTER_COUNT", failure_message: "starter(*_0000.rad)가 정확히 1개 있어야 합니다(현재 2개)", params: { fem_verify_id: "fv-2", fv_no: 2, hpc: null } });
  srv.jobs.push(fj2);
  srv.fems.push({
    id: "fv-2", study_id: s.id, fv_no: 2, source_kind: "PREDICT_JOB", source_label: "④ 예측 (시드)", links: { predict_job_id: "j-pred", batch_id: null, doe_no: null, opt_id: null }, predict_job_id: "j-pred", companion: false,
    param_set_id: ps.id, model_id: s.final_model_id ?? null, values: (srv.jobs.find((j) => j.id === "j-pred")!.params as { values: Record<string, number> }).values, applied_values: (srv.jobs.find((j) => j.id === "j-pred")!.params as { values: Record<string, number> }).values, out_of_range: [],
    assem_kind: "CUSTOM", assem_label: "직접 지정", assem_path: "E:\\shared\\AI_WORK\\cushion_v1\\00_inbox\\two_starters", input_mode: "rebuild", hpc_mode: srv.hpcMode === "scx" ? "scx" : "command", status: "FAILED", job_id: fj2.id, attempt_no: 1, compare: null,
    failure: { code: "ASSEM_STARTER_COUNT", message: "starter(*_0000.rad)가 정확히 1개 있어야 합니다(현재 2개)" }, warnings: [], media: [], created_by: by.id, created_by_name: by.name, created_at: iso(60 * 3), finished_at: iso(60 * 3 - 2), notified: false,
  });
  // FV-003: 템플릿 값 — 같은 값의 예측이 없어 동반 예측을 먼저 실행
  const vals3 = { THK_TOP: 0.47, THK_FOAM: 2.6, E_FOAM: 9.5, RIB_N: 7 };
  const comp = baseJob({ id: "j-fvp3", study_id: s.id, project_id: s.project_id, study_title: s.title, job_type: "PREDICT", state: "QUEUED", created_at: iso(8), params: { param_set_id: ps.id, model_id: null, values: vals3, value_source: "manual", source_run_key: null, template_kind: "assembly", fem_verify_id: "fv-3" } });
  srv.jobs.push(comp);
  srv.queueOrder.set(comp.id, ++srv.queueSeq);
  srv.fems.push({
    id: "fv-3", study_id: s.id, fv_no: 3, source_kind: "VALUES", source_label: "템플릿 값 THK_TOP=0.47, THK_FOAM=2.6", links: { predict_job_id: null, batch_id: null, doe_no: null, opt_id: null }, predict_job_id: comp.id, companion: true,
    param_set_id: ps.id, model_id: s.final_model_id ?? null, values: vals3, applied_values: vals3, out_of_range: [], assem_kind: "TRAIN_DOE", assem_label: "DOE-001", assem_path: srv.disp(s.id, "01_train/doe/doe-1/radioss_assem"),
    input_mode: "rebuild", hpc_mode: srv.hpcMode === "scx" ? "scx" : "command", status: "WAITING_PREDICT", job_id: null, attempt_no: 1, compare: null, failure: null, warnings: [], media: [], created_by: by.id, created_by_name: by.name, created_at: iso(8), finished_at: null, notified: false,
  });
}
