// phase3.md §18 S13·§22 S17 목: 플랫폼 내장 최적화(미리보기·생성·목록·상세·runs.csv·취소·이어서 실행·추가 검증 verify). 재사용 배치 지표는 S12 목(predictBatch design-map).
// 진행은 엔진 tick마다 한 단계(탐색 → 학습 → 검증 → … → 완료). 목적 값 = seed.responseFn(예측 흉내). S17: 목적 1~3·제약 ≤/≥/범위·관찰·가중치, 파레토·HV·예측 전선(상세 계산은 서버 몫 — 목은 흉내).
// R-F 분할(동작 불변): 기록·타입 surrogateOptRec · 지표·표본·전선 계산 surrogateOptMath · 진행·마무리 surrogateOptAdvance · 상세 응답 surrogateOptDetail · 요청 정규화·생성 surrogateOptCreate. 옛 import 경로는 아래에서 재노출한다.
import { err, needPower, ok, type Route } from "./route";
import type { MockServer } from "./server";
import { iso, responseFn } from "./data";
import { perfRows } from "../stages/stage5/surrogate/perfRules";
import { ACTIVE, soInput, soLabel } from "./surrogateOptRec";
import type { SoRec } from "./surrogateOptRec";
import { addRun, metricValue } from "./surrogateOptMath";
import { advance, batchRef } from "./surrogateOptAdvance";
import { detail } from "./surrogateOptDetail";
import { newRec, normalize } from "./surrogateOptCreate";
import { capability } from "./inputKind";
export { soLabel } from "./surrogateOptRec";
export { advance } from "./surrogateOptAdvance";

/** 시드: s-cushion에 완료된 SO-001(단일 목적) · SO-002(2목적) · SO-003(3목적, 커브 성능 포함) — 모두 쿠션 단독 템플릿(ps-2) */
export function seedSurrogate(srv: MockServer) {
  const power = { id: "u-power", name: "김연구" };
  const n = normalize(srv, "s-cushion", {
    param_set_id: "ps-2", explore: { kind: "new", count: 16, seed: 1 }, objective: { metric: "resp:MaxStress_MAX", sense: "min" },
    constraints: [{ metric: "resp:MaxDisp_MAX", op: "<=", value: 14 }], iterations: 3, candidates: 4, tol_rel: 0.01, multi_execution: 4,
  });
  if ("error" in n) return;
  const o = newRec("so-1", "s-cushion", 1, "ps-2", n.settings, power, iso(60 * 3), 10);
  for (let i = 0; i < 20 && o.status !== "DONE"; i++) advance(o, srv);
  o.finished_at = iso(20);
  srv.surrogate.push(o);

  const two = normalize(srv, "s-cushion", {
    param_set_id: "ps-2", explore: { kind: "new", count: 16, seed: 2 },
    objectives: [{ metric: "perf:MaxStress", series: null, sense: "min" }, { metric: "perf:MaxDisp", series: null, sense: "min" }],
    iterations: 3, candidates: 4, tol_rel: 0.001, multi_execution: 4, weights: [50, 50],
  });
  if (!("error" in two)) {
    const o2 = newRec("so-2", "s-cushion", 2, "ps-2", two.settings, power, iso(60 * 2), 30);
    for (let i = 0; i < 20 && o2.status !== "DONE"; i++) advance(o2, srv);
    o2.finished_at = iso(15);
    srv.surrogate.push(o2);
  }
  const three = normalize(srv, "s-cushion", {
    param_set_id: "ps-2", explore: { kind: "new", count: 20, seed: 3 },
    objectives: [{ metric: "perf:MaxStress", series: null, sense: "min" }, { metric: "perf:MaxDisp", series: null, sense: "min" }, { metric: "perf:AccelPeak", series: null, sense: "min" }],
    iterations: 3, candidates: 4, tol_rel: 0.001, multi_execution: 4, weights: [1, 1, 1],
  });
  if (!("error" in three)) {
    three.settings.performances.AccelPeak = { unit: "g", spec: { source: "CURVE", series: "Node 100 / X", stat: "ABSMAX" } };
    const o3 = newRec("so-3", "s-cushion", 3, "ps-2", three.settings, power, iso(60), 50);
    for (let i = 0; i < 20 && o3.status !== "DONE"; i++) advance(o3, srv);
    o3.finished_at = iso(10);
    srv.surrogate.push(o3);
  }
}

export function tickSurrogate(srv: MockServer) {
  for (const o of srv.surrogate) {
    if (ACTIVE.includes(o.status)) advance(o, srv);
    if (o.extra) finishExtra(o);
  }
  // S17 PB_RESP_EXTRACT 완료 → 배치 하위 예측의 응답 표에 H3D 성능 값을 채운다(멱등)
  for (const j of srv.jobs) {
    if (j.job_type !== "PB_RESP_EXTRACT" || j.state !== "SUCCEEDED" || (j as { _applied?: boolean })._applied) continue;
    (j as { _applied?: boolean })._applied = true;
    const b = srv.batches.find((x) => x.id === (j.params as { batch_id?: string }).batch_id);
    const ps = b && srv.paramSets.find((p) => p.id === b.param_set_id);
    if (!b || !ps) continue;
    for (const r of b.runs) {
      const pj = srv.jobs.find((x) => x.id === r.predict_job_id);
      const res = pj?.result as { response_table?: { name: string; unit: string; predicted: number | null; nearest_measured: number | null; diff_pct: number | null }[]; applied_values?: Record<string, number> } | null;
      if (!pj || !res || pj.state !== "SUCCEEDED") continue;
      const pred = responseFn({ ...(res.applied_values ?? r.applied_values), RIB_N: Math.round((res.applied_values ?? r.applied_values).RIB_N ?? 4) }) as Record<string, number>;
      res.response_table = res.response_table ?? [];
      for (const d of perfRows(ps.responses)) {
        if (d.source !== "H3D" || res.response_table.some((q) => q.name === d.name)) continue;
        res.response_table.push({ name: d.name, unit: d.unit, predicted: Number((pred[d.name] ?? metricValue(`perf:${d.name}`, r.applied_values)).toFixed(4)), nearest_measured: null, diff_pct: null });
      }
    }
  }
}

function finishExtra(o: SoRec) {
  const ex = o.extra!;
  if (--ex.ticks > 0) return;
  ex.points.forEach((v, i) => addRun(o, ex.iter_no, i + 1, v, null, "EXTRA"));
  const it = o.iters.find((x) => x.iter_no === ex.iter_no);
  if (it) it.batch = batchRef(o, ex.iter_no, ex.points.length, true);
  o.extra = null;
}

export const surrogateRoutes: Route = (srv, { method, seg, body, me }) => {
  if (seg[0] === "studies" && seg[2] === "surrogate-opts") {
    const s = srv.studies.find((x) => x.id === seg[1]);
    if (!s) return err(404, "NOT_FOUND", "Study를 찾을 수 없습니다.");
    if (method === "GET" && !seg[3])
      return ok(srv.surrogate.filter((o) => o.study_id === s.id).sort((a, b) => b.opt_no - a.opt_no).map((o) => ({
        id: o.id, label: soLabel(o.opt_no), input: soInput(o, srv.paramSets.find((p) => p.id === o.param_set_id)), status: o.status, objective: o.settings.objective, best_value: detail(srv, o).best?.objective ?? null,
        iter_no: o.iter_no, iterations: o.settings.iterations, created_at: o.created_at, created_by_name: o.created_by_name,
      })));
    if (method === "POST" && seg[3] === "preview") {
      const n = normalize(srv, s.id, body ?? {});
      if ("error" in n) return n.error!;
      const st = n.settings;
      const none = st.verification === "none";
      const total = n.count + (none ? 0 : st.iterations * st.candidates);
      const cap = capability(n.ps);
      return ok({ input: n.input, input_capability: cap.cap, input_capability_reason: cap.reason, notes: [], free_variables: n.free, integer_variables: n.integer, fixed: n.fixed, explore_count: n.count,
        max_total_runs: total, estimate_min: Math.round(total * 2.2),
        objective_available: true, problems: n.problems, mode: st.mode, performances: n.info,
        algorithm: st.algorithm, algo_options: st.algo_options, verification: st.verification,
        variables_kind: Object.fromEntries(n.free.map((v) => [v, v === "baseline" ? "categorical" : n.integer.includes(v) ? "integer" : "continuous"])),
        levels: n.levels ? { baseline: n.levels } : null, var_notes: n.varNotes, var_rows: n.varRows, excluded: n.excluded });
    }
    if (method === "POST" && !seg[3]) {
      const deny = needPower(srv, s.project_id);
      if (deny) return deny;
      const n = normalize(srv, s.id, body ?? {});
      if ("error" in n) return n.error!;
      if (n.missing.length) return err(422, "OPT_CRITERIA_REQUIRED", "최적화 기준이 비어 있습니다 — 목적 응답·방향(최소/최대)·제약 임계값·다목적 가중치를 직접 정하세요", { missing: n.missing, problems: n.problems.filter((p) => p.code === "OPT_CRITERIA_REQUIRED") });
      if (n.problems.length) return err(422, "SURROGATE_OPT_INVALID", "내장 최적화 설정이 올바르지 않습니다", { problems: n.problems });
      if (srv.surrogate.some((o) => o.study_id === s.id && ACTIVE.includes(o.status))) return err(409, "SURROGATE_OPT_ACTIVE", "이 Study에 진행 중인 내장 최적화가 있습니다 — 끝나거나 취소한 뒤 시작하세요");
      const no = Math.max(0, ...srv.surrogate.filter((o) => o.study_id === s.id).map((o) => o.opt_no)) + 1;
      const o = newRec(srv.nid("so"), s.id, no, n.ps.id, n.settings, { id: me.user_id, name: me.display_name }, new Date().toISOString(), 20 + no * 5,
        n.settings.explore.kind === "new" ? "EXPLORING" : "FITTING");
      if (o.status === "FITTING") {
        const keep = o.status;
        o.status = "EXPLORING";
        advance(o);
        o.iters[0].kind = "REUSE";
        o.status = keep;
      }
      srv.surrogate.push(o);
      return ok(detail(srv, o), 201);
    }
  }
  if (seg[0] === "surrogate-opts" && seg[1]) {
    const o = srv.surrogate.find((x) => x.id === seg[1]);
    if (!o) return err(404, "SURROGATE_OPT_NOT_FOUND", "내장 최적화를 찾을 수 없습니다");
    const s = srv.studies.find((x) => x.id === o.study_id)!;
    if (method === "GET" && !seg[2]) return ok(detail(srv, o));
    if (method === "GET" && seg[2] === "runs.csv") {
      const st = o.settings;
      const multi = st.mode === "multi";
      const head = ["iter", "batch", "doe_no", "run_key", ...st.names, ...(multi ? st.objectives.map((_, i) => `objective_${i + 1}`) : ["objective"]), ...st.constraints.map((c) => c.metric), ...st.observe.map((c) => `obs:${c.metric}`), "predicted", "feasible", "state"];
      const lines = o.runs.map((r) => [r.iter_no, r.batch_label, r.doe_no, r.run_key, ...st.names.map((n) => (r.values as Record<string, number>)[n]), ...(multi ? (r.objectives ?? []).map((v) => v ?? "") : [r.objective ?? ""]), ...(r.constraints ?? []).map((v) => v ?? ""), ...st.observe.map((c) => r.observed?.[c.metric] ?? ""), r.predicted ?? "", r.feasible == null ? "" : String(r.feasible), r.state].join(","));
      return { status: 200, text: "﻿" + [head.join(","), ...lines].join("\r\n") + "\r\n", contentType: "text/csv" };
    }
    if (method === "POST" && seg[2] === "cancel") {
      const deny = needPower(srv, s.project_id);
      if (deny) return deny;
      if (!me.is_global_admin && o.created_by !== me.user_id) return err(403, "PERMISSION_DENIED", "내장 최적화 등록자 또는 관리자만 취소할 수 있습니다", { required: "owner_or_global_admin" });
      if (ACTIVE.includes(o.status)) {
        o.status = "CANCELED";
        o.stop_reason = "CANCELED";
        o.finished_at = new Date().toISOString();
      }
      return ok(detail(srv, o), 202);
    }
    if (method === "POST" && seg[2] === "resume") {
      const deny = needPower(srv, s.project_id);
      if (deny) return deny;
      if (o.status !== "FAILED") return err(409, "SURROGATE_OPT_NOT_RESUMABLE", "실패한 내장 최적화만 이어서 실행할 수 있습니다");
      o.status = "FITTING";
      o.stop_reason = null;
      return ok({ job_id: srv.nid("j"), batch_retry: null }, 201);
    }
    if (method === "POST" && seg[2] === "verify") {
      const deny = needPower(srv, s.project_id);
      if (deny) return deny;
      if (o.status !== "DONE") return err(409, "SURROGATE_OPT_NOT_DONE", "끝난 내장 최적화만 추가 검증할 수 있습니다");
      if (o.extra) return err(409, "SURROGATE_OPT_EXTRA_ACTIVE", "진행 중인 추가 검증이 있습니다");
      const pts = ((body?.points ?? []) as { values: Record<string, number> }[]).map((p) => p.values);
      if (pts.length < 1 || pts.length > 10) return err(422, "SURROGATE_OPT_INVALID", "추가 검증은 1~10개 점입니다", { problems: [{ code: "POINTS_RANGE", field: "points", message: "점은 1~10개입니다" }] });
      const bad = pts.flatMap((v) => o.settings.names.filter((n) => !(v[n] >= o.settings.bounds[n][0] && v[n] <= o.settings.bounds[n][1])));
      if (bad.length) return err(422, "SURROGATE_OPT_INVALID", "점이 변수 범위 밖입니다", { problems: [{ code: "BOUNDS_OUT_OF_RANGE", field: "points", message: `범위 밖 변수: ${[...new Set(bad)].join(", ")}` }] });
      const iter = Math.max(...o.iters.map((x) => x.iter_no), 0) + 1;
      o.iters.push({ iter_no: iter, kind: "EXTRA", batch: batchRef(o, iter, pts.length, false), fit: null, candidates: null, best_value: null, best_feasible: null, improvement_rel: null });
      o.extra = { iter_no: iter, points: pts, capture: !!body?.capture, ticks: 2 };
      return ok({ batch_id: `b-so-${o.id}-${iter}`, batch_label: `B-${String(o.batch_no + iter).padStart(3, "0")}`, job_id: srv.nid("j"), iter_no: iter }, 201);
    }
  }
  return null;
};

export type { SoRec };
