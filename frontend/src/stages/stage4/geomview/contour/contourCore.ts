// 결과 3D 컨투어 순수 로직(geometry-view.md §13.4·§13.6) — three 없이 시험한다.
// contour_frames.bin = 프레임 우선 레코드(scalar float32[N] + 선택 disp float32[N][3], 리틀엔디언), offset(i) = i × record_bytes.
import type { Contour3d, Contour3dPhase } from "../../../../api";

export interface ContourFrameInfo {
  i: number;
  src: number;
  time: number | null;
  min: number | null;
  max: number | null;
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
  mesh: { file?: string; nodes: number; triangles?: number; bytes?: number };
  frames: { file?: string; count: number; record_bytes: number; has_disp: boolean; dtype?: string; nan_count?: number; bytes?: number; list: ContourFrameInfo[] };
  range: { min: number | null; max: number | null };
  sampling?: { total_frames?: number; max_frames?: number; rule?: string } | null;
  warnings?: { code?: string; count?: number; message?: string }[] | string[];
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
