// S14 목(phase3.md §19.5): GET /train-does/{doe_id}/result-table — 해석 DOE 샘플 표(파라미터) + 수집된 run의 응답. 읽기 전용, DB 쓰기 없음.
// 응답은 DOE의 has_run_responses가 true일 때만(시드는 false → responses [] + 안내). 값은 가짜 응답 함수(seed.responseFn), 수집(COLLECTED)된 run만 값이 있다.
import type { DoeResultTable } from "../api/analysis";
import type { TrainDoe } from "../api/types";
import { isIntegerFormat } from "../lib/format";
import { err, ok, type MockResp } from "./route";
import { responseFn } from "./seed";
import type { Phase2Mock } from "./phase2";

export const RESULT_TABLE_MAX_RUNS = 200;

const finite = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

export function doeResultTable(p2: Phase2Mock, d: TrainDoe): MockResp {
  if (d.status !== "READY" || d.sample_status === "MISSING" || d.sample_status === "PENDING") return err(409, "DOE_NOT_READY", "아직 샘플 표가 준비되지 않았습니다");
  const samples = p2.doeSamples[d.id];
  if (!samples) return err(404, "SAMPLES_MISSING", "DOE 샘플 표가 없습니다");
  const runs = p2.runs[d.id] ?? [];
  const state = new Map(runs.map((r) => [r.run_key, r.state]));
  const names = Object.keys(samples[0]?.values ?? {});
  const fmt = new Map((p2.setups[d.study_id]?.tpl?.params ?? []).map((t) => [t.name, t.format]));
  const withResp = d.has_run_responses;
  const respNames = withResp ? Object.keys(responseFn({})) : [];
  const shown = samples.slice(0, RESULT_TABLE_MAX_RUNS);
  const rows = shown.map((s, i) => {
    const st = state.get(s.run_key) ?? "GENERATED";
    const resp = withResp && st === "COLLECTED" ? responseFn(s.values) : null;
    return {
      run_id: s.run_key,
      no: Number(/(\d+)$/.exec(s.run_key)?.[1] ?? i + 1),
      state: st,
      params: Object.fromEntries(names.map((n) => [n, finite(s.values[n]) ? s.values[n] : null])),
      responses: Object.fromEntries(respNames.map((n) => [n, resp && finite(resp[n]) ? Number(resp[n].toFixed(3)) : null])),
    };
  });
  const usable = respNames.length ? rows.filter((r) => respNames.every((n) => finite(r.responses[n]))).length : 0;
  const lhs = /LATIN|LHS/i.test(d.doe_type);
  const notes: string[] = [];
  if (!respNames.length) notes.push("응답 파일이 없습니다");
  if (samples.length > RESULT_TABLE_MAX_RUNS) notes.push(`앞 ${RESULT_TABLE_MAX_RUNS}행만 표시합니다`);
  const body: DoeResultTable = {
    doe_id: d.id,
    label: d.doe_label,
    study_id: d.study_id,
    type: lhs ? "LHS" : d.doe_type,
    parameters: names.map((n) => {
      const vs = samples.map((s) => s.values[n]).filter(finite);
      return { name: n, integer: isIntegerFormat(fmt.get(n)), min: vs.length ? Math.min(...vs) : null, max: vs.length ? Math.max(...vs) : null, unit: null };
    }),
    responses: respNames.map((n) => ({ name: n, unit: null })),
    meta: { engine_version: null, baseline_id: null, scene: null },
    rows,
    counts: { total: rows.length, usable, no_response: rows.length - usable },
    influence_ok: lhs && usable >= Math.max(5, names.length + 2),
    notes,
  };
  return ok(body);
}
