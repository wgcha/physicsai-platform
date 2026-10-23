// 목 가상 형상·컨투어(geometry-view.md §4·§13.4 모양): 쿠션 바디 2개(슬래브 + 리브 + 구멍)의 GLB·manifest와
// 가상 판(비드) 컨투어 GLB·프레임(bin)·manifest. 파일을 저장소에 두지 않고 요청 때 만든다(≤ 100 KB GLB).
import { writeGlb, type GlbNode } from "./glb";
import type { ManifestFeature, PreviewManifest, Vec3, ViewManifest } from "../stages/stage4/geomview/viewerCore";
import type { ContourManifest } from "../stages/stage4/geomview/contour/contourCore";

export interface CushionParams {
  thk: number;
  ribT: number;
  ribH: number;
  holeU: number;
}
export const NOMINAL: CushionParams = { thk: 12.5, ribT: 3, ribH: 8, holeU: 30 };
const L = 120;
const W = 80;
const CY = 40;
const R = 4;
const N = 16;
const RIB_X = 50;

/** 파라미터 이름 → CushionParams 키(목: 포켓 깊이 = 리브 높이) */
export const PARAM_KEY: Record<string, keyof CushionParams> = {
  CUSH_L_THK_1: "thk",
  CUSH_L_POCKET_D_1: "ribH",
  CUSH_L_RIB_T_2: "ribT",
  CUSH_L_HOLE_U_1: "holeU",
};

type Tri = [Vec3, Vec3, Vec3];
const quad = (a: Vec3, b: Vec3, c: Vec3, d: Vec3): Tri[] => [
  [a, b, c],
  [a, c, d],
];
const flip = (ts: Tri[]): Tri[] => ts.map(([a, b, c]) => [a, c, b]);

class Builder {
  pos: number[] = [];
  nrm: number[] = [];
  fid: number[] = [];
  disp: number[] = [];
  faces: { id: string; surface: string; tri: [number, number]; area: number }[] = [];
  lines: number[] = [];
  private tri = 0;
  face(id: number, surface: string, tris: Tri[], normal: (p: Vec3) => Vec3, disp: (p: Vec3) => number) {
    const first = this.tri;
    let area = 0;
    for (const t of tris) {
      for (const p of t) {
        this.pos.push(...p);
        this.nrm.push(...normal(p));
        this.fid.push(id);
        this.disp.push(disp(p));
      }
      const u = [t[1][0] - t[0][0], t[1][1] - t[0][1], t[1][2] - t[0][2]];
      const v = [t[2][0] - t[0][0], t[2][1] - t[0][1], t[2][2] - t[0][2]];
      area += 0.5 * Math.hypot(u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]);
      this.tri++;
    }
    this.faces.push({ id: `F${id}`, surface, tri: [first, tris.length], area: Number(area.toFixed(1)) });
  }
  line(a: Vec3, b: Vec3) {
    this.lines.push(...a, ...b);
  }
  box(x0: number, y0: number, z0: number, x1: number, y1: number, z1: number) {
    const c = (x: number, y: number, z: number): Vec3 => [x, y, z];
    for (const z of [z0, z1]) {
      this.line(c(x0, y0, z), c(x1, y0, z));
      this.line(c(x1, y0, z), c(x1, y1, z));
      this.line(c(x1, y1, z), c(x0, y1, z));
      this.line(c(x0, y1, z), c(x0, y0, z));
    }
    for (const [x, y] of [
      [x0, y0],
      [x1, y0],
      [x1, y1],
      [x0, y1],
    ])
      this.line(c(x, y, z0), c(x, y, z1));
  }
}

/** 구멍 둘레 정사각형(반 변 s) 안을 원 바깥만 삼각분할(+z 방향 반시계) */
function squareMinusCircle(cx: number, cy: number, s: number, z: number): Tri[] {
  const C: Vec3[] = [
    [cx + s, cy + s, z],
    [cx - s, cy + s, z],
    [cx - s, cy - s, z],
    [cx + s, cy - s, z],
  ];
  const P = (j: number): Vec3 => {
    const a = (2 * Math.PI * (((j % N) + N) % N)) / N;
    return [cx + R * Math.cos(a), cy + R * Math.sin(a), z];
  };
  const out: Tri[] = [];
  for (let k = 0; k < 4; k++) {
    const a = C[k];
    const b = C[(k + 1) % 4];
    for (let j = 2 + 4 * k; j < 4 + 4 * k; j++) out.push([a, P(j + 1), P(j)]);
    for (let j = 4 + 4 * k; j < 6 + 4 * k; j++) out.push([b, P(j + 1), P(j)]);
    out.push([a, b, P(4 + 4 * k)]);
  }
  return out;
}

/** 슬래브 윗면·아랫면(구멍 포함) */
function slabCap(ox: number, cx: number, z: number): Tri[] {
  const s = 8;
  const q = (x0: number, y0: number, x1: number, y1: number) => quad([x0, y0, z], [x1, y0, z], [x1, y1, z], [x0, y1, z]);
  return [...q(ox, 0, cx - s, W), ...q(cx + s, 0, ox + L, W), ...q(cx - s, 0, cx + s, CY - s), ...q(cx - s, CY + s, cx + s, W), ...squareMinusCircle(cx, CY, s, z)];
}

function addBody(b: Builder, ox: number, p: CushionParams, nom: CushionParams) {
  const cx = ox + p.holeU;
  const cx0 = ox + nom.holeU;
  const zero = () => 0;
  const n = (v: Vec3) => () => v;
  b.face(1, "PLANE", flip(slabCap(ox, cx, 0)), n([0, 0, -1]), zero);
  b.face(2, "PLANE", slabCap(ox, cx, p.thk), n([0, 0, 1]), () => Math.abs(p.thk - nom.thk));
  b.face(3, "PLANE", quad([ox, W, 0], [ox, 0, 0], [ox, 0, p.thk], [ox, W, p.thk]), n([-1, 0, 0]), zero);
  b.face(4, "PLANE", quad([ox + L, 0, 0], [ox + L, W, 0], [ox + L, W, p.thk], [ox + L, 0, p.thk]), n([1, 0, 0]), zero);
  b.face(5, "PLANE", quad([ox, 0, 0], [ox + L, 0, 0], [ox + L, 0, p.thk], [ox, 0, p.thk]), n([0, -1, 0]), zero);
  b.face(6, "PLANE", quad([ox + L, W, 0], [ox, W, 0], [ox, W, p.thk], [ox + L, W, p.thk]), n([0, 1, 0]), zero);
  const x0 = ox + RIB_X;
  const x1 = x0 + p.ribT;
  const z0 = p.thk;
  const z1 = p.thk + p.ribH;
  const dTop = Math.abs(z1 - (nom.thk + nom.ribH));
  b.face(7, "PLANE", quad([x0, 10, z1], [x1, 10, z1], [x1, 70, z1], [x0, 70, z1]), n([0, 0, 1]), () => dTop);
  b.face(8, "PLANE", quad([x0, 70, z0], [x0, 10, z0], [x0, 10, z1], [x0, 70, z1]), n([-1, 0, 0]), zero);
  b.face(9, "PLANE", quad([x1, 10, z0], [x1, 70, z0], [x1, 70, z1], [x1, 10, z1]), n([1, 0, 0]), () => Math.abs(p.ribT - nom.ribT));
  b.face(10, "PLANE", quad([x0, 10, z0], [x1, 10, z0], [x1, 10, z1], [x0, 10, z1]), n([0, -1, 0]), zero);
  b.face(11, "PLANE", quad([x1, 70, z0], [x0, 70, z0], [x0, 70, z1], [x1, 70, z1]), n([0, 1, 0]), zero);
  const wall: Tri[] = [];
  for (let j = 0; j < N; j++) {
    const a0 = (2 * Math.PI * j) / N;
    const a1 = (2 * Math.PI * (j + 1)) / N;
    const pa = (a: number, z: number): Vec3 => [cx + R * Math.cos(a), CY + R * Math.sin(a), z];
    const [a, bb, c, d] = [pa(a0, 0), pa(a1, 0), pa(a1, p.thk), pa(a0, p.thk)];
    wall.push([a, c, bb], [a, d, c]);
    b.line(pa(a0, 0), pa(a1, 0));
    b.line(pa(a0, p.thk), pa(a1, p.thk));
  }
  b.face(12, "CYLINDER", wall, (q) => {
    const dx = q[0] - cx;
    const dy = q[1] - CY;
    const r = Math.hypot(dx, dy) || 1;
    return [-dx / r, -dy / r, 0];
  }, (q) => Math.abs(Math.hypot(q[0] - cx0, q[1] - CY) - R));
  b.box(ox, 0, 0, ox + L, W, p.thk);
  b.box(x0, 10, z0, x1, 70, z1);
}

const BODIES = [
  { body: "CUSH_L", ox: 0 },
  { body: "CUSH_R", ox: 150 },
];

/** 쿠션 GLB(바디 2개 × 면 메시 + 엣지 선). preview = _DISP_MM 포함 */
export function cushionGlb(p: CushionParams, preview: boolean): { glb: Uint8Array; bodies: ViewManifest["bodies"]; maxDisp: number } {
  const nodes: GlbNode[] = [];
  const bodies: ViewManifest["bodies"] = [];
  let maxDisp = 0;
  for (const { body, ox } of BODIES) {
    const b = new Builder();
    addBody(b, ox, p, NOMINAL);
    const attributes: GlbNode["attributes"] = {
      POSITION: { data: new Float32Array(b.pos), size: 3 },
      NORMAL: { data: new Float32Array(b.nrm), size: 3 },
      _FACE_ID: { data: new Uint16Array(b.fid), size: 1 },
    };
    if (preview) attributes._DISP_MM = { data: new Float32Array(b.disp), size: 1 };
    maxDisp = Math.max(maxDisp, ...b.disp);
    const count = b.pos.length / 3;
    nodes.push({ name: body, mode: 4, attributes, indices: Uint32Array.from({ length: count }, (_, i) => i) });
    nodes.push({ name: `${body}.edges`, mode: 1, attributes: { POSITION: { data: new Float32Array(b.lines), size: 3 } } });
    bodies.push({ body, node: body, edges_node: `${body}.edges`, faces: b.faces });
  }
  return { glb: writeGlb("paicad_view", nodes), bodies, maxDisp: Number(maxDisp.toFixed(4)) };
}

/** 조립 매칭 검사 GLB(asm-match.md §4.3 10: 노드 = 행 바디 이름, `_DIST_MM`) — 목은 쿠션 바디 표면에 거리 값을 칠한다. hot = 바디별 거리 최대 위치·크기 */
export function asmMatchGlb(rows: { body: string; max: number; hot: Vec3 }[]): { glb: Uint8Array; worst: Record<string, { xyz: Vec3; dist_mm: number }[]> } {
  const nodes: GlbNode[] = [];
  const worst: Record<string, { xyz: Vec3; dist_mm: number }[]> = {};
  for (const { body, ox } of BODIES) {
    const row = rows.find((r) => r.body === body);
    if (!row) continue;
    const b = new Builder();
    addBody(b, ox, NOMINAL, NOMINAL);
    const count = b.pos.length / 3;
    const dist = new Float32Array(count);
    const sigma = Math.max(8, row.max * 3);
    for (let i = 0; i < count; i++) {
      const d2 = (b.pos[i * 3] - row.hot[0]) ** 2 + (b.pos[i * 3 + 1] - row.hot[1]) ** 2 + (b.pos[i * 3 + 2] - row.hot[2]) ** 2;
      dist[i] = Number((row.max * (0.08 + 0.92 * Math.exp(-d2 / (2 * sigma * sigma)))).toFixed(4));
    }
    nodes.push({
      name: body, mode: 4,
      attributes: { POSITION: { data: new Float32Array(b.pos), size: 3 }, NORMAL: { data: new Float32Array(b.nrm), size: 3 }, _DIST_MM: { data: dist, size: 1 } },
      indices: Uint32Array.from({ length: count }, (_, i) => i),
    });
    nodes.push({ name: `${body}.edges`, mode: 1, attributes: { POSITION: { data: new Float32Array(b.lines), size: 3 } } });
    const order = Array.from({ length: count }, (_, i) => i).sort((x, y) => dist[y] - dist[x]);
    const pts: { xyz: Vec3; dist_mm: number }[] = [];
    for (const i of order) {
      const xyz: Vec3 = [b.pos[i * 3], b.pos[i * 3 + 1], b.pos[i * 3 + 2]];
      if (pts.every((q) => Math.hypot(q.xyz[0] - xyz[0], q.xyz[1] - xyz[1], q.xyz[2] - xyz[2]) > 6)) pts.push({ xyz, dist_mm: dist[i] });
      if (pts.length >= 3) break;
    }
    worst[body] = pts;
  }
  return { glb: writeGlb("paicad_asm_match", nodes), worst };
}

function feature(name: string, parameter: string, type: string, body: string, value: number, nominal: number, range: [number, number], feasible: [number, number] | null, source: string, moving: string[], fixed: string[], dim: ManifestFeature["dimension"]): ManifestFeature {
  return {
    name, parameter, type, body, nominal, value, unit: "mm",
    range: { min: range[0], max: range[1] },
    feasible: feasible ? { min: feasible[0], max: feasible[1], source } : null,
    faces: { moving, fixed, other: [] },
    dimension: dim,
  };
}

/** manifest features(seedFeatures와 같은 이름·범위) — 값은 p */
export function cushionFeatures(p: CushionParams): ManifestFeature[] {
  const thk = (body: string, ox: number, name: string) =>
    feature(name, "CUSH_L_THK_1", "THICKNESS", body, p.thk, NOMINAL.thk, [11.875, 13.125], [6.2, 18], "envelope", ["F2"], ["F1"], {
      kind: "linear", p0: [ox + L, 20, 0], p1: [ox + L, 20, p.thk], label: [ox + L + 10, 20, p.thk / 2], value: p.thk, unit: "mm", geom_len: p.thk,
    });
  const rx = RIB_X + p.ribT / 2;
  return [
    thk("CUSH_L", 0, "CUSH_L_THK_1"),
    thk("CUSH_R", 150, "CUSH_R_THK_1"),
    feature("CUSH_L_POCKET_D_1", "CUSH_L_POCKET_D_1", "POCKET_DEPTH", "CUSH_L", p.ribH, NOMINAL.ribH, [7.6, 8.4], [4, 11], "estimate", ["F7"], ["F2"], {
      kind: "linear", p0: [rx, 70, p.thk], p1: [rx, 70, p.thk + p.ribH], label: [rx, W + 10, p.thk + p.ribH / 2], value: p.ribH, unit: "mm", geom_len: p.ribH,
    }),
    feature("CUSH_L_RIB_T_2", "CUSH_L_RIB_T_2", "RIB_THICKNESS", "CUSH_L", p.ribT, NOMINAL.ribT, [2.85, 3.15], [2.9, 4], "estimate", ["F9"], ["F8"], {
      kind: "linear", p0: [RIB_X, 40, p.thk + p.ribH], p1: [RIB_X + p.ribT, 40, p.thk + p.ribH], label: [rx, 40, p.thk + p.ribH + 10], value: p.ribT, unit: "mm", geom_len: p.ribT,
    }),
    feature("CUSH_L_HOLE_U_1", "CUSH_L_HOLE_U_1", "HOLE_POS_U", "CUSH_L", p.holeU, NOMINAL.holeU, [25, 35], [27, 40], "envelope", ["F12"], ["F3"], {
      kind: "position", p0: [0, CY, p.thk], p1: [p.holeU, CY, p.thk], label: [p.holeU / 2, CY, p.thk + 12], value: p.holeU, unit: "mm", geom_len: p.holeU,
    }),
    feature("CUSH_L_FILLET_R_1", "CUSH_L_FILLET_R_1", "FILLET_RADIUS", "CUSH_L", 2, 2, [1.9, 2.1], null, "estimate", ["F10"], [], null),
  ];
}

export function viewManifest(bodies: ViewManifest["bodies"], glbBytes: number): ViewManifest {
  return {
    schema_version: 1, kind: "solid", mode: "nominal", status: "OK", code: null, category: null, message: null, unit: "mm", up_axis: "Z",
    bbox: [0, 0, 0, 270, W, NOMINAL.thk + NOMINAL.ribH],
    bodies, features: cushionFeatures(NOMINAL), fixed_clusters: [], warnings: [],
    ...({ engine: "native", engine_version: "0.10.0", glb: { file: "view.glb", bytes: glbBytes }, tess: { linear_mm: 0.1, angular_deg: 20 } } as object),
  } as ViewManifest;
}

/** 미리보기 값 → 판정(목): feasible 밖 값이면 충돌 FAIL(update FAIL — GLB 없음) */
export function previewOutcome(values: Record<string, number>): { ok: true; params: CushionParams } | { ok: false; code: string; category: string; feature: string } {
  const p = { ...NOMINAL };
  const feats = cushionFeatures(NOMINAL);
  for (const [k, v] of Object.entries(values)) {
    const f = feats.find((x) => x.name === k);
    if (f?.feasible && ((f.feasible.min != null && v < f.feasible.min) || (f.feasible.max != null && v > f.feasible.max))) return { ok: false, code: "GEOM_FEATURE_COLLISION", category: "CAD_FAILED", feature: k };
    const key = PARAM_KEY[k];
    if (key) p[key] = v;
  }
  return { ok: true, params: p };
}

export function previewManifest(values: Record<string, number>, out: ReturnType<typeof previewOutcome>, glb: { bodies: ViewManifest["bodies"]; maxDisp: number } | null): PreviewManifest {
  const base = {
    schema_version: 1, kind: "solid" as const, mode: "preview" as const, unit: "mm", up_axis: "Z", values,
    fe: { mode: "off" }, timing: { update_s: 1.2, tess_s: 0.3, total_s: 2.1 },
  };
  if (!out.ok) {
    return {
      ...base, status: "FAIL", code: out.code, category: out.category, message: "feature collision", bodies: [],
      features: cushionFeatures(NOMINAL).map((f) => ({ ...f, dimension: null })), disp: null,
      failure: { features: [out.feature, "CUSH_L_RIB_T_2"], clusters: [], points: [] },
    };
  }
  return { ...base, status: "OK", code: null, category: null, message: null, bodies: glb!.bodies, features: cushionFeatures(out.params), disp: { attribute: "_DISP_MM", max_mm: glb!.maxDisp }, failure: null };
}

// ---------------------------------------------------------------- 결과 컨투어(가상 판 + 비드)

const NX = 48;
const NY = 28;
const PL = 560;
const PW = 320;

function plateZ(x: number, y: number) {
  const bead = Math.exp(-(((y - PW / 2) / 22) ** 2)) * (x > 60 && x < PL - 60 ? 1 : Math.max(0, 1 - Math.abs(x < 60 ? 60 - x : x - (PL - 60)) / 30));
  return 18 * Math.sin((Math.PI * x) / PL) * 0.4 + 7 * bead;
}

export interface ContourData {
  glb: Uint8Array;
  frames: Uint8Array;
  manifest: ContourManifest;
  /** schema 2: 변위 파일(없으면 null) · LOD GLB(없으면 null) */
  disp: Uint8Array | null;
  lod: Uint8Array | null;
}

/** 시나리오(contour3d-field): schema 1 = float32 섞임 레코드, 2 = uint16 양자화 + 양자화 GLB(meshopt 없음 — 목은 인코더가 없다). disp=false = 변위 없음, lod = 저해상도 메시, nx·ny·frames = 대형 합성 */
export interface ContourOpt {
  schema?: 1 | 2;
  disp?: boolean;
  lod?: boolean;
  nx?: number;
  ny?: number;
  frames?: number;
}

/** 목: 원본마다 값의 크기를 조금 다르게(비교 모드 공통 범례 시연) — j-pred·해석 DOE는 기준 1 */
function amplitude(ref: Record<string, unknown>): number {
  const id = String(ref.job_id ?? ref.fem_verification_id ?? "");
  if (!id || id === "j-pred") return 1;
  let h = 2166136261;
  for (const ch of id) h = Math.imul(h ^ ch.charCodeAt(0), 16777619) >>> 0;
  return 0.78 + (h % 7) * 0.06;
}

export function contourData(sourceKind: string, ref: Record<string, unknown>, opt: ContourOpt = {}): ContourData {
  const schema = opt.schema ?? 1;
  const nx = opt.nx ?? NX;
  const ny = opt.ny ?? NY;
  const amp = amplitude(ref);
  const nodes = nx * ny;
  const pos = new Float32Array(nodes * 3);
  const ids = new Uint32Array(nodes);
  for (let j = 0; j < ny; j++)
    for (let i = 0; i < nx; i++) {
      const k = j * nx + i;
      const x = (PL * i) / (nx - 1);
      const y = (PW * j) / (ny - 1);
      pos.set([x, y, plateZ(x, y)], k * 3);
      ids[k] = 100001 + k;
    }
  const grid = (xs: number[], ys: number[]) => {
    const idx: number[] = [];
    for (let j = 0; j < ys.length - 1; j++)
      for (let i = 0; i < xs.length - 1; i++) {
        const n1 = ys[j] * nx + xs[i];
        const n2 = ys[j] * nx + xs[i + 1];
        const n3 = ys[j + 1] * nx + xs[i + 1];
        const n4 = ys[j + 1] * nx + xs[i];
        idx.push(n1, n2, n3, n1, n3, n4);
      }
    return Uint32Array.from(idx);
  };
  const all = (n: number) => Array.from({ length: n }, (_, k) => k);
  const idx = grid(all(nx), all(ny));
  const count = opt.frames ?? 24;
  const total = 120;
  // 프레임 값(공통): 위치별 상수를 미리 계산
  const rr = new Float32Array(nodes);
  const bd = new Float32Array(nodes);
  for (let k = 0; k < nodes; k++) {
    rr[k] = Math.hypot(pos[k * 3] - 80, pos[k * 3 + 1] - 40);
    bd[k] = Math.exp(-(((pos[k * 3 + 1] - PW / 2) / 30) ** 2)) * Math.sin((Math.PI * pos[k * 3]) / PL);
  }
  const dzOf = (k: number, s: number) => -6 * s * Math.sin((Math.PI * pos[k * 3]) / PL) * Math.sin((Math.PI * pos[k * 3 + 1]) / PW);
  const valueAt = (k: number, s: number) => amp * 412.3 * s * (0.55 * Math.exp(-(((rr[k] - 620 * s) / 90) ** 2)) + 0.45 * bd[k]) + 3 * s;
  const frameMeta = (f: number) => {
    const src = Math.round((f * (total - 1)) / Math.max(1, count - 1));
    return { src, time: Number((src * 1e-4).toFixed(6)), s: f / Math.max(1, count - 1) };
  };

  if (schema === 1) {
    const nrm = new Float32Array(nodes * 3);
    for (let t = 0; t < idx.length; t += 3) {
      const [a, b, c] = [idx[t], idx[t + 1], idx[t + 2]];
      const u = [pos[b * 3] - pos[a * 3], pos[b * 3 + 1] - pos[a * 3 + 1], pos[b * 3 + 2] - pos[a * 3 + 2]];
      const v = [pos[c * 3] - pos[a * 3], pos[c * 3 + 1] - pos[a * 3 + 1], pos[c * 3 + 2] - pos[a * 3 + 2]];
      const nn = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]];
      for (const q of [a, b, c]) for (let k = 0; k < 3; k++) nrm[q * 3 + k] += nn[k];
    }
    for (let k = 0; k < nodes; k++) {
      const l = Math.hypot(nrm[k * 3], nrm[k * 3 + 1], nrm[k * 3 + 2]) || 1;
      for (let q = 0; q < 3; q++) nrm[k * 3 + q] /= l;
    }
    const glb = writeGlb("paicad_contour", [
      { name: "surface", mode: 4, attributes: { POSITION: { data: pos, size: 3 }, NORMAL: { data: nrm, size: 3 }, _NODE_ID: { data: ids, size: 1 } }, indices: idx },
    ]);
    const rec = nodes * 4;
    const buf = new Float32Array(count * rec);
    const list: ContourManifest["frames"]["list"] = [];
    let gmin = Infinity;
    let gmax = -Infinity;
    for (let f = 0; f < count; f++) {
      const { src, time, s: sf } = frameMeta(f);
      let lo = Infinity;
      let hi = -Infinity;
      for (let k = 0; k < nodes; k++) {
        const v = valueAt(k, sf);
        buf[f * rec + k] = v;
        lo = Math.min(lo, v);
        hi = Math.max(hi, v);
        buf.set([0, 0, dzOf(k, sf)], f * rec + nodes + k * 3);
      }
      gmin = Math.min(gmin, lo);
      gmax = Math.max(gmax, hi);
      list.push({ i: f, src, time, min: Number(lo.toFixed(4)), max: Number(hi.toFixed(4)) });
    }
    const frames = new Uint8Array(buf.buffer);
    return {
      glb,
      frames,
      disp: null,
      lod: null,
      manifest: {
        schema_version: 1, kind: "contour3d", status: "OK", code: null, message: null,
        ...({ source: { kind: sourceKind, ref, h3d_name: sourceKind === "PREDICT_H3D" ? "pred.h3d" : "solver_0001.h3d" } } as object),
        display: { field: "Stress", comp: "vonMises", avgmode: "simple" },
        unit: "MPa", length_unit: "mm", up_axis: "Z",
        mesh: { file: "contour.glb", nodes, triangles: idx.length / 3, bytes: glb.byteLength },
        frames: { file: "contour_frames.bin", bytes: frames.byteLength, count, record_bytes: rec * 4, has_disp: true, dtype: "float32", nan_count: 0, list },
        range: { min: Number(gmin.toFixed(4)), max: Number(gmax.toFixed(4)) },
        sampling: { total_frames: total, max_frames: 50, rule: "uniform_inclusive" },
        warnings: [],
      } as ContourManifest,
    };
  }

  // ---- schema 2: 양자화 위치 GLB(SHORT normalized + 노드 translation·scale), 법선 없음(뷰어가 계산), uint16 프레임
  const mn = [Infinity, Infinity, Infinity];
  const mx = [-Infinity, -Infinity, -Infinity];
  for (let k = 0; k < nodes; k++)
    for (let c = 0; c < 3; c++) {
      mn[c] = Math.min(mn[c], pos[k * 3 + c]);
      mx[c] = Math.max(mx[c], pos[k * 3 + c]);
    }
  const center = mn.map((v, c) => (v + mx[c]) / 2) as [number, number, number];
  const half = mn.map((v, c) => Math.max((mx[c] - v) / 2, 1e-6)) as [number, number, number];
  const quant = (sel: number[] | null) => {
    const n = sel ? sel.length : nodes;
    const out = new Int16Array(n * 3);
    for (let a = 0; a < n; a++) {
      const k = sel ? sel[a] : a;
      for (let c = 0; c < 3; c++) out[a * 3 + c] = Math.max(-32767, Math.min(32767, Math.round(((pos[k * 3 + c] - center[c]) / half[c]) * 32767)));
    }
    return out;
  };
  const transform = { translation: center, scale: half };
  const glb = writeGlb("paicad_contour", [{ name: "surface", mode: 4, attributes: { POSITION: { data: quant(null), size: 3 }, _NODE_ID: { data: ids, size: 1 } }, indices: idx, transform }]);
  let lod: Uint8Array | null = null;
  let lodInfo: ContourManifest["lod"] = null;
  if (opt.lod) {
    const step = Math.max(2, Math.ceil(Math.max(nx, ny) / 120));
    const pick = (n: number) => Array.from(new Set([...all(n).filter((v) => v % step === 0), n - 1]));
    const xs = pick(nx);
    const ys = pick(ny);
    const sel: number[] = [];
    const at = new Map<number, number>();
    for (const j of ys)
      for (const i of xs) {
        at.set(j * nx + i, sel.length);
        sel.push(j * nx + i);
      }
    const tri = grid(xs, ys);
    const remap = Uint32Array.from(tri, (v) => at.get(v)!);
    lod = writeGlb("paicad_contour", [{ name: "surface", mode: 4, attributes: { POSITION: { data: quant(sel), size: 3 }, _NODE_ID: { data: Uint32Array.from(sel, (k) => ids[k]), size: 1 }, _SRC: { data: Uint32Array.from(sel), size: 1 } }, indices: remap, transform }]);
    lodInfo = { file: "contour_lod.glb", bytes: lod.byteLength, vertices: sel.length, triangles: remap.length / 3, method: "cluster_peak" };
  }
  const frames = new Uint8Array(count * nodes * 2);
  const fv = new Uint16Array(frames.buffer);
  const hasDisp = opt.disp !== false;
  const dispBytes = hasDisp ? new Uint8Array(count * nodes * 6) : null;
  const dv = dispBytes ? new Uint16Array(dispBytes.buffer) : null;
  const list: ContourManifest["frames"]["list"] = [];
  const dlist: NonNullable<ContourManifest["disp"]>["list"] = [];
  const vals = new Float64Array(nodes);
  let gmin = Infinity;
  let gmax = -Infinity;
  for (let f = 0; f < count; f++) {
    const { src, time, s: sf } = frameMeta(f);
    let lo = Infinity;
    let hi = -Infinity;
    let lov = 0;
    let hiv = 0;
    for (let k = 0; k < nodes; k++) {
      const v = valueAt(k, sf);
      vals[k] = v;
      if (v < lo) {
        lo = v;
        lov = k;
      }
      if (v > hi) {
        hi = v;
        hiv = k;
      }
    }
    const scale = (hi - lo) / 65534;
    for (let k = 0; k < nodes; k++) fv[f * nodes + k] = scale > 0 ? Math.round((vals[k] - lo) / scale) : 0;
    gmin = Math.min(gmin, lo);
    gmax = Math.max(gmax, hi);
    list.push({ i: f, src, time, min: lo, max: hi, scale, min_v: lov, max_v: hiv });
    if (dv) {
      const dz = new Float64Array(nodes);
      let dlo = Infinity;
      let dhi = -Infinity;
      for (let k = 0; k < nodes; k++) {
        dz[k] = dzOf(k, sf);
        dlo = Math.min(dlo, dz[k]);
        dhi = Math.max(dhi, dz[k]);
      }
      const t = (dhi - dlo) / 65535;
      for (let k = 0; k < nodes; k++) {
        const o = f * nodes * 3 + k * 3;
        dv[o] = 0;
        dv[o + 1] = 0;
        dv[o + 2] = t > 0 ? Math.round((dz[k] - dlo) / t) : 0;
      }
      dlist.push({ i: f, min: [0, 0, dlo], scale: [0, 0, t] });
    }
  }
  const manifest: ContourManifest = {
    schema_version: 2, kind: "contour3d", status: "OK", code: null, message: null,
    ...({ converter_version: 2, source: { kind: sourceKind, ref, h3d_name: sourceKind === "PREDICT_H3D" ? "pred.h3d" : "solver_0001.h3d" } } as object),
    display: { field: "Stress", comp: "vonMises", avgmode: "simple" },
    unit: "MPa", length_unit: "mm", up_axis: "Z",
    mesh: { file: "contour.glb", nodes, triangles: idx.length / 3, bytes: glb.byteLength, compression: "none", order: "grid", normals: "viewer" },
    lod: lodInfo,
    frames: { file: "contour_frames.bin", bytes: frames.byteLength, count, record_bytes: nodes * 2, has_disp: hasDisp, dtype: "uint16q", nan_code: 65535, nan_count: 0, list },
    disp: dispBytes ? { file: "contour_disp.bin", bytes: dispBytes.byteLength, record_bytes: nodes * 6, list: dlist } : null,
    range: { min: Number(gmin.toFixed(4)), max: Number(gmax.toFixed(4)) },
    limits: { nodes, max_nodes: 2_000_000, glb_bytes: glb.byteLength, max_glb_bytes: 67_108_864, bin_bytes: frames.byteLength, max_bin_bytes: 268_435_456, disp_bytes: dispBytes?.byteLength ?? 0, max_disp_bytes: 1_073_741_824 },
    scope: { comps: [], applied: false },
    sampling: { total_frames: total, max_frames: 55, rule: "uniform_inclusive" },
    warnings: hasDisp ? [] : [{ code: "CONTOUR3D_DISP_UNAVAILABLE", message: "결과에 변위가 없어 변형 표시 없이 보입니다" }],
  };
  return { glb, frames, disp: dispBytes, lod, manifest };
}
