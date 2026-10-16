// S10 목: 작은 PNG 인코더(무압축 deflate 블록) + 방향별 가짜 컨투어 그림.
// 목 서버가 /artifacts/{id}/content 로 진짜 PNG 바이트를 돌려준다(데이터 URL 아님). 요청 때 그린다(시드 비용 없음).

const CRC_TABLE = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    t[n] = c >>> 0;
  }
  return t;
})();

function crc32(bytes: Uint8Array): number {
  let c = 0xffffffff;
  for (let i = 0; i < bytes.length; i++) c = CRC_TABLE[(c ^ bytes[i]) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

function adler32(bytes: Uint8Array): number {
  let a = 1;
  let b = 0;
  for (let i = 0; i < bytes.length; i++) {
    a = (a + bytes[i]) % 65521;
    b = (b + a) % 65521;
  }
  return ((b << 16) | a) >>> 0;
}

const u32 = (v: number) => [(v >>> 24) & 0xff, (v >>> 16) & 0xff, (v >>> 8) & 0xff, v & 0xff];

function chunk(type: string, data: Uint8Array): number[] {
  const td = new Uint8Array(4 + data.length);
  for (let i = 0; i < 4; i++) td[i] = type.charCodeAt(i);
  td.set(data, 4);
  return [...u32(data.length), ...td, ...u32(crc32(td))];
}

/** RGB 픽셀 함수 → PNG 바이트 */
export function encodePng(w: number, h: number, px: (x: number, y: number) => [number, number, number]): Uint8Array {
  const raw = new Uint8Array(h * (1 + w * 3));
  let o = 0;
  for (let y = 0; y < h; y++) {
    raw[o++] = 0; // 필터 없음
    for (let x = 0; x < w; x++) {
      const [r, g, b] = px(x, y);
      raw[o++] = r;
      raw[o++] = g;
      raw[o++] = b;
    }
  }
  // zlib: 헤더 + 무압축 블록(최대 65535바이트씩) + adler32
  const blocks: number[] = [0x78, 0x01];
  for (let i = 0; i < raw.length; i += 65535) {
    const n = Math.min(65535, raw.length - i);
    const last = i + n >= raw.length ? 1 : 0;
    blocks.push(last, n & 0xff, n >>> 8, ~n & 0xff, (~n >>> 8) & 0xff);
    for (let k = 0; k < n; k++) blocks.push(raw[i + k]);
  }
  blocks.push(...u32(adler32(raw)));
  const ihdr = new Uint8Array([...u32(w), ...u32(h), 8, 2, 0, 0, 0]);
  return new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10, ...chunk("IHDR", ihdr), ...chunk("IDAT", new Uint8Array(blocks)), ...chunk("IEND", new Uint8Array(0))]);
}

/** HyperView 기본 범례처럼 9단 띠(파랑 → 빨강) */
const BANDS: [number, number, number][] = [
  [0, 0, 200], [0, 85, 255], [0, 170, 255], [0, 220, 170], [60, 200, 60], [170, 220, 0], [255, 220, 0], [255, 140, 0], [220, 20, 20],
];
const BG: [number, number, number] = [236, 236, 232];
const EDGE: [number, number, number] = [40, 40, 40];

/** 방향별 가짜 컨투어(판 모양 쿠션: 가운데·리브에 응력 집중). values로 무늬가 run마다 조금 다르다 */
export function contourPng(view: string, values: Record<string, number>, frame = 1): Uint8Array {
  const W = 320;
  const H = 200;
  const ribs = Math.max(2, Math.round(values.RIB_N ?? 4));
  const thk = Math.max(0.2, Math.min(1, values.THK_TOP ?? 0.5));
  const peak = 0.55 + 0.45 * Math.min(1, (values.E_FOAM ?? 8) / 14);
  /** 판 좌표(u,v ∈ [0,1]) → 0..1 값 */
  const field = (u: number, v: number) => {
    const c = Math.exp(-(((u - 0.5) / 0.28) ** 2 + ((v - 0.5) / 0.35) ** 2));
    const rib = 0.5 + 0.5 * Math.cos(u * Math.PI * 2 * ribs);
    return Math.max(0, Math.min(0.999, frame * peak * (0.75 * c + 0.25 * rib * c + 0.1 * v)));
  };
  const color = (f: number) => BANDS[Math.floor(f * BANDS.length)];
  // 방향별 투영: 화면 (x,y) → 판 좌표 또는 null
  const L = 40; // 범례 오른쪽 끝
  const proj = (x: number, y: number): [number, number] | "edge" | null => {
    const X = x - L - 10;
    const Wp = W - L - 24;
    if (view === "top" || view === "bottom") {
      const u = X / Wp;
      const v = (y - 30) / 140;
      return u >= 0 && u <= 1 && v >= 0 && v <= 1 ? [u, view === "bottom" ? 1 - v : v] : null;
    }
    if (view === "front" || view === "back" || view === "left" || view === "right") {
      const span = view === "left" || view === "right" ? Wp * 0.62 : Wp;
      const hgt = 18 + 40 * thk;
      const u = X / span;
      const v = (y - (100 - hgt / 2)) / hgt;
      if (u < 0 || u > 1 || v < 0 || v > 1) return null;
      return [u, 0.5 + 0.4 * (v - 0.5)];
    }
    // iso: 기울인 윗면 + 앞면 두께
    const sx = X - (170 - y) * 0.55;
    const u = sx / (Wp * 0.72);
    const v = (y - 40) / 100;
    if (u >= 0 && u <= 1 && v >= 0 && v <= 1) return [u, v];
    const sideH = 10 + 18 * thk;
    const fu = (X - (170 - 140) * 0.55) / (Wp * 0.72);
    if (fu >= 0 && fu <= 1 && y > 140 && y <= 140 + sideH) return "edge";
    return null;
  };
  return encodePng(W, H, (x, y) => {
    // 범례(왼쪽 세로 띠, 위 = 빨강)
    if (x >= 12 && x < 24 && y >= 30 && y < 170) return BANDS[BANDS.length - 1 - Math.floor(((y - 30) / 140) * BANDS.length)];
    const p = proj(x, y);
    if (p === null) return BG;
    if (p === "edge") return EDGE;
    return color(field(p[0], p[1]));
  });
}
