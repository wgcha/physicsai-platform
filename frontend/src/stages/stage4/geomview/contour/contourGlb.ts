// 결과 컨투어 GLB 읽기(contour3d-field §4): GLTFLoader + three 동봉 MeshoptDecoder(주 스레드, 새 npm 의존·CDN 없음).
// KHR_mesh_quantization(SHORT normalized POSITION + 노드 translation·scale)은 로드할 때 한 번 float32 mm로 복원하고,
// 법선이 없으면(schema 2) 복원한 위치로 1회 계산한다. `_NODE_ID`·`_SRC`(LOD 원 정점 번호)는 읽어 둔다. meshopt를 쓰지 않은 GLB(폴백·v0.2.9 캐시)도 읽힌다.
import { BufferAttribute, BufferGeometry, Mesh, Matrix4, Vector3, type BufferAttribute as BA, type InterleavedBufferAttribute } from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { MeshoptDecoder } from "three/examples/jsm/libs/meshopt_decoder.module.js";

export interface ContourGeometry {
  /** float32 위치(mm)·법선·인덱스를 가진 지오메트리 — 색은 호출자가 붙인다 */
  geometry: BufferGeometry;
  nodes: number;
  /** 변형 전 위치(float32 mm, 정점 순서) */
  base: Float32Array;
  /** `_NODE_ID` (없으면 null) */
  nodeIds: Uint32Array | null;
  /** LOD 메시의 `_SRC`(원 정점 번호, 없으면 null) */
  src: Uint32Array | null;
}

function readUint(a: BA | InterleavedBufferAttribute | undefined): Uint32Array | null {
  if (!a) return null;
  if ("isBufferAttribute" in a && (a as BA).array instanceof Uint32Array && !(a as BA).normalized) return (a as BA).array as Uint32Array;
  const out = new Uint32Array(a.count);
  for (let i = 0; i < a.count; i++) out[i] = a.getX(i);
  return out;
}

export async function loadContourGlb(buf: ArrayBuffer): Promise<ContourGeometry> {
  const loader = new GLTFLoader();
  loader.setMeshoptDecoder(MeshoptDecoder);
  const gltf = await loader.parseAsync(buf, "");
  let mesh: Mesh | null = null;
  gltf.scene.traverse((o) => {
    if (!mesh && (o as Mesh).isMesh) mesh = o as Mesh;
  });
  const found = mesh as Mesh | null;
  if (!found) throw new Error("contour.glb에 면 메시가 없습니다");
  gltf.scene.updateMatrixWorld(true);
  const g = found.geometry as BufferGeometry;
  const p = g.getAttribute("position");
  const count = p.count;
  const base = new Float32Array(count * 3);
  const m = found.matrixWorld;
  if (m.equals(new Matrix4())) {
    for (let i = 0; i < count; i++) {
      base[i * 3] = p.getX(i);
      base[i * 3 + 1] = p.getY(i);
      base[i * 3 + 2] = p.getZ(i);
    }
  } else {
    const v = new Vector3();
    for (let i = 0; i < count; i++) {
      v.set(p.getX(i), p.getY(i), p.getZ(i)).applyMatrix4(m);
      base[i * 3] = v.x;
      base[i * 3 + 1] = v.y;
      base[i * 3 + 2] = v.z;
    }
  }
  const geometry = new BufferGeometry();
  geometry.setAttribute("position", new BufferAttribute(base.slice(), 3));
  if (g.index) geometry.setIndex(g.index);
  const normal = g.getAttribute("normal");
  if (normal && !(normal as BA).normalized) geometry.setAttribute("normal", normal as BA);
  else geometry.computeVertexNormals(); // 변형 중에는 다시 계산하지 않는다(§13.4)
  const nodeIds = readUint(g.getAttribute("_node_id"));
  const src = readUint(g.getAttribute("_src"));
  g.dispose();
  return { geometry, nodes: count, base, nodeIds, src };
}
