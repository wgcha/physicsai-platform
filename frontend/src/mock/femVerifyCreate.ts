// S16 V2 목(phase3 §21.3, R-F 분할): 미리보기·생성(POST fem-verifications/preview·create).
import type { Study } from "../api/types";
import { err, type MockResp } from "./route";
import type { MockServer } from "./server";
import { MAX_ACTIVE, latest, newJob } from "./femVerifyRec";
import type { FemRec } from "./femVerifyRec";
import { assemblyPlanFor, checkCustomPath, plan, resolveSource } from "./femVerifySource";
import type { Problem, Resolved } from "./femVerifySource";
import { detailOf } from "./femVerifyOut";
import { normHpc } from "./jobs";

// ------------------------------------------------------------------ 미리보기·생성
type Body = Record<string, unknown>;

export function previewOf(srv: MockServer, s: Study, body: Body): { error: MockResp } | { out: Record<string, unknown>; res: Resolved; assem: FemRec["assem_kind"]; assemLabel: string; assemPath: string | null; inputMode: "reuse" | "rebuild"; warnings: Problem[] } {
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
      input: res.meshOnly ? "cushion" : "assembly",
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

export function activeOf(r: FemRec) {
  return r.status === "WAITING_PREDICT" || r.status === "RUNNING";
}

export function createRec(srv: MockServer, s: Study, body: Body, by: { id: string; name: string }): MockResp {
  if (s.status !== "ACTIVE") return err(409, "STUDY_ARCHIVED", "보관된 Study입니다.");
  const p = previewOf(srv, s, body);
  if ("error" in p) return p.error;
  const hpc = normHpc(body.hpc);
  if ("error" in hpc) return hpc.error;
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
    created_by: by.id, created_by_name: by.name, created_at: new Date().toISOString(), finished_at: null, notified: false, input: res.meshOnly ? "cushion" : "assembly",
  };
  srv.fems.push(rec);
  if (res.needsCompanion) {
    const pp = { param_set_id: res.ps!.id, model_id: res.modelId, values: res.values, value_source: "manual", source_run_key: null, template_kind: res.meshOnly ? "mesh_only" : "assembly", fem_verify_id: rec.id };
    rec.predict_job_id = newJob(srv, s, "PREDICT", pp, by).id;
    rec.status = "WAITING_PREDICT";
  } else {
    rec.job_id = newJob(srv, s, "FEM_VERIFY", { fem_verify_id: rec.id, fv_no: no, hpc: hpc.hpc }, by).id;
  }
  return { status: 201, body: detailOf(srv, rec) };
}
