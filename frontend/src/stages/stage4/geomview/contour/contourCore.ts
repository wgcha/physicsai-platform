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

export const DENIED_TEXT = "3D는 실행 권한이 있는 사용자가 한 번 열면 볼 수 있습니다";
export const BUSY_TEXT = "앞선 3D 생성이 끝나면 이어서 요청합니다";

/** 3D 대신 PNG·영상을 그 자리에 보여야 하는 상태: 결과 없음·작업 실패·요청 실패·읽기 사용자 미적중(C3D-2·6) */
export function showsMedia(s: { c: Contour3d | null; error: string | null; denied: boolean }): boolean {
  const view = contourView(s.c);
  if (s.denied) return true;
  if (s.error && (!s.c || view !== "waiting")) return true;
  return view === "result_fail" || view === "failed";
}
