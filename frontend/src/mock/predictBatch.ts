// phase3.md §14 S9 목: 조합 계산(batch_matrix 흉내)·미리보기·PREDICT_BATCH 생성·진행·하위 PREDICT·결과 표·CSV·커브·
// 일괄 취소·실패만 다시·템플릿 응답 저장. 배치 상태는 하위 작업(재시도 사슬 포함)에서 매번 계산한다(목 단순화).
// S12(§17.4): GET /predict-batches/{bid}/design-map — 완료 run의 curve.json 계열별 max·min·|max|, RESP(가짜 응답 함수의 _MAX·_MIN), 결과 표 값.
// 시드: s-cushion에 끝난 배치 B-002(20 run, 생성 실패 1·예측 실패 1). MockOptions.batchDemo="running"이면 진행 중 B-003도 넣는다(대기열에 하위 12개).
import type {
  BatchCurves,
  BatchPreviewRow,
  BatchNote,
  BatchProblem,
  BatchSampling,
  BatchRowState,
  BatchSource,
  BatchStatus,
  InputKind,
  Job,
  ParamSet,
  PredictBatch,
  PredictBatchRow,
  ResponseSpec,
  Study,
  TemplateResponse,
  ViewKey,
} from "../api/types";
import { downsampleMinMax } from "../lib/downsample";
import { isIntegerFormat } from "../lib/format";
import { PREVIEW_JSON, baseJob, contourSvg, curveJson, iso, makeSteps, responseFn, rng } from "./data";
import { err, needPower, ok, type MockResp, type Route } from "./route";
import { captureMedia } from "./capture";
import { isNewKind, mockBrief, mockDesign, mockSampling } from "./sampling";
import { isSamplingKind, recommendedCount } from "../lib/sampling";
import type { MockServer } from "./server";
import type { DesignMap, DesignMapCurveStats, DesignMapMetric, DesignMapRun } from "../api/designMap";

export const BATCH_MAX_RUNS = 200;
export const BATCH_TABLE_MAX_BYTES = 1048576;
export const CURVE_MAX_RUNS = 200;
const MAX_MULTI = 8;
const TERMINAL = ["SUCCEEDED", "FAILED", "CANCELED", "INTERRUPTED"];

type GenState = "PENDING" | "RUNNING" | "DONE" | "FAILED";
export interface BatchRunRec extends BatchPreviewRow {
  gen_state: GenState;
  gen_code: string | null;
  gen_message: string | null;
  predict_job_id: string | null;
}
export interface BatchRec {
  id: string;
  study_id: string;
  batch_no: number;
  job_id: string;
  param_set_id: string;
  model_id: string;
  input_kind: InputKind;
  /** DB source_kind(S15: 10종) */
  source_kind: string;
  /** source_meta(방식 인자·품질·이어서 추가 정보, §20.5) */
  meta: Record<string, unknown>;
  multi_execution: number;
  created_by: string;
  created_by_name: string;
  created_at: string;
  canceled: boolean;
  done_notified: boolean;
  runs: BatchRunRec[];
}

export const batchLabel = (no: number) => `B-${String(no).padStart(3, "0")}`;
export const batchRunKey = (n: number) => `run__${String(n).padStart(5, "0")}`;
const round4 = (v: number) => Number(v.toPrecision(6));

export function inputKindOf(ps: ParamSet): InputKind {
  return ps.input_kind ?? "assembly";
}

// ------------------------------------------------------------------ 조합 계산
function applyRows(ps: ParamSet, raw: { doe_no: number; values: Record<string, number> }[]): BatchPreviewRow[] {
  const ints = new Set(ps.tpl_params.filter((t) => isIntegerFormat(t.format)).map((t) => t.name));
  return raw.map(({ doe_no, values }) => {
    const applied: Record<string, number> = {};
    for (const p of ps.parameters) applied[p.name] = ints.has(p.name) ? Math.floor(values[p.name] + 0.5) : values[p.name];
    const out = ps.parameters.filter((p) => applied[p.name] < p.min || applied[p.name] > p.max).map((p) => p.name);
    return { doe_no, run_key: batchRunKey(doe_no), values, applied_values: applied, out_of_range: out };
  });
}

function lhs(ps: ParamSet, count: number, seed: number, ranges: Record<string, [number, number]>): BatchPreviewRow[] {
  const r = rng(seed * 7919 + 13);
  const cols: Record<string, number[]> = {};
  for (const p of ps.parameters) {
    const [lo, hi] = ranges[p.name] ?? [p.min, p.max];
    const perm = Array.from({ length: count }, (_, i) => i);
    for (let i = count - 1; i > 0; i--) {
      const j = Math.floor(r() * (i + 1));
      [perm[i], perm[j]] = [perm[j], perm[i]];
    }
    cols[p.name] = perm.map((k) => round4(lo + ((k + r()) / count) * (hi - lo)));
  }
  return applyRows(ps, Array.from({ length: count }, (_, i) => ({ doe_no: i + 1, values: Object.fromEntries(ps.parameters.map((p) => [p.name, cols[p.name][i]])) })));
}

function parseTable(ps: ParamSet, text: string): { rows: BatchPreviewRow[]; problems: BatchProblem[] } {
  if (new TextEncoder().encode(text).length > BATCH_TABLE_MAX_BYTES) return { rows: [], problems: [{ code: "TEXT_TOO_LARGE", message: "표가 1 MiB를 넘습니다" }] };
  const lines = text.replace(/^﻿/, "").split(/\r?\n/).filter((l) => l.trim());
  if (!lines.length) return { rows: [], problems: [{ code: "TOO_FEW_ROWS", message: "조합 행이 없습니다" }] };
  const sep = lines[0].includes("\t") ? "\t" : ",";
  const head = lines[0].split(sep).map((h) => h.trim());
  const names = ps.parameters.map((p) => p.name);
  const missing = names.filter((n) => !head.includes(n));
  const unknown = head.filter((h) => h.toLowerCase() !== "doe" && !names.includes(h));
  if (missing.length || unknown.length)
    return {
      rows: [],
      problems: [{ code: "TABLE_HEADER", message: `첫 줄은 파라미터 이름 전부여야 합니다${missing.length ? ` — 없음: ${missing.join(", ")}` : ""}${unknown.length ? ` — 모르는 열: ${unknown.join(", ")}` : ""}` }],
    };
  const problems: BatchProblem[] = [];
  const raw: { doe_no: number; values: Record<string, number> }[] = [];
  lines.slice(1).forEach((line, i) => {
    const cells = line.split(sep).map((c) => c.trim());
    const values: Record<string, number> = {};
    for (const n of names) {
      const v = Number(cells[head.indexOf(n)]);
      if (!Number.isFinite(v) || cells[head.indexOf(n)] === "") {
        problems.push({ code: "TABLE_VALUE", row: i + 1, message: `${i + 1}행 ${n} 값이 숫자가 아닙니다` });
        return;
      }
      values[n] = v;
    }
    raw.push({ doe_no: raw.length + 1, values });
  });
  if (!problems.length && raw.length < 1) problems.push({ code: "TOO_FEW_ROWS", message: "조합 행이 없습니다" });
  if (raw.length > BATCH_MAX_RUNS) problems.push({ code: "TOO_MANY_ROWS", message: `조합은 ${BATCH_MAX_RUNS}개까지입니다(${raw.length}개)` });
  return problems.length ? { rows: [], problems } : { rows: applyRows(ps, raw), problems };
}

export interface BatchMatrixOut {
  rows: BatchPreviewRow[];
  problems: BatchProblem[];
  notes?: BatchNote[];
  /** source_meta */
  meta?: Record<string, unknown>;
}

/** 새 7개 kind의 모양 오류(422 INVALID_PARAMS) — 서버 pydantic 흉내 */
function shapeError(source: BatchSource): MockResp | null {
  const s = source as Record<string, unknown>;
  if (s.kind === "fracfact" && s.resolution !== 4 && s.resolution !== 5) return err(422, "INVALID_PARAMS", "resolution은 4·5입니다.");
  if (s.kind === "ccd" && s.alpha !== "face" && s.alpha !== "inscribed") return err(422, "INVALID_PARAMS", "alpha는 face·inscribed입니다.");
  if (s.kind === "lhs_opt" && s.criterion !== "maximin" && s.criterion !== "corr") return err(422, "INVALID_PARAMS", "criterion은 maximin·corr입니다.");
  if ((s.kind === "sobol" || s.kind === "lhs_opt") && s.seed != null && (!Number.isInteger(s.seed) || (s.seed as number) < 0 || (s.seed as number) > 4294967295)) return err(422, "INVALID_PARAMS", "seed는 0~4294967295 정수입니다.");
  return null;
}

/** batch_matrix 흉내. 409 오류는 MockResp, 그 밖은 rows·problems(+notes·meta) */
export function batchMatrix(srv: MockServer, ps: ParamSet, source: BatchSource | undefined): MockResp | BatchMatrixOut {
  if (!source || typeof source !== "object") return err(422, "INVALID_PARAMS", "source가 필요합니다.");
  if (isNewKind(source.kind)) {
    const bad = shapeError(source);
    if (bad) return bad;
    const d = mockDesign(ps, source, BATCH_MAX_RUNS, srv.batches.filter((b) => b.study_id === ps.study_id));
    return { rows: applyRows(ps, d.rows), problems: d.problems, notes: d.notes, meta: d.meta };
  }
  if (source.kind === "lhs") {
    const count = Number(source.count);
    const seed = Number(source.seed ?? 1);
    if (!Number.isInteger(count) || !Number.isInteger(seed)) return err(422, "INVALID_PARAMS", "count·seed는 정수입니다.");
    if (count < 2) return { rows: [], problems: [{ code: "TOO_FEW_ROWS", message: "조합 수는 2개 이상입니다" }] };
    if (count > BATCH_MAX_RUNS) return { rows: [], problems: [{ code: "TOO_MANY_ROWS", message: `조합 수는 ${BATCH_MAX_RUNS}개까지입니다` }] };
    const ranges = (source.ranges ?? {}) as Record<string, [number, number]>;
    const bad = Object.entries(ranges).filter(([n, r]) => !ps.parameters.some((p) => p.name === n) || !Array.isArray(r) || !Number.isFinite(r[0]) || !Number.isFinite(r[1]) || !(r[0] < r[1]));
    if (bad.length) return { rows: [], problems: bad.map(([n]) => ({ code: "RANGE_INVALID", message: `${n} 범위는 최소 < 최대인 유한한 값이어야 합니다` })) };
    return { rows: lhs(ps, count, seed, ranges), problems: [], meta: { count, seed, ranges } };
  }
  if (source.kind === "table") return parseTable(ps, String(source.text ?? ""));
  if (source.kind === "train_doe") {
    const doe = srv.p2.does.find((d) => d.id === source.doe_id && d.study_id === ps.study_id);
    if (!doe || doe.status !== "READY") return err(409, "DOE_NOT_READY", "준비된 ① DOE가 아닙니다.");
    if (doe.sample_status !== "PARSED" && doe.sample_status !== "PARTIAL") return err(409, "SAMPLES_MISSING", "이 DOE에는 샘플 표가 없습니다.");
    const samples = srv.p2.doeSamples[doe.id] ?? [];
    const names = ps.parameters.map((p) => p.name).sort();
    const have = Object.keys(samples[0]?.values ?? {}).sort();
    if (names.join() !== have.join())
      return { rows: [], problems: [{ code: "DOE_PARAM_MISMATCH", message: `① DOE 파라미터(${have.join(", ")})가 템플릿 파라미터(${names.join(", ")})와 다릅니다` }] };
    return { rows: applyRows(ps, samples.map((s) => ({ doe_no: Number(/(\d+)$/.exec(s.run_key)?.[1] ?? 0), values: s.values }))), problems: [], meta: { doe_id: doe.id } };
  }
  return err(422, "INVALID_PARAMS", "source.kind를 확인하세요.");
}

const isResp = (x: unknown): x is MockResp => !!x && typeof x === "object" && "status" in x;

// ------------------------------------------------------------------ 배치 상태 계산
function latestJob(srv: MockServer, id: string | null): Job | null {
  let j = id ? srv.jobs.find((x) => x.id === id) ?? null : null;
  for (let k = 0; j && k < 20; k++) {
    const next = srv.jobs.find((x) => x.retry_of_job_id === j!.id);
    if (!next) break;
    j = next;
  }
  return j;
}

function rowState(srv: MockServer, b: BatchRec, r: BatchRunRec): { state: BatchRowState; job: Job | null } {
  const job = latestJob(srv, r.predict_job_id);
  if (job) {
    const s = job.state;
    return { state: s === "SUCCEEDED" ? "SUCCEEDED" : s === "RUNNING" || s === "COLLECTING" || s === "WAITING_HPC" ? "RUNNING" : s === "QUEUED" ? "QUEUED" : s === "CANCELED" ? "CANCELED" : "FAILED", job };
  }
  if (b.canceled && r.gen_state !== "FAILED") return { state: "CANCELED", job: null };
  return { state: r.gen_state === "RUNNING" ? "GENERATING" : r.gen_state === "FAILED" ? "GEN_FAILED" : r.gen_state === "DONE" ? "QUEUED" : "GEN_PENDING", job: null };
}

function parentJob(srv: MockServer, b: BatchRec): Job | undefined {
  return latestJob(srv, b.job_id) ?? undefined;
}

export function batchStatus(srv: MockServer, b: BatchRec): BatchStatus {
  if (b.canceled) return "CANCELED";
  const p = parentJob(srv, b);
  if (p && !TERMINAL.includes(p.state)) return "GENERATING";
  if (p && p.state !== "SUCCEEDED" && !b.runs.some((r) => r.predict_job_id)) return "FAILED";
  const states = b.runs.map((r) => rowState(srv, b, r).state);
  return states.some((s) => s === "QUEUED" || s === "RUNNING" || s === "GEN_PENDING" || s === "GENERATING") ? "PREDICTING" : "DONE";
}

function responsesOf(job: Job | null): Record<string, number | null> | null {
  if (!job || job.state !== "SUCCEEDED") return null;
  const t = (job.result as { response_table?: { name: string; predicted: number | null }[] } | null)?.response_table ?? [];
  return Object.fromEntries(t.map((x) => [x.name, x.predicted == null ? null : Number(x.predicted.toFixed(4))]));
}

/** §20.6 배치 상세·미리보기 sampling(등급은 서버가 정함 — 목은 §20.7 표 그대로) */
export function samplingOf(srv: MockServer, b: BatchRec): BatchSampling {
  const doe = b.source_kind === "TRAIN_DOE" ? srv.p2.does.find((d) => d.id === b.meta.doe_id) : undefined;
  // 최적화 소유 VERIFY·FINAL 배치는 kind보다 우선 reference(§20.7) — 목은 소유 배치를 만들지 않는다
  return mockSampling(b.source_kind, b.meta, { doeType: doe?.doe_type ?? null, doeOptions: doe?.options, });
}

export function batchOut(srv: MockServer, b: BatchRec): PredictBatch {
  const ps = srv.paramSets.find((p) => p.id === b.param_set_id)!;
  const model = srv.models.find((m) => m.id === b.model_id);
  const dir = srv.disp(b.study_id, `04_batch/${batchLabel(b.batch_no)}`);
  const rows: PredictBatchRow[] = b.runs.map((r) => {
    const { state, job } = rowState(srv, b, r);
    return {
      doe_no: r.doe_no, run_key: r.run_key, folder: `${dir}\\${r.run_key}`, values: r.values, applied_values: r.applied_values, out_of_range: r.out_of_range,
      state, code: state === "GEN_FAILED" ? r.gen_code : state === "FAILED" ? job?.failure_code ?? null : null,
      message: state === "GEN_FAILED" ? r.gen_message : state === "FAILED" ? job?.failure_message ?? null : null,
      job_id: job?.id ?? null, responses: responsesOf(job),
      media_views: job?.state === "SUCCEEDED" ? ((job.result as { media?: { view: string }[] | null } | null)?.media ?? []).map((m) => m.view) : [], // S10
    };
  });
  const cnt = (s: BatchRowState) => rows.filter((r) => r.state === s).length;
  const gen = { total: b.runs.length, done: b.runs.filter((r) => r.gen_state === "DONE").length, failed: b.runs.filter((r) => r.gen_state === "FAILED").length, running: b.runs.filter((r) => r.gen_state === "RUNNING").length, waiting: b.runs.filter((r) => r.gen_state === "PENDING").length };
  return {
    id: b.id, label: batchLabel(b.batch_no), status: batchStatus(srv, b), dir, input_kind: b.input_kind,
    param_set: { id: ps.id, label: ps.label ?? null }, model: { id: b.model_id, name: model ? `${model.name} v${model.version}` : b.model_id },
    job_id: parentJob(srv, b)?.id ?? b.job_id, multi_execution: b.multi_execution, gen,
    predict: { running: cnt("RUNNING"), queued: cnt("QUEUED"), succeeded: cnt("SUCCEEDED"), failed: cnt("FAILED"), canceled: cnt("CANCELED") },
    parameters: ps.parameters.map((p) => p.name), responses: ps.responses.map((r) => ({ name: r.name, unit: r.unit })), rows,
    source_kind: b.source_kind, sampling: samplingOf(srv, b), created_at: b.created_at, created_by_name: b.created_by_name, finished_at: null,
    can_cancel: ["GENERATING", "PREDICTING"].includes(batchStatus(srv, b)),
    can_retry_failed: rows.some((r) => r.state === "GEN_FAILED" || r.state === "FAILED" || r.state === "CANCELED"),
  };
}

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
  const m = batchMatrix(srv, ps, params.source as BatchSource);
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

// ------------------------------------------------------------------ 템플릿 응답
const NAME_RE = /^[A-Za-z][A-Za-z0-9_]*$/;
export function validateResponses(list: unknown): { problems: { code: string; message: string }[]; rows: TemplateResponse[] } {
  const problems: { code: string; message: string }[] = [];
  const rows = Array.isArray(list) ? (list as TemplateResponse[]) : [];
  const seen = new Set<string>();
  for (const r of rows) {
    const name = String(r?.name ?? "");
    if (!NAME_RE.test(name) || name.length > 64) problems.push({ code: "NAME", message: `이름 ${name || "(빈 값)"}: 영문자로 시작하는 영문·숫자·_` });
    if (seen.has(name.toLowerCase())) problems.push({ code: "DUPLICATE", message: `같은 이름이 있습니다: ${name}` });
    seen.add(name.toLowerCase());
    const sp = r?.spec as ResponseSpec | null | undefined;
    if (!sp) continue;
    if ([name, sp.datatype, sp.component, sp.layer, r.unit].some((v) => String(v ?? "").includes("|"))) problems.push({ code: "PIPE", message: `${name}: 문자 | 는 쓸 수 없습니다` });
    if (!["MAX", "MIN", "ABSMAX"].includes(sp.stat)) problems.push({ code: "STAT", message: `${name}: stat은 MAX·MIN·ABSMAX` });
    if (!Number.isInteger(sp.subcase) || sp.subcase < 1) problems.push({ code: "SUBCASE", message: `${name}: subcase는 1 이상 정수` });
    // D3-54: component는 선택(layer와 같은 규칙) — datatype만 필수
    if (!String(sp.datatype ?? "").trim()) problems.push({ code: "SPEC", message: `${name}: datatype이 필요합니다` });
  }
  return { problems, rows };
}

// ------------------------------------------------------------------ 시드
function seedBatch(srv: MockServer, no: number, count: number, opts: { running?: boolean; genFail?: number[]; predFail?: number[]; source?: BatchSource }) {
  const s = srv.studies.find((x) => x.id === "s-cushion")!;
  const ps = srv.paramSets.find((p) => p.id === "ps-1")!;
  // S15 시드: source를 주면 그 방식의 조합(mockDesign)으로 만든다(예: 화면 확인용 Sobol·Box–Behnken 배치)
  const design = opts.source && isNewKind(opts.source.kind) ? mockDesign(ps, opts.source, BATCH_MAX_RUNS, []) : null;
  const rows = design ? applyRows(ps, design.rows) : lhs(ps, count, no, {});
  const rec: BatchRec = {
    meta: design ? design.meta : { count, seed: no, ranges: Object.fromEntries(ps.parameters.map((p) => [p.name, [p.min, p.max]])) },
    id: `pb-${no}`, study_id: s.id, batch_no: no, job_id: `j-pb${no}`, param_set_id: ps.id, model_id: s.final_model_id ?? "m-2", input_kind: "assembly", source_kind: opts.source ? opts.source.kind.toUpperCase() : "LHS",
    multi_execution: 4, created_by: "u-power", created_by_name: "김연구", created_at: iso(opts.running ? 40 : 60 * 6), canceled: false, done_notified: true,
    runs: rows.map((r) => ({ ...r, gen_state: "DONE", gen_code: null, gen_message: null, predict_job_id: null })),
  };
  srv.batches.unshift(rec);
  const parent = baseJob({
    id: rec.job_id, study_id: s.id, project_id: s.project_id, study_title: s.title, job_type: "PREDICT_BATCH", state: "SUCCEEDED",
    created_at: rec.created_at, started_at: iso(opts.running ? 39 : 60 * 6 - 1), finished_at: iso(opts.running ? 27 : 60 * 6 - 13), progress_pct: 100,
    steps: makeSteps("PREDICT_BATCH", 3, null), params: { param_set_id: ps.id, model_id: null, multi_execution: 4, source: opts.source ?? { kind: "lhs", count, seed: no }, batch_id: rec.id, batch_no: no },
  });
  srv.jobs.push(parent);
  for (const n of opts.genFail ?? []) Object.assign(rec.runs[n - 1], { gen_state: "FAILED", gen_code: "OUTPUT_MISSING", gen_message: "m_1 EPS_mesh_0000.rad가 만들어지지 않았습니다" });
  finishBatchParent(srv, parent);
  const kids = rec.runs.map((r) => srv.jobs.find((x) => x.id === r.predict_job_id)).filter((x): x is Job => !!x);
  kids.forEach((c, i) => {
    srv.queueOrder.delete(c.id);
    const done = !opts.running || i < 7;
    c.created_at = iso(opts.running ? 27 - i * 0.01 : 60 * 6 - 13);
    if (done) {
      const fail = (opts.predFail ?? []).includes(rec.runs.find((r) => r.predict_job_id === c.id)!.doe_no);
      Object.assign(c, { state: fail ? "FAILED" : "SUCCEEDED", started_at: iso(60), finished_at: iso(59), progress_pct: 100, steps: makeSteps("PREDICT", fail ? 5 : 10, null, fail ? { failedIdx: 5 } : {}) });
      if (fail) Object.assign(c, { failure_code: "EXIT_NONZERO", failure_message: "edspy 종료코드 1" });
      else c.result = batchChildResult(srv, c);
    } else if (i === 7) Object.assign(c, { state: "RUNNING", started_at: iso(2), progress_pct: 40, steps: makeSteps("PREDICT", 5, 5) });
    else srv.queueOrder.set(c.id, ++srv.queueSeq);
  });
}

/** demo: "running" 진행 중 B-003 · "sobol" 끝난 Sobol 16개 B-003(이어서 추가 후보) · "bbd" 끝난 Box–Behnken B-003(⑤ 영향도 참고용 확인) */
export function seedBatches(srv: MockServer, demo?: "running" | "sobol" | "bbd") {
  seedBatch(srv, 2, 20, { genFail: [12], predFail: [5] });
  if (demo === "running") seedBatch(srv, 3, 20, { running: true });
  if (demo === "sobol") seedBatch(srv, 3, 16, { source: { kind: "sobol", count: 16, seed: 1, ranges: null, continue_from: null } });
  if (demo === "bbd") seedBatch(srv, 3, 25, { source: { kind: "bbd", ranges: null } });
}

// ------------------------------------------------------------------ 라우트
function csvOut(b: PredictBatch): string {
  const esc = (v: unknown) => {
    const t = v == null ? "" : String(v);
    return /[",\n]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t;
  };
  const head = ["doe_no", "run_key", "folder", ...b.parameters, ...b.responses.map((r) => r.name), "state"];
  const lines = b.rows.map((r) => [r.doe_no, r.run_key, r.folder, ...b.parameters.map((p) => r.applied_values[p]), ...b.responses.map((x) => r.responses?.[x.name] ?? ""), r.state].map(esc).join(","));
  return "﻿" + [head.join(","), ...lines].join("\n") + "\n";
}

function curvesOut(srv: MockServer, b: PredictBatch, name: string | null, maxPoints: number): BatchCurves {
  const done = b.rows.filter((r) => r.state === "SUCCEEDED" && r.job_id).sort((x, y) => x.doe_no - y.doe_no);
  const take = done.slice(0, CURVE_MAX_RUNS);
  const read = (jobId: string) => {
    const j = srv.jobs.find((x) => x.id === jobId);
    const aid = (j?.result as { curve_artifact_id?: string } | null)?.curve_artifact_id;
    const a = srv.artifacts.find((x) => x.id === aid);
    return a ? (JSON.parse(a.body) as { series: { name: string; x: number[]; y: number[] }[] }) : null;
  };
  const first = take[0] ? read(take[0].job_id!) : null;
  const names = first?.series.map((s) => s.name) ?? [];
  const pick = name && names.includes(name) ? name : names[0] ?? null;
  let downsampled = false;
  const series = take.flatMap((r) => {
    const c = read(r.job_id!)?.series.find((s) => s.name === pick);
    if (!c) return [];
    const d = downsampleMinMax(c.x, c.y, maxPoints);
    if (d.x.length < c.x.length) downsampled = true;
    return [{ doe_no: r.doe_no, run_key: r.run_key, x: d.x, y: d.y }];
  });
  return { names, name: pick, truncated: done.length > CURVE_MAX_RUNS, downsampled, series };
}

// ------------------------------------------------------------------ S12 설계공간 지도(백엔드 run_metrics·design_map 흉내)
const fin = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

export function curveStatsOf(series: { name: string; x: number[]; y: number[] }[]): Record<string, DesignMapCurveStats> {
  const out: Record<string, DesignMapCurveStats> = {};
  for (const s of series) {
    if (Object.keys(out).length >= 50) break;
    if (!s?.name || out[s.name] || !Array.isArray(s.y) || s.y.length !== s.x?.length || !s.y.length || ![...s.x, ...s.y].every(fin)) continue;
    let iMax = 0;
    let iMin = 0;
    s.y.forEach((v, i) => {
      if (v > s.y[iMax]) iMax = i;
      if (v < s.y[iMin]) iMin = i;
    });
    const [hi, lo] = [s.y[iMax], s.y[iMin]];
    out[s.name] = { max: hi, min: lo, absmax: Math.max(Math.abs(hi), Math.abs(lo)), x_at_max: s.x[iMax], x_at_min: s.x[iMin], n: s.y.length };
  }
  return out;
}

function designMapOut(srv: MockServer, b: PredictBatch): DesignMap {
  const ps = srv.paramSets.find((p) => p.id === b.param_set.id)!;
  const ints = new Set(ps.tpl_params.filter((t) => isIntegerFormat(t.format)).map((t) => t.name));
  const h3d = ps.responses.filter((r) => r.spec);
  const units = Object.fromEntries(ps.responses.map((r) => [r.name, r.unit || null]));
  const series: string[] = [];
  const respKeys = new Set<string>();
  const counts = { total: b.rows.length, succeeded: 0, no_curve: 0, no_resp: 0 };
  const runs: DesignMapRun[] = b.rows.map((r) => {
    const values = Object.fromEntries(b.parameters.filter((n) => fin(r.applied_values[n])).map((n) => [n, r.applied_values[n]]));
    const row: DesignMapRun = { doe_no: r.doe_no, run_key: r.run_key, state: r.state, values, curve: null, resp: null, tbl: null };
    if (r.state !== "SUCCEEDED" || !r.job_id) return row;
    counts.succeeded++;
    const j = srv.jobs.find((x) => x.id === r.job_id);
    const a = srv.artifacts.find((x) => x.id === (j?.result as { curve_artifact_id?: string } | null)?.curve_artifact_id);
    const cs = a ? curveStatsOf((JSON.parse(a.body) as { series: { name: string; x: number[]; y: number[] }[] }).series) : {};
    if (Object.keys(cs).length) {
      row.curve = cs;
      for (const k of Object.keys(cs)) if (!series.includes(k)) series.push(k);
    } else counts.no_curve++;
    if (h3d.length) {
      const pred = responseFn(r.applied_values);
      row.resp = Object.fromEntries(h3d.flatMap((x) => (fin(pred[x.name]) ? [[`${x.name}_MAX`, round4(pred[x.name])], [`${x.name}_MIN`, round4(pred[x.name] * 0.04)]] : [])));
      Object.keys(row.resp).forEach((k) => respKeys.add(k));
    } else counts.no_resp++;
    row.tbl = r.responses ?? {};
    return row;
  });
  const metrics: DesignMapMetric[] = [];
  if (series.length)
    metrics.push(
      { id: "curve:max", label: "커브 최대값", unit: null, needs_series: true },
      { id: "curve:min", label: "커브 최소값", unit: null, needs_series: true },
      { id: "curve:absmax", label: "커브 |최대|", unit: null, needs_series: true },
    );
  for (const k of [...respKeys].sort()) {
    const name = k.slice(0, k.lastIndexOf("_"));
    metrics.push({ id: `resp:${k}`, label: `${name} ${k.endsWith("_MAX") ? "최대" : "최소"}(RESP)`, unit: units[name] ?? null, needs_series: false });
  }
  if (!runs.some((x) => x.resp))
    for (const r of ps.responses)
      if (runs.some((x) => fin(x.tbl?.[r.name]))) metrics.push({ id: `tbl:${r.name}`, label: `${r.name}(결과 표)`, unit: r.unit || null, needs_series: false });
  return {
    batch_id: b.id, label: b.label, status: b.status,
    parameters: ps.parameters.map((p) => ({ name: p.name, integer: ints.has(p.name), min: p.min, max: p.max })),
    series, metrics, runs, counts,
  };
}

/** §14.7 일괄 예측 라우트 + PUT /param-sets/{id}/responses */
export const predictBatchRoutes: Route = (srv, { method, seg, query, body, me }) => {
  if (seg[0] === "studies" && seg[2] === "predict-batches") {
    const s = srv.studies.find((x) => x.id === seg[1]);
    if (!s) return err(404, "NOT_FOUND", "Study를 찾을 수 없습니다.");
    if (method === "GET" && !seg[3])
      return ok(srv.batches.filter((b) => b.study_id === s.id).map((b) => {
        const o = batchOut(srv, b); // D3-53 실행 목록: 템플릿·집계
        const r0 = o.responses[0];
        const vals = r0 ? o.rows.filter((r) => r.state === "SUCCEEDED").map((r) => r.responses?.[r0.name]).filter((v): v is number => typeof v === "number" && Number.isFinite(v)) : [];
        const response_summary = r0 && vals.length ? { name: r0.name, unit: r0.unit, min: Math.min(...vals), max: Math.max(...vals), count: vals.length } : null;
        return { id: b.id, label: batchLabel(b.batch_no), status: batchStatus(srv, b), run_count: b.runs.length, created_at: b.created_at, created_by_name: b.created_by_name, param_set: o.param_set, gen: o.gen, predict: o.predict, response_summary, sampling: mockBrief(b) };
      }));
    if (method === "POST" && seg[3] === "preview") {
      const ps = srv.paramSets.find((p) => p.id === body?.param_set_id && p.study_id === s.id);
      if (!ps) return err(409, "PREREQUISITE_MISSING", "템플릿을 먼저 등록하세요.", { missing: ["PARAM_SET"] });
      const m = batchMatrix(srv, ps, body?.source as BatchSource);
      if (isResp(m)) return m;
      const src = body?.source as BatchSource;
      const out: Record<string, unknown> = { input_kind: inputKindOf(ps), count: m.rows.length, estimate_min: m.rows.length ? Math.round(m.rows.length * 1.75) : null, rows: m.rows, problems: m.problems };
      const need = Math.max(5, ps.parameters.length + 2);
      const notes = [...(m.notes ?? [])];
      if (m.rows.length && m.rows.length < need) notes.push({ code: "INFLUENCE_TOO_FEW", message: `run이 ${need}개보다 적어 ⑤ 영향도는 계산되지 않습니다` });
      const act = (m.meta?.active as string[] | undefined)?.length ?? ps.parameters.length;
      const doe = src.kind === "train_doe" ? srv.p2.does.find((d) => d.id === src.doe_id) : undefined;
      out.notes = notes;
      out.sampling = mockSampling(src.kind.toUpperCase(), m.meta ?? {}, { recommended: isSamplingKind(src.kind) ? recommendedCount(src.kind, act, BATCH_MAX_RUNS) : null, doeType: doe?.doe_type ?? null, doeOptions: doe?.options });
      return ok(out);
    }
    return null;
  }
  if (seg[0] === "predict-batches" && seg[1]) {
    const b = srv.batches.find((x) => x.id === seg[1]);
    if (!b) return err(404, "BATCH_NOT_FOUND", "일괄 예측을 찾을 수 없습니다.");
    const s = srv.studies.find((x) => x.id === b.study_id)!;
    const out = batchOut(srv, b);
    if (method === "GET" && !seg[2]) return ok(out);
    if (method === "GET" && seg[2] === "table.csv") return { status: 200, text: csvOut(out), contentType: "text/csv; charset=utf-8" };
    if (method === "GET" && seg[2] === "design-map") return ok(designMapOut(srv, out));
    if (method === "GET" && seg[2] === "curves") return ok(curvesOut(srv, out, query.get("name"), Math.min(2000, Number(query.get("max_points") ?? 500))));
    const d = needPower(srv, s.project_id);
    if (d) return d;
    if (method === "POST" && seg[2] === "cancel") {
      if (!(me.is_global_admin || b.created_by === me.user_id)) return err(403, "PERMISSION_DENIED", "등록자 또는 관리자만 취소할 수 있습니다.", { required: "owner_or_global_admin" });
      if (out.status === "DONE" || out.status === "FAILED" || out.status === "CANCELED") return ok(out, 202);
      const ids = [out.job_id, ...out.rows.map((r) => r.job_id)].filter((x): x is string => !!x);
      for (const id of ids) {
        const j = srv.jobs.find((x) => x.id === id)!;
        if (TERMINAL.includes(j.state)) continue;
        if (j.state === "QUEUED") {
          j.state = "CANCELED";
          j.finished_at = new Date().toISOString();
          srv.queueOrder.delete(j.id);
        } else j.cancel_requested = true;
        srv.bump(j);
      }
      b.canceled = true;
      return ok(batchOut(srv, b), 202);
    }
    if (method === "POST" && seg[2] === "retry-failed") {
      if (out.status === "GENERATING") return err(409, "BATCH_ACTIVE", "입력 생성이 진행 중입니다.");
      b.canceled = false;
      let parent: string | null = null;
      if (b.runs.some((r) => r.gen_state === "FAILED")) {
        b.runs.forEach((r) => r.gen_state === "FAILED" && ((r.gen_code = "RETRY"), (r.gen_state = "PENDING")));
        const r = srv.createJob(s, "PREDICT_BATCH", { batch_id: b.id });
        if (r.status !== 201) return r;
        parent = (r.body as Job).id;
      }
      const retried: string[] = [];
      for (const row of out.rows) {
        if (!row.job_id || !["FAILED", "CANCELED"].includes(row.state)) continue;
        const r = srv.handle("POST", `/jobs/${row.job_id}/retry`, new URLSearchParams(), {}, new Headers({ "X-PhysicsAI-Request": "1" }));
        if (r.status === 201) retried.push((r.body as Job).id);
      }
      return ok({ parent_job_id: parent, retried_job_ids: retried }, 201);
    }
    return null;
  }
  if (method === "PUT" && seg[0] === "param-sets" && seg[1] && seg[2] === "responses") {
    const ps = srv.paramSets.find((p) => p.id === seg[1]);
    if (!ps) return err(404, "NOT_FOUND", "파라미터 세트를 찾을 수 없습니다.");
    const s = srv.studies.find((x) => x.id === ps.study_id)!;
    const d = needPower(srv, s.project_id);
    if (d) return d;
    const v = validateResponses(body?.responses);
    if (v.problems.length) return err(422, "RESPONSE_INVALID", "응답 정의를 확인하세요", { problems: v.problems });
    ps.responses = v.rows.map((r) => ({ name: r.name, unit: r.unit ?? "", spec: r.spec ?? null }));
    return ok(ps);
  }
  return null;
};
