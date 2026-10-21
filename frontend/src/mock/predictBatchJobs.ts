// phase3.md §14 S9 목(R-F 분할): PREDICT_BATCH 작업 생성·진행·부모 종료·하위 PREDICT 결과·컨투어 캡처.
import type { BatchSource, Job, Study, ViewKey } from "../api/types";
import { PREVIEW_JSON, baseJob, contourSvg, curveJson, responseFn } from "./data";
import { err, type MockResp } from "./route";
import { captureMedia } from "./capture";
import type { MockServer } from "./server";
import { MAX_MULTI, batchLabel, inputKindOf } from "./predictBatchRec";
import type { BatchRec } from "./predictBatchRec";
import { batchMatrix, isResp } from "./predictBatchMatrix";
import { runVars, snapshotOf } from "./nativeVars";
import { batchOut } from "./predictBatchOut";

// ------------------------------------------------------------------ 작업 생성·진행
export function isBatchChild(j: Job): boolean {
  return j.job_type === "PREDICT" && !!(j.params as { batch_run?: unknown }).batch_run;
}

/** POST jobs PREDICT_BATCH 사전 검사 → 저장할 params(batch_id·batch_no 확정) */
export function predictBatchCreate(srv: MockServer, s: Study, params: Record<string, unknown>): { error: MockResp } | { params: Record<string, unknown>; rec: BatchRec } {
  if (params.batch_id) {
    // 실패만 다시: 부모 재실행({batch_id}만)
    const b = srv.batches.find((x) => x.id === params.batch_id && x.study_id === s.id);
    if (!b) return { error: err(404, "BATCH_NOT_FOUND", "일괄 예측을 찾을 수 없습니다.") };
    return { params: { batch_id: b.id, batch_no: b.batch_no }, rec: b };
  }
  const ps = srv.paramSets.find((p) => p.id === params.param_set_id && p.study_id === s.id);
  if (!ps) return { error: err(409, "PREREQUISITE_MISSING", "템플릿을 먼저 등록하세요.", { missing: ["PARAM_SET"] }) };
  const kind = inputKindOf(ps);
  const feat = srv.p2.feature(kind === "mesh_only" ? "predict_mesh_only" : "predict_parametric");
  if (!feat.enabled) return { error: err(409, "TEMPLATE_NOT_CONFIGURED", "형상 갱신 설정이 필요합니다(관리자).", { missing: feat.missing }) };
  const modelId = (params.model_id as string | null) || s.final_model_id;
  if (!modelId) return { error: err(409, "FINAL_MODEL_REQUIRED", "Final 모델을 먼저 지정하세요.") };
  const multi = Number(params.multi_execution);
  if (!Number.isInteger(multi) || multi < 1 || multi > MAX_MULTI) return { error: err(422, "INVALID_PARAMS", `동시 실행 수는 1~${MAX_MULTI}입니다.`) };
  const cap = params.capture as { enabled?: unknown; views?: unknown; video?: unknown } | null | undefined;
  if (cap != null && (typeof cap.enabled !== "boolean" || (cap.views !== undefined && (!Array.isArray(cap.views) || !cap.views.length || new Set(cap.views).size !== cap.views.length)) || (cap.video !== undefined && typeof cap.video !== "boolean")))
    return { error: err(422, "INVALID_PARAMS", "capture를 확인하세요.") };
  const rv = runVars(srv, ps, params.vars as { add?: string[]; exclude?: string[] } | null | undefined, modelId);
  if (rv.error === "NATIVE_VARS_UNSUPPORTED") return { error: err(422, "NATIVE_VARS_UNSUPPORTED", "변수 추가·제외는 Native 템플릿에서만 쓸 수 있습니다") };
  const m = batchMatrix(srv, rv.out.ps, params.source as BatchSource);
  if (isResp(m)) return { error: m };
  if (m.problems.length || !m.rows.length) return { error: err(422, "BATCH_SOURCE_INVALID", "조합을 만들 수 없습니다", { problems: m.problems }) };
  const no = Math.max(0, ...srv.batches.filter((b) => b.study_id === s.id).map((b) => b.batch_no)) + 1;
  const me = srv.me!;
  const src = params.source as BatchSource;
  const rec: BatchRec = {
    id: srv.nid("pb"), study_id: s.id, batch_no: no, job_id: "", param_set_id: ps.id, model_id: modelId, input_kind: kind,
    source_kind: src.kind.toUpperCase(), meta: m.meta ?? {}, multi_execution: multi,
    created_by: me.user_id, created_by_name: me.display_name, created_at: new Date().toISOString(), canceled: false, done_notified: false,
    runs: m.rows.map((r) => ({ ...r, gen_state: "PENDING", gen_code: null, gen_message: null, predict_job_id: null })),
    ...(ps.engine === "native" ? { vars: snapshotOf(ps, rv.out) } : {}), // §4.1 스냅숏(Native만)
  };
  return { params: { ...params, model_id: params.model_id ?? null, batch_id: rec.id, batch_no: no }, rec };
}

export function onBatchJobCreated(srv: MockServer, j: Job, rec: BatchRec) {
  if (!srv.batches.includes(rec)) srv.batches.unshift(rec);
  rec.job_id = j.id;
  rec.canceled = false;
  rec.done_notified = false;
}

const recOf = (srv: MockServer, j: Job) => srv.batches.find((b) => b.id === (j.params as { batch_id?: string }).batch_id);

/** tick 중 진행: BP_GEN 구간에서 동시 M개씩 생성 완료 */
export function batchOnProgress(srv: MockServer, j: Job) {
  if (j.job_type !== "PREDICT_BATCH") return;
  const b = recOf(srv, j);
  if (!b) return;
  const todo = b.runs.filter((r) => r.gen_state !== "DONE" && r.gen_state !== "FAILED" || r.gen_state === "FAILED" && r.gen_code === "RETRY");
  const pct = j.progress_pct ?? 0;
  const k = Math.floor(Math.max(0, Math.min(1, (pct - 33) / 34)) * todo.length);
  todo.forEach((r, i) => (r.gen_state = i < k ? "DONE" : i < k + b.multi_execution && pct >= 33 ? "RUNNING" : "PENDING"));
  const failed = b.runs.filter((r) => r.gen_state === "FAILED").length;
  j.progress_label = `run ${b.runs.filter((r) => r.gen_state === "DONE").length}/${b.runs.length} 완료${failed ? ` · 실패 ${failed}` : ""}`;
}

/** 부모 완료: 남은 run 생성 완료 → 하위 PREDICT를 doe_no 순으로 연속 등록(BP_ENQUEUE) */
export function finishBatchParent(srv: MockServer, j: Job) {
  const b = recOf(srv, j);
  if (!b) return;
  for (const r of b.runs) if (r.gen_state !== "FAILED" || r.gen_code === "RETRY") (r.gen_state = "DONE"), (r.gen_code = null), (r.gen_message = null);
  const ps = srv.paramSets.find((p) => p.id === b.param_set_id)!;
  const dir = srv.disp(b.study_id, `04_batch/${batchLabel(b.batch_no)}`);
  for (const r of [...b.runs].sort((x, y) => x.doe_no - y.doe_no)) {
    if (r.gen_state !== "DONE" || r.predict_job_id) continue;
    const input = b.input_kind === "mesh_only" ? `${dir}\\${r.run_key}\\m_1\\EPS_mesh_0000.rad` : `${dir}\\${r.run_key}\\m_3`;
    const c = baseJob({
      id: srv.nid("j"), study_id: b.study_id, project_id: j.project_id, study_title: j.study_title, job_type: "PREDICT", state: "QUEUED",
      created_by: b.created_by, created_by_name: b.created_by_name, created_at: new Date().toISOString(),
      params: { input_mode: "prepared", input_path: input, input_kind: b.input_kind === "mesh_only" ? "file" : "dir", starter_name: b.input_kind === "mesh_only" ? "EPS_mesh_0000.rad" : ps.starter_name, model_id: b.model_id, param_set_id: b.param_set_id, batch_run: { batch_id: b.id, doe_no: r.doe_no } },
    });
    srv.jobs.push(c);
    srv.queueOrder.set(c.id, ++srv.queueSeq);
    r.predict_job_id = c.id;
  }
  j.result = { batch_id: b.id, run_count: b.runs.length, gen_done: b.runs.filter((r) => r.gen_state === "DONE").length, gen_failed: b.runs.filter((r) => r.gen_state === "FAILED").length };
}

/** 하위 PREDICT 결과(run 값으로 컨투어·커브·응답) */
export function batchChildResult(srv: MockServer, j: Job) {
  const br = (j.params as { batch_run: { batch_id: string; doe_no: number } }).batch_run;
  const b = srv.batches.find((x) => x.id === br.batch_id);
  const run = b?.runs.find((r) => r.doe_no === br.doe_no);
  const ps = srv.paramSets.find((p) => p.id === b?.param_set_id);
  const vals = run?.applied_values ?? {};
  const pred = responseFn(vals);
  const img = srv.addArtifact(j.id, j.study_id, "PREVIEW_IMAGE", `04_predict/${j.id}/contour.png`, "image/svg+xml", contourSvg(vals));
  const pj = srv.addArtifact(j.id, j.study_id, "PREVIEW_JSON", `04_predict/${j.id}/H3D_PREVIEW.json`, "application/json", JSON.stringify(PREVIEW_JSON));
  const cj = srv.addArtifact(j.id, j.study_id, "CURVE_JSON", `04_predict/${j.id}/curve.json`, "application/json", JSON.stringify(curveJson(vals)));
  return {
    model_id: (j.params as { model_id?: string }).model_id ?? b?.model_id, param_set_id: b?.param_set_id ?? null, input_mode: "prepared" as const,
    input_path: (j.params as { input_path?: string }).input_path ?? null, values: run?.values ?? {}, applied_values: vals, out_of_range: run?.out_of_range ?? [], nearest: null,
    preview_json_artifact_id: pj, image_artifact_ids: [img], curve_artifact_id: cj, response_table_artifact_id: null,
    response_table: (ps?.responses ?? []).map((r) => ({ name: r.name, unit: r.unit, predicted: pred[r.name] ?? null, nearest_measured: null, diff_pct: null })),
    media: batchCapture(srv, j, b?.job_id, vals), // S10 + D3-53 배치 캡처 옵션
  };
}

/** D3-53: 배치 params.capture — enabled false면 캡처 SKIPPED(media 빈 목록), views가 있으면 그 방향만 */
function batchCapture(srv: MockServer, j: Job, parentId: string | undefined, vals: Record<string, number>) {
  const parent = srv.jobs.find((x) => x.id === parentId);
  const cap = (parent?.params as { capture?: { enabled: boolean; views?: ViewKey[] } } | undefined)?.capture;
  if (cap && !cap.enabled) {
    srv.mediaInfo.set(j.id, { status: "DISABLED", message: "일괄 예측 설정에서 컨투어 캡처를 껐습니다" });
    return [];
  }
  return captureMedia(srv, j, vals, cap?.views ?? null);
}

/** 하위 종료 뒤: 모두 끝났으면 완료 알림 1건 */
export function batchAfterChild(srv: MockServer, j: Job) {
  const id = (j.params as { batch_run?: { batch_id: string } }).batch_run?.batch_id;
  const b = srv.batches.find((x) => x.id === id);
  if (!b) return;
  const out = batchOut(srv, b);
  if (out.status !== "DONE") return void (b.done_notified = false);
  if (b.done_notified) return;
  b.done_notified = true;
  const failed = out.rows.filter((r) => r.state !== "SUCCEEDED").length;
  srv.notify(b.created_by, "PREDICT_BATCH_DONE", srv.jobs.find((x) => x.id === b.job_id) ?? null, `일괄 예측 ${out.label} 완료 — 완료 ${out.predict.succeeded} · 실패 ${failed}`);
}
