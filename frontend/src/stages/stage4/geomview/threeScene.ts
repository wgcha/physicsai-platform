// three.js 장면(geometry-view.md §7·§13.6) — 3D 패널을 열 때만 동적 import("./threeScene")로 적재한다(별도 청크, CDN·디코더 로더 없음).
// 허용 모듈: three 코어 + examples/jsm GLTFLoader·OrbitControls·CSS2DRenderer + libs/meshopt_decoder.module.js(contour3d-field C3F-2, 컨투어 GLB 읽기 — contour/contourGlb.ts). 렌더는 요청 시(onDemand), 픽셀 비 ≤ 2.
// 좌표 mm·Z-up(카메라 up = Z). 하이라이트 = faces[].tri 구간 → geometry 그룹 + 재질 배열(정점 탐색 없음).
import {
  AmbientLight,
  Box3,
  BufferAttribute,
  BufferGeometry,
  CanvasTexture,
  Color,
  DirectionalLight,
  DoubleSide,
  FrontSide,
  Group,
  LineBasicMaterial,
  LineSegments,
  Material,
  Mesh,
  MeshLambertMaterial,
  Object3D,
  PerspectiveCamera,
  Points,
  PointsMaterial,
  Raycaster,
  Scene,
  Sprite,
  SpriteMaterial,
  Texture,
  Vector2,
  Vector3,
  WebGLRenderer,
} from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { loadContourGlb } from "./contour/contourGlb";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { CSS2DObject, CSS2DRenderer } from "three/examples/jsm/renderers/CSS2DRenderer.js";
import { faceGroups, lightColor, nearestScreenPoint, SELECTION_COLORS, type FixedCluster, type Highlight, type ViewManifest, type DimDraw, type Vec3 } from "./viewerCore";
import { fillColors } from "./contour/colormap";
import type { BoxState, CameraState } from "./contour/contourCore";

// PNG 하이라이트와 같은 색(이동 주황·고정 파랑) + 실패 빨강
const COLORS = { base: 0xb9c0c8, moving: 0xf08c28, fixed: 0x3c6edc, red: 0xe5484d, ghost: 0x9aa4ae, edge: 0x2b3440, dim: 0x7dff5a };

class Stage {
  readonly renderer: WebGLRenderer;
  readonly labels: CSS2DRenderer;
  readonly scene = new Scene();
  readonly camera = new PerspectiveCamera(35, 1, 0.1, 1e7);
  readonly controls: OrbitControls;
  private raf = 0;
  private loop = false;
  private ro: ResizeObserver | null = null;
  private disposed = false;
  onFrame: (() => void) | null = null;

  constructor(readonly container: HTMLElement, onLost: () => void) {
    this.renderer = new WebGLRenderer({ antialias: true, alpha: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.domElement.className = "gv-canvas";
    container.appendChild(this.renderer.domElement);
    this.labels = new CSS2DRenderer();
    this.labels.domElement.className = "gv-labels";
    container.appendChild(this.labels.domElement);
    this.camera.up.set(0, 0, 1);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.addEventListener("change", () => this.request());
    this.scene.add(new AmbientLight(0xffffff, 0.85));
    const key = new DirectionalLight(0xffffff, 1.1);
    key.position.set(0.4, -0.6, 1);
    this.camera.add(key);
    this.scene.add(this.camera);
    this.renderer.domElement.addEventListener("webglcontextlost", (e) => {
      e.preventDefault();
      onLost();
    });
    this.resize();
    if (typeof ResizeObserver !== "undefined") {
      this.ro = new ResizeObserver(() => this.resize());
      this.ro.observe(container);
    }
  }

  resize() {
    const w = Math.max(1, this.container.clientWidth);
    const h = Math.max(1, this.container.clientHeight);
    this.renderer.setSize(w, h, false);
    this.renderer.domElement.style.width = "100%";
    this.renderer.domElement.style.height = "100%";
    this.labels.setSize(w, h);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.request();
  }

  request() {
    if (this.disposed || this.raf) return;
    this.raf = requestAnimationFrame(() => {
      this.raf = 0;
      this.onFrame?.();
      this.renderer.render(this.scene, this.camera);
      this.labels.render(this.scene, this.camera);
      if (this.loop) this.request();
    });
  }

  /** 재생 중에만 연속 렌더 */
  setLoop(on: boolean) {
    this.loop = on;
    if (on) this.request();
  }

  fitTo(objects: Object3D[]) {
    const box = new Box3();
    for (const o of objects) if (o.visible) box.expandByObject(o);
    this.fitBox(box);
  }

  fitBox(box: Box3) {
    if (box.isEmpty()) return;
    const center = box.getCenter(new Vector3());
    const dir = new Vector3(1, -1.4, 0.9).normalize();
    // 상자 8 꼭짓점이 화면 안에 들어오는 최소 거리(구 대신 투영 — 넓은 화면에서 모델이 작아지지 않게)
    this.camera.position.copy(center).add(dir);
    this.camera.lookAt(center);
    this.camera.updateMatrixWorld();
    const r = new Vector3().setFromMatrixColumn(this.camera.matrixWorld, 0);
    const u = new Vector3().setFromMatrixColumn(this.camera.matrixWorld, 1);
    const tv = Math.tan(((this.camera.fov / 2) * Math.PI) / 180);
    const th = tv * this.camera.aspect;
    let dist = 1e-3;
    const c = new Vector3();
    for (const x of [box.min.x, box.max.x])
      for (const y of [box.min.y, box.max.y])
        for (const z of [box.min.z, box.max.z]) {
          c.set(x, y, z).sub(center);
          const d = c.dot(dir); // 카메라 쪽으로 나온 정도
          dist = Math.max(dist, Math.abs(c.dot(r)) / th + d, Math.abs(c.dot(u)) / tv + d);
        }
    dist *= 1.12;
    this.camera.position.copy(center).addScaledVector(dir, dist);
    this.camera.near = dist / 1000;
    this.camera.far = dist * 100;
    this.camera.updateProjectionMatrix();
    this.controls.target.copy(center);
    this.controls.update();
    this.request();
  }

  /** 클릭(이동 4px 미만) 좌표 → NDC */
  onClick(cb: (ndc: Vector2, additive: boolean) => void) {
    const el = this.renderer.domElement;
    let down: [number, number] | null = null;
    el.addEventListener("pointerdown", (e) => (down = [e.clientX, e.clientY]));
    el.addEventListener("pointerup", (e) => {
      if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 4) return;
      const r = el.getBoundingClientRect();
      cb(new Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1), e.ctrlKey || e.metaKey);
    });
  }

  dispose() {
    this.disposed = true;
    cancelAnimationFrame(this.raf);
    this.ro?.disconnect();
    this.controls.dispose();
    disposeTree(this.scene);
    this.renderer.dispose();
    this.renderer.domElement.remove();
    this.labels.domElement.remove();
  }
}

function disposeTree(root: Object3D) {
  root.traverse((o) => {
    const g = (o as Mesh).geometry as BufferGeometry | undefined;
    g?.dispose?.();
    const m = (o as Mesh).material as Material | Material[] | undefined;
    for (const x of Array.isArray(m) ? m : m ? [m] : []) {
      const t = (x as SpriteMaterial).map as Texture | null | undefined;
      t?.dispose();
      x.dispose();
    }
    if (o instanceof CSS2DObject) o.element.remove();
  });
}

async function parseGlb(buf: ArrayBuffer): Promise<Object3D> {
  const gltf = await new GLTFLoader().parseAsync(buf, "");
  return gltf.scene;
}

function byName(root: Object3D): Map<string, Object3D> {
  const out = new Map<string, Object3D>();
  root.traverse((o) => {
    const n = (o.userData?.name as string | undefined) ?? o.name;
    if (n && !out.has(n)) out.set(n, o);
  });
  return out;
}

const hexNum = (hex: string) => parseInt(hex.slice(1), 16);
const lambert = (color: number, side: typeof FrontSide | typeof DoubleSide, opacity = 1) =>
  new MeshLambertMaterial({ color, side, transparent: opacity < 1, opacity, depthWrite: opacity >= 1 });

function label(text: string, cls: string): CSS2DObject {
  const div = document.createElement("div");
  div.className = cls;
  div.textContent = text;
  return new CSS2DObject(div);
}

function ringTexture(color: string): CanvasTexture {
  const c = document.createElement("canvas");
  c.width = c.height = 128;
  const g = c.getContext("2d")!;
  g.strokeStyle = color;
  g.lineWidth = 8;
  g.beginPath();
  g.arc(64, 64, 58, 0, Math.PI * 2);
  g.stroke();
  return new CanvasTexture(c);
}

function colorizeDisp(mesh: Mesh, max: number | null) {
  const g = mesh.geometry as BufferGeometry;
  // 형상 미리보기 FE = `_DISP_MM`(노드 이동), 조립 매칭 검사 = `_DIST_MM`(노드 → CAD 경계 거리, asm-match.md §4.3 10)
  const d = g.getAttribute("_disp_mm") ?? g.getAttribute("_dist_mm");
  if (!d) return false;
  const vals = new Float32Array(d.count);
  for (let i = 0; i < d.count; i++) vals[i] = d.getX(i);
  const top = max != null && max > 0 ? max : Math.max(1e-9, ...vals);
  g.setAttribute("color", new BufferAttribute(fillColors(vals, 0, top, new Float32Array(d.count * 3), true), 3));
  return true;
}

// ---------------------------------------------------------------- 형상 뷰

export interface GeomSceneApi {
  setNominal(buf: ArrayBuffer, m: ViewManifest): Promise<void>;
  /** 미리보기 겹쳐 보기(null = 공칭만). kind=fe면 FE 메시(요소 엣지 + 노드 변위 색) */
  setOverlay(buf: ArrayBuffer | null, kind: "shape" | "fe", dispMax: number | null): Promise<void>;
  setHighlight(h: Highlight): void;
  setBodyVisible(body: string, on: boolean): void;
  setFixed(show: boolean, clusters: FixedCluster[], red: Set<string>): void;
  /** label = 항상 보이는 글자, title = 포인터를 올리면 뜨는 툴팁(예: 노드 id) */
  setPoints(points: { xyz: Vec3; label: string; title?: string }[]): void;
  fit(): void;
  dispose(): void;
}

export function createGeomScene(container: HTMLElement, opts: { onPick: (hit: { body: string; face: number } | null, additive?: boolean) => void; onLost: () => void }): GeomSceneApi {
  const st = new Stage(container, opts.onLost);
  const root = new Group();
  const overlayRoot = new Group();
  const dimRoot = new Group();
  const fixedRoot = new Group();
  const pointRoot = new Group();
  st.scene.add(root, overlayRoot, dimRoot, fixedRoot, pointRoot);
  let manifest: ViewManifest | null = null;
  let side: typeof FrontSide | typeof DoubleSide = FrontSide;
  const bodies = new Map<string, { mesh: Mesh | null; edges: Object3D | null; fixed: Object3D | null }>();
  const overlayBodies = new Map<string, Object3D[]>();
  const hidden = new Set<string>();
  let mats: MeshLambertMaterial[] = [];
  let ghost: MeshLambertMaterial[] = [];
  let highlight: Highlight | null = null;
  let overlayKind: "shape" | "fe" | null = null;
  const ray = new Raycaster();

  const applyGroups = () => {
    if (!manifest) return;
    for (const b of manifest.bodies) {
      const mesh = bodies.get(b.body)?.mesh;
      if (!mesh) continue;
      const g = mesh.geometry as BufferGeometry;
      g.clearGroups();
      const groups = faceGroups(b, overlayKind ? { moving: new Set(), fixed: new Set(), red: new Set(), dims: [] } : highlight ?? { moving: new Set(), fixed: new Set(), red: new Set(), dims: [] });
      if (!groups.length) g.addGroup(0, Infinity, 0);
      for (const x of groups) g.addGroup(x.start, x.count, x.mat);
      mesh.material = overlayKind ? ghost : mats;
    }
    st.request();
  };

  const applyVisible = () => {
    for (const [name, b] of bodies) for (const o of [b.mesh, b.edges]) if (o) o.visible = !hidden.has(name);
    for (const [name, list] of overlayBodies) for (const o of list) o.visible = !hidden.has(name);
    st.request();
  };

  // 점 툴팁: 포인터 가까이(8px)의 점 title을 보인다(점이 많아도 DOM 요소는 1개)
  let pts: { xyz: Vec3; title: string }[] = [];
  const tip = document.createElement("div");
  tip.className = "gv-pt-tip";
  tip.hidden = true;
  container.appendChild(tip);
  const probe = new Vector3();
  const hover = (e: PointerEvent) => {
    if (!pts.length) return;
    const r = st.renderer.domElement.getBoundingClientRect();
    const mx = e.clientX - r.left;
    const my = e.clientY - r.top;
    const screen = pts.map((p) => {
      probe.set(...p.xyz).project(st.camera);
      return { x: ((probe.x + 1) / 2) * r.width, y: ((1 - probe.y) / 2) * r.height, ok: probe.z < 1 };
    });
    const i = nearestScreenPoint(screen, mx, my, 8);
    tip.hidden = i < 0;
    if (i >= 0) {
      tip.textContent = pts[i].title;
      tip.style.left = `${mx + 12}px`;
      tip.style.top = `${my + 12}px`;
    }
  };
  st.renderer.domElement.addEventListener("pointermove", hover);
  st.renderer.domElement.addEventListener("pointerleave", () => (tip.hidden = true));

  st.onClick((ndc, additive) => {
    if (overlayKind === "fe") return;
    ray.setFromCamera(ndc, st.camera);
    const targets: Object3D[] = [];
    if (overlayKind === "shape") overlayBodies.forEach((l, n) => !hidden.has(n) && l.forEach((o) => o instanceof Mesh && targets.push(o)));
    else bodies.forEach((b, n) => b.mesh && !hidden.has(n) && targets.push(b.mesh));
    const hit = ray.intersectObjects(targets, false)[0];
    if (!hit || hit.faceIndex == null) return opts.onPick(null, additive);
    const mesh = hit.object as Mesh;
    const g = mesh.geometry as BufferGeometry;
    const fid = g.getAttribute("_face_id");
    if (!fid) return opts.onPick(null, additive);
    const v = g.index ? g.index.getX(hit.faceIndex * 3) : hit.faceIndex * 3;
    opts.onPick({ body: String(mesh.userData?.name ?? mesh.name), face: fid.getX(v) }, additive);
  });

  return {
    async setNominal(buf, m) {
      manifest = m;
      side = m.kind === "shell" ? DoubleSide : FrontSide;
      mats = [lambert(COLORS.base, side), lambert(COLORS.moving, side), lambert(COLORS.fixed, side), lambert(COLORS.red, side), lambert(COLORS.ghost, side, 0.25), ...SELECTION_COLORS.map((c) => lambert(hexNum(c), side)), ...SELECTION_COLORS.map((c) => lambert(hexNum(lightColor(c)), side))];
      ghost = mats.map(() => {
        const g = lambert(COLORS.ghost, side, 0.25);
        g.polygonOffset = true; // 겹치는 면은 변경 형상이 보이도록 공칭을 뒤로
        g.polygonOffsetFactor = 2;
        g.polygonOffsetUnits = 2;
        return g;
      });
      disposeTree(root);
      root.clear();
      bodies.clear();
      const obj = await parseGlb(buf);
      root.add(obj);
      const names = byName(obj);
      for (const b of m.bodies) {
        const mesh = names.get(b.node) as Mesh | undefined;
        const edges = names.get(b.edges_node ?? `${b.body}.edges`) ?? null;
        const fixed = names.get(`${b.body}.fixed`) ?? null;
        if (edges instanceof LineSegments) edges.material = new LineBasicMaterial({ color: COLORS.edge, transparent: true, opacity: 0.55 });
        if (fixed) fixed.visible = false;
        bodies.set(b.body, { mesh: mesh instanceof Mesh ? mesh : null, edges, fixed });
      }
      applyGroups();
      applyVisible();
      st.fitTo([root]);
    },
    async setOverlay(buf, kind, max) {
      disposeTree(overlayRoot);
      overlayRoot.clear();
      overlayBodies.clear();
      overlayKind = buf ? kind : null;
      if (buf) {
        const obj = await parseGlb(buf);
        overlayRoot.add(obj);
        obj.traverse((o) => {
          const n = String(o.userData?.name ?? o.name);
          const body = n.replace(/\.(edges|fixed)$/, "");
          if (o instanceof Mesh) {
            const colored = colorizeDisp(o, max);
            o.material = new MeshLambertMaterial({ color: colored ? 0xffffff : COLORS.base, vertexColors: colored, side });
          } else if (o instanceof LineSegments) {
            o.material = new LineBasicMaterial({ color: COLORS.edge, transparent: true, opacity: kind === "fe" ? 0.35 : 0.55 });
          } else if (o instanceof Points) {
            o.visible = false;
          } else return;
          overlayBodies.set(body, [...(overlayBodies.get(body) ?? []), o]);
        });
      }
      applyGroups();
      applyVisible();
    },
    setHighlight(h) {
      highlight = h;
      applyGroups();
      disposeTree(dimRoot);
      dimRoot.clear();
      if (!h.dims.length) return st.request();
      const pos: number[] = [];
      const ends: number[] = [];
      h.dims.forEach((d: DimDraw) => {
        pos.push(...d.line[0], ...d.line[1]);
        ends.push(...d.line[0], ...d.line[1]);
        const l = label(d.text, "gv-dim-label");
        l.position.set(...d.label);
        dimRoot.add(l);
      });
      const lg = new BufferGeometry();
      lg.setAttribute("position", new BufferAttribute(new Float32Array(pos), 3));
      const line = new LineSegments(lg, new LineBasicMaterial({ color: COLORS.dim, depthTest: false }));
      line.renderOrder = 10;
      const pg = new BufferGeometry();
      pg.setAttribute("position", new BufferAttribute(new Float32Array(ends), 3));
      const pts = new Points(pg, new PointsMaterial({ color: COLORS.dim, size: 7, sizeAttenuation: false, depthTest: false }));
      pts.renderOrder = 10;
      dimRoot.add(line, pts);
      st.request();
    },
    setBodyVisible(body, on) {
      if (on) hidden.delete(body);
      else hidden.add(body);
      applyVisible();
    },
    setFixed(show, clusters, red) {
      disposeTree(fixedRoot);
      fixedRoot.clear();
      for (const b of bodies.values()) {
        const p = b.fixed;
        if (!(p instanceof Points)) continue;
        p.visible = show;
        const g = p.geometry as BufferGeometry;
        const cid = g.getAttribute("_cluster_id");
        const col = new Float32Array(g.getAttribute("position").count * 3);
        const blue = new Color(COLORS.fixed);
        const r = new Color(COLORS.red);
        for (let i = 0; i < col.length / 3; i++) (cid && red.has(String(cid.getX(i))) ? r : blue).toArray(col, i * 3);
        g.setAttribute("color", new BufferAttribute(col, 3));
        p.material = new PointsMaterial({ size: 4, sizeAttenuation: false, vertexColors: true, depthTest: false });
        p.renderOrder = 5;
      }
      if (show) {
        const tex = { blue: ringTexture("#3c6edc"), red: ringTexture("#e5484d") };
        for (const c of clusters) {
          const isRed = red.has(String(c.id));
          const s = new Sprite(new SpriteMaterial({ map: isRed ? tex.red : tex.blue, depthTest: false, transparent: true }));
          s.position.set(...c.center);
          const d = Math.max(c.radius_mm * 2, 1);
          s.scale.set(d, d, 1);
          s.renderOrder = 6;
          fixedRoot.add(s);
        }
      }
      st.request();
    },
    setPoints(points) {
      disposeTree(pointRoot);
      pointRoot.clear();
      pts = points.filter((x) => x.title).map((x) => ({ xyz: x.xyz, title: x.title as string }));
      tip.hidden = true;
      if (points.length) {
        const g = new BufferGeometry();
        g.setAttribute("position", new BufferAttribute(new Float32Array(points.flatMap((p) => p.xyz)), 3));
        const p = new Points(g, new PointsMaterial({ color: COLORS.red, size: points.length > 100 ? 5 : 9, sizeAttenuation: false, depthTest: false }));
        p.renderOrder = 11;
        pointRoot.add(p);
        for (const x of points) {
          if (!x.label) continue;
          const l = label(x.label, "gv-dim-label bad");
          l.position.set(...x.xyz);
          pointRoot.add(l);
        }
      }
      st.request();
    },
    fit() {
      st.fitTo([root, overlayRoot]);
    },
    dispose() {
      tip.remove();
      st.dispose();
    },
  };
}

// ---------------------------------------------------------------- 결과 컨투어

export type ContourLevel = "lod" | "full";
export interface ContourMeshInfo {
  nodes: number;
  /** 변형 전 위치(float32 mm) */
  base: Float32Array;
  nodeIds: Uint32Array | null;
  /** LOD 메시의 원 정점 번호(`_SRC`) — 전체 메시는 null */
  src: Uint32Array | null;
}
/** 극값 마커: 변형 반영 위치(mm) */
export interface ContourMarker {
  kind: "max" | "min";
  pos: Vec3;
}
export interface ContourPick {
  level: ContourLevel;
  /** 그 메시의 정점 번호(LOD면 `_SRC`로 전체 번호) */
  vertex: number;
  /** 컨테이너 안 클릭 위치(px) */
  x: number;
  y: number;
}

export interface ContourSceneApi {
  /** level = 전체(기본) 또는 LOD. 처음 올린 메시가 보이고, 카메라는 처음 한 번만 맞춘다(전환해도 유지) */
  setMesh(buf: ArrayBuffer, level?: ContourLevel): Promise<ContourMeshInfo>;
  /** 보일 메시(올라와 있지 않으면 있는 쪽) */
  setLevel(level: ContourLevel): void;
  setColors(colors: Float32Array, level?: ContourLevel): void;
  setPositions(pos: Float32Array, level?: ContourLevel): void;
  /** 화면 크기가 고정된 극값 마커(빈 목록 = 숨김) */
  setMarkers(markers: ContourMarker[]): void;
  setLoop(on: boolean): void;
  fit(): void;
  /** 비교 모드(contour3d-default §3.1): 시점 연결·두 메시 bbox 합집합 맞춤 */
  getCamera(): CameraState;
  setCamera(s: CameraState): void;
  /** 사용자가 돌리거나 확대할 때만 호출(setCamera로 바뀐 것은 부르지 않는다). 해제 함수를 돌려준다 */
  onCameraChange(cb: (s: CameraState) => void): () => void;
  /** 조작 시작·끝(휠 포함) = start·end, 다른 쪽이 시점을 연결해 움직였을 때 = pulse(LOD 전환용) */
  onInteract(cb: (e: "start" | "end" | "pulse") => void): () => void;
  /** 클릭(이동 4px 미만)한 곳에서 가장 가까운 정점(없으면 null) */
  onPick(cb: (hit: ContourPick | null) => void): () => void;
  getBox(): BoxState | null;
  fitBox(box: BoxState): void;
  dispose(): void;
}

export function createContourScene(container: HTMLElement, opts: { onLost: () => void }): ContourSceneApi {
  const st = new Stage(container, opts.onLost);
  const root = new Group();
  const markerRoot = new Group();
  st.scene.add(root, markerRoot);
  const meshes: Partial<Record<ContourLevel, Mesh>> = {};
  const infos: Partial<Record<ContourLevel, ContourMeshInfo>> = {};
  let want: ContourLevel | null = null;
  const listeners = new Set<(s: CameraState) => void>();
  const interact = new Set<(e: "start" | "end" | "pulse") => void>();
  const picks = new Set<(h: ContourPick | null) => void>();
  let applying = false;
  const cam = (): CameraState => ({
    position: st.camera.position.toArray() as [number, number, number],
    target: st.controls.target.toArray() as [number, number, number],
    up: st.camera.up.toArray() as [number, number, number],
    zoom: st.camera.zoom,
  });
  st.controls.addEventListener("change", () => {
    if (applying || !listeners.size) return;
    const s = cam();
    listeners.forEach((f) => f(s));
  });
  st.controls.addEventListener("start", () => interact.forEach((f) => f("start")));
  st.controls.addEventListener("end", () => interact.forEach((f) => f("end")));
  const shown = (): ContourLevel | null => (want && meshes[want] ? want : meshes.full ? "full" : meshes.lod ? "lod" : null);
  const applyLevel = () => {
    const l = shown();
    for (const k of ["lod", "full"] as const) {
      const m = meshes[k];
      if (m) m.visible = k === l;
    }
    st.request();
  };
  const attr = (level: ContourLevel, name: "color" | "position") => meshes[level]?.geometry.getAttribute(name) as BufferAttribute | undefined;

  // 극값 마커: 화면 크기 고정(sizeAttenuation=false) 링 — 깊이 검사 없이 늘 보인다
  const tex = { max: ringTexture("#e5484d"), min: ringTexture("#3c6edc") };
  const sprites = (["max", "min"] as const).map((k) => {
    const sp = new Sprite(new SpriteMaterial({ map: tex[k], depthTest: false, transparent: true, sizeAttenuation: false }));
    sp.scale.set(0.045, 0.045, 1);
    sp.renderOrder = 10;
    sp.visible = false;
    sp.userData.kind = k;
    markerRoot.add(sp);
    return sp;
  });

  const ray = new Raycaster();
  st.onClick((ndc) => {
    const l = shown();
    const m = l ? meshes[l] : null;
    if (!l || !m) return;
    ray.setFromCamera(ndc, st.camera);
    const hit = ray.intersectObject(m, false)[0];
    const x = ((ndc.x + 1) / 2) * st.container.clientWidth;
    const y = ((1 - ndc.y) / 2) * st.container.clientHeight;
    if (!hit || !hit.face) return picks.forEach((f) => f(null));
    const pos = (m.geometry as BufferGeometry).getAttribute("position");
    let best = hit.face.a;
    let bd = Infinity;
    for (const v of [hit.face.a, hit.face.b, hit.face.c]) {
      const d = hit.point.distanceToSquared(new Vector3(pos.getX(v), pos.getY(v), pos.getZ(v)));
      if (d < bd) {
        bd = d;
        best = v;
      }
    }
    picks.forEach((f) => f({ level: l, vertex: best, x, y }));
  });

  return {
    async setMesh(buf, level = "full") {
      const r = await loadContourGlb(buf);
      const first = !meshes.full && !meshes.lod;
      const old = meshes[level];
      if (old) {
        root.remove(old);
        old.geometry.dispose();
        (old.material as Material).dispose();
      }
      r.geometry.setAttribute("color", new BufferAttribute(new Float32Array(r.nodes * 3).fill(0.6), 3));
      const mesh = new Mesh(r.geometry, new MeshLambertMaterial({ vertexColors: true, side: DoubleSide }));
      mesh.frustumCulled = false; // 변형으로 위치가 바뀐다
      meshes[level] = mesh;
      infos[level] = { nodes: r.nodes, base: r.base, nodeIds: r.nodeIds, src: r.src };
      root.add(mesh);
      if (first) want = level;
      applyLevel();
      if (first) st.fitTo([root]);
      return infos[level]!;
    },
    setLevel(level) {
      want = level;
      applyLevel();
    },
    setColors(colors, level = "full") {
      const a = attr(level, "color");
      if (!a) return;
      (a.array as Float32Array).set(colors.subarray(0, a.array.length));
      a.needsUpdate = true;
      if (shown() === level) st.request();
    },
    setPositions(pos, level = "full") {
      const a = attr(level, "position");
      const g = meshes[level]?.geometry;
      if (!g || !a) return;
      (a.array as Float32Array).set(pos.subarray(0, a.array.length));
      a.needsUpdate = true;
      g.boundingBox = null;
      g.computeBoundingSphere();
      if (shown() === level) st.request();
    },
    setMarkers(markers) {
      for (const sp of sprites) {
        const mk = markers.find((x) => x.kind === sp.userData.kind);
        sp.visible = !!mk;
        if (mk) sp.position.set(...mk.pos);
      }
      st.request();
    },
    setLoop(on) {
      st.setLoop(on);
    },
    fit() {
      st.fitTo([root]);
    },
    getCamera: cam,
    setCamera(s) {
      applying = true;
      try {
        st.camera.position.fromArray(s.position);
        st.camera.up.fromArray(s.up);
        st.camera.zoom = s.zoom;
        st.camera.updateProjectionMatrix();
        st.controls.target.fromArray(s.target);
        st.controls.update();
      } finally {
        applying = false;
      }
      interact.forEach((f) => f("pulse"));
      st.request();
    },
    onCameraChange(cb) {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    onInteract(cb) {
      interact.add(cb);
      return () => interact.delete(cb);
    },
    onPick(cb) {
      picks.add(cb);
      return () => picks.delete(cb);
    },
    getBox() {
      const b = new Box3();
      const l = shown();
      const m = l ? meshes[l] : null;
      if (m) b.expandByObject(m);
      return b.isEmpty() ? null : { min: b.min.toArray() as Vec3, max: b.max.toArray() as Vec3 };
    },
    fitBox(b) {
      st.fitBox(new Box3(new Vector3(...b.min), new Vector3(...b.max)));
    },
    dispose() {
      listeners.clear();
      interact.clear();
      picks.clear();
      st.dispose();
    },
  };
}
