// phase3.md §14 S9 목: 조합 계산(batch_matrix 흉내)·미리보기·PREDICT_BATCH 생성·진행·하위 PREDICT·결과 표·CSV·커브·
// 일괄 취소·실패만 다시·템플릿 응답 저장. 배치 상태는 하위 작업(재시도 사슬 포함)에서 매번 계산한다(목 단순화).
// S12(§17.4): GET /predict-batches/{bid}/design-map — 완료 run의 curve.json 계열별 max·min·|max|, RESP(가짜 응답 함수의 _MAX·_MIN), 결과 표 값.
// 시드: s-cushion에 끝난 배치 B-002(20 run, 생성 실패 1·예측 실패 1). MockOptions.batchDemo="running"이면 진행 중 B-003도 넣는다(대기열에 하위 12개).
// R-F 분할(동작 불변): 기록·상수·타입 predictBatchRec · 조합 계산 predictBatchMatrix · 상태·응답 predictBatchOut · 작업 생성·진행 predictBatchJobs · 시드 predictBatchSeed · 설계공간 지도 predictBatchDesign. 옛 import 경로는 아래에서 재노출한다.
import type { BatchCurves, BatchSource, Job, PredictBatch, ResponseSpec, TemplateResponse } from "../api/types";
import { downsampleMinMax } from "../lib/downsample";
import { err, needPower, ok, type Route } from "./route";
import { mockBrief, mockSampling } from "./sampling";
import { isSamplingKind, recommendedCount } from "../lib/sampling";
import type { MockServer } from "./server";
import { BATCH_MAX_RUNS, CURVE_MAX_RUNS, TERMINAL, batchLabel, inputKindOf } from "./predictBatchRec";
import { batchMatrix, isResp } from "./predictBatchMatrix";
import { batchOut, batchStatus } from "./predictBatchOut";
import { designMapOut } from "./predictBatchDesign";
export { BATCH_MAX_RUNS, BATCH_TABLE_MAX_BYTES, CURVE_MAX_RUNS, batchLabel, batchRunKey, inputKindOf } from "./predictBatchRec";
export type { BatchRunRec, BatchRec } from "./predictBatchRec";
export { batchMatrix } from "./predictBatchMatrix";
export type { BatchMatrixOut } from "./predictBatchMatrix";
export { batchStatus, samplingOf, batchOut } from "./predictBatchOut";
export { isBatchChild, predictBatchCreate, onBatchJobCreated, batchOnProgress, finishBatchParent, batchChildResult, batchAfterChild } from "./predictBatchJobs";
export { seedBatches } from "./predictBatchSeed";
export { curveStatsOf } from "./predictBatchDesign";

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
    if (!["MAX", "MIN", "ABSMAX"].includes(sp.stat)) problems.push({ code: "STAT", message: `${name}: stat은 MAX·MIN·ABSMAX` });
    // S17 §22.3.1: CURVE spec = {source, series, stat}(series 문자열 1~200자·| 금지·제어문자 금지, null = 첫 계열)
    if (sp.source === "CURVE") {
      const se = sp.series;
      if (Object.keys(sp).some((k) => !["source", "series", "stat"].includes(k))) problems.push({ code: "SPEC", message: `${name}: 커브 정의 키는 source·series·stat뿐입니다` });
      if (se != null && (typeof se !== "string" || se.length < 1 || se.length > 200 || se.includes("|") || [...se].some((c) => c.charCodeAt(0) < 32)))
        problems.push({ code: "SERIES", message: `${name}: 계열 이름은 1~200자, | 와 제어 문자는 쓸 수 없습니다` });
      continue;
    }
    if ([name, sp.datatype, sp.component, sp.layer, r.unit].some((v) => String(v ?? "").includes("|"))) problems.push({ code: "PIPE", message: `${name}: 문자 | 는 쓸 수 없습니다` });
    if (!Number.isInteger(sp.subcase) || sp.subcase < 1) problems.push({ code: "SUBCASE", message: `${name}: subcase는 1 이상 정수` });
    // D3-54: component는 선택(layer와 같은 규칙) — datatype만 필수
    if (!String(sp.datatype ?? "").trim()) problems.push({ code: "SPEC", message: `${name}: datatype이 필요합니다` });
  }
  return { problems, rows };
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
    // S17 §22.3.5 끝난 배치의 H3D 성능 다시 추출
    if (method === "POST" && seg[2] === "extract-responses") {
      if (out.status !== "DONE") return err(409, "BATCH_NOT_DONE", "끝난 일괄 예측만 성능을 다시 추출할 수 있습니다.");
      const ps = srv.paramSets.find((p) => p.id === b.param_set_id)!;
      if (!ps.responses.some((r) => r.spec?.source === "H3D")) return err(422, "NO_H3D_PERFORMANCE", "템플릿에 H3D 성능 정의가 없습니다.");
      return srv.createJob(s, "PB_RESP_EXTRACT", { batch_id: b.id });
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
    // S17 §22.3.1: 진행 중 내장 최적화가 스냅샷한 성능의 spec 변경·삭제는 409(단위만 바뀌는 것은 허용)
    const busy = srv.surrogate.find((o) => o.study_id === ps.study_id && o.param_set_id === ps.id && ["EXPLORING", "FITTING", "VERIFYING", "FINALIZING"].includes(o.status));
    if (busy)
      for (const [name, def] of Object.entries(busy.settings.performances)) {
        const next = v.rows.find((r) => r.name === name);
        if (!next || JSON.stringify(next.spec ?? null) !== JSON.stringify(def.spec))
          return err(409, "PERF_IN_USE_BY_OPT", `내장 최적화 ${`SO-${String(busy.opt_no).padStart(3, "0")}`}이 이 성능을 쓰고 있어 정의를 바꿀 수 없습니다 — 끝난 뒤 바꾸세요`);
      }
    ps.responses = v.rows.map((r) => ({ name: r.name, unit: r.unit ?? "", spec: r.spec ?? null }));
    return ok(ps);
  }
  return null;
};
