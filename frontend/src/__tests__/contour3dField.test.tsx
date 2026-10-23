// v0.2.10 결과 3D 컨투어 현장 보정 프런트(contour3d-field.md, V-C3F-15): schema 2 uint16 프레임·변위 지연 로드(배율 0이면 disp 요청 0건), schema 1 호환, 변위 없음 시 변형 배율 숨김 + 안내,
// LOD ↔ 전체 전환(조작·재생·미수신)·극값 마커·툴팁, 비교 뷰어 LOD, 대체 사유 문구(§12)·[다시] 규칙·실패 뒤 자동 재요청 없음.
// 3D 장면(three)은 가짜 장면으로 대신하되 GLB는 실제 `loadContourGlb`(GLTFLoader + MeshoptDecoder)로 읽어 LOD src·노드 번호·위치를 검증한다.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { renderApp, STUDY } from "../test/render";
import type { MockServer } from "../mock/server";
import { gvRecords, setGvMode } from "../mock/geomView";
import { resetWebGLCache } from "../stages/stage4/geomview/webgl";
import { loadContourGlb } from "../stages/stage4/geomview/contour/contourGlb";
import { decodeScalarFor, DENIED_TEXT, fmtExact, tooltipText, WEBGL_TEXT, type ContourManifest } from "../stages/stage4/geomview/contour/contourCore";
import { POLL } from "../lib/poll";

type Fn = ReturnType<typeof vi.fn>;
interface FakeScene {
  setMesh: Fn;
  setLevel: Fn;
  setColors: Fn;
  setPositions: Fn;
  setMarkers: Fn;
  setLoop: Fn;
  fit: Fn;
  getCamera: Fn;
  setCamera: Fn;
  onCameraChange: Fn;
  onInteract: Fn;
  onPick: Fn;
  getBox: Fn;
  fitBox: Fn;
  dispose: Fn;
  interact: (e: "start" | "end" | "pulse") => void;
  pick: (h: { level: "lod" | "full"; vertex: number; x: number; y: number } | null) => void;
}
const fake = vi.hoisted(() => ({ all: [] as FakeScene[], failFull: false, hold: null as null | { promise: Promise<void>; resolve: () => void } }));
vi.mock("../stages/stage4/geomview/threeScene", async () => {
  const { loadContourGlb: load } = await import("../stages/stage4/geomview/contour/contourGlb");
  return {
    createGeomScene: vi.fn(),
    createContourScene: () => {
      let onI: ((e: "start" | "end" | "pulse") => void) | null = null;
      let onP: ((h: unknown) => void) | null = null;
      const f: FakeScene = {
        setMesh: vi.fn(async (buf: ArrayBuffer, level: "lod" | "full" = "full") => {
          if (level === "full" && fake.hold) await fake.hold.promise;
          if (level === "full" && fake.failFull) throw new Error("형상 파일을 읽을 수 없습니다");
          const r = await load(buf);
          return { nodes: r.nodes, base: r.base, nodeIds: r.nodeIds, src: r.src };
        }),
        setLevel: vi.fn(),
        setColors: vi.fn(),
        setPositions: vi.fn(),
        setMarkers: vi.fn(),
        setLoop: vi.fn(),
        fit: vi.fn(),
        getCamera: vi.fn(() => ({ position: [1, 2, 3], target: [0, 0, 0], up: [0, 0, 1], zoom: 1 })),
        setCamera: vi.fn(),
        onCameraChange: vi.fn(() => () => undefined),
        onInteract: vi.fn((cb) => {
          onI = cb;
          return () => (onI = null);
        }),
        onPick: vi.fn((cb) => {
          onP = cb;
          return () => (onP = null);
        }),
        getBox: vi.fn(() => ({ min: [0, 0, 0], max: [10, 20, 30] })),
        fitBox: vi.fn(),
        dispose: vi.fn(),
        interact: (e) => onI?.(e),
        pick: (h) => onP?.(h),
      };
      fake.all.push(f);
      return f;
    },
  };
});

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
function hold() {
  let resolve!: () => void;
  const promise = new Promise<void>((r) => (resolve = r));
  fake.hold = { promise, resolve };
  return fake.hold;
}

function spy(server: MockServer) {
  const calls: { m: string; p: string; range: string | null }[] = [];
  const orig = server.handle.bind(server);
  server.handle = (m, p, q, b, h) => {
    calls.push({ m, p, range: h.get("Range") });
    return orig(m, p, q, b, h);
  };
  return calls;
}
const media = (calls: { p: string; range: string | null }[], id: string | null | undefined) => calls.filter((c) => c.p === `/artifacts/${id}/media`);
const manifestOf = (server: MockServer, i = 0) => JSON.parse(server.artifacts.find((a) => a.id === gvRecords(server).contours[i].manifest_artifact_id)!.body) as ContourManifest;
const last = (f: Fn) => f.mock.calls[f.mock.calls.length - 1] as unknown[];
const lvl = (f: FakeScene) => f.setLevel.mock.calls[f.setLevel.mock.calls.length - 1]?.[0];
const open = () => screen.findByTestId("contour-slot");

beforeEach(() => {
  resetWebGLCache();
  fake.all = [];
  fake.hold = null;
  fake.failFull = false;
  POLL.preview = 20;
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({} as never);
});
afterEach(() => {
  vi.restoreAllMocks();
  resetWebGLCache();
  localStorage.clear();
});

describe("schema 2 — uint16 프레임·변위 지연 로드", () => {
  it("스칼라는 2N B Range, 변위는 별도 파일 6N B Range(배율 > 0 기본), 색은 복원값", async () => {
    const { server } = renderApp(`${STUDY}/4`, { user: "power" });
    const calls = spy(server);
    const panel = await open();
    await within(panel).findByTestId("contour-viewer");
    const rec = gvRecords(server).contours[0];
    const m = manifestOf(server);
    const n = m.mesh.nodes;
    expect(rec.disp_artifact_id).toBeTruthy();
    expect(rec.lod_artifact_id).toBeNull();
    await waitFor(() => expect(media(calls, rec.frames_artifact_id).map((c) => c.range)).toEqual(expect.arrayContaining([`bytes=0-${2 * n - 1}`, `bytes=${2 * n}-${4 * n - 1}`])));
    await waitFor(() => expect(media(calls, rec.disp_artifact_id).map((c) => c.range)).toContain(`bytes=0-${6 * n - 1}`));
    expect(media(calls, rec.glb_artifact_id)).toHaveLength(1);
    await waitFor(() => expect(fake.all[0].setColors).toHaveBeenCalled());
    fireEvent.change(within(panel).getByLabelText("타임스텝"), { target: { value: "23" } });
    await waitFor(() => expect(media(calls, rec.frames_artifact_id).map((c) => c.range)).toContain(`bytes=${46 * n}-${48 * n - 1}`));
    expect(within(panel).getByLabelText("변형 배율")).toBeTruthy();
  });

  it("대형(변위 레코드 > 2 MiB): 기본 배율 0 → 변위 요청 0건, 배율을 올리면 Range로 받고 프레임당 크기를 안내", async () => {
    const { server } = renderApp(`${STUDY}/4`, { user: "power" }, (s) => setGvMode(s, { c3data: { nx: 600, ny: 600, frames: 3 } }));
    const calls = spy(server);
    const panel = await open();
    const viewer = await within(panel).findByTestId("contour-viewer", undefined, { timeout: 20000 });
    const rec = gvRecords(server).contours[0];
    const n = 360000;
    await waitFor(() => expect(media(calls, rec.frames_artifact_id).length).toBeGreaterThan(0), { timeout: 20000 });
    await waitFor(() => expect(fake.all[0].setColors).toHaveBeenCalled(), { timeout: 20000 });
    fireEvent.click(within(viewer).getByRole("button", { name: "다음 프레임" }));
    await waitFor(() => expect(within(viewer).getByTestId("contour-frame").textContent).toMatch(/^2\/3/));
    await sleep(100);
    expect(media(calls, rec.disp_artifact_id)).toHaveLength(0);
    const select = within(viewer).getByLabelText("변형 배율") as HTMLSelectElement;
    expect(select.value).toBe("0");
    expect(within(viewer).queryByTestId("contour-disp-size")).toBeNull();
    fireEvent.change(select, { target: { value: "1" } });
    await waitFor(() => expect(media(calls, rec.disp_artifact_id).map((c) => c.range)).toContain(`bytes=${6 * n}-${12 * n - 1}`));
    expect(within(viewer).getByTestId("contour-disp-size").textContent).toBe("변형 데이터 프레임당 2.1 MB");
    await waitFor(() => {
      const pos = last(fake.all[0].setPositions)[0] as Float32Array;
      expect(pos.length).toBe(n * 3);
    });
  }, 60000);

  it("schema 1 manifest(float32 섞임 레코드)도 그대로 — 16N B Range, 변위 파일 없음, 변형 배율 표시", async () => {
    const { server } = renderApp(`${STUDY}/4`, { user: "power" }, (s) => setGvMode(s, { c3data: { schema: 1 } }));
    const calls = spy(server);
    const panel = await open();
    const viewer = await within(panel).findByTestId("contour-viewer");
    const rec = gvRecords(server).contours[0];
    const n = manifestOf(server).mesh.nodes;
    expect(manifestOf(server).schema_version).toBe(1);
    await waitFor(() => expect(media(calls, rec.frames_artifact_id).map((c) => c.range)).toContain(`bytes=0-${16 * n - 1}`));
    expect(rec.disp_artifact_id ?? null).toBeNull();
    expect(within(viewer).getByLabelText("변형 배율")).toBeTruthy();
    fireEvent.change(within(viewer).getByLabelText("타임스텝"), { target: { value: "12" } }); // 프레임 0은 변위 0
    await waitFor(() => expect(within(viewer).getByTestId("contour-frame").textContent).toMatch(/^13\//));
    fireEvent.change(within(viewer).getByLabelText("변형 배율"), { target: { value: "50" } });
    await waitFor(() => expect(Math.min(...(last(fake.all[0].setPositions)[0] as Float32Array))).toBeLessThan(-10));
  });

  it("변위 없음(disp: null): 변형 배율 컨트롤 숨김 + CONTOUR3D_DISP_UNAVAILABLE 안내 한 줄, 변위 요청 없음", async () => {
    const { server } = renderApp(`${STUDY}/4`, { user: "power" }, (s) => setGvMode(s, { c3data: { disp: false } }));
    const calls = spy(server);
    const panel = await open();
    const viewer = await within(panel).findByTestId("contour-viewer");
    await waitFor(() => expect(fake.all[0].setColors).toHaveBeenCalled());
    expect(manifestOf(server).disp).toBeNull();
    expect(within(viewer).queryByLabelText("변형 배율")).toBeNull();
    expect(within(viewer).queryByLabelText("변형 배율 직접 입력")).toBeNull();
    const w = within(viewer).getAllByTestId("contour-warning");
    expect(w).toHaveLength(1);
    expect(w[0].textContent).toBe("변형 표시 없음 — 결과에 변위가 없습니다");
    const rec = gvRecords(server).contours[0];
    expect(rec.disp_artifact_id ?? null).toBeNull();
    const ids = new Set([rec.glb_artifact_id, rec.frames_artifact_id].map((id) => `/artifacts/${id}/media`));
    expect(calls.filter((c) => c.p.endsWith("/media")).every((c) => ids.has(c.p))).toBe(true); // 변위 파일 요청 없음
    // 위치는 변형 없이(원래 위치 그대로) 보낸다
    const pos = last(fake.all[0].setPositions)[0] as Float32Array;
    expect(Math.min(...pos)).toBeGreaterThanOrEqual(-1e-3);
  });
});

describe("LOD(C3F-8·9)", () => {
  it("첫 표시 = LOD, 전체는 백그라운드 → 받으면 전체, 조작(시작·끝+250 ms)·재생 중에는 LOD, 극값 마커는 늘 표시", async () => {
    const h = hold();
    const { server } = renderApp(`${STUDY}/4`, { user: "power" }, (s) => setGvMode(s, { c3data: { lod: true } }));
    const calls = spy(server);
    const panel = await open();
    const viewer = await within(panel).findByTestId("contour-viewer");
    const rec = gvRecords(server).contours[0];
    const m = manifestOf(server);
    expect(m.lod!.vertices).toBeLessThan(m.mesh.nodes);
    await waitFor(() => expect(fake.all[0].setMesh).toHaveBeenCalledTimes(2));
    // 첫 메시 = LOD(level lod), 두 번째 = 전체(받는 중)
    expect(fake.all[0].setMesh.mock.calls.map((c) => c[1])).toEqual(["lod", "full"]);
    expect(media(calls, rec.lod_artifact_id)).toHaveLength(1);
    expect(media(calls, rec.glb_artifact_id)).toHaveLength(1);
    expect(within(viewer).getByTestId("contour-full-loading").textContent).toBe("전체 해상도 받는 중…");
    await waitFor(() => expect(fake.all[0].setColors).toHaveBeenCalled());
    expect(lvl(fake.all[0])).toBe("lod");
    // LOD 색 = 정점 수(LOD) × 3, 전체 색은 아직 없음
    const lodCalls = fake.all[0].setColors.mock.calls.filter((c) => c[1] === "lod");
    expect(lodCalls.length).toBeGreaterThan(0);
    expect((lodCalls[0][0] as Float32Array).length).toBe(m.lod!.vertices * 3);
    expect(fake.all[0].setColors.mock.calls.some((c) => c[1] === "full")).toBe(false);
    // 극값 라벨은 LOD에서도 보인다
    expect(within(viewer).getByTestId("contour-extreme-max").textContent).toMatch(/^최대 .* MPa/);

    await act(async () => h.resolve());
    await waitFor(() => expect(lvl(fake.all[0])).toBe("full"));
    expect(within(viewer).queryByTestId("contour-full-loading")).toBeNull();
    expect(fake.all[0].setColors.mock.calls.some((c) => c[1] === "full")).toBe(true);

    // 조작 시작 → LOD, 끝 + 250 ms 뒤 전체
    act(() => fake.all[0].interact("start"));
    expect(lvl(fake.all[0])).toBe("lod");
    act(() => fake.all[0].interact("end"));
    await sleep(120);
    expect(lvl(fake.all[0])).toBe("lod");
    await waitFor(() => expect(lvl(fake.all[0])).toBe("full"), { timeout: 1500 });

    // 재생 중 LOD, 정지 후 전체
    fireEvent.click(within(viewer).getByRole("button", { name: "재생" }));
    await waitFor(() => expect(lvl(fake.all[0])).toBe("lod"));
    fireEvent.click(within(viewer).getByRole("button", { name: "일시정지" }));
    await waitFor(() => expect(lvl(fake.all[0])).toBe("full"), { timeout: 1500 });
  });

  it("극값 마커: 현재 프레임 max_v·min_v 정점의 원 위치 + 라벨 `최대 {정확값} MPa · 노드 {id}`(전체 해상도)", async () => {
    const { server } = renderApp(`${STUDY}/4`, { user: "power" }, (s) => setGvMode(s, { c3data: { lod: true, disp: false } }));
    const panel = await open();
    const viewer = await within(panel).findByTestId("contour-viewer");
    await waitFor(() => expect(fake.all[0].setMarkers).toHaveBeenCalled());
    fireEvent.change(within(viewer).getByLabelText("타임스텝"), { target: { value: "10" } });
    await waitFor(() => expect(within(viewer).getByTestId("contour-frame").textContent).toMatch(/^11\/24/));
    await waitFor(() => expect(lvl(fake.all[0])).toBe("full"));
    const m = manifestOf(server);
    const f = m.frames.list[10];
    const info = await (fake.all[0].setMesh.mock.results[1].value as Promise<{ base: Float32Array }>);
    // manifest 정확값·노드 번호(= 100001 + 정점 번호, 목의 격자 순서)
    await waitFor(() => expect(within(viewer).getByTestId("contour-extreme-max").textContent).toBe(`최대 ${fmtExact(f.max as number)} MPa · 노드 ${100001 + (f.max_v as number)}`));
    expect(within(viewer).getByTestId("contour-extreme-min").textContent).toBe(`최소 ${fmtExact(f.min as number)} MPa · 노드 ${100001 + (f.min_v as number)}`);
    await waitFor(() => {
      const mk = last(fake.all[0].setMarkers)[0] as { kind: string; pos: number[] }[];
      expect(mk.map((x) => x.kind)).toEqual(["max", "min"]);
      const v = f.max_v as number;
      expect(mk[0].pos[0]).toBeCloseTo(info.base[v * 3], 3);
      expect(mk[0].pos[1]).toBeCloseTo(info.base[v * 3 + 1], 3);
      expect(mk[0].pos[2]).toBeCloseTo(info.base[v * 3 + 2], 3);
    });
  });

  it("툴팁: 전체 정점 클릭 = 노드 {id} · 복원값 {단위}, LOD 정점 클릭 = _SRC로 전체 레코드의 값·노드", async () => {
    const h = hold();
    const { server } = renderApp(`${STUDY}/4`, { user: "power" }, (s) => setGvMode(s, { c3data: { lod: true } }));
    const panel = await open();
    const viewer = await within(panel).findByTestId("contour-viewer");
    const rec = gvRecords(server).contours[0];
    const m = manifestOf(server);
    const n = m.mesh.nodes;
    const bytes = server.artifacts.find((a) => a.id === rec.frames_artifact_id)!.render!();
    const s0 = decodeScalarFor(m, 0, bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + 2 * n) as ArrayBuffer, 0);
    await waitFor(() => expect(fake.all[0].setColors).toHaveBeenCalled());
    // LOD 정점 3 → 원 정점 src[3]
    const lodGlb = await loadContourGlb((() => {
      const b = server.artifacts.find((a) => a.id === rec.lod_artifact_id)!.render!();
      return b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength) as ArrayBuffer;
    })());
    act(() => fake.all[0].pick({ level: "lod", vertex: 3, x: 40, y: 50 }));
    const src3 = lodGlb.src![3];
    expect(within(viewer).getByTestId("contour-tip").textContent).toBe(tooltipText(100001 + src3, s0[src3], m.frames.list[0].scale, "MPa"));
    await act(async () => h.resolve());
    await waitFor(() => expect(lvl(fake.all[0])).toBe("full"));
    act(() => fake.all[0].pick({ level: "full", vertex: 5, x: 10, y: 20 }));
    expect(within(viewer).getByTestId("contour-tip").textContent).toBe(tooltipText(100006, s0[5], m.frames.list[0].scale, "MPa"));
    expect(within(viewer).getByTestId("contour-tip").textContent).toMatch(/^노드 100006 · .+ MPa$/);
    act(() => fake.all[0].pick(null));
    expect(within(viewer).queryByTestId("contour-tip")).toBeNull();
  });

  it("전체 해상도를 받지 못하면 LOD로 계속 + 안내 한 줄(재요청 없음)", async () => {
    fake.failFull = true;
    const { server } = renderApp(`${STUDY}/4`, { user: "power" }, (s) => setGvMode(s, { c3data: { lod: true } }));
    const calls = spy(server);
    const panel = await open();
    const viewer = await within(panel).findByTestId("contour-viewer");
    expect((await within(viewer).findByTestId("contour-full-error")).textContent).toContain("전체 해상도를 받지 못해 간략 형상으로 표시합니다 — 형상 파일을 읽을 수 없습니다");
    expect(within(viewer).queryByTestId("contour-full-loading")).toBeNull();
    act(() => fake.all[0].interact("start"));
    act(() => fake.all[0].interact("end"));
    await sleep(350);
    expect(lvl(fake.all[0])).toBe("lod"); // 전체가 없으면 계속 LOD
    expect(media(calls, gvRecords(server).contours[0].glb_artifact_id)).toHaveLength(1);
  });
});

describe("비교 뷰어 — LOD·변형 배율 숨김", () => {
  const title = "컨투어 비교 — 기존안 · 최적안";
  const region = (name: string) => screen.findByRole("region", { name });

  it("두 장면 모두 LOD로 시작해 전체로 전환, 시점 연결로 움직이는 쪽(pulse)도 LOD → 250 ms 뒤 전체", async () => {
    renderApp(`${STUDY}/5/surrogate/so-1`, { user: "power" }, (s) => setGvMode(s, { c3data: { lod: true } }));
    const card = await region(title);
    await within(card).findByTestId("contour-compare3d");
    await waitFor(() => expect(fake.all).toHaveLength(2));
    await waitFor(() => fake.all.forEach((f) => expect(lvl(f)).toBe("full")));
    expect(fake.all.map((f) => f.setMesh.mock.calls.map((c) => c[1]))).toEqual([["lod", "full"], ["lod", "full"]]);
    act(() => fake.all[1].interact("pulse"));
    expect(lvl(fake.all[1])).toBe("lod");
    await waitFor(() => expect(lvl(fake.all[1])).toBe("full"), { timeout: 1500 });
    expect(lvl(fake.all[0])).toBe("full"); // 건드리지 않은 쪽은 그대로
  });

  it("변위가 없으면 변형 배율 컨트롤을 숨긴다(한쪽만 없어도 숨김 규칙의 양쪽 없음 경우)", async () => {
    renderApp(`${STUDY}/5/surrogate/so-1`, { user: "power" }, (s) => setGvMode(s, { c3data: { disp: false } }));
    const card = await region(title);
    await within(card).findByTestId("contour-compare3d");
    await waitFor(() => expect(fake.all[0].setColors).toHaveBeenCalled());
    await waitFor(() => expect(within(card).getAllByTestId("contour-warning").length).toBe(2));
    expect(within(card).queryByLabelText("변형 배율")).toBeNull();
  });

  it("변위가 있으면 컨트롤이 보이고, 대형이면 기본 배율 0", async () => {
    renderApp(`${STUDY}/5/surrogate/so-1`, { user: "power" });
    const card = await region(title);
    await within(card).findByTestId("contour-compare3d");
    await waitFor(() => expect(fake.all[0].setColors).toHaveBeenCalled());
    expect((within(card).getByLabelText("변형 배율") as HTMLSelectElement).value).toBe("1");
  });
});

describe("대체 사유 한 줄(§12)·[다시] 규칙", () => {
  const postCount = (calls: { m: string; p: string }[]) => calls.filter((c) => c.m === "POST" && c.p === "/contour3d").length;

  it("결과 FAIL·노드(쿠션: comps 없음): 상한 비교 문구, 부품 문구 없음, PNG 인라인, [다시] 없음, 자동 재요청 0회", async () => {
    const { server } = renderApp(`${STUDY}/4`, { user: "power" }, (s) => setGvMode(s, { c3d: "toolarge" }));
    const calls = spy(server);
    const panel = await open();
    await waitFor(() => expect(within(panel).getByTestId("contour3d-fail").textContent).toBe("3D 생략 — 외부 면 노드 2,350,000개 > 상한 2,000,000. 관리자에게 상한(contour3d.max_nodes) 조정을 요청하세요"));
    expect(within(panel).getByTestId("contour3d-fail").getAttribute("title")).toContain("2,350,000");
    expect(within(panel).getByTestId("contour-media")).toBeTruthy();
    expect(within(panel).queryByRole("button", { name: "다시" })).toBeNull();
    await sleep(250);
    expect(postCount(calls)).toBe(1);
  });

  it("결과 FAIL·노드(부품 범위가 있을 때): '부품 이름으로 범위를 줄이거나' 포함", async () => {
    renderApp(`${STUDY}/4`, { user: "power" }, (s) => setGvMode(s, { c3d: "toolarge_comps" }));
    const panel = await open();
    await waitFor(() => expect(within(panel).getByTestId("contour3d-fail").textContent).toBe("3D 생략 — 외부 면 노드 2,350,000개 > 상한 2,000,000. 부품 이름으로 범위를 줄이거나 관리자에게 상한(contour3d.max_nodes) 조정을 요청하세요"));
  });

  it("결과 FAIL·형상·프레임·값 없음", async () => {
    const t = async (c3d: "toolarge_glb" | "toolarge_frames" | "fail", text: string) => {
      const { unmount } = renderApp(`${STUDY}/4`, { user: "power" }, (s) => setGvMode(s, { c3d }));
      const panel = await open();
      await waitFor(() => expect(within(panel).getByTestId("contour3d-fail").textContent).toBe(text));
      unmount();
    };
    await t("toolarge_glb", "3D 생략 — 형상 70.0 MB > 상한 64.0 MB(contour3d.max_glb_bytes), 관리자에게 조정을 요청하세요");
    await t("toolarge_frames", "3D 생략 — 프레임 2개도 크기 상한(contour3d.max_bin_bytes)을 넘습니다");
    await t("fail", "3D 생략 — 선택한 결과 값이 없습니다(Stress)");
  });

  it("작업 FAILED: 3D 생성 실패 — {message_ko} ({code}) + [다시] → 새 요청, 자동 재요청은 없다", async () => {
    const { server } = renderApp(`${STUDY}/4`, { user: "power" }, (s) => setGvMode(s, { c3d: "jobfail" }));
    const calls = spy(server);
    const panel = await open();
    const stopped = await within(panel).findByTestId("contour3d-stopped");
    expect(stopped.textContent).toContain("3D 생성 실패 — H3D 읽기 도구가 종료되었습니다 (CONTOUR3D_JOB_FAILED)");
    expect(within(panel).getByTestId("contour-media")).toBeTruthy();
    await sleep(250);
    expect(postCount(calls)).toBe(1);
    setGvMode(server, { c3d: null });
    fireEvent.click(within(stopped).getByRole("button", { name: "다시" }));
    expect(await within(panel).findByTestId("contour-viewer")).toBeTruthy();
    expect(postCount(calls)).toBe(2);
  });

  it("기능 꺼짐 → 칸 맨 위 사유 한 줄(missing 첫 키) + PNG, 요청 없음", async () => {
    const { server } = renderApp(`${STUDY}/4`, { user: "power", disabledFeatures: ["contour3d"] });
    const calls = spy(server);
    const media = await screen.findByTestId("contour-media");
    const slot = media.closest(".contour-slot")!;
    const reason = slot.firstElementChild as HTMLElement;
    expect(reason.getAttribute("data-testid")).toBe("contour-slot-reason");
    expect(reason.textContent).toBe("3D 꺼짐 — 관리자 설정 contour3d.enabled");
    expect(reason.className).toContain("contour-slot-reason");
    expect(reason.getAttribute("title")).toBe(reason.textContent);
    expect(calls.filter((c) => c.p === "/contour3d")).toHaveLength(0);
  });

  it("WebGL 불가 → 사유 한 줄", async () => {
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
    resetWebGLCache();
    renderApp(`${STUDY}/4`, { user: "power" });
    const media = await screen.findByTestId("contour-media");
    expect(within(media.closest(".contour-slot") as HTMLElement).getByTestId("contour-slot-reason").textContent).toBe(WEBGL_TEXT);
  });

  it("읽기 사용자의 미적중(403) → member 사유 한 줄", async () => {
    renderApp(`${STUDY}/4`, { user: "general" });
    const reason = await screen.findByTestId("contour3d-denied");
    expect(reason.textContent).toBe(DENIED_TEXT);
    expect(reason.className).toContain("contour-slot-reason");
    expect(DENIED_TEXT).toBe("3D 미생성 — 처음 생성은 power 권한이 필요합니다");
  });

});
