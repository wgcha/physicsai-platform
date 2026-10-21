// 형상 3D 뷰 화면(geometry-view.md §7·§6.9): ④ native 세트 상세 [3D | 그림], 표 행 ↔ 3D 면 양방향 선택·다중 피처 면 목록,
// 바디 토글, 미리보기(값 입력·슬라이더 범위·[미리보기]·겹쳐 보기·범례·캐시 적중·실패 배지·410 재요청), WebGL 대체·컨텍스트 손실,
// ①-2 공칭 뷰(미리보기 없음·3D 대응 없음). three 장면은 목(threeScene) — 호출만 기록한다.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { renderApp, STUDY } from "../test/render";
import { err } from "../mock/route";
import type { MockServer } from "../mock/server";
import { nativeTrainParams } from "../mock/geometry";
import { expireArtifacts, gvRecords, setGvMode } from "../mock/geomView";
import { resetWebGLCache } from "../stages/stage4/geomview/webgl";
import { POLL } from "../lib/poll";
import { paintFixedMat, paintMovingMat, selectionColor, type Highlight } from "../stages/stage4/geomview/viewerCore";

type Fn = ReturnType<typeof vi.fn>;
const lastCall = (f: Fn) => f.mock.calls[f.mock.calls.length - 1] as unknown[];
interface FakeGeom {
  setNominal: Fn;
  setOverlay: Fn;
  setHighlight: Fn;
  setBodyVisible: Fn;
  setFixed: Fn;
  setPoints: Fn;
  fit: Fn;
  dispose: Fn;
  opts: { onPick: (h: { body: string; face: number } | null, additive?: boolean) => void; onLost: () => void };
}
const fake = vi.hoisted(() => ({ geom: null as FakeGeom | null, failCreate: null as Error | null, hlThrow: null as Error | null }));
vi.mock("../stages/stage4/geomview/threeScene", () => ({
  createGeomScene: (_el: HTMLElement, opts: FakeGeom["opts"]) => {
    if (fake.failCreate) throw fake.failCreate;
    fake.geom = { setNominal: vi.fn(async () => undefined), setOverlay: vi.fn(async () => undefined), setHighlight: vi.fn(() => { if (fake.hlThrow) throw fake.hlThrow; }), setBodyVisible: vi.fn(), setFixed: vi.fn(), setPoints: vi.fn(), fit: vi.fn(), dispose: vi.fn(), opts };
    return fake.geom;
  },
  createContourScene: vi.fn(),
}));

const nativeCurrent = (s: MockServer) => s.paramSets.forEach((p) => (p.is_current = p.id === "ps-n1"));
const lastHl = () => lastCall(fake.geom!.setHighlight)[0] as Highlight;
const rowSel = (table: HTMLElement, name: string) => within(table).getByText(name).closest("tr")!.getAttribute("aria-selected");

function posts(server: MockServer, re: RegExp) {
  const out: Record<string, unknown>[] = [];
  const orig = server.handle.bind(server);
  server.handle = (m, p, q, b, h) => {
    if (m === "POST" && re.test(p)) out.push(b as Record<string, unknown>);
    return orig(m, p, q, b, h);
  };
  return out;
}

async function openDetail() {
  fireEvent.click(await screen.findByRole("button", { name: "템플릿 관리" }));
  const card = await screen.findByRole("region", { name: "템플릿 관리" });
  const table = await within(card).findByRole("table", { name: "형상 피처 표" });
  return { card, table };
}

beforeEach(() => {
  resetWebGLCache();
  fake.geom = null;
  fake.failCreate = null;
  fake.hlThrow = null;
  POLL.preview = 20;
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({} as never);
});
afterEach(() => {
  vi.restoreAllMocks();
  resetWebGLCache();
});

describe("④ native 세트 상세 — 형상 3D 뷰", () => {
  it("[3D | 그림] 기본 3D, GLB 로드, 행 → 면 하이라이트(대칭 구성원 포함)·치수선, 면 클릭 → 행, 다중 피처 면 목록, 빈 면 = 해제, 바디 토글", async () => {
    renderApp(`${STUDY}/4`, { user: "power", geometry: "native" }, nativeCurrent);
    const { card, table } = await openDetail();
    const panel = await within(card).findByTestId("gv-panel");
    expect(within(panel).getByRole("tab", { name: "3D" }).getAttribute("aria-selected")).toBe("true");
    await waitFor(() => expect(fake.geom?.setNominal).toHaveBeenCalled());
    const [buf, manifest] = fake.geom!.setNominal.mock.calls[0];
    expect(buf).toBeInstanceOf(ArrayBuffer);
    expect(manifest.bodies.map((b: { body: string }) => b.body)).toEqual(["CUSH_L", "CUSH_R"]);

    fireEvent.click(within(table).getByText("CUSH_L_THK_1"));
    await waitFor(() => expect([...lastHl().moving].sort()).toEqual(["CUSH_L#2", "CUSH_R#2"]));
    expect([...lastHl().fixed].sort()).toEqual(["CUSH_L#1", "CUSH_R#1"]);
    expect(lastHl().dims.map((d) => d.text)).toEqual(["12.5 mm", "12.5 mm"]);

    act(() => fake.geom!.opts.onPick({ body: "CUSH_L", face: 12 }));
    await waitFor(() => expect(rowSel(table, "CUSH_L_HOLE_U_1")).toBe("true"));
    expect(lastHl().dims[0].text).toBe("30 mm");

    act(() => fake.geom!.opts.onPick({ body: "CUSH_L", face: 2 }));
    const lb = await within(card).findByRole("listbox", { name: "이 면을 쓰는 피처" });
    expect(within(lb).getAllByRole("option").map((o) => o.textContent)).toEqual(["CUSH_L_THK_1", "CUSH_L_POCKET_D_1"]);
    fireEvent.click(within(lb).getByRole("option", { name: "CUSH_L_POCKET_D_1" }));
    await waitFor(() => expect(rowSel(table, "CUSH_L_POCKET_D_1")).toBe("true"));
    expect(within(card).queryByRole("listbox")).toBeNull();

    act(() => fake.geom!.opts.onPick({ body: "CUSH_L", face: 4 }));
    await waitFor(() => expect(within(table).queryAllByRole("row").some((r) => r.getAttribute("aria-selected") === "true")).toBe(false));

    fireEvent.click(within(card).getByLabelText("CUSH_R 표시"));
    await waitFor(() => expect(fake.geom!.setBodyVisible).toHaveBeenCalledWith("CUSH_R", false));
    fireEvent.click(within(card).getByRole("button", { name: "맞춤" }));
    expect(fake.geom!.fit).toHaveBeenCalled();

    fireEvent.click(within(table).getByText("CUSH_L_HOLE_U_1"));
    fireEvent.click(within(panel).getByRole("tab", { name: "그림" }));
    const fig = await within(card).findByTestId("feature-png");
    await waitFor(() => expect(fig.querySelector("img")?.getAttribute("alt")).toBe("CUSH_L_HOLE_U_1 하이라이트"));
    await waitFor(() => expect(fake.geom!.dispose).toHaveBeenCalled()); // 3D 탭을 닫으면 dispose
  });

  it("미리보기: 슬라이더 범위·띠 문구 → [미리보기] → 겹쳐 보기(형상 + 변위 범례)·치수 = 입력 값, 같은 값 다시 = 캐시 결과", async () => {
    const { server } = renderApp(`${STUDY}/4`, { user: "power", geometry: "native" }, nativeCurrent);
    const sent = posts(server, /\/param-sets\/ps-n1\/previews$/);
    const { card, table } = await openDetail();
    await waitFor(() => expect(fake.geom?.setNominal).toHaveBeenCalled());
    expect(within(card).getByText("행을 고르면 값을 바꿔 미리볼 수 있습니다")).toBeTruthy();
    fireEvent.click(within(table).getByText("CUSH_L_THK_1"));
    const input = await within(card).findByLabelText("CUSH_L_THK_1 미리보기 값");
    expect(within(card).getByTestId("slider-range").textContent).toBe("모핑 가능 6.2~18(envelope 측정) · 사용자 범위 11.875~13.125");
    expect((within(card).getByLabelText("CUSH_L_THK_1 슬라이더") as HTMLInputElement).min).toBe("6.2");
    fireEvent.change(input, { target: { value: "14" } });
    expect(sent).toHaveLength(0); // 값 변경만으로는 요청하지 않음
    fireEvent.click(within(card).getByRole("button", { name: "미리보기" }));
    const okText = await within(card).findByTestId("preview-ok");
    expect(sent[0]).toEqual({ values: { CUSH_L_THK_1: 14 }, fe: "off" });
    expect(okText.textContent).toContain("완료");
    expect(okText.textContent).toContain("형상만 — 검사 생략");
    await waitFor(() => expect(lastCall(fake.geom!.setOverlay)[0]).toBeInstanceOf(ArrayBuffer));
    expect(lastCall(fake.geom!.setOverlay).slice(1)).toEqual(["shape", 1.5]);
    expect(within(card).getByTestId("disp-legend").textContent).toContain("공칭 형상과의 거리(mm)");
    await waitFor(() => expect(lastHl().dims[0].text).toBe("14 mm"));
    fireEvent.click(within(card).getByRole("button", { name: "미리보기" }));
    await waitFor(() => expect(within(card).getByTestId("preview-ok").textContent).toContain("캐시 결과"));
    expect(sent).toHaveLength(2);
    fireEvent.click(within(card).getByRole("button", { name: "공칭으로" }));
    await waitFor(() => expect(lastCall(fake.geom!.setOverlay)[0]).toBeNull());
  });

  it("미리보기 실패: 범위 밖 경고 → FAIL 배지(CAD 생성 불가)·한국어 사유·관련 피처 면 빨강", async () => {
    renderApp(`${STUDY}/4`, { user: "power", geometry: "native" }, nativeCurrent);
    const { card, table } = await openDetail();
    await waitFor(() => expect(fake.geom?.setNominal).toHaveBeenCalled());
    fireEvent.click(within(table).getByText("CUSH_L_THK_1"));
    fireEvent.change(await within(card).findByLabelText("CUSH_L_THK_1 미리보기 값"), { target: { value: "20" } });
    expect(within(card).getByText("모핑 가능 범위 밖 — 실패할 수 있음")).toBeTruthy();
    fireEvent.click(within(card).getByRole("button", { name: "미리보기" }));
    const fail = await within(card).findByTestId("preview-fail");
    expect(fail.textContent).toContain("CAD 생성 불가");
    expect(fail.textContent).toContain("피처끼리 충돌합니다");
    expect(fail.textContent).toContain("GEOM_FEATURE_COLLISION");
    await waitFor(() => expect(lastHl().red.has("CUSH_L#9")).toBe(true));
    expect(lastHl().red.has("CUSH_R#2")).toBe(true);
  });

  it("410(서버 캐시 정리됨) → 같은 값으로 다시 요청해 새로 만든다", async () => {
    const { server } = renderApp(`${STUDY}/4`, { user: "power", geometry: "native" }, nativeCurrent);
    const sent = posts(server, /\/previews$/);
    const { card, table } = await openDetail();
    await waitFor(() => expect(fake.geom?.setNominal).toHaveBeenCalled());
    fireEvent.click(within(table).getByText("CUSH_L_HOLE_U_1"));
    fireEvent.change(await within(card).findByLabelText("CUSH_L_HOLE_U_1 미리보기 값"), { target: { value: "33" } });
    fireEvent.click(within(card).getByRole("button", { name: "미리보기" }));
    await within(card).findByTestId("preview-ok");
    const first = gvRecords(server).previews[0];
    expireArtifacts(server, [first.glb_artifact_id, first.manifest_artifact_id], false); // 행은 아직 DONE(정리 직후)
    fireEvent.click(within(card).getByRole("button", { name: "미리보기" }));
    await waitFor(() => expect(gvRecords(server).previews).toHaveLength(2));
    await waitFor(() => expect(within(card).getByTestId("preview-ok").textContent).toContain("완료"));
    expect(sent).toHaveLength(3);
    expect(first.status).toBe("EXPIRED");
  });

  it("쉘: 고정 영역 마커 토글(fixed_clusters), 실패 클러스터 없음 = 파랑", async () => {
    renderApp(`${STUDY}/4`, { user: "power", geometry: "native" }, (s) => (nativeCurrent(s), setGvMode(s, { shell: true })));
    const { card } = await openDetail();
    await waitFor(() => expect(fake.geom?.setFixed).toHaveBeenCalled());
    expect(lastCall(fake.geom!.setFixed)[0]).toBe(true);
    expect((lastCall(fake.geom!.setFixed)[1] as { id: number }[]).map((c) => c.id)).toEqual([1]);
    expect((lastCall(fake.geom!.setFixed)[2] as Set<string>).size).toBe(0);
    fireEvent.click(within(card).getByLabelText("고정 영역(1)"));
    await waitFor(() => expect(lastCall(fake.geom!.setFixed)[0]).toBe(false));
  });

  it("WebGL 불가 → 그림만 + 안내, 컨텍스트 손실 → 그림으로 대체", async () => {
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
    resetWebGLCache();
    renderApp(`${STUDY}/4`, { user: "power", geometry: "native" }, nativeCurrent);
    const { card, table } = await openDetail();
    expect((await within(card).findByTestId("gv-fallback")).textContent).toBe("이 PC는 WebGL을 쓸 수 없어 그림으로 표시합니다(하드웨어 가속 꺼짐·원격 데스크톱·GPU 없음 추정)");
    expect(within(card).queryByRole("tablist", { name: "형상 보기" })).toBeNull();
    fireEvent.click(within(table).getByText("CUSH_L_HOLE_U_1"));
    expect(await within(card).findByTestId("feature-png")).toBeTruthy();
    expect(fake.geom).toBeNull(); // three 미적재
  });

  it("컨텍스트 손실(webglcontextlost) → 그림 탭으로 대체", async () => {
    renderApp(`${STUDY}/4`, { user: "power", geometry: "native" }, nativeCurrent);
    const { card } = await openDetail();
    await waitFor(() => expect(fake.geom?.setNominal).toHaveBeenCalled());
    act(() => fake.geom!.opts.onLost());
    expect((await within(card).findByTestId("gv-fallback")).textContent).toContain("그래픽 컨텍스트 손실");
    expect(fake.geom!.dispose).toHaveBeenCalled();
  });
});

describe("①-2 파라미터 표 — 공칭 3D 뷰(§6.9)", () => {
  it("같은 뷰어, 미리보기 숨김, 행 클릭 → 하이라이트, manifest에 없는 행 = 3D 대응 없음", async () => {
    renderApp(`${STUDY}/1`, { user: "power" }, (s) => {
      Object.assign(s.p2.setups["s-cushion"], { engine: "native", parameters: nativeTrainParams(), tpl: null, extract_job_id: "j-x" });
      setGvMode(s, {});
    });
    const panel = await screen.findByTestId("gv-panel");
    await waitFor(() => expect(fake.geom?.setNominal).toHaveBeenCalled());
    expect(screen.queryByTestId("preview-panel")).toBeNull();
    const table = screen.getByRole("table", { name: "파라미터 표" });
    fireEvent.click(within(table).getByText("CUSH_L_POCKET_D_1"));
    await waitFor(() => expect([...lastHl().moving]).toEqual(["CUSH_L#7"]));
    act(() => fake.geom!.opts.onPick({ body: "CUSH_L", face: 12 }));
    await waitFor(() => expect(rowSel(table, "CUSH_L_HOLE_U_1")).toBe("true"));
    fireEvent.click(within(table).getByText("BOX_SHELL_T"));
    expect(await within(panel).findByText("3D 대응 없음(쉘 두께 등 — 표에서만)")).toBeTruthy();
  });
});

describe("항상 떠 있는 3D 창 + 변수 클릭·다중 선택 하이라이트", () => {
  const native1 = (extra = 0) => (s: MockServer) => {
    const params = nativeTrainParams();
    for (let i = 0; i < extra; i++) params.push({ name: `EXTRA_${i}`, raw_nominal: "1 mm", nominal: 1, min: 0.9, max: 1.1, use: false, format: "%.4f", unit: "mm", valid: true, problems: [] });
    Object.assign(s.p2.setups["s-cushion"], { engine: "native", parameters: params, tpl: null, extract_job_id: "j-x" });
    setGvMode(s, {});
  };
  const isSel = (table: HTMLElement, name: string) => rowSel(table, name) === "true";
  const selected = (table: HTMLElement) => within(table).queryAllByRole("row").filter((r) => r.getAttribute("aria-selected") === "true").map((r) => r.getAttribute("data-row"));
  const open12 = async () => {
    const { server } = renderApp(`${STUDY}/1`, { user: "power" }, native1());
    await screen.findByTestId("gv-panel");
    await waitFor(() => expect(fake.geom?.setNominal).toHaveBeenCalled()); // 선택 없이도 공칭 형상이 바로 보임
    return { server, table: screen.getByRole("table", { name: "파라미터 표" }) };
  };

  it("공칭 형상은 선택 없이 표시, 행 클릭 = 단일 선택(다시 클릭 = 해제), Ctrl/⌘ = 토글 추가, Shift = 범위, [선택 해제] 1개", async () => {
    const { table } = await open12();
    expect(lastHl().moving.size).toBe(0);
    expect(screen.queryByRole("button", { name: "선택 해제" })).toBeNull();
    fireEvent.click(within(table).getByText("CUSH_L_THK_1"));
    expect(selected(table)).toEqual(["CUSH_L_THK_1"]);
    fireEvent.click(within(table).getByText("CUSH_L_THK_1"));
    expect(selected(table)).toEqual([]);
    fireEvent.click(within(table).getByText("CUSH_L_THK_1"));
    fireEvent.click(within(table).getByText("CUSH_L_HOLE_U_1"), { ctrlKey: true });
    fireEvent.click(within(table).getByText("CUSH_L_RIB_T_2"), { metaKey: true });
    expect(selected(table)).toEqual(["CUSH_L_THK_1", "CUSH_L_RIB_T_2", "CUSH_L_HOLE_U_1"]); // 표 순서
    fireEvent.click(within(table).getByText("CUSH_L_HOLE_U_1"), { ctrlKey: true });
    expect(selected(table)).toEqual(["CUSH_L_THK_1", "CUSH_L_RIB_T_2"]);
    fireEvent.click(within(table).getByText("CUSH_L_THK_1"));
    fireEvent.click(within(table).getByText("CUSH_L_HOLE_U_1"), { shiftKey: true });
    expect(selected(table)).toEqual(["CUSH_L_THK_1", "CUSH_L_POCKET_D_1", "CUSH_L_RIB_T_2", "CUSH_L_HOLE_U_1"]);
    // 사용 체크박스 클릭은 선택을 바꾸지 않는다
    fireEvent.click(within(table).getByLabelText("BOX_SHELL_T 사용"));
    expect(isSel(table, "BOX_SHELL_T")).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "선택 해제" }));
    expect(selected(table)).toEqual([]);
    await waitFor(() => expect(lastHl().moving.size).toBe(0));
    expect(screen.queryByRole("button", { name: "선택 해제" })).toBeNull();
  });

  it("다중 선택: 변수마다 다른 색(이동 = 색, 고정 = 옅은 색)·범례, 치수선은 1개일 때만, 선택 행 색 띠", async () => {
    const { table } = await open12();
    fireEvent.click(within(table).getByText("CUSH_L_THK_1"));
    await waitFor(() => expect(lastHl().dims).toHaveLength(2));
    fireEvent.click(within(table).getByText("CUSH_L_HOLE_U_1"), { ctrlKey: true });
    await waitFor(() => expect(lastHl().dims).toEqual([])); // 다중 = 치수선 생략
    const h = lastHl();
    expect(h.paint!.get("CUSH_L#2")).toBe(paintMovingMat(0));
    expect(h.paint!.get("CUSH_L#1")).toBe(paintFixedMat(0));
    expect(h.paint!.get("CUSH_L#12")).toBe(paintMovingMat(1));
    const legend = screen.getByTestId("sel-legend");
    expect(within(legend).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["CUSH_L_THK_1", "CUSH_L_HOLE_U_1"]);
    const sw = within(legend).getAllByRole("listitem").map((li) => (li.firstElementChild as HTMLElement).style.background);
    expect(new Set(sw).size).toBe(2);
    expect((within(table).getByText("CUSH_L_THK_1").closest("tr") as HTMLElement).style.getPropertyValue("--sel-color")).toBe(selectionColor(0));
    expect((within(table).getByText("CUSH_L_HOLE_U_1").closest("tr") as HTMLElement).style.getPropertyValue("--sel-color")).toBe(selectionColor(1));
    // 선택 1개로 줄면 치수선 복귀
    fireEvent.click(within(table).getByText("CUSH_L_HOLE_U_1"), { ctrlKey: true });
    await waitFor(() => expect(lastHl().dims).toHaveLength(2));
    // 3D 대응 없는 행은 범례에서 빠지고 안내
    fireEvent.click(within(table).getByText("BOX_SHELL_T"), { ctrlKey: true });
    expect(await screen.findByText("3D 대응 없음(쉘 두께 등 — 표에서만)")).toBeTruthy();
    expect(within(screen.getByTestId("sel-legend")).getAllByRole("listitem")).toHaveLength(1);
  });

  it("호버: 행에 올리면 임시 하이라이트(선택은 그대로), 떠나면 원복", async () => {
    const { table } = await open12();
    fireEvent.click(within(table).getByText("CUSH_L_THK_1"));
    const tr = within(table).getByText("CUSH_L_POCKET_D_1").closest("tr")!;
    fireEvent.mouseEnter(tr);
    await waitFor(() => expect(lastHl().moving.has("CUSH_L#7")).toBe(true));
    expect(selected(table)).toEqual(["CUSH_L_THK_1"]);
    expect(lastHl().dims).toHaveLength(2); // 선택 1개의 치수선 유지
    fireEvent.mouseLeave(tr);
    await waitFor(() => expect(lastHl().moving.has("CUSH_L#7")).toBe(false));
  });

  it("3D 면 클릭 → 행 선택, Ctrl+면 클릭 = 추가·다시 = 해제, 면 목록에서 Ctrl로 열면 추가", async () => {
    const { table } = await open12();
    act(() => fake.geom!.opts.onPick({ body: "CUSH_L", face: 12 }, false));
    await waitFor(() => expect(selected(table)).toEqual(["CUSH_L_HOLE_U_1"]));
    act(() => fake.geom!.opts.onPick({ body: "CUSH_L", face: 7 }, true));
    await waitFor(() => expect(selected(table)).toEqual(["CUSH_L_POCKET_D_1", "CUSH_L_HOLE_U_1"]));
    act(() => fake.geom!.opts.onPick({ body: "CUSH_L", face: 7 }, true));
    await waitFor(() => expect(selected(table)).toEqual(["CUSH_L_HOLE_U_1"]));
    act(() => fake.geom!.opts.onPick({ body: "CUSH_L", face: 2 }, true));
    const lb = await screen.findByRole("listbox", { name: "이 면을 쓰는 피처" });
    fireEvent.click(within(lb).getByRole("option", { name: "CUSH_L_THK_1" }));
    await waitFor(() => expect(selected(table)).toEqual(["CUSH_L_THK_1", "CUSH_L_HOLE_U_1"]));
  });

  it("그림 탭 = 0개 안내(+첫 변수 보기)·1개 그 PNG·다중 격자", async () => {
    const { table } = await open12();
    const panel = screen.getByTestId("gv-panel");
    fireEvent.click(within(panel).getByRole("tab", { name: "그림" }));
    expect(within(panel).getByTestId("png-empty").textContent).toContain("표에서 변수를 클릭하면");
    fireEvent.click(within(panel).getByRole("button", { name: "첫 변수 보기" }));
    await waitFor(() => expect(selected(table)).toEqual(["CUSH_L_THK_1"]));
    fireEvent.click(within(table).getByText("CUSH_L_THK_1")); // 해제 → 다시 안내
    await waitFor(() => expect(within(panel).getByTestId("png-empty")).toBeTruthy());
    fireEvent.click(within(table).getByText("CUSH_L_HOLE_U_1"));
    const fig = await screen.findByTestId("feature-png");
    expect(fig.textContent).toContain("CUSH_L_HOLE_U_1");
    fireEvent.click(within(table).getByText("CUSH_L_THK_1"), { ctrlKey: true });
    await waitFor(() => expect(within(screen.getByTestId("png-grid")).getAllByTestId("feature-png")).toHaveLength(2));
  });

  it("④: 다중 선택은 하이라이트 전용 — 미리보기 입력은 단일 선택일 때만, 편집값은 유지", async () => {
    renderApp(`${STUDY}/4`, { user: "power", geometry: "native" }, nativeCurrent);
    const { card, table } = await openDetail();
    await waitFor(() => expect(fake.geom?.setNominal).toHaveBeenCalled());
    fireEvent.click(within(table).getByText("CUSH_L_THK_1"));
    fireEvent.change(await within(card).findByLabelText("CUSH_L_THK_1 미리보기 값"), { target: { value: "14" } });
    fireEvent.click(within(table).getByText("CUSH_L_HOLE_U_1"), { ctrlKey: true });
    await waitFor(() => expect(within(card).queryByLabelText("CUSH_L_THK_1 미리보기 값")).toBeNull());
    expect(within(card).getByText("행을 고르면 값을 바꿔 미리볼 수 있습니다")).toBeTruthy();
    expect(within(card).getByRole("button", { name: "선택 해제" })).toBeTruthy();
    fireEvent.click(within(table).getByText("CUSH_L_HOLE_U_1"), { ctrlKey: true });
    expect((await within(card).findByLabelText("CUSH_L_THK_1 미리보기 값") as HTMLInputElement).value).toBe("14");
  });

  it("300행: 표는 고정 높이 상자 안에서 내부 스크롤(페이지는 행 수와 무관), 3D 창 나란히, 3D 면 클릭 → 표 상자만 스크롤", async () => {
    renderApp(`${STUDY}/1`, { user: "power" }, native1(300));
    await screen.findByTestId("gv-panel");
    await waitFor(() => expect(fake.geom?.setNominal).toHaveBeenCalled());
    const table = screen.getByRole("table", { name: "파라미터 표" });
    expect(within(table).getAllByRole("row")).toHaveLength(1 + 306);
    const split = screen.getByTestId("gv-split");
    const box = screen.getByTestId("gv-split-table").querySelector(".table-wrap") as HTMLElement;
    expect(box.contains(table)).toBe(true); // 표 상자(스크롤) ⊂ 분할 영역(고정 높이)
    expect(split.contains(screen.getByTestId("gv-panel"))).toBe(true); // 3D 창은 같은 분할 영역의 옆 칸
    expect(split.parentElement!.querySelectorAll(".table-wrap")).toHaveLength(1);
    // 표 상자 안에서만 스크롤: 상자 scrollTop을 바꾸고 window 스크롤은 건드리지 않는다
    const winScroll = vi.spyOn(window, "scrollTo").mockImplementation(() => undefined);
    const rowEl = within(table).getByText("EXTRA_250").closest("tr") as HTMLElement;
    const rect = (top: number, h: number) => ({ top, bottom: top + h, height: h, left: 0, right: 0, width: 0, x: 0, y: top, toJSON: () => ({}) }) as DOMRect;
    vi.spyOn(box, "getBoundingClientRect").mockReturnValue(rect(100, 500));
    vi.spyOn(box.querySelector("thead")!, "getBoundingClientRect").mockReturnValue(rect(100, 30));
    vi.spyOn(rowEl, "getBoundingClientRect").mockReturnValue(rect(900, 40));
    const into = vi.fn();
    rowEl.scrollIntoView = into;
    act(() => fake.geom!.opts.onPick({ body: "CUSH_L", face: 12 }, false)); // 3D 면 클릭 → 그 행 선택·표 상자 스크롤
    await waitFor(() => expect(selected(table)).toEqual(["CUSH_L_HOLE_U_1"]));
    expect(into).not.toHaveBeenCalled(); // scrollIntoView(페이지 스크롤 유발) 대신 상자 scrollTop 조정
    expect(winScroll).not.toHaveBeenCalled();
    const hole = within(table).getByText("CUSH_L_HOLE_U_1").closest("tr") as HTMLElement;
    vi.spyOn(hole, "getBoundingClientRect").mockReturnValue(rect(900, 40));
    box.scrollTop = 0;
    const { scrollRowIntoView } = await import("../stages/stage4/geomview/selection");
    scrollRowIntoView(box, "CUSH_L_HOLE_U_1");
    expect(box.scrollTop).toBe(340); // 900+40-(100+500)
    // 306행 일괄(Shift 범위) 선택도 한 번의 렌더로 끝난다
    const t0 = performance.now();
    fireEvent.click(within(table).getByText("CUSH_L_THK_1"));
    fireEvent.click(within(table).getByText("EXTRA_299"), { shiftKey: true });
    expect(selected(table).length).toBe(306);
    expect(performance.now() - t0).toBeLessThan(3000);
  });
});

describe("폴백 — 어떤 PC에서도 빈 패널 없음(이유 한 줄 + 그림 + 다시 시도 + 진단)", () => {
  const native12 = (extra = 0) => (s: MockServer) => {
    const params = nativeTrainParams();
    for (let i = 0; i < extra; i++) params.push({ name: `EXTRA_${i}`, raw_nominal: "1 mm", nominal: 1, min: 0.9, max: 1.1, use: false, format: "%.4f", unit: "mm", valid: true, problems: [] });
    Object.assign(s.p2.setups["s-cushion"], { engine: "native", parameters: params, tpl: null, extract_job_id: "j-x" });
    setGvMode(s, {});
  };
  const sel = (table: HTMLElement) => within(table).queryAllByRole("row").filter((r) => r.getAttribute("aria-selected") === "true").map((r) => r.getAttribute("data-row"));
  /** 지연 적재 중의 '불러오는 중…'이 아니라 실제 사유 줄 */
  const reasonNote = async () => {
    await waitFor(() => expect(screen.getByTestId("gv-fallback").textContent).not.toContain("불러오는 중"));
    return screen.getByTestId("gv-fallback");
  };
  const noGl = () => {
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
    resetWebGLCache();
  };

  it("WebGL 없음: 이유 한 줄 + 선택 없음 안내·[첫 변수 보기] + 접힌 진단(브라우저·WebGL 단계·마지막 오류)", async () => {
    noGl();
    renderApp(`${STUDY}/1`, { user: "power" }, native12());
    const note = await reasonNote();
    expect(note.textContent).toBe("이 PC는 WebGL을 쓸 수 없어 그림으로 표시합니다(하드웨어 가속 꺼짐·원격 데스크톱·GPU 없음 추정)");
    expect(screen.queryByRole("button", { name: "다시 시도" })).toBeNull(); // 환경 문제는 재시도 대상 아님
    const table = screen.getByRole("table", { name: "파라미터 표" });
    expect(screen.getByTestId("png-empty")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "첫 변수 보기" }));
    await waitFor(() => expect(sel(table)).toEqual(["CUSH_L_THK_1"]));
    expect(await screen.findByTestId("feature-png")).toBeTruthy();
    const diag = screen.getByTestId("gv-diag");
    expect(diag.tagName).toBe("DETAILS");
    expect(diag.textContent).toContain("브라우저:");
    expect(diag.textContent).toContain("WebGL: none [CONTEXT_NULL]");
    expect(diag.textContent).toContain("마지막 오류: no-webgl");
    expect(fake.geom).toBeNull();
  });

  it("WebGL1만 가능(구버전·드라이버): three는 WebGL2가 필요 → 그림 + WebGL 2 안내", async () => {
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(((id: string) => (id === "webgl" ? {} : null)) as never);
    resetWebGLCache();
    renderApp(`${STUDY}/1`, { user: "power" }, native12());
    expect((await reasonNote()).textContent).toContain("WebGL 2를 지원하지 않아 그림으로 표시합니다");
    expect(screen.getByTestId("gv-diag").textContent).toContain("WebGL: webgl [WEBGL2_UNSUPPORTED]");
  });

  it("three 초기화 예외(컨텍스트 생성 실패) → 그림 폴백 + 원인 코드 + [다시 시도]로 복구", async () => {
    fake.failCreate = new Error("Error creating WebGL context.");
    renderApp(`${STUDY}/1`, { user: "power" }, native12());
    const note = await reasonNote();
    expect(note.textContent).toContain("3D 화면을 시작하지 못해 그림으로 표시합니다(그래픽 초기화 오류: Error: Error creating WebGL context.)");
    fake.failCreate = null;
    fireEvent.click(within(note).getByRole("button", { name: "다시 시도" }));
    await screen.findByTestId("gv-panel");
    await waitFor(() => expect(fake.geom?.setNominal).toHaveBeenCalled());
  });

  it("3D 패널 렌더 중 예외 → ErrorBoundary가 그림 폴백으로 대체, 다시 시도 = 패널 복구", async () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    fake.hlThrow = new Error("boom");
    renderApp(`${STUDY}/1`, { user: "power" }, native12());
    const note = await reasonNote();
    expect(note.textContent).toContain("그래픽 초기화 오류: Error: boom");
    expect(screen.queryByTestId("gv-panel")).toBeNull();
    fake.hlThrow = null;
    fireEvent.click(within(note).getByRole("button", { name: "다시 시도" }));
    await screen.findByTestId("gv-panel");
  });

  it("GLB 받기 실패(410) → 원인 코드 + 그림, 다시 시도", async () => {
    const { server } = renderApp(`${STUDY}/1`, { user: "power" }, native12());
    const orig = server.handle.bind(server);
    let fail = true;
    server.handle = (m, p, q, b, h) => (fail && m === "GET" && /\/artifacts\/[^/]+\/media$/.test(p) && server.artifacts.find((a) => p.includes(a.id))?.kind === "GEOM_VIEW_GLB" ? err(410, "ARTIFACT_EXPIRED", "정리됨") : orig(m, p, q, b, h));
    const note = await reasonNote();
    expect(note.textContent).toContain("3D 형상 파일을 불러오지 못해 그림으로 표시합니다(HTTP 410 ARTIFACT_EXPIRED)");
    fail = false;
    fireEvent.click(within(note).getByRole("button", { name: "다시 시도" }));
    await screen.findByTestId("gv-panel");
  });

  it("PNG 410 → 조용히 삼키지 않고 원인 + [다시 시도], 재시도하면 그림 표시", async () => {
    noGl();
    const { server } = renderApp(`${STUDY}/1`, { user: "power" }, native12());
    const orig = server.handle.bind(server);
    let fail = true;
    server.handle = (m, p, q, b, h) => (fail && m === "GET" && /\/artifacts\/[^/]+\/media$/.test(p) && server.artifacts.find((a) => p.includes(a.id))?.kind === "FEATURE_PNG" ? err(410, "ARTIFACT_EXPIRED", "정리됨") : orig(m, p, q, b, h));
    const table = await screen.findByRole("table", { name: "파라미터 표" });
    await reasonNote();
    fireEvent.click(within(table).getByText("CUSH_L_THK_1"));
    const alert = await screen.findByTestId("png-error");
    expect(alert.textContent).toContain("그림을 불러오지 못했습니다(HTTP 410 ARTIFACT_EXPIRED)");
    fail = false;
    fireEvent.click(within(alert).getByRole("button", { name: "다시 시도" }));
    await waitFor(() => expect(screen.getByTestId("feature-png").querySelector("img")).toBeTruthy());
    expect(screen.queryByTestId("png-error")).toBeNull();
  });

  it("다중 선택: 선택 변수 PNG를 격자로(범례 색 테두리), 최대 8개 + '외 N개', PNG 없는 변수는 자리 표시", async () => {
    noGl();
    renderApp(`${STUDY}/1`, { user: "power" }, native12(10));
    const table = await screen.findByRole("table", { name: "파라미터 표" });
    await reasonNote();
    fireEvent.click(within(table).getByText("CUSH_L_THK_1"));
    fireEvent.click(within(table).getByText("CUSH_L_POCKET_D_1"), { ctrlKey: true });
    const grid = await screen.findByTestId("png-grid");
    const figs = within(grid).getAllByTestId("feature-png");
    expect(figs.map((f) => f.querySelector("figcaption")!.textContent)).toEqual(["CUSH_L_THK_1", "CUSH_L_POCKET_D_1"]);
    expect(figs.map((f) => f.style.borderColor)).toEqual([hexToRgb(selectionColor(0)), hexToRgb(selectionColor(1))]);
    fireEvent.click(within(table).getByText("CUSH_L_THK_1"));
    fireEvent.click(within(table).getByText("EXTRA_9"), { shiftKey: true });
    await waitFor(() => expect(sel(table).length).toBe(16)); // THK~EXTRA_9 = 6 + 10 행(리브 위치 CUSH_L_RIB_U_1 포함)
    const g2 = screen.getByTestId("png-grid");
    expect(g2.children).toHaveLength(8);
    expect(screen.getByText("외 8개는 표시하지 않습니다(최대 8개)")).toBeTruthy();
    expect(within(g2).getByText("EXTRA_0").closest("figure")!.textContent).toContain("그림 없음");
  });
});

const hexToRgb = (h: string) => {
  const n = parseInt(h.slice(1), 16);
  return `rgb(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255})`;
};
