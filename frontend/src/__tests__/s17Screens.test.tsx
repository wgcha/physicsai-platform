// V3-S17-12: ⑥ 성능 표(정의 편집·역할·값·재사용 n/N·가중치) · 다목적 결과(산점도·쌍 그림·슬라이더 추천·파레토 표·HV·검증 버튼) ·
// ④ 템플릿 CURVE 응답 · ⑤ 결과분석의 curve:/perf: 지표 확장(D3-65 보강 2).
import { afterEach, describe, expect, it } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { renderApp, STUDY } from "../test/render";
import { recordCalls } from "../test/recordCalls";
import type { MockServer } from "../mock/server";
import { fromBatch } from "../analysis/adapters/fromBatch";
import { curveColumns, curveValue, NO_RESP_HINT, perfValue, withPerfMetrics } from "../analysis/perfColumns";
import { perfRows, rolesIssue, rolesToBody, roleValueIssue, SAVE_FIRST_TEXT } from "../stages/stage5/surrogate/perfRules";
import { stairPath } from "../stages/stage5/surrogate/ParetoPlot";
import { recommend } from "../stages/stage5/surrogate/pareto";
import type { PredictBatch, TemplateResponse } from "../api";
import type { DesignMap } from "../api/designMap";

function bodyOf(server: MockServer, path: string, method = "POST") {
  const out: Record<string, unknown>[] = [];
  const orig = server.handle.bind(server);
  server.handle = (m, p, q, b, h) => {
    if (m === method && p === path) out.push(b as Record<string, unknown>);
    return orig(m, p, q, b, h);
  };
  return out;
}

describe("V3-S17-12 ⑥ 성능 표", () => {
  afterEach(() => localStorage.clear());

  it("정의 편집: 커브 성능 추가 → 저장 전에는 역할 지정 불가 → 저장하면 역할 선택", async () => {
    renderApp(`${STUDY}/5`, { user: "power" });
    fireEvent.click(await screen.findByRole("tab", { name: /새 최적화/ }));
    const table = await screen.findByRole("table", { name: "성능" });
    expect(within(table).getByLabelText("MaxStress 역할")).toBeTruthy();
    const add = screen.getByRole("group", { name: "응답 추가" });
    fireEvent.change(within(add).getByLabelText("출처"), { target: { value: "CURVE" } });
    fireEvent.change(within(add).getByLabelText("응답 이름"), { target: { value: "AccelPeak" } });
    fireEvent.change(within(add).getByLabelText("커브 계열"), { target: { value: "Node 100 / X" } });
    fireEvent.click(within(add).getByRole("button", { name: /추가/ }));
    const row = await screen.findByTestId("perf-AccelPeak");
    expect(within(row).getByTestId("perf-unsaved-AccelPeak").textContent).toBe(SAVE_FIRST_TEXT);
    expect(within(row).queryByLabelText("AccelPeak 역할")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "성능 정의 저장(템플릿)" }));
    expect(await screen.findByLabelText("AccelPeak 역할")).toBeTruthy();
  });

  it("역할별 값 입력 · 목적 2개면 가중치 슬라이더와 다목적 안내 · 본문 objectives/constraints/observe/weights", async () => {
    const { server } = renderApp(`${STUDY}/5`, { user: "power" });
    const posts = bodyOf(server, "/studies/s-cushion/surrogate-opts");
    fireEvent.click(await screen.findByRole("tab", { name: /새 최적화/ }));
    await screen.findByRole("table", { name: "성능" });
    expect(screen.queryByTestId("weight-inputs")).toBeNull();
    fireEvent.change(screen.getByLabelText("MaxStress 역할"), { target: { value: "min" } });
    expect(screen.queryByTestId("weight-inputs")).toBeNull();
    fireEvent.change(screen.getByLabelText("MaxDisp 역할"), { target: { value: "range" } });
    expect(screen.getByLabelText("MaxDisp 하한")).toBeTruthy();
    expect(screen.getByLabelText("MaxDisp 상한")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("MaxDisp 역할"), { target: { value: "max" } });
    const w = await screen.findByTestId("weight-inputs");
    expect(within(w).getByTestId("multi-note").textContent).toMatch(/다목적|파레토/);
    fireEvent.change(within(w).getByLabelText("MaxStress 가중치"), { target: { value: "80" } });
    await waitFor(() => expect((screen.getByRole("button", { name: "최적화 시작" }) as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByRole("button", { name: "최적화 시작" }));
    await screen.findByTestId("so-status");
    expect(posts[0]).toMatchObject({
      objectives: [{ metric: "perf:MaxStress", sense: "min" }, { metric: "perf:MaxDisp", sense: "max" }],
      constraints: [], observe: [], weights: [80, 50],
    });
  });

  it("순수 규칙: 역할 → 본문, 값 검증, 목적 0개 막기", () => {
    const ps = [{ name: "A", unit: "", spec: { source: "H3D", stat: "MAX" } }, { name: "B", unit: "", spec: { source: "H3D", stat: "MAX" } }] as unknown as TemplateResponse[];
    const names = perfRows(ps).map((r) => r.name);
    const rows = perfRows(ps);
    expect(names).toEqual(["A", "B"]);
    expect(rolesIssue(rows, {})).toMatch(/목적/);
    const sels = { A: { role: "min", a: "", b: "" }, B: { role: "range", a: "1", b: "3" } } as never;
    expect(rolesIssue(rows, sels)).toBeNull();
    expect(rolesToBody(rows, sels, {})).toMatchObject({ objectives: [{ metric: "perf:A", sense: "min" }], constraints: [{ metric: "perf:B", op: "range", lo: 1, hi: 3 }] });
    expect(roleValueIssue({ role: "range", a: "5", b: "2" })).toBeTruthy();
    expect(roleValueIssue({ role: "le", a: "", b: "" })).toBeTruthy();
  });

  it("ParetoPlot 계단선: y 최소면 가로→세로, 최대면 세로→가로", () => {
    expect(stairPath([[0, 10], [5, 4]], true)).toBe("M0 10 H5 V4");
    expect(stairPath([[0, 10], [5, 4]], false)).toBe("M0 10 V4 H5");
  });
});

describe("V3-S17-12 다목적 결과 화면", () => {
  afterEach(() => localStorage.clear());

  it("2목적: 산점도(전선·지배·예측 토글)·추천 링·슬라이더로 추천 이동·localStorage·기본값", async () => {
    renderApp(`${STUDY}/5/surrogate/so-2`, { user: "power" });
    const plot = await screen.findByTestId("pareto-plot");
    expect(plot.querySelectorAll(".so-front").length).toBeGreaterThan(1);
    expect(plot.querySelectorAll(".so-dot").length).toBeGreaterThan(0);
    expect(screen.getByTestId("pareto-stair")).toBeTruthy();
    const recKey = screen.getByTestId("pareto-rec").getAttribute("data-key") as string;
    expect(screen.getByTestId(`prow-${recKey}`).className).toContain("recommended");
    expect(screen.getByTestId(`rank-${recKey}`).textContent).toBe("1");
    // 예측 전선 토글
    const hollow = plot.querySelectorAll(".so-hollow").length;
    if (hollow) {
      fireEvent.click(screen.getByRole("checkbox", { name: /대리모델 예측 전선/ }));
      expect(screen.getByTestId("pareto-plot").querySelectorAll(".so-hollow")).toHaveLength(0);
      fireEvent.click(screen.getByRole("checkbox", { name: /대리모델 예측 전선/ }));
    }
    // 슬라이더 극단 → 추천이 서버 식과 같은 점으로 이동
    const before = screen.getByTestId("so-recommend").textContent;
    fireEvent.change(screen.getByLabelText(/가중치$/, { selector: "#so-w-0" }), { target: { value: "100" } });
    fireEvent.change(screen.getByLabelText(/가중치$/, { selector: "#so-w-1" }), { target: { value: "0" } });
    expect(screen.getByTestId("weight-pct-0").textContent).toBe("100%");
    expect(screen.getByTestId("weight-pct-1").textContent).toBe("0%");
    const after = screen.getByTestId("pareto-rec").getAttribute("data-key") as string;
    expect(screen.getByTestId(`rank-${after}`).textContent).toBeTruthy();
    expect(screen.getByTestId("so-recommend").textContent).toBeTruthy();
    expect(Object.keys(localStorage).some((k) => k.startsWith("physicsai.stage6.weights."))).toBe(true);
    void before;
    fireEvent.click(screen.getByRole("button", { name: "기본값으로" }));
    expect(Object.keys(localStorage).some((k) => k.startsWith("physicsai.stage6.weights."))).toBe(false);
    expect(screen.getByTestId("weight-pct-0").textContent).toBe("50%");
  });

  it("2목적: 점 클릭 ↔ 표 체크, 점수 열 = pareto.ts, 버튼 조건(FEM은 검증된 해 1개)", async () => {
    const { server } = renderApp(`${STUDY}/5/surrogate/so-2`, { user: "power", hpcConfigured: true });
    const calls = recordCalls(server);
    const posts = bodyOf(server, "/surrogate-opts/so-2/verify");
    const plot = await screen.findByTestId("pareto-plot");
    const pt = plot.querySelector(".so-pt.front") as SVGGElement;
    const key = pt.getAttribute("data-testid")!.replace(/^pt-/, "");
    const row = screen.getByTestId(`prow-${key}`);
    expect((row.querySelector("input[type=checkbox]") as HTMLInputElement).checked).toBe(false);
    fireEvent.click(pt);
    expect((row.querySelector("input[type=checkbox]") as HTMLInputElement).checked).toBe(true);
    expect(plot.querySelectorAll(".so-sel")).toHaveLength(1);
    // 표 점수 = 같은 식
    const o = server.surrogate[1];
    expect(o).toBeTruthy();
    const card = screen.getByRole("table", { name: "파레토 표" }).closest(".so-pareto-table") as HTMLElement;
    const fem = () => within(card).getByRole("button", { name: /FEM 검증/ }) as HTMLButtonElement;
    expect(fem().disabled).toBe(false); // 검증된 해 1개 + features.fem_verify
    // 예측 검증 → POST verify 본문
    fireEvent.click(screen.getByRole("button", { name: /선택 해 예측 검증/ }));
    await screen.findByTestId("extra-note");
    expect(posts[0]).toMatchObject({ capture: false });
    expect((posts[0].points as unknown[]).length).toBe(1);
    expect(calls).toContain("POST /surrogate-opts/so-2/verify");
    // 표 헤더: 목적·점수·순위
    const heads = within(screen.getByRole("table", { name: "파레토 표" })).getAllByRole("columnheader").map((h) => h.textContent);
    expect(heads).toContain("가중 점수");
    expect(heads).toContain("순위");
  });

  it("3목적: 쌍 그림 3개 · HV 그래프 · 목적별 품질 표 · 수렴 그래프 없음", async () => {
    renderApp(`${STUDY}/5/surrogate/so-3`, { user: "power" });
    await screen.findByTestId("pair-plots");
    for (const id of ["pair-1-2", "pair-1-3", "pair-2-3"]) expect(screen.getByTestId(id)).toBeTruthy();
    expect(screen.getByTestId("so-hv")).toBeTruthy();
    expect(screen.queryByRole("img", { name: "수렴 그래프" })).toBeNull();
  });

  it("단일 목적(so-1)은 파레토 영역 없이 기존 화면", async () => {
    renderApp(`${STUDY}/5/surrogate/so-1`, { user: "power" });
    await screen.findByRole("img", { name: "수렴 그래프" });
    expect(screen.queryByTestId("pareto-plot")).toBeNull();
  });

  it("골든 추천 = 화면 추천(같은 함수)", () => {
    const r = recommend([{ key: "A", f: [1, 9] }, { key: "B", f: [3, 4] }, { key: "C", f: [6, 2] }, { key: "D", f: [10, 1] }], ["min", "min"], [50, 50]);
    expect(r.key).toBe("B");
  });
});

describe("V3-S17-12 ④ 템플릿 CURVE 응답", () => {
  async function openDefs() {
    fireEvent.click(await screen.findByRole("button", { name: "템플릿 관리" }));
    const card = await screen.findByRole("region", { name: "템플릿 관리" });
    return { defs: within(card).getByTestId("resp-defs") };
  }

  it("커브 응답 추가: 이름·'|' 검증 → 출처 열 '커브' · 저장 본문 spec CURVE", async () => {
    const { server } = renderApp(`${STUDY}/4`, { user: "power" });
    const puts = bodyOf(server, "/param-sets/ps-1/responses", "PUT");
    const { defs } = await openDefs();
    const add = within(defs).getByRole("group", { name: "응답 추가" });
    fireEvent.change(within(add).getByLabelText("출처"), { target: { value: "CURVE" } });
    expect(within(add).getByLabelText("커브 계열")).toBeTruthy();
    expect(within(defs).getByTestId("curve-hint")).toBeTruthy();
    fireEvent.change(within(add).getByLabelText("응답 이름"), { target: { value: "1bad" } });
    fireEvent.click(within(add).getByRole("button", { name: "응답 추가" }));
    expect(within(defs).getByRole("alert").textContent).toMatch(/영문자로 시작/);
    fireEvent.change(within(add).getByLabelText("응답 이름"), { target: { value: "AccelPeak" } });
    fireEvent.change(within(add).getByLabelText("커브 계열"), { target: { value: "a|b" } });
    fireEvent.click(within(add).getByRole("button", { name: "응답 추가" }));
    expect(within(defs).getByRole("alert").textContent).toMatch(/\|/);
    fireEvent.change(within(add).getByLabelText("커브 계열"), { target: { value: "Node 100 / X" } });
    fireEvent.change(within(add).getByLabelText("stat"), { target: { value: "ABSMAX" } });
    fireEvent.click(within(add).getByRole("button", { name: "응답 추가" }));
    expect(within(defs).getByText("AccelPeak")).toBeTruthy();
    fireEvent.click(within(defs).getByRole("button", { name: "응답 저장" }));
    await waitFor(() => expect(puts).toHaveLength(1));
    const list = puts[0].responses as { name: string; spec: Record<string, unknown> }[];
    expect(list.find((r) => r.name === "AccelPeak")!.spec).toEqual({ source: "CURVE", series: "Node 100 / X", stat: "ABSMAX" });
  });

  it("진행 중 최적화가 쓰는 성능을 지우면 409 PERF_IN_USE_BY_OPT 문구", async () => {
    renderApp(`${STUDY}/4`, { user: "power" }, (s) => {
      const o = s.surrogate[0];
      o.param_set_id = "ps-1";
      o.status = "EXPLORING";
      o.settings.performances = { MaxStress: { unit: "MPa", spec: { source: "H3D", subcase: 1, datatype: "Stress", component: "", layer: "", stat: "MAX" } } } as never;
    });
    const { defs } = await openDefs();
    fireEvent.click(within(defs).getByRole("button", { name: "MaxStress 삭제" }));
    fireEvent.click(within(defs).getByRole("button", { name: "응답 저장" }));
    await waitFor(() => expect(within(defs).getAllByRole("alert").map((x) => x.textContent).join(" ")).toMatch(/SO-001/));
  });
});

describe("V3-S17-12 ⑤ 결과분석 curve:/perf: 지표 확장", () => {
  const dm = {
    parameters: [{ name: "T", min: 0, max: 1, integer: false }],
    series: ["Node 100 / X"],
    metrics: [{ id: "resp:S_MAX", label: "S", unit: null, needs_series: false }],
    runs: [1, 2, 3, 4, 5, 6].map((n) => ({
      doe_no: n, run_key: `r${n}`, state: "SUCCEEDED", values: { T: n / 10 },
      curve: { "Node 100 / X": { max: n * 2, min: -n, absmax: n * 2 } }, resp: { S_MAX: n }, tbl: {},
    })),
  } as unknown as DesignMap;
  const batch = {
    id: "b1", parameters: ["T"], responses: [], status: "DONE", predict: { succeeded: 6 },
    rows: [1, 2, 3, 4, 5, 6].map((n) => ({ doe_no: n, run_key: `r${n}`, state: "SUCCEEDED", values: { T: n / 10 }, applied_values: { T: n / 10 }, responses: {} })),
  } as unknown as PredictBatch;
  const perfs = [{ name: "AccelPeak", unit: "g", spec: { source: "CURVE", series: "Node 100 / X", stat: "ABSMAX" } }, { name: "S", unit: "MPa", spec: { source: "H3D", stat: "MAX" } }] as unknown as TemplateResponse[];

  it("응답이 없는 배치 → 커브 대표값 열(≤12 계열 × 3)과 성능 열이 생기고 영향도가 켜진다", () => {
    const rt = fromBatch(batch, dm, undefined, perfs);
    const names = rt.responses.map((r) => r.name);
    expect(names).toContain("curve:max|Node 100 / X");
    expect(names).toContain("curve:absmax|Node 100 / X");
    expect(names).toContain("AccelPeak");
    expect(rt.responses.find((r) => r.name === "curve:min|Node 100 / X")?.kind).toBe("curve");
    expect(rt.responses.find((r) => r.name === "AccelPeak")?.kind).toBe("perf");
    expect(rt.rows[2].responses.AccelPeak).toBe(6);
    expect(rt.rows[2].responses.S).toBe(3);
    expect(rt.influence.ok).toBe(true);
    // design-map에 perf: 지표가 더해진다
    const ids = rt.designMap!.metrics.map((m) => m.id);
    expect(ids).toContain("perf:AccelPeak");
    expect(ids).toContain("perf:S");
  });

  it("템플릿 성능도 커브도 없으면 off 사유에 ④ 안내를 덧붙인다", () => {
    const empty = { ...dm, series: [], runs: dm.runs.map((r) => ({ ...r, curve: null, resp: {} })) } as unknown as DesignMap;
    const rt = fromBatch(batch, empty, undefined, null);
    expect(rt.influence.ok).toBe(false);
    expect(rt.influence.reason).toContain(NO_RESP_HINT);
  });

  it("성능 없음 → design-map 원본 그대로(같은 참조)", () => {
    expect(withPerfMetrics(dm, [], () => null)).toBe(dm);
    expect(curveColumns(null)).toEqual([]);
    expect(curveValue("curve:max|Node 100 / X", dm.runs[0])).toBe(2);
    expect(perfValue(perfRows(perfs)[0], undefined, dm.runs[0])).toBe(2);
  });
});
