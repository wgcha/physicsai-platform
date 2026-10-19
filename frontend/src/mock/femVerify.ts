// S16 V2 목(phase3 §21.3): 조립 상태 FEM 검증. fem-verifications preview·create·list·get·media·curves·table.csv·cancel·rerun.
// 상태 갱신은 작업 상태(PREDICT 동반 예측·FEM_VERIFY)에서 syncFem이 계산한다(틱·조회 때마다, 멱등) — 종료 훅 흉내.
// 경로 이름으로 조립 원본 시나리오를 고른다: nostarter → starter 0개, two → 2개(ASSEM_STARTER_COUNT), huge → ASSEM_TOO_LARGE,
//   nocsv·noinc·noref → 경고 RENUM_CSV_MISSING·MESH_INCLUDE_NOT_IN_ASSEM·MESH_INCLUDE_NOT_REFERENCED. 허용 루트 = AI_WORK 또는 SPDM 루트(S:\SPDM, 읽기 전용).
// MockOptions.femVerify = "demo" → FV-001 완료(⑤ 배치 run)·FV-002 실패(starter 2개)·FV-003 동반 예측 대기.
import type { Job, ParamSet, Study } from "../api/types";
import type { FemCompare, FemMedia, FemProblem, FemVerification, FemVerifySummary, FvStatus } from "../api/femVerify";
import { baseJob, iso, makeSteps } from "./data";
import { curveJson, responseFn } from "./data";
import { contourPng } from "./png";
import { file as mediaFile } from "./capture";
import { err, needPower, ok, type MockResp, type Route } from "./route";
import type { MockServer } from "./server";
import { batchLabel, isBatchChild } from "./predictBatch";
import { inspectPath } from "./studies";
import { DEFAULT_VIEWS, viewLabel } from "../lib/views";
import { JOB_STATE_LABEL } from "../lib/format";

type SourceKind = FemVerifySummary["source_kind"];
const MAX_ACTIVE = 4;
export const MOCK_SPDM_ROOT = "S:\\SPDM\\cushion";

export interface FemRec {
  id: string;
  study_id: string;
  fv_no: number;
  source_kind: SourceKind;
  source_label: string;
  links: FemVerifySummary["links"];
  predict_job_id: string | null;
  companion: boolean;
  param_set_id: string | null;
  model_id: string | null;
  values: Record<string, number>;
  applied_values: Record<string, number>;
  out_of_range: string[];
  assem_kind: "PREDICT_INPUT" | "TRAIN_DOE" | "CUSTOM";
  assem_label: string;
  assem_path: string | null;
  input_mode: "reuse" | "rebuild";
  hpc_mode: "command" | "scx";
  status: FvStatus;
  job_id: string | null;
  attempt_no: number;
  compare: FemCompare | null;
  failure: FemProblem | null;
  warnings: FemProblem[];
  media: { view: string; pred: [string, string | null]; fem: [string, string | null] }[];
  created_by: string;
  created_by_name: string;
  created_at: string;
  finished_at: string | null;
  notified: boolean;
}

export const fvLabel = (no: number) => `FV-${String(no).padStart(3, "0")}`;
const TERMINAL = ["SUCCEEDED", "FAILED", "CANCELED", "INTERRUPTED"];
const md = (iso_: string) => {
  const d = new Date(iso_);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
};

// ------------------------------------------------------------------ 작업 사슬
function latest(srv: MockServer, id: string | null): Job | null {
  let j = id ? srv.jobs.find((x) => x.id === id) ?? null : null;
  for (let k = 0; j && k < 50; k++) {
    const next = srv.jobs.find((x) => x.retry_of_job_id === j!.id);
    if (!next) break;
    j = next;
  }
  return j;
}

function newJob(srv: MockServer, s: Study, type: "PREDICT" | "FEM_VERIFY", params: Record<string, unknown>, by: { id: string; name: string }, retryOf: string | null = null): Job {
  const j = baseJob({ id: srv.nid("j"), study_id: s.id, project_id: s.project_id, study_title: s.title, job_type: type, state: "QUEUED", created_by: by.id, created_by_name: by.name, created_at: new Date().toISOString(), params, retry_of_job_id: retryOf });
  srv.jobs.push(j);
  srv.queueOrder.set(j.id, ++srv.queueSeq);
  return j;
}

// ------------------------------------------------------------------ 출처 해석
interface Resolved {
  kind: SourceKind;
  label: string;
  links: FemRec["links"];
  ps: ParamSet | null;
  modelId: string | null;
  values: Record<string, number>;
  applied: Record<string, number>;
  outOfRange: string[];
  predict: Job | null;
  /** 같은 설계점·모델의 성공 예측이 없어 동반 예측을 만들어야 하는 경우의 params 재료 */
  needsCompanion: boolean;
  inputIsAssembly: boolean;
  meshAvailable: boolean;
  meshOnly: boolean;
}
type Problem = FemProblem;

function applyInts(ps: ParamSet, values: Record<string, number>) {
  const ints = new Set(ps.tpl_params.filter((t) => /^%[-0-9.]*[id]$/.test(t.format)).map((t) => t.name));
  const applied = { ...values };
  for (const n of ints) if (Number.isFinite(applied[n])) applied[n] = Math.floor(applied[n] + 0.5);
  const out = ps.parameters.filter((p) => values[p.name] < p.min || values[p.name] > p.max).map((p) => p.name);
  return { applied, out };
}

const sameValues = (a: Record<string, number>, b: Record<string, number>) => Object.keys(a).length === Object.keys(b).length && Object.keys(a).every((k) => Math.abs((a[k] ?? NaN) - (b[k] ?? NaN)) <= 1e-9);

function fromJob(srv: MockServer, s: Study, j: Job, kind: SourceKind, label: string, links: FemRec["links"], problems: Problem[]): Resolved {
  const p = j.params as { input_mode?: string; param_set_id?: string | null; values?: Record<string, number>; model_id?: string | null; batch_run?: unknown };
  const r = (j.result ?? {}) as { applied_values?: Record<string, number>; out_of_range?: string[]; model_id?: string };
  if (j.state !== "SUCCEEDED") problems.push({ code: "PREDICT_NOT_SUCCEEDED", message: "성공한 예측만 검증할 수 있습니다" });
  const prepared = p.input_mode === "prepared";
  const ps = srv.paramSets.find((x) => x.id === (p.param_set_id ?? (prepared ? null : r && (r as { param_set_id?: string }).param_set_id))) ?? null;
  const meshOnly = ps?.input_kind === "mesh_only" && !prepared;
  return {
    kind, label, links, ps, modelId: p.model_id ?? r.model_id ?? s.final_model_id ?? null, values: prepared ? {} : (p.values ?? {}), applied: r.applied_values ?? p.values ?? {}, outOfRange: r.out_of_range ?? [],
    predict: j, needsCompanion: false, inputIsAssembly: !meshOnly, meshAvailable: !(prepared && !p.batch_run), meshOnly,
  };
}

function resolveValues(srv: MockServer, s: Study, a: { param_set_id: string; model_id?: string | null; values: Record<string, number>; reuse_existing?: boolean }, label: string, kind: SourceKind, links: FemRec["links"]): Resolved | MockResp {
  const ps = srv.paramSets.find((x) => x.id === a.param_set_id && x.study_id === s.id);
  if (!ps) return err(422, "INVALID_PARAMS", "템플릿을 찾을 수 없습니다.");
  const miss = ps.parameters.filter((p) => !Number.isFinite(a.values?.[p.name]));
  if (miss.length) return err(422, "INVALID_PARAMS", `모든 파라미터 값이 필요합니다(${miss.map((m) => m.name).join(", ")}).`);
  const modelId = a.model_id || s.final_model_id;
  if (!modelId) return err(409, "FINAL_MODEL_REQUIRED", "Final 모델을 먼저 지정하세요.");
  const { applied, out } = applyInts(ps, a.values);
  const reuse = a.reuse_existing !== false
    ? [...srv.jobs].reverse().find((j) => j.study_id === s.id && j.job_type === "PREDICT" && j.state === "SUCCEEDED" && !isBatchChild(j) && (j.params as { input_mode?: string }).input_mode !== "prepared" && (j.params as { param_set_id?: string }).param_set_id === ps.id &&
        ((j.params as { model_id?: string | null }).model_id || s.final_model_id) === modelId && sameValues((j.result as { applied_values?: Record<string, number> } | null)?.applied_values ?? {}, applied))
    : undefined;
  const meshOnly = ps.input_kind === "mesh_only";
  return { kind, label, links, ps, modelId, values: a.values, applied, outOfRange: out, predict: reuse ?? null, needsCompanion: !reuse, inputIsAssembly: !meshOnly, meshAvailable: true, meshOnly };
}

function resolveSource(srv: MockServer, s: Study, src: Record<string, unknown>, problems: Problem[]): Resolved | MockResp {
  const none = { predict_job_id: null, batch_id: null, doe_no: null, opt_id: null };
  switch (src.kind) {
    case "predict_job": {
      const j = srv.jobs.find((x) => x.id === src.job_id && x.study_id === s.id && x.job_type === "PREDICT");
      if (!j) return err(422, "FEM_VERIFY_INVALID", "검증 요청을 확인하세요.", { problems: [{ code: "SOURCE_NOT_FOUND", message: "예측 작업을 찾을 수 없습니다" }] });
      const br = (j.params as { batch_run?: { batch_id: string; doe_no: number } }).batch_run;
      const b = br ? srv.batches.find((x) => x.id === br.batch_id) : null;
      const label = b && br ? `${batchLabel(b.batch_no)} DOE #${br.doe_no}` : `④ 예측 ${md(j.created_at)}`;
      return fromJob(srv, s, j, "PREDICT_JOB", label, { predict_job_id: j.id, batch_id: br?.batch_id ?? null, doe_no: br?.doe_no ?? null, opt_id: null }, problems);
    }
    case "batch_run": {
      const b = srv.batches.find((x) => x.id === src.batch_id && x.study_id === s.id);
      const run = b?.runs.find((r) => r.doe_no === Number(src.doe_no));
      if (!b || !run) return err(422, "FEM_VERIFY_INVALID", "검증 요청을 확인하세요.", { problems: [{ code: "SOURCE_NOT_FOUND", message: "배치 run을 찾을 수 없습니다" }] });
      const j = latest(srv, run.predict_job_id);
      if (!j) return err(422, "FEM_VERIFY_INVALID", "검증 요청을 확인하세요.", { problems: [{ code: "PREDICT_NOT_SUCCEEDED", message: "성공한 예측만 검증할 수 있습니다" }] });
      const r = fromJob(srv, s, j, "BATCH_RUN", `${batchLabel(b.batch_no)} DOE #${run.doe_no}`, { predict_job_id: j.id, batch_id: b.id, doe_no: run.doe_no, opt_id: null }, problems);
      const ps = srv.paramSets.find((x) => x.id === b.param_set_id) ?? r.ps;
      return { ...r, ps, values: run.values ?? r.values, inputIsAssembly: b.input_kind !== "mesh_only", meshOnly: b.input_kind === "mesh_only" };
    }
    case "values": {
      const label = `템플릿 값 ${Object.entries(src.values as Record<string, number>).slice(0, 2).map(([k, v]) => `${k}=${v}`).join(", ")}`;
      return resolveValues(srv, s, src as never, label, "VALUES", none);
    }
    case "opt_design": {
      const o = srv.surrogate.find((x) => x.id === src.opt_id && x.study_id === s.id);
      if (!o) return err(404, "NOT_FOUND", "내장 최적화를 찾을 수 없습니다.");
      const pool = o.runs.filter((r) => r.objective != null);
      const feas = pool.filter((r) => r.feasible);
      const sign = o.settings.objective.sense === "max" ? -1 : 1;
      const cand = feas.length ? feas : pool;
      const best = cand.length ? cand.reduce((a, b) => (sign * (b.objective as number) < sign * (a.objective as number) ? b : a)) : null;
      let run = best;
      let tag = "최적 설계";
      if (src.pick === "run") {
        run = o.runs.find((r) => r.iter_no === src.iter_no && r.doe_no === src.doe_no) ?? null;
        tag = `반복 ${src.iter_no} · DOE #${src.doe_no}`;
      } else if (src.pick === "final_optimum") tag = "최적안(마무리)";
      else if (src.pick === "surrogate_optimum") tag = "대리모델 예측 최적안";
      if (!run) return err(422, "FEM_VERIFY_INVALID", "검증 요청을 확인하세요.", { problems: [{ code: "OPT_DESIGN_UNAVAILABLE", message: "이 최적화에는 검증할 설계가 없습니다" }] });
      return resolveValues(srv, s, { param_set_id: o.param_set_id, values: run.values as Record<string, number> }, `내장 최적화 SO-${String(o.opt_no).padStart(3, "0")} ${tag}`, "OPT_DESIGN", { ...none, opt_id: o.id });
    }
    default:
      return err(422, "INVALID_PARAMS", "source.kind를 확인하세요.");
  }
}

// ------------------------------------------------------------------ 조립 원본
function plan(label: string, path: string, over: Record<string, unknown> = {}) {
  return { label, path, starter: "Face_Drop_0000.rad", rad: ["Face_Drop_0000.rad", "Face_Drop_0001.rad"], inc_count: 12, renum_csv: true, include_baseline: true, include_referenced: true, file_count: 31, total_bytes: 182_736_451, ...over };
}

/** paths/inspect FEM_ASSEMBLY·custom 미리보기 공용: 경로 시나리오 → 계획 + 문제·경고 */
export function assemblyPlanFor(path: string): { plan: ReturnType<typeof plan> & { problems: Problem[]; warnings: Problem[] }; error?: MockResp } {
  const warnings: Problem[] = [];
  const problems: Problem[] = [];
  const over: Record<string, unknown> = {};
  if (/nostarter/i.test(path)) {
    over.starter = null;
    problems.push({ code: "ASSEM_STARTER_COUNT", message: "starter(*_0000.rad)가 정확히 1개 있어야 합니다(현재 0개)" });
  } else if (/two/i.test(path)) {
    over.starter = null;
    over.starter_candidates = ["Face_Drop_0000.rad", "Side_Drop_0000.rad"];
    problems.push({ code: "ASSEM_STARTER_COUNT", message: "starter(*_0000.rad)가 정확히 1개 있어야 합니다(현재 2개: Face_Drop_0000.rad, Side_Drop_0000.rad)" });
  }
  if (/huge/i.test(path)) {
    over.total_bytes = 2_147_483_649;
    problems.push({ code: "ASSEM_TOO_LARGE", message: "조립 원본 파일 합계가 2 GiB를 넘습니다" });
  }
  if (/nocsv/i.test(path)) {
    over.renum_csv = false;
    warnings.push({ code: "RENUM_CSV_MISSING", message: "RENUM csv가 없습니다 — 번호 재배열 없이 조립합니다" });
  }
  if (/noinc/i.test(path)) {
    over.include_baseline = false;
    over.include_referenced = null;
    warnings.push({ code: "MESH_INCLUDE_NOT_IN_ASSEM", message: "조립 폴더에 교체할 메시 include 기준본이 없습니다" });
  } else if (/noref/i.test(path)) {
    over.include_referenced = false;
    warnings.push({ code: "MESH_INCLUDE_NOT_REFERENCED", message: "starter가 메시 include(104_replace_node_elem.inc)를 참조하지 않습니다" });
  }
  return { plan: { ...plan("직접 지정", path, over), problems, warnings } as never };
}

function checkCustomPath(path: string): MockResp | null {
  if (!path.trim()) return err(422, "PATH_NOT_FOUND", "경로를 입력하세요.");
  if (path.toLowerCase().startsWith(MOCK_SPDM_ROOT.toLowerCase())) {
    if (/\s|[&|<>^%!"]/.test(path)) return err(422, "PATH_UNSAFE", "경로에 공백이나 특수문자를 쓸 수 없습니다.");
    return null;
  }
  const r = inspectPath("RADIOSS_ASSEM", path);
  return r.status === 200 ? null : r;
}

// ------------------------------------------------------------------ 미리보기·생성
type Body = Record<string, unknown>;

function previewOf(srv: MockServer, s: Study, body: Body): { error: MockResp } | { out: Record<string, unknown>; res: Resolved; assem: FemRec["assem_kind"]; assemLabel: string; assemPath: string | null; inputMode: "reuse" | "rebuild"; warnings: Problem[] } {
  if (srv.hpcMode === "none") return { error: err(409, "HPC_NOT_CONFIGURED", "해석 연결(PBS·SCX)이 설정되지 않았습니다.") };
  if (!srv.p2.feature("fem_verify").enabled) return { error: err(409, "FEATURE_NOT_AVAILABLE", "FEM 검증을 쓸 수 없습니다(관리자 설정 필요).", { missing: srv.p2.feature("fem_verify").missing }) };
  const problems: Problem[] = [];
  const warnings: Problem[] = [];
  const res = resolveSource(srv, s, (body.source ?? {}) as Body, problems);
  if ("status" in res) return { error: res };
  const req = (body.assembly ?? null) as Body | null;
  const does = srv.p2.does.filter((d) => d.study_id === s.id && d.status === "READY").sort((a, b) => b.created_at.localeCompare(a.created_at));
  let kind: FemRec["assem_kind"];
  let label = "";
  let path: string | null = null;
  let pl: ReturnType<typeof assemblyPlanFor>["plan"] | null = null;
  const root = res.predict ? (latest(srv, res.predict.id)?.id ?? res.predict.id) : "(예정)";
  const chosen = req?.kind ?? (res.inputIsAssembly ? "predict_input" : does.length ? "train_doe" : null);
  if (chosen === null) {
    problems.push({ code: "ASSEMBLY_REQUIRED", message: "조립 원본을 고르세요" });
    kind = "TRAIN_DOE";
  } else if (chosen === "predict_input") {
    kind = "PREDICT_INPUT";
    label = "예측 입력 그대로";
    path = srv.disp(s.id, `04_predict/${root}/INPUT`);
    if (!res.inputIsAssembly) problems.push({ code: "INPUT_MESH_ONLY", message: "이 예측 입력은 쿠션 메시뿐이라 그대로 해석할 수 없습니다 — 조립 원본을 고르세요" });
    pl = { ...plan(label, path), problems: [], warnings: [] } as never;
  } else if (chosen === "train_doe") {
    kind = "TRAIN_DOE";
    const doe = does.find((d) => d.id === req?.doe_id) ?? (req?.doe_id ? undefined : does[0]);
    if (!doe) problems.push({ code: "DOE_NOT_READY", message: "준비된 ① DOE가 아닙니다" });
    else {
      label = doeLabel(srv, doe.id);
      path = srv.disp(s.id, `01_train/doe/${doe.id}/radioss_assem`);
      pl = { ...plan(label, path), problems: [], warnings: [] } as never;
      const have = Object.keys(srv.p2.doeSamples[doe.id]?.[0]?.values ?? {}).sort().join();
      if (res.ps && have && have !== res.ps.parameters.map((p) => p.name).sort().join()) warnings.push({ code: "DOE_PARAM_MISMATCH", message: "① DOE 파라미터가 템플릿 파라미터와 다릅니다(조립 폴더만 사용)" });
    }
  } else {
    kind = "CUSTOM";
    label = "직접 지정";
    path = String(req?.path ?? "");
    const bad = checkCustomPath(path);
    if (bad) return { error: bad };
    const a = assemblyPlanFor(path);
    pl = a.plan;
    problems.push(...a.plan.problems);
    warnings.push(...a.plan.warnings);
  }
  const inputMode: "reuse" | "rebuild" = kind === "PREDICT_INPUT" ? "reuse" : "rebuild";
  if (inputMode === "rebuild") {
    if (!res.meshAvailable) problems.push({ code: "MESH_MISSING", message: "예측 폴더에 형상 메시가 없습니다(정리됨 또는 준비된 입력)" });
    if (!srv.p2.feature("fem_verify_rebuild").enabled) return { error: err(409, "TEMPLATE_NOT_CONFIGURED", "형상 갱신 설정이 필요합니다(관리자).", { missing: srv.p2.feature("fem_verify_rebuild").missing }) };
  }
  if (res.meshOnly) warnings.push({ code: "FEM_RESPONSE_WHOLE_MODEL", message: "FEM 응답은 조립 전체 모델의 최솟값·최댓값입니다(쿠션만 한정 불가) — 컨투어를 함께 보세요" });
  if (res.outOfRange.length) warnings.push({ code: "OUT_OF_RANGE", message: "학습 범위 밖 값이 있습니다" });
  const model = srv.models.find((m) => m.id === res.modelId);
  const out = {
    source_label: res.label,
    design: {
      param_set: res.ps ? { id: res.ps.id, label: res.ps.label ?? (res.ps.source_path.split(/[\\/]/).filter(Boolean).pop() ?? null), input_kind: res.ps.input_kind } : null,
      model: model ? { id: model.id, name: model.name, version: model.version } : null,
      values: res.values, applied_values: res.applied, out_of_range: res.outOfRange,
    },
    predict: { job_id: res.predict?.id ?? null, state: res.predict?.state ?? null, reuse: !!res.predict, will_run: res.needsCompanion, created_at: res.predict?.created_at ?? null },
    input_mode: inputMode,
    mesh: inputMode === "rebuild" ? { path: srv.disp(s.id, `04_predict/${root}/geom/EPS_mesh_0000.rad`), available: res.meshAvailable } : null,
    assembly: pl ? { kind: kind.toLowerCase(), ...pl } : null,
    fem_field: "CornerStress",
    comps_auto: res.meshOnly ? ["3000001"] : [],
    hpc_mode: srv.hpcMode === "scx" ? "scx" : "command",
    problems,
    warnings,
  };
  return { out, res, assem: kind, assemLabel: label, assemPath: path, inputMode, warnings };
}

function doeLabel(srv: MockServer, doeId: string): string {
  const all = [...srv.p2.does].sort((a, b) => a.created_at.localeCompare(b.created_at));
  const i = all.findIndex((d) => d.id === doeId);
  return `DOE-${String(i + 1).padStart(3, "0")}`;
}

function activeOf(r: FemRec) {
  return r.status === "WAITING_PREDICT" || r.status === "RUNNING";
}

function createRec(srv: MockServer, s: Study, body: Body, by: { id: string; name: string }): MockResp {
  if (s.status !== "ACTIVE") return err(409, "STUDY_ARCHIVED", "보관된 Study입니다.");
  const p = previewOf(srv, s, body);
  if ("error" in p) return p.error;
  const problems = p.out.problems as Problem[];
  if (problems.length) return err(422, "FEM_VERIFY_INVALID", "검증 요청을 확인하세요.", { problems });
  const act = srv.fems.filter((r) => r.study_id === s.id && activeOf(r));
  if (act.some((r) => p.res.predict && r.predict_job_id === p.res.predict.id && r.assem_kind === p.assem && r.assem_path === p.assemPath)) return err(409, "FEM_VERIFY_ACTIVE", "같은 예측·같은 조립 원본의 검증이 진행 중입니다");
  if (act.length >= MAX_ACTIVE) return err(409, "FEM_VERIFY_LIMIT", `진행 중인 FEM 검증이 ${act.length}건입니다(상한 ${MAX_ACTIVE})`);
  const no = Math.max(0, ...srv.fems.filter((r) => r.study_id === s.id).map((r) => r.fv_no)) + 1;
  const res = p.res;
  const rec: FemRec = {
    id: srv.nid("fv"), study_id: s.id, fv_no: no, source_kind: res.kind, source_label: res.label, links: res.links, predict_job_id: res.predict?.id ?? null, companion: res.needsCompanion,
    param_set_id: res.ps?.id ?? null, model_id: res.modelId, values: res.values, applied_values: res.applied, out_of_range: res.outOfRange,
    assem_kind: p.assem, assem_label: p.assemLabel, assem_path: p.assemPath, input_mode: p.inputMode, hpc_mode: srv.hpcMode === "scx" ? "scx" : "command",
    status: "RUNNING", job_id: null, attempt_no: 1, compare: null, failure: null, warnings: p.warnings, media: [],
    created_by: by.id, created_by_name: by.name, created_at: new Date().toISOString(), finished_at: null, notified: false,
  };
  srv.fems.push(rec);
  if (res.needsCompanion) {
    const pp = { param_set_id: res.ps!.id, model_id: res.modelId, values: res.values, value_source: "manual", source_run_key: null, template_kind: res.ps!.input_kind, fem_verify_id: rec.id };
    rec.predict_job_id = newJob(srv, s, "PREDICT", pp, by).id;
    rec.status = "WAITING_PREDICT";
  } else {
    rec.job_id = newJob(srv, s, "FEM_VERIFY", { fem_verify_id: rec.id, fv_no: no, hpc: null }, by).id;
  }
  return { status: 201, body: detailOf(srv, rec) };
}

// ------------------------------------------------------------------ 상태 동기화(종료 훅 흉내)
export function syncFem(srv: MockServer) {
  for (const r of srv.fems) {
    const s = srv.studies.find((x) => x.id === r.study_id);
    if (!s || !activeOf(r)) continue;
    const by = { id: r.created_by, name: r.created_by_name };
    if (r.status === "WAITING_PREDICT") {
      const pj = latest(srv, r.predict_job_id);
      if (!pj) continue;
      r.predict_job_id = pj.id;
      if (pj.state === "SUCCEEDED") {
        r.job_id = newJob(srv, s, "FEM_VERIFY", { fem_verify_id: r.id, fv_no: r.fv_no, hpc: null }, by).id;
        r.status = "RUNNING";
      } else if (pj.state === "FAILED" || pj.state === "INTERRUPTED") fail(r, "PREDICT_FAILED", "함께 실행한 예측이 실패했습니다");
      else if (pj.state === "CANCELED") r.status = "CANCELED";
      continue;
    }
    const fj = latest(srv, r.job_id);
    if (!fj) continue;
    r.job_id = fj.id;
    if (fj.state === "SUCCEEDED") done(srv, r, fj);
    else if (fj.state === "FAILED" || fj.state === "INTERRUPTED") fail(r, fj.failure_code ?? "EXIT_NONZERO", fj.failure_message ?? "FEM 검증 작업이 실패했습니다");
    else if (fj.state === "CANCELED") r.status = "CANCELED";
    if (!activeOf(r)) r.finished_at ??= new Date().toISOString();
  }
}

function fail(r: FemRec, code: string, message: string) {
  r.status = "FAILED";
  r.failure = { code, message };
  r.finished_at = new Date().toISOString();
}

const FEM_FACTOR: Record<string, number> = { MaxStress: 1.072, MaxDisp: 0.968, Energy: 1.031 };

/** 비교 결과(수치만) 만들기 — 응답 정의가 있는 것만(spec 없는 응답은 비교 안 함) */
export function buildCompare(srv: MockServer, r: FemRec): FemCompare {
  const ps = srv.paramSets.find((x) => x.id === r.param_set_id) ?? srv.paramSets[0];
  const base = responseFn(r.applied_values);
  const rows = ps.responses
    .filter((x) => x.spec)
    .map((x) => {
      const pv = base[x.name];
      const fv = pv * (FEM_FACTOR[x.name] ?? 1.05);
      const diff = pv - fv;
      return {
        name: x.name, unit: x.unit, stat: x.spec?.stat ?? "MAX", pred_min: Number((pv * 0.012).toPrecision(5)), pred_max: Number(pv.toPrecision(5)), fem_min: Number((fv * 0.009).toPrecision(5)), fem_max: Number(fv.toPrecision(5)),
        pred_value: Number(pv.toPrecision(5)), fem_value: Number(fv.toPrecision(5)), diff: Number(diff.toPrecision(4)), diff_pct: Number(((diff / Math.abs(fv)) * 100).toFixed(2)), note: null as string | null,
      };
    });
  const worst = rows.reduce<(typeof rows)[number] | null>((a, b) => (!a || Math.abs(b.diff_pct ?? 0) > Math.abs(a.diff_pct ?? 0) ? b : a), null);
  const maxS = base.MaxStress;
  return {
    responses: rows,
    max_abs_diff_pct: worst ? Math.abs(worst.diff_pct ?? 0) : null,
    worst: worst?.name ?? null,
    legend: { mode: "fixed", min: 0, max: Number((maxS * 1.05).toFixed(1)), source: "minmax", note: null },
    curve: { status: "OK", message: null, names: curveJson(r.applied_values).series.map((x) => x.name), unmatched_pred: [], unmatched_fem: ["Node 30001 변위 [mm]"] },
    media: { pred_status: "OK", fem_status: "OK" },
  };
}

function makeMedia(srv: MockServer, r: FemRec, job: Job) {
  const ps = srv.paramSets.find((x) => x.id === r.param_set_id);
  const views = ps?.display?.views?.length ? ps.display.views : DEFAULT_VIEWS;
  r.media = views.map((view) => {
    const mk = (side: "pred" | "fem", k: number): [string, string | null] => [
      srv.addPngArtifact(job.id, job.study_id, "CONTOUR_IMAGE", `04_verify/${fvLabel(r.fv_no)}/a1/media/${side}/${view}.png`, () => contourPng(view, r.applied_values, k)),
      srv.addPngArtifact(job.id, job.study_id, "CONTOUR_VIDEO", `04_verify/${fvLabel(r.fv_no)}/a1/media/${side}/${view}_anim.png`, () => contourPng(view, r.applied_values, k * 0.7)),
    ];
    return { view, pred: mk("pred", 1), fem: mk("fem", 1.08) };
  });
}

function done(srv: MockServer, r: FemRec, job: Job) {
  r.status = "DONE";
  r.compare = buildCompare(srv, r);
  makeMedia(srv, r, job);
  r.finished_at = new Date().toISOString();
  if (!r.notified) {
    r.notified = true;
    const c = r.compare;
    const msg = c.worst ? `FEM 검증 ${fvLabel(r.fv_no)} 완료 — 최대 오차 ${c.max_abs_diff_pct}% (${c.worst})` : `FEM 검증 ${fvLabel(r.fv_no)} 완료 — 응답 비교 없음`;
    srv.notify(r.created_by, "FEM_VERIFY_DONE", job, msg);
  }
}

// ------------------------------------------------------------------ 출력
const STATUS_TEXT: Record<FvStatus, string> = { WAITING_PREDICT: "예측 실행 중", RUNNING: "실행 중", DONE: "완료", FAILED: "실패", CANCELED: "취소됨" };

function summaryOf(r: FemRec): FemVerifySummary {
  return {
    id: r.id, label: fvLabel(r.fv_no), status: r.status, source_label: r.source_label, source_kind: r.source_kind, links: r.links,
    max_abs_diff_pct: r.compare?.max_abs_diff_pct ?? null, worst: r.compare?.worst ?? null, created_at: r.created_at, created_by_name: r.created_by_name, finished_at: r.finished_at, values: r.values,
  };
}

function detailOf(srv: MockServer, r: FemRec): FemVerification {
  const job = latest(srv, r.job_id);
  const pj = latest(srv, r.predict_job_id);
  const me = srv.me;
  const s = srv.studies.find((x) => x.id === r.study_id)!;
  const ps = srv.paramSets.find((x) => x.id === r.param_set_id) ?? null;
  const model = srv.models.find((m) => m.id === r.model_id);
  const dir = srv.disp(r.study_id, `04_verify/${fvLabel(r.fv_no)}`);
  const a = `${dir}\\a${r.attempt_no}`;
  const owner = !!me && (me.is_global_admin || me.user_id === r.created_by);
  const power = !!me && ["power", "admin"].includes(srv.role(s.project_id) ?? "");
  const text = r.status === "RUNNING" && job ? (job.state === "WAITING_HPC" || job.state === "COLLECTING" ? (r.hpc_mode === "scx" ? "해석 대기(SCX)" : "해석 대기(PBS)") : `${JOB_STATE_LABEL[job.state]}`) : STATUS_TEXT[r.status];
  return {
    ...summaryOf(r),
    status_text: text,
    source: { kind: r.source_kind, label: r.source_label },
    design: {
      param_set: ps ? { id: ps.id, label: ps.label ?? (ps.source_path.split(/[\\/]/).filter(Boolean).pop() ?? null), input_kind: ps.input_kind } : null,
      model: model ? { id: model.id, name: model.name, version: model.version } : null,
      values: r.values, applied_values: r.applied_values, out_of_range: r.out_of_range,
    },
    predict: { job_id: pj?.id ?? r.predict_job_id, state: pj?.state ?? null, companion: r.companion, reuse: !r.companion, will_run: r.companion && r.status === "WAITING_PREDICT" },
    assembly: { kind: r.assem_kind, label: r.assem_label, path: r.assem_path, snapshot_dir: r.job_id ? `${a}\\assem` : null },
    input_mode: r.input_mode,
    attempt_no: r.attempt_no,
    dir,
    paths: {
      input_dir: r.job_id ? `${a}\\input` : null, result_dir: r.status === "DONE" ? `${a}\\result` : null, starter: r.job_id ? "Face_Drop_0000.rad" : null,
      remote_dir: r.hpc_mode === "scx" && r.job_id ? `/Users/vd.dashboard/cushion/04_${fvLabel(r.fv_no)}_20261019T101500` : null,
    },
    job: job ? ({ ...job, steps: undefined } as never) : null,
    compare: r.compare,
    warnings: r.warnings,
    failure: r.failure,
    can_cancel: activeOf(r) && owner && power,
    can_rerun: (r.status === "FAILED" || r.status === "CANCELED") && power,
    hpc_mode: r.hpc_mode,
  };
}

function mediaOf(srv: MockServer, r: FemRec): FemMedia {
  const side = (ids: [string, string | null], view: string) => ({ image: mediaFile(srv, ids[0]), video: ids[1] ? mediaFile(srv, ids[1], view, true) : null, video_error: ids[1] ? null : "파일이 만들어지지 않았습니다(HyperView 성공 보고)" });
  return {
    status: r.status === "DONE" ? "OK" : "NONE",
    display: srv.paramSets.find((x) => x.id === r.param_set_id)?.display ?? null,
    legend: r.compare?.legend ?? null,
    items: r.media.map((m) => ({ view: m.view, label: viewLabel(m.view), pred: side(m.pred, m.view), fem: side(m.fem, m.view) })),
  };
}

function curvesOf(r: FemRec, name: string | null) {
  const c = curveJson(r.applied_values);
  const names = c.series.map((x) => x.name);
  const pick = name && names.includes(name) ? name : names[0];
  const s = c.series.find((x) => x.name === pick)!;
  return {
    names, name: pick, downsampled: false,
    pred: { x: s.x, y: s.y },
    fem: { x: s.x, y: s.y.map((v, i) => Number((v * (1.06 + 0.02 * Math.sin(i / 5)) + 0.01).toFixed(4))) },
  };
}

function csvOf(r: FemRec): string {
  const head = "name,unit,stat,pred_min,pred_max,fem_min,fem_max,pred_value,fem_value,diff,diff_pct";
  const lines = (r.compare?.responses ?? []).map((x) => [x.name, x.unit ?? "", x.stat, x.pred_min, x.pred_max, x.fem_min, x.fem_max, x.pred_value, x.fem_value, x.diff, x.diff_pct].join(","));
  return "﻿" + [head, ...lines].join("\n") + "\n";
}

function cancelJob(srv: MockServer, j: Job | null) {
  if (!j || TERMINAL.includes(j.state)) return;
  if (j.state === "QUEUED") {
    j.state = "CANCELED";
    j.finished_at = new Date().toISOString();
    srv.queueOrder.delete(j.id);
  } else j.cancel_requested = true;
  srv.bump(j);
}

function rerun(srv: MockServer, r: FemRec, by: { id: string; name: string }): MockResp {
  const s = srv.studies.find((x) => x.id === r.study_id)!;
  const pj = latest(srv, r.predict_job_id);
  if (r.companion && pj && pj.state !== "SUCCEEDED") {
    const nj = newJob(srv, s, "PREDICT", { ...pj.params }, by, pj.id);
    r.predict_job_id = nj.id;
    r.status = "WAITING_PREDICT";
  } else {
    const fj = latest(srv, r.job_id);
    const failedIdx = fj?.steps.findIndex((x) => x.state === "FAILED") ?? -1;
    if (failedIdx < 0 || failedIdx <= 5) r.attempt_no++;
    r.job_id = newJob(srv, s, "FEM_VERIFY", { fem_verify_id: r.id, fv_no: r.fv_no, hpc: null }, by, fj?.id ?? null).id;
    r.status = "RUNNING";
  }
  r.failure = null;
  r.finished_at = null;
  return { status: 201, body: detailOf(srv, r) };
}

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
      return { status: 200, body: page.map(summaryOf), headers: list.length > lim && last ? { "X-Next-Cursor": `${last.created_at}|${last.id}` } : undefined };
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
