// v0.2.9 결과 컨투어 3D 기본 표시·1:1 배치 프런트(contour3d-default.md, V-C3D-1~11·14): ④ 단일·일괄·FEM 검증, ⑤, ⑥ — 자동 요청(IntersectionObserver 목)·머무름·429·권한 안내·
// [그림/영상] 창·PNG 폴백·비교 뷰어(공통 범례·시점 연결·공용 시간)·c-half 배치. 3D 장면(three)은 가짜 장면으로 대신한다(WebGL 불필요).
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import gridCss from "../design/grid.css?raw";
import { renderApp, STUDY } from "../test/render";
import type { MockServer } from "../mock/server";
import { gvRecords, setGvMode } from "../mock/geomView";
import { resetWebGLCache } from "../stages/stage4/geomview/webgl";
import { fmtLegend } from "../stages/stage4/geomview/contour/colormap";
import { BUSY_TEXT, commonLegend, DENIED_TEXT, LEGEND_SEPARATE_NOTE, pairFrame, sameTimes, showsMedia, unionBox, type ContourManifest } from "../stages/stage4/geomview/contour/contourCore";
import type { Contour3d } from "../api";
import { POLL } from "../lib/poll";

type Fn = ReturnType<typeof vi.fn>;
interface FakeScene {
  setMesh: Fn;
  setColors: Fn;
  setPositions: Fn;
  setLoop: Fn;
  setLevel: Fn;
  setMarkers: Fn;
  onInteract: Fn;
  onPick: Fn;
  fit: Fn;
  getCamera: Fn;
  setCamera: Fn;
  onCameraChange: Fn;
  emit: (s: unknown) => void;
  getBox: Fn;
  fitBox: Fn;
  dispose: Fn;
}
const fake = vi.hoisted(() => ({ all: [] as FakeScene[], nodes: 48 * 28 }));
vi.mock("../stages/stage4/geomview/threeScene", () => ({
  createGeomScene: vi.fn(),
  createContourScene: () => {
    const listeners = new Set<(s: unknown) => void>();
    const f: FakeScene = {
      setMesh: vi.fn(async () => ({ nodes: fake.nodes, base: new Float32Array(fake.nodes * 3) })),
      setColors: vi.fn(),
      setPositions: vi.fn(),
      setLoop: vi.fn(),
      setLevel: vi.fn(),
      setMarkers: vi.fn(),
      onInteract: vi.fn(() => () => undefined),
      onPick: vi.fn(() => () => undefined),
      fit: vi.fn(),
      getCamera: vi.fn(() => ({ position: [1, 2, 3], target: [0, 0, 0], up: [0, 0, 1], zoom: 1 })),
      setCamera: vi.fn(),
      onCameraChange: vi.fn((cb: (s: unknown) => void) => {
        listeners.add(cb);
        return () => listeners.delete(cb);
      }),
      emit: (s) => listeners.forEach((l) => l(s)),
      getBox: vi.fn(() => ({ min: [0, 0, 0], max: [10, 20, 30] })),
      fitBox: vi.fn(),
      dispose: vi.fn(),
    };
    fake.all.push(f);
    return f;
  },
}));

class FakeIO {
  static all: FakeIO[] = [];
  el: Element | null = null;
  constructor(private cb: (e: { isIntersecting: boolean; target: Element }[]) => void) {
    FakeIO.all.push(this);
  }
  observe(el: Element) {
    this.el = el;
  }
  unobserve() {}
  disconnect() {
    FakeIO.all = FakeIO.all.filter((x) => x !== this);
  }
  show(on: boolean) {
    this.cb([{ isIntersecting: on, target: this.el! }]);
  }
}

function spy(server: MockServer) {
  const calls: { m: string; p: string; body: unknown }[] = [];
  const orig = server.handle.bind(server);
  server.handle = (m, p, q, b, h) => {
    calls.push({ m, p, body: b });
    return orig(m, p, q, b, h);
  };
  return {
    calls,
    posts: () => calls.filter((c) => c.m === "POST" && c.p === "/contour3d"),
    cancels: () => calls.filter((c) => c.m === "POST" && /^\/contour3d\/.+\/cancel$/.test(c.p)),
  };
}
const handle = (s: MockServer, m: string, p: string, body: Record<string, unknown> | null = null) => s.handle(m, p, new URLSearchParams(), body, new Headers({ "X-PhysicsAI-Request": "1" }));
const sleep = (ms: number) => act(() => new Promise<void>((r) => setTimeout(r, ms)));
const region = (name: string) => screen.findByRole("region", { name });
/** ④ 결과 컨투어 칸: 예측 작업이 끝나 3D 칸으로 바뀐 뒤의 카드(칸이 바뀌면 카드 요소도 새로 만들어진다) */
const slotCard = async () => {
  await screen.findByTestId("contour-slot");
  return screen.getByRole("region", { name: "결과 컨투어" });
};
const slotBtn = (c: HTMLElement) => within(c).queryByRole("button", { name: "그림/영상" });
const BATCH = `${STUDY}/4/batch/pb-2`;
const A = `${STUDY}/analysis`;

/** 이미 만들어 둔(캐시 적중 상태) 컨투어 */
function seedContour(server: MockServer, source_kind: string, source_ref: Record<string, unknown>) {
  const who = server.user;
  server.user = "power"; // 새 생성은 power — 만든 뒤 화면 사용자로 되돌린다
  let c = handle(server, "POST", "/contour3d", { source_kind, source_ref }).body as Contour3d;
  for (let i = 0; i < 8 && c.status !== "DONE"; i++) c = handle(server, "GET", `/contour3d/${c.id}`).body as Contour3d;
  server.user = who;
  expect(c.status).toBe("DONE");
}

beforeEach(() => {
  resetWebGLCache();
  fake.all = [];
  FakeIO.all = [];
  Object.assign(POLL, { preview: 20, contourDwell: 150, contourRetry: 80 });
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({} as never);
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  resetWebGLCache();
  localStorage.clear();
  Object.assign(POLL, { contourDwell: 800, contourRetry: 3000 });
});

describe("V-C3D-1·4 ④ 단일: 3D 기본·칸이 보일 때만 자동 요청", () => {
  it("뷰포트에 들어올 때 1회 POST(그 전 0회) → 3D 뷰어, PNG 인라인 없음, 카드 머리 [그림/영상]", async () => {
    vi.stubGlobal("IntersectionObserver", FakeIO);
    const { server } = renderApp(`${STUDY}/4`, { user: "power" });
    const s = spy(server);
    const card = await slotCard();
    const slot = await within(card).findByTestId("contour-slot");
    await sleep(120);
    expect(s.posts()).toHaveLength(0); // 아직 안 보임 = 요청 없음
    const io = FakeIO.all.find((x) => x.el === slot)!;
    act(() => io.show(true));
    await within(card).findByTestId("contour-viewer");
    expect(s.posts()).toHaveLength(1);
    expect(s.posts()[0].body).toEqual({ source_kind: "PREDICT_H3D", source_ref: { job_id: "j-pred" } });
    expect(within(card).queryByTestId("contour-media")).toBeNull();
    expect(slotBtn(card)).toBeTruthy();
    act(() => io.show(false));
    act(() => io.show(true));
    await sleep(80);
    expect(s.posts()).toHaveLength(1); // 다시 들어와도 이미 있으면 요청하지 않음
  });

  it("이미 캐시에 있으면(200 적중) 대기 화면 없이 곧바로 뷰어", async () => {
    const { server } = renderApp(`${STUDY}/4`, { user: "power" }, (srv) => seedContour(srv, "PREDICT_H3D", { job_id: "j-pred" }));
    const s = spy(server);
    const card = await slotCard();
    await within(card).findByTestId("contour-viewer");
    expect(within(card).queryByTestId("contour3d-wait")).toBeNull();
    expect(s.posts()).toHaveLength(1);
    expect(gvRecords(server).contours).toHaveLength(1); // 새 작업 없음
  });

  it("V-C3D-11 배치: 템플릿 | 결과 컨투어 = c-half 1:1, 결과 칸은 12칸 뒤, 진행 카드 없음(진행 단계는 컨투어 카드 안 접힘)", async () => {
    renderApp(`${STUDY}/4`, { user: "power" });
    const card = await slotCard();
    const tpl = screen.getByRole("region", { name: "템플릿" });
    const res = screen.getByRole("region", { name: "결과" });
    expect(tpl.className).toContain("c-half");
    expect(card.className).toContain("c-half");
    expect(res.className).toContain("c9");
    expect(tpl.compareDocumentPosition(card) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(card.compareDocumentPosition(res) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.queryByRole("region", { name: "진행" })).toBeNull();
    expect(within(card).getByTestId("predict-progress").tagName).toBe("DETAILS");
    expect(within(res).queryByTestId("contour-media")).toBeNull(); // 컨투어는 결과 칸 안에 없다
  });
});

describe("V-C3D-3 [그림/영상] 창", () => {
  it("열면 기존 PNG 부품(방향·영상·받기·다시 캡처 power), Esc로 닫으면 버튼으로 포커스 복귀", async () => {
    renderApp(`${STUDY}/4`, { user: "power" });
    const card = await slotCard();
    await within(card).findByTestId("contour-viewer");
    const btn = slotBtn(card)!;
    btn.focus();
    fireEvent.click(btn);
    const dlg = await screen.findByRole("dialog", { name: "그림/영상 — 예측 컨투어" });
    expect(dlg.className).toContain("media-dialog");
    expect(document.activeElement).toBe(within(dlg).getByRole("button", { name: "닫기" }));
    const media = await within(dlg).findByTestId("contour-media");
    expect(await within(media).findByRole("group", { name: "방향" })).toBeTruthy();
    expect(await within(media).findByRole("link", { name: "이미지 받기" })).toBeTruthy();
    expect(await within(media).findByRole("button", { name: "다시 캡처" })).toBeTruthy();
    fireEvent.keyDown(dlg, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(document.activeElement).toBe(btn);
    fireEvent.click(btn);
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "닫기" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("읽기 사용자는 창 안에 다시 캡처가 없다", async () => {
    renderApp(`${STUDY}/4`, { user: "general" }, (srv) => seedContour(srv, "PREDICT_H3D", { job_id: "j-pred" }));
    const card = await slotCard();
    await within(card).findByTestId("contour-viewer");
    fireEvent.click(slotBtn(card)!);
    const dlg = await screen.findByRole("dialog");
    await within(dlg).findByRole("link", { name: "이미지 받기" });
    expect(within(dlg).queryByRole("button", { name: "다시 캡처" })).toBeNull();
  });
});

describe("V-C3D-6·7·14 대기·429·권한·실패", () => {
  it("429 → 안내 문구 → 간격 뒤 재요청 → 202 → 뷰어(대기 화면에도 [그림/영상])", async () => {
    const { server } = renderApp(`${STUDY}/4`, { user: "power" }, (srv) => setGvMode(srv, { c3dBusy: 2, c3d: "hold" }));
    const s = spy(server);
    const card = await slotCard();
    expect((await within(card).findByTestId("contour3d-busy")).textContent).toBe(BUSY_TEXT);
    expect(slotBtn(card)).toBeTruthy();
    await within(card).findByTestId("contour3d-wait");
    expect(s.posts()).toHaveLength(3); // 429, 429, 202
    expect(slotBtn(card)).toBeTruthy(); // 대기 화면에도
    setGvMode(server, { c3d: null });
    await within(card).findByTestId("contour-viewer", undefined, { timeout: 3000 });
  });

  it("읽기 사용자 미적중(403 PERMISSION_DENIED) → 작업 없이 PNG 인라인 + 안내 한 줄, [그림/영상] 버튼은 없음", async () => {
    const { server } = renderApp(`${STUDY}/4`, { user: "general" });
    const card = await slotCard();
    expect((await within(card).findByTestId("contour3d-denied")).textContent).toBe(DENIED_TEXT);
    expect(within(card).getByTestId("contour-media")).toBeTruthy();
    expect(slotBtn(card)).toBeNull();
    expect(gvRecords(server).contours).toHaveLength(0);
  });

  it("작업 실패(FAILED) → 사유 + [다시] + PNG 인라인, 다시 누르면 새로 요청", async () => {
    const { server } = renderApp(`${STUDY}/4`, { user: "power" }, (srv) => setGvMode(srv, { c3d: "jobfail" }));
    const card = await slotCard();
    const stopped = await within(card).findByTestId("contour3d-stopped");
    expect(stopped.textContent).toContain("H3D 읽기 도구가 종료되었습니다");
    expect(within(card).getByTestId("contour-media")).toBeTruthy();
    expect(slotBtn(card)).toBeNull();
    setGvMode(server, { c3d: null });
    fireEvent.click(within(stopped).getByRole("button", { name: "다시" }));
    await within(card).findByTestId("contour-viewer");
    expect(gvRecords(server).contours).toHaveLength(2);
  });
});

describe("V-C3D-2 폴백", () => {
  it("WebGL 불가 → ⑥도 PNG 두 열 인라인(그림/영상 버튼·요청 없음)", async () => {
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
    resetWebGLCache();
    const { server } = renderApp(`${STUDY}/5/surrogate/so-1`, { user: "power" });
    const s = spy(server);
    const card = await region("컨투어 비교 — 기존안 · 최적안");
    expect(await within(card).findByTestId("contour-기존안")).toBeTruthy();
    expect(within(card).getByTestId("contour-최적안")).toBeTruthy();
    expect(within(card).getByTestId("so-legend-text").textContent).toMatch(/^같은 범례\(0–/);
    expect(slotBtn(card)).toBeNull();
    expect(s.posts()).toHaveLength(0);
  });
});

describe("V-C3D-5·1·11 ④ 일괄 결과", () => {
  it("행 3번을 머무름 안에 바꾸면 마지막 행만 POST(취소 호출 0회), 결과 표 | DOE c-half, 결과분석 카드 없음", async () => {
    const { server } = renderApp(BATCH, { user: "power" });
    const s = spy(server);
    const table = await region("결과 표 — B-002");
    const ok = (handle(server, "GET", "/predict-batches/pb-2").body as { rows: { doe_no: number; job_id: string | null; state: string }[] }).rows.filter((r) => r.state === "SUCCEEDED" && r.job_id);
    expect(ok.length).toBeGreaterThanOrEqual(4);
    const [a, b, c] = ok.slice(1, 4);
    for (const r of [a, b, c]) fireEvent.click(screen.getByTestId(`row-${r.doe_no}`));
    const card = await region(`DOE #${c.doe_no}`);
    expect(table.className).toContain("c-half");
    expect(card.className).toContain("c-half");
    expect(screen.queryByRole("region", { name: "결과분석" })).toBeNull();
    await within(card).findByTestId("contour-viewer");
    expect(s.posts().map((p) => (p.body as { source_ref: { job_id: string } }).source_ref.job_id)).toEqual([c.job_id]);
    expect(s.cancels()).toHaveLength(0);
    expect(slotBtn(card)).toBeTruthy();
    // 행을 바꾸면 이전 서버 작업은 그대로 두고 새 원본만 요청
    fireEvent.click(screen.getByTestId(`row-${a.doe_no}`));
    await within(await region(`DOE #${a.doe_no}`)).findByTestId("contour-viewer");
    expect(s.posts()).toHaveLength(2);
    expect(s.cancels()).toHaveLength(0);
    expect(within(table).getByTestId("analysis-link").getAttribute("href")).toBe(`${STUDY}/analysis?source=batch&id=pb-2`);
  });
});

describe("V-C3D-10 ⑤ 결과 컨투어 칸", () => {
  it("일괄: 결과 표 | 결과 컨투어 c-half, 응답 그래프 12칸(탭 4개)은 아래 줄, 선택 행 PREDICT_H3D {job_id}", async () => {
    const { server } = renderApp(`${A}?source=batch&id=pb-2`, { user: "power" });
    const s = spy(server);
    const table = await region("결과 표 — B-002");
    const card = await region("결과 컨투어");
    const graph = await region("응답 그래프");
    expect(table.className).toContain("c-half");
    expect(card.className).toContain("c-half");
    expect(graph.className).toContain("c12");
    expect(within(graph).getAllByRole("tab")).toHaveLength(4);
    expect(table.compareDocumentPosition(card) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(card.compareDocumentPosition(graph) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    await within(card).findByTestId("contour-viewer");
    const first = s.posts()[0].body as { source_kind: string; source_ref: { job_id: string } };
    expect(first.source_kind).toBe("PREDICT_H3D");
    expect(first.source_ref.job_id).toMatch(/^j-/);
    expect(slotBtn(card)).toBeTruthy(); // 일괄은 PNG가 있어 [그림/영상]
  });

  it("DOE: runs 페이지 맵으로 SOLVER_H3D {study_id, h3d_rel}, h3d_rel 없는 run은 안내, PNG 없음 → 버튼 없음, 행 선택은 머무름", async () => {
    const { server } = renderApp(`${A}?source=doe&id=doe-1`, { user: "power", hpcConfigured: true });
    const s = spy(server);
    await region("결과 표 — LatinHyperCube");
    const card = await region("결과 컨투어");
    await within(card).findByTestId("contour-viewer");
    expect(s.calls.some((c) => c.m === "GET" && c.p === "/train-does/doe-1/runs")).toBe(true);
    const body = s.posts()[0].body as { source_kind: string; source_ref: Record<string, string> };
    expect(body.source_kind).toBe("SOLVER_H3D");
    expect(body.source_ref).toEqual({ study_id: "s-cushion", h3d_rel: expect.stringMatching(/^01_train\/results\/.+\/run__00001\/.+\.h3d$/) });
    expect(slotBtn(card)).toBeNull();
    const n = s.posts().length;
    fireEvent.click(screen.getByTestId("row-27")); // 해석 실패 run = h3d 없음
    expect((await within(card).findByTestId("analysis-contour-note")).textContent).toBe("이 run은 결과 h3d가 없습니다");
    await sleep(250);
    expect(s.posts()).toHaveLength(n);
  });
});

describe("V-C3D-9 ⑥ 내장 최적화·FEM 검증 비교 뷰어", () => {
  const title = "컨투어 비교 — 기존안 · 최적안";

  it("final.baseline/best job_id로 POST 2건, 기존안·최적안 열, 공통 범례(두 range 합집합)·공용 시간·시점 연결·맞춤", async () => {
    const { server, unmount } = renderApp(`${STUDY}/5/surrogate/so-1`, { user: "power" });
    const s = spy(server);
    const card = await region(title);
    const cmp = await within(card).findByTestId("contour-compare3d");
    expect(card.className).toContain("c-half");
    expect(screen.getByRole("region", { name: "최적안 — 기존안 대비" }).className).toContain("c-half");
    await waitFor(() => expect(fake.all).toHaveLength(2));
    await waitFor(() => expect(fake.all[0].setColors).toHaveBeenCalled());
    const fin = server.surrogate[0].final!;
    expect(s.posts().map((p) => (p.body as { source_ref: { job_id: string } }).source_ref.job_id).sort()).toEqual([fin.baseline!.job_id!, fin.best!.job_id!].sort());
    expect(within(within(cmp).getByTestId("contour-left")).getByText("기존안")).toBeTruthy();
    expect(within(within(cmp).getByTestId("contour-right")).getByText("최적안")).toBeTruthy();
    expect(within(card).queryByTestId("contour-media")).toBeNull();

    // 공통 범례 = 두 manifest range 합집합, 뷰어 안 범례는 숨기고 아래 한 개
    const ranges = gvRecords(server).contours.map((c) => (JSON.parse(server.artifacts.find((a) => a.id === c.manifest_artifact_id)!.body) as ContourManifest).range);
    expect(ranges[0].max).not.toBe(ranges[1].max);
    const lo = Math.min(...ranges.map((r) => r.min!));
    const hi = Math.max(...ranges.map((r) => r.max!));
    expect(within(card).getByTestId("c3-legend-common").textContent).toBe(`같은 범례(${fmtLegend(lo)}–${fmtLegend(hi)})로 비교`);
    expect(within(card).getAllByTestId("contour-legend-common")).toHaveLength(1);
    expect(within(card).queryAllByTestId("contour-legend")).toHaveLength(0);
    fireEvent.click(within(card).getByRole("button", { name: "개별" }));
    expect(within(card).queryByTestId("contour-legend-common")).toBeNull();
    expect(within(card).getAllByTestId("contour-legend")).toHaveLength(2);
    fireEvent.click(within(card).getByRole("button", { name: "공통" }));
    expect(within(card).getAllByTestId("contour-legend-common")).toHaveLength(1);

    // 처음 맞춤: 두 메시 bbox 합집합으로 같은 카메라
    expect(fake.all[0].fitBox).toHaveBeenCalledWith({ min: [0, 0, 0], max: [10, 20, 30] });
    expect(fake.all[1].fitBox).toHaveBeenCalled();

    // 공용 시간 슬라이더
    fireEvent.change(within(card).getByLabelText("타임스텝"), { target: { value: "10" } });
    await waitFor(() => expect(within(card).getByTestId("contour-frame").textContent).toMatch(/^11\/24/));
    expect(within(card).getAllByLabelText("타임스텝")).toHaveLength(1);

    // 시점 연결(기본 켬): 한쪽을 돌리면 다른 쪽이 따라가고, 끄면 따라가지 않는다
    const cam = { position: [9, 9, 9], target: [1, 1, 1], up: [0, 0, 1], zoom: 2 };
    act(() => fake.all[0].emit(cam));
    expect(fake.all[1].setCamera).toHaveBeenCalledWith(cam);
    expect(fake.all[0].setCamera).not.toHaveBeenCalled();
    const link = within(card).getByRole("checkbox", { name: "시점 연결" }) as HTMLInputElement;
    expect(link.checked).toBe(true);
    fireEvent.click(link);
    fake.all[1].setCamera.mockClear();
    act(() => fake.all[0].emit(cam));
    act(() => fake.all[1].emit(cam));
    expect(fake.all[1].setCamera).not.toHaveBeenCalled();
    expect(fake.all[0].setCamera).not.toHaveBeenCalled();

    // [그림/영상] 창: 기존 PNG 두 열(같은 범례 문구·방향 공유)
    fireEvent.click(slotBtn(card)!);
    const dlg = await screen.findByRole("dialog");
    expect(within(dlg).getByTestId("so-legend-text").textContent).toMatch(/^같은 범례\(0–/);
    expect(within(dlg).getByTestId("contour-기존안")).toBeTruthy();
    expect(within(dlg).getByTestId("contour-최적안")).toBeTruthy();
    fireEvent.keyDown(dlg, { key: "Escape" });

    // 패널을 닫으면(언마운트) 뷰어 2개 모두 dispose
    unmount();
    fake.all.forEach((f) => expect(f.dispose).toHaveBeenCalled());
  });

  it("다목적 라벨 = 추천점, final이 DONE이 아니면 기존 문구(요청 없음)", async () => {
    const { server } = renderApp(`${STUDY}/5/surrogate/so-2`, { user: "power" });
    const s = spy(server);
    const card = await region("컨투어 비교 — 기존안 · 추천점");
    expect(within(await within(card).findByTestId("contour-right")).getByText("추천점")).toBeTruthy();
    expect(s.posts().length).toBeGreaterThanOrEqual(2);
    expect(screen.queryByRole("region", { name: title })).toBeNull();
  });

  it("final DONE 아님 → 기존 문구, 3D 요청 없음", async () => {
    const { server } = renderApp(`${STUDY}/5/surrogate/so-1`, { user: "power" }, (srv) => {
      srv.surrogate[0].final = { status: "SKIPPED", reason: "컨투어 캡처 미구성" };
    });
    const s = spy(server);
    const card = await region(title);
    expect((await within(card).findByTestId("contour-none")).textContent).toContain("캡처 없음 — 컨투어 캡처 미구성");
    expect(s.posts()).toHaveLength(0);
  });

  it("FEM 검증: 예측·FEM 두 원본, links.predict_job_id가 null이면 FEM 단독 뷰어 1개", async () => {
    const r1 = renderApp(`${STUDY}/4/verify/fv-1`, { user: "power", hpcConfigured: true, femVerify: "demo" });
    await screen.findByRole("table", { name: "FEM 응답 비교" });
    fireEvent.click(screen.getByRole("tab", { name: "컨투어" }));
    const cmp = await screen.findByTestId("contour-compare3d");
    await waitFor(() => expect(gvRecords(r1.server).contours).toHaveLength(2));
    expect(within(within(cmp).getByTestId("contour-left")).getByText("예측")).toBeTruthy();
    expect(within(within(cmp).getByTestId("contour-right")).getByText("FEM")).toBeTruthy();
    expect(gvRecords(r1.server).contours.map((c) => c.source_kind).sort()).toEqual(["PREDICT_H3D", "SOLVER_H3D"]);
    r1.unmount();
    fake.all = [];
    const r2 = renderApp(`${STUDY}/4/verify/fv-1`, { user: "power", hpcConfigured: true, femVerify: "demo" }, (srv) => {
      srv.fems[0].links.predict_job_id = null;
    });
    await screen.findByRole("table", { name: "FEM 응답 비교" });
    fireEvent.click(screen.getByRole("tab", { name: "컨투어" }));
    await screen.findByTestId("contour-viewer");
    expect(screen.queryByTestId("contour-compare3d")).toBeNull();
    expect(gvRecords(r2.server).contours.map((c) => c.source_kind)).toEqual(["SOLVER_H3D"]);
    expect(fake.all).toHaveLength(1);
  });
});

describe("V-C3D-8 비교 순수 함수", () => {
  const man = (over: Partial<Pick<ContourManifest, "display" | "unit">> & { times?: number[]; range?: [number, number] } = {}): ContourManifest => {
    const times = over.times ?? [0, 1, 2, 3];
    const [min, max] = over.range ?? [0, 10];
    return {
      schema_version: 1,
      kind: "contour3d",
      status: "OK",
      display: over.display ?? { field: "Stress", comp: "vonMises", avgmode: "simple" },
      unit: over.unit === undefined ? "MPa" : over.unit,
      mesh: { nodes: 4 },
      frames: { count: times.length, record_bytes: 16, has_disp: false, list: times.map((t, i) => ({ i, src: i, time: t, min, max })) },
      range: { min, max },
    };
  };

  it("공통 범례 = range 합집합, display·unit이 다르면 개별 + 문구, 한쪽 없으면 개별(문구 없음)", () => {
    expect(commonLegend(man({ range: [2, 8] }), man({ range: [-1, 6] }))).toEqual({ shareable: true, range: [-1, 8], note: null });
    const kind = commonLegend(man(), man({ display: { field: "Displacement", comp: "mag", avgmode: "simple" } }));
    expect(kind).toEqual({ shareable: false, range: null, note: LEGEND_SEPARATE_NOTE });
    expect(commonLegend(man(), man({ unit: "GPa" })).shareable).toBe(false);
    expect(commonLegend(man(), null)).toEqual({ shareable: false, range: null, note: null });
  });

  it("pairFrame: 같은 시간표 = 같은 인덱스, 다르면 왼쪽 시간에 가장 가까운 오른쪽 프레임", () => {
    const a = man({ times: [0, 1, 2, 3] });
    expect(sameTimes(a, man({ times: [0, 1, 2, 3 + 1e-12] }))).toBe(true);
    expect(pairFrame(a, man({ times: [0, 1, 2, 3 + 1e-12] }), 2)).toBe(2);
    const b = man({ times: [0, 0.4, 1.7, 2.1, 5] });
    expect(sameTimes(a, b)).toBe(false);
    expect([0, 1, 2, 3].map((i) => pairFrame(a, b, i))).toEqual([0, 1, 3, 3]); // t=1은 0.4(차 0.6)가 1.7(차 0.7)보다 가깝다
  });

  it("unionBox·showsMedia", () => {
    expect(unionBox({ min: [0, 0, 0], max: [1, 1, 1] }, { min: [-1, 0, 2], max: [0, 3, 3] })).toEqual({ min: [-1, 0, 0], max: [1, 3, 3] });
    expect(unionBox(null, { min: [0, 0, 0], max: [1, 1, 1] })).toEqual({ min: [0, 0, 0], max: [1, 1, 1] });
    expect(showsMedia({ c: null, error: null, denied: true })).toBe(true);
    expect(showsMedia({ c: null, error: "x", denied: false })).toBe(true);
    expect(showsMedia({ c: null, error: null, denied: false })).toBe(false);
  });
});

describe("V-C3D-11 격자 CSS(정적)", () => {
  it(".c-half = 12열 중 6칸(≥1280), 1280 미만(6열)·720 미만(2열)은 전체 폭", () => {
    const css = gridCss.replace(/\/\*[\s\S]*?\*\//g, "");
    expect(css).toMatch(/\.c-half\s*\{\s*grid-column:\s*span 6;\s*\}/);
    const wide = css.match(/@media \(min-width: 1280px\)\s*\{([\s\S]*?)\n\}/)![1];
    expect(wide).toMatch(/\.workgrid \.c-half\s*\{\s*grid-column:\s*span 6;/);
    const narrow = css.match(/@media \(max-width: 1279px\)\s*\{([\s\S]*?)\n\}/)![1];
    expect(narrow).toMatch(/repeat\(6,/);
    expect(narrow).toMatch(/\.c-half[\s\S]*?grid-column:\s*span 6;/); // 6열 중 6 = 전체 폭
    const tiny = css.match(/@media \(max-width: 719px\)\s*\{([\s\S]*?)\n\}/)![1];
    expect(tiny).toMatch(/\.c-half[\s\S]*?grid-column:\s*span 2;/);
  });
});
