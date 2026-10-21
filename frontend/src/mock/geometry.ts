// native 형상 엔진 목(geometry-engine.md §7.3.4·§7.4·§7.6·§11.1·§11.4).
// openapi 모양: native discover·등록 202·native-prepare·features·PATCH geom_options·/status.geometry,
// 3S(POST props/scan 202·GET props·PUT props → ParamSet), 4B(baselines 추가 202·삭제·disable, remap 202, param-map GET·PUT·confirm),
// ① GET /studies/{id}/train/features. 응답 모양은 backend physicsai_api(services/param_set_props_api·param_set_baselines_api)를 따른다.
import type {
  ExtractFilter, GeomOptions, Job, MapDecision, MapRow, NativeFeature, NativeFeatures, ParamMap, ParamSet, ParamSetDiscover, ParamSetParameter, ShellProp, ShellProps, StatusGeometry, Study, TrainParam,
} from "../api/types";
import { getOpt } from "../lib/geometry";
import { encodePng } from "./png";
import { inspectPath } from "./studies";
import { err, needPower, ok, type MockResp, type Route } from "./route";
import type { MockServer } from "./server";
import { createJobFor } from "./jobs";
import { iso } from "./base";
import { checkFilter, normalizeFilter, typeSelected } from "./extractFilter";

/** 설정 geometry.defaults(§4.9) */
export const GEOM_DEFAULTS: GeomOptions = {
  schema_version: 1,
  quality: { min_stretch: 0.1, max_aspect: 10.0, min_edge_ratio: 0.8, dt_ratio_min: 0.8, min_edge_mm: null, relative_to_baseline: true },
  deviation: { boundary_max_mm: 0.05, param_abs_mm: 0.05, param_rel: 0.01 },
  interference: { body_mm: 0.01, product_mm: 0.05 },
  tie: { default_dsearch_mm: null, required: true },
  extract: { position_range_mm: 5.0, draft_max_deg: 3.0, overlap_min: 0.5, range_ratio: 0.05, sample_grid: 12 },
  thickness_ref: "contact_fixed",
  position_ref: "nearest_fixed",
  thickness_ref_overrides: {},
  symmetry_split: [],
};

function merge(a: unknown, b: unknown): unknown {
  if (b === undefined) return a;
  if (a && b && typeof a === "object" && typeof b === "object" && !Array.isArray(a) && !Array.isArray(b)) {
    const out: Record<string, unknown> = { ...(a as Record<string, unknown>) };
    for (const [k, v] of Object.entries(b as Record<string, unknown>)) out[k] = merge(out[k], v);
    return out;
  }
  return b;
}
export const effectiveOptions = (o: GeomOptions | null | undefined) => merge(GEOM_DEFAULTS, o ?? {}) as GeomOptions;

/** §4.9 범위 검사(API 422 GEOM_OPTIONS_INVALID problems) */
export function validateGeomOptions(o: GeomOptions, groups: string[]): { path: string; message: string }[] {
  const p: { path: string; message: string }[] = [];
  const allowedTop = new Set(Object.keys(GEOM_DEFAULTS).concat(["morph", "tag", "map"]));
  for (const k of Object.keys(o)) if (!allowedTop.has(k) || k === "engine" || k === "engine_version") p.push({ path: k, message: `알 수 없는 키: ${k}` });
  const num = (path: string[], ok: (v: number) => boolean, msg: string, nullable = false) => {
    const v = getOpt(o, path);
    if (v === undefined || (nullable && v === null)) return;
    if (typeof v !== "number" || !Number.isFinite(v) || !ok(v)) p.push({ path: path.join("."), message: msg });
  };
  num(["quality", "min_stretch"], (v) => v > 0 && v <= 1, "0 < min_stretch ≤ 1");
  num(["quality", "max_aspect"], (v) => v >= 1, "max_aspect ≥ 1");
  num(["quality", "min_edge_ratio"], (v) => v > 0 && v <= 1, "0 < min_edge_ratio ≤ 1");
  num(["quality", "dt_ratio_min"], (v) => v > 0 && v <= 1, "0 < dt_ratio_min ≤ 1");
  num(["quality", "min_edge_mm"], (v) => v > 0, "min_edge_mm은 비우거나 0보다 커야 합니다", true);
  num(["extract", "position_range_mm"], (v) => v > 0, "position_range_mm > 0");
  for (const k of ["body_mm", "product_mm"]) num(["interference", k], (v) => v > 0, `${k} > 0`);
  for (const k of ["boundary_max_mm", "param_abs_mm", "param_rel"]) num(["deviation", k], (v) => v > 0, `${k} > 0`);
  const pr = getOpt(o, ["position_ref"]);
  if (pr !== undefined && pr !== "nearest_fixed" && pr !== "proportional") p.push({ path: "position_ref", message: "position_ref ∈ {nearest_fixed, proportional}" });
  const ss = getOpt(o, ["symmetry_split"]);
  if (ss !== undefined && (!Array.isArray(ss) || ss.some((g) => !groups.includes(String(g))))) p.push({ path: "symmetry_split", message: "없는 대칭 그룹입니다" });
  return p;
}

// ---------------------------------------------------------------- 시드 데이터

const F = (name: string, type: string, nominal: number, min: number, max: number, feasible: [number, number] | null, extra: Partial<NativeFeature> = {}): NativeFeature => ({
  name, type, body: name.startsWith("CUSH_R") ? "CUSH_R" : "CUSH_L", nominal, min, max, unit: "mm",
  feasible: feasible ? { min: feasible[0], max: feasible[1], source: "estimate" } : null, group: null, ref_provisional: true, ref_locked: false, png_artifact_id: null, ...extra,
});

export function seedFeatures(): NativeFeature[] {
  return [
    F("CUSH_L_THK_1", "THICKNESS", 12.5, 11.875, 13.125, [6.2, 18], { group: "G1" }),
    F("CUSH_L_POCKET_D_1", "POCKET_DEPTH", 8, 7.6, 8.4, [4, 11]),
    F("CUSH_L_RIB_T_2", "RIB_THICKNESS", 3, 2.85, 3.15, [2.9, 4], { ref_locked: true }),
    F("CUSH_L_HOLE_U_1", "HOLE_POS_U", 30, 25, 35, [27, 40]),
    F("CUSH_L_RIB_U_1", "RIB_POS_U", 51.5, 46.5, 56.5, [47, 60], { ref_provisional: false }),
    F("CUSH_L_FILLET_R_1", "FILLET_RADIUS", 2, 1.9, 2.1, null),
  ];
}

export function nativeTrainParams(): TrainParam[] {
  const p = (name: string, nominal: number, min: number, max: number, use = true): TrainParam => ({
    name, raw_nominal: `${nominal} mm`, nominal, min, max, use, format: "%.4f", unit: "mm", valid: true, problems: [],
  });
  return [
    p("CUSH_L_THK_1", 12.5, 11.875, 13.125),
    p("CUSH_L_POCKET_D_1", 8, 7.6, 8.4),
    p("CUSH_L_RIB_T_2", 3, 2.85, 3.15, false),
    p("CUSH_L_HOLE_U_1", 30, 25, 35),
    p("CUSH_L_RIB_U_1", 51.5, 46.5, 56.5, false),
    p("BOX_SHELL_T", 1.2, 1.14, 1.26, false),
  ];
}

/** props.json(paicad props scan) 행 — 플랫폼은 읽기만, 선택은 파라미터 표의 source:"prop" 행 */
type RawProp = Omit<ShellProp, "selected" | "min" | "max" | "reason_code">;
function seedProps(): { props: RawProp[]; warnings: ShellProps["warnings"] } {
  const P = (id: number, title: string, keyword: string, supported: boolean, parameter: string | null, thickness: number | null, parts: [number, string][], file: string, extra: Partial<RawProp> = {}): RawProp => ({
    id, title, type: supported ? "SHELL" : "COMPOSITE", keyword, supported, parameter, thickness,
    range: thickness ? { min: Number((thickness * 0.95).toFixed(4)), max: Number((thickness * 1.05).toFixed(4)), ratio: 0.05 } : null,
    parts: parts.map(([pid, t]) => ({ id: pid, title: t, thickness: null })), part_overrides: [], element_overrides: 0, file, selectable: supported && !!thickness, ...extra,
  });
  return {
    props: [
      P(101, "BOX_SHELL", "/PROP/TYPE1", true, "BOX_SHELL_SHELL_T", 1.2, [[1, "BOX_TOP"], [2, "BOX_SIDE"]], "cushion_0000.rad"),
      P(102, "TRAY", "/PROP/TYPE1", true, "TRAY_SHELL_T", 0.8, [[3, "TRAY"]], "cushion_0000.rad"),
      P(103, "LABEL", "/PROP/TYPE1", true, "LABEL_SHELL_T", 0.3, [[4, "LABEL"]], "label.inc", { element_overrides: 12, selectable: false }),
      P(201, "FILM_COMP", "/PROP/TYPE10", false, null, null, [[5, "FILM"]], "cushion_0000.rad"),
    ],
    warnings: [
      { code: "PROP_SHARED_BY_PARTS", prop: 101, parts: [1, 2], message: "PROP 101 is shared by 2 parts: 1, 2" },
      { code: "PROP_OVERRIDDEN_BY_ELEMENT", prop: 103, parts: [], message: "PROP 103: 12 shell elements carry their own thickness" },
      { code: "PROP_UNSUPPORTED_TYPE", prop: 201, parts: [], message: "PROP 201 (/PROP/TYPE10, COMPOSITE) is not supported: listed only" },
    ],
  };
}

function reasonCode(r: RawProp): string | null {
  if (r.selectable) return null;
  if (!r.supported) return "PROP_UNSUPPORTED_TYPE";
  if (r.element_overrides) return "PROP_OVERRIDDEN_BY_ELEMENT";
  if (r.part_overrides.length) return "PROP_OVERRIDDEN_BY_PART";
  return "PROP_THICKNESS_INVALID";
}

/** GET /param-sets/{id}/props 응답(shell.summary) */
function propsOut(ps: ParamSet, rec: GeomRec): ShellProps {
  const chosen = new Map(ps.parameters.filter((p) => p.source === "prop").map((p) => [p.name, p]));
  const base = { scanned: rec.propsScanned, shell_only: !!ps.native?.shell_only, include_geometry: ps.parameters.some((p) => p.source !== "prop") };
  if (!rec.propsScanned) return { ...base, engine_version: null, props: [], warnings: [] };
  return {
    ...base, engine_version: ps.engine_version ?? null, warnings: rec.props.warnings,
    props: rec.props.props.map((r) => {
      const c = r.parameter ? chosen.get(r.parameter) : undefined;
      return { ...r, reason_code: reasonCode(r), selected: !!c, min: c?.min ?? null, max: c?.max ?? null };
    }),
  };
}

export interface GeomRec {
  features: NativeFeature[];
  groups: NativeFeatures["groups"];
  warnings: NativeFeatures["warnings"];
  props: { props: RawProp[]; warnings: ShellProps["warnings"] };
  propsScanned: boolean;
  /** param_map.json(서버 저장 모양 — 응답은 mapOut이 requires_decision·unresolved_rows 등을 붙인다) */
  map: StoredMap | null;
}

type StoredMap = Omit<ParamMap, "unresolved_rows" | "undecided_count" | "variables" | "common"> & { common: Omit<MapRow, "requires_decision">[] };

function featurePng(name: string): () => Uint8Array {
  const hue = [...name].reduce((a, c) => a + c.charCodeAt(0), 0) % 3;
  return () => encodePng(80, 60, (x, y) => {
    const inBody = x > 10 && x < 70 && y > 10 && y < 50;
    const moving = inBody && y < 18;
    const fixed = inBody && y > 42;
    if (moving) return [240, 140, 40];
    if (fixed) return [60, 110, 220];
    if (inBody) return [170 + hue * 10, 170, 170];
    return [245, 245, 245];
  });
}

function newRec(srv: MockServer, studyId: string, jobId: string, filter: ExtractFilter | null = null): GeomRec {
  const features = seedFeatures().filter((f) => typeSelected(f.type, filter)).map((f) => ({
    ...f,
    png_artifact_id: f.name === "CUSH_L_FILLET_R_1" ? null : srv.addPngArtifact(jobId, studyId, "FEATURE_PNG", `04_params/features/${f.name}.png`, featurePng(f.name)),
  }));
  return {
    features,
    groups: [{ id: "G1", kind: "MIRROR", parameter: "CUSH_L_THK_1", members: ["CUSH_L_THK_1", "CUSH_R_THK_1"] }],
    warnings: [
      { code: "REF_BOTH_CONTACT", feature: "CUSH_L_RIB_T_2", message: "both faces are in contact; thickness cannot change (excluded from candidates by default)" },
      { code: "PNG_RENDER_FAILED", feature: "CUSH_L_FILLET_R_1", message: "offscreen render failed" },
    ],
    props: seedProps(),
    propsScanned: false,
    map: null,
  };
}

function nativeParamSet(srv: MockServer, s: Study, id: string, path: string, label: string | null, geom: GeomOptions | null, filter: ExtractFilter | null = null): ParamSet {
  const feats = seedFeatures().filter((f) => typeSelected(f.type, filter));
  return {
    id, study_id: s.id, source_path: path, engine: "native", engine_version: "0.6.0", unit_system: "mm-ton-s",
    parameters: feats.map((f) => ({ name: f.name, nominal: f.nominal!, min: f.min!, max: f.max!, unit: "mm" })),
    responses: [], sample_count: 0, sample_has_measured: false, cad_file_name: "cushion_base.step", starter_name: "cushion_0000.rad",
    input_kind: "assembly", assem_rel: "radioss_assem", tpl_params: [], origin: "FOLDER", label, is_current: true, train_doe_id: null,
    registered_by_name: srv.me?.display_name ?? "김연구", registered_at: new Date().toISOString(), display: null, warnings: [],
    geom_options: geom, geom_options_effective: effectiveOptions(geom), native: { prep_status: "READY", prep_reason: null, feature_count: feats.length, props_scanned: false, shell_only: false, kind: "solid", view_status: "MISSING", extract_filter: filter, vars_revision: 0, vars_count: feats.length },
    param_map_status: null,
  } as ParamSet;
}

/** MockOptions.geometry="native": ps-n1(native 세트, 현재 아님) 시드 */
export function seedNative(srv: MockServer, multi = false) {
  const s = srv.studies.find((x) => x.id === "s-cushion")!;
  const ps = nativeParamSet(srv, s, "ps-n1", "E:/shared/AI_WORK/cushion_v1/00_inbox/native_project", "쿠션 native v1", null);
  ps.is_current = false;
  ps.registered_at = iso(60 * 2);
  srv.paramSets.push(ps);
  srv.geom.set(ps.id, newRec(srv, s.id, "j-seed-native"));
  if (multi) addBaselineDone(srv, ps, { id: "B2", label: "리브 5개" }, "topology");
}

// ---------------------------------------------------------------- 4B 매칭표(param_set_baselines_api 모양)

const BASE_ID = "B1";
const RESERVED = new Set(["baseline"]);
const NAME_RE = /^[A-Za-z_][A-Za-z0-9_]{0,63}$/;

function draftMap(ps: ParamSet, bids: string[], prev: StoredMap | null, usage: "topology" | "range"): StoredMap {
  const row = (row_id: string, type: string, name: string, score: number, grade: MapRow["proposed"]["grade"], map: Record<string, string | null>, nominal: number) => {
    const old = prev?.common.find((r) => r.row_id === row_id);
    return {
      row_id, type, feature_type: null, unit: "mm", signature: `sha256:${row_id}`, needs_review: !!prev && !old,
      proposed: { name, score, grade, map, nominal: Object.fromEntries(bids.map((b, i) => [b, map[b] ? nominal + i * 2 : null])), candidates: [], group_size: null },
      decision: old?.decision ?? null,
    };
  };
  const two = (a: string, b: string | null) => Object.fromEntries(bids.map((id, i) => [id, i === 0 ? a : b]));
  return {
    status: "draft", confirmed_by: null, confirmed_at: null, usage, engine_version: ps.engine_version ?? null, discrete: null, map_options: null,
    baselines: bids.map((id) => ({ id, rel: id === BASE_ID ? "." : `baselines/${id}` })),
    range_split: usage === "range" ? { param: "CUSH_THK", intervals: bids.map((b, i) => ({ baseline: b, nominal: 12.5 + i * 2.5 })) } : null,
    common: [
      row("r1", "thickness", "CUSH_THK", 0.93, "recommend", two("CUSH_L_THK_1", "CUSH_L_THK_1"), 12.5),
      row("r2", "height", "CUSH_POCKET_D", 0.58, "check", two("CUSH_L_POCKET_D_1", "CUSH_L_POCKET_D_2"), 8),
      row("r3", "thickness", "CUSH_RIB_T", 0.41, "unmatched", two("CUSH_L_RIB_T_2", null), 3),
      row("r4", "position", "CUSH_HOLE_U", 0.88, "recommend", two("CUSH_L_HOLE_U_1", "CUSH_L_HOLE_U_1"), 30),
    ],
    warnings: [{ code: "MAP_LOW_SCORE", row_id: "r2", message: "r2: score 0.58 below 0.7" }],
  };
}

const unresolved = (m: StoredMap) => m.common.filter((r) => !r.decision && (r.needs_review || r.proposed.grade === "check")).map((r) => r.row_id);

function decisionNames(r: StoredMap["common"][number]): string[] {
  const d = r.decision;
  if (!d) return [];
  return d.action === "split" ? (d.parts ?? []).map((p) => p.name) : [d.name ?? r.proposed.name];
}

/** GET·PUT·confirm 응답(map_out) */
export function mapOut(m: StoredMap): ParamMap {
  const left = new Set(unresolved(m));
  return {
    ...m,
    common: m.common.map((r) => ({ ...r, requires_decision: left.has(r.row_id) })),
    unresolved_rows: [...left],
    undecided_count: m.common.filter((r) => !r.decision).length,
    variables: m.common.flatMap((r) => (r.decision ? decisionNames(r) : [r.proposed.name])),
  };
}

function addBaselineDone(srv: MockServer, ps: ParamSet, b: { id: string; label?: string | null }, usage: "topology" | "range") {
  const base = { id: BASE_ID, rel: ".", label: ps.label ?? null, prep_status: "READY" as const, prep_reason: null, feature_count: ps.native?.feature_count ?? 0 };
  const list = ps.baselines?.length ? ps.baselines : [base];
  ps.baselines = [...list.filter((x) => x.id !== b.id), { id: b.id, rel: `baselines/${b.id}`, label: b.label ?? null, prep_status: "READY", prep_reason: null, feature_count: 5 }];
  const rec = srv.geom.get(ps.id)!;
  rec.map = draftMap(ps, ps.baselines.map((x) => x.id), rec.map, usage);
  ps.param_map_status = "draft";
}

/** normalize_decision: accept = 제안 채움, map 키 = 모든 baseline, split = parts */
function normalize(r: StoredMap["common"][number], d: MapDecision | null, bids: string[]): MapDecision | null {
  if (!d) return null;
  if (d.action === "accept") return { action: "accept", name: r.proposed.name, map: { ...r.proposed.map } };
  if (d.action === "split") {
    const parts = (d.parts ?? []).map((p) => ({ name: p.name, map: Object.fromEntries(bids.map((b) => [b, p.map?.[b] ?? null])) }));
    return { action: "split", name: parts[0]?.name ?? null, map: Object.fromEntries(bids.map((b) => [b, null])), parts };
  }
  return { action: d.action, name: d.name ?? null, map: Object.fromEntries(bids.map((b) => [b, d.map?.[b] ?? null])) };
}

/** decision_problems(이름 규칙·예약어·중복, 한 baseline 안 원 파라미터 중복, split parts) */
function decisionProblems(m: StoredMap): { code: string; row_id: string; message: string }[] {
  const bids = m.baselines.map((b) => b.id);
  const out: { code: string; row_id: string; message: string }[] = [];
  const seen = new Map<string, string>();
  const used = new Map<string, string>();
  for (const r of m.common) {
    const d = r.decision;
    if (!d) continue;
    const parts = d.action === "split" ? (d.parts ?? []).map((p) => [p.name, p.map] as const) : [[d.name ?? "", d.map ?? {}] as const];
    if (!parts.length) out.push({ code: "GEOM_INPUT_INVALID", row_id: r.row_id, message: `${r.row_id}: 분리(split)에는 parts가 필요합니다` });
    for (const [name, mp] of parts) {
      if (!NAME_RE.test(name) || RESERVED.has(name)) {
        out.push({ code: "PARAM_NAME_CONFLICT", row_id: r.row_id, message: `${r.row_id}: 공통 이름 '${name}'은 규칙에 맞지 않거나 예약어입니다(baseline·…__na·baseline__…)` });
        continue;
      }
      const prev = seen.get(name);
      if (prev) {
        out.push({ code: "PARAM_NAME_CONFLICT", row_id: r.row_id, message: `${r.row_id}: 공통 이름 '${name}'이 다른 행(${prev})과 겹칩니다` });
        continue;
      }
      seen.set(name, r.row_id);
      if (!bids.some((b) => mp[b])) out.push({ code: "GEOM_INPUT_INVALID", row_id: r.row_id, message: `${r.row_id}: '${name}'이 모든 baseline에서 N/A입니다` });
      for (const b of bids) {
        const o = mp[b];
        if (!o) continue;
        const k = `${b}\u0000${o}`;
        const u = used.get(k);
        if (u && u !== name) out.push({ code: "PARAM_NAME_CONFLICT", row_id: r.row_id, message: `${r.row_id}: baseline ${b}의 ${o}을(를) 서로 다른 공통 이름(${u}, ${name})이 가리킵니다` });
        used.set(k, name);
      }
    }
  }
  return out;
}

// ---------------------------------------------------------------- 상태·discover

export function geometryStatus(srv: MockServer): StatusGeometry {
  const off = srv.p2.disabled.has("geometry_native");
  return { engine_default: srv.geometryDefault, native_available: !off, reason: off ? "paicad 실행 파일이 설정되지 않았습니다(geometry.paicad_exe)" : null };
}

const NATIVE_ASSEM = { rel: "RADIOSS_ASSEM", starter: "cushion_0000.rad", has_eps_mesh: true, has_renum_csv: true, file_count: 7, has_baseline_inc: true };

/** §7.4 native discover: tpl 없음, CAD = STEP(단일) 또는 parts/, 조립 폴더는 기준본 inc 필수 */
export function discoverNative(path: string): MockResp {
  const chk = inspectPath("PARAM_SET", path);
  if (chk.status !== 200) return chk;
  const out: ParamSetDiscover = {
    path, engine: "native", kind: "solid", tpl: [], selected_tpl: null, cad: [], radioss_assem: [], parameters_source: null, parameters_file: null,
    parameters: [], samples: null, responses: null, problems: [], notes: [], truncated: false, scanned: 38,
  };
  if (/noinc/i.test(path)) {
    out.cad = [{ rel: "01_CAD/cushion_base.step", name: "cushion_base.step", kind: "single" }];
    out.problems = [{ code: "BASELINE_INC_MISSING", message: "조립 폴더에 기준 메시 104_replace_node_elem.inc가 없습니다", file: "RADIOSS_ASSEM" }];
    return ok(out);
  }
  out.cad = /multi/i.test(path)
    ? [{ rel: "01_CAD/cushion_base.step", name: "cushion_base.step", kind: "single" }, { rel: "01_CAD/parts", name: "parts", kind: "parts" }]
    : [{ rel: "01_CAD/cushion_base.step", name: "cushion_base.step", kind: "single" }];
  out.radioss_assem = [NATIVE_ASSEM];
  out.notes = [{ code: "FEATURES_FOUND", message: "parameter_features.json 동반 — 피처 추출을 생략합니다" }];
  return ok(out);
}

// ---------------------------------------------------------------- 작업

function nativeJob(srv: MockServer, s: Study, params: Record<string, unknown>): MockResp {
  if (srv.p2.disabled.has("geometry_native")) return err(409, "GEOM_NATIVE_UNAVAILABLE", "Native 형상 엔진을 쓸 수 없습니다(paicad 미설정)");
  const r = createJobFor(srv, s, "PARAM_SET_NATIVE", params);
  if (r.status !== 201) return r;
  return { status: 202, body: { job_id: (r.body as Job).id } };
}

/** PARAM_SET_NATIVE 완료(§7.3.4·§7.3.8) */
export function finishGeometry(srv: MockServer, j: Job) {
  if (j.job_type !== "PARAM_SET_NATIVE") return;
  const p = j.params as Record<string, unknown>;
  const s = srv.studies.find((x) => x.id === j.study_id)!;
  if (p.mode === "new") {
    srv.paramSets.forEach((x) => x.study_id === s.id && (x.is_current = false));
    const id = srv.nid("ps");
    // extract-filter.md §6.7: 조건이 있으면 폴더의 parameters.json 범위를 쓰지 않는다(경고 PARAMS_JSON_IGNORED, 목은 경로에 "params"가 있을 때)
    const filter = p.extract_filter != null ? normalizeFilter(p.extract_filter).norm : null;
    if (filter && /params/i.test(String(p.path ?? ""))) j.warnings.push({ code: "PARAMS_JSON_IGNORED", message: "추출 조건이 지정되어 폴더의 parameters.json 범위를 쓰지 않았습니다" });
    const ps = nativeParamSet(srv, s, id, String(p.path ?? ""), (p.label as string | null) ?? null, (p.geom_options as GeomOptions | null) ?? null, filter);
    srv.paramSets.unshift(ps);
    srv.geom.set(id, newRec(srv, s.id, j.id, filter));
    j.result = { param_set_id: id, feature_count: ps.native!.feature_count };
    j.steps.forEach((st) => st.step_key === "BL_MAP" && (st.state = "SKIPPED"));
  } else {
    const ps = srv.paramSets.find((x) => x.id === p.param_set_id);
    if (!ps) return;
    const rec = srv.geom.get(ps.id);
    if (p.mode === "add_baseline") {
      const b = p.baseline as { id: string; label?: string | null };
      addBaselineDone(srv, ps, b, (p.usage as "topology" | "range" | null) ?? rec?.map?.usage ?? "topology");
    } else if (p.mode === "remap" && rec?.map) {
      rec.map = draftMap(ps, rec.map.baselines.map((b) => b.id), rec.map, (p.usage as "topology" | "range" | null) ?? rec.map.usage);
      ps.param_map_status = "draft";
    } else if (p.mode === "props_scan" && rec) {
      rec.propsScanned = true;
      ps.native = { ...(ps.native ?? { prep_status: "READY", feature_count: 0, shell_only: false, kind: "solid", view_status: "MISSING", vars_revision: 0, vars_count: 0 }), props_scanned: true };
    } else {
      ps.native = { ...(ps.native ?? { feature_count: 0, props_scanned: false, shell_only: false, kind: "solid", view_status: "MISSING", vars_revision: 0, vars_count: 0 }), prep_status: "READY", prep_reason: null };
    }
    j.result = { param_set_id: ps.id };
  }
}

const findPs = (srv: MockServer, id: string) => srv.paramSets.find((p) => p.id === id);
const studyOf = (srv: MockServer, ps: ParamSet) => srv.studies.find((s) => s.id === ps.study_id)!;

/** native 라우트(studyRoutes·paramSetRoutes보다 먼저) */
export const geometryRoutes: Route = (srv, { method, seg, body }) => {
  // POST /studies/{id}/param-sets/discover {engine:"native"}
  if (seg[0] === "studies" && seg[2] === "param-sets" && method === "POST") {
    const s = srv.studies.find((x) => x.id === seg[1]);
    if (s && body?.engine !== "native" && body?.extract_filter != null) return checkFilter(body.extract_filter, { native: false }) as MockResp; // altair 요청의 extract_filter = 422(그 밖 altair 동작 불변)
    if (!s || body?.engine !== "native") return null;
    if (seg[3] === "discover") return discoverNative(String(body?.path ?? ""));
    if (!seg[3]) {
      const deny = needPower(srv, s.project_id);
      if (deny) return deny;
      const d = discoverNative(String(body?.path ?? ""));
      if (d.status !== 200) return d;
      const found = d.body as ParamSetDiscover;
      if (found.problems.length) return err(422, "PARAM_SET_INVALID", found.problems[0].message);
      const choice = (body?.choice ?? {}) as Record<string, string | null>;
      if (found.cad.length > 1 && !choice.cad) return err(422, "PARAM_SET_INVALID", "후보 중 하나를 고르세요");
      if (body?.geom_options) {
        const probs = validateGeomOptions(body.geom_options as GeomOptions, []);
        if (probs.length) return err(422, "GEOM_OPTIONS_INVALID", "검사 기준 값이 허용 범위를 벗어났습니다", { problems: probs });
      }
      const chk = checkFilter(body?.extract_filter, { native: true });
      if ("status" in chk) return chk;
      return nativeJob(srv, s, { mode: "new", path: body?.path, choice, label: body?.label ?? null, geom_options: body?.geom_options ?? null, ...(chk.norm ? { extract_filter: chk.norm } : {}) });
    }
    return null;
  }
  // ① GET /studies/{id}/train/features(§7.3.1): native 추출 피처 + 하이라이트 PNG artifact
  if (seg[0] === "studies" && seg[2] === "train" && seg[3] === "features" && method === "GET") {
    const s = srv.studies.find((x) => x.id === seg[1]);
    if (!s) return null;
    const setup = srv.p2.setups[s.id];
    if (!setup || setup.engine !== "native") return err(409, "NATIVE_PREP_MISSING", "① Native 형상 피처가 없습니다 — 파라미터 추출을 Native로 먼저 하세요");
    const key = `train:${s.id}:${setup.extract_job_id ?? ""}`;
    if (!srv.geom.has(key)) srv.geom.set(key, newRec(srv, s.id, setup.extract_job_id ?? "j-train-native", setup.extract_filter ?? null));
    const r = srv.geom.get(key)!;
    return ok({ engine_version: "0.6.0", features: r.features, groups: r.groups, warnings: r.warnings, filter: setup.extract_filter ?? null });
  }
  if (seg[0] !== "param-sets" || !seg[1]) return null;
  const ps = findPs(srv, seg[1]);
  if (!ps) return null;
  const rec = srv.geom.get(ps.id);
  const sub = seg[2];
  if (method === "PATCH" && !sub && body && "geom_options" in body) {
    if (ps.engine !== "native") return err(422, "GEOM_OPTIONS_INVALID", "SimLab 템플릿에는 형상 검사 기준이 없습니다");
    const g = (body.geom_options ?? null) as GeomOptions | null;
    const probs = g ? validateGeomOptions(g, rec?.groups.map((x) => String(x.id)) ?? []) : [];
    if (probs.length) return err(422, "GEOM_OPTIONS_INVALID", "검사 기준 값이 허용 범위를 벗어났습니다", { problems: probs });
    const tagChanged = JSON.stringify(getOpt(ps.geom_options, ["tag"])) !== JSON.stringify(getOpt(g, ["tag"]));
    ps.geom_options = g && Object.keys(g).length ? g : null;
    ps.geom_options_effective = effectiveOptions(ps.geom_options);
    if ("label" in body) ps.label = String(body.label ?? "").trim() || null;
    if (tagChanged && ps.native) ps.native = { ...ps.native, prep_status: "STALE", prep_reason: "경계 분류 기준이 바뀌어 형상 준비를 다시 해야 합니다" };
    return ok(ps);
  }
  if (ps.engine !== "native") {
    if (sub === "baselines" || sub === "param-map" || sub === "remap") return err(409, "ENGINE_MISMATCH", "다중 baseline은 Native 형상 엔진 세트에서만 씁니다");
    if (sub === "features" || sub === "native-prepare" || sub === "props") return err(409, "ENGINE_NATIVE_UNSUPPORTED", "Native 세트에서만 쓸 수 있습니다");
    return null;
  }
  if (method === "POST" && sub === "native-prepare") {
    // 등록된 세트의 추출 조건은 바꿀 수 없다(§6.7)
    if (body?.extract_filter != null) return err(422, "EXTRACT_FILTER_INVALID", "등록된 세트의 추출 조건은 바꿀 수 없습니다 — 새 세트로 등록하세요", { problems: [{ key: "extract_filter", message: "등록된 세트의 추출 조건은 바꿀 수 없습니다 — 새 세트로 등록하세요" }] });
  }
  if (method === "POST" && sub === "native-prepare") return nativeJob(srv, studyOf(srv, ps), { mode: "reprep", param_set_id: ps.id });
  if (method === "GET" && sub === "features" && rec) return ok({ engine_version: ps.engine_version, features: rec.features, groups: rec.groups, warnings: rec.warnings, filter: ps.native?.extract_filter ?? null });
  // 3S 쉘 두께(§11.1)
  if (sub === "props" && rec) {
    if (method === "POST" && seg[3] === "scan") return nativeJob(srv, studyOf(srv, ps), { mode: "props_scan", param_set_id: ps.id });
    if (seg[3]) return null;
    if (method === "GET") return ok(propsOut(ps, rec));
    if (method === "PUT") {
      const deny = needPower(srv, studyOf(srv, ps).project_id);
      if (deny) return deny;
      if (!rec.propsScanned) return err(409, "PROPS_NOT_SCANNED", "쉘 두께 PROP 스캔을 먼저 하세요");
      const sel = (body?.selected ?? []) as { name: string; min?: number | null; max?: number | null }[];
      let include = body?.include_geometry !== false;
      if (ps.native?.shell_only) include = false;
      else if (!include && rec.map) return err(422, "PROP_SELECTION_INVALID", "다중 baseline 세트는 형상 파라미터를 뺄 수 없습니다", { problems: [{ code: "MULTI_BASELINE", message: "다중 baseline 세트는 형상 파라미터를 뺄 수 없습니다" }] });
      const geo = ps.parameters.filter((p) => p.source !== "prop");
      const problems: { code: string; parameter: string; message: string }[] = [];
      const rows: ParamSetParameter[] = [];
      const seen = new Set<string>();
      for (const it of sel) {
        if (seen.has(it.name)) {
          problems.push({ code: "PROP_SELECTION_DUPLICATE", parameter: it.name, message: `${it.name}: 중복 선택입니다` });
          continue;
        }
        seen.add(it.name);
        const r = rec.props.props.find((x) => x.parameter === it.name);
        if (!r || !r.selectable || r.thickness == null) {
          problems.push({ code: r ? reasonCode(r)! : "PROP_NOT_FOUND", parameter: it.name, message: `${it.name}: ${r ? "선택할 수 없는 PROP입니다" : "PROP 목록에 없습니다(스캔을 다시 하세요)"}` });
          continue;
        }
        const rg = (r.range ?? {}) as { min?: number; max?: number };
        const min = it.min ?? rg.min ?? r.thickness;
        const max = it.max ?? rg.max ?? r.thickness;
        if (!(0 < min && min <= r.thickness && r.thickness <= max)) {
          problems.push({ code: "PROP_THICKNESS_INVALID", parameter: it.name, message: `${it.name}: 0 < min ≤ 공칭(${r.thickness}) ≤ max 이어야 합니다` });
          continue;
        }
        rows.push({ name: it.name, nominal: r.thickness, min, max, unit: "mm", source: "prop", prop_id: r.id ?? null });
      }
      if (problems.length) return err(422, "PROP_SELECTION_INVALID", "쉘 두께 선택이 올바르지 않습니다", { problems });
      const next = [...(include ? geo : []), ...rows];
      if (!next.length) return err(422, "PROP_SELECTION_INVALID", "파라미터가 1개 이상 필요합니다", { problems: [{ code: "PARAMETERS_EMPTY", message: "형상 또는 쉘 두께 파라미터를 하나 이상 고르세요" }] });
      ps.parameters = next;
      return ok(ps);
    }
  }
  // 4B 다중 baseline(§7.3.8)
  if (sub === "baselines") {
    if (method === "POST" && !seg[3]) {
      const b = (body ?? {}) as { id?: string; path?: string; choice?: unknown; label?: string | null; usage?: "topology" | "range" | null; split_param?: string | null };
      if (!b.id || !/^[A-Za-z0-9_-]{1,32}$/.test(b.id) || b.id === BASE_ID || ps.baselines?.some((x) => x.id === b.id))
        return err(422, "GEOM_INPUT_INVALID", "baseline id는 영문·숫자·_-(32자 이내)이고 세트 안에서 유일해야 합니다");
      const d = discoverNative(String(b.path ?? ""));
      if (d.status !== 200) return d;
      if ((d.body as ParamSetDiscover).problems.length) return err(422, "PARAM_SET_INVALID", (d.body as ParamSetDiscover).problems[0].message);
      return nativeJob(srv, studyOf(srv, ps), { mode: "add_baseline", param_set_id: ps.id, baseline: { id: b.id, path: b.path, choice: b.choice ?? {}, label: b.label ?? null }, usage: b.usage ?? null, split_param: b.split_param ?? null });
    }
    if (method === "POST" && seg[3] === "disable") {
      if (!rec?.map) return err(409, "NOT_MULTI_BASELINE", "다중 baseline 세트가 아닙니다 — baseline을 먼저 추가하세요");
      rec.map = null;
      ps.baselines = null;
      ps.param_map_status = null;
      return ok(ps);
    }
    if (method === "DELETE" && seg[3]) {
      if (!rec?.map) return err(409, "NOT_MULTI_BASELINE", "다중 baseline 세트가 아닙니다 — baseline을 먼저 추가하세요");
      const bl = rec.map.baselines;
      const target = bl.find((x) => x.id === seg[3]);
      if (!target) return err(404, "NOT_FOUND", `baseline ${seg[3]}이(가) 없습니다`);
      if (target.rel === ".") return err(409, "BASELINE_BASE", "첫 baseline(세트 자신)은 삭제할 수 없습니다 — 단일로 되돌리려면 disable을 쓰세요");
      if (bl.length <= 2) return err(409, "BASELINE_LAST", "baseline이 2개뿐이라 삭제할 수 없습니다 — 단일로 되돌리려면 disable을 쓰세요");
      const left = bl.filter((x) => x.id !== seg[3]).map((x) => x.id);
      rec.map = { ...draftMap(ps, left, rec.map, rec.map.usage) };
      ps.baselines = (ps.baselines ?? []).filter((x) => x.id !== seg[3]);
      ps.param_map_status = "draft";
      return ok(ps);
    }
  }
  if (sub === "remap" && method === "POST") {
    if (!rec?.map) return err(409, "NOT_MULTI_BASELINE", "다중 baseline 세트가 아닙니다 — baseline을 먼저 추가하세요");
    return nativeJob(srv, studyOf(srv, ps), { mode: "remap", param_set_id: ps.id, usage: body?.usage ?? null, split_param: body?.split_param ?? null });
  }
  if (sub === "param-map" && rec) {
    if (!rec.map) return err(409, "NOT_MULTI_BASELINE", "다중 baseline 세트가 아닙니다 — baseline을 먼저 추가하세요");
    if (method === "GET" && !seg[3]) return ok(mapOut(rec.map));
    if (method === "PUT" && !seg[3]) {
      const next: StoredMap = JSON.parse(JSON.stringify(rec.map));
      const bids = next.baselines.map((b) => b.id);
      for (const d of (body?.decisions ?? []) as { row_id: string; decision: MapDecision | null }[]) {
        const r = next.common.find((x) => x.row_id === d.row_id);
        if (!r) return err(422, "GEOM_INPUT_INVALID", `없는 행입니다: ${d.row_id}`, { problems: [{ code: "GEOM_INPUT_INVALID", row_id: d.row_id, message: `없는 행입니다: ${d.row_id}` }] });
        r.decision = normalize(r, d.decision, bids);
      }
      const probs = decisionProblems(next);
      if (probs.length) return err(422, probs[0].code, probs[0].message, { problems: probs });
      Object.assign(next, { status: "draft", confirmed_by: null, confirmed_at: null });
      rec.map = next;
      ps.param_map_status = "draft";
      return ok(mapOut(next));
    }
    if (method === "POST" && seg[3] === "confirm") {
      const left = unresolved(rec.map);
      if (left.length)
        return err(422, "GEOM_INPUT_INVALID", `결정하지 않은 행이 ${left.length}개 있습니다(재확인·확인 필요)`, { problems: left.map((id) => ({ code: "GEOM_INPUT_INVALID", row_id: id, message: `${id}: 결정이 필요합니다` })) });
      rec.map = {
        ...rec.map, status: "confirmed", confirmed_by: srv.me?.display_name ?? null, confirmed_at: new Date().toISOString(),
        common: rec.map.common.map((r) => (r.decision ? r : { ...r, decision: { action: "accept", name: r.proposed.name, map: { ...r.proposed.map } } })),
      };
      ps.param_map_status = "confirmed";
      return ok(mapOut(rec.map));
    }
  }
  return null;
};

/** ①-3 세트 기준 native DOE 게이트(§7.3.8): 다중 baseline 미확정 → 409 PARAM_MAP_UNCONFIRMED */
export function mapGate(srv: MockServer, psId: string): MockResp | null {
  const rec = srv.geom.get(psId);
  if (rec?.map && rec.map.status !== "confirmed") {
    const n = rec.map.common.filter((r) => !r.decision).length;
    return err(409, "PARAM_MAP_UNCONFIRMED", `다중 baseline 매칭표가 확정되지 않았습니다(미결정 행 ${n}개) — 매칭표를 확인해 확정하세요`, { param_set_id: psId, undecided_rows: n, unresolved_rows: unresolved(rec.map) });
  }
  return null;
}
