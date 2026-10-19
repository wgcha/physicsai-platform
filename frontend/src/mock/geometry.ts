// native 형상 엔진 목(geometry-engine.md §7.3.4·§7.4·§7.6·§11.1·§11.4).
// 단계 4 API(openapi 반영됨): native discover·등록 202·native-prepare·features·PATCH geom_options·/status.geometry.
// 3S(GET·PUT /param-sets/{id}/props)·4B(baselines·param-map)는 백엔드 병합 전 계약 모양 목 라우트.
import type {
  GeomOptions, Job, MapDecision, MapRow, NativeFeature, NativeFeatures, ParamMap, ParamSet, ParamSetDiscover, ShellPropsDoc, StatusGeometry, Study, TrainParam,
} from "../api/types";
import { getOpt } from "../lib/geometry";
import { encodePng } from "./png";
import { inspectPath } from "./studies";
import { err, needPower, ok, type MockResp, type Route } from "./route";
import type { MockServer } from "./server";
import { createJobFor } from "./jobs";
import { iso } from "./base";

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
    p("BOX_SHELL_T", 1.2, 1.14, 1.26, false),
  ];
}

function seedProps(): ShellPropsDoc {
  return {
    props: [
      { id: 101, title: "BOX_SHELL", type: "SHELL", keyword: "/PROP/TYPE1", supported: true, parameter: "BOX_SHELL_SHELL_T", thickness: 1.2, unit: "mm", range: { min: 1.14, max: 1.26, ratio: 0.05 }, parts: [{ id: 1, title: "BOX_TOP" }, { id: 2, title: "BOX_SIDE" }], file: "cushion_0000.rad", element_overrides: 0, selectable: true },
      { id: 102, title: "TRAY", type: "SHELL", keyword: "/PROP/TYPE1", supported: true, parameter: "TRAY_SHELL_T", thickness: 0.8, unit: "mm", range: { min: 0.76, max: 0.84, ratio: 0.05 }, parts: [{ id: 3, title: "TRAY" }], file: "cushion_0000.rad", element_overrides: 0, selectable: true },
      { id: 103, title: "LABEL", type: "SHELL", keyword: "/PROP/TYPE1", supported: true, parameter: "LABEL_SHELL_T", thickness: 0.3, unit: "mm", range: { min: 0.285, max: 0.315, ratio: 0.05 }, parts: [{ id: 4, title: "LABEL" }], file: "label.inc", element_overrides: 12, selectable: false },
      { id: 201, title: "FILM_COMP", type: "COMPOSITE", keyword: "/PROP/TYPE10", supported: false, parameter: null, thickness: null, unit: "mm", range: null, parts: [{ id: 5, title: "FILM" }], file: "cushion_0000.rad", element_overrides: 0, selectable: false },
    ],
    selected: [],
    warnings: [
      { code: "PROP_SHARED_BY_PARTS", prop: 101, parts: [1, 2], message: "PROP 101 is shared by 2 parts: 1, 2" },
      { code: "PROP_OVERRIDDEN_BY_ELEMENT", prop: 103, message: "PROP 103: 12 shell elements carry their own thickness" },
      { code: "PROP_UNSUPPORTED_TYPE", prop: 201, message: "PROP 201 (/PROP/TYPE10, COMPOSITE) is not supported: listed only" },
    ],
  };
}

export interface GeomRec {
  features: NativeFeature[];
  groups: NativeFeatures["groups"];
  warnings: NativeFeatures["warnings"];
  props: ShellPropsDoc;
  map: ParamMap | null;
}

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

function newRec(srv: MockServer, studyId: string, jobId: string): GeomRec {
  const features = seedFeatures().map((f) => ({
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
    map: null,
  };
}

function nativeParamSet(srv: MockServer, s: Study, id: string, path: string, label: string | null, geom: GeomOptions | null): ParamSet {
  const feats = seedFeatures();
  return {
    id, study_id: s.id, source_path: path, engine: "native", engine_version: "0.6.0", unit_system: "mm-ton-s",
    parameters: feats.map((f) => ({ name: f.name, nominal: f.nominal!, min: f.min!, max: f.max!, unit: "mm" })),
    responses: [], sample_count: 0, sample_has_measured: false, cad_file_name: "cushion_base.step", starter_name: "cushion_0000.rad",
    input_kind: "assembly", assem_rel: "radioss_assem", tpl_params: [], origin: "FOLDER", label, is_current: true, train_doe_id: null,
    registered_by_name: srv.me?.display_name ?? "김연구", registered_at: new Date().toISOString(), display: null, warnings: [],
    geom_options: geom, geom_options_effective: effectiveOptions(geom), native: { prep_status: "READY", prep_reason: null, feature_count: feats.length },
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
  if (multi) addBaselineDone(srv, ps, { id: "B2", label: "리브 5개" });
}

// ---------------------------------------------------------------- 4B 매칭표

function draftMap(ps: ParamSet, bids: string[], prev: ParamMap | null): ParamMap {
  const row = (row_id: string, type: string, name: string, score: number, grade: MapRow["proposed"]["grade"], map: Record<string, string | null>): MapRow => {
    const old = prev?.common.find((r) => r.row_id === row_id);
    return {
      row_id, type, unit: "mm", signature: `sha256:${row_id}`, needs_review: !!prev && !old,
      proposed: { name, score, grade, map, candidates: [] }, decision: old?.decision ?? null,
    };
  };
  const two = (a: string, b: string | null) => Object.fromEntries(bids.map((id, i) => [id, i === 0 ? a : b]));
  return {
    schema_version: 1, status: "draft", confirmed_by: null, confirmed_at: null, usage: "topology",
    baselines: bids.map((id) => ({ id, rel: id === "base" ? "." : `baselines/${id}` })),
    range_split: null,
    common: [
      row("r1", "thickness", "CUSH_THK", 0.93, "recommend", two("CUSH_L_THK_1", "CUSH_L_THK_1")),
      row("r2", "height", "CUSH_POCKET_D", 0.58, "check", two("CUSH_L_POCKET_D_1", "CUSH_L_POCKET_D_2")),
      row("r3", "thickness", "CUSH_RIB_T", 0.41, "unmatched", two("CUSH_L_RIB_T_2", null)),
      row("r4", "position", "CUSH_HOLE_U", 0.88, "recommend", two("CUSH_L_HOLE_U_1", "CUSH_L_HOLE_U_1")),
    ],
    warnings: [{ code: "MAP_LOW_SCORE", row_id: "r2" }],
    params: Object.fromEntries(bids.map((id, i) => [id, i === 0 ? ps.parameters.map((p) => p.name) : ["CUSH_L_THK_1", "CUSH_L_POCKET_D_2", "CUSH_L_HOLE_U_1", "CUSH_L_RIB_T_5"]])),
  };
}

function addBaselineDone(srv: MockServer, ps: ParamSet, b: { id: string; label?: string | null; path?: string }) {
  const list = ps.baselines?.length ? ps.baselines : [{ id: "base", label: "기준", source_path: ps.source_path, prep_status: "READY" as const }];
  ps.baselines = [...list.filter((x) => x.id !== b.id), { id: b.id, label: b.label ?? null, source_path: b.path ?? null, prep_status: "READY" }];
  const rec = srv.geom.get(ps.id)!;
  rec.map = draftMap(ps, ps.baselines.map((x) => x.id), rec.map);
}

function applyDecision(m: ParamMap, row_id: string, d: MapDecision | null): MockResp | null {
  const i = m.common.findIndex((r) => r.row_id === row_id);
  if (i < 0) return err(422, "GEOM_INPUT_INVALID", `없는 행입니다: ${row_id}`);
  const r = m.common[i];
  if (d?.action === "split") {
    // 한 행 → baseline별 별도 변수 행(분리된 행마다 decision 1개)
    const rows = m.baselines
      .filter((b) => r.proposed.map[b.id])
      .map((b): MapRow => {
        const map = Object.fromEntries(m.baselines.map((x) => [x.id, x.id === b.id ? r.proposed.map[b.id] : null]));
        const name = `${d.name}_${b.id}`;
        return { ...r, row_id: `${r.row_id}_${b.id}`, needs_review: false, proposed: { ...r.proposed, map }, decision: { action: "split", name, map } };
      });
    m.common.splice(i, 1, ...rows);
  } else {
    m.common[i] = { ...r, decision: d, needs_review: d ? false : r.needs_review };
  }
  return null;
}

function conflict(m: ParamMap): string | null {
  const seen = new Set<string>();
  for (const r of m.common) {
    const n = r.decision?.name ?? r.proposed.name;
    if (n === "baseline" || seen.has(n)) return n;
    seen.add(n);
  }
  return null;
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
    path, engine: "native", tpl: [], selected_tpl: null, cad: [], radioss_assem: [], parameters_source: null, parameters_file: null,
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
  if (srv.p2.disabled.has("geometry_native")) return err(409, "GEOM_NATIVE_UNAVAILABLE", "native 형상 엔진을 쓸 수 없습니다(paicad 미설정)");
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
    const ps = nativeParamSet(srv, s, id, String(p.path ?? ""), (p.label as string | null) ?? null, (p.geom_options as GeomOptions | null) ?? null);
    srv.paramSets.unshift(ps);
    srv.geom.set(id, newRec(srv, s.id, j.id));
    j.result = { param_set_id: id, feature_count: ps.native!.feature_count };
    j.steps.forEach((st) => st.step_key === "BL_MAP" && (st.state = "SKIPPED"));
  } else {
    const ps = srv.paramSets.find((x) => x.id === p.param_set_id);
    if (!ps) return;
    if (p.mode === "add_baseline") {
      const b = p.baseline as { id: string; label?: string | null; path?: string };
      addBaselineDone(srv, ps, b);
    } else {
      ps.native = { ...(ps.native ?? { feature_count: 0 }), prep_status: "READY", prep_reason: null };
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
      return nativeJob(srv, s, { mode: "new", path: body?.path, choice, label: body?.label ?? null, geom_options: body?.geom_options ?? null });
    }
    return null;
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
    if (sub === "features" || sub === "native-prepare" || sub === "props" || sub === "baselines" || sub === "param-map")
      return err(409, "ENGINE_NATIVE_UNSUPPORTED", "native 세트에서만 쓸 수 있습니다");
    return null;
  }
  if (method === "POST" && sub === "native-prepare") return nativeJob(srv, studyOf(srv, ps), { mode: "reprep", param_set_id: ps.id });
  if (method === "GET" && sub === "features" && rec) return ok({ engine_version: ps.engine_version, features: rec.features, groups: rec.groups, warnings: rec.warnings });
  // 3S 쉘 두께
  if (sub === "props" && rec) {
    if (method === "GET") return ok(rec.props);
    if (method === "PUT") {
      const sel = (body?.selected ?? []) as { prop_id: number; name?: string; min: number; max: number }[];
      for (const x of sel) {
        const pr = rec.props.props.find((p) => p.id === x.prop_id);
        if (!pr || !pr.selectable) return err(422, "PROP_UNSUPPORTED_TYPE", `선택할 수 없는 PROP입니다: ${x.prop_id}`);
        if (!(x.min > 0) || !(x.min < x.max)) return err(422, "PROP_THICKNESS_INVALID", `PROP ${x.prop_id}: 두께 범위는 0 < 하한 < 상한`);
      }
      rec.props = { ...rec.props, selected: sel.map((x) => ({ prop_id: x.prop_id, name: rec.props.props.find((p) => p.id === x.prop_id)!.parameter!, min: x.min, max: x.max })) };
      const shell = new Set(rec.props.props.map((p) => p.parameter));
      ps.parameters = [
        ...ps.parameters.filter((p) => !shell.has(p.name)),
        ...rec.props.selected.map((x) => ({ name: x.name, nominal: rec.props.props.find((p) => p.id === x.prop_id)!.thickness!, min: x.min, max: x.max, unit: "mm" })),
      ];
      return ok(rec.props);
    }
  }
  // 4B 다중 baseline
  if (sub === "baselines") {
    if (method === "POST" && !seg[3]) {
      const b = (body?.baseline ?? {}) as { id?: string; path?: string; choice?: unknown; label?: string | null };
      if (!b.id || !/^[A-Za-z0-9_-]{1,32}$/.test(b.id) || b.id === "base" || ps.baselines?.some((x) => x.id === b.id))
        return err(422, "GEOM_INPUT_INVALID", "baseline id는 영문·숫자·_-(32자 이내)이고 세트 안에서 유일해야 합니다");
      const d = discoverNative(String(b.path ?? ""));
      if (d.status !== 200) return d;
      if ((d.body as ParamSetDiscover).problems.length) return err(422, "PARAM_SET_INVALID", (d.body as ParamSetDiscover).problems[0].message);
      return nativeJob(srv, studyOf(srv, ps), { mode: "add_baseline", param_set_id: ps.id, baseline: b });
    }
    if (method === "DELETE" && seg[3]) {
      if (!ps.baselines?.some((x) => x.id === seg[3]) || seg[3] === "base") return err(422, "GEOM_INPUT_INVALID", "삭제할 수 없는 baseline입니다");
      const left = ps.baselines.filter((x) => x.id !== seg[3]);
      if (left.length <= 1) {
        delete ps.baselines;
        if (rec) rec.map = null;
      } else {
        ps.baselines = left;
        if (rec) rec.map = draftMap(ps, left.map((x) => x.id), rec.map);
      }
      return ok(ps);
    }
  }
  if (sub === "param-map" && rec) {
    if (!rec.map) return err(404, "NOT_FOUND", "다중 baseline 매칭표가 없습니다");
    if (method === "GET" && !seg[3]) return ok(rec.map);
    if (method === "PUT" && !seg[3]) {
      const next: ParamMap = JSON.parse(JSON.stringify(rec.map));
      for (const d of (body?.decisions ?? []) as { row_id: string; decision: MapDecision | null }[]) {
        const e = applyDecision(next, d.row_id, d.decision);
        if (e) return e;
      }
      const c = conflict(next);
      if (c) return err(422, "PARAM_NAME_CONFLICT", `공통 변수 이름이 겹칩니다: ${c}`);
      next.status = "draft";
      next.confirmed_by = null;
      next.confirmed_at = null;
      rec.map = next;
      return ok(next);
    }
    if (method === "POST" && seg[3] === "confirm") {
      const pend = rec.map.common.filter((r) => !r.decision && (r.needs_review || r.proposed.grade === "check"));
      if (pend.length) return err(422, "GEOM_INPUT_INVALID", `결정하지 않은 행이 ${pend.length}개 있습니다(재확인·확인 필요)`);
      rec.map = {
        ...rec.map, status: "confirmed", confirmed_by: srv.me?.display_name ?? null, confirmed_at: new Date().toISOString(),
        common: rec.map.common.map((r) => (r.decision ? r : { ...r, decision: { action: "accept", name: r.proposed.name, map: r.proposed.map } })),
      };
      return ok(rec.map);
    }
  }
  return null;
};

