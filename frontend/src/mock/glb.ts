// 목 전용 작은 GLB(glTF 2.0 바이너리) 작성기(geometry-view.md §4.1·§13.4 모양): 헤더 + JSON 청크 + BIN 청크, 4바이트 정렬, 확장 없음.
// 루트 노드 아래 노드마다 primitive 1개. 사용자 정의 속성은 `_` 접두(UNSIGNED_SHORT는 byteStride 4 — GV-C1).

export type GlbAttr = Float32Array | Uint16Array | Uint32Array;
export interface GlbNode {
  name: string;
  mode: 0 | 1 | 4; // POINTS · LINES · TRIANGLES
  attributes: Record<string, { data: GlbAttr; size: 1 | 3 }>;
  indices?: Uint32Array;
}

const FLOAT = 5126;
const USHORT = 5123;
const UINT = 5125;

export function writeGlb(rootName: string, nodes: GlbNode[]): Uint8Array {
  const chunks: Uint8Array[] = [];
  let offset = 0;
  const bufferViews: Record<string, unknown>[] = [];
  const accessors: Record<string, unknown>[] = [];
  const push = (bytes: Uint8Array, stride?: number, target?: number) => {
    const pad = (4 - (offset % 4)) % 4;
    if (pad) {
      chunks.push(new Uint8Array(pad));
      offset += pad;
    }
    bufferViews.push({ buffer: 0, byteOffset: offset, byteLength: bytes.byteLength, ...(stride ? { byteStride: stride } : {}), ...(target ? { target } : {}) });
    chunks.push(bytes);
    offset += bytes.byteLength;
    return bufferViews.length - 1;
  };
  const accessor = (data: GlbAttr, size: 1 | 3, isIndex = false) => {
    let bytes: Uint8Array;
    let stride: number | undefined;
    let componentType = FLOAT;
    if (data instanceof Uint16Array) {
      componentType = USHORT;
      // 4바이트 정렬: 값 하나마다 4바이트(2바이트 값 + 2바이트 채움)
      const wide = new Uint16Array(data.length * 2);
      data.forEach((v, i) => (wide[i * 2] = v));
      bytes = new Uint8Array(wide.buffer);
      stride = 4;
    } else {
      componentType = data instanceof Uint32Array ? UINT : FLOAT;
      bytes = new Uint8Array(data.buffer, data.byteOffset, data.byteLength);
    }
    const view = push(bytes, isIndex ? undefined : stride, isIndex ? 34963 : 34962);
    const count = data.length / size;
    const acc: Record<string, unknown> = { bufferView: view, componentType, count, type: size === 3 ? "VEC3" : "SCALAR" };
    if (size === 3 && data instanceof Float32Array) {
      const min = [Infinity, Infinity, Infinity];
      const max = [-Infinity, -Infinity, -Infinity];
      for (let i = 0; i < count; i++)
        for (let k = 0; k < 3; k++) {
          min[k] = Math.min(min[k], data[i * 3 + k]);
          max[k] = Math.max(max[k], data[i * 3 + k]);
        }
      acc.min = min;
      acc.max = max;
    }
    accessors.push(acc);
    return accessors.length - 1;
  };
  const meshes = nodes.map((n) => {
    const attributes: Record<string, number> = {};
    for (const [k, a] of Object.entries(n.attributes)) attributes[k] = accessor(a.data, a.size);
    const prim: Record<string, unknown> = { attributes, mode: n.mode, material: 0 };
    if (n.indices) prim.indices = accessor(n.indices, 1, true);
    return { name: n.name, primitives: [prim] };
  });
  const json = {
    asset: { version: "2.0", generator: "physicsai mock" },
    scene: 0,
    scenes: [{ nodes: [0] }],
    nodes: [{ name: rootName, children: nodes.map((_, i) => i + 1), extras: { unit: "mm", up_axis: "Z" } }, ...nodes.map((n, i) => ({ name: n.name, mesh: i }))],
    meshes,
    materials: [{ name: "default", doubleSided: true, pbrMetallicRoughness: { baseColorFactor: [0.7, 0.7, 0.7, 1], metallicFactor: 0, roughnessFactor: 1 } }],
    accessors,
    bufferViews,
    buffers: [{ byteLength: 0 }],
  };
  const binPad = (4 - (offset % 4)) % 4;
  const binLen = offset + binPad;
  json.buffers[0].byteLength = binLen;
  let jsonBytes = new TextEncoder().encode(JSON.stringify(json));
  const jPad = (4 - (jsonBytes.length % 4)) % 4;
  if (jPad) {
    const t = new Uint8Array(jsonBytes.length + jPad).fill(0x20);
    t.set(jsonBytes);
    jsonBytes = t;
  }
  const total = 12 + 8 + jsonBytes.length + 8 + binLen;
  const out = new Uint8Array(total);
  const dv = new DataView(out.buffer);
  dv.setUint32(0, 0x46546c67, true); // glTF
  dv.setUint32(4, 2, true);
  dv.setUint32(8, total, true);
  dv.setUint32(12, jsonBytes.length, true);
  dv.setUint32(16, 0x4e4f534a, true); // JSON
  out.set(jsonBytes, 20);
  let p = 20 + jsonBytes.length;
  dv.setUint32(p, binLen, true);
  dv.setUint32(p + 4, 0x004e4942, true); // BIN
  p += 8;
  for (const c of chunks) {
    out.set(c, p);
    p += c.byteLength;
  }
  return out;
}

/** GLB 헤더·청크 읽기(시험용): JSON 객체 + BIN 바이트 */
export function readGlb(bytes: Uint8Array): { json: Record<string, unknown>; bin: Uint8Array } {
  const dv = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  if (dv.getUint32(0, true) !== 0x46546c67) throw new Error("GLB 아님");
  const jLen = dv.getUint32(12, true);
  const json = JSON.parse(new TextDecoder().decode(bytes.subarray(20, 20 + jLen)));
  const bLen = dv.getUint32(20 + jLen, true);
  return { json, bin: bytes.subarray(28 + jLen, 28 + jLen + bLen) };
}
