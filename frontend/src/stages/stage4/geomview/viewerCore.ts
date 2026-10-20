// 형상 3D 뷰 순수 로직(geometry-view.md §4.2·§4.3·§7) — three 없이 시험한다.
// manifest 해석: 행(parameter) ↔ 면(body·_FACE_ID) 매핑, 치수선 데이터, 슬라이더 범위, 실패 표시, WebGL 확인.
import type { GeomPreview } from "../../../api";
import { GEN_CATEGORY_LABEL } from "../../../lib/geometry";

export type Vec3 = [number, number, number];

export interface ManifestFace {
  id: string;
  surface?: string;
  tri: [number, number];
  area?: number;
}
export interface ManifestBody {
  body: string;
  node: string;
  edges_node?: string | null;
  faces: ManifestFace[];
}
export interface Dimension {
  kind: "linear" | "radius" | "position";
  p0: Vec3;
  p1: Vec3;
  label: Vec3;
  value: number;
  unit: string;
  geom_len?: number;
}
export interface ManifestFeature {
  name: string;
  parameter: string;
  type: string;
  body: string;
  nominal: number | null;
  value: number | null;
  unit: string;
  range?: { min: number | null; max: number | null } | null;
  feasible?: { min: number | null; max: number | null; source?: string | null } | null;
  faces: { moving: string[]; fixed: string[]; other?: string[] };
  dimension: Dimension | null;
}
export interface FixedCluster {
  id: string | number;
  center: Vec3;
  radius_mm: number;
  kinds?: string[];
  body?: string;
  node?: string;
  faces?: string[];
}
export interface ViewManifest {
  schema_version: number;
  kind: "solid" | "shell";
  mode: "nominal" | "preview";
  status: "OK" | "FAIL";
  code?: string | null;
  category?: string | null;
  message?: string | null;
  unit?: string;
  up_axis?: string;
  bbox?: number[];
  bodies: ManifestBody[];
  features: ManifestFeature[];
  fixed_clusters?: FixedCluster[];
  warnings?: { code: string; face?: string; feature?: string }[];
}
export interface PreviewManifest extends ViewManifest {
  values?: Record<string, number>;
  disp?: { attribute?: string; max_mm: number | null; by_face?: Record<string, Record<string, { max: number; mean: number; change: string }>> } | null;
  fe?: { mode: string; status?: string | null; code?: string | null; max_disp_mm?: number | null; glb?: unknown } | null;
  failure?: { features?: string[]; clusters?: (string | number)[]; points?: { xyz: Vec3; label?: string }[] } | null;
  timing?: Record<string, number | null> | null;
}

// ---------------------------------------------------------------- 면 키

/** "F12" → 12 (형식이 다르면 NaN) */
export function faceNo(id: string): number {
  const m = /^F(\d+)$/.exec(id);
  return m ? Number(m[1]) : NaN;
}
/** 바디 + 면 번호 → 키 "CUSH_L#12" */
export const faceKey = (body: string, face: number | string) => `${body}#${typeof face === "number" ? face : faceNo(face)}`;

/** 표 행 이름 목록(parameter 기준, 처음 나온 순서) */
export function parameterRows(m: ViewManifest): string[] {
  return [...new Set(m.features.map((f) => f.parameter || f.name))];
}

/** 면 → 그 면을 쓰는(moving·fixed) 피처의 행 이름들. 3D → 표 선택용 */
export function buildFaceRows(m: ViewManifest): Map<string, string[]> {
  const out = new Map<string, string[]>();
  for (const f of m.features) {
    const row = f.parameter || f.name;
    for (const id of [...f.faces.moving, ...f.faces.fixed]) {
      const k = faceKey(f.body, id);
      const list = out.get(k) ?? [];
      if (!list.includes(row)) list.push(row);
      out.set(k, list);
    }
  }
  return out;
}

export interface Highlight {
  moving: Set<string>;
  fixed: Set<string>;
  red: Set<string>;
  dims: DimDraw[];
}
export const EMPTY_HIGHLIGHT: Highlight = { moving: new Set(), fixed: new Set(), red: new Set(), dims: [] };

/** 행 선택 → parameter가 같은 피처 전부(대칭 그룹 구성원 포함)의 이동 면(주황)·고정 면(파랑)·치수선. 이동이 고정보다 우선 */
export function rowHighlight(m: ViewManifest, row: string | null): Highlight {
  if (!row) return EMPTY_HIGHLIGHT;
  const moving = new Set<string>();
  const fixed = new Set<string>();
  const dims: DimDraw[] = [];
  for (const f of m.features) {
    if ((f.parameter || f.name) !== row && f.name !== row) continue;
    f.faces.moving.forEach((id) => moving.add(faceKey(f.body, id)));
    f.faces.fixed.forEach((id) => fixed.add(faceKey(f.body, id)));
    const d = dimDraw(f.dimension);
    if (d) dims.push(d);
  }
  moving.forEach((k) => fixed.delete(k));
  return { moving, fixed, red: new Set(), dims };
}

/** 그 행이 3D에 대응하는가(manifest에 피처가 있고 면 또는 치수가 있음). 쉘 두께(PROP) 행은 false → "3D 대응 없음" */
export function hasRow3d(m: ViewManifest, row: string): boolean {
  return m.features.some((f) => ((f.parameter || f.name) === row || f.name === row) && (f.faces.moving.length + f.faces.fixed.length > 0 || !!f.dimension));
}

// ---------------------------------------------------------------- 치수선

export interface DimDraw {
  line: [Vec3, Vec3];
  label: Vec3;
  text: string;
}

/** 숫자 표시(소수 4자리까지, 뒤 0 제거) */
export function fmtVal(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "–";
  return String(Number(v.toFixed(4)));
}

/** 치수 라벨: 선형·위치 "12.5 mm", 반경 "R 2 mm" — 값은 항상 dimension.value(= features·values 값) */
export function dimText(d: Dimension): string {
  return `${d.kind === "radius" ? "R " : ""}${fmtVal(d.value)} ${d.unit || "mm"}`;
}

const finite3 = (p: unknown): p is Vec3 => Array.isArray(p) && p.length === 3 && p.every((x) => typeof x === "number" && Number.isFinite(x));

/** manifest dimension → 그릴 선·라벨(점이 비유한이면 null) */
export function dimDraw(d: Dimension | null | undefined): DimDraw | null {
  if (!d || !finite3(d.p0) || !finite3(d.p1)) return null;
  const label = finite3(d.label) ? d.label : ([(d.p0[0] + d.p1[0]) / 2, (d.p0[1] + d.p1[1]) / 2, (d.p0[2] + d.p1[2]) / 2] as Vec3);
  return { line: [d.p0, d.p1], label, text: dimText(d) };
}

// ---------------------------------------------------------------- 미리보기 입력

export interface SliderSpec {
  min: number;
  max: number;
  step: number;
  band: { min: number; max: number } | null;
  source: "envelope" | "estimate" | "range";
  sourceText: string;
}

const SOURCE_TEXT = { envelope: "envelope 측정", estimate: "추정", range: "사용자 범위" } as const;

/** 슬라이더 범위 = feasible(없으면 range), 띠 = 사용자 범위(표 값 우선 → manifest range) */
export function sliderSpec(f: ManifestFeature, user?: { min?: number | null; max?: number | null } | null): SliderSpec | null {
  const band = user?.min != null && user?.max != null ? { min: user.min, max: user.max } : f.range?.min != null && f.range?.max != null ? { min: f.range.min, max: f.range.max } : null;
  const fe = f.feasible;
  let lo = fe?.min ?? null;
  let hi = fe?.max ?? null;
  let source: SliderSpec["source"] = fe?.source === "envelope" ? "envelope" : "estimate";
  if (lo == null || hi == null) {
    lo = lo ?? band?.min ?? null;
    hi = hi ?? band?.max ?? null;
    if (fe?.min == null && fe?.max == null) source = "range";
  }
  if (lo == null || hi == null || !(hi > lo)) return null;
  const span = hi - lo;
  const step = Number((10 ** Math.floor(Math.log10(span / 200))).toPrecision(1));
  return { min: lo, max: hi, step, band, source, sourceText: SOURCE_TEXT[source] };
}

/** feasible 밖이면 경고(입력은 허용, §7.3) */
export function outsideFeasible(f: ManifestFeature, v: number): boolean {
  const fe = f.feasible;
  if (!fe) return false;
  return (fe.min != null && v < fe.min) || (fe.max != null && v > fe.max);
}

/** 대표 행의 공칭값 */
export function rowNominal(m: ViewManifest, row: string): number | null {
  const f = m.features.find((x) => x.name === row) ?? m.features.find((x) => x.parameter === row);
  return f?.nominal ?? null;
}

/** 편집값 중 공칭과 다른 것만 요청 본문으로(빠진 이름은 서버가 공칭으로 채움, §6.4) */
export function previewValues(m: ViewManifest, edits: Record<string, number>): Record<string, number> {
  const out: Record<string, number> = {};
  for (const [k, v] of Object.entries(edits)) {
    if (!Number.isFinite(v)) continue;
    const nom = rowNominal(m, k);
    if (nom == null || Math.abs(v - nom) > 1e-12) out[k] = v;
  }
  return out;
}

// ---------------------------------------------------------------- 미리보기 결과

export type PreviewPhase = "idle" | "running" | "ok" | "fail" | "error" | "expired";

export function previewPhase(p: GeomPreview | null): PreviewPhase {
  if (!p) return "idle";
  if (p.status === "QUEUED" || p.status === "RUNNING") return "running";
  if (p.status === "DONE") return p.result_status === "FAIL" ? "fail" : "ok";
  if (p.status === "EXPIRED") return "expired";
  return "error";
}

/** 실패 배지 문구: GE §8 묶음 + VIEW·FIXED */
export const PREVIEW_CATEGORY_LABEL: Record<string, string> = { ...GEN_CATEGORY_LABEL, VIEW: "3D 변환 실패", FIXED: "고정 영역 침범", COLLISION: "충돌" };

/** code·category → 배지(category 없으면 코드 이름으로 추정) */
export function failureBadge(category: string | null | undefined, code: string | null | undefined): string {
  if (category && PREVIEW_CATEGORY_LABEL[category]) return PREVIEW_CATEGORY_LABEL[category];
  const c = code ?? "";
  if (/COLLISION|INTERFER/.test(c)) return "충돌";
  if (/QUALITY/.test(c)) return PREVIEW_CATEGORY_LABEL.QUALITY;
  if (/FIXED/.test(c)) return PREVIEW_CATEGORY_LABEL.FIXED;
  if (/^VIEW_/.test(c)) return PREVIEW_CATEGORY_LABEL.VIEW;
  if (/^(GEOM|SHELL)_/.test(c)) return PREVIEW_CATEGORY_LABEL.CAD_FAILED;
  return category ?? "실패";
}

/** 실패 표시: failure.features 피처의 이동·고정 면 빨강, clusters·points 빨강 */
export function failureHighlight(pm: PreviewManifest | null): { red: Set<string>; clusters: Set<string>; points: { xyz: Vec3; label: string }[] } {
  const red = new Set<string>();
  const clusters = new Set<string>();
  const points: { xyz: Vec3; label: string }[] = [];
  const fl = pm?.failure;
  if (!pm || !fl) return { red, clusters, points };
  const names = new Set(fl.features ?? []);
  for (const f of pm.features) {
    if (!names.has(f.name) && !names.has(f.parameter)) continue;
    [...f.faces.moving, ...f.faces.fixed].forEach((id) => red.add(faceKey(f.body, id)));
  }
  (fl.clusters ?? []).forEach((c) => clusters.add(String(c)));
  for (const p of fl.points ?? []) if (finite3(p.xyz)) points.push({ xyz: p.xyz, label: p.label ?? "" });
  return { red, clusters, points };
}

/** 변위 색 맵 범위: 0 ~ disp.max_mm(형상) | fe.max_disp_mm(FE) */
export function dispMax(pm: PreviewManifest | null, fe: boolean): number | null {
  const v = fe ? pm?.fe?.max_disp_mm : pm?.disp?.max_mm;
  return v != null && Number.isFinite(v) ? v : null;
}

// ---------------------------------------------------------------- 면 그룹(하이라이트 = 삼각형 구간)

export type FaceMat = 0 | 1 | 2 | 3 | 4; // 0 기본 · 1 이동(주황) · 2 고정(파랑) · 3 빨강 · 4 흐림(선택 밖 회색 반투명)

/** 바디의 faces[].tri → 연속 구간 그룹(start·count는 정점 인덱스 단위 = 삼각형 × 3). 같은 재질 연속 면은 합친다 */
export function faceGroups(body: ManifestBody, h: Highlight): { start: number; count: number; mat: FaceMat }[] {
  const any = h.moving.size + h.fixed.size + h.red.size > 0;
  const out: { start: number; count: number; mat: FaceMat }[] = [];
  const faces = [...body.faces].sort((a, b) => a.tri[0] - b.tri[0]);
  for (const f of faces) {
    const k = faceKey(body.body, f.id);
    const mat: FaceMat = h.red.has(k) ? 3 : h.moving.has(k) ? 1 : h.fixed.has(k) ? 2 : any ? 4 : 0;
    const start = f.tri[0] * 3;
    const count = f.tri[1] * 3;
    if (count <= 0) continue;
    const last = out[out.length - 1];
    if (last && last.mat === mat && last.start + last.count === start) last.count += count;
    else out.push({ start, count, mat });
  }
  return out;
}

// ---------------------------------------------------------------- WebGL(§7.4)

export { detectWebGL } from "./webgl";

export const NO_WEBGL_3D = "이 환경에서는 3D 보기를 쓸 수 없습니다(WebGL 미지원) — 그림으로 표시합니다";
export const LOST_WEBGL_3D = "3D 표시가 중단되었습니다(그래픽 컨텍스트 손실) — 그림으로 표시합니다";
