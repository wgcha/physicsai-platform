// phase3.md §14 S9 목(R-F 분할): 조합 계산(batch_matrix 흉내) — lhs·표 붙여넣기·① DOE·S15 새 방식(mockDesign).
import type { BatchPreviewRow, BatchNote, BatchProblem, BatchSource, ParamSet } from "../api/types";
import { isIntegerFormat } from "../lib/format";
import { rng } from "./data";
import { err, type MockResp } from "./route";
import { isNewKind, mockDesign } from "./sampling";
import type { MockServer } from "./server";
import { BATCH_MAX_RUNS, BATCH_TABLE_MAX_BYTES, batchRunKey, round4 } from "./predictBatchRec";

// ------------------------------------------------------------------ 조합 계산
export function applyRows(ps: ParamSet, raw: { doe_no: number; values: Record<string, number> }[]): BatchPreviewRow[] {
  const ints = new Set(ps.tpl_params.filter((t) => isIntegerFormat(t.format)).map((t) => t.name));
  return raw.map(({ doe_no, values }) => {
    const applied: Record<string, number> = {};
    for (const p of ps.parameters) applied[p.name] = ints.has(p.name) ? Math.floor(values[p.name] + 0.5) : values[p.name];
    const out = ps.parameters.filter((p) => applied[p.name] < p.min || applied[p.name] > p.max).map((p) => p.name);
    return { doe_no, run_key: batchRunKey(doe_no), values, applied_values: applied, out_of_range: out };
  });
}

export function lhs(ps: ParamSet, count: number, seed: number, ranges: Record<string, [number, number]>): BatchPreviewRow[] {
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

export const isResp = (x: unknown): x is MockResp => !!x && typeof x === "object" && "status" in x;
