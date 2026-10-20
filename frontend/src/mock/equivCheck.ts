// ⑤ 등가성 판정 목(equiv-check.md §6): /equiv/recipes CRUD(시스템 기본 sys:default 읽기 전용·버전·소프트 삭제),
// /studies/{id}/equiv-checks preview·create(202, EQ_CHECK 작업)·list(커서)·/equiv-checks/{id}·curves·table.csv·PATCH note.
// 작업이 끝나면(tick) 이력 행을 DONE으로 바꾸고 결정적 지표 값을 만든다(syncEquiv — 종료 훅 흉내).
import type { Job } from "../api/types";
import type { EqCheck, EqCheckListItem, EqCurves, EqDefinition, EqMetric, EqMetricAgg, EqPreview, EqRecipe, EqRow, EqSource } from "../api/equivCheck";
import { baseJob, makeSteps } from "./data";
import { err, needPower, ok, type MockResp, type Route } from "./route";
import type { MockServer } from "./server";
import { batchStatus } from "./predictBatchOut";

export const SYS_KEY = "sys:default";
const SYS_NAME = "시스템 기본(제안값)";
const SYS_RUN_MSG = "시스템 기본 레시피는 제안값입니다 — 복제(다른 이름으로 저장)해 지표·허용오차·필수/참고를 확인한 레시피로 실행하세요";
const PERF_NAMES = ["MaxStress", "MinDisp", "AccPeak"];

export interface RecipeRec {
  key: string;
  version: number;
  scope: "study" | "global";
  study_id: string | null;
  name: string;
  description: string;
  definition: EqDefinition;
  parent: { key: string; version: number } | null;
  created_by: string;
  created_by_name: string;
  created_at: string;
  deleted: boolean;
}

export interface EqRec {
  id: string;
  study_id: string;
  eq_no: number;
  job_id: string | null;
  status: EqCheck["status"];
  verdict: EqCheck["verdict"];
  recipe: EqCheck["recipe"];
  snapshot: EqDefinition;
  side_a: { kind: string; ref: string; label: string };
  side_b: { kind: string; ref: string; label: string };
  pairs: { no: number; a: string; b: string }[];
  mode: EqCheck["pairing"]["mode"];
  note: string | null;
  created_by: string;
  created_by_name: string;
  created_at: string;
  finished_at: string | null;
  rows: EqRow[];
  warnings: { code: string; message: string }[];
}

export const systemDefinition = (): EqDefinition => {
  const sc = (id: string, label: string, rel: number, required: boolean): EqMetric => ({ id, label, kind: "scalar", source: null, tol: { rel_pct: rel, abs: null }, required });
  return {
    schema_version: 1,
    metrics: [
      sc("accel_peak", "가속도 피크", 5, true),
      sc("cushion_deform", "쿠션 최대 변형", 5, true),
      sc("ie_max", "내부 에너지 최대", 5, true),
      sc("ke_max", "운동 에너지 최대", 5, true),
      sc("stress_peak", "응력 피크", 10, false),
      sc("contact_peak", "접촉력 피크", 10, false),
      { id: "accel_corr", label: "가속도 곡선 상관", kind: "curve_corr", source: { type: "curve", series: null, t01: null }, tol: { corr_min: 0.95 }, required: true },
      { id: "volume_diff", label: "쿠션 부피 차", kind: "mesh_volume", source: { type: "mesh_volume", parts: "cushion", origin: "mesh" }, tol: { rel_pct: 0.1, abs: null }, required: true },
    ],
    pair_rule: { mode: "all" },
    verdict_rule: "required_all",
  };
};

const latestOf = (srv: MockServer, key: string): RecipeRec | undefined => srv.eqRecipes.filter((r) => r.key === key).sort((a, b) => b.version - a.version)[0];

function recipeOut(srv: MockServer, r: RecipeRec, full: boolean): EqRecipe {
  const me = srv.me!;
  const canEdit = !r.deleted && (r.scope === "global" ? me.is_global_admin || r.created_by === me.user_id : srv.role(srv.studies.find((s) => s.id === r.study_id)?.project_id ?? "") !== "general");
  return {
    key: r.key, version: r.version, name: r.name, description: r.description, scope: r.scope, study_id: r.study_id, metrics_count: r.definition.metrics.length,
    updated_at: r.created_at, updated_by_name: r.created_by_name, readonly: false, deleted: r.deleted, can_edit: canEdit,
    definition: full ? r.definition : (undefined as unknown as EqDefinition), parent: r.parent,
    versions: full ? srv.eqRecipes.filter((x) => x.key === r.key).sort((a, b) => b.version - a.version).map((v) => ({ version: v.version, created_at: v.created_at, created_by_name: v.created_by_name, name: v.name })) : null,
  };
}

const sysOut = (): EqRecipe => ({
  key: SYS_KEY, version: 1, name: SYS_NAME, description: "시스템 제안값 — 복제해서 허용오차·필수 여부·원천 연결을 사용자가 정합니다", scope: "system", study_id: null,
  metrics_count: 8, updated_at: null, updated_by_name: null, readonly: true, deleted: false, can_edit: false, definition: systemDefinition(), parent: null, versions: null,
});

function validate(d: unknown): MockResp | null {
  const def = d as Partial<EqDefinition> | null;
  if (!def || !Array.isArray(def.metrics)) return err(422, "EQ_RECIPE_INVALID", "레시피 정의가 올바르지 않습니다.", { problems: [{ code: "METRICS_RANGE", message: "지표 목록이 필요합니다" }] });
  if (def.metrics.length < 1 || def.metrics.length > 20) return err(422, "EQ_RECIPE_INVALID", "레시피 정의가 올바르지 않습니다.", { problems: [{ code: "METRICS_RANGE", message: `지표는 1~20개여야 합니다(현재 ${def.metrics.length}개)` }] });
  for (const m of def.metrics as EqMetric[]) {
    if (!/^[a-z][a-z0-9_]{0,31}$/.test(m.id)) return err(422, "EQ_RECIPE_INVALID", "레시피 정의가 올바르지 않습니다.", { problems: [{ code: "METRIC_ID_INVALID", message: `지표 id가 올바르지 않습니다: ${m.id}` }] });
    const t = m.tol ?? {};
    if ((m.kind === "scalar" || m.kind === "mesh_volume") && t.rel_pct == null && t.abs == null) return err(422, "EQ_RECIPE_INVALID", "레시피 정의가 올바르지 않습니다.", { problems: [{ code: "TOL_INVALID", message: "상대 % 또는 절대값 중 하나 이상이 필요합니다", metric_id: m.id }] });
    if ((t.rel_pct ?? 0) < 0 || (t.abs ?? 0) < 0) return err(422, "EQ_RECIPE_INVALID", "레시피 정의가 올바르지 않습니다.", { problems: [{ code: "TOL_INVALID", message: "허용오차는 0 이상이어야 합니다", metric_id: m.id }] });
  }
  return null;
}

// ---- 결과 집합 흉내 --------------------------------------------------------------------------------

function sideRuns(srv: MockServer, s: { kind: string; doe_id?: string; batch_id?: string; fv_id?: string; paths?: string[] }): { label: string; ref: string; runs: { name: string; params: Record<string, number> | null }[] } | null {
  if (s.kind === "train_doe") {
    const d = srv.p2.does.find((x) => x.id === s.doe_id);
    if (!d || d.status !== "READY") return null;
    const rows = srv.p2.doeSamples[d.id] ?? [];
    return { label: `① ${d.doe_label}`, ref: d.id, runs: rows.slice(0, 30).map((r) => ({ name: r.run_key, params: r.values })) };
  }
  if (s.kind === "predict_batch") {
    const b = srv.batches.find((x) => x.id === s.batch_id);
    if (!b || batchStatus(srv, b) !== "DONE") return null;
    return { label: `④ B-${String(b.batch_no).padStart(3, "0")}`, ref: b.id, runs: b.runs.map((r) => ({ name: r.run_key, params: r.values })) };
  }
  if (s.kind === "fem_verify") {
    const f = srv.fems.find((x) => x.id === s.fv_id);
    if (!f || f.status !== "DONE") return null;
    return { label: `FEM 검증 FV-${String(f.fv_no).padStart(3, "0")}`, ref: f.id, runs: [{ name: `FV-${String(f.fv_no).padStart(3, "0")}`, params: null }] };
  }
  if (s.kind === "folder") {
    const paths = s.paths ?? [];
    return { label: `폴더 ${paths.length}개`, ref: "folder", runs: paths.map((p) => ({ name: p.replace(/[\\/]+$/, "").split(/[\\/]/).pop() ?? p, params: null })) };
  }
  return null;
}

function pair(mode: string, a: { name: string; params: Record<string, number> | null }[], b: { name: string; params: Record<string, number> | null }[], manual: { a: string; b: string }[] | null) {
  const pairs: { no: number; a: string; b: string }[] = [];
  const usedB = new Set<string>();
  const problems: EqPreview["problems"] = [];
  if (mode === "manual") {
    for (const p of manual ?? []) if (a.some((x) => x.name === p.a) && b.some((x) => x.name === p.b)) pairs.push({ no: pairs.length + 1, a: p.a, b: p.b });
  } else if (mode === "by_params") {
    const na = new Set(a.flatMap((r) => Object.keys(r.params ?? {})));
    const nb = new Set(b.flatMap((r) => Object.keys(r.params ?? {})));
    if ([...na].sort().join() !== [...nb].sort().join()) {
      problems.push({ code: "PARAM_SET_MISMATCH", message: "두 쪽 파라미터 이름 집합이 다릅니다", only_a: [...na].filter((x) => !nb.has(x)), only_b: [...nb].filter((x) => !na.has(x)) });
    } else {
      for (const r of a) {
        const hit = b.find((s) => !usedB.has(s.name) && [...na].every((n) => Math.abs((r.params?.[n] ?? 0) - (s.params?.[n] ?? 0)) <= 1e-6 * Math.max(1, Math.abs(r.params?.[n] ?? 0))));
        if (hit) {
          usedB.add(hit.name);
          pairs.push({ no: pairs.length + 1, a: r.name, b: hit.name });
        }
      }
    }
  } else {
    for (const r of a) {
      const hit = b.find((s) => !usedB.has(s.name) && s.name === r.name) ?? b.find((s) => !usedB.has(s.name) && s.name.toLowerCase() === r.name.toLowerCase());
      if (hit) {
        usedB.add(hit.name);
        pairs.push({ no: pairs.length + 1, a: r.name, b: hit.name });
      }
    }
    if (!pairs.length && a.length === 1 && b.length === 1) pairs.push({ no: 1, a: a[0].name, b: b[0].name });
  }
  const pa = new Set(pairs.map((p) => p.a));
  if (!problems.length && !pairs.length) problems.push({ code: "NO_PAIRS", message: "짝이 맞는 run이 없습니다" });
  return { pairs, unmatched_a: a.filter((r) => !pa.has(r.name)).map((r) => r.name), unmatched_b: b.filter((r) => !usedB.has(r.name)).map((r) => r.name), problems };
}

function resolveRecipe(srv: MockServer, body: Record<string, unknown>): { def: EqDefinition; ref: EqCheck["recipe"] } | MockResp {
  const rec = body.recipe as { key: string; version?: number | null } | undefined;
  const inline = body.recipe_inline as { definition: EqDefinition; base?: { key: string; version?: number | null } | null } | undefined;
  if ((rec ? 1 : 0) + (inline ? 1 : 0) !== 1) return err(422, "EQ_CHECK_INVALID", "레시피를 선택하세요(recipe 또는 recipe_inline 중 하나)", { problems: [{ code: "RECIPE_REQUIRED", message: "판정에는 사용자가 선택·확인한 레시피가 필요합니다" }] });
  if (inline) {
    const bad = validate(inline.definition);
    if (bad) return bad;
    const base = inline.base ? (inline.base.key === SYS_KEY ? sysOut() : latestOf(srv, inline.base.key)) : null;
    return { def: inline.definition, ref: { source: base ? (inline.base!.key === SYS_KEY ? "system" : "user") : "adhoc", key: inline.base?.key ?? null, version: inline.base?.version ?? base?.version ?? null, modified: true, name: base?.name ?? null, deleted: false, current_version: base?.version ?? null } };
  }
  if (rec!.key === SYS_KEY) return { def: systemDefinition(), ref: { source: "system", key: SYS_KEY, version: 1, modified: false, name: SYS_NAME, deleted: false, current_version: 1 } };
  const r = rec!.version ? srv.eqRecipes.find((x) => x.key === rec!.key && x.version === rec!.version) : latestOf(srv, rec!.key);
  if (!r || r.deleted) return err(404, "EQ_RECIPE_NOT_FOUND", "레시피를 찾을 수 없습니다.");
  return { def: r.definition, ref: { source: "user", key: r.key, version: r.version, modified: false, name: r.name, deleted: false, current_version: latestOf(srv, r.key)!.version } };
}

function bind(def: EqDefinition, bindings: Record<string, EqSource | null> | null | undefined): EqDefinition {
  return { ...def, metrics: def.metrics.map((m) => (m.source === null && bindings?.[m.id] ? { ...m, source: bindings[m.id]! } : m)) };
}

function previewOf(srv: MockServer, body: Record<string, unknown>): MockResp {
  const rr = resolveRecipe(srv, body);
  if ("status" in rr) return rr;
  const def = bind(rr.def, body.bindings as Record<string, EqSource | null> | null);
  const problems: EqPreview["problems"] = [];
  const a = sideRuns(srv, body.side_a as { kind: string });
  const b = sideRuns(srv, body.side_b as { kind: string });
  if (!a) problems.push({ code: "SIDE_NOT_FOUND", message: "A 쪽 결과 집합을 찾을 수 없거나 준비되지 않았습니다", side: "a" });
  if (!b) problems.push({ code: "SIDE_NOT_FOUND", message: "B 쪽 결과 집합을 찾을 수 없거나 준비되지 않았습니다", side: "b" });
  if (rr.ref.source === "system") problems.push({ code: "RECIPE_NOT_CONFIRMED", message: SYS_RUN_MSG });
  for (const m of def.metrics) if (m.source === null && m.kind !== "mesh_volume") problems.push({ code: "METRIC_UNBOUND", message: `지표 '${m.label}'의 응답이 연결되지 않았습니다 — 성능 정의(응답)를 선택하거나 레시피에서 지표를 빼세요`, metric_id: m.id });
  const pg = (body.pairing as { mode: string; pairs?: { a: string; b: string }[] | null }) ?? { mode: "by_name" };
  const pr = a && b ? pair(pg.mode, a.runs, b.runs, pg.pairs ?? null) : { pairs: [], unmatched_a: [], unmatched_b: [], problems: [] };
  problems.push(...pr.problems);
  const side = (s: ReturnType<typeof sideRuns>, kind: string) => ({ kind, ref: s?.ref ?? "", label: s?.label ?? "", run_count: s?.runs.length ?? 0, ok_count: s?.runs.length ?? 0, responses: PERF_NAMES, runs: (s?.runs ?? []).map((r, i) => ({ name: r.name, no: i + 1, ok: true, state: "COLLECTED", has_h3d: true, has_t01: true, has_curve: kind === "predict_batch", has_mesh: true })) });
  const out: EqPreview = {
    side_a: side(a, (body.side_a as { kind: string }).kind), side_b: side(b, (body.side_b as { kind: string }).kind),
    pairing: { mode: pg.mode as EqPreview["pairing"]["mode"], n_pairs: pr.pairs.length, n_unmatched_a: pr.unmatched_a.length, n_unmatched_b: pr.unmatched_b.length },
    pairs: pr.pairs, unmatched_a: pr.unmatched_a, unmatched_b: pr.unmatched_b,
    metrics: def.metrics.map((m) => ({ id: m.id, label: m.label, kind: m.kind, required: m.required, source: m.source, tol: m.tol, tol_text: "", bound: m.source !== null || m.kind === "mesh_volume", a: null, b: null, na: null })),
    extract: { h3d_runs: pr.pairs.length * 2, t01_runs: pr.pairs.length, copy_bytes: pr.pairs.length * 12345678 }, problems, warnings: [], can_run: problems.length === 0,
  };
  return ok(out);
}

// ---- 결과 흉내(결정적) -----------------------------------------------------------------------------

function hash(s: string): number {
  let h = 0;
  for (const c of s) h = (h * 31 + c.charCodeAt(0)) % 100000;
  return h;
}

function computeRows(rec: EqRec): EqRow[] {
  const rows: EqRow[] = [];
  for (const p of rec.pairs) {
    for (const m of rec.snapshot.metrics) {
      const base = 100 + (hash(m.id) % 50);
      const same = rec.side_a.ref === rec.side_b.ref;
      const wob = same ? 0 : ((hash(p.a + m.id) % 90) - 30) / 10; // -3%~+6%
      if (m.kind === "curve_corr" || m.kind === "curve_nrmse") {
        const corr = same ? 1 : 0.999 - (hash(p.b + m.id) % 80) / 1000;
        const status = m.kind === "curve_corr" ? (corr >= (m.tol.corr_min ?? 0) ? "PASS" : "FAIL") : (1 - corr) * 100 <= (m.tol.nrmse_max_pct ?? 5) ? "PASS" : "FAIL";
        rows.push({ pair_no: p.no, a_run: p.a, b_run: p.b, metric_id: m.id, a: null, b: null, diff: null, rel_pct: m.kind === "curve_nrmse" ? (1 - corr) * 100 : null, corr: m.kind === "curve_corr" ? corr : null, status, reason: null, reason_text: null });
        continue;
      }
      if (m.source === null && m.kind !== "mesh_volume") {
        rows.push({ pair_no: p.no, a_run: p.a, b_run: p.b, metric_id: m.id, a: null, b: null, diff: null, rel_pct: null, corr: null, status: "NA", reason: "UNBOUND", reason_text: "원천 미연결" });
        continue;
      }
      const a = m.kind === "mesh_volume" ? 12345.6 : base;
      const b = a * (1 + wob / 100);
      const diff = b - a;
      const rel = (diff / Math.abs(a)) * 100;
      const okRel = m.tol.rel_pct != null && Math.abs(rel) <= m.tol.rel_pct;
      const okAbs = m.tol.abs != null && Math.abs(diff) <= m.tol.abs;
      rows.push({ pair_no: p.no, a_run: p.a, b_run: p.b, metric_id: m.id, a, b, diff, rel_pct: rel, corr: null, status: okRel || okAbs ? "PASS" : "FAIL", reason: null, reason_text: null });
    }
  }
  return rows;
}

function aggregates(rec: EqRec): EqMetricAgg[] {
  return rec.snapshot.metrics.map((m) => {
    const rows = rec.rows.filter((r) => r.metric_id === m.id);
    const n_pass = rows.filter((r) => r.status === "PASS").length;
    const n_fail = rows.filter((r) => r.status === "FAIL").length;
    const n_na = rows.length - n_pass - n_fail;
    const mean = (k: "a" | "b") => {
      const v = rows.map((r) => r[k]).filter((x): x is number => x != null);
      return v.length ? v.reduce((s, x) => s + x, 0) / v.length : null;
    };
    const worst = rows.filter((r) => r.rel_pct != null).sort((x, y) => Math.abs(y.rel_pct!) - Math.abs(x.rel_pct!))[0];
    const corrs = rows.map((r) => r.corr).filter((x): x is number => x != null);
    const tolText = m.kind === "curve_corr" ? `r ≥ ${m.tol.corr_min}` : m.kind === "curve_nrmse" ? `NRMSE ≤ ${m.tol.nrmse_max_pct}%` : [m.tol.rel_pct != null ? `상대 ${m.tol.rel_pct}%` : "", m.tol.abs != null ? `절대 ${m.tol.abs}` : ""].filter(Boolean).join(" 또는 ");
    return {
      id: m.id, label: m.label, kind: m.kind, required: m.required, tol: m.tol, tol_text: tolText, source: m.source,
      status: n_pass + n_fail === 0 ? "NA" : rec.snapshot.pair_rule.mode === "min_ratio" ? (n_pass / (n_pass + n_fail) >= (rec.snapshot.pair_rule.ratio ?? 1) ? "PASS" : "FAIL") : n_fail ? "FAIL" : "PASS",
      n_pairs: rows.length, n_pass, n_fail, n_na, a_mean: mean("a"), b_mean: mean("b"), max_abs_rel_pct: worst?.rel_pct != null ? Math.abs(worst.rel_pct) : null,
      max_abs_diff: worst?.diff != null ? Math.abs(worst.diff) : null, min_corr: corrs.length ? Math.min(...corrs) : null, worst_pair: worst ? `${worst.a_run} ↔ ${worst.b_run}` : null,
    };
  });
}

function verdictOf(rec: EqRec): { verdict: EqCheck["verdict"]; summary: NonNullable<EqCheck["summary"]> } {
  const aggs = aggregates(rec);
  const req = aggs.filter((a) => a.required);
  const ref = aggs.filter((a) => !a.required);
  const required_fail = req.filter((a) => a.status === "FAIL").length;
  const required_pass = req.filter((a) => a.status === "PASS").length;
  const verdict: EqCheck["verdict"] = required_fail ? "FAIL" : req.length && required_pass === req.length ? "PASS" : "INCOMPLETE";
  return { verdict, summary: { verdict: { required_total: req.length, required_pass, required_fail, reference_total: ref.length, reference_fail: ref.filter((a) => a.status === "FAIL").length }, n_pairs: rec.pairs.length } };
}

export function syncEquiv(srv: MockServer) {
  for (const rec of srv.eqChecks.filter((r) => r.status === "RUNNING" && r.job_id)) {
    const j = srv.jobs.find((x) => x.id === rec.job_id);
    if (!j) continue;
    if (j.state === "SUCCEEDED") {
      rec.rows = computeRows(rec);
      rec.verdict = verdictOf(rec).verdict;
      rec.status = "DONE";
      rec.finished_at = new Date().toISOString();
      srv.notifs.unshift({ seq: ++srv.seq, user_id: rec.created_by, event: "EQ_CHECK_DONE", job_id: j.id, study_id: rec.study_id, project_id: j.project_id, title: `등가성 판정 ${label(rec.eq_no)} ${rec.verdict === "PASS" ? "통과" : rec.verdict === "FAIL" ? "미달" : "판정 불가"} — 쌍 ${rec.pairs.length}`, body: "해석 등가성 판정이 끝났습니다.", created_at: new Date().toISOString(), read_at: null });
    } else if (j.state === "FAILED" || j.state === "INTERRUPTED") {
      rec.status = "FAILED";
      rec.finished_at = new Date().toISOString();
    } else if (j.state === "CANCELED") {
      rec.status = "CANCELED";
      rec.finished_at = new Date().toISOString();
    }
  }
}

const label = (no: number) => `EQ-${String(no).padStart(3, "0")}`;
const STATUS_TEXT: Record<EqCheck["status"], string> = { RUNNING: "실행 중", DONE: "완료", FAILED: "실패", CANCELED: "취소" };
const VERDICT_TEXT = { PASS: "통과", FAIL: "미달", INCOMPLETE: "판정 불가" } as const;

function itemOf(srv: MockServer, rec: EqRec): EqCheckListItem {
  const v = rec.status === "DONE" ? verdictOf(rec) : null;
  const cur = rec.recipe.key && rec.recipe.key !== SYS_KEY ? latestOf(srv, rec.recipe.key) : null;
  return {
    id: rec.id, label: label(rec.eq_no), eq_no: rec.eq_no, status: rec.status, status_text: STATUS_TEXT[rec.status], verdict: rec.verdict,
    verdict_text: rec.verdict ? VERDICT_TEXT[rec.verdict] : null, side_a: rec.side_a, side_b: rec.side_b,
    pairing: { mode: rec.mode, n_pairs: rec.pairs.length, n_unmatched_a: 0, n_unmatched_b: 0 },
    recipe: { ...rec.recipe, deleted: cur?.deleted ?? false, current_version: cur?.version ?? rec.recipe.current_version },
    summary_line: v ? `필수 ${v.summary.verdict!.required_pass}/${v.summary.verdict!.required_total} · 참고 미달 ${v.summary.verdict!.reference_fail} · 쌍 ${rec.pairs.length} · ${rec.recipe.name ?? "1회용"}${rec.recipe.version ? ` v${rec.recipe.version}` : ""}${rec.recipe.modified ? "(수정됨)" : ""}` : null,
    note: rec.note, created_at: rec.created_at, created_by: rec.created_by, created_by_name: rec.created_by_name, finished_at: rec.finished_at, job_id: rec.job_id,
  };
}

function detailOf(srv: MockServer, rec: EqRec): EqCheck {
  const j = rec.job_id ? srv.jobs.find((x) => x.id === rec.job_id) ?? null : null;
  const v = rec.status === "DONE" ? verdictOf(rec) : null;
  const me = srv.me!;
  return {
    ...itemOf(srv, rec), recipe_snapshot: { ...rec.snapshot, recipe: { name: rec.recipe.name } }, summary: v?.summary ?? null,
    metrics: rec.status === "DONE" ? aggregates(rec) : rec.snapshot.metrics.map((m) => ({ id: m.id, label: m.label, kind: m.kind, required: m.required, tol: m.tol, tol_text: "", source: m.source, status: "NA" as const })),
    rows: rec.rows, pairs: rec.pairs, unmatched_a: [], unmatched_b: [], warnings: rec.warnings, failure: rec.status === "FAILED" ? { code: "INTERNAL_ERROR", message: "작업 실패" } : null,
    job: j ? { id: j.id, study_id: j.study_id, project_id: j.project_id, study_title: j.study_title, job_type: j.job_type, stage: j.stage, stage_label: "⑤", lane: j.lane, state: j.state, created_by: j.created_by, created_by_name: j.created_by_name, queue_position: j.queue_position, progress_pct: j.progress_pct, progress_label: j.progress_label, cancel_requested: j.cancel_requested, created_at: j.created_at, started_at: j.started_at, current_step_key: null, current_step_label: null, hpc_summary: null, attention_code: null, batch: null } : null,
    dir: `E:\\shared\\AI_WORK\\cushion_v1\\05_equiv\\${label(rec.eq_no)}`, can_edit_note: me.is_global_admin || rec.created_by === me.user_id,
    can_cancel: !!j && me.is_global_admin && !["SUCCEEDED", "FAILED", "CANCELED", "INTERRUPTED"].includes(j.state), can_retry: !!j && ["FAILED", "CANCELED", "INTERRUPTED"].includes(j.state),
  };
}

function curvesOf(rec: EqRec, pairNo: number, metric: string): MockResp {
  const p = rec.pairs.find((x) => x.no === pairNo);
  const m = rec.snapshot.metrics.find((x) => x.id === metric);
  if (!p || !m || (m.kind !== "curve_corr" && m.kind !== "curve_nrmse")) return err(404, "EQ_CHECK_NOT_FOUND", "곡선을 찾을 수 없습니다(곡선 지표가 아니거나 계산되지 않음)");
  const n = 50;
  const t = Array.from({ length: n }, (_x, i) => i / (n - 1) * 0.02);
  const a = t.map((x) => 120 * Math.sin((x / 0.02) * Math.PI));
  const same = rec.side_a.ref === rec.side_b.ref;
  const b = a.map((y, i) => (same ? y : y * 1.03 + 2 * Math.sin(i / 3)));
  const row = rec.rows.find((r) => r.pair_no === pairNo && r.metric_id === metric);
  const out: EqCurves = { pair_no: pairNo, metric_id: metric, a_run: p.a, b_run: p.b, t, a, b, corr: row?.corr ?? (same ? 1 : 0.98), nrmse_pct: same ? 0 : 3.1, overlap_ratio: 1, downsampled: false };
  return ok(out);
}

// ---- 라우트 -------------------------------------------------------------------------------------------

export const equivRoutes: Route = (srv, { method, seg, query, body, me }) => {
  if (seg[0] === "equiv" && seg[1] === "recipes") {
    const key = seg[2] ? decodeURIComponent(seg[2]) : null;
    if (method === "GET" && !key) {
      const sid = query.get("study_id");
      const latest = new Map<string, RecipeRec>();
      for (const r of srv.eqRecipes) if (r.scope === "global" || r.study_id === sid) if (!latest.has(r.key) || latest.get(r.key)!.version < r.version) latest.set(r.key, r);
      return ok([{ ...sysOut(), definition: undefined }, ...[...latest.values()].filter((r) => !r.deleted).map((r) => ({ ...recipeOut(srv, r, false), definition: undefined }))]);
    }
    if (method === "POST" && !key) {
      const b = body ?? {};
      const scope = (b.scope as "study" | "global") ?? "study";
      const sid = scope === "study" ? (b.study_id as string) : null;
      const s = sid ? srv.studies.find((x) => x.id === sid) : null;
      if (scope === "study" && !s) return err(404, "NOT_FOUND", "Study를 찾을 수 없습니다.");
      const denied = s ? needPower(srv, s.project_id) : me.is_global_admin || Object.values(me.roles).some((r) => r === "power" || r === "admin") ? null : err(403, "PERMISSION_DENIED", "실행 권한(power 이상)이 필요합니다.", { required: "power" });
      if (denied) return denied;
      let def: EqDefinition;
      let parent: RecipeRec["parent"] = null;
      if (b.clone_from) {
        const cf = b.clone_from as { key: string; version?: number | null };
        if (cf.key === SYS_KEY) {
          def = systemDefinition();
          parent = { key: SYS_KEY, version: 1 };
        } else {
          const src = cf.version ? srv.eqRecipes.find((x) => x.key === cf.key && x.version === cf.version) : latestOf(srv, cf.key);
          if (!src) return err(404, "EQ_RECIPE_NOT_FOUND", "레시피를 찾을 수 없습니다.");
          def = src.definition;
          parent = { key: src.key, version: src.version };
        }
      } else if (b.from_check) {
        const c = srv.eqChecks.find((x) => x.id === b.from_check);
        if (!c) return err(404, "EQ_CHECK_NOT_FOUND", "판정 이력을 찾을 수 없습니다.");
        def = c.snapshot;
        parent = c.recipe.key && c.recipe.version ? { key: c.recipe.key, version: c.recipe.version } : null;
      } else {
        const bad = validate(b.definition);
        if (bad) return bad;
        def = b.definition as EqDefinition;
      }
      const name = String(b.name ?? "").trim();
      if (srv.eqRecipes.some((r) => !r.deleted && r.scope === scope && r.study_id === sid && r.name.toLowerCase() === name.toLowerCase())) return err(409, "EQ_RECIPE_NAME_TAKEN", `같은 범위에 같은 이름의 레시피가 있습니다: ${name}`);
      const rec: RecipeRec = { key: srv.nid("rcp"), version: 1, scope, study_id: sid, name, description: String(b.description ?? ""), definition: def, parent, created_by: me.user_id, created_by_name: me.display_name, created_at: new Date().toISOString(), deleted: false };
      srv.eqRecipes.push(rec);
      return ok(recipeOut(srv, rec, true), 201);
    }
    if (!key) return null;
    if (key === SYS_KEY) {
      if (method === "GET") return ok(sysOut());
      return err(409, "EQ_RECIPE_READONLY", "시스템 기본 레시피는 수정·삭제할 수 없습니다 — 복제해서 사용하세요");
    }
    const cur = latestOf(srv, key);
    if (!cur) return err(404, "EQ_RECIPE_NOT_FOUND", "레시피를 찾을 수 없습니다.");
    if (method === "GET") {
      const v = query.get("version");
      const r = v ? srv.eqRecipes.find((x) => x.key === key && x.version === Number(v)) : cur;
      return r ? ok(recipeOut(srv, r, true)) : err(404, "EQ_RECIPE_NOT_FOUND", "레시피를 찾을 수 없습니다.");
    }
    const owner = cur.scope === "global" ? (me.is_global_admin || cur.created_by === me.user_id ? null : err(403, "PERMISSION_DENIED", "전역 레시피는 작성자 또는 관리자만 고칠 수 있습니다", { required: "owner" })) : needPower(srv, srv.studies.find((s) => s.id === cur.study_id)?.project_id ?? "");
    if (method === "PUT") {
      if (owner) return owner;
      if (cur.deleted) return err(404, "EQ_RECIPE_NOT_FOUND", "삭제된 레시피입니다(관리자 되살리기 후 편집)");
      const b = body ?? {};
      if (Number(b.base_version) !== cur.version) return err(409, "EQ_RECIPE_VERSION_CONFLICT", `레시피가 다른 곳에서 바뀌었습니다(현재 v${cur.version}, 요청 v${b.base_version})`, { current_version: cur.version });
      const bad = validate(b.definition);
      if (bad) return bad;
      const rec: RecipeRec = { ...cur, version: cur.version + 1, name: String(b.name ?? cur.name), description: b.description == null ? cur.description : String(b.description), definition: b.definition as EqDefinition, created_by: me.user_id, created_by_name: me.display_name, created_at: new Date().toISOString() };
      srv.eqRecipes.push(rec);
      return ok(recipeOut(srv, rec, true));
    }
    if (method === "DELETE") {
      if (owner) return owner;
      srv.eqRecipes.filter((r) => r.key === key).forEach((r) => (r.deleted = true));
      return { status: 204 };
    }
    if (method === "POST" && seg[3] === "restore") {
      if (!me.is_global_admin) return err(403, "PERMISSION_DENIED", "전역 관리자 권한이 필요합니다", { required: "global_admin" });
      srv.eqRecipes.filter((r) => r.key === key).forEach((r) => (r.deleted = false));
      return ok(recipeOut(srv, latestOf(srv, key)!, true));
    }
    return null;
  }
  if (seg[0] === "studies" && seg[1] && seg[2] === "equiv-checks") {
    const s = srv.studies.find((x) => x.id === seg[1]);
    if (!s) return err(404, "NOT_FOUND", "Study를 찾을 수 없습니다.");
    syncEquiv(srv);
    if (method === "GET") {
      const lim = Math.max(1, Math.min(200, Number(query.get("limit") ?? 50)));
      let list = srv.eqChecks.filter((r) => r.study_id === s.id).sort((a, b) => b.eq_no - a.eq_no);
      const v = query.get("verdict");
      if (v) list = list.filter((r) => r.verdict === v);
      const rk = query.get("recipe_key");
      if (rk) list = list.filter((r) => r.recipe.key === rk);
      const cursor = query.get("cursor");
      if (cursor) list = list.filter((r) => r.eq_no < Number(cursor));
      const page = list.slice(0, lim);
      return { status: 200, body: page.map((r) => itemOf(srv, r)), headers: list.length > lim ? { "X-Next-Cursor": String(page[page.length - 1].eq_no) } : undefined };
    }
    if (method === "POST" && seg[3] === "preview") return previewOf(srv, body ?? {});
    if (method === "POST" && !seg[3]) {
      const d = needPower(srv, s.project_id);
      if (d) return d;
      const pv = previewOf(srv, body ?? {});
      if (pv.status !== 200) return pv;
      const p = pv.body as EqPreview;
      if (!p.can_run) return err(422, "EQ_CHECK_INVALID", "판정을 실행할 수 없습니다", { problems: p.problems });
      if (srv.eqChecks.filter((r) => r.study_id === s.id && r.status === "RUNNING").length >= 2) return err(409, "EQ_CHECK_LIMIT", "이 Study에서 동시에 실행할 수 있는 판정은 2개입니다");
      const rr = resolveRecipe(srv, body ?? {});
      if ("status" in rr) return rr;
      const no = Math.max(0, ...srv.eqChecks.filter((r) => r.study_id === s.id).map((r) => r.eq_no)) + 1;
      const j: Job = baseJob({ id: srv.nid("j"), study_id: s.id, project_id: s.project_id, study_title: s.title, job_type: "EQ_CHECK", state: "QUEUED", created_by: me.user_id, created_by_name: me.display_name, created_at: new Date().toISOString(), params: { eq_id: `eq-${no}`, eq_no: no }, steps: makeSteps("EQ_CHECK", 0, null) });
      srv.jobs.push(j);
      srv.queueOrder.set(j.id, ++srv.queueSeq);
      const rec: EqRec = {
        id: `eq-${srv.nid("x")}`, study_id: s.id, eq_no: no, job_id: j.id, status: "RUNNING", verdict: null, recipe: rr.ref, snapshot: bind(rr.def, (body ?? {}).bindings as Record<string, EqSource | null> | null),
        side_a: { kind: p.side_a.kind, ref: p.side_a.ref, label: p.side_a.label }, side_b: { kind: p.side_b.kind, ref: p.side_b.ref, label: p.side_b.label }, pairs: p.pairs, mode: p.pairing.mode,
        note: ((body ?? {}).note as string | null) ?? null, created_by: me.user_id, created_by_name: me.display_name, created_at: new Date().toISOString(), finished_at: null, rows: [], warnings: [],
      };
      j.params = { eq_id: rec.id, eq_no: no };
      srv.eqChecks.push(rec);
      return ok({ eq_id: rec.id, eq_no: no, label: label(no), job_id: j.id }, 202);
    }
    return null;
  }
  if (seg[0] === "equiv-checks" && seg[1]) {
    syncEquiv(srv);
    const rec = srv.eqChecks.find((r) => r.id === seg[1]);
    if (!rec) return err(404, "EQ_CHECK_NOT_FOUND", "판정 이력을 찾을 수 없습니다.");
    if (method === "GET" && !seg[2]) return ok(detailOf(srv, rec));
    if (method === "GET" && seg[2] === "curves") return curvesOf(rec, Number(query.get("pair")), String(query.get("metric")));
    if (method === "GET" && seg[2] === "table.csv") {
      const text = ["pair_no,a_run,b_run,metric_id,a,b,diff,rel_pct,corr,status,reason", ...rec.rows.map((r) => [r.pair_no, r.a_run, r.b_run, r.metric_id, r.a ?? "", r.b ?? "", r.diff ?? "", r.rel_pct ?? "", r.corr ?? "", r.status, r.reason ?? ""].join(","))].join("\n") + "\n";
      return { status: 200, text, contentType: "text/csv; charset=utf-8" };
    }
    if (method === "PATCH" && !seg[2]) {
      if (!(me.is_global_admin || rec.created_by === me.user_id)) return err(403, "PERMISSION_DENIED", "작성자 또는 관리자만 메모를 고칠 수 있습니다", { required: "owner" });
      const keys = Object.keys(body ?? {});
      if (keys.some((k) => k !== "note")) return err(422, "INVALID_PARAMS", "note만 고칠 수 있습니다.");
      rec.note = ((body ?? {}).note as string | null) || null;
      return ok(itemOf(srv, rec));
    }
    return null;
  }
  return null;
};

/** MockOptions.equiv = "demo": 사용자 레시피 1개(복제본 v2) + 완료 이력 EQ-001(통과)·EQ-002(미달) */
export function seedEquiv(srv: MockServer) {
  const s = srv.studies.find((x) => x.id === "s-cushion")!;
  const def = systemDefinition();
  def.metrics = def.metrics.map((m) => (m.kind === "scalar" ? { ...m, source: { type: "perf", perf: m.id === "cushion_deform" ? "MinDisp" : "MaxStress" } } : m));
  const r1: RecipeRec = { key: "rcp-1", version: 1, scope: "study", study_id: s.id, name: "쿠션 기본 레시피", description: "", definition: def, parent: { key: SYS_KEY, version: 1 }, created_by: "u-power", created_by_name: "김연구", created_at: new Date(Date.now() - 86400000).toISOString(), deleted: false };
  const r2: RecipeRec = { ...r1, version: 2, definition: { ...def, metrics: def.metrics.map((m) => (m.id === "stress_peak" ? { ...m, required: true } : m)) }, created_at: new Date(Date.now() - 3600000).toISOString() };
  srv.eqRecipes.push(r1, r2);
  const doe = srv.p2.does[0];
  const b = srv.batches.find((x) => x.id === "pb-2");
  const pairs = (srv.p2.doeSamples[doe.id] ?? []).slice(0, 5).map((r, i) => ({ no: i + 1, a: r.run_key, b: r.run_key }));
  const mk = (no: number, recipe: EqCheck["recipe"], snap: EqDefinition, sideB: EqRec["side_b"], note: string | null): EqRec => ({
    id: `eq-seed-${no}`, study_id: s.id, eq_no: no, job_id: null, status: "DONE", verdict: null, recipe, snapshot: snap, side_a: { kind: "train_doe", ref: doe.id, label: `① ${doe.doe_label}` }, side_b: sideB, pairs, mode: "by_name",
    note, created_by: "u-power", created_by_name: "김연구", created_at: new Date(Date.now() - 7200000 + no * 60000).toISOString(), finished_at: new Date(Date.now() - 7000000 + no * 60000).toISOString(), rows: [], warnings: [],
  });
  const e1 = mk(1, { source: "user", key: "rcp-1", version: 1, modified: false, name: r1.name, deleted: false, current_version: 2 }, r1.definition, { kind: "train_doe", ref: doe.id, label: `① ${doe.doe_label}` }, "같은 해석을 A·B에 — 기준 확인");
  const e2 = mk(2, { source: "user", key: "rcp-1", version: 2, modified: true, name: r1.name, deleted: false, current_version: 2 }, r2.definition, { kind: "predict_batch", ref: b?.id ?? "pb-2", label: "④ B-002" }, null);
  for (const e of [e1, e2]) {
    e.rows = computeRows(e);
    e.verdict = verdictOf(e).verdict;
  }
  srv.eqChecks.push(e1, e2);
}
