// S16 V1 목(phase3 §21.2): GET /studies/{id}/predict-runs · GET /predict-runs/{job_id}. 새 DB 없이 PREDICT 작업(params·result)으로 만든다.
// 대상 = 그 Study의 PREDICT 중 일괄 하위(params.batch_run) 제외, 재시도로 대체된 이전 시도 숨김(최신 1행·attempts), 정렬 (created_at DESC, id DESC).
// MockOptions.predictRuns = "history" → 이력 시드(템플릿·준비된 입력·재시도·실패·진행 중).
import type { Job, JobState } from "../api/types";
import type { PredictRunDetail, PredictRunSummary } from "../api/predictRuns";
import { baseJob, iso, makeSteps } from "./data";
import { err, ok, type Route } from "./route";
import type { MockServer } from "./server";
import { predictResult } from "./stage4";
import { preparedResult } from "./stage4Prepared";
import { isBatchChild } from "./predictBatch";

const STATES: JobState[] = ["QUEUED", "RUNNING", "WAITING_HPC", "COLLECTING", "SUCCEEDED", "FAILED", "CANCELED", "INTERRUPTED"];
const prm = (j: Job) => j.params as Record<string, unknown>;

function chainOf(srv: MockServer, j: Job): { root: Job; latest: Job; attempts: number } {
  let root = j;
  for (let k = 0; k < 50 && root.retry_of_job_id; k++) {
    const prev = srv.jobs.find((x) => x.id === root.retry_of_job_id);
    if (!prev) break;
    root = prev;
  }
  let latest = root;
  let attempts = 1;
  for (let k = 0; k < 50; k++) {
    const next = srv.jobs.find((x) => x.retry_of_job_id === latest.id);
    if (!next) break;
    latest = next;
    attempts++;
  }
  return { root, latest, attempts };
}

function summaryOf(srv: MockServer, j: Job): PredictRunSummary {
  const p = prm(j);
  const { root, attempts } = chainOf(srv, j);
  const r = (j.state === "SUCCEEDED" ? j.result : null) as Record<string, unknown> | null;
  const prepared = p.input_mode === "prepared";
  const study = srv.studies.find((s) => s.id === j.study_id)!;
  const psId = (p.param_set_id as string | null) ?? (prepared ? null : (r?.param_set_id as string | undefined) ?? srv.paramSets.find((x) => x.study_id === j.study_id && x.is_current)?.id ?? null);
  const ps = srv.paramSets.find((x) => x.id === psId) ?? null;
  const model = srv.models.find((m) => m.id === ((p.model_id as string) || (r?.model_id as string) || study.final_model_id));
  const table = ((r?.response_table as { name: string; unit: string | null; predicted: number | null }[] | undefined) ?? []).slice(0, 5);
  const media = (r?.media as { view: string }[] | null | undefined) ?? null;
  const info = srv.mediaInfo.get(j.id);
  const ver = [...srv.jobs].reverse().find((x) => x.job_type === "PREDICT_VERIFY" && (x.params as { predict_job_id?: string }).predict_job_id === j.id);
  const start = j.started_at ? new Date(j.started_at).getTime() : null;
  const end = j.finished_at ? new Date(j.finished_at).getTime() : null;
  return {
    job_id: j.id,
    root_job_id: root.id,
    attempts,
    state: j.state,
    origin: p.fem_verify_id ? "fem_verify" : "manual",
    created_at: j.created_at,
    started_at: j.started_at ?? null,
    finished_at: j.finished_at ?? null,
    duration_s: start != null && end != null ? Math.round((end - start) / 1000) : null,
    created_by_name: j.created_by_name,
    input_mode: prepared ? "prepared" : "template",
    template: ps ? { id: ps.id, label: ps.label ?? (ps.source_path.split(/[\\/]/).filter(Boolean).pop() ?? null), input_kind: ps.input_kind } : null,
    model: model ? { id: model.id, name: model.name, version: model.version } : null,
    values: prepared ? {} : ((p.values as Record<string, number> | undefined) ?? {}),
    applied_values: (r?.applied_values as Record<string, number> | undefined) ?? {},
    out_of_range: (r?.out_of_range as string[] | undefined) ?? [],
    input_path: prepared ? ((p.input_path as string | undefined) ?? null) : null,
    starter: prepared ? ((p.starter_name as string | undefined) ?? null) : null,
    responses: table.map((x) => ({ name: x.name, unit: x.unit, predicted: x.predicted })),
    capture: info && info.status !== "DISABLED" ? { status: info.status, views: (media ?? []).map((m) => m.view) } : null,
    has_curve: !!r?.curve_artifact_id,
    warnings_count: j.warnings.length,
    failure: j.failure_code ? { code: j.failure_code, message: j.failure_message ?? "" } : null,
    verify: ver ? { job_id: ver.id, state: ver.state } : null,
  };
}

function detailOf(srv: MockServer, j: Job): PredictRunDetail {
  const s = summaryOf(srv, j);
  const r = (j.state === "SUCCEEDED" ? j.result : null) as Record<string, unknown> | null;
  const root = s.root_job_id;
  const d = (rel: string) => srv.disp(j.study_id, `04_predict/${root}${rel ? `/${rel}` : ""}`);
  const done = j.state === "SUCCEEDED";
  const ps = srv.paramSets.find((x) => x.id === s.template?.id);
  return {
    ...s,
    nearest: (r?.nearest as PredictRunDetail["nearest"]) ?? null,
    response_table: (r?.response_table as PredictRunDetail["response_table"]) ?? [],
    paths: {
      dir: d(""),
      input_dir: j.steps.some((x) => x.step_key === "RAD_ASSEMBLE" && x.state === "SUCCEEDED") || done ? d("INPUT") : null,
      result_dir: done ? d("RESULT") : null,
      pred_h3d: done ? d("RESULT/EPS_mesh_0000_pred.h3d") : null,
      media_dir: done && r?.media ? d("RESULT/media") : null,
      geom_dir: s.input_mode === "template" ? d("geom") : null,
    },
    display: ps?.display ?? null,
  };
}

function eligible(srv: MockServer, studyId: string): Job[] {
  return srv.jobs
    .filter((j) => j.study_id === studyId && j.job_type === "PREDICT" && !isBatchChild(j) && !srv.jobs.some((x) => x.retry_of_job_id === j.id))
    .sort((a, b) => b.created_at.localeCompare(a.created_at) || b.id.localeCompare(a.id));
}

export const predictRunsRoutes: Route = (srv, { method, seg, query }) => {
  if (method !== "GET") return null;
  if (seg[0] === "studies" && seg[1] && seg[2] === "predict-runs" && !seg[3]) {
    if (!srv.studies.some((s) => s.id === seg[1])) return err(404, "NOT_FOUND", "Study를 찾을 수 없습니다.");
    const mode = query.get("mode") ?? "all";
    if (!["all", "template", "prepared"].includes(mode)) return err(422, "INVALID_PARAMS", "mode는 all·template·prepared입니다.");
    const st = (query.get("state") ?? "").split(",").filter(Boolean);
    if (st.some((x) => !STATES.includes(x as JobState))) return err(422, "INVALID_PARAMS", "알 수 없는 state입니다.");
    const limit = Math.max(1, Math.min(200, Number(query.get("limit") ?? 50)));
    const cursor = query.get("cursor");
    let list = eligible(srv, seg[1]).filter((j) => (mode === "all" ? true : mode === "prepared" ? prm(j).input_mode === "prepared" : prm(j).input_mode !== "prepared"));
    if (st.length) list = list.filter((j) => st.includes(j.state));
    if (cursor) {
      const [c, id] = cursor.split("|");
      list = list.filter((j) => j.created_at < c || (j.created_at === c && j.id < id));
    }
    const page = list.slice(0, limit);
    const last = page[page.length - 1];
    const headers = list.length > limit && last ? { "X-Next-Cursor": `${last.created_at}|${last.id}` } : undefined;
    return { status: 200, body: page.map((j) => summaryOf(srv, j)), headers };
  }
  if (seg[0] === "predict-runs" && seg[1] && !seg[2]) {
    const j = srv.jobs.find((x) => x.id === seg[1]);
    if (!j) return err(404, "JOB_NOT_FOUND", "작업을 찾을 수 없습니다.");
    if (j.job_type !== "PREDICT" || isBatchChild(j)) return err(404, "NOT_PREDICT_RUN", "단일 예측 작업이 아닙니다.");
    return ok(detailOf(srv, j));
  }
  return null;
};

/** 이력 시드(시험·스크린샷용): 시간순으로 오래된 것부터 12건. 마지막은 진행 중 */
export function seedPredictRuns(srv: MockServer) {
  const st = "쿠션 두께·리브 예측";
  const mk = (id: string, minAgo: number, durMin: number | null, p: Record<string, unknown>, state: JobState, extra: Partial<Job> = {}): Job => {
    const j = baseJob({
      id, study_id: "s-cushion", project_id: "p-cushion", study_title: st, job_type: "PREDICT", state,
      created_by: "u-power", created_by_name: "김연구", created_at: iso(minAgo), started_at: state === "QUEUED" ? null : iso(minAgo - 1),
      finished_at: durMin != null ? iso(minAgo - 1 - durMin) : null, steps: makeSteps("PREDICT", state === "SUCCEEDED" ? 10 : 3, null), progress_pct: state === "SUCCEEDED" ? 100 : 40, params: p, ...extra,
    });
    srv.jobs.push(j);
    return j;
  };
  const vals = (t: number, f: number, r: number) => ({ THK_TOP: t, THK_FOAM: f, E_FOAM: 9.5, RIB_N: r });
  const tpl = (values: Record<string, number>) => ({ param_set_id: "ps-1", model_id: null, values, value_source: "manual", source_run_key: null, template_kind: "assembly" });
  for (let i = 0; i < 9; i++) {
    const v = vals(0.4 + i * 0.05, 1.8 + i * 0.1, 3 + (i % 4));
    const j = mk(`j-h${i}`, 60 * (30 - i * 2), 7 + (i % 3), tpl(v), "SUCCEEDED");
    j.result = predictResult(srv, j, v, "m-1", "ps-1");
  }
  const prep = (path: string) => ({ input_mode: "prepared", input_path: path, input_kind: "dir", starter_name: "Face_Drop_0000.rad", model_id: null, param_set_id: null });
  const p1 = mk("j-hp1", 60 * 11, 9, prep("E:/shared/AI_WORK/cushion_v1/00_inbox/case_A"), "SUCCEEDED");
  p1.result = preparedResult(srv, p1);
  // 실패 → 재시도 → 성공(2회차)
  const f1 = mk("j-hf1", 60 * 7, 2, tpl(vals(0.6, 2.4, 5)), "FAILED", { failure_code: "EXIT_NONZERO", failure_message: "EDSPY_PREDICT 종료코드 1" });
  f1.steps = makeSteps("PREDICT", 4, null, { failedIdx: 4 });
  const f2 = mk("j-hf2", 60 * 6, 8, tpl(vals(0.6, 2.4, 5)), "SUCCEEDED", { retry_of_job_id: f1.id });
  f2.result = predictResult(srv, f2, vals(0.6, 2.4, 5), "m-1", "ps-1");
  mk("j-hr", 4, null, tpl(vals(0.52, 2.1, 6)), "RUNNING");
}
