// V3-S12-5(phase3.md §17.6·§17.7) → S14: ⑤ 결과분석으로 이동한 설계공간 지도 화면(입력만 바꿔 같은 기준으로 통과) — 탭 전환·저장, 방법·색 값·커브 드롭다운(계열 1개면 숨김), 색 막대 최소·최대 숫자,
// 툴팁 내용, 점 클릭 → 표 행 선택·커브 강조, 표 행 클릭 → 지도 강조, 커브 계열 공유, 평행 좌표 브러싱(흐림·개수·해제),
// 진행 중 배치에서 succeeded가 늘 때만 재요청, 목 라우트(openapi 모양). 목 서버(mock/predictBatch.ts) B-002: 20 run 중 성공 18.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { renderApp, STUDY } from "../test/render";
import { recordCalls } from "../test/recordCalls";
import type { MockServer } from "../mock/server";
import type { DesignMap } from "../api/designMap";
import { fmtNum } from "../lib/format";
import { PREFS_KEY, TAB_KEY, TEXT } from "../analysis/viz/designMap/designMapData";
import specJson from "../../../backend/openapi.json";

const BATCH = `${STUDY}/analysis?source=batch&id=pb-2`;
const S1 = "Node 10234 변위 [mm]";
const S2 = "Node 20811 변위 [mm]";

function getMap(server: MockServer, id = "pb-2"): DesignMap {
  return server.handle("GET", `/predict-batches/${id}/design-map`, new URLSearchParams(), null, new Headers()).body as DesignMap;
}

async function openMap() {
  const card = await screen.findByRole("region", { name: "응답 그래프" });
  fireEvent.click(within(card).getByRole("tab", { name: "설계공간 지도" }));
  await within(card).findByTestId("design-map");
  return card;
}

const methodBtn = (card: HTMLElement, name: string) => within(within(card).getByRole("group", { name: "지도 방법" })).getByRole("button", { name });

describe("⑤ 설계공간 지도 화면 (V3-S12-5, S14 이동)", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it("탭 전환·저장: 기본 변수–응답, 설계공간 지도 고르면 기억(새로 열어도 유지), 기본 PLS·화살표·색 값 커브 최대값", async () => {
    const first = renderApp(BATCH, { user: "power" });
    const card = await screen.findByRole("region", { name: "응답 그래프" });
    expect(within(card).getByRole("tab", { name: "변수–응답" }).getAttribute("aria-selected")).toBe("true");
    expect(await within(card).findByTestId("plot2d")).toBeTruthy();
    await openMap();
    expect(localStorage.getItem(TAB_KEY)).toBe("map");
    first.unmount();
    renderApp(BATCH, { user: "power" });
    const c2 = await screen.findByRole("region", { name: "응답 그래프" });
    expect(within(c2).getByRole("tab", { name: "설계공간 지도" }).getAttribute("aria-selected")).toBe("true");
    expect(await within(c2).findByTestId("dm-pls")).toBeTruthy();
    expect(methodBtn(c2, "PLS").getAttribute("aria-pressed")).toBe("true");
    expect((within(c2).getByLabelText("색 값") as HTMLSelectElement).value).toBe("curve:max");
    expect(within(c2).getByTestId("dm-xlabel").textContent).toMatch(/^.*PLS1 \(X \d+% · 값 \d+%\)$/);
    expect(within(c2).getByTestId("dm-xlabel").querySelector("title")!.textContent).toBe(TEXT.plsTip);
    expect(within(c2).getAllByTestId("dm-arrow")).toHaveLength(4); // 유효 변수 4개
    expect(within(c2).getAllByRole("button", { name: /^지도 점 DOE #\d+$/ })).toHaveLength(18);
    expect(within(c2).getByTestId("dm-notes").textContent).toContain("제외: 실패·미완료 2");
    expect(within(c2).getByTestId("dm-notes").textContent).toContain(TEXT.footer);
  });

  it("localStorage가 막혀도 기본(변수–응답)으로 렌더하고 지도로 전환된다", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    renderApp(BATCH, { user: "power" });
    const card = await openMap();
    expect(await within(card).findByTestId("dm-pls")).toBeTruthy();
  });

  it("방법(PCA·평행 좌표)·색 값·커브 드롭다운·화살표 토글, 선택 저장", async () => {
    renderApp(BATCH, { user: "power" });
    const card = await openMap();
    const metric = within(card).getByLabelText("색 값") as HTMLSelectElement;
    expect([...metric.options].map((o) => o.textContent)).toEqual([
      "커브 최대값", "커브 최소값", "커브 |최대|", "MaxDisp 최대(RESP) [mm]", "MaxDisp 최소(RESP) [mm]", "MaxStress 최대(RESP) [MPa]", "MaxStress 최소(RESP) [MPa]", "MaxStress (MAX) [MPa]", "MaxDisp (MAX) [mm]", // S17 D3-65 보강 2: 템플릿 성능(perf:)
    ]);
    const curve = within(card).getByLabelText("커브") as HTMLSelectElement;
    expect([...curve.options].map((o) => o.value)).toEqual([S1, S2]);
    fireEvent.change(metric, { target: { value: "resp:MaxStress_MAX" } });
    expect(within(card).queryByLabelText("커브")).toBeNull(); // RESP 지표 → 커브 선택 숨김
    expect(within(card).getByTestId("dm-colorbar").textContent).toContain("MaxStress 최대(RESP) [MPa]");
    fireEvent.click(methodBtn(card, "PCA"));
    expect(within(card).getByTestId("dm-pca")).toBeTruthy();
    expect(within(card).getByTestId("dm-xlabel").textContent).toMatch(/PC1 \(X 분산 \d+\.\d%\)$/);
    expect(within(card).getByTestId("dm-ylabel").textContent).toMatch(/PC2 \(X 분산 \d+\.\d%\)$/);
    fireEvent.click(within(card).getByRole("checkbox", { name: "변수 화살표" }));
    expect(within(card).queryAllByTestId("dm-arrow")).toHaveLength(0);
    fireEvent.click(methodBtn(card, "평행 좌표"));
    expect(within(card).getByTestId("dm-pc")).toBeTruthy();
    expect(within(card).queryByRole("checkbox", { name: "변수 화살표" })).toBeNull();
    expect(within(card).getAllByRole("button", { name: /^선 DOE #\d+$/ })).toHaveLength(18);
    expect(JSON.parse(localStorage.getItem(PREFS_KEY)!)).toEqual({ method: "pc", metric: "resp:MaxStress_MAX", series: S1, arrows: false });
  });

  it("계열이 1개면 커브 드롭다운 숨김, 저장된 값이 목록에 없으면 기본으로", async () => {
    localStorage.setItem(PREFS_KEY, JSON.stringify({ method: "zzz", metric: "resp:Gone_MAX", series: "없는 계열", arrows: "x" }));
    renderApp(BATCH, { user: "power" }, (s) => {
      for (const a of s.artifacts.filter((x) => x.kind === "CURVE_JSON")) {
        const c = JSON.parse(a.body) as { series: unknown[] };
        a.body = JSON.stringify({ ...c, series: c.series.slice(0, 1) });
      }
    });
    const card = await openMap();
    expect(methodBtn(card, "PLS").getAttribute("aria-pressed")).toBe("true");
    expect((within(card).getByLabelText("색 값") as HTMLSelectElement).value).toBe("curve:max");
    expect(within(card).queryByLabelText("커브")).toBeNull();
    expect(within(card).getAllByTestId("dm-arrow")).toHaveLength(4);
  });

  it("색 막대: 위 최대·아래 최소 숫자(선택 커브 최대값·RESP), 머리 = 지표 라벨·단위", async () => {
    const { server } = renderApp(BATCH, { user: "power" });
    const card = await openMap();
    const vals = getMap(server).runs.filter((r) => r.state === "SUCCEEDED").map((r) => r.curve![S1].max);
    expect(vals).toHaveLength(18);
    const bar = within(card).getByTestId("dm-colorbar");
    expect(within(bar).getByTestId("dm-cb-max").textContent).toBe(fmtNum(Math.max(...vals)));
    expect(within(bar).getByTestId("dm-cb-min").textContent).toBe(fmtNum(Math.min(...vals)));
    expect(bar.querySelector("figcaption")!.textContent).toBe("커브 최대값");
    // RESP 지표로 바꾸면 숫자·머리(단위)도
    fireEvent.change(within(card).getByLabelText("색 값"), { target: { value: "resp:MaxDisp_MAX" } });
    const disp = getMap(server).runs.filter((r) => r.resp).map((r) => r.resp!.MaxDisp_MAX);
    expect(within(bar).getByTestId("dm-cb-max").textContent).toBe(fmtNum(Math.max(...disp)));
    expect(within(bar).getByTestId("dm-cb-min").textContent).toBe(fmtNum(Math.min(...disp)));
    expect(bar.querySelector("figcaption")!.textContent).toBe("MaxDisp 최대(RESP) [mm]");
  });

  it("값이 모두 같으면 PLS 대신 PCA + 문구, 색 1개·색 막대 숫자 1개", async () => {
    renderApp(BATCH, { user: "power" }, (s) => {
      for (const a of s.artifacts.filter((x) => x.kind === "CURVE_JSON")) a.body = JSON.stringify({ file: "a.xy", series: [{ name: "flat", x: [0, 1], y: [0, 5] }], note: null });
    });
    const card = await openMap();
    expect(within(card).getByTestId("dm-pca")).toBeTruthy();
    expect(within(card).getByTestId("dm-note").textContent).toBe("값이 모두 같아 PLS를 계산할 수 없습니다 — PCA로 표시");
    expect(within(card).getByTestId("dm-cb-single").textContent).toBe("5");
    expect(within(card).queryByTestId("dm-cb-max")).toBeNull();
    const fills = new Set(within(card).getAllByRole("button", { name: /^지도 점/ }).map((c) => c.getAttribute("fill")));
    expect(fills.size).toBe(1);
  });

  it("툴팁(DOE#·변수·값), 점 클릭 → 표 행 선택·커브 강조, 표 행 클릭 → 지도 강조(맨 위)", async () => {
    const { server } = renderApp(BATCH, { user: "power" });
    const card = await openMap();
    const run3 = getMap(server).runs.find((r) => r.doe_no === 3)!;
    const pt = within(card).getByRole("button", { name: "지도 점 DOE #3" });
    fireEvent.mouseEnter(pt);
    const tip = within(card).getByTestId("dm-tip");
    expect([...tip.children].map((d) => d.textContent)).toEqual([
      "DOE #3 · run__00003",
      ["THK_TOP", "THK_FOAM", "E_FOAM", "RIB_N"].map((n) => `${n} ${fmtNum(run3.values[n])}`).join(" · "),
      `커브 최대값 ${fmtNum(run3.curve![S1].max)}`,
    ]);
    fireEvent.mouseLeave(pt);
    expect(within(card).queryByTestId("dm-tip")).toBeNull();
    fireEvent.click(pt);
    expect(screen.getByTestId("row-3").className).toContain("selected");
    expect(within(card).getByRole("button", { name: "지도 점 DOE #3" }).getAttribute("aria-pressed")).toBe("true");
    // 커브 탭(S14: 커브 겹쳐보기는 탭 안) — 고른 run만 진하게
    fireEvent.click(within(card).getByRole("tab", { name: "커브" }));
    const curves = within(card).getByRole("region", { name: "커브 겹쳐보기" });
    await waitFor(() => expect(curves.querySelectorAll("path.overlay.on").length).toBe(1));
    fireEvent.click(within(card).getByRole("tab", { name: "설계공간 지도" }));
    // 표에서 다른 행 → 지도 강조가 따라가고 맨 위(마지막)에 그린다
    fireEvent.click(screen.getByRole("button", { name: "DOE #9 선택" }));
    const p9 = within(card).getByRole("button", { name: "지도 점 DOE #9" });
    expect(p9.getAttribute("aria-pressed")).toBe("true");
    expect(p9.getAttribute("class")).toBe("dm-pt on");
    const pts = within(card).getAllByRole("button", { name: /^지도 점 DOE #\d+$/ });
    expect(pts[pts.length - 1]).toBe(p9);
  });

  it("커브 계열 공유: 지도에서 바꾸면 커브 탭도, 커브 탭에서 바꾸면 지도도", async () => {
    renderApp(BATCH, { user: "power" });
    const card = await openMap();
    fireEvent.click(within(card).getByRole("tab", { name: "커브" }));
    const overlaySel = (await within(card).findByLabelText("계열")) as HTMLSelectElement;
    expect(overlaySel.value).toBe(S1);
    fireEvent.click(within(card).getByRole("tab", { name: "설계공간 지도" }));
    fireEvent.change(within(card).getByLabelText("커브"), { target: { value: S2 } });
    fireEvent.click(within(card).getByRole("tab", { name: "커브" }));
    const curves = within(card).getByRole("region", { name: "커브 겹쳐보기" });
    await waitFor(() => expect((within(curves).getByLabelText("계열") as HTMLSelectElement).value).toBe(S2));
    expect(within(curves).getByRole("img").getAttribute("aria-label")).toBe(`커브 겹쳐보기: ${S2}`);
    fireEvent.change(within(curves).getByLabelText("계열"), { target: { value: S1 } });
    fireEvent.click(within(card).getByRole("tab", { name: "설계공간 지도" }));
    await waitFor(() => expect((within(card).getByLabelText("커브") as HTMLSelectElement).value).toBe(S1));
  });

  it("평행 좌표 값 축 브러싱: 범위 밖 선 흐림·머리 개수, 더블클릭·범위 해제로 해제", async () => {
    renderApp(BATCH, { user: "power" });
    const card = await openMap();
    fireEvent.click(methodBtn(card, "평행 좌표"));
    const area = within(card).getByTestId("dm-brush-area");
    expect(within(card).getByTestId("dm-brush-head").textContent).toBe("값 축을 세로로 끌어 범위를 고릅니다 · run 18개");
    // 값 축(높이 230, 위 여백 26): y 40 ~ 150 끌기
    fireEvent.mouseDown(area, { clientY: 40 });
    fireEvent.mouseMove(area, { clientY: 150 });
    fireEvent.mouseUp(area, { clientY: 150 });
    const head = within(card).getByTestId("dm-brush-head").textContent!;
    const m = head.match(/^값 (.+) ~ (.+) · (\d+)개 run범위 해제$/);
    expect(m).toBeTruthy();
    const k = Number(m![3]);
    const lines = within(card).getAllByRole("button", { name: /^선 DOE #\d+$/ });
    const dim = lines.filter((l) => l.getAttribute("class")!.includes("dim"));
    expect(k).toBeGreaterThan(0);
    expect(k).toBeLessThan(18);
    expect(dim).toHaveLength(18 - k);
    fireEvent.doubleClick(area);
    expect(within(card).getByTestId("dm-brush-head").textContent).toContain("run 18개");
    expect(within(card).getAllByRole("button", { name: /^선 DOE/ }).filter((l) => l.getAttribute("class")!.includes("dim"))).toHaveLength(0);
    fireEvent.mouseDown(area, { clientY: 60 });
    fireEvent.mouseMove(area, { clientY: 200 });
    fireEvent.mouseUp(area, { clientY: 200 });
    fireEvent.click(within(card).getByRole("button", { name: "범위 해제" }));
    expect(within(card).queryByRole("button", { name: "범위 해제" })).toBeNull();
    // 선 클릭 = 행 선택
    fireEvent.click(within(card).getByRole("button", { name: "선 DOE #4" }));
    await waitFor(() => expect(screen.getByTestId("row-4").className).toContain("selected"));
  });

  it("진행 중 배치: 5초 폴링마다 받지 않고 완료 수(succeeded)가 늘 때만 다시 받는다", async () => {
    const { server } = renderApp(`${STUDY}/analysis?source=batch&id=pb-3`, { user: "power", batchDemo: "running" });
    const calls = recordCalls(server);
    const card = await openMap();
    const dmCalls = () => calls.filter((c) => c === "GET /predict-batches/pb-3/design-map").length;
    await waitFor(() => expect(dmCalls()).toBe(1));
    const polls = () => calls.filter((c) => c === "GET /predict-batches/pb-3").length;
    const p0 = polls();
    await waitFor(() => expect(polls()).toBeGreaterThan(p0 + 2)); // 배치 폴링은 계속
    expect(dmCalls()).toBe(1);
    const run = server.jobs.find((j) => j.state === "RUNNING" && (j.params as { batch_run?: { batch_id: string } }).batch_run?.batch_id === "pb-3")!;
    (run as unknown as { _pct: number })._pct = 100;
    server.tick();
    await waitFor(() => expect(dmCalls()).toBe(2));
    expect(within(card).getAllByRole("button", { name: /^지도 점 DOE #\d+$/ })).toHaveLength(8);
  });
});

// ---- 목 계약 ------------------------------------------------------------------------------------

type Sch = { $ref?: string; required?: string[]; properties?: Record<string, Sch>; items?: Sch; anyOf?: Sch[]; type?: string; additionalProperties?: Sch | boolean };
const spec = specJson as unknown as { paths: Record<string, Record<string, { responses: Record<string, { content: Record<string, { schema: Sch }> }> }>>; components: { schemas: Record<string, Sch> } };
const resolve = (s: Sch): Sch => (s.$ref ? spec.components.schemas[s.$ref.split("/").pop()!] : s);
function problems(value: unknown, s0: Sch, at: string): string[] {
  const s = resolve(s0);
  if (s.anyOf) {
    if (value === null && s.anyOf.some((x) => x.type === "null")) return [];
    const opts = s.anyOf.filter((x) => x.type !== "null");
    return opts.length ? problems(value, opts[0], at) : [];
  }
  if (Array.isArray(value)) return s.items ? value.flatMap((v, i) => problems(v, s.items!, `${at}[${i}]`)) : [];
  if (value && typeof value === "object") {
    const o = value as Record<string, unknown>;
    if (s.properties) {
      const out = (s.required ?? []).filter((k) => !(k in o)).map((k) => `${at}.${k} 없음`);
      for (const [k, ps] of Object.entries(s.properties)) if (k in o && o[k] !== undefined) out.push(...problems(o[k], ps, `${at}.${k}`));
      return out;
    }
    if (s.additionalProperties && typeof s.additionalProperties === "object") return Object.entries(o).flatMap(([k, v]) => problems(v, s.additionalProperties as Sch, `${at}.${k}`));
  }
  return [];
}

describe("목 계약: GET /predict-batches/{bid}/design-map", () => {
  it("응답이 openapi DesignMap 모양(중첩 curve 통계 포함), 실패 run null, 계열·지표 규칙", () => {
    const { server } = renderApp(BATCH, { user: "power" });
    const r = server.handle("GET", "/predict-batches/pb-2/design-map", new URLSearchParams(), null, new Headers());
    expect(r.status).toBe(200);
    const schema = spec.paths["/physicsai/api/predict-batches/{batch_id}/design-map"].get.responses["200"].content["application/json"].schema;
    expect(problems(r.body, schema, "$")).toEqual([]);
    const d = r.body as DesignMap;
    expect(d.series).toEqual([S1, S2]);
    expect(d.parameters.map((p) => [p.name, p.integer])).toEqual([["THK_TOP", false], ["THK_FOAM", false], ["E_FOAM", false], ["RIB_N", true]]);
    expect(d.counts).toEqual({ total: 20, succeeded: 18, no_curve: 0, no_resp: 0 });
    for (const x of d.runs.filter((x) => x.state !== "SUCCEEDED")) expect([x.curve, x.resp, x.tbl]).toEqual([null, null, null]);
    expect(d.metrics.filter((m) => m.id.startsWith("tbl:"))).toEqual([]);
    expect(server.handle("GET", "/predict-batches/nope/design-map", new URLSearchParams(), null, new Headers()).status).toBe(404);
  });
});
