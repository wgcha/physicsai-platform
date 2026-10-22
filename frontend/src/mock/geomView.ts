// 형상 3D 뷰·미리보기·결과 3D 컨투어 목(geometry-view.md §6.5·§6.9·§13.5, openapi 모양):
// GET /param-sets/{id}/view · GET /studies/{id}/train/view · POST /param-sets/{id}/previews(200 적중 | 202) · GET /previews/{id}
// POST /contour3d(200 | 202) · GET /contour3d/{id}(조회마다 한 단계 진행 — 대기 안내 시연) · POST /contour3d/{id}/cancel
// GET /artifacts/{id}/media(GEOM_*·CONTOUR3D_*, Range 206, 만료 = 410 ARTIFACT_EXPIRED).
// 시연 모드(setGvMode): c3d="hold"면 컨투어 생성이 '프레임 변환'에서 멈춤, "fail"이면 결과 실패, "jobfail"이면 작업 실패(FAILED), "expire"면 첫 프레임 요청에 410 1회.
// c3dBusy=n이면 새 생성 요청을 n번 429(PREVIEW_BUSY)로 거절. POST /contour3d는 캐시 적중·진행 중이면 읽기 사용자도 허용, 새 생성은 power(contour3d-default C3D-6).
import type { Artifact, Contour3d, Contour3dPhase, Contour3dProgress, GeomPreview, GeomView } from "../api/types";
import { contourData, cushionGlb, NOMINAL, previewManifest, previewOutcome, viewManifest } from "./geomViewData";
import { err, needPower, ok, type MockResp, type Route } from "./route";
import type { MockServer } from "./server";

export interface GvMode {
  c3d?: "hold" | "fail" | "jobfail" | "expire" | null;
  /** 새 컨투어 생성 요청을 n번 429(PREVIEW_BUSY)로 거절(캐시 적중은 영향 없음) */
  c3dBusy?: number;
  /** 미리보기 완료까지 GET 횟수(기본 1) */
  previewPolls?: number;
  /** 공칭 뷰를 쉘(양면·고정 클러스터 1개)로 */
  shell?: boolean;
}

interface PreviewRec extends GeomPreview {
  key: string;
  polls: number;
}
interface C3Rec extends Contour3d {
  key: string;
  polls: number;
}
interface GvState {
  mode: GvMode;
  views: Map<string, { glb: string; manifest: string }>;
  previews: PreviewRec[];
  contours: C3Rec[];
  expired: Set<string>;
  expireOnce: boolean;
}

const STATE = new WeakMap<MockServer, GvState>();
function st(srv: MockServer): GvState {
  let s = STATE.get(srv);
  if (!s) {
    s = { mode: {}, views: new Map(), previews: [], contours: [], expired: new Set(), expireOnce: false };
    STATE.set(srv, s);
  }
  return s;
}

export function setGvMode(srv: MockServer, mode: GvMode) {
  const s = st(srv);
  s.mode = { ...s.mode, ...mode };
  s.expireOnce = mode.c3d === "expire";
}

/** 캐시 정리 흉내: 산출물을 만료(410)로 */
export function expireArtifacts(srv: MockServer, ids: (string | null | undefined)[], rows = true) {
  const s = st(srv);
  ids.forEach((id) => id && s.expired.add(id));
  if (rows) ids.forEach((id) => id && markExpired(s, id));
}

/** 그 산출물을 쓰는 미리보기·컨투어 행을 EXPIRED로(housekeeping 흉내) */
function markExpired(s: GvState, id: string) {
  for (const r of [...s.previews, ...s.contours]) if ([r.glb_artifact_id, r.manifest_artifact_id, (r as C3Rec).frames_artifact_id, (r as PreviewRec).fe_glb_artifact_id].includes(id)) r.status = "EXPIRED";
}

/** 시험용: 목 미리보기·컨투어 기록 */
export const gvRecords = (srv: MockServer) => ({ previews: st(srv).previews, contours: st(srv).contours });

function addBin(srv: MockServer, studyId: string, kind: Artifact["kind"], rel: string, ct: string, render: () => Uint8Array): string {
  const id = srv.nid("a");
  srv.artifacts.push({ id, study_id: studyId, job_id: "", kind, file_name: rel.split("/").pop()!, size: 0, sha256: null, content_type: ct, created_at: new Date().toISOString(), body: "", render });
  return id;
}

function nominalView(srv: MockServer, key: string, studyId: string, rel: string) {
  const s = st(srv);
  let v = s.views.get(key);
  if (!v) {
    const g = cushionGlb(NOMINAL, false);
    const m = viewManifest(g.bodies, g.glb.byteLength);
    if (s.mode.shell) Object.assign(m, { kind: "shell", fixed_clusters: [{ id: 1, center: [60, 8, 0], radius_mm: 5, kinds: ["BOLT"], body: "CUSH_L", node: "CUSH_L.fixed", faces: ["F1"] }] });
    v = {
      glb: addBin(srv, studyId, "GEOM_VIEW_GLB", `${rel}/view.glb`, "model/gltf-binary", () => g.glb),
      manifest: srv.addArtifact("", studyId, "GEOM_VIEW_MANIFEST", `${rel}/view_manifest.json`, "application/json", JSON.stringify(m)),
    };
    s.views.set(key, v);
  }
  return v;
}

function viewOut(srv: MockServer, v: { glb: string; manifest: string }, extra: Partial<GeomView>): GeomView {
  const on = srv.p2.feature("geometry_view").enabled;
  return {
    status: "READY", kind: "solid", reason: null, glb_artifact_id: v.glb, manifest_artifact_id: v.manifest,
    tess: { linear_mm: 0.1, angular_deg: 20 }, engine_version: "0.10.0", available: on, preview_available: on, param_set_id: null, train_setup_id: null, ...extra,
  };
}

const PREVIEW_MSG: Record<string, string> = { GEOM_FEATURE_COLLISION: "피처끼리 충돌합니다 — 형상을 만들 수 없습니다" };

function finishPreview(srv: MockServer, p: PreviewRec) {
  const out = previewOutcome(p.values);
  const glb = out.ok ? cushionGlb(out.params, true) : null;
  const m = previewManifest(p.values, out, glb);
  p.status = "DONE";
  p.result_status = out.ok ? "OK" : "FAIL";
  p.code = out.ok ? null : out.code;
  p.category = out.ok ? null : out.category;
  p.message_ko = out.ok ? null : PREVIEW_MSG[out.code] ?? out.code;
  p.glb_artifact_id = glb ? addBin(srv, "s-cushion", "GEOM_PREVIEW_GLB", `_cache/geom_preview/${p.id}/preview.glb`, "model/gltf-binary", () => glb.glb) : null;
  p.manifest_artifact_id = srv.addArtifact("", "s-cushion", "GEOM_PREVIEW_MANIFEST", `_cache/geom_preview/${p.id}/preview_manifest.json`, "application/json", JSON.stringify(m));
  p.timing = { update_s: 1.2, tess_s: 0.3, total_s: 2.1 };
  p.finished_at = new Date().toISOString();
}

const C3_ORDER: Contour3dPhase[] = ["waiting", "reading_h3d", "geometry", "frames", "done"];
const C3_LABEL: Record<string, string> = { waiting: "대기", reading_h3d: "H3D 읽기", geometry: "형상", frames: "프레임 변환", done: "완료", failed: "실패", canceled: "취소", expired: "만료" };

function c3Progress(phase: Contour3dPhase, elapsed: number, estimate: number | null, canCancel: boolean): Contour3dProgress {
  const k = C3_ORDER.indexOf(phase);
  return { phase, phase_label: C3_LABEL[phase], percent: k < 0 ? null : phase === "frames" ? 62 : Math.round((k / 4) * 100), elapsed_s: elapsed, estimate_s: estimate, can_cancel: canCancel, step_key: null, label: null };
}

function finishContour(srv: MockServer, c: C3Rec, fail: boolean) {
  c.status = "DONE";
  c.finished_at = new Date().toISOString();
  c.progress = c3Progress("done", 74, 95, false);
  if (fail) {
    c.result_status = "FAIL";
    c.code = "CONTOUR3D_FIELD_EMPTY";
    c.message_ko = "선택한 결과 값이 없습니다";
    return;
  }
  const d = contourData(c.source_kind, c.source_ref);
  const rel = `_cache/contour3d/${c.id}`;
  c.result_status = "OK";
  c.glb_artifact_id = addBin(srv, "s-cushion", "CONTOUR3D_GLB", `${rel}/contour.glb`, "model/gltf-binary", () => d.glb);
  c.frames_artifact_id = addBin(srv, "s-cushion", "CONTOUR3D_FRAMES", `${rel}/contour_frames.bin`, "application/octet-stream", () => d.frames);
  c.manifest_artifact_id = srv.addArtifact("", "s-cushion", "CONTOUR3D_MANIFEST", `${rel}/contour_manifest.json`, "application/json", JSON.stringify(d.manifest));
  c.frames = d.manifest.frames.count;
  c.nodes = d.manifest.mesh.nodes;
  c.bytes = d.frames.byteLength + d.glb.byteLength;
  c.timing = { total_s: 74 };
}

function media(srv: MockServer, id: string, range: string | null): MockResp | null {
  const a = srv.artifacts.find((x) => x.id === id);
  if (!a || !(a.kind.startsWith("GEOM_") || a.kind.startsWith("CONTOUR3D_"))) return null;
  const s = st(srv);
  if (s.expired.has(id)) {
    markExpired(s, id);
    return err(410, "ARTIFACT_EXPIRED", "미리보기 파일이 정리되었습니다 — 다시 미리보기 하세요");
  }
  if (a.kind === "CONTOUR3D_FRAMES" && s.expireOnce && range) {
    s.expireOnce = false;
    // 캐시 정리 흉내: 이 결과의 행을 EXPIRED로 바꾸고 410
    const c = s.contours.find((x) => x.frames_artifact_id === id);
    if (c) {
      c.status = "EXPIRED";
      [c.glb_artifact_id, c.frames_artifact_id, c.manifest_artifact_id].forEach((x) => x && s.expired.add(x));
    }
    return err(410, "ARTIFACT_EXPIRED", "파일이 정리되었습니다 — 다시 요청하세요");
  }
  const bytes = a.render ? a.render() : new TextEncoder().encode(a.body);
  const m = range ? /^bytes=(\d+)-(\d*)$/.exec(range) : null;
  if (m) {
    const start = Number(m[1]);
    const end = m[2] ? Math.min(Number(m[2]), bytes.length - 1) : bytes.length - 1;
    if (start >= bytes.length || end < start) return { status: 416, text: "", headers: { "Content-Range": `bytes */${bytes.length}` } };
    return { status: 206, bytes: bytes.slice(start, end + 1), contentType: a.content_type, headers: { "Content-Range": `bytes ${start}-${end}/${bytes.length}`, "Accept-Ranges": "bytes" } };
  }
  return { status: 200, bytes, contentType: a.content_type, headers: { "Accept-Ranges": "bytes" } };
}

export const geomViewRoutes: Route = (srv, { method, seg, body, headers }) => {
  const s = st(srv);
  if (method === "GET" && seg[0] === "artifacts" && seg[1] && seg[2] === "media") return media(srv, seg[1], headers.get("Range"));
  if (method === "GET" && seg[0] === "artifacts" && seg[1] && seg[2] === "content" && s.expired.has(seg[1])) {
    markExpired(s, seg[1]);
    return err(410, "ARTIFACT_EXPIRED", "파일이 정리되었습니다");
  }

  // ① 공칭 뷰(§6.9)
  if (method === "GET" && seg[0] === "studies" && seg[2] === "train" && seg[3] === "view") {
    const setup = srv.p2.setups[seg[1]];
    if (!setup) return err(404, "NOT_FOUND", "학습 설정이 없습니다");
    if (setup.engine !== "native") return ok({ status: "MISSING", kind: "solid", reason: "Native 추출이 아닙니다", available: false, preview_available: false, param_set_id: null, train_setup_id: seg[1] } satisfies GeomView);
    const v = nominalView(srv, `train:${seg[1]}:${setup.extract_job_id ?? ""}`, seg[1], `01_train/extract/${setup.extract_job_id ?? "x"}/view`);
    return ok(viewOut(srv, v, { train_setup_id: seg[1], preview_available: false }));
  }

  if (seg[0] === "param-sets" && seg[1] && (seg[2] === "view" || seg[2] === "previews")) {
    const ps = srv.paramSets.find((p) => p.id === seg[1]);
    if (!ps) return err(404, "NOT_FOUND", "파라미터 세트를 찾을 수 없습니다.");
    if (ps.engine !== "native") return err(409, "VIEW_NATIVE_ONLY", "3D 미리보기는 Native 템플릿에서만 쓸 수 있습니다");
    if (method === "GET" && seg[2] === "view") return ok(viewOut(srv, nominalView(srv, ps.id, ps.study_id, `04_params/${ps.id}/native/view`), { param_set_id: ps.id }));
    if (method === "POST" && seg[2] === "previews") {
      const study = srv.studies.find((x) => x.id === ps.study_id)!;
      const deny = needPower(srv, study.project_id);
      if (deny) return deny;
      const values = (body?.values ?? {}) as Record<string, number>;
      const names = new Set(ps.parameters.map((p) => p.name));
      for (const [k, v] of Object.entries(values)) {
        if (!names.has(k) || typeof v !== "number" || !Number.isFinite(v)) return err(422, "INPUT_INVALID", `알 수 없는 이름이거나 값이 올바르지 않습니다: ${k}`, { loc: ["values", k] });
      }
      const fe = body?.fe === "check" ? "check" : "off";
      const key = JSON.stringify([ps.id, Object.entries(values).sort(([a], [b]) => a.localeCompare(b)), fe]);
      const hit = s.previews.find((p) => p.key === key && (p.status === "DONE" || p.status === "QUEUED" || p.status === "RUNNING"));
      if (hit?.status === "DONE") return ok({ ...strip(hit), cache_hit: true });
      if (hit) return ok(strip(hit), 202);
      // 같은 세트의 대기 미리보기는 취소(최신 값 우선, §6.4-3)
      s.previews.filter((p) => p.param_set_id === ps.id && p.status === "QUEUED").forEach((p) => (p.status = "CANCELED"));
      const rec: PreviewRec = {
        id: srv.nid("gp"), key, polls: 0, param_set_id: ps.id, job_id: srv.nid("j"), status: "RUNNING", cache_hit: false, values, fe,
        result_status: null, code: null, category: null, message_ko: null, fe_status: null, fe_code: null,
        glb_artifact_id: null, fe_glb_artifact_id: null, manifest_artifact_id: null, timing: null, created_at: new Date().toISOString(), finished_at: null,
      };
      s.previews.push(rec);
      return ok(strip(rec), 202);
    }
    return null;
  }
  if (method === "GET" && seg[0] === "previews" && seg[1]) {
    const p = s.previews.find((x) => x.id === seg[1]);
    if (!p) return err(404, "NOT_FOUND", "미리보기를 찾을 수 없습니다");
    if (p.status === "RUNNING" && ++p.polls >= (s.mode.previewPolls ?? 1)) finishPreview(srv, p);
    return ok(strip(p));
  }

  // 결과 3D 컨투어(§13.5)
  if (seg[0] === "contour3d") {
    if (method === "POST" && !seg[1]) {
      const study = srv.studies.find((x) => x.id === "s-cushion")!;
      if (!srv.p2.feature("contour3d").enabled) return err(409, "CONTOUR3D_NOT_CONFIGURED", "3D 컨투어를 쓸 수 없습니다 — 설정 확인");
      const kind = body?.source_kind;
      const ref = (body?.source_ref ?? {}) as Record<string, string>;
      if (kind !== "PREDICT_H3D" && kind !== "SOLVER_H3D") return err(422, "INPUT_INVALID", "source_kind를 확인하세요");
      if (kind === "PREDICT_H3D" && !srv.jobs.some((j) => j.id === ref.job_id && j.state === "SUCCEEDED")) return err(409, "PREREQUISITE_MISSING", "예측 결과 h3d가 없습니다");
      const key = JSON.stringify([kind, ref, body?.display ?? null]);
      const hit = s.contours.find((c) => c.key === key && ["QUEUED", "RUNNING", "DONE"].includes(c.status));
      // C3D-6: 캐시 적중·진행 중(공유)은 읽기 사용자도 허용, 새 생성은 power
      if (hit?.status === "DONE") return ok({ ...strip(hit), cache_hit: true });
      if (hit) return ok(strip(hit), 202);
      const deny = needPower(srv, study.project_id);
      if (deny) return deny;
      if ((s.mode.c3dBusy ?? 0) > 0) {
        s.mode.c3dBusy = (s.mode.c3dBusy ?? 0) - 1;
        return err(429, "PREVIEW_BUSY", "앞선 3D 생성이 끝나면 다시 요청하세요");
      }
      const rec: C3Rec = {
        id: srv.nid("c3"), key, polls: 0, job_id: srv.nid("j"), status: "QUEUED", cache_hit: false, source_kind: kind, source_ref: ref, display: (body?.display as Record<string, unknown>) ?? null,
        result_status: null, code: null, message_ko: null, frames: null, nodes: null, bytes: null,
        glb_artifact_id: null, frames_artifact_id: null, manifest_artifact_id: null, timing: null, created_at: new Date().toISOString(), finished_at: null,
        progress: c3Progress("waiting", 0, 95, true),
      };
      s.contours.push(rec);
      return ok(strip(rec), 202);
    }
    const c = s.contours.find((x) => x.id === seg[1]);
    if (!c) return err(404, "NOT_FOUND", "3D 컨투어를 찾을 수 없습니다");
    if (method === "POST" && seg[2] === "cancel") {
      if (c.status !== "QUEUED" && c.status !== "RUNNING") return err(409, "JOB_TERMINAL", "이미 끝난 생성입니다");
      c.status = "CANCELED";
      c.progress = { ...c3Progress("canceled", c.progress?.elapsed_s ?? 0, 95, false), step_key: c.progress?.phase ?? null };
      return ok(strip(c));
    }
    if (method === "GET" && !seg[2]) {
      if (c.status === "QUEUED" || c.status === "RUNNING") {
        if (s.mode.c3d === "jobfail") {
          c.status = "FAILED";
          c.code = "CONTOUR3D_JOB_FAILED";
          c.message_ko = "H3D 읽기 도구가 종료되었습니다";
          c.progress = { ...c3Progress("failed", 12, 95, false), step_key: "reading_h3d" };
          return ok(strip(c));
        }
        const hold = s.mode.c3d === "hold";
        const k = hold ? 3 : Math.min(4, ++c.polls);
        const phase = C3_ORDER[k];
        if (phase === "done") finishContour(srv, c, s.mode.c3d === "fail");
        else {
          c.status = k === 0 ? "QUEUED" : "RUNNING";
          c.progress = c3Progress(phase, hold ? 46 : k * 12, 95, true);
        }
      }
      return ok(strip(c));
    }
  }
  return null;
};

function strip<T extends { key: string; polls: number }>(r: T): Omit<T, "key" | "polls"> {
  const { key: _k, polls: _p, ...rest } = r;
  void _k;
  void _p;
  return rest;
}
