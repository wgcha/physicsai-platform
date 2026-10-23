// V-C3F-8 왕복(서버 인코더 → 프런트 디코더): `python -m physicsai_core.contour3d.fixture <폴더>`가 만든 GLB·프레임·변위 파일을 커밋한 픽스처로 쓴다
// (fixtures/c3f_server/{meshopt,plain}, `--b64`로 `*.b64` 텍스트화 — 재생성: `python -m physicsai_core.contour3d.fixture <폴더> --b64`, 백엔드 시험이 최신 여부를 검사). `loadContourGlb`(GLTFLoader + MeshoptDecoder)와 프레임 복원이 합성 입력의 위치·노드 ID·값과 맞는지 대조한다.
// 합성 입력(fixture.py): 24×16×2 노드, 값 = sin(id·0.3)·50·(i+1), 변위 = (0.1·i·cos(0.2·id), 0, −0.05·i), 입력 4번째 행의 값·변위 없음(NaN).
// 기존 JS 인코더 픽스처(c3f_meshopt_plate)·목 GLB 시험(contourGlb.test.ts)은 그대로 둔다.
import { describe, expect, it } from "vitest";
import { loadContourGlb, type ContourGeometry } from "../stages/stage4/geomview/contour/contourGlb";
import { decodeDispFor, decodeScalarFor, frameExtremes, isQuantized, manifestHasDisp, type ContourManifest } from "../stages/stage4/geomview/contour/contourCore";
import mGlb from "./fixtures/c3f_server/meshopt/contour.glb.b64?raw";
import mLod from "./fixtures/c3f_server/meshopt/contour_lod.glb.b64?raw";
import mFrames from "./fixtures/c3f_server/meshopt/contour_frames.bin.b64?raw";
import mDisp from "./fixtures/c3f_server/meshopt/contour_disp.bin.b64?raw";
import mManifest from "./fixtures/c3f_server/meshopt/contour_manifest.json";
import mExpected from "./fixtures/c3f_server/meshopt/expected.json";
import pGlb from "./fixtures/c3f_server/plain/contour.glb.b64?raw";
import pLod from "./fixtures/c3f_server/plain/contour_lod.glb.b64?raw";
import pFrames from "./fixtures/c3f_server/plain/contour_frames.bin.b64?raw";
import pDisp from "./fixtures/c3f_server/plain/contour_disp.bin.b64?raw";
import pManifest from "./fixtures/c3f_server/plain/contour_manifest.json";
import pExpected from "./fixtures/c3f_server/plain/expected.json";

const b64 = (s: string): ArrayBuffer => {
  const u = Uint8Array.from(atob(s.trim()), (c) => c.charCodeAt(0));
  return u.buffer.slice(u.byteOffset, u.byteOffset + u.byteLength) as ArrayBuffer;
};
const ab = b64;

interface Expected {
  count: number;
  position_i16: string;
  _NODE_ID: string;
  _SRC?: string;
  indices_u32: string;
  translation: number[];
  scale: number[];
}
type Variant = { name: string; glb: string; lod: string; frames: string; disp: string; manifest: unknown; expected: Record<string, Expected> };

const variants: Variant[] = [
  { name: "meshopt(압축)", glb: mGlb, lod: mLod, frames: mFrames, disp: mDisp, manifest: mManifest, expected: mExpected as unknown as Record<string, Expected> },
  { name: "plain(meshopt 끔)", glb: pGlb, lod: pLod, frames: pFrames, disp: pDisp, manifest: pManifest, expected: pExpected as unknown as Record<string, Expected> },
];

/** 서버 인코더가 쓴 int16 위치(정규화 SHORT) → mm: v = max(q/32767, −1)·scale + translation */
function expectedPositions(e: Expected): Float32Array {
  const q = new Int16Array(b64(e.position_i16));
  const out = new Float32Array(q.length);
  for (let k = 0; k < q.length; k++) out[k] = Math.max(q[k] / 32767, -1) * e.scale[k % 3] + e.translation[k % 3];
  return out;
}

// 합성 입력의 정답(노드 ID로 계산)
const trueValue = (id: number, i: number) => Math.sin(id * 0.3) * 50 * (i + 1);
const NAN_NODE = 500 + (768 - 1 - 3) * 7; // 입력 4번째 행 = ids[3]

describe.each(variants)("V-C3F-8 서버 인코더 픽스처 왕복 — $name", (v) => {
  const m = v.manifest as unknown as ContourManifest;
  let full: ContourGeometry;
  let lod: ContourGeometry;
  const idOf = (g: ContourGeometry, k: number) => g.nodeIds![k];

  it("manifest v2 필드명: frames.list(scale·min_v·max_v)·disp.list(min[3]·scale[3])·lod·mesh.compression·nan_code", () => {
    expect(m.schema_version).toBe(2);
    expect(isQuantized(m)).toBe(true);
    expect(m.frames.dtype).toBe("uint16q");
    expect(m.frames.nan_code).toBe(65535);
    expect(m.mesh.compression).toBe(v.name.startsWith("meshopt") ? "meshopt" : "none");
    expect(m.frames.list.length).toBe(3);
    for (const f of m.frames.list) expect(f).toEqual(expect.objectContaining({ i: expect.any(Number), scale: expect.any(Number), min_v: expect.any(Number), max_v: expect.any(Number) }));
    expect(manifestHasDisp(m)).toBe(true);
    expect(m.disp!.list.length).toBe(3);
    expect(m.disp!.list[1].min).toHaveLength(3);
    expect(m.disp!.list[1].scale).toHaveLength(3);
    expect(m.lod!.vertices).toBeLessThan(m.mesh.nodes);
    expect(m.scope).toEqual(expect.objectContaining({ comps: [], comps_applicable: false }));
    expect(m.unit).toBe("MPa");
  });

  it("전체 GLB: 정점 수·위치·노드 ID·인덱스가 인코더 기대값과 같다", async () => {
    full = await loadContourGlb(ab(v.glb));
    const e = v.expected["contour.glb"];
    expect(full.nodes).toBe(e.count);
    expect(full.nodes).toBe(m.mesh.nodes);
    expect(full.src).toBeNull();
    const pos = expectedPositions(e);
    for (let k = 0; k < pos.length; k++) expect(full.base[k]).toBeCloseTo(pos[k], 3);
    expect(Array.from(full.nodeIds!)).toEqual(Array.from(new Uint32Array(b64(e._NODE_ID))));
    expect(Array.from(full.geometry.getIndex()!.array)).toEqual(Array.from(new Uint32Array(b64(e.indices_u32))));
    expect(full.geometry.getAttribute("normal").count).toBe(full.nodes);
    // 합성 판(0..46 × 0..22.5 × 0..0.2 mm) 안, 양자화 오차 이내
    const xs = Array.from({ length: full.nodes }, (_, k) => full.base[k * 3]);
    expect(Math.min(...xs)).toBeCloseTo(0, 2);
    expect(Math.max(...xs)).toBeCloseTo(46, 2);
  });

  it("LOD GLB: _SRC가 원 정점을 가리키고 위치·노드 ID가 전체와 같다", async () => {
    lod = await loadContourGlb(ab(v.lod));
    const e = v.expected["contour_lod.glb"];
    expect(lod.nodes).toBe(e.count);
    expect(lod.nodes).toBe(m.lod!.vertices);
    expect(Array.from(lod.src!)).toEqual(Array.from(new Uint32Array(b64(e._SRC!))));
    for (let j = 0; j < lod.nodes; j++) {
      const s = lod.src![j];
      expect(s).toBeLessThan(full.nodes);
      expect(idOf(lod, j)).toBe(idOf(full, s));
      for (let c = 0; c < 3; c++) expect(lod.base[j * 3 + c]).toBeCloseTo(full.base[s * 3 + c], 3);
    }
  });

  it("스칼라 프레임: 노드 ID별 정답과 양자화 간격 이내로 같고, 값 없음 노드는 NaN", () => {
    const bytes = ab(v.frames);
    const n = m.mesh.nodes;
    expect(bytes.byteLength).toBe(m.frames.bytes);
    expect(m.frames.record_bytes).toBe(2 * n);
    for (let i = 0; i < m.frames.count; i++) {
      const s = decodeScalarFor(m, i, bytes, i * m.frames.record_bytes);
      const tol = (m.frames.list[i].scale ?? 0) / 2 + 1e-4;
      let nan = 0;
      for (let k = 0; k < n; k++) {
        const id = idOf(full, k);
        if (id === NAN_NODE) {
          expect(Number.isNaN(s[k])).toBe(true);
          nan++;
        } else expect(Math.abs(s[k] - trueValue(id, i))).toBeLessThanOrEqual(tol);
      }
      expect(nan).toBe(1);
      // 극값 정점: manifest의 max_v·min_v 위치의 복원 값이 manifest max·min과 같고, 정답의 최대·최소 노드다
      for (const x of frameExtremes(m, i)) expect(Math.abs(s[x.vertex] - x.value)).toBeLessThanOrEqual(tol);
    }
  });

  it("변위 프레임: 노드 ID별 정답과 같고, 변위 파일은 프레임당 6·N 바이트", () => {
    const bytes = ab(v.disp);
    const n = m.mesh.nodes;
    expect(bytes.byteLength).toBe(m.disp!.bytes);
    expect(m.disp!.record_bytes).toBe(6 * n);
    for (let i = 0; i < m.frames.count; i++) {
      const d = decodeDispFor(m, i, bytes, i * m.disp!.record_bytes);
      for (let k = 0; k < n; k++) {
        const id = idOf(full, k);
        if (id === NAN_NODE) continue; // 값 없음 행의 변위는 정답 없음
        const want = [0.1 * i * Math.cos(id * 0.2), 0, -0.05 * i];
        for (let c = 0; c < 3; c++) expect(Math.abs(d[k * 3 + c] - want[c])).toBeLessThanOrEqual(m.disp!.list[i].scale[c] / 2 + 1e-6);
      }
    }
  });
});

describe("메시 압축 여부와 무관", () => {
  it("meshopt와 plain GLB는 같은 위치·노드 ID·인덱스를 준다(바이트는 다름)", async () => {
    const a = await loadContourGlb(ab(mGlb));
    const b = await loadContourGlb(ab(pGlb));
    expect(ab(mGlb).byteLength).toBeLessThan(ab(pGlb).byteLength);
    expect(Array.from(a.nodeIds!)).toEqual(Array.from(b.nodeIds!));
    expect(Array.from(a.base)).toEqual(Array.from(b.base));
    expect(Array.from(a.geometry.getIndex()!.array)).toEqual(Array.from(b.geometry.getIndex()!.array));
  });
});
