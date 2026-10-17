// V3-S14-5·6(phase3.md §19.6·§19.7·§19.9): ⑤ 결과분석 화면 — 출처 전환·저장·쿼리 우선, 빈 상태, 탭(커브는 출처 b에서 숨김), 영향도 비활성 문구,
// 이동한 변수–응답(2D·3D·안내)·커브 겹쳐보기 시험(V3-S12-3~5 기준 그대로), 겹쳐 보기(이름 집합·공통 응답·범례·색 막대 합집합·메타).
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { renderApp, STUDY } from "../test/render";
import { recordCalls } from "../test/recordCalls";
import type { MockServer } from "../mock/server";
import type { DoeResultTable } from "../api/analysis";
import { PLOT_HINT } from "../stages/stage4/batch/batchTable";
import { NO_WEBGL_TEXT } from "../analysis/viz/ResponsePlot3D";
import { EMPTY_TEXT, SOURCE_KEY } from "../stages/stageAnalysis/SourcePicker";
import { NO3D_COMPARE_TEXT } from "../stages/stageAnalysis/AnalysisTabs";
import { META_DIFF_TEXT, NO_COMMON_RESP_TEXT } from "../analysis/compare";
import { NOT_LHS_TEXT, REF_ONLY_TEXT } from "../analysis/influence";
import { TAB_KEY } from "../analysis/viz/designMap/designMapData";
import { fmtNum } from "../lib/format";
import specJson from "../../../backend/openapi.json";

const plotly = vi.hoisted(() => ({ react: vi.fn(async (el: HTMLElement) => el), purge: vi.fn() }));
vi.mock("plotly.js-gl3d-dist-min", () => ({ default: plotly }));

const A = `${STUDY}/analysis`;
const BATCH = `${A}?source=batch&id=pb-2`;
const DOE = `${A}?source=doe&id=doe-1`;
const withResp = (s: MockServer) => {
  s.p2.does[0].has_run_responses = true;
};
/** doe-1의 파라미터 이름을 pb-2 템플릿(THK_TOP·THK_FOAM·E_FOAM·RIB_N)과 같게 */
const sameNames = (s: MockServer) => {
  withResp(s);
  s.p2.doeSamples["doe-1"] = s.p2.doeSamples["doe-1"].map((r) => ({ ...r, values: { THK_TOP: r.values.THK_TOP, THK_FOAM: r.values.THK_FOAM, E_FOAM: 6 + (r.values.RIB_H % 5), RIB_N: r.values.RIB_N } }));
};
const resultTable = (server: MockServer, id = "doe-1") => server.handle("GET", `/train-does/${id}/result-table`, new URLSearchParams(), null, new Headers()).body as DoeResultTable;
const srcSelect = (slot = "기본") => screen.findByRole("combobox", { name: `${slot} 출처 선택` }) as Promise<HTMLSelectElement>;
const tab = (card: HTMLElement, name: string) => within(card).getByRole("tab", { name });

describe("⑤ 결과분석 화면: 출처·탭·빈 상태 (V3-S14-5)", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it("기본 출처 = 완료 배치 첫 번째, 세그먼트로 해석 DOE 전환 → 표·저장(physicsai.analysis.source), 새로 열어도 유지", async () => {
    const first = renderApp(A, { user: "power" }, withResp);
    expect(((await srcSelect()).value)).toBe("pb-2");
    await screen.findByRole("region", { name: "결과 표 — B-002" });
    const seg = screen.getByRole("group", { name: "기본 출처" });
    expect(within(seg).getAllByRole("button").map((b) => b.textContent)).toEqual(["일괄 예측 결과(예측)", "해석 DOE 결과(해석)"]);
    fireEvent.click(within(seg).getByRole("button", { name: "해석 DOE 결과(해석)" }));
    await screen.findByRole("region", { name: "결과 표 — LatinHyperCube" });
    expect(JSON.parse(localStorage.getItem(SOURCE_KEY)!)).toEqual({ kind: "doe", id: "doe-1" });
    // 표 값 = result-table API (수집된 24 run만 응답 있음)
    const t = resultTable(first.server);
    expect(t.rows).toHaveLength(30);
    expect(screen.getAllByTestId(/^row-\d+$/)).toHaveLength(30);
    first.unmount();
    renderApp(A, { user: "power" }, withResp);
    await screen.findByRole("region", { name: "결과 표 — LatinHyperCube" });
    expect((await srcSelect()).value).toBe("doe-1");
  });

  it("쿼리가 저장값보다 우선, 저장 실패(localStorage 막힘)여도 렌더", async () => {
    localStorage.setItem(SOURCE_KEY, JSON.stringify({ kind: "doe", id: "doe-1" }));
    renderApp(BATCH, { user: "power" });
    await screen.findByRole("region", { name: "결과 표 — B-002" });
    expect((await srcSelect()).value).toBe("pb-2");
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    fireEvent.click(within(screen.getByRole("group", { name: "기본 출처" })).getByRole("button", { name: "해석 DOE 결과(해석)" }));
    await screen.findByRole("region", { name: "결과 표 — LatinHyperCube" });
  });

  it("빈 상태: 완료 배치도 해석 DOE도 없으면 안내 문구", async () => {
    renderApp(A, { user: "power" }, (s) => {
      s.batches.length = 0;
      s.p2.does.length = 0;
    });
    expect((await screen.findByTestId("analysis-empty")).textContent).toBe(EMPTY_TEXT);
  });

  it("탭: 출처 a = 변수–응답·설계공간 지도·영향도·커브, 출처 b = 커브 숨김(저장된 curve 탭이면 변수–응답으로)", async () => {
    localStorage.setItem(TAB_KEY, "curve");
    renderApp(DOE, { user: "power" }, withResp);
    const card = await screen.findByRole("region", { name: "응답 그래프" });
    expect(within(card).getAllByRole("tab").map((t) => t.textContent)).toEqual(["변수–응답", "설계공간 지도", "영향도"]);
    expect(tab(card, "변수–응답").getAttribute("aria-selected")).toBe("true");
    expect(await within(card).findByTestId("plot2d")).toBeTruthy();
    // 출처 a로 바꾸면 커브 탭이 나온다
    fireEvent.click(within(screen.getByRole("group", { name: "기본 출처" })).getByRole("button", { name: "일괄 예측 결과(예측)" }));
    await screen.findByRole("region", { name: "결과 표 — B-002" });
    expect(within(screen.getByRole("region", { name: "응답 그래프" })).getAllByRole("tab").map((t) => t.textContent)).toEqual(["변수–응답", "설계공간 지도", "영향도", "커브"]);
  });

  it("해석 DOE 설계공간 지도: 색 값 = 응답 이름(커브 지표 없음), 점 = 수집된 24 run", async () => {
    renderApp(DOE, { user: "power" }, withResp);
    const card = await screen.findByRole("region", { name: "응답 그래프" });
    fireEvent.click(tab(card, "설계공간 지도"));
    await within(card).findByTestId("design-map");
    const metric = within(card).getByLabelText("색 값") as HTMLSelectElement;
    expect([...metric.options].map((o) => o.textContent)).toEqual(["MaxStress", "MaxDisp", "Energy"]);
    expect(within(card).getAllByRole("button", { name: /^지도 점 DOE #\d+$/ })).toHaveLength(24);
    expect(within(card).queryByLabelText("커브")).toBeNull();
    expect(within(card).getByTestId("dm-notes").textContent).toContain("제외: 실패·미완료 6");
  });

  it("영향도: LHS 해석 DOE는 PRCC·SRC 표(|PRCC| 내림차순)와 R² 한 줄", async () => {
    renderApp(DOE, { user: "power" }, withResp);
    const card = await screen.findByRole("region", { name: "응답 그래프" });
    fireEvent.click(tab(card, "영향도"));
    const inf = await within(card).findByTestId("influence");
    const rows = within(inf).getAllByTestId(/^inf-/);
    expect(rows.map((r) => r.getAttribute("data-testid"))).toHaveLength(4);
    const prcc = rows.map((r) => Number(r.querySelectorAll("td")[1].textContent));
    const abs = prcc.map(Math.abs);
    expect([...abs].sort((x, y) => y - x)).toEqual(abs);
    expect(within(inf).getByTestId("influence-r2").textContent).toMatch(/^R² \d\.\d\d$/);
    // 응답을 바꾸면 값도 바뀐다(MaxStress → MaxDisp)
    fireEvent.click(screen.getByRole("radio", { name: "MaxDisp" }));
    expect(within(inf).getByText(/응답/).textContent).toContain("MaxDisp");
    expect(within(card).queryByTestId("influence-ref")).toBeNull();
  });

  it("영향도 비활성: 비 LHS DOE·응답 없는 DOE·유효 run 부족", async () => {
    const r1 = renderApp(DOE, { user: "power" }, (s) => {
      withResp(s);
      s.p2.does[0].doe_type = "TYPE_FULLFACTORIAL";
    });
    let card = await screen.findByRole("region", { name: "응답 그래프" });
    fireEvent.click(tab(card, "영향도"));
    expect((await within(card).findByTestId("influence-off")).textContent).toBe(NOT_LHS_TEXT);
    r1.unmount();
    const r2 = renderApp(DOE, { user: "power" }); // 시드: 응답 파일 없음
    card = await screen.findByRole("region", { name: "응답 그래프" });
    fireEvent.click(tab(card, "영향도"));
    expect((await within(card).findByTestId("influence-off")).textContent).toContain("응답이 없어");
    expect((await screen.findAllByTestId("table-note"))[0].textContent).toBe("응답 파일이 없습니다");
    expect(screen.getByTestId("no-resp").textContent).toBe("응답 없음");
    r2.unmount();
    renderApp(DOE, { user: "power" }, (s) => {
      withResp(s);
      s.p2.runs["doe-1"].forEach((r, i) => (r.state = i < 5 ? "COLLECTED" : "SOLVE_FAILED")); // 유효 5 < p+2 = 6
    });
    card = await screen.findByRole("region", { name: "응답 그래프" });
    fireEvent.click(tab(card, "영향도"));
    expect((await within(card).findByTestId("influence-off")).textContent).toBe("영향도에는 유효 run이 6개 이상 필요합니다(현재 5개)");
  });

  it("출처 a(예측 배치) 영향도: LHS 배치는 안내 없음, 표(TABLE) 배치는 '참고용' 회색 안내", async () => {
    const r1 = renderApp(BATCH, { user: "power" });
    let card = await screen.findByRole("region", { name: "응답 그래프" });
    fireEvent.click(tab(card, "영향도"));
    await within(card).findByTestId("influence");
    expect(within(card).getAllByTestId(/^inf-/)).toHaveLength(4);
    expect(within(card).queryByTestId("influence-ref")).toBeNull();
    r1.unmount();
    renderApp(BATCH, { user: "power" }, (s) => {
      s.batches.find((b) => b.id === "pb-2")!.source_kind = "TABLE";
    });
    card = await screen.findByRole("region", { name: "응답 그래프" });
    fireEvent.click(tab(card, "영향도"));
    expect((await within(card).findByTestId("influence-ref")).textContent).toContain(REF_ONLY_TEXT);
  });
});

describe("⑤ 이동한 분석 화면 시험 (V3-S12-3~5 기준 그대로, 입력만 ⑤)", () => {
  afterEach(() => vi.restoreAllMocks());

  it("응답 그래프 선택 규칙: 변수 1+응답 1 = 2D, 변수 2+응답 1 = 3D(plotly 동적 import), 그 밖 = 회색 안내", async () => {
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation((() => ({})) as never);
    renderApp(BATCH, { user: "power" });
    await screen.findByRole("region", { name: "결과 표 — B-002" });
    const plot = screen.getByRole("region", { name: "응답 그래프" });
    expect(((await screen.findByRole("checkbox", { name: "THK_TOP" })) as HTMLInputElement).checked).toBe(true);
    expect((screen.getByRole("radio", { name: "MaxStress" }) as HTMLInputElement).checked).toBe(true);
    expect(within(plot).getByTestId("plot2d")).toBeTruthy();
    expect(within(plot).getAllByRole("button", { name: /^점 DOE #\d+$/ })).toHaveLength(18);
    // 점 클릭 = 행 선택
    fireEvent.click(within(plot).getByRole("button", { name: "점 DOE #3" }));
    expect(screen.getByTestId("row-3").className).toContain("selected");
    fireEvent.click(screen.getByRole("radio", { name: "MaxDisp" }));
    expect(within(plot).getByRole("img").getAttribute("aria-label")).toBe("응답 그래프 2D: THK_TOP – MaxDisp");
    fireEvent.click(screen.getByRole("checkbox", { name: "RIB_N" }));
    expect(await within(plot).findByTestId("plot3d")).toBeTruthy();
    await waitFor(() => expect(plotly.react).toHaveBeenCalled());
    const [, data] = plotly.react.mock.calls[plotly.react.mock.calls.length - 1] as unknown as [HTMLElement, Record<string, unknown>[]];
    expect(data[0].type).toBe("scatter3d");
    expect((data[0].customdata as number[]).length).toBe(18);
    fireEvent.click(within(plot).getByRole("checkbox", { name: "보간면" }));
    await waitFor(() => expect(((plotly.react.mock.calls[plotly.react.mock.calls.length - 1] as unknown[])[1] as Record<string, unknown>[])[1]).toMatchObject({ type: "mesh3d", delaunayaxis: "z" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "E_FOAM" }));
    expect(within(plot).getByTestId("plot-hint").textContent).toBe(PLOT_HINT);
    expect(within(plot).getByTestId("plot-hint").className).toContain("muted");
    for (const n of ["THK_TOP", "RIB_N", "E_FOAM"]) fireEvent.click(screen.getByRole("checkbox", { name: n }));
    expect(within(plot).getByTestId("plot-hint").textContent).toBe(PLOT_HINT);
  });

  it("WebGL이 없으면 3D 자리에 안내 한 줄", async () => {
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation((() => null) as never);
    renderApp(BATCH, { user: "power" });
    await screen.findByRole("region", { name: "결과 표 — B-002" });
    fireEvent.click(await screen.findByRole("checkbox", { name: "RIB_N" }));
    expect((await screen.findByTestId("plot3d-nogl")).textContent).toBe(NO_WEBGL_TEXT);
  });

  it("커브 탭: 완료 run 모두 흐리게, 고른 run만 진하게(표에서 바꾸면 따라감)", async () => {
    renderApp(BATCH, { user: "power" });
    await screen.findByRole("region", { name: "결과 표 — B-002" });
    fireEvent.click(tab(screen.getByRole("region", { name: "응답 그래프" }), "커브"));
    const curves = screen.getByRole("region", { name: "커브 겹쳐보기" });
    await waitFor(() => expect(curves.querySelectorAll("path.overlay").length).toBe(18));
    fireEvent.click(screen.getByRole("button", { name: "DOE #9 선택" }));
    await waitFor(() => expect(curves.querySelectorAll("path.overlay.on").length).toBe(1));
    const on = curves.querySelector("path.overlay.on")!;
    expect(on).toBe(curves.querySelectorAll("path.overlay")[17]);
    expect(within(curves).getByLabelText("계열")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "DOE #1 선택" }));
    await waitFor(() => expect(curves.querySelectorAll("path.overlay.on").length).toBe(1));
  });

  it("표 값 = ④ 결과 표(applied_values·응답), 실패 run은 응답 '—', 영향도·지도는 값 있는 18 run", async () => {
    const { server } = renderApp(BATCH, { user: "power" });
    await screen.findByRole("region", { name: "결과 표 — B-002" });
    const b = server.handle("GET", "/predict-batches/pb-2", new URLSearchParams(), null, new Headers()).body as { rows: { doe_no: number; state: string; responses: Record<string, number> | null; applied_values: Record<string, number> }[] };
    const ok = b.rows.find((r) => r.state === "SUCCEEDED")!;
    const tr = screen.getByTestId(`row-${ok.doe_no}`);
    expect(tr.textContent).toContain(fmtNum(ok.applied_values.THK_TOP));
    expect(tr.textContent).toContain(fmtNum(ok.responses!.MaxStress));
    const bad = b.rows.find((r) => r.state === "FAILED")!;
    expect(within(screen.getByTestId(`row-${bad.doe_no}`)).getAllByText("—").length).toBeGreaterThan(0);
  });

  it("진행 중 배치 pb-3도 쿼리로 열린다(완료 목록에 없어도 드롭다운에 '진행 중')", async () => {
    const { server } = renderApp(`${A}?source=batch&id=pb-3`, { user: "power", batchDemo: "running" });
    const calls = recordCalls(server);
    await screen.findByRole("region", { name: "결과 표 — B-003" });
    const sel = await srcSelect();
    expect([...sel.options].find((o) => o.value === "pb-3")!.textContent).toContain("진행 중");
    expect(calls.filter((c) => c === "GET /predict-batches/pb-3/design-map")).toHaveLength(1);
  });
});

describe("⑤ 겹쳐 보기 (V3-S14-6)", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
  });
  const addCompare = async () => {
    await screen.findByRole("region", { name: "결과 표 — B-002" });
    fireEvent.click(screen.getByRole("button", { name: "비교 추가" }));
    await screen.findByRole("group", { name: "비교 슬롯" });
  };

  it("이름 집합이 같으면(순서 무관) 활성: 2D에 해석 = 속 빈 원 · 예측 = 채운 점 + 범례 2개", async () => {
    renderApp(BATCH, { user: "power" }, sameNames);
    await addCompare();
    expect(((await srcSelect("비교")).value)).toBe("doe-1");
    await waitFor(() => expect(screen.getAllByTestId("plot2d-other").length).toBe(24));
    expect(screen.queryByTestId("compare-message")).toBeNull();
    const plot = screen.getByRole("region", { name: "응답 그래프" });
    const legend = within(plot).getByTestId("plot-legend");
    expect(within(legend).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["B-002 (예측 · 채운 점)", "LatinHyperCube (해석 · 속 빈 원)"]);
    expect(legend.querySelectorAll(".lg-mark.hollow")).toHaveLength(1);
    // 해석 점 = 속 빈 원 클래스, 예측 점 = 채운 점(hollow 없음)
    expect(screen.getAllByTestId("plot2d-other").every((c) => c.classList.contains("hollow"))).toBe(true);
    expect(within(plot).getAllByRole("button", { name: /^점 DOE #\d+$/ }).every((c) => !c.classList.contains("hollow"))).toBe(true);
  });

  it("이름 집합이 다르면 비활성 + 다른 쪽에만 있는 이름 안내(그래프에 겹치지 않음)", async () => {
    renderApp(BATCH, { user: "power" }, withResp); // doe-1: RIB_H 있음·E_FOAM 없음
    await addCompare();
    const msg = await screen.findByTestId("compare-message");
    expect(msg.textContent).toBe("파라미터 이름이 달라 겹쳐 볼 수 없습니다 — 다른 쪽에만 있음: E_FOAM, RIB_H");
    expect(screen.queryByTestId("plot2d-other")).toBeNull();
    expect(screen.queryByTestId("plot-legend")).toBeNull();
  });

  it("공통 응답이 0이면 비활성 + 안내(이름 집합은 같음)", async () => {
    renderApp(BATCH, { user: "power" }, (s) => {
      sameNames(s);
      s.p2.does[0].has_run_responses = false; // 해석 DOE 응답 없음 → 공통 응답 0
    });
    await addCompare();
    expect((await screen.findByTestId("compare-message")).textContent).toBe(NO_COMMON_RESP_TEXT);
    expect(screen.queryByTestId("plot2d-other")).toBeNull();
  });

  it("응답 선택은 두 표 공통 응답만: 공통 아닌 응답 라디오 비활성, 현재 선택이 공통이 아니면 첫 공통 응답으로, 비교 해제하면 복원", async () => {
    // 기본 = 해석 DOE(MaxStress·MaxDisp·Energy), 비교 = 배치 pb-2(Energy 없음) → 공통 = MaxStress·MaxDisp
    renderApp(DOE, { user: "power" }, (s) => {
      sameNames(s);
      const ps = s.paramSets.find((p) => p.id === "ps-1")!;
      ps.responses = ps.responses.filter((r) => r.name !== "Energy");
    });
    await screen.findByRole("region", { name: /^결과 표/ });
    const radio = (n: string) => screen.getByRole("radio", { name: n }) as HTMLInputElement;
    fireEvent.click(radio("Energy"));
    expect(radio("Energy").checked).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "비교 추가" }));
    await screen.findByRole("group", { name: "비교 슬롯" });
    await waitFor(() => expect(radio("Energy").disabled).toBe(true));
    expect(radio("MaxStress").disabled).toBe(false);
    expect(radio("MaxDisp").disabled).toBe(false);
    expect(radio("MaxStress").checked).toBe(true); // 첫 공통 응답으로 바뀜
    expect(radio("Energy").checked).toBe(false);
    // 공통 응답은 계속 고를 수 있다
    fireEvent.click(radio("MaxDisp"));
    expect(radio("MaxDisp").checked).toBe(true);
    // 설계공간 지도 색 값에도 공통 응답만
    const card = screen.getByRole("region", { name: "응답 그래프" });
    fireEvent.click(tab(card, "설계공간 지도"));
    await within(card).findByTestId("design-map");
    const opts = [...(within(card).getByLabelText("색 값") as HTMLSelectElement).options].map((o) => o.value);
    expect(opts).toEqual(["tbl:MaxStress", "tbl:MaxDisp"]);
    // 비교를 닫으면 전체 응답 선택 가능(고른 응답 유지)
    fireEvent.click(screen.getByRole("button", { name: /비교.*(제거|해제|닫기)/ }));
    await waitFor(() => expect(radio("Energy").disabled).toBe(false));
  });

  it("설계공간 지도: 두 표를 한 지도에 — 색 막대 최소·최대 = 두 표 합집합, 해석 점은 속 빈 원, 비교 점은 선택 불가", async () => {
    const { server } = renderApp(BATCH, { user: "power" }, sameNames);
    await addCompare();
    const card = screen.getByRole("region", { name: "응답 그래프" });
    fireEvent.click(tab(card, "설계공간 지도"));
    await within(card).findByTestId("design-map");
    fireEvent.change(within(card).getByLabelText("색 값"), { target: { value: "tbl:MaxStress" } });
    await waitFor(() => expect(within(card).getAllByRole("img", { name: /^비교 지도 점 #\d+$/ }).length).toBe(24));
    const solver = resultTable(server).rows.map((r) => r.responses.MaxStress).filter((v): v is number => typeof v === "number");
    const b = server.handle("GET", "/predict-batches/pb-2", new URLSearchParams(), null, new Headers()).body as { rows: { state: string; responses: Record<string, number> | null }[] };
    const pred = b.rows.filter((r) => r.state === "SUCCEEDED").map((r) => r.responses!.MaxStress);
    const all = [...solver, ...pred];
    const bar = within(card).getByTestId("dm-colorbar");
    expect(within(bar).getByTestId("dm-cb-max").textContent).toBe(fmtNum(Math.max(...all)));
    expect(within(bar).getByTestId("dm-cb-min").textContent).toBe(fmtNum(Math.min(...all)));
    expect(within(card).getAllByRole("img", { name: /^비교 지도 점/ }).every((c) => c.classList.contains("hollow"))).toBe(true);
    expect(within(within(card).getByTestId("plot-legend")).getAllByRole("listitem")).toHaveLength(2);
    expect(within(card).getByTestId("dm-notes").textContent).toContain("두 표 합집합");
    // 3D 선택은 겹치지 않는다는 안내
    fireEvent.click(tab(card, "변수–응답"));
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation((() => null) as never);
    fireEvent.click(screen.getByRole("checkbox", { name: "RIB_N" }));
    expect((await screen.findByTestId("plot-3d-compare")).textContent).toBe(NO3D_COMPARE_TEXT);
  });

  it("메타: 둘 다 값이 있고 다르면 회색 '메타 다름' 한 줄, 칩에 엔진·기준안·scene 그대로", async () => {
    renderApp(DOE, { user: "power" }, (s) => {
      sameNames(s);
      const d2 = { ...s.p2.does[0], id: "doe-2", doe_label: "LatinHyperCube2" };
      s.p2.does.push(d2);
      s.p2.runs["doe-2"] = s.p2.runs["doe-1"].map((r) => ({ ...r }));
      s.p2.doeSamples["doe-2"] = s.p2.doeSamples["doe-1"];
      const orig = s.handle.bind(s);
      s.handle = (m, p, q, b, h) => {
        const r = orig(m, p, q, b, h);
        const mm = /^\/train-does\/(doe-\d)\/result-table$/.exec(p);
        if (mm && r.status === 200) (r.body as DoeResultTable).meta = { engine_version: mm[1] === "doe-1" ? "ai-1.2" : "ai-1.3", baseline_id: "BL-7", scene: null };
        return r;
      };
    });
    await screen.findByRole("region", { name: "결과 표 — LatinHyperCube" });
    const chips = await screen.findByTestId("meta-chips");
    expect(chips.textContent).toContain("엔진 ai-1.2");
    expect(chips.textContent).toContain("기준안 BL-7");
    expect(chips.textContent).toContain("scene —");
    expect(screen.queryByTestId("meta-diff")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "비교 추가" })); // 기본이 해석이면 비교 기본은 예측 → 비교를 해석으로 바꾼다
    const group = await screen.findByRole("group", { name: "비교 슬롯" });
    fireEvent.click(within(group).getByRole("button", { name: "해석 DOE 결과(해석)" }));
    fireEvent.change(await srcSelect("비교"), { target: { value: "doe-2" } });
    expect((await screen.findByTestId("meta-diff")).textContent).toBe(META_DIFF_TEXT);
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


describe("목 계약: GET /train-does/{doe_id}/result-table (§19.5)", () => {
  it("응답이 openapi DoeResultTable 모양, 오류 코드(404·409)", () => {
    const { server } = renderApp(DOE, { user: "power" }, withResp);
    const r = server.handle("GET", "/train-does/doe-1/result-table", new URLSearchParams(), null, new Headers());
    expect(r.status).toBe(200);
    const schema = spec.paths["/physicsai/api/train-does/{doe_id}/result-table"].get.responses["200"].content["application/json"].schema;
    expect(problems(r.body, schema, "$")).toEqual([]);
    const t = r.body as DoeResultTable;
    expect(t.rows.map((x) => x.state)).toContain("COLLECTED");
    expect(t.responses.every((x) => x.unit == null)).toBe(true);
    expect(server.handle("GET", "/train-does/nope/result-table", new URLSearchParams(), null, new Headers()).status).toBe(404);
  });
});
