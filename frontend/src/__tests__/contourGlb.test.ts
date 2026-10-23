// 컨투어 GLB 읽기(contour3d-field §4, V-C3F-8 디코드 측): three 동봉 MeshoptDecoder 연결, KHR_mesh_quantization 위치 복원, 법선 1회 계산,
// `_NODE_ID`·`_SRC` 보존, meshopt를 쓰지 않은 GLB(폴백·v0.2.9)도 읽힘. 픽스처 = 실제 meshopt 인코더(meshoptimizer 1.1.1)로 만든 12×8 판.
import fixtureB64 from "./fixtures/c3f_meshopt_plate.glb.b64?raw"; // 실제 meshopt 인코더로 만든 GLB(base64) — 생성: 전용 스크립트(scratchpad c3f_gen_fixture.mjs)
import sceneSrc from "../stages/stage4/geomview/threeScene.ts?raw";
import glbSrc from "../stages/stage4/geomview/contour/contourGlb.ts?raw";
import { describe, expect, it } from "vitest";
import { loadContourGlb } from "../stages/stage4/geomview/contour/contourGlb";
import { contourData } from "../mock/geomViewData";
import { readGlb } from "../mock/glb";

const fixture = () => Uint8Array.from(atob(fixtureB64.trim()), (c) => c.charCodeAt(0));
const ab = (u: Uint8Array) => u.buffer.slice(u.byteOffset, u.byteOffset + u.byteLength) as ArrayBuffer;

describe("contourGlb", () => {
  it("meshopt 압축 GLB(ATTRIBUTES + INDICES + 양자화 위치)를 디코드한다 — 위치 복원·_NODE_ID 순서·법선", async () => {
    const file = fixture();
    const { json } = readGlb(file);
    expect(json.extensionsRequired).toEqual(["KHR_mesh_quantization", "EXT_meshopt_compression"]);
    const r = await loadContourGlb(ab(file));
    expect(r.nodes).toBe(96);
    expect(r.src).toBeNull();
    expect(Array.from(r.nodeIds!.slice(0, 3))).toEqual([5000, 5001, 5002]);
    expect(r.nodeIds![95]).toBe(5095);
    // 정점 k = j*12 + i → (10i, 5j, i+j), 양자화 오차 ≤ half/32767/2
    for (const [i, j] of [[0, 0], [11, 0], [3, 5], [11, 7]]) {
      const k = j * 12 + i;
      expect(r.base[k * 3]).toBeCloseTo(10 * i, 1);
      expect(r.base[k * 3 + 1]).toBeCloseTo(5 * j, 1);
      expect(r.base[k * 3 + 2]).toBeCloseTo(i + j, 1);
    }
    expect(r.geometry.getIndex()!.count).toBe(11 * 7 * 6);
    const nrm = r.geometry.getAttribute("normal");
    expect(nrm.count).toBe(96); // NORMAL은 파일에 없고 로드할 때 1회 계산
    expect(Math.hypot(nrm.getX(40), nrm.getY(40), nrm.getZ(40))).toBeCloseTo(1, 3);
    expect(Math.abs(nrm.getZ(40))).toBeGreaterThan(0.9); // 거의 평평한 판 → z 법선
    expect(r.geometry.getAttribute("position").array).toBeInstanceOf(Float32Array); // 역양자화는 1회
  });

  it("meshopt를 쓰지 않은 양자화 GLB(meshopt:false 폴백)도 읽힌다 — 위치는 노드 translation·scale로 복원", async () => {
    const d = contourData("PREDICT_H3D", { job_id: "j" }, { schema: 2 });
    const { json } = readGlb(d.glb);
    expect(json.extensionsUsed).toEqual(["KHR_mesh_quantization"]);
    const r = await loadContourGlb(ab(d.glb));
    expect(r.nodes).toBe(d.manifest.mesh.nodes);
    expect(r.nodeIds![0]).toBe(100001);
    expect(r.nodeIds![r.nodes - 1]).toBe(100000 + r.nodes);
    // 양 끝 위치 = 판 크기(0..560, 0..320) 근처
    expect(r.base[0]).toBeCloseTo(0, 1);
    expect(r.base[(r.nodes - 1) * 3]).toBeCloseTo(560, 1);
    expect(r.base[(r.nodes - 1) * 3 + 1]).toBeCloseTo(320, 1);
    expect(r.geometry.getAttribute("normal").count).toBe(r.nodes);
  });

  it("LOD GLB: _SRC(원 정점 번호)와 _NODE_ID 보존, LOD 정점은 원 노드의 위치", async () => {
    const d = contourData("PREDICT_H3D", { job_id: "j" }, { schema: 2, lod: true });
    expect(d.manifest.lod!.vertices).toBeLessThan(d.manifest.mesh.nodes);
    const full = await loadContourGlb(ab(d.glb));
    const lod = await loadContourGlb(ab(d.lod!));
    expect(lod.nodes).toBe(d.manifest.lod!.vertices);
    expect(lod.src!.length).toBe(lod.nodes);
    for (const j of [0, 5, lod.nodes - 1]) {
      const s = lod.src![j];
      expect(lod.nodeIds![j]).toBe(full.nodeIds![s]);
      expect(lod.base[j * 3]).toBeCloseTo(full.base[s * 3], 1);
      expect(lod.base[j * 3 + 2]).toBeCloseTo(full.base[s * 3 + 2], 1);
    }
  });

  it("v0.2.9 GLB(float32 위치·법선)는 그대로 읽는다 — 법선을 다시 계산하지 않고 `_NODE_ID` 유지", async () => {
    const d = contourData("PREDICT_H3D", { job_id: "j" }, { schema: 1 });
    const r = await loadContourGlb(ab(d.glb));
    expect(r.nodes).toBe(d.manifest.mesh.nodes);
    expect(r.nodeIds![3]).toBe(100004);
    expect(r.geometry.getAttribute("normal").count).toBe(r.nodes);
  });

  it("면 메시가 없으면 오류", async () => {
    const empty = fixture();
    // 헤더만 망가뜨려 GLTFLoader가 거부 → 오류가 그대로 전달된다
    empty[0] = 0;
    await expect(loadContourGlb(ab(empty))).rejects.toBeTruthy();
  });
});

describe("허용 모듈(geometry-view §7.1, C3F-2)", () => {
  const src = [sceneSrc, glbSrc].join("\n");
  it("three examples는 GLTFLoader·OrbitControls·CSS2DRenderer·meshopt_decoder.module만, Draco·웹 워커·외부 URL 없음", () => {
    const mods = [...new Set([...src.matchAll(/from "(three\/examples\/[^"]+)"/g)].map((m) => m[1]))].sort();
    expect(mods).toEqual(["three/examples/jsm/controls/OrbitControls.js", "three/examples/jsm/libs/meshopt_decoder.module.js", "three/examples/jsm/loaders/GLTFLoader.js", "three/examples/jsm/renderers/CSS2DRenderer.js"]);
    expect(src).not.toMatch(/DRACOLoader|new Worker|https?:\/\//);
  });
});
