// 결과 3D 컨투어 순수 로직(geometry-view.md §13.4·§13.6) — three 없이 시험한다.
// schema 1: contour_frames.bin = 프레임 우선 레코드(scalar float32[N] + 선택 disp float32[N][3], 리틀엔디언), offset(i) = i × record_bytes.
// schema 2(contour3d-field C3F-5·6): contour_frames.bin = uint16[N](65535 = NaN, 복원 = min + q·scale), contour_disp.bin = uint16[N][3](선택, 복원 = min[c] + q·scale[c]).
import type { Contour3d, Contour3dPhase } from "../../../../api";

export interface ContourFrameInfo {
  i: number;
  src: number;
  time: number | null;
  min: number | null;
  max: number | null;
  /** schema 2: 스칼라 양자화 간격 s_i(0 = 상수 프레임) */
  scale?: number | null;
  /** schema 2: 프레임 최소·최대 값의 정점 번호(GLB 정점 순서) */
  min_v?: number | null;
  max_v?: number | null;
}

export interface ContourLodInfo {
  file?: string;
  bytes?: number;
  vertices: number;
  triangles?: number;
  method?: string;
}

export interface ContourDispInfo {
  file?: string;
  bytes?: number;
  record_bytes: number;
  list: { i: number; min: [number, number, number]; scale: [number, number, number] }[];
}

export interface ContourLimits {
  nodes?: number;
  max_nodes?: number;
  glb_bytes?: number;
  max_glb_bytes?: number;
  bin_bytes?: number;
  max_bin_bytes?: number;
  disp_bytes?: number;
  max_disp_bytes?: number;
}

export interface ContourWarning {
  code?: string;
  count?: number;
  message?: string;
}

export interface ContourManifest {
  schema_version: number;
  kind: "contour3d";
  status: "OK" | "FAIL";
  code?: string | null;
  message?: string | null;
  display?: { field?: string | null; comp?: string | null; avgmode?: string | null } | null;
  unit?: string | null;
  length_unit?: string;
  up_axis?: string;
  mesh: { file?: string; nodes: number; triangles?: number; bytes?: number; compression?: "meshopt" | "none"; order?: string; normals?: string };
  frames: { file?: string; count: number; record_bytes: number; has_disp: boolean; dtype?: string; nan_code?: number; nan_count?: number; bytes?: number; list: ContourFrameInfo[] };
  /** schema 2: 저해상도 메시(없으면 null·생략) */
  lod?: ContourLodInfo | null;
  /** schema 2: 변위 파일(없으면 null — 변형 배율 컨트롤을 숨긴다) */
  disp?: ContourDispInfo | null;
  range: { min: number | null; max: number | null };
  limits?: ContourLimits | null;
  scope?: { comps?: string[]; comps_applicable?: boolean; applied?: boolean } | null;
  sampling?: { total_frames?: number; max_frames?: number; rule?: string } | null;
  warnings?: ContourWarning[] | string[];
}

export interface DecodedFrame {
  scalar: Float32Array;
  disp: Float32Array | null;
}

/** 레코드 바이트 수(§13.4): 4·N·(1 + 3·has_disp) */
export const recordBytes = (nodes: number, hasDisp: boolean) => 4 * nodes * (1 + (hasDisp ? 3 : 0));

/** 프레임 i의 Range(포함 끝) — `Range: bytes=start-end` */
export function frameRange(m: ContourManifest, i: number): [number, number] {
  const rb = m.frames.record_bytes || recordBytes(m.mesh.nodes, m.frames.has_disp);
  const start = i * rb;
  return [start, start + rb - 1];
}

const LITTLE = new Uint8Array(new Uint16Array([1]).buffer)[0] === 1;

/** 레코드 1개 디코딩. buf는 레코드 하나(또는 offset부터 시작하는 큰 버퍼) */
export function decodeFrame(buf: ArrayBuffer, nodes: number, hasDisp: boolean, offset = 0): DecodedFrame {
  const need = recordBytes(nodes, hasDisp);
  if (buf.byteLength - offset < need) throw new Error(`프레임 길이가 짧습니다(${buf.byteLength - offset} < ${need})`);
  const read = (byteOff: number, count: number): Float32Array => {
    if (LITTLE && byteOff % 4 === 0) return new Float32Array(buf.slice(byteOff, byteOff + count * 4));
    const dv = new DataView(buf, byteOff, count * 4);
    const out = new Float32Array(count);
    for (let k = 0; k < count; k++) out[k] = dv.getFloat32(k * 4, true);
    return out;
  };
  return { scalar: read(offset, nodes), disp: hasDisp ? read(offset + nodes * 4, nodes * 3) : null };
}

// ---------------------------------------------------------------- schema 2(uint16 양자화, contour3d-field §5)

export const NAN_CODE = 65535;
const MiB = 1024 * 1024;
/** 프레임 캐시 바이트 예산(§7.3): 스칼라 32 MiB · 변위 96 MiB, 각 최소 2프레임 */
export const SCALAR_BUDGET = 32 * MiB;
export const DISP_BUDGET = 96 * MiB;
/** 변형 배율 기본값을 1로 두는 변위 레코드 상한(§7.3) */
export const DISP_DEFAULT_MAX_BYTES = 2 * MiB;

/** uint16 양자화 manifest(schema 2)인가 */
export const isQuantized = (m: ContourManifest) => m.frames.dtype === "uint16q" || m.schema_version >= 2;

/** 변위가 있는가: schema 2 = `disp` 있음, schema 1 = `frames.has_disp` */
export const manifestHasDisp = (m: ContourManifest) => (isQuantized(m) ? m.disp != null && m.frames.has_disp !== false : !!m.frames.has_disp);

/** 스칼라 파일의 레코드 바이트(schema 1은 변위가 섞인 레코드) */
export const scalarRecordBytes = (m: ContourManifest) => m.frames.record_bytes || (isQuantized(m) ? 2 * m.mesh.nodes : recordBytes(m.mesh.nodes, m.frames.has_disp));

/** 변위 파일의 레코드 바이트(schema 2만, 없으면 0) */
export const dispRecordBytes = (m: ContourManifest) => (isQuantized(m) && m.disp ? m.disp.record_bytes || 6 * m.mesh.nodes : 0);

/** 변위 프레임 i의 Range(포함 끝) */
export function dispRange(m: ContourManifest, i: number): [number, number] {
  const rb = dispRecordBytes(m);
  return [i * rb, i * rb + rb - 1];
}

/** 변형 배율 기본값: 변위 없음 0 · schema 1 = 1 · schema 2 = 변위 레코드 ≤ 2 MiB(N ≤ 약 35만)면 1, 넘으면 0 */
export function defaultDeformScale(m: ContourManifest): number {
  if (!manifestHasDisp(m)) return 0;
  return !isQuantized(m) || dispRecordBytes(m) <= DISP_DEFAULT_MAX_BYTES ? 1 : 0;
}

function u16(buf: ArrayBuffer, offset: number, count: number): Uint16Array {
  if (buf.byteLength - offset < count * 2) throw new Error(`프레임 길이가 짧습니다(${buf.byteLength - offset} < ${count * 2})`);
  if (LITTLE && offset % 2 === 0) return new Uint16Array(buf, offset, count);
  const dv = new DataView(buf, offset, count * 2);
  const out = new Uint16Array(count);
  for (let k = 0; k < count; k++) out[k] = dv.getUint16(k * 2, true);
  return out;
}

/** 스칼라 레코드 복원(C3F-5): v̂ = min + q·scale, q = 65535 → NaN */
export function decodeScalarU16(buf: ArrayBuffer, nodes: number, min: number, scale: number, offset = 0): Float32Array {
  const q = u16(buf, offset, nodes);
  const out = new Float32Array(nodes);
  for (let k = 0; k < nodes; k++) {
    const v = q[k];
    out[k] = v === NAN_CODE ? NaN : min + v * scale;
  }
  return out;
}

/** 변위 레코드 복원(성분별 min·scale, 정점마다 dx,dy,dz) */
export function decodeDispU16(buf: ArrayBuffer, nodes: number, min: readonly number[], scale: readonly number[], offset = 0): Float32Array {
  const q = u16(buf, offset, nodes * 3);
  const out = new Float32Array(nodes * 3);
  for (let k = 0; k < nodes; k++)
    for (let c = 0; c < 3; c++) out[k * 3 + c] = min[c] + q[k * 3 + c] * scale[c];
  return out;
}

/** 프레임 i의 스칼라를 manifest에 맞춰 복원(schema 1 = float32 레코드의 앞부분, schema 2 = uint16q) */
export function decodeScalarFor(m: ContourManifest, i: number, buf: ArrayBuffer, offset = 0): Float32Array {
  const n = m.mesh.nodes;
  if (!isQuantized(m)) return decodeFrame(buf, n, m.frames.has_disp, offset).scalar;
  const f = m.frames.list[i];
  return decodeScalarU16(buf, n, f?.min ?? 0, f?.scale ?? 0, offset);
}

/** 프레임 i의 변위를 복원(schema 2만 — schema 1은 decodeFrame이 레코드에서 함께 푼다) */
export function decodeDispFor(m: ContourManifest, i: number, buf: ArrayBuffer, offset = 0): Float32Array {
  const d = m.disp?.list[i];
  if (!d) throw new Error("변위 정보가 없습니다");
  return decodeDispU16(buf, m.mesh.nodes, d.min, d.scale, offset);
}

/** 값 표시용 정확값(유효 6자리) */
export const fmtExact = (v: number) => (Number.isFinite(v) ? String(Number(v.toPrecision(6))) : "–");

/**
 * 툴팁 값(§5.5): 소수 자리 = max(0, −floor(log10(s_i))), 유효숫자 최대 6자리 — 양자화 간격보다 정밀하게 보이지 않는다.
 * s = 0(상수 프레임)이면 값을 그대로, scale이 없으면(schema 1) 유효 6자리.
 */
export function fmtQuantized(v: number, scale: number | null | undefined): string {
  if (!Number.isFinite(v)) return "–";
  if (!scale || !(scale > 0)) return fmtExact(v);
  const byStep = Math.max(0, -Math.floor(Math.log10(scale)));
  const intDigits = v === 0 ? 1 : Math.floor(Math.log10(Math.abs(v))) + 1; // 0.0123 → −1(유효숫자가 소수 셋째 자리부터)
  const dec = Math.min(byStep, Math.max(0, 6 - intDigits), 20);
  return v.toFixed(dec);
}

/** 노드 클릭 툴팁: `노드 {_NODE_ID} · {v̂} {unit}` */
export function tooltipText(nodeId: number | null, v: number, scale: number | null | undefined, unit?: string | null): string {
  const node = nodeId == null ? "" : `노드 ${nodeId} · `;
  if (!Number.isFinite(v)) return `${node}값 없음`;
  return `${node}${fmtQuantized(v, scale)}${unit ? ` ${unit}` : ""}`;
}

export interface Extreme {
  kind: "max" | "min";
  /** GLB 정점 번호 */
  vertex: number;
  /** manifest의 정확값 */
  value: number;
}

/** 현재 프레임의 극값 노드(최대·최소). schema 1(정점 번호 없음)은 빈 목록 */
export function frameExtremes(m: ContourManifest, i: number): Extreme[] {
  const f = m.frames.list[i];
  if (!f) return [];
  const out: Extreme[] = [];
  if (f.max_v != null && f.max != null) out.push({ kind: "max", vertex: f.max_v, value: f.max });
  if (f.min_v != null && f.min != null) out.push({ kind: "min", vertex: f.min_v, value: f.min });
  return out;
}

/** 극값 라벨: `최대 {값} {단위} · 노드 {id}`(노드 번호를 아직 모르면 생략) */
export function extremeLabel(e: Extreme, nodeId: number | null, unit?: string | null): string {
  return `${e.kind === "max" ? "최대" : "최소"} ${fmtExact(e.value)}${unit ? ` ${unit}` : ""}${nodeId == null ? "" : ` · 노드 ${nodeId}`}`;
}

// ---------------------------------------------------------------- 경고 한 줄(§12, manifest warnings)

const WARNING_TEXT: [string, string][] = [
  ["DISP_UNAVAILABLE", "변형 표시 없음 — 결과에 변위가 없습니다"],
  ["DISP_DROPPED", "변형 표시 없음 — 크기 또는 노드 수 상한으로 변위를 뺐습니다"],
  ["COMPS_IGNORED", "표시 부품 이름을 적용하지 못해 전체를 표시합니다"],
];

/** manifest 경고 → 뷰어 아래 한 줄씩(알려진 코드는 고정 문구, 나머지는 manifest 문구 → 없으면 생략) */
export function warningLines(m: ContourManifest | null): { code: string; text: string }[] {
  const out: { code: string; text: string }[] = [];
  for (const w of m?.warnings ?? []) {
    const code = typeof w === "string" ? w : (w.code ?? "");
    const known = WARNING_TEXT.find(([k]) => code.includes(k));
    const text = known ? known[1] : typeof w === "string" ? "" : (w.message ?? "");
    if (text) out.push({ code, text });
  }
  return out;
}

// ---------------------------------------------------------------- LOD ↔ 전체 해상도(§7.3) · 바이트 예산 캐시

export const LOD_SETTLE_MS = 250;
export type LodLevel = "lod" | "full";

/**
 * 표시 단계 상태기. LOD 메시가 없으면 늘 full. 있으면 첫 표시는 LOD이고, 전체를 받았고 조작·재생이 없으며 마지막 조작 뒤 250 ms가 지났을 때만 full.
 * start/end = OrbitControls 시작·끝(휠 포함), pulse = 다른 쪽이 시점을 연결해 움직일 때(끝을 알 수 없음).
 */
export class LodGate {
  private fullReady = false;
  private interacting = false;
  private playing = false;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private last: LodLevel;
  constructor(
    private hasLod: boolean,
    private onChange: (l: LodLevel) => void,
    private settleMs = LOD_SETTLE_MS,
  ) {
    this.last = this.level;
  }
  get level(): LodLevel {
    if (!this.hasLod) return "full";
    return this.fullReady && !this.interacting && !this.playing && this.timer == null ? "full" : "lod";
  }
  private emit() {
    const l = this.level;
    if (l !== this.last) {
      this.last = l;
      this.onChange(l);
    }
  }
  private settle() {
    if (this.timer != null) clearTimeout(this.timer);
    this.timer = setTimeout(() => {
      this.timer = null;
      this.emit();
    }, this.settleMs);
  }
  start() {
    this.interacting = true;
    if (this.timer != null) clearTimeout(this.timer);
    this.timer = null;
    this.emit();
  }
  end() {
    this.interacting = false;
    this.settle();
    this.emit();
  }
  pulse() {
    this.settle();
    this.emit();
  }
  setPlaying(on: boolean) {
    if (this.playing === on) return;
    this.playing = on;
    if (!on) this.settle();
    this.emit();
  }
  setFullReady(on: boolean) {
    this.fullReady = on;
    this.emit();
  }
  dispose() {
    if (this.timer != null) clearTimeout(this.timer);
    this.timer = null;
  }
}

/** 바이트 예산 LRU: 합계가 예산을 넘으면 오래된 것부터 지우되 최소 minItems개는 남긴다 */
export class ByteBudgetCache<T extends { byteLength: number }> {
  private map = new Map<number, T>();
  private total = 0;
  constructor(
    readonly budget: number,
    readonly minItems = 2,
  ) {}
  get(i: number): T | undefined {
    const v = this.map.get(i);
    if (v !== undefined) {
      this.map.delete(i);
      this.map.set(i, v);
    }
    return v;
  }
  set(i: number, v: T) {
    const old = this.map.get(i);
    if (old) this.total -= old.byteLength;
    this.map.delete(i);
    this.map.set(i, v);
    this.total += v.byteLength;
    while (this.total > this.budget && this.map.size > this.minItems) {
      const k = this.map.keys().next().value as number;
      this.total -= this.map.get(k)!.byteLength;
      this.map.delete(k);
    }
  }
  has(i: number) {
    return this.map.has(i);
  }
  keys(): number[] {
    return [...this.map.keys()];
  }
  get bytes() {
    return this.total;
  }
  clear() {
    this.map.clear();
    this.total = 0;
  }
}

export type LegendMode = "global" | "frame";

/** 범례 범위: 고정 = range, 프레임별 = list[i] (없거나 null이면 고정으로) */
export function legendRange(m: ContourManifest, i: number, mode: LegendMode): [number, number] | null {
  const g = m.range;
  const f = m.frames.list[i];
  if (mode === "frame" && f && f.min != null && f.max != null) return [f.min, f.max];
  if (g.min != null && g.max != null) return [g.min, g.max];
  return null;
}

/** NaN 제외 최소·최대(전부 NaN이면 null) */
export function scalarMinMax(values: ArrayLike<number>): [number, number] | null {
  let lo = Infinity;
  let hi = -Infinity;
  for (let k = 0; k < values.length; k++) {
    const v = values[k];
    if (Number.isNaN(v)) continue;
    if (v < lo) lo = v;
    if (v > hi) hi = v;
  }
  return lo <= hi ? [lo, hi] : null;
}

/** 변형 위치 = POSITION + scale × disp (disp 없거나 scale 0이면 원래 위치 복사) */
export function applyDeform(base: Float32Array, disp: Float32Array | null, scale: number, out: Float32Array): Float32Array {
  if (!disp || scale === 0) {
    out.set(base);
    return out;
  }
  for (let k = 0; k < base.length; k++) {
    const d = disp[k];
    out[k] = base[k] + scale * (Number.isFinite(d) ? d : 0);
  }
  return out;
}

/** LOD 정점 값 모으기: out[j] = values[src[j]] (보간·평균 없음, C3F-8) */
export function gatherValues(values: ArrayLike<number>, src: Uint32Array, out: Float32Array): Float32Array {
  for (let j = 0; j < src.length; j++) out[j] = values[src[j]];
  return out;
}

/** LOD 변형 위치: out[j] = base[j] + scale × disp[src[j]] (disp 없거나 scale 0이면 원래 위치) */
export function applyDeformGather(base: Float32Array, disp: Float32Array | null, scale: number, src: Uint32Array, out: Float32Array): Float32Array {
  if (!disp || scale === 0) {
    out.set(base);
    return out;
  }
  for (let j = 0; j < src.length; j++)
    for (let c = 0; c < 3; c++) {
      const d = disp[src[j] * 3 + c];
      out[j * 3 + c] = base[j * 3 + c] + scale * (Number.isFinite(d) ? d : 0);
    }
  return out;
}

export const DEFORM_SCALES = [0, 1, 5, 10, 50] as const;
export const FPS_CHOICES = [1, 2, 5, 10, 15, 30] as const;

/** 재생 다음 프레임(반복) */
export const nextFrame = (i: number, count: number) => (count <= 0 ? 0 : (i + 1) % count);
export const prevFrame = (i: number, count: number) => (count <= 0 ? 0 : (i - 1 + count) % count);

/** 최근 N프레임만 메모리 유지(§13.6 기본 8) */
export class FrameCache<T> {
  private map = new Map<number, T>();
  constructor(readonly limit = 8) {}
  get(i: number): T | undefined {
    const v = this.map.get(i);
    if (v !== undefined) {
      this.map.delete(i);
      this.map.set(i, v);
    }
    return v;
  }
  set(i: number, v: T) {
    this.map.delete(i);
    this.map.set(i, v);
    while (this.map.size > this.limit) this.map.delete(this.map.keys().next().value as number);
  }
  has(i: number) {
    return this.map.has(i);
  }
  keys(): number[] {
    return [...this.map.keys()];
  }
  clear() {
    this.map.clear();
  }
}

// ---------------------------------------------------------------- 대기 안내(§13.6 열 때 생성)

/** 단계 스테퍼(대기 → H3D 읽기 → 형상 → 프레임 변환 → 완료) */
export const STEPPER: { phase: Contour3dPhase; label: string }[] = [
  { phase: "waiting", label: "대기" },
  { phase: "reading_h3d", label: "H3D 읽기" },
  { phase: "geometry", label: "형상" },
  { phase: "frames", label: "프레임 변환" },
  { phase: "done", label: "완료" },
];

export type StepMark = "done" | "active" | "todo" | "failed";

/** 진행 phase → 단계별 표시. failed·canceled는 마지막으로 진행한 단계(step_key 기준 추정)를 실패로 */
export function stepMarks(phase: Contour3dPhase, failedAt?: Contour3dPhase | null): StepMark[] {
  const order = STEPPER.map((s) => s.phase);
  if (phase === "failed" || phase === "canceled" || phase === "expired") {
    const at = Math.max(0, order.indexOf(failedAt ?? "waiting"));
    return order.map((_, k) => (k < at ? "done" : k === at ? "failed" : "todo"));
  }
  const cur = order.indexOf(phase);
  if (cur < 0) return order.map(() => "todo");
  return order.map((_, k) => (k < cur || phase === "done" ? "done" : k === cur ? "active" : "todo"));
}

/** 화면 상태: 생성 요청 전·대기(생성 중)·표시·결과 실패(결정적)·작업 실패·취소·만료 */
export type ContourView = "idle" | "waiting" | "ready" | "result_fail" | "failed" | "canceled" | "expired";

export function contourView(c: Contour3d | null): ContourView {
  if (!c) return "idle";
  switch (c.status) {
    case "QUEUED":
    case "RUNNING":
      return "waiting";
    case "DONE":
      return c.result_status === "FAIL" ? "result_fail" : "ready";
    case "FAILED":
      return "failed";
    case "CANCELED":
      return "canceled";
    case "EXPIRED":
      return "expired";
    default:
      return "failed";
  }
}

/** 진행률(0~100) — progress.percent가 없으면 단계 위치로 추정 */
export function progressPercent(c: Contour3d | null): number | null {
  const p = c?.progress;
  if (!p) return null;
  if (p.percent != null && Number.isFinite(p.percent)) return Math.max(0, Math.min(100, p.percent));
  const k = STEPPER.findIndex((s) => s.phase === p.phase);
  return k < 0 ? null : Math.round((k / (STEPPER.length - 1)) * 100);
}

/** 초 → "1분 05초" / "42초" */
export function fmtSeconds(s: number | null | undefined): string {
  if (s == null || !Number.isFinite(s)) return "–";
  const t = Math.max(0, Math.round(s));
  if (t < 60) return `${t}초`;
  const m = Math.floor(t / 60);
  const r = t % 60;
  return m >= 60 ? `${Math.floor(m / 60)}시간 ${m % 60}분` : `${m}분 ${String(r).padStart(2, "0")}초`;
}

/** 예상 시간 문구: estimate_s 없으면 "수 분"(§13.6), 남은 시간 = 예상 − 경과 */
export function etaText(c: Contour3d | null): string {
  const p = c?.progress;
  if (!p || p.estimate_s == null) return "예상 시간 수 분";
  const left = p.estimate_s - (p.elapsed_s ?? 0);
  return left > 0 ? `예상 ${fmtSeconds(p.estimate_s)} · 남은 약 ${fmtSeconds(left)}` : `예상 ${fmtSeconds(p.estimate_s)} · 곧 끝납니다`;
}

/** 프레임 시간 표시 */
export function fmtTime(t: number | null | undefined): string {
  if (t == null || !Number.isFinite(t)) return "–";
  return t === 0 ? "0" : Math.abs(t) < 1e-3 ? t.toExponential(2) : String(Number(t.toPrecision(4)));
}

// ---------------------------------------------------------------- 비교 모드(contour3d-default §3.3, C3D-7·8)

export type Vec3 = [number, number, number];
/** 시점(OrbitControls) 상태 — 비교 모드 시점 연결용 */
export interface CameraState {
  position: Vec3;
  target: Vec3;
  up: Vec3;
  zoom: number;
}
export interface BoxState {
  min: Vec3;
  max: Vec3;
}

/** 두 상자의 합집합(둘 중 없으면 있는 쪽) */
export function unionBox(a: BoxState | null, b: BoxState | null): BoxState | null {
  if (!a || !b) return a ?? b;
  return { min: a.min.map((v, k) => Math.min(v, b.min[k])) as Vec3, max: a.max.map((v, k) => Math.max(v, b.max[k])) as Vec3 };
}

export const LEGEND_SEPARATE_NOTE = "결과 종류가 달라 범례를 따로 씁니다";

export interface CommonLegend {
  /** 두 manifest가 모두 있고 display(field·comp·avgmode)·unit이 같아 공통 범례를 쓸 수 있는가 */
  shareable: boolean;
  /** 공통 범례 범위 = 두 range의 합집합(shareable일 때만, 아니면 null) */
  range: [number, number] | null;
  /** 개별 범례를 쓰는 이유(두 manifest가 모두 있는데 종류가 다를 때만) */
  note: string | null;
}

const sameText = (a: string | null | undefined, b: string | null | undefined) => (a ?? "") === (b ?? "");

/** C3D-8: 공통 범례 = 두 manifest `range`의 합집합. display·unit이 다르면 개별 + 문구. D3-61 final.legend(PNG용)는 쓰지 않는다 */
export function commonLegend(a: ContourManifest | null, b: ContourManifest | null): CommonLegend {
  if (!a || !b) return { shareable: false, range: null, note: null };
  const same = sameText(a.display?.field, b.display?.field) && sameText(a.display?.comp, b.display?.comp) && sameText(a.display?.avgmode, b.display?.avgmode) && sameText(a.unit, b.unit);
  if (!same) return { shareable: false, range: null, note: LEGEND_SEPARATE_NOTE };
  const los = [a.range.min, b.range.min].filter((v): v is number => v != null && Number.isFinite(v));
  const his = [a.range.max, b.range.max].filter((v): v is number => v != null && Number.isFinite(v));
  if (!los.length || !his.length) return { shareable: false, range: null, note: null };
  return { shareable: true, range: [Math.min(...los), Math.max(...his)], note: null };
}

/** 두 프레임 시간표가 같은가: 개수가 같고 각 time 차 ≤ 1e-9·max(|t|) (time null이 있으면 같다고 보지 않음) */
export function sameTimes(a: ContourManifest, b: ContourManifest): boolean {
  if (a.frames.count !== b.frames.count) return false;
  const ts = [...a.frames.list, ...b.frames.list].map((f) => f.time);
  if (ts.some((t) => t == null || !Number.isFinite(t))) return false;
  const tol = 1e-9 * Math.max(0, ...(ts as number[]).map((t) => Math.abs(t)));
  return a.frames.list.every((f, k) => Math.abs((f.time as number) - (b.frames.list[k].time as number)) <= tol);
}

/** 공용 슬라이더(왼쪽 프레임 i)에 대응하는 오른쪽 프레임: 같은 시간표면 같은 인덱스, 아니면 왼쪽 프레임 시간에 가장 가까운 오른쪽 프레임 */
export function pairFrame(left: ContourManifest, right: ContourManifest, i: number): number {
  const n = right.frames.count;
  if (n <= 0) return 0;
  const at = Math.max(0, Math.min(i, left.frames.count - 1));
  if (sameTimes(left, right)) return Math.min(at, n - 1);
  const t = left.frames.list[at]?.time;
  if (t == null || !Number.isFinite(t)) return Math.min(at, n - 1);
  let best = 0;
  let bd = Infinity;
  right.frames.list.forEach((f, k) => {
    if (f.time == null || !Number.isFinite(f.time)) return;
    const d = Math.abs(f.time - t);
    if (d < bd) {
      bd = d;
      best = k;
    }
  });
  return best;
}

// ---------------------------------------------------------------- 칸 상태(contour3d-default C3D-2·5·6)

export const DENIED_TEXT = "3D 미생성 — 처음 생성은 power 권한이 필요합니다";
export const BUSY_TEXT = "앞선 3D 생성이 끝나면 이어서 요청합니다";

/** 3D 대신 PNG·영상을 그 자리에 보여야 하는 상태: 결과 없음·작업 실패·요청 실패·읽기 사용자 미적중(C3D-2·6) */
export function showsMedia(s: { c: Contour3d | null; error: string | null; denied: boolean }): boolean {
  const view = contourView(s.c);
  if (s.denied) return true;
  if (s.error && (!s.c || view !== "waiting")) return true;
  return view === "result_fail" || view === "failed";
}

// ---------------------------------------------------------------- 대체 사유 한 줄(contour3d-field §12)

export const WEBGL_TEXT = "3D 불가 — 이 브라우저에서 WebGL2를 쓸 수 없습니다";
export const NO_SOURCE_TEXT = "3D 없음 — 결과 h3d가 없습니다";
export const MEMBER_TEXT = DENIED_TEXT;

/** 천 단위 구분 숫자(로캘 무관) */
export const fmtInt = (n: number) => Math.round(n).toLocaleString("en-US");
const fmtMB = (bytes: number) => (bytes / MiB).toFixed(1);

/** 기능 꺼짐(`missing` 첫 키): contour3d.enabled · 추출 TCL · 그 밖(템플릿 placeholder) */
export function featureOffText(missing: readonly string[] | null | undefined): string {
  const key = missing?.[0] ?? "contour3d.enabled";
  if (key === "contour3d.enabled") return "3D 꺼짐 — 관리자 설정 contour3d.enabled";
  if (key === "resources.contour_extract_tcl") return "3D 꺼짐 — 추출 TCL 없음(resources.contour_extract_tcl)";
  return `3D 꺼짐 — HyperView 경로 미설정(${key})`;
}

/** 작업 FAILED: "3D 생성 실패 — {message_ko} ({code})" */
export function jobFailText(c: Pick<Contour3d, "message_ko" | "code">): string {
  const msg = c.message_ko ?? "";
  const code = c.code ? ` (${c.code})` : "";
  return `3D 생성 실패 — ${msg || "작업 실패"}${code}`;
}

/** 결과 FAIL(결정적): 상한 비교는 FAIL manifest의 `limits`로 판별, 읽지 못하면 message_ko만 */
export function resultFailText(c: Pick<Contour3d, "message_ko" | "code" | "nodes" | "display"> & { reason?: Contour3d["reason"] }, m: ContourManifest | null): string {
  const code = c.code ?? m?.code ?? "";
  const lim = m?.limits ?? null;
  const fallback = `3D 생략 — ${c.message_ko ?? m?.message ?? code ?? "결과 없음"}`;
  if (code.includes("TOO_LARGE")) {
    const n = lim?.nodes ?? c.nodes ?? null;
    if (n != null && lim?.max_nodes != null && n > lim.max_nodes) {
      // API reason.comps_applicable(= 쿠션 입력이 아님)이 있으면 그것, 없으면 manifest scope(부품 이름이 있었는가)로 판단
      const applicable = c.reason?.comps_applicable ?? (m?.scope?.comps_applicable ?? (m?.scope?.comps?.length ?? 0) > 0);
      const comps = applicable ? "부품 이름으로 범위를 줄이거나 " : "";
      return `3D 생략 — 외부 면 노드 ${fmtInt(n)}개 > 상한 ${fmtInt(lim.max_nodes)}. ${comps}관리자에게 상한(contour3d.max_nodes) 조정을 요청하세요`;
    }
    if (lim?.glb_bytes != null && lim.max_glb_bytes != null && lim.glb_bytes > lim.max_glb_bytes)
      return `3D 생략 — 형상 ${fmtMB(lim.glb_bytes)} MB > 상한 ${fmtMB(lim.max_glb_bytes)} MB(contour3d.max_glb_bytes), 관리자에게 조정을 요청하세요`;
    if (lim) return "3D 생략 — 프레임 2개도 크기 상한(contour3d.max_bin_bytes)을 넘습니다";
    return fallback;
  }
  if (code.includes("FIELD_EMPTY")) {
    const field = (c.display?.field as string | undefined) ?? m?.display?.field ?? "";
    return `3D 생략 — 선택한 결과 값이 없습니다(${field})`;
  }
  return fallback;
}

export interface ReasonState {
  c: Contour3d | null;
  error: string | null;
  denied: boolean;
  errInfo?: { status: number; code: string; missing: string[] } | null;
}

/**
 * 3D 대신 PNG·빈 칸이 나오는 요청 단계의 사유(결과 FAIL은 manifest가 필요해 resultFailText로 따로).
 * 409 CONTOUR3D_NOT_CONFIGURED = 기능 꺼짐과 같은 문구, 409 PREREQUISITE_MISSING = 원본 없음, 403 = member 미생성.
 */
export function requestReason(s: ReasonState): string | null {
  if (s.denied) return MEMBER_TEXT;
  const e = s.errInfo;
  if (s.error && e?.status === 409 && e.code === "CONTOUR3D_NOT_CONFIGURED") return featureOffText(e.missing);
  if (s.error && e?.status === 409 && e.code === "PREREQUISITE_MISSING") return NO_SOURCE_TEXT;
  if (s.c && contourView(s.c) === "failed") return jobFailText(s.c);
  if (s.error) return `3D 컨투어를 요청하지 못했습니다 — ${s.error}`;
  return null;
}
