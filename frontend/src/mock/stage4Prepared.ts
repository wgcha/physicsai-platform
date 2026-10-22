// S6 ④ 준비된 입력 예측 목(phase3.md §11.5): paths/inspect PREDICT_INPUT, PREDICT params 검증(422·409), prepared step 생략·결과.
// 경로 이름으로 시나리오를 고른다(데모·시험용):
//   …/X.rad → 파일(같은 폴더 .rad·.inc 복사), …/X.hm → 그 파일만, 확장자가 그 밖이면 INPUT_EXT
//   폴더 이름에 two → starter 2개(STARTER_COUNT), nostarter → 0개, toomany → TOO_MANY_FILES, huge → TOO_LARGE, bad&name 없음(경로 검사에서 거부)
//   경로에 nested → 하위 폴더 2개(subdir_count, 복사 안 함 — D3-43)
//   폴더 이름에 batch → 직계 starter 0개 + 하위 폴더 후보 starter_hints 2개(안내 전용 — D3-44)
import type { Job, PredictInputInspect, PredictInputProblem, Study } from "../api/types";
import { PREVIEW_JSON, contourSvg, curveJson, responseFn } from "./data";
import { err, needPower, type MockResp, type Route } from "./route";
import type { MockServer } from "./server";
import { inspectPath } from "./studies";
import { captureMedia } from "./capture";
import { resolveInput, toInternal } from "./inputKind";

const MAX_FILES = 500;
const MAX_BYTES = 2147483648;
const EXTS = [".rad", ".hm"];
/** prepared에서 SKIPPED "준비된 입력 — 해당 없음" */
export const PREPARED_SKIPPED = new Set(["TPL_RENDER", "GEOM_UPDATE", "MESH"]);

const baseName = (p: string) => p.split(/[\\/]/).filter(Boolean).pop() ?? "";

/** 복사 계획(plan_copy 흉내). 경로 자체가 거부되면 MockResp */
export function planCopy(path: string): PredictInputInspect | MockResp {
  const base = inspectPath("PREDICT_INPUT", path);
  if (base.status !== 200) return base;
  const name = baseName(path);
  const ext = /\.[A-Za-z0-9]+$/.exec(name)?.[0]?.toLowerCase() ?? "";
  const problems: PredictInputProblem[] = [];
  if (ext && !EXTS.includes(ext)) {
    problems.push({ code: "INPUT_EXT", message: `입력 파일 확장자는 ${EXTS.join("·")}만 쓸 수 있습니다(${ext}).` });
    return { kind: "file", starter: [], starter_ok: false, rad: [], inc_count: 0, file_count: 0, total_bytes: 0, subdir_count: 0, starter_hints: [], problems };
  }
  if (ext === ".hm") return { kind: "file", starter: [name], starter_ok: true, rad: [], inc_count: 0, file_count: 1, total_bytes: 48_234_112, subdir_count: 0, starter_hints: [], problems };
  const kind = ext === ".rad" ? "file" : "dir";
  const batch = kind === "dir" && /batch/i.test(path);
  const starter = kind === "file" ? [name] : /nostarter/i.test(path) || batch ? [] : /two/i.test(path) ? ["Face_Drop_0000.rad", "Side_Drop_0000.rad"] : ["Face_Drop_0000.rad"];
  const sep = path.includes("\\") ? "\\" : "/";
  const hints = batch ? [`case1${sep}Face_Drop_0000.rad`, `case2${sep}Side_Drop_0000.rad`] : [];
  const rad = [...starter, "Face_Drop_0001.rad"];
  const many = /toomany/i.test(path);
  const incCount = many ? 640 : 3;
  const total = /huge/i.test(path) ? MAX_BYTES + 1 : 182_400_512;
  if (kind === "dir" && starter.length !== 1)
    problems.push({ code: "STARTER_COUNT", message: `starter(*_0000.rad)가 정확히 1개 있어야 합니다(현재 ${starter.length}개${starter.length ? `: ${starter.join(", ")}` : ""})` });
  if (rad.length + incCount > MAX_FILES) problems.push({ code: "TOO_MANY_FILES", message: `복사할 파일이 ${MAX_FILES}개를 넘습니다(${rad.length + incCount}개).` });
  if (total > MAX_BYTES) problems.push({ code: "TOO_LARGE", message: "복사할 파일 합계가 2 GiB를 넘습니다." });
  const subdirCount = /nested/i.test(path) ? 2 : batch ? 2 : 0;
  return { kind, starter, starter_ok: starter.length === 1, rad, inc_count: incCount, file_count: rad.length + incCount, total_bytes: total, subdir_count: subdirCount, starter_hints: hints, problems };
}

const isResp = (x: PredictInputInspect | MockResp): x is MockResp => "status" in x;

/** POST paths/inspect purpose=PREDICT_INPUT: 기존 모양(normalized_path·ok·problems·summary) + summary에 §11.5 키 */
export function inspectPredictInput(path: string): MockResp {
  const plan = planCopy(path);
  if (isResp(plan)) return plan;
  const { problems, ...summary } = plan;
  const ok = plan.starter_ok && problems.length === 0;
  return { status: 200, body: { normalized_path: path.replace(/\\/g, "/"), ok, problems, summary } };
}

/**
 * PREDICT params 검증(§11.5): input_mode 생략 = parametric. 실패면 { error }, 통과면 저장할 params.
 * prepared는 저장 params를 정규화(input_path·input_kind·starter_name)한다. 요청 본문은 바꾸지 않는다.
 */
export function predictParams(srv: MockServer, s: Study, params: Record<string, unknown>): { error: MockResp } | { params: Record<string, unknown> } {
  const r = checkPredictParams(srv, s, params);
  if (r && typeof r.status === "number" && "body" in r) return { error: r as MockResp };
  return { params: (r as Record<string, unknown> | null) ?? params };
}

function checkPredictParams(srv: MockServer, s: Study, params: Record<string, unknown>): MockResp | Record<string, unknown> | null {
  const mode = params.input_mode ?? "parametric";
  if (mode !== "parametric" && mode !== "prepared") return err(422, "INVALID_PARAMS", "input_mode는 parametric 또는 prepared입니다.");
  if (mode === "parametric") {
    if (params.input_path) return err(422, "INVALID_PARAMS", "파라미터 입력에는 input_path를 쓸 수 없습니다.");
    // S9 §14.4: 템플릿 input_kind별 기능(mesh_only = predict_mesh_only), 서버가 params에 template_kind로 확정 기록(백엔드 P0)
    const ps = srv.paramSets.find((p) => (params.param_set_id ? p.id === params.param_set_id : p.study_id === s.id && p.is_current));
    let kind: "assembly" | "mesh_only" = ps?.input_kind ?? "assembly";
    if (ps) {
      const ri = resolveInput(ps, params.input);
      if ("error" in ri) return ri.error;
      kind = toInternal(ri.input);
    }
    const f = srv.p2.feature(kind === "mesh_only" ? "predict_mesh_only" : "predict_parametric");
    if (!f.enabled) return err(409, "TEMPLATE_NOT_CONFIGURED", "형상 갱신 설정이 필요합니다(관리자).", { missing: f.missing });
    const { input: _i, ...rest } = params;
    return { ...rest, template_kind: kind };
  }
  const path = typeof params.input_path === "string" ? params.input_path.trim() : "";
  if (!path) return err(422, "INVALID_PARAMS", "input_path가 필요합니다.");
  const vals = params.values as Record<string, unknown> | undefined;
  if ((vals && Object.keys(vals).length) || params.value_source != null || params.source_run_key != null)
    return err(422, "INVALID_PARAMS", "준비된 입력에는 values·value_source·source_run_key를 쓸 수 없습니다.");
  if (params.param_set_id && !srv.paramSets.some((p) => p.id === params.param_set_id && p.study_id === s.id))
    return err(409, "PREREQUISITE_MISSING", "지정한 파라미터 세트가 없습니다.", { missing: ["PARAM_SET"] });
  const plan = planCopy(path);
  if (isResp(plan)) return plan;
  if (!plan.starter_ok || plan.problems.length)
    return err(422, "PREDICT_INPUT_INVALID", "준비된 입력을 쓸 수 없습니다", { problems: plan.problems });
  return {
    input_mode: "prepared",
    input_path: path.replace(/\\/g, "/"),
    input_kind: plan.kind,
    starter_name: plan.starter[0],
    model_id: params.model_id ?? null,
    param_set_id: params.param_set_id ?? null,
  };
}

export function isPrepared(j: Job): boolean {
  return j.job_type === "PREDICT" && (j.params as { input_mode?: string }).input_mode === "prepared";
}

/** 응답 표에 쓸 세트: 지정 세트, 없으면 현재 세트(없으면 null) */
function respSet(srv: MockServer, j: Job) {
  const id = (j.params as { param_set_id?: string | null }).param_set_id;
  return srv.paramSets.find((p) => (id ? p.id === id : p.study_id === j.study_id && p.is_current)) ?? null;
}

/** step 상태 보정: 형상·메싱 step SKIPPED, 세트에 응답이 없으면 RESPONSE_TABLE도 SKIPPED */
export function adjustPreparedSteps(srv: MockServer, j: Job) {
  if (!isPrepared(j)) return;
  const noResp = !respSet(srv, j)?.responses.length;
  for (const st of j.steps) {
    if (st.state === "PENDING") continue;
    if (PREPARED_SKIPPED.has(st.step_key) || (noResp && st.step_key === "RESPONSE_TABLE")) {
      st.state = "SKIPPED";
      st.exit_code = null;
      st.finished_at = null;
    }
  }
}

/** prepared 완료 결과(§11.5): values 비어 있음, nearest·diff null */
export function preparedResult(srv: MockServer, j: Job) {
  const p = j.params as { model_id?: string | null; param_set_id?: string | null; input_path?: string };
  const study = srv.studies.find((s) => s.id === j.study_id)!;
  const ps = respSet(srv, j);
  const nominal = ps ? Object.fromEntries(ps.parameters.map((x) => [x.name, x.nominal])) : {};
  const pred = responseFn(nominal);
  const img = srv.addArtifact(j.id, j.study_id, "PREVIEW_IMAGE", `04_predict/${j.id}/contour.png`, "image/svg+xml", contourSvg(nominal));
  const pj = srv.addArtifact(j.id, j.study_id, "PREVIEW_JSON", `04_predict/${j.id}/H3D_PREVIEW.json`, "application/json", JSON.stringify(PREVIEW_JSON));
  const cj = srv.addArtifact(j.id, j.study_id, "CURVE_JSON", `04_predict/${j.id}/curve.json`, "application/json", JSON.stringify(curveJson(nominal)));
  return {
    model_id: p.model_id || study.final_model_id || "m-1",
    param_set_id: p.param_set_id ?? null,
    input_mode: "prepared" as const,
    input_path: p.input_path ?? null,
    values: {},
    applied_values: {},
    out_of_range: [],
    nearest: null,
    preview_json_artifact_id: pj,
    image_artifact_ids: [img],
    curve_artifact_id: cj,
    response_table_artifact_id: null,
    response_table: (ps?.responses ?? []).map((r) => ({ name: r.name, unit: r.unit, predicted: pred[r.name] ?? null, nearest_measured: null, diff_pct: null })),
    media: captureMedia(srv, j, nominal), // S10
  };
}

/** POST /studies/{id}/paths/inspect (purpose=PREDICT_INPUT)만 맡는다. 나머지는 studyRoutes로 */
export const preparedRoutes: Route = (srv, { method, seg, body }) => {
  if (method !== "POST" || seg[0] !== "studies" || seg[2] !== "paths" || seg[3] !== "inspect" || body?.purpose !== "PREDICT_INPUT") return null;
  const s = srv.studies.find((x) => x.id === seg[1]);
  if (!s) return err(404, "NOT_FOUND", "Study를 찾을 수 없습니다.");
  const d = needPower(srv, s.project_id);
  if (d) return d;
  return inspectPredictInput(String(body?.path ?? ""));
};
