// S16 V2 목(phase3 §21.3, R-F 분할): 검증 출처 해석(배치 run·단일 예측·값 직접)·조립 원본 시나리오·사용자 지정 경로 검사.
import type { Job, ParamSet, Study } from "../api/types";
import type { FemProblem } from "../api/femVerify";
import { err, type MockResp } from "./route";
import { resolveInput } from "./inputKind";
import type { MockServer } from "./server";
import { batchLabel, isBatchChild } from "./predictBatch";
import { inspectPath } from "./studies";
import { MOCK_SPDM_ROOT, latest, md } from "./femVerifyRec";
import type { FemRec, SourceKind } from "./femVerifyRec";

// ------------------------------------------------------------------ 출처 해석
export interface Resolved {
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
export type Problem = FemProblem;

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

function resolveValues(srv: MockServer, s: Study, a: { param_set_id: string; model_id?: string | null; values: Record<string, number>; reuse_existing?: boolean; input?: string }, label: string, kind: SourceKind, links: FemRec["links"]): Resolved | MockResp {
  const ps = srv.paramSets.find((x) => x.id === a.param_set_id && x.study_id === s.id);
  if (!ps) return err(422, "INVALID_PARAMS", "템플릿을 찾을 수 없습니다.");
  const ri = resolveInput(ps, a.input);
  if ("error" in ri) return ri.error;
  const miss = ps.parameters.filter((p) => !Number.isFinite(a.values?.[p.name]));
  if (miss.length) return err(422, "INVALID_PARAMS", `모든 파라미터 값이 필요합니다(${miss.map((m) => m.name).join(", ")}).`);
  const modelId = a.model_id || s.final_model_id;
  if (!modelId) return err(409, "FINAL_MODEL_REQUIRED", "Final 모델을 먼저 지정하세요.");
  const { applied, out } = applyInts(ps, a.values);
  const reuse = a.reuse_existing !== false
    ? [...srv.jobs].reverse().find((j) => j.study_id === s.id && j.job_type === "PREDICT" && j.state === "SUCCEEDED" && !isBatchChild(j) && (j.params as { input_mode?: string }).input_mode !== "prepared" && (j.params as { param_set_id?: string }).param_set_id === ps.id &&
        ((j.params as { model_id?: string | null }).model_id || s.final_model_id) === modelId && sameValues((j.result as { applied_values?: Record<string, number> } | null)?.applied_values ?? {}, applied))
    : undefined;
  const meshOnly = ri.input === "cushion";
  return { kind, label, links, ps, modelId, values: a.values, applied, outOfRange: out, predict: reuse ?? null, needsCompanion: !reuse, inputIsAssembly: !meshOnly, meshAvailable: true, meshOnly };
}

export function resolveSource(srv: MockServer, s: Study, src: Record<string, unknown>, problems: Problem[]): Resolved | MockResp {
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
export function plan(label: string, path: string, over: Record<string, unknown> = {}) {
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

export function checkCustomPath(path: string): MockResp | null {
  if (!path.trim()) return err(422, "PATH_NOT_FOUND", "경로를 입력하세요.");
  if (path.toLowerCase().startsWith(MOCK_SPDM_ROOT.toLowerCase())) {
    if (/\s|[&|<>^%!"]/.test(path)) return err(422, "PATH_UNSAFE", "경로에 공백이나 특수문자를 쓸 수 없습니다.");
    return null;
  }
  const r = inspectPath("RADIOSS_ASSEM", path);
  return r.status === 200 ? null : r;
}
