// 1차 ④(예측) 목: 예측 결과 산출물, 범위·최근접 검사, ① 결과 파라미터 세트, 완료 처리, 파라미터 세트 라우트(§10.4).
import type { Job, ParamSet, PredictCheck, SampleRow, Study } from "../api/types";
import { PREVIEW_JSON, contourSvg, curveJson, responseFn, seedParamSet } from "./data";
import { err, type Route } from "./route";
import type { MockServer } from "./server";
import { isPrepared, preparedResult } from "./stage4Prepared";
import { batchChildResult, finishBatchParent, isBatchChild } from "./predictBatch";

export function predictResult(srv: MockServer, job: Job, values: Record<string, number>, modelId: string, psId: string) {
  const ps = srv.paramSets.find((p) => p.id === psId)!;
  const chk = check(srv, ps, values);
  const pred = responseFn({ ...values, RIB_N: Math.round(values.RIB_N ?? 4) });
  const img = srv.addArtifact(job.id, job.study_id, "PREVIEW_IMAGE", `04_predict/${job.id}/contour.png`, "image/svg+xml", contourSvg(values));
  const pj = srv.addArtifact(job.id, job.study_id, "PREVIEW_JSON", `04_predict/${job.id}/H3D_PREVIEW.json`, "application/json", JSON.stringify(PREVIEW_JSON));
  const cj = srv.addArtifact(job.id, job.study_id, "CURVE_JSON", `04_predict/${job.id}/curve.json`, "application/json", JSON.stringify(curveJson(values)));
  const applied = { ...values };
  for (const r of chk.rounded) applied[r.name] = r.applied;
  return {
    model_id: modelId,
    param_set_id: psId,
    values,
    applied_values: applied,
    out_of_range: chk.out_of_range.map((o) => o.name),
    nearest: chk.nearest ? { run_key: chk.nearest.run_key, distance: chk.nearest.distance } : null,
    preview_json_artifact_id: pj,
    image_artifact_ids: [img],
    curve_artifact_id: cj,
    response_table_artifact_id: null as string | null,
    response_table: ps.responses.map((r) => {
      const p = pred[r.name] ?? null;
      const m = chk.nearest?.measured?.[r.name] ?? null;
      return { name: r.name, unit: r.unit, predicted: p, nearest_measured: m, diff_pct: p != null && m ? ((p - m) / m) * 100 : null };
    }),
  };
}

export function check(srv: MockServer, ps: ParamSet, values: Record<string, number>): PredictCheck {
  const out_of_range = ps.parameters.filter((p) => values[p.name] < p.min || values[p.name] > p.max).map((p) => ({ name: p.name, value: values[p.name], min: p.min, max: p.max }));
  const ints = ps.tpl_params.filter((t) => /^%[-0-9.]*[id]$/.test(t.format)).map((t) => t.name);
  const rounded = ints.filter((n) => Number.isFinite(values[n])).map((n) => ({ name: n, value: values[n], applied: Math.floor(values[n] + 0.5) }));
  const rows = srv.samples[ps.id] ?? [];
  let best: { row: SampleRow; d: number } | null = null;
  for (const row of rows) {
    let s = 0;
    for (const p of ps.parameters) {
      if (p.max === p.min) continue;
      s += ((values[p.name] - row.values[p.name]) / (p.max - p.min)) ** 2;
    }
    const d = Math.sqrt(s);
    if (!best || d < best.d || (d === best.d && row.run_key < best.row.run_key)) best = { row, d };
  }
  return {
    out_of_range,
    rounded,
    nearest: best ? { run_key: best.row.run_key, distance: best.d, values: best.row.values, measured: ps.sample_has_measured ? best.row.measured : null } : null,
  };
}

/** phase2.md §6.13 F: ① 결과로 파라미터 세트 */
export function addParamSetFromTrain(srv: MockServer, s: Study, doeId: string, sampleCount: number): ParamSet {
  const me = srv.me!;
  srv.paramSets.forEach((p) => p.study_id === s.id && (p.is_current = false));
  const base = seedParamSet();
  const ps: ParamSet = {
    ...base, id: srv.nid("ps"), study_id: s.id, source_path: `① DOE ${doeId.slice(0, 8)}`, sample_count: sampleCount, sample_has_measured: false,
    parameters: base.parameters.filter((p) => p.name !== "E_FOAM"), origin: "TRAIN_DOE", train_doe_id: doeId,
    registered_by_name: me.display_name, registered_at: new Date().toISOString(),
  };
  srv.samples[ps.id] = (srv.p2.doeSamples[doeId] ?? []).slice(0, sampleCount);
  srv.paramSets.unshift(ps);
  return ps;
}

/** ④ 작업 완료 처리(PREDICT·PREDICT_VERIFY) */
export function finishStage4(srv: MockServer, j: Job) {
  const p = j.params as Record<string, unknown>;
  switch (j.job_type) {
    case "PREDICT_BATCH":
      finishBatchParent(srv, j);
      break;
    case "PREDICT": {
      if (isBatchChild(j)) {
        j.result = batchChildResult(srv, j);
        break;
      }
      if (isPrepared(j)) {
        j.result = preparedResult(srv, j);
        break;
      }
      const ps = (p.param_set_id as string) || srv.paramSets.find((x) => x.study_id === j.study_id && x.is_current)?.id || "ps-1";
      const study = srv.studies.find((s) => s.id === j.study_id)!;
      const nominal = Object.fromEntries(srv.paramSets.find((x) => x.id === ps)!.parameters.map((x) => [x.name, x.nominal]));
      j.result = predictResult(srv, j, (p.values as Record<string, number>) ?? nominal, (p.model_id as string) || study.final_model_id || "m-1", ps);
      break;
    }
    case "PREDICT_VERIFY": {
      const pj = srv.jobs.find((x) => x.id === p.predict_job_id);
      const vals = (pj?.params.values ?? {}) as Record<string, number>;
      const r = responseFn(vals);
      j.result = { verify_values: Object.fromEntries(Object.entries(r).map(([k, v]) => [k, Number((v * 1.02).toFixed(3))])) };
      break;
    }
  }
}

/** §10.4 파라미터 세트 단건·샘플 */
export const paramSetRoutes: Route = (srv, { method, seg, query, body }) => {
  if (method === "PATCH" && seg[0] === "param-sets" && seg[1] && !seg[2]) {
    const ps = srv.paramSets.find((p) => p.id === seg[1]);
    if (!ps) return err(404, "NOT_FOUND", "파라미터 세트를 찾을 수 없습니다.");
    ps.label = String(body?.label ?? "").trim() || null;
    return { status: 200, body: ps };
  }
  if (method === "GET" && seg[0] === "param-sets" && seg[1]) {
    const ps = srv.paramSets.find((p) => p.id === seg[1]);
    if (!ps) return err(404, "NOT_FOUND", "파라미터 세트를 찾을 수 없습니다.");
    if (seg[2] === "samples") {
      const rows = srv.samples[ps.id] ?? [];
      const limit = Math.min(200, Number(query.get("limit") ?? 50));
      const start = Number(query.get("cursor") ?? 0);
      const next = start + limit < rows.length ? String(start + limit) : null;
      return { status: 200, body: { columns: ["run_key", ...ps.parameters.map((p) => p.name)], rows: rows.slice(start, start + limit), next_cursor: next } };
    }
    return { status: 200, body: ps };
  }
  return null;
};
