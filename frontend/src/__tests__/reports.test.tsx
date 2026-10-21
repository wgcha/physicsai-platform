// upload-report.md §9.4·§13.2(V-RP-8): HTML 보고서 보조 버튼 — ⑥(내장·HyperStudy 레거시)·⑤(결과 표·등가성 판정 탭). 현재 화면 선택(source·id·compare·vars·resp)이
// 쿼리로 넘어가고, 서버가 준 파일 이름으로 내려받고, 409 REPORT_NOT_READY 면 비활성+이유. 목 서버(mock/uploads.ts reportRoutes) 기준.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { renderApp, STUDY } from "../test/render";
import { analysisQuery } from "../api/reports";
import { dispositionName } from "../api/client";
import type { MockServer } from "../mock/server";

const plotly = vi.hoisted(() => ({ react: vi.fn(async (el: HTMLElement) => el), purge: vi.fn() }));
vi.mock("plotly.js-gl3d-dist-min", () => ({ default: plotly }));

const A = `${STUDY}/analysis`;
const sameNames = (s: MockServer) => {
  s.p2.does[0].has_run_responses = true;
  s.p2.doeSamples["doe-1"] = s.p2.doeSamples["doe-1"].map((r) => ({ ...r, values: { THK_TOP: r.values.THK_TOP, THK_FOAM: r.values.THK_FOAM, E_FOAM: 6 + (r.values.RIB_H % 5), RIB_N: r.values.RIB_N } }));
};

const origClick = HTMLAnchorElement.prototype.click;
let saved: { download: string; href: string }[] = [];
beforeEach(() => {
  localStorage.clear();
  saved = [];
  HTMLAnchorElement.prototype.click = function (this: HTMLAnchorElement) {
    saved.push({ download: this.download, href: this.href });
  };
});
afterEach(() => {
  HTMLAnchorElement.prototype.click = origClick;
  vi.restoreAllMocks();
  localStorage.clear();
});

const btnIn = (el: HTMLElement) => within(el).getByRole("button", { name: "HTML 보고서" }) as HTMLButtonElement;
const lastReport = (s: MockServer) => s.up.reports[s.up.reports.length - 1];

describe("보고서 쿼리·파일 이름 (순수)", () => {
  it("analysis 쿼리: source·id, 비교(둘 다 있을 때만), vars 반복 키, resp, download=1", () => {
    expect(analysisQuery({ source: "batch", id: "pb-2", vars: ["THK_TOP", "RIB_N"], resp: "MaxStress" }).toString()).toBe("source=batch&id=pb-2&vars=THK_TOP&vars=RIB_N&resp=MaxStress&download=1");
    expect(analysisQuery({ source: "doe", id: "d1", compare_source: "batch", compare_id: "b9" }).toString()).toBe("source=doe&id=d1&compare_source=batch&compare_id=b9&download=1");
    expect(analysisQuery({ source: "doe", id: "d1", compare_source: "batch", compare_id: null, vars: [], resp: null }).toString()).toBe("source=doe&id=d1&download=1");
  });

  it("Content-Disposition 파일 이름: filename*(UTF-8) 우선, 일반 filename 도 처리", () => {
    expect(dispositionName("attachment; filename*=UTF-8''PAI_%EC%BF%A0%EC%85%98_analysis-batch_pb-2_20261021-1530.html")).toBe("PAI_쿠션_analysis-batch_pb-2_20261021-1530.html");
    expect(dispositionName('attachment; filename="a.html"')).toBe("a.html");
    expect(dispositionName(null)).toBeNull();
  });
});

describe("⑥ 최적화 — HTML 보고서 버튼", () => {
  it("내장 최적화 결과: 버튼 1개, 클릭하면 /reports/surrogate-opt/{id}?download=1 을 받아 서버 파일 이름으로 저장", async () => {
    const { server } = renderApp(`${STUDY}/5/surrogate/so-1`, { user: "power" });
    const head = (await screen.findByTestId("so-status")).closest("section") as HTMLElement;
    expect(within(head).getAllByRole("button", { name: "HTML 보고서" })).toHaveLength(1);
    fireEvent.click(btnIn(head));
    await waitFor(() => expect(saved).toHaveLength(1));
    expect(lastReport(server)).toEqual({ path: "/reports/surrogate-opt/so-1", query: "download=1" });
    expect(saved[0].download).toBe("PAI_cushion_surrogate-opt_so-1_20261022-1030.html");
  });

  it("409 REPORT_NOT_READY 면 비활성 + 서버 이유 표시(요청은 한 번)", async () => {
    const { server } = renderApp(`${STUDY}/5/surrogate/so-1`, { user: "power" });
    const head = (await screen.findByTestId("so-status")).closest("section") as HTMLElement;
    server.up.reportNotReady = true;
    fireEvent.click(btnIn(head));
    await waitFor(() => expect(btnIn(head).disabled).toBe(true));
    expect(within(head).getByTestId("report-reason").textContent).toContain("끝난 뒤 받을 수 있습니다");
    expect(saved).toHaveLength(0);
  });

  it("HyperStudy(레거시) 결과: /reports/optimization/{id}, 진행 중이면 비활성+이유(요청 없음)", async () => {
    localStorage.setItem("physicsai.stage5.mode", "original"); // ⑥ 기존(HyperStudy) 화면
    const r1 = renderApp(`${STUDY}/5`, { user: "power" });
    const prog = await screen.findByTestId("opt-progress");
    const root = prog.closest(".opt-result") as HTMLElement;
    fireEvent.click(btnIn(root));
    await waitFor(() => expect(saved).toHaveLength(1));
    expect(lastReport(r1.server).path).toMatch(/^\/reports\/optimization\/.+/);
    expect(saved[0].download).toMatch(/^PAI_cushion_optimization_.+\.html$/);
    r1.unmount();
    const r2 = renderApp(`${STUDY}/5`, { user: "power" }, (s) => Object.assign(s.p2.opts[0], { status: "RUNNING", runs_started: 3 }));
    const root2 = (await screen.findByTestId("opt-progress")).closest(".opt-result") as HTMLElement;
    expect(btnIn(root2).disabled).toBe(true);
    expect(within(root2).getByTestId("report-reason").textContent).toContain("진행 중");
    expect(r2.server.up.reports).toHaveLength(0);
  });
});

describe("⑤ 결과분석 — HTML 보고서 버튼", () => {
  it("결과 표 탭: 현재 선택(출처·변수·응답)이 쿼리로, 변수·응답을 바꾸면 그대로 따라간다", async () => {
    const { server } = renderApp(`${A}?source=batch&id=pb-2`, { user: "power" }, sameNames);
    const card = await screen.findByRole("region", { name: "결과 표 — B-002" });
    fireEvent.click(btnIn(card));
    await waitFor(() => expect(saved).toHaveLength(1));
    const q1 = new URLSearchParams(lastReport(server).query);
    expect(lastReport(server).path).toBe("/reports/analysis");
    expect([q1.get("source"), q1.get("id"), q1.get("download")]).toEqual(["batch", "pb-2", "1"]);
    expect(q1.getAll("vars")).toHaveLength(1); // 화면 기본 = 첫 변수
    expect(q1.get("resp")).toBeTruthy();
    expect(q1.get("compare_source")).toBeNull();
    // 변수 1개 더, 응답 바꾸기
    fireEvent.click(within(card).getByRole("checkbox", { name: "THK_FOAM" }));
    const radios = within(card).getAllByRole("radio") as HTMLInputElement[];
    const other = radios.find((r) => !r.checked)!;
    fireEvent.click(other);
    fireEvent.click(btnIn(card));
    await waitFor(() => expect(saved).toHaveLength(2));
    const q2 = new URLSearchParams(lastReport(server).query);
    expect(q2.getAll("vars")).toEqual([q1.getAll("vars")[0], "THK_FOAM"]);
    expect(q2.get("resp")).not.toBe(q1.get("resp"));
  });

  it("비교 출처가 겹쳐 보이는 중이면 compare_source·compare_id 도 넘어간다(해석 DOE ↔ 일괄 예측)", async () => {
    const { server } = renderApp(`${A}?source=batch&id=pb-2`, { user: "power" }, sameNames);
    const card = await screen.findByRole("region", { name: "결과 표 — B-002" });
    fireEvent.click(screen.getByRole("button", { name: "비교 추가" }));
    await screen.findByRole("group", { name: "비교 슬롯" });
    await waitFor(() => expect(screen.getAllByTestId("plot2d-other").length).toBeGreaterThan(0));
    fireEvent.click(btnIn(card));
    await waitFor(() => expect(saved).toHaveLength(1));
    const q = new URLSearchParams(lastReport(server).query);
    expect([q.get("source"), q.get("id"), q.get("compare_source"), q.get("compare_id")]).toEqual(["batch", "pb-2", "doe", "doe-1"]);
  });

  it("출처가 해석 DOE 면 source=doe", async () => {
    const { server } = renderApp(`${A}?source=doe&id=doe-1`, { user: "power" }, (s) => (s.p2.does[0].has_run_responses = true));
    const card = await screen.findByRole("region", { name: /^결과 표 — / });
    fireEvent.click(btnIn(card));
    await waitFor(() => expect(saved).toHaveLength(1));
    const q = new URLSearchParams(lastReport(server).query);
    expect([q.get("source"), q.get("id")]).toEqual(["doe", "doe-1"]);
  });

  it("409 NOT_READY(진행 중 배치 출처)면 비활성+이유", async () => {
    const { server } = renderApp(`${A}?source=batch&id=pb-2`, { user: "power" });
    const card = await screen.findByRole("region", { name: "결과 표 — B-002" });
    server.up.reportNotReady = true;
    fireEvent.click(btnIn(card));
    await waitFor(() => expect(btnIn(card).disabled).toBe(true));
    expect(within(card).getByTestId("report-reason").textContent).toContain("끝난 뒤");
  });

  it("등가성 판정 탭: 이력에서 연 판정의 /reports/equiv-check/{id}", async () => {
    const { server } = renderApp(`${A}?tab=equiv`, { user: "power", equiv: "demo" });
    const hist = await screen.findByTestId("eq-history");
    expect(screen.queryByRole("button", { name: "HTML 보고서" })).toBeNull(); // 판정을 열기 전에는 없음
    fireEvent.click(within(within(hist).getByTestId("eq-hist-EQ-001")).getByRole("button", { name: "열기" }));
    const result = await screen.findByTestId("eq-result");
    const section = result.closest("section") as HTMLElement;
    fireEvent.click(btnIn(section));
    await waitFor(() => expect(saved).toHaveLength(1));
    expect(lastReport(server).path).toBe(`/reports/equiv-check/${server.eqChecks.find((c) => c.eq_no === 1)!.id}`);
  });
});
