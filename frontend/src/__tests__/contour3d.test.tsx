// 결과 3D 컨투어 화면(geometry-view.md §13.6, contour3d-default): ④ 예측 결과 컨투어 칸 = 3D 기본(칸이 보이면 자동 POST) → 대기 안내(단계 스테퍼·진행률·경과/예상·취소)
// → 뷰어(정점 색·프레임 Range 로드·이전/다음·재생·범례 고정/프레임별·변형 배율), 410이면 자동 재요청, 결과 실패 사유 + PNG, 기능 꺼짐·WebGL 불가 = PNG 인라인.
// 자동 요청·머무름·429·비교·배치(V-C3D-*)는 contour3dDefault.test.tsx.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { renderApp, STUDY } from "../test/render";
import type { MockServer } from "../mock/server";
import { gvRecords, setGvMode } from "../mock/geomView";
import { resetWebGLCache } from "../stages/stage4/geomview/webgl";
import { POLL } from "../lib/poll";

type Fn = ReturnType<typeof vi.fn>;
const lastCall = (f: Fn) => f.mock.calls[f.mock.calls.length - 1] as unknown[];
interface FakeContour {
  setMesh: Fn;
  setColors: Fn;
  setPositions: Fn;
  setLoop: Fn;
  fit: Fn;
  dispose: Fn;
}
const fake = vi.hoisted(() => ({ c: null as FakeContour | null, nodes: 48 * 28 }));
vi.mock("../stages/stage4/geomview/threeScene", () => ({
  createGeomScene: vi.fn(),
  createContourScene: () => {
    fake.c = {
      setMesh: vi.fn(async () => ({ nodes: fake.nodes, base: new Float32Array(fake.nodes * 3) })),
      setColors: vi.fn(),
      setPositions: vi.fn(),
      setLoop: vi.fn(),
      fit: vi.fn(),
      dispose: vi.fn(),
    };
    return fake.c;
  },
}));

function spy(server: MockServer) {
  const calls: { m: string; p: string; range: string | null }[] = [];
  const orig = server.handle.bind(server);
  server.handle = (m, p, q, b, h) => {
    calls.push({ m, p, range: h.get("Range") });
    return orig(m, p, q, b, h);
  };
  return calls;
}

/** ④ 결과 컨투어 칸(자동 요청 — 열기 버튼 없음) */
async function open() {
  return screen.findByTestId("contour-slot");
}

beforeEach(() => {
  resetWebGLCache();
  fake.c = null;
  POLL.preview = 20;
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({} as never);
});
afterEach(() => {
  vi.restoreAllMocks();
  resetWebGLCache();
  localStorage.clear();
});

describe("④ 예측 결과 — 결과 3D 컨투어", () => {
  it("칸이 보이면 생성 → 뷰어: contour.glb 1회 + 프레임 Range, 정점 색, 이전/다음·슬라이더, 범례 고정/프레임별, 변형 배율, 재생", async () => {
    const { server } = renderApp(`${STUDY}/4`, { user: "power" });
    const calls = spy(server);
    const panel = await open();
    await waitFor(() => expect(calls.some((c) => c.m === "POST" && c.p === "/contour3d")).toBe(true));
    const viewer = await within(panel).findByTestId("contour-viewer");
    await waitFor(() => expect(fake.c?.setMesh).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(fake.c!.setColors).toHaveBeenCalled());
    expect(within(viewer).getByTestId("contour-frame").textContent).toBe("1/24 · t = 0");
    const rec = gvRecords(server).contours[0];
    expect(rec.source_ref).toEqual({ job_id: "j-pred" });
    const rb = fake.nodes * 16;
    await waitFor(() => expect(calls.filter((c) => c.p === `/artifacts/${rec.frames_artifact_id}/media`).map((c) => c.range)).toEqual(expect.arrayContaining([`bytes=0-${rb - 1}`, `bytes=${rb}-${2 * rb - 1}`])));
    expect(calls.filter((c) => c.p === `/artifacts/${rec.glb_artifact_id}/media`)).toHaveLength(1);

    fireEvent.click(within(viewer).getByRole("button", { name: "다음 프레임" }));
    await waitFor(() => expect(within(viewer).getByTestId("contour-frame").textContent).toMatch(/^2\/24/));
    fireEvent.change(within(viewer).getByLabelText("타임스텝"), { target: { value: "23" } });
    await waitFor(() => expect(within(viewer).getByTestId("contour-frame").textContent).toMatch(/^24\/24/));
    await waitFor(() => expect(calls.some((c) => c.range === `bytes=${23 * rb}-${24 * rb - 1}`)).toBe(true));
    fireEvent.click(within(viewer).getByRole("button", { name: "다음 프레임" }));
    await waitFor(() => expect(within(viewer).getByTestId("contour-frame").textContent).toMatch(/^1\/24/)); // 반복

    const legend = within(viewer).getByTestId("contour-legend");
    expect(legend.textContent).toContain("Stress · vonMises (MPa)");
    const n = fake.c!.setColors.mock.calls.length;
    fireEvent.click(within(legend).getByRole("button", { name: "프레임별" }));
    await waitFor(() => expect(fake.c!.setColors.mock.calls.length).toBeGreaterThan(n));

    const scale = within(viewer).getByLabelText("변형 배율") as HTMLSelectElement;
    expect(scale.disabled).toBe(false);
    fireEvent.change(within(viewer).getByLabelText("타임스텝"), { target: { value: "12" } });
    await waitFor(() => expect(within(viewer).getByTestId("contour-frame").textContent).toMatch(/^13\/24/));
    fireEvent.change(scale, { target: { value: "50" } });
    await waitFor(() => {
      const pos = lastCall(fake.c!.setPositions)[0] as Float32Array;
      expect(Math.min(...pos)).toBeLessThan(-10); // z = 50 × dz
    });

    fireEvent.click(within(viewer).getByRole("button", { name: "재생" }));
    await waitFor(() => expect(fake.c!.setLoop).toHaveBeenLastCalledWith(true));
    await waitFor(() => expect(within(viewer).getByTestId("contour-frame").textContent).not.toMatch(/^13\/24/));
    fireEvent.click(within(viewer).getByRole("button", { name: "일시정지" }));
    await waitFor(() => expect(fake.c!.setLoop).toHaveBeenLastCalledWith(false));
  });

  it("대기 안내: 단계 스테퍼(현재 = 프레임 변환)·진행률 62%·경과/예상·취소 → 다시 만들기 → 표시", async () => {
    const { server } = renderApp(`${STUDY}/4`, { user: "power" }, (s) => setGvMode(s, { c3d: "hold" }));
    const panel = await open();
    const wait = await within(panel).findByTestId("contour3d-wait");
    expect(wait.textContent).toContain("3D 컨투어를 만드는 중입니다");
    await waitFor(() => expect(within(wait).getByRole("progressbar").getAttribute("aria-valuenow")).toBe("62"));
    const steps = within(within(wait).getByRole("list", { name: "진행 단계" })).getAllByRole("listitem");
    expect(steps.map((s) => s.textContent)).toEqual(["1대기", "2H3D 읽기", "3형상", "4프레임 변환", "5완료"]);
    expect(steps[3].getAttribute("aria-current")).toBe("step");
    expect(steps[0].className).toContain("done");
    expect(wait.textContent).toContain("경과 46초");
    expect(wait.textContent).toContain("예상 1분 35초 · 남은 약 49초");
    fireEvent.click(within(wait).getByRole("button", { name: "취소" }));
    const stopped = await within(panel).findByTestId("contour3d-stopped");
    expect(stopped.textContent).toContain("3D 컨투어 생성을 취소했습니다.");
    expect(gvRecords(server).contours[0].status).toBe("CANCELED");
    setGvMode(server, { c3d: null });
    fireEvent.click(within(stopped).getByRole("button", { name: "다시 만들기" }));
    expect(await within(panel).findByTestId("contour-viewer")).toBeTruthy();
    expect(gvRecords(server).contours).toHaveLength(2);
  });

  it("410(캐시 정리됨) → 자동으로 다시 요청해 다시 표시", async () => {
    const { server } = renderApp(`${STUDY}/4`, { user: "power" }, (s) => setGvMode(s, { c3d: "expire" }));
    const calls = spy(server);
    const panel = await open();
    await waitFor(() => expect(calls.filter((c) => c.m === "POST" && c.p === "/contour3d")).toHaveLength(2));
    expect(gvRecords(server).contours[0].status).toBe("EXPIRED");
    await waitFor(() => expect(gvRecords(server).contours[1].status).toBe("DONE"));
    const viewer = await within(panel).findByTestId("contour-viewer");
    await waitFor(() => expect(within(viewer).getByTestId("contour-frame").textContent).toBe("1/24 · t = 0"));
  });

  it("결과 실패(값 없음)는 사유 표시, 기능 꺼짐·WebGL 불가면 버튼 숨김", async () => {
    renderApp(`${STUDY}/4`, { user: "power" }, (s) => setGvMode(s, { c3d: "fail" }));
    const panel = await open();
    expect((await within(panel).findByTestId("contour3d-fail")).textContent).toContain("선택한 결과 값이 없습니다");
    expect(within(panel).getByTestId("contour-media")).toBeTruthy(); // V-C3D-14: 사유 + PNG 인라인([다시] 없음)
    expect(within(panel).queryByRole("button", { name: "다시" })).toBeNull();
  });

  it("FEM 검증 결과 컨투어 탭: 예측·FEM 두 원본(PREDICT_H3D·SOLVER_H3D {fem_verification_id})으로 생성, 예측 job 없으면 FEM 단독", async () => {
    const { server } = renderApp(`${STUDY}/4/verify/fv-1`, { user: "power", hpcConfigured: true, femVerify: "demo" });
    await screen.findByRole("table", { name: "FEM 응답 비교" });
    fireEvent.click(screen.getByRole("tab", { name: "컨투어" }));
    await screen.findByTestId("contour-compare3d");
    await waitFor(() => expect(gvRecords(server).contours).toHaveLength(2));
    expect(gvRecords(server).contours.map((c) => c.source_kind).sort()).toEqual(["PREDICT_H3D", "SOLVER_H3D"]);
    expect(gvRecords(server).contours.find((c) => c.source_kind === "SOLVER_H3D")).toMatchObject({ source_ref: { fem_verification_id: "fv-1" } });
  });

  it("GV-C3 ① 해석 run 결과: h3d_rel 있는 run만 [3D 컨투어] → SOLVER_H3D {study_id, h3d_rel}로 생성", async () => {
    const { server } = renderApp(`${STUDY}/1`, { user: "power", hpcConfigured: true });
    const table = await screen.findByRole("table", { name: "PBS 제출 표" });
    await waitFor(() => expect(within(table).getAllByRole("row").length).toBe(31));
    const row = (k: string) => within(table).getAllByRole("row").find((r) => r.textContent?.includes(k))!;
    expect(within(row("run__00027")).queryByRole("button", { name: "3D 컨투어" })).toBeNull(); // 해석 실패 = h3d 없음
    fireEvent.click(within(row("run__00001")).getByRole("button", { name: "3D 컨투어" }));
    const panel = await screen.findByTestId("contour3d-panel");
    await within(panel).findByTestId("contour-viewer"); // 열린 채로 시작(바로 생성 요청)
    const rec = gvRecords(server).contours[0];
    expect(rec.source_kind).toBe("SOLVER_H3D");
    expect(rec.source_ref).toEqual({ study_id: "s-cushion", h3d_rel: expect.stringMatching(/^01_train\/results\/.+\/run__00001\/.+\.h3d$/) });
    fireEvent.click(within(row("run__00001")).getByRole("button", { name: "3D 컨투어" }));
    await waitFor(() => expect(screen.queryByTestId("run-contour3d")).toBeNull());
  });

  it("GV-C3 ① run 표: features.contour3d=false → 결과 열·버튼 없음", async () => {
    renderApp(`${STUDY}/1`, { user: "power", hpcConfigured: true, disabledFeatures: ["contour3d"] });
    const table = await screen.findByRole("table", { name: "PBS 제출 표" });
    await waitFor(() => expect(within(table).getAllByRole("row").length).toBe(31));
    expect(within(table).queryByRole("button", { name: "3D 컨투어" })).toBeNull();
    expect(within(table).queryByRole("columnheader", { name: "결과" })).toBeNull();
  });

  it("features.contour3d=false → PNG 인라인(그림/영상 버튼·요청 없음)", async () => {
    const { server } = renderApp(`${STUDY}/4`, { user: "power", disabledFeatures: ["contour3d"] });
    const calls = spy(server);
    await screen.findByTestId("contour-media");
    expect(screen.queryByTestId("contour-slot")).toBeNull();
    expect(screen.queryByRole("button", { name: "그림/영상" })).toBeNull();
    expect(calls.filter((c) => c.p === "/contour3d")).toHaveLength(0);
  });

  it("WebGL 불가 → PNG 인라인(기존 PNG·영상 유지, 요청 없음)", async () => {
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
    resetWebGLCache();
    const { server } = renderApp(`${STUDY}/4`, { user: "power" });
    const calls = spy(server);
    await screen.findByTestId("contour-media");
    expect(screen.queryByTestId("contour-slot")).toBeNull();
    expect(screen.queryByRole("button", { name: "그림/영상" })).toBeNull();
    expect(calls.filter((c) => c.p === "/contour3d")).toHaveLength(0);
  });
});
