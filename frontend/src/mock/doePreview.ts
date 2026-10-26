// DOE 표본 형상 그리드 미리보기 목(doe-preview.md §6.6, openapi 반영 전 로컬 모양):
// POST /studies/{id}/doe-previews(200 전부 캐시 | 202) · GET /doe-previews/{id}(조회마다 셀이 채워진다) · POST /doe-previews/{id}/cancel.
// 셀 PNG(320×240)·GLB·manifest는 요청 때 만든다(GEOM_THUMB_PNG는 geomView 미디어 라우트가 그대로 서빙).
// 시나리오(setDpMode): 기본 = 한 페이지 24셀 중 실패 셀 2·잘림 1·색 범위 초과(구멍 위치 변화) 포함, 조회 2번에 완료.
//   hold = 12/24에서 진행 중으로 멈춤(진행률 시연), error = 셀 1개 ERROR, perPoll = 한 번 조회에 채우는 셀 수, fail = 실패 셀 순번(페이지 안), none = 실패 없음.
import type { Artifact, DoePreview, DoePreviewCell, DoePreviewReq, ParamSet } from "../api/types";
import { TURBO16 } from "../stages/stage1/doepreview/gridModel";
import { NOMINAL, PARAM_KEY, cushionGlb, previewManifest, type CushionParams } from "./geomViewData";
import { encodePng } from "./png";
import { err, needPower, ok, type Route } from "./route";
import type { MockServer } from "./server";

export interface DpMode {
  hold?: boolean;
  error?: boolean;
  perPoll?: number;
  fail?: number[];
  /** 실패·오류 없음 */
  clean?: boolean;
}

interface Var {
  name: string;
  nominal: number;
  min: number;
  max: number;
}
interface Rec {
  pv: DoePreview;
  key: string;
  full: DoePreviewCell[];
  done: number;
  perPoll: number;
  hold: boolean;
  cancelled: boolean;
}
interface DpState {
  mode: DpMode;
  recs: Rec[];
  nominal: Map<string, { png: string; glb: string; manifest: string }>;
}

const STATE = new WeakMap<MockServer, DpState>();
const st = (srv: MockServer): DpState => {
  let s = STATE.get(srv);
  if (!s) {
    s = { mode: {}, recs: [], nominal: new Map() };
    STATE.set(srv, s);
  }
  return s;
};
export const setDpMode = (srv: MockServer, mode: DpMode) => {
  st(srv).mode = { ...st(srv).mode, ...mode };
};
/** 시험용: 목 미리보기 기록 */
export const dpRecords = (srv: MockServer) => st(srv).recs.map(view);

const RANGE: [number, number] = [0, 1.5];

function lcg(seed: number) {
  let s = (seed * 2654435761 + 12345) >>> 0;
  return () => ((s = (Math.imul(s, 1664525) + 1013904223) >>> 0) / 4294967296);
}

/** 표본 행렬(실제 DOE와 달리 목은 라틴 방격 흉내) */
function matrix(vars: Var[], n: number, seed: number): Record<string, number>[] {
  const r = lcg(seed);
  const perms = vars.map(() => {
    const p = Array.from({ length: n }, (_, i) => i);
    for (let i = n - 1; i > 0; i--) {
      const j = Math.floor(r() * (i + 1));
      [p[i], p[j]] = [p[j], p[i]];
    }
    return p;
  });
  return Array.from({ length: n }, (_, i) => Object.fromEntries(vars.map((v, j) => [v.name, Number((v.min + ((perms[j][i] + r()) / n) * (v.max - v.min)).toPrecision(5))])));
}

const rel = (v: Var, x: number) => (v.max > v.min ? (x - v.nominal) / (v.max - v.min) : 0);

function varsOf(srv: MockServer, studyId: string, ps: ParamSet | null): Var[] {
  const rows = ps ? ps.parameters : (srv.p2.setups[studyId]?.parameters ?? []).filter((p) => p.use);
  return rows.map((p) => ({ name: p.name, nominal: p.nominal ?? 0, min: p.min ?? 0, max: p.max ?? 0 }));
}

function params(values: Record<string, number>): CushionParams {
  const p = { ...NOMINAL };
  for (const [k, v] of Object.entries(values)) if (PARAM_KEY[k]) p[PARAM_KEY[k]] = v;
  return p;
}
const maxDispOf = (values: Record<string, number>): number => {
  const p = params(values);
  return Number(Math.max(Math.abs(p.thk - NOMINAL.thk), Math.abs(p.ribH - NOMINAL.ribH), Math.abs(p.ribT - NOMINAL.ribT), Math.abs(p.holeU - NOMINAL.holeU) * 0.4).toFixed(3));
};

let bodiesCache: ReturnType<typeof cushionGlb>["bodies"] | null = null;
const nominalBodies = () => (bodiesCache ??= cushionGlb(NOMINAL, false).bodies);

function turbo(f: number): [number, number, number] {
  const c = TURBO16[Math.max(0, Math.min(15, Math.floor(f * 16)))];
  return [c[0], c[1], c[2]];
}

/** 셀 PNG: 가상 쿠션 윗면 — 변위 색 슬래브 + 리브 줄 + 구멍. 실패 셀은 공칭 회색 + 원인 면 빨강 */
export function cellPng(values: Record<string, number>, kind: "nominal" | "ok" | "fail"): Uint8Array {
  const p = params(values);
  const f = kind === "nominal" ? 0 : Math.min(1, maxDispOf(values) / RANGE[1]);
  const base = kind === "nominal" || kind === "fail" ? ([200, 204, 210] as [number, number, number]) : turbo(0.12 + 0.8 * f);
  const holeX = 70 + (p.holeU / 120) * 160;
  const ribX = 150 + (p.ribT - 3) * 40;
  return encodePng(320, 240, (x, y) => {
    if (x < 36 || x > 284 || y < 56 || y > 196) return [250, 250, 250];
    if (kind === "fail" && Math.abs(x - 150) < 6 + p.ribT * 2) return [220, 40, 40];
    if (Math.hypot(x - holeX, y - 126) < 11) return [250, 250, 250];
    if (Math.abs(x - ribX) < p.ribT * 1.6) return base.map((c) => Math.max(0, c - 55)) as [number, number, number];
    const edge = x < 38 || x > 282 || y < 58 || y > 194;
    return edge ? [70, 70, 70] : base;
  });
}

const bin = (srv: MockServer, studyId: string, kind: string, rel: string, ct: string, render: () => Uint8Array): string => {
  const id = srv.nid("a");
  srv.artifacts.push({ id, study_id: studyId, job_id: "", kind: kind as Artifact["kind"], file_name: rel.split("/").pop()!, size: 0, sha256: null, content_type: ct, created_at: new Date().toISOString(), body: "", render });
  return id;
};

function topChanges(vars: Var[], values: Record<string, number>) {
  return vars
    .map((v) => ({ name: v.name, value: values[v.name], rel: Number(rel(v, values[v.name]).toFixed(3)) }))
    .filter((c) => Math.abs(c.rel) > 1e-9)
    .sort((a, b) => Math.abs(b.rel) - Math.abs(a.rel))
    .slice(0, 3);
}

interface Row {
  doe_no: number | null;
  values: Record<string, number>;
  gen?: DoePreviewCell["gen"];
}

/** 셀 완성본(PNG·GLB·manifest 산출물 포함) — 순번(페이지 안 위치)이 실패·오류·잘림 시나리오를 정한다 */
function finishCell(srv: MockServer, studyId: string, vars: Var[], row: Row, pos: number, mode: DpMode, gallery: boolean): DoePreviewCell {
  const nominal = row.doe_no == null;
  const tag = nominal ? "nominal" : `${studyId}-${row.doe_no}-${JSON.stringify(row.values).length}`;
  const base: DoePreviewCell = { doe_no: row.doe_no, nominal, status: "OK", values: row.values, top_changes: topChanges(vars, row.values), ...(row.gen ? { gen: row.gen } : {}) };
  const failAt = mode.clean ? [] : mode.fail ?? [4, 13];
  if (!nominal && failAt.includes(pos)) {
    const out = { ok: false as const, code: "GEOM_FEATURE_COLLISION", category: "CAD_FAILED", feature: "CUSH_L_RIB_T_2" };
    const man = previewManifest(row.values, out, null);
    return {
      ...base, status: "FAIL", code: out.code, category: out.category, message_ko: "피처 충돌 — RIB_T_2·HOLE_U_1", max_disp_mm: null, clipped: false,
      png_artifact_id: bin(srv, studyId, "GEOM_THUMB_PNG", `_cache/doe_preview/${tag}/thumb.png`, "image/png", () => cellPng(row.values, "fail")),
      glb_artifact_id: null, manifest_artifact_id: srv.addArtifact("", studyId, "GEOM_PREVIEW_MANIFEST", `_cache/doe_preview/${tag}/preview_manifest.json`, "application/json", JSON.stringify(man)),
    };
  }
  if (!nominal && mode.error && pos === 7 && !gallery) return { ...base, status: "ERROR", code: "VIEW_TOO_LARGE", message_ko: "미리보기 오류" };
  const md = nominal ? 0 : maxDispOf(row.values);
  const man = previewManifest(row.values, { ok: true, params: params(row.values) }, { bodies: nominalBodies(), maxDisp: md });
  return {
    ...base, max_disp_mm: md, clipped: !nominal && !mode.clean && pos === 19,
    png_artifact_id: bin(srv, studyId, "GEOM_THUMB_PNG", `_cache/doe_preview/${tag}/thumb.png`, "image/png", () => cellPng(row.values, nominal ? "nominal" : "ok")),
    glb_artifact_id: bin(srv, studyId, "GEOM_PREVIEW_GLB", `_cache/doe_preview/${tag}/preview.glb`, "model/gltf-binary", () => cushionGlb(params(row.values), !nominal).glb),
    manifest_artifact_id: srv.addArtifact("", studyId, "GEOM_PREVIEW_MANIFEST", `_cache/doe_preview/${tag}/preview_manifest.json`, "application/json", JSON.stringify(man)),
  };
}

const pending = (c: DoePreviewCell): DoePreviewCell => ({ doe_no: c.doe_no, nominal: c.nominal, status: "PENDING", values: c.values, top_changes: c.top_changes, ...(c.gen ? { gen: c.gen } : {}) });

function view(r: Rec): DoePreview {
  const cells = r.full.map((c, i) => (i < r.done ? c : pending(c)));
  const active = !r.cancelled && r.done < r.full.length;
  return { ...r.pv, status: r.cancelled ? "CANCELED" : active ? "RUNNING" : "DONE", cells, queue: null, warnings: r.full.some((c) => c.status === "ERROR") && r.done >= r.full.length ? [{ code: "DOE_PREVIEW_PARTIAL", message: "일부 셀을 만들지 못했습니다" }] : [] };
}

function select(rows: Row[], vars: Var[], sel: DoePreviewReq["select"]): Row[] {
  const sorted = [...rows];
  if (sel.order === "change") {
    const norm = (r: Row) => Math.sqrt(vars.reduce((a, v) => a + rel(v, r.values[v.name]) ** 2, 0));
    sorted.sort((a, b) => norm(b) - norm(a) || (a.doe_no ?? 0) - (b.doe_no ?? 0));
  } else if (sel.order === "var" && sel.var) {
    const k = sel.var;
    const d = sel.desc ? -1 : 1;
    sorted.sort((a, b) => d * (a.values[k] - b.values[k]) || (a.doe_no ?? 0) - (b.doe_no ?? 0));
  } else sorted.sort((a, b) => (a.doe_no ?? 0) - (b.doe_no ?? 0));
  const limit = Math.max(1, Math.min(48, sel.limit || 24));
  const nominal = sel.offset === 0 ? [{ doe_no: null, values: {} } as Row] : [];
  const start = sel.offset === 0 ? 0 : sel.offset - 1;
  return [...nominal, ...sorted.slice(start, start + limit - nominal.length)];
}

export const doePreviewRoutes: Route = (srv, { method, seg, body }) => {
  const s = st(srv);
  if (seg[0] === "studies" && seg[2] === "doe-previews" && method === "POST") {
    const study = srv.studies.find((x) => x.id === seg[1]);
    if (!study) return err(404, "NOT_FOUND", "Study를 찾을 수 없습니다.");
    const deny = needPower(srv, study.project_id);
    if (deny) return deny;
    if (!srv.p2.feature("doe_preview").enabled) return err(409, "DOE_PREVIEW_UNAVAILABLE", "형상 미리보기가 꺼져 있습니다(관리자 설정)");
    const req = body as unknown as DoePreviewReq;
    const src = req?.source;
    if (!src || !["train", "param_set", "train_doe"].includes(src.kind) || !req.select) return err(422, "INPUT_INVALID", "요청 본문을 확인하세요");
    const ps = src.kind === "param_set" ? srv.paramSets.find((p) => p.id === src.param_set_id) ?? null : null;
    if (src.kind === "param_set" && (!ps || ps.engine !== "native")) return err(409, "DOE_PREVIEW_UNSUPPORTED", "형상 미리보기는 Native 형상 엔진에서만 쓸 수 있습니다");
    if (ps && (ps.baselines?.length ?? 0) > 1) return err(409, "DOE_PREVIEW_UNSUPPORTED", "다중 baseline DOE는 형상 미리보기를 지원하지 않습니다");
    let vars: Var[];
    let rows: Row[];
    if (src.kind === "train_doe") {
      const samples = srv.p2.doeSamples[String(src.doe_id)];
      if (!samples) return err(404, "NOT_FOUND", "DOE를 찾을 수 없습니다");
      const names = Object.keys(samples[0]?.values ?? {});
      vars = names.map((n) => {
        const xs = samples.map((r) => r.values[n]);
        const lo = Math.min(...xs);
        const hi = Math.max(...xs);
        return { name: n, nominal: (lo + hi) / 2, min: lo, max: hi };
      });
      rows = samples.map((r, i) => ({ doe_no: i + 1, values: r.values, gen: i === 11 ? { status: "SKIPPED", code: "GEOM_QUALITY", step: "check" } : i === 2 ? { status: "SKIPPED", code: "GEOM_FEATURE_COLLISION", step: "update" } : i >= 27 ? { status: "PENDING" } : { status: "OK" } }));
    } else {
      vars = varsOf(srv, study.id, ps);
      if (!vars.length) return err(422, "DOE_SAMPLING_INVALID", "사용할 변수가 없습니다", { problems: [{ code: "NO_NAMES", message: "사용할 변수가 없습니다" }] });
      const sp = (req.sampling ?? {}) as { count?: number; seed?: number };
      const n = Math.max(2, Math.min(2000, Number(sp.count) || 30));
      rows = matrix(vars, n, Number(sp.seed) || 1).map((values, i) => ({ doe_no: i + 1, values }));
    }
    const chosen = select(rows, vars, req.select);
    const key = JSON.stringify([src, req.sampling ?? null, req.select]);
    const hit = s.recs.find((r) => r.key === key && !r.cancelled);
    if (hit) {
      const v = view(hit);
      return v.status === "DONE" ? ok({ ...v, cache_hit: true }) : ok(v, 202);
    }
    const gallery = src.kind === "train_doe";
    const full = chosen.map((r, i) => finishCell(srv, study.id, vars, r, i, s.mode, gallery));
    const pv: DoePreview = {
      id: srv.nid("dp"), job_id: srv.nid("j"), status: "RUNNING", cache_hit: false, queue: null, n_total: rows.length,
      order: rows.map((r) => r.doe_no as number), tag_state: src.kind === "train" ? "none" : "tagged", disp_range_mm: RANGE, colormap: "turbo16", cells: [], warnings: [], timing: null,
    };
    const rec: Rec = { pv, key, full, done: 0, perPoll: s.mode.perPoll ?? 12, hold: !!s.mode.hold, cancelled: false };
    s.recs.push(rec);
    return ok(view(rec), 202);
  }
  if (seg[0] === "doe-previews" && seg[1]) {
    const rec = s.recs.find((r) => r.pv.id === seg[1]);
    if (!rec) return err(404, "NOT_FOUND", "형상 미리보기를 찾을 수 없습니다");
    if (method === "GET" && !seg[2]) {
      if (!rec.cancelled) {
        const cap = rec.hold ? Math.min(rec.full.length, 12) : rec.full.length;
        rec.done = Math.min(cap, rec.done + rec.perPoll);
      }
      const v = view(rec);
      if (v.status === "DONE") v.timing = { total_s: 41.2 };
      return ok(v);
    }
    if (method === "POST" && seg[2] === "cancel") {
      if (rec.cancelled || rec.done >= rec.full.length) return err(409, "JOB_TERMINAL", "이미 끝난 미리보기입니다");
      rec.cancelled = true;
      return ok(view(rec), 202);
    }
  }
  return null;
};
