// 2차 ⑤(phase2.md §9) 최적화: 시드·요약 산출물, 작업 훅(사전 검사·생성·진행·완료), ⑤ 라우트.
import type { Job, JobType, OptResponse, Study } from "../api/types";
import { iso, rng } from "./data";
import { err, ok, type MockResp, type Route } from "./route";
import type { Phase2Mock, SeedJob } from "./phase2";

function optSummary(seed: number, n: number) {
  const r = rng(seed);
  const rows: (number | string)[][] = [];
  let best = 240;
  for (let i = 1; i <= n; i++) {
    const t = 0.3 + r() * 0.9;
    const f = 1 + r() * 2;
    const vm = Math.max(118, best - r() * 18 + (r() - 0.6) * 22);
    best = Math.min(best, vm + 6);
    const dx = 2.4 + r() * 3.4;
    rows.push([i, Number(t.toFixed(4)), Number(f.toFixed(4)), Math.round(11.9 + r() * 1.2), 2 + Math.floor(r() * 7), Number(vm.toFixed(2)), Number(dx.toFixed(3)), dx <= 5 ? "Yes" : "No"]);
  }
  return { columns: ["Design", "THK_TOP", "THK_FOAM", "RIB_H", "RIB_N", "MAX_VM", "DISP_X", "Feasible"], rows };
}

/** ⑤ summary.json(C14 csv_table): rows는 문자열 배열 */
function summaryJson(t: { columns: string[]; rows: (number | string)[][] }, fileRel: string) {
  return { parser: "hst_csv", kind: "csv_table", file_rel: fileRel, columns: t.columns, rows: t.rows.map((r) => r.map(String)) };
}

/** ⑤ 시드: 최적화 작업·산출물·opt-1 */
export function seedOptimize(p2: Phase2Mock, J: SeedJob, sid: string) {
  // ⑤ 최적화
  const responses: OptResponse[] = [
    { name: "MAX_VM", source: "H3D", subcase: 1, datatype: "Stress", component: "vonMises", layer: "", stat: "MAX", goal: "MINIMIZE" },
    { name: "DISP_X", source: "XYDATA", request: "Node 100", component: "X", stat: "ABSMAX", goal: "CONSTRAINT", bound: "<=", value: 5 },
  ];
  J({ id: "j-opt", job_type: "OPTIMIZE", state: "SUCCEEDED", created_at: iso(60 + 10), started_at: iso(60 + 9), finished_at: iso(22), params: { approach: "OPT", opt_method: "ARSM", max_designs: 25, run_nominal: true, study_folder: "HST_PHYSICSAI_OPTIMIZATION", responses }, result: { runs_started: 25, log_error_lines: 0 } });
  const summary = optSummary(3, 25);
  const sumId = p2.s.addArtifact("j-opt", sid, "OPT_SUMMARY", "05_opt/j-opt/summary.json", "application/json", JSON.stringify(summaryJson(summary, "HST_PHYSICSAI_OPTIMIZATION/approaches/opt_1/opt_summary.csv")));
  const csv = [summary.columns.join(","), ...summary.rows.map((r) => r.join(","))].join("\n") + "\n";
  p2.s.addArtifact("j-opt", sid, "OPT_FILE", "05_opt/j-opt/HST_PHYSICSAI_OPTIMIZATION/approaches/opt_1/opt_summary.csv", "text/csv", csv);
  p2.s.addArtifact("j-opt", sid, "OPT_FILE", "05_opt/j-opt/HST_PHYSICSAI_OPTIMIZATION/run_log.txt", "text/plain", "HyperStudy optimization log (목)\nStarted run (1), model (m_1)\n…\nStarted run (25), model (m_1)\nFinished.\n");
  const fl = p2.s.addArtifact("j-opt", sid, "FILE_LIST", "05_opt/j-opt/file_list.json", "application/json", JSON.stringify({
    root: "HST_PHYSICSAI_OPTIMIZATION",
    truncated: false,
    files: [
      { rel: "HST_PHYSICSAI_OPTIMIZATION/approaches/opt_1/opt_summary.csv", size: csv.length },
      { rel: "HST_PHYSICSAI_OPTIMIZATION/run_log.txt", size: 2140 },
      { rel: "HST_PHYSICSAI_OPTIMIZATION/approaches/opt_1/study.hstx", size: 912_400 },
      { rel: "HST_PHYSICSAI_OPTIMIZATION/approaches/opt_1/run__00001/m_1/cushion_0000_pred.h3d", size: 41_200_000 },
    ],
  }));
  p2.opts.push({
    id: "opt-1", study_id: sid, job_id: "j-opt", status: "DONE", approach: "OPT", opt_method: "ARSM", max_designs: 25, model_id: "m-1", model_name: "cushion_TNS v1", param_set_id: "ps-1",
    study_folder: "HST_PHYSICSAI_OPTIMIZATION", runs_started: 25, responses, summary_status: "PARSED",
    summary_meta: { parser: "hst_csv", file_rel: "05_opt/j-opt/HST_PHYSICSAI_OPTIMIZATION/approaches/opt_1/opt_summary.csv", row_count: 25, columns: summary.columns },
    summary_artifact_id: sumId, file_count: 4, file_list_artifact_id: fl, folder_display_path: p2.s.disp(sid, "05_opt/j-opt"), created_by_name: "김연구", created_at: iso(60 + 10),
  });
}

export function precheckOptimize(s: Study, type: JobType, params: Record<string, unknown>): MockResp | null {
  if (type === "OPTIMIZE") {
    if (!params.model_id && !s.final_model_id) return err(409, "FINAL_MODEL_REQUIRED", "Final 모델을 먼저 지정하세요.");
    const rs = (params.responses as OptResponse[]) ?? [];
    if (!rs.length) return err(422, "RESPONSES_INVALID", "응답을 1개 이상 추가하세요.", { problems: [] });
    if (params.approach === "OPT" && !rs.some((r) => r.goal === "MINIMIZE" || r.goal === "MAXIMIZE"))
      return err(422, "OBJECTIVE_REQUIRED", "최적화에는 MINIMIZE 또는 MAXIMIZE 응답이 1개 이상 필요합니다.");
    const missing = rs.flatMap((r, i) => (r.goal === "CONSTRAINT" ? (["bound", "value"] as const).filter((k) => r[k] == null).map((k) => `responses.${i}.${k}`) : []));
    if (missing.length) return err(422, "OPT_CRITERIA_REQUIRED", "최적화 기준이 비어 있습니다 — 제약의 조건(≤·≥·=)과 임계값을 직접 입력하세요", { missing });
  }
  return null;
}

export function onCreateOptimize(p2: Phase2Mock, j: Job, me: { display_name: string }) {
  const p = j.params as Record<string, unknown>;
  const sid = j.study_id;
  const now = j.created_at;
  if (j.job_type === "OPTIMIZE") {
    const id = p2.s.nid("opt");
    p.optimization_id = id;
    const st = p2.s.studies.find((x) => x.id === sid)!;
    const mid = (p.model_id as string) || st.final_model_id || "m-1";
    const m = p2.s.models.find((x) => x.id === mid);
    p2.opts.unshift({
      id, study_id: sid, job_id: j.id, status: "RUNNING", approach: (p.approach as "OPT") ?? "OPT", opt_method: (p.opt_method as "ARSM") ?? "ARSM", max_designs: Number(p.max_designs ?? 25),
      model_id: mid, model_name: m ? `${m.name} v${m.version}` : mid, param_set_id: (p.param_set_id as string) || "ps-1", study_folder: String(p.study_folder ?? "HST_PHYSICSAI_OPTIMIZATION"),
      runs_started: null, responses: (p.responses as OptResponse[]) ?? [], summary_status: "NONE", summary_meta: null, summary_artifact_id: null, file_count: null, file_list_artifact_id: null,
      folder_display_path: p2.s.disp(sid, `05_opt/${j.id}`), created_by_name: me.display_name, created_at: now,
    });
  }
}

export function onProgressOptimize(p2: Phase2Mock, j: Job) {
  if (j.job_type === "OPTIMIZE") {
    const o = p2.opts.find((x) => x.job_id === j.id);
    if (o) {
      const n = Math.max(1, Math.floor(((j.progress_pct ?? 0) / 100) * o.max_designs));
      o.runs_started = n;
      j.progress_label = o.approach === "DOE" ? `run ${n} 시작` : `run ${n} / ${o.max_designs} 시작`;
      if (o.approach === "DOE") j.progress_pct = null;
    }
  }
}

/** ⑤ 완료 처리. OPTIMIZE가 아니면 undefined */
export function finishOptimize(p2: Phase2Mock, j: Job): "done" | undefined {
  if (j.job_type !== "OPTIMIZE") return undefined;
  const sid = j.study_id;
  const o = p2.opts.find((x) => x.job_id === j.id)!;
  const sm = optSummary(p2.s.idn, o.approach === "DOE" ? 12 : o.max_designs);
  o.status = "DONE";
  o.runs_started = sm.rows.length;
  o.summary_status = "PARSED";
  o.summary_artifact_id = p2.s.addArtifact(j.id, sid, "OPT_SUMMARY", `05_opt/${j.id}/summary.json`, "application/json", JSON.stringify(summaryJson(sm, "opt_summary.csv")));
  o.summary_meta = { parser: "hst_csv", file_rel: "opt_summary.csv", row_count: sm.rows.length, columns: sm.columns };
  o.file_list_artifact_id = p2.s.addArtifact(j.id, sid, "FILE_LIST", `05_opt/${j.id}/file_list.json`, "application/json", JSON.stringify({ root: o.study_folder, files: [{ rel: `${o.study_folder}/run_log.txt`, size: 900 }], truncated: false }));
  p2.s.addArtifact(j.id, sid, "OPT_FILE", `05_opt/${j.id}/${o.study_folder}/run_log.txt`, "text/plain", "Started run (1), model (m_1)\n");
  o.file_count = 1;
  j.progress_label = null;
  j.result = { runs_started: sm.rows.length, log_error_lines: 0 };
  return "done";
}

/** ⑤ 라우트: 최적화 단건, Study 최적화 목록·응답 후보 */
export const optimizeRoutes: Route = (srv, { method, seg }) => {
  const p2 = srv.p2;
  if (method === "GET" && seg[0] === "optimizations" && seg[1]) {
    const o = p2.opts.find((x) => x.id === seg[1]);
    return o ? ok(o) : err(404, "NOT_FOUND", "최적화를 찾을 수 없습니다.");
  }
  if (seg[0] === "studies" && seg[1]) {
    const s = p2.s.studies.find((x) => x.id === seg[1]);
    if (!s) return null;
    const sub = seg.slice(2).join("/");
    if (method === "GET" && sub === "optimizations") return ok(p2.opts.filter((x) => x.study_id === s.id));
    if (method === "GET" && sub === "optimize/response-candidates")
      return ok({
        source_job_id: "j-pred",
        h3d: { subcases: [{ id: 1, label: "Subcase 1", datatypes: [{ name: "Stress", components: ["vonMises", "P1 (major)"], layers: ["", "Max", "Min"], format: "tensor" }, { name: "Displacement", components: ["X", "Y", "Z", "Mag"], layers: [""], format: "vector" }] }] },
        xydata: { requests: { "Node 100": ["X", "Y", "Z"], "RBODY 1": ["F-Mag"] } },
      });
  }
  return null;
};
