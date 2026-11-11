// shell-morph.md §14 화면(SM-C6 정책·SM-C7 hold): V-SM-13(UI 항목), V-SM-19(화면: 정책 선택·배지·집계), V-SM-20(화면: hold 열 표시 조건).
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { renderApp, STUDY } from "../test/render";
import type { MockServer } from "../mock/server";
import { SHELL_BEADS, markShell, nativeTrainParams } from "../mock/geometry";
import { buildNativeParams, buildReuseParams, initialNative } from "../stages/stage1/doeGenParams";
import { genBadge, cellTone } from "../stages/stage1/doepreview/gridModel";
import { holdBeads, parseHoldNum, policyOptions, toggleHold, warnSummary, warnTotals, warnTotalsText, warnedRuns, withHold, withHoldParam } from "../lib/shellPolicy";

type Call = { m: string; p: string; b: Record<string, unknown> | null };
function record(server: MockServer, re: RegExp): Call[] {
  const calls: Call[] = [];
  const orig = server.handle.bind(server);
  server.handle = (m, p, q, b, h) => {
    if (m !== "GET" && re.test(p)) calls.push({ m, p, b: b ? structuredClone(b as Record<string, unknown>) : null });
    return orig(m, p, q, b, h);
  };
  return calls;
}
const doeBodies = (server: MockServer) => record(server, /\/studies\/[^/]+\/jobs$/);
const nativeSetup = (s: MockServer) => Object.assign(s.p2.setups["s-cushion"], { engine: "native", parameters: nativeTrainParams(), tpl: null });
const shellSet = (s: MockServer) => markShell(s, { paramSetId: "ps-n1" });
const shellTrain = (s: MockServer) => {
  nativeSetup(s);
  markShell(s, { trainStudyId: "s-cushion" });
};

async function doeCard(opts: Parameters<typeof renderApp>[1], setup?: (s: MockServer) => void) {
  const r = renderApp(`${STUDY}/1`, { user: "power", ...opts }, setup);
  const card = await screen.findByRole("region", { name: "DOE · Radioss 입력" });
  return { ...r, card };
}
const runBtn = (card: HTMLElement) => within(card).getByRole("button", { name: "입력 생성" }) as HTMLButtonElement;

describe("SM-C6 정책(고급 옵션) — V-SM-13 UI·V-SM-19 화면", () => {
  afterEach(() => vi.restoreAllMocks());

  it("솔리드 세트에는 정책 칸이 없다", async () => {
    const { card } = await doeCard({ geometry: "native" });
    fireEvent.change(await within(card).findByLabelText("형상 기준"), { target: { value: "ps-n1" } });
    expect(within(card).queryByLabelText("고정 침범·품질 미달 처리")).toBeNull();
  });

  it("쉘 세트: 고급 안에 [스킵 | 경고 후 사용], 기본 스킵(키 안 보냄) → 경고 선택 시 한 줄 안내·geom_options 전송 → 경고 통과 배지·집계", async () => {
    const { server, card } = await doeCard({ geometry: "native" }, shellSet);
    const bodies = doeBodies(server);
    fireEvent.change(await within(card).findByLabelText("형상 기준"), { target: { value: "ps-n1" } });
    const sel = within(card).getByLabelText("고정 침범·품질 미달 처리") as HTMLSelectElement;
    expect(sel.closest("details.advanced")).toBeTruthy(); // 고급 옵션 안
    expect([...sel.options].map((o) => o.textContent)).toEqual(["스킵", "경고 후 사용"]);
    expect(sel.value).toBe("skip");
    expect(within(card).queryByTestId("policy-warn-note")).toBeNull();
    // 기본 skip: 새 키를 보내지 않는다(옵션 sha 불변)
    await waitFor(() => expect(runBtn(card).disabled).toBe(false));
    fireEvent.click(runBtn(card));
    await waitFor(() => expect(bodies.length).toBe(1));
    expect((bodies[0].b as { params: Record<string, unknown> }).params).not.toHaveProperty("geom_options");
    act(() => server.finishAll());
    await waitFor(() => expect(within(card).getByTestId("doe-skipped")).toBeTruthy());
    expect(within(card).queryByTestId("doe-warned")).toBeNull();
    // 경고 후 사용
    fireEvent.change(sel, { target: { value: "warn" } });
    expect(within(card).getByTestId("policy-warn-note").textContent).toBe("스킵 대신 경고로 남겨 학습 데이터에 포함됨");
    await waitFor(() => expect(runBtn(card).disabled).toBe(false));
    fireEvent.click(runBtn(card));
    await waitFor(() => expect(bodies.length).toBe(2));
    expect((bodies[1].b as { params: Record<string, unknown> }).params.geom_options).toEqual({ fixed: { policy: "warn" }, quality: { fail_policy: "warn" } });
    act(() => server.finishAll());
    const warned = await within(card).findByTestId("doe-warned");
    expect(warned.textContent).toContain("경고 통과 1(고정 0·품질 1)");
    // 서버 result.gen_summary와 화면 집계가 같다
    const res = server.jobs[server.jobs.length - 1].result as { gen_warned: number; gen_summary: { warned: { fixed: number; quality: number }; skipped: object; waived: object } };
    expect(res.gen_warned).toBe(1);
    expect(res.gen_summary.warned).toEqual({ fixed: 0, quality: 1, other: 0 });
    expect(warnTotalsText(warnTotals({ ...res, doe_id: "x" }, "x")!)).toBe(warned.querySelector(".pill.warn")!.textContent);
    expect(within(warned).getAllByText("품질").length).toBeGreaterThan(0);
    expect(within(card).queryByTestId("doe-skipped")).toBeNull();
  });
});

describe("정책·경고 순수 함수", () => {
  it("policyOptions: skip = 키 없음, warn = 두 키", () => {
    expect(policyOptions("skip")).toBeNull();
    expect(policyOptions("warn")).toEqual({ fixed: { policy: "warn" }, quality: { fail_policy: "warn" } });
  });
  it("buildNativeParams·buildReuseParams: skip이면 geom_options 없음, warn이면 포함", () => {
    const o = { multi: 1, maxRuns: 500, assemPath: "A", paramSetId: null };
    expect(buildNativeParams(initialNative(), o)).not.toHaveProperty("geom_options");
    expect(buildNativeParams(initialNative(), { ...o, policy: "skip" })).not.toHaveProperty("geom_options");
    expect(buildNativeParams(initialNative(), { ...o, policy: "warn" })).toMatchObject({ geom_options: { fixed: { policy: "warn" } } });
    expect(buildReuseParams({ doeId: "d1", multi: 1, assemPath: "A", paramSetId: null, continueOnFailure: true })).not.toHaveProperty("geom_options");
    expect(buildReuseParams({ doeId: "d1", multi: 1, assemPath: "A", paramSetId: null, continueOnFailure: true, policy: "warn" })).toHaveProperty("geom_options");
  });
  it("warnSummary: 경고 통과 n(고정 a·품질 b), 그 DOE 결과만", () => {
    const res = { doe_id: "d1", warned_runs: [
      { run_key: "R1", codes: ["SHELL_FIXED_MOVED"], waived: ["SHELL_FIXED_REGION_VIOLATION"] },
      { run_key: "R2", codes: ["SHELL_QUALITY_WARN"], waived: ["GEOM_QUALITY"] },
      { run_key: "R3", codes: ["SHELL_FIXED_MOVED", "SHELL_QUALITY_WARN"], waived: ["SHELL_FIXED_REGION_VIOLATION", "GEOM_QUALITY"] },
    ] };
    expect(warnSummary(warnedRuns(res, "d1"))).toBe("경고 통과 3(고정 2·품질 2)");
    expect(warnedRuns(res, "d2")).toEqual([]);
    expect(warnSummary([])).toBeNull();
  });
  it("그리드 셀 배지: 경고 통과 = warn 톤(waived 표시), 스킵 = bad, 정상 = 없음", () => {
    expect(genBadge({ status: "OK", waived: ["SHELL_FIXED_REGION_VIOLATION"], warnings: ["SHELL_FIXED_MOVED"] })).toEqual({ tone: "warn", text: "경고 통과 · 고정" });
    expect(genBadge({ status: "OK", waived: ["GEOM_QUALITY", "SHELL_FIXED_REGION_VIOLATION"] })?.text).toBe("경고 통과 · 품질·고정");
    expect(genBadge({ status: "OK" })).toBeNull();
    expect(genBadge({ status: "SKIPPED", code: "GEOM_QUALITY", step: "check" })?.tone).toBe("bad");
    expect(cellTone({ doe_no: 3, status: "OK", values: {}, gen: { status: "OK", waived: ["GEOM_QUALITY"] } })).toBe("ok"); // 경고여도 실패 색 아님
  });
});

describe("SM-C7 hold — V-SM-20 화면", () => {
  afterEach(() => vi.restoreAllMocks());

  it("geom_options 헬퍼: ρ·b 보존, 빈 절 제거", () => {
    expect(withHold(null, ["B5"])).toEqual({ bead: { hold: { beads: ["B5"] } } });
    expect(withHold({ bead: { hold: { beads: ["B5"], ring_mm: 4 }, depth_mode: "x" } }, [])).toEqual({ bead: { hold: { ring_mm: 4 }, depth_mode: "x" } });
    expect(withHold({ bead: { hold: { beads: ["B5"] } } }, [])).toEqual({});
    expect(holdBeads({ bead: { hold: { beads: ["B5"] } } })).toEqual(["B5"]);
    expect(toggleHold(["B5"], "B1", true)).toEqual(["B1", "B5"]);
    expect(toggleHold(["B1", "B5"], "B1", false)).toEqual(["B5"]);
  });

  it("①-2 파라미터 표: hold 열은 hold_eligible 비드만 활성(기본 off) → 켜면 그 비드 행 사용 → 저장에 hold_beads", async () => {
    const { server } = renderApp(`${STUDY}/1`, { user: "power" }, shellTrain);
    const calls = record(server, /\/train\/params$/);
    const table = await screen.findByRole("table", { name: "파라미터 표" });
    await within(table).findByText("체결 보스 고정");
    const boxes = within(table).getAllByLabelText(/체결 보스 고정$/) as HTMLInputElement[];
    expect(boxes.length).toBeGreaterThan(0);
    expect(boxes.every((b) => !b.checked)).toBe(true); // 기본 off
    // hold_eligible이 아닌 비드의 행에는 체크 칸이 없다(–)
    const rows = within(table).getAllByRole("row").slice(1);
    const withBox = rows.filter((r) => within(r).queryByLabelText(/체결 보스 고정$/));
    expect(withBox.length).toBe(boxes.length);
    expect(withBox.length).toBeLessThan(rows.length);
    const rowOf = (b: HTMLElement) => b.closest("tr")!;
    const target = boxes[0];
    const useBox = within(rowOf(target)).getByLabelText(/ 사용$/) as HTMLInputElement;
    fireEvent.click(useBox); // 행 사용 해제
    expect(useBox.checked).toBe(false);
    fireEvent.click(target);
    expect(target.checked).toBe(true);
    expect((within(rowOf(target)).getByLabelText(/ 사용$/) as HTMLInputElement).checked).toBe(true); // 켜면 사용 활성
    fireEvent.click(screen.getByRole("button", { name: "표 저장" }));
    await waitFor(() => expect(calls.length).toBe(1));
    expect(calls[0].b!.hold_beads).toEqual([SHELL_BEADS.eligible]);
  });

  it("솔리드 native(hold_eligible 없음)에는 hold 열이 없다", async () => {
    renderApp(`${STUDY}/1`, { user: "power" }, nativeSetup);
    const table = await screen.findByRole("table", { name: "파라미터 표" });
    await within(table).findByText("종류");
    expect(within(table).queryByText("체결 보스 고정")).toBeNull();
  });

  it("④ 피처 표: hold 열 → PATCH geom_options.bead.hold.beads, 끄면 null", async () => {
    const { server } = renderApp(`${STUDY}/4`, { user: "power", geometry: "native" }, (s) => {
      s.paramSets.forEach((p) => (p.is_current = p.id === "ps-n1"));
      shellSet(s);
    });
    const calls = record(server, /\/param-sets\/ps-n1$/);
    fireEvent.click(await screen.findByRole("button", { name: "템플릿 관리" }));
    const card = await screen.findByRole("region", { name: "템플릿 관리" });
    const table = await within(card).findByRole("table", { name: "형상 피처 표" });
    const boxes = within(table).getAllByLabelText(/체결 보스 고정$/) as HTMLInputElement[];
    expect(boxes.every((b) => !b.checked)).toBe(true);
    fireEvent.click(boxes[0]);
    await waitFor(() => expect(calls[0]?.b).toEqual({ geom_options: { bead: { hold: { beads: [SHELL_BEADS.eligible] } } } }));
    await waitFor(() => expect((within(table).getAllByLabelText(/체결 보스 고정$/)[0] as HTMLInputElement).checked).toBe(true));
    fireEvent.click(within(table).getAllByLabelText(/체결 보스 고정$/)[0]);
    await waitFor(() => expect(calls[1]?.b).toEqual({ geom_options: null }));
  });

  it("hold_eligible 아닌 비드를 hold로 PATCH하면 422 GEOM_OPTIONS_INVALID", async () => {
    const { server } = renderApp(`${STUDY}/4`, { user: "power", geometry: "native" }, shellSet);
    const res = server.handle("PATCH", "/param-sets/ps-n1", new URLSearchParams(), { geom_options: { bead: { hold: { beads: [SHELL_BEADS.plain] } } } }, new Headers({ "X-PhysicsAI-Request": "1" }));
    expect(res.status).toBe(422);
    expect(JSON.stringify(res.body)).toContain("GEOM_OPTIONS_INVALID");
  });

  it("쉘이 아닌 세트의 ④ 표에는 hold 열이 없다", async () => {
    renderApp(`${STUDY}/4`, { user: "power", geometry: "native" }, (s) => s.paramSets.forEach((p) => (p.is_current = p.id === "ps-n1")));
    fireEvent.click(await screen.findByRole("button", { name: "템플릿 관리" }));
    const card = await screen.findByRole("region", { name: "템플릿 관리" });
    const table = await within(card).findByRole("table", { name: "형상 피처 표" });
    expect(within(table).queryByText("체결 보스 고정")).toBeNull();
  });
});

describe("hold ρ·b 고급 입력", () => {
  it("parseHoldNum: 빈칸·기본값 = 키 생략, 0 이하·문자 = 오류", () => {
    expect(parseHoldNum("", "ring_mm")).toEqual({ value: undefined });
    expect(parseHoldNum("3", "ring_mm")).toEqual({ value: undefined });
    expect(parseHoldNum("8", "blend_mm")).toEqual({ value: undefined });
    expect(parseHoldNum("4.5", "ring_mm")).toEqual({ value: 4.5 });
    expect("error" in parseHoldNum("0", "ring_mm")).toBe(true);
    expect("error" in parseHoldNum("-1", "blend_mm")).toBe(true);
    expect("error" in parseHoldNum("abc", "blend_mm")).toBe(true);
    expect(withHoldParam({ bead: { hold: { beads: ["B5"], ring_mm: 4 } } }, "ring_mm", undefined)).toEqual({ bead: { hold: { beads: ["B5"] } } });
    expect(warnTotals({ doe_id: "d", gen_warned: 0, gen_summary: { warned: { fixed: 0, quality: 0 } } }, "d")).toBeNull();
  });

  it("①-2: ρ·b 접힘 입력 — 기본이면 hold_options 없음, 값 입력 시 기본 아닌 키만 전송, 잘못된 값은 저장 막힘", async () => {
    const { server } = renderApp(`${STUDY}/1`, { user: "power" }, shellTrain);
    const calls = record(server, /\/train\/params$/);
    const table = await screen.findByRole("table", { name: "파라미터 표" });
    await within(table).findByText("체결 보스 고정");
    const ring = screen.getByLabelText("보스 둘레 고정 ρ (mm)") as HTMLInputElement;
    expect(ring.closest("details.advanced")).toBeTruthy();
    expect(ring.placeholder).toBe("기본 3");
    fireEvent.click(screen.getByRole("button", { name: "표 저장" }));
    await waitFor(() => expect(calls.length).toBe(1));
    expect(calls[0].b).not.toHaveProperty("hold_options");
    fireEvent.change(ring, { target: { value: "0" } });
    expect((screen.getByRole("button", { name: "표 저장" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(ring, { target: { value: "4.5" } });
    fireEvent.change(screen.getByLabelText("전이 폭 b (mm)"), { target: { value: "8" } });
    fireEvent.click(screen.getByRole("button", { name: "표 저장" }));
    await waitFor(() => expect(calls.length).toBe(2));
    expect(calls[1].b!.hold_options).toEqual({ ring_mm: 4.5 });
  });

  it("①-2: 저장된 ρ·b를 기본값으로 되돌리면 hold_options {}를 보내고, 다시 열어도 기본값(빈칸)", async () => {
    const { server } = renderApp(`${STUDY}/1`, { user: "power" }, shellTrain);
    const calls = record(server, /\/train\/params$/);
    await within(await screen.findByRole("table", { name: "파라미터 표" })).findByText("체결 보스 고정");
    fireEvent.change(screen.getByLabelText("보스 둘레 고정 ρ (mm)"), { target: { value: "4.5" } });
    fireEvent.click(screen.getByRole("button", { name: "표 저장" }));
    await waitFor(() => expect(calls.length).toBe(1));
    await waitFor(() => expect((screen.getByLabelText("보스 둘레 고정 ρ (mm)") as HTMLInputElement).value).toBe("4.5"));
    // 건드리지 않고 다시 저장 → 생략(서버 유지)
    fireEvent.click(screen.getByRole("button", { name: "표 저장" }));
    await waitFor(() => expect(calls.length).toBe(2));
    expect(calls[1].b).not.toHaveProperty("hold_options");
    expect((server.p2.setups["s-cushion"] as { hold_options?: object }).hold_options).toEqual({ ring_mm: 4.5 });
    // 기본값으로 복귀(빈칸) → {} 전송 → 서버 초기화
    fireEvent.change(screen.getByLabelText("보스 둘레 고정 ρ (mm)"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "표 저장" }));
    await waitFor(() => expect(calls.length).toBe(3));
    expect(calls[2].b!.hold_options).toEqual({});
    expect((server.p2.setups["s-cushion"] as { hold_options?: object | null }).hold_options).toBeNull();
    await waitFor(() => expect((screen.getByLabelText("보스 둘레 고정 ρ (mm)") as HTMLInputElement).value).toBe(""));
  });

  it("①-2: 저장값 {4.5, 10}에서 ρ만 기본값으로 되돌리면 {ring_mm:null} 전송 → 다시 열면 ρ 빈칸·b 10", async () => {
    const { server } = renderApp(`${STUDY}/1`, { user: "power" }, shellTrain);
    const calls = record(server, /\/train\/params$/);
    await within(await screen.findByRole("table", { name: "파라미터 표" })).findByText("체결 보스 고정");
    const ring = () => screen.getByLabelText("보스 둘레 고정 ρ (mm)") as HTMLInputElement;
    const blend = () => screen.getByLabelText("전이 폭 b (mm)") as HTMLInputElement;
    fireEvent.change(ring(), { target: { value: "4.5" } });
    fireEvent.change(blend(), { target: { value: "10" } });
    fireEvent.click(screen.getByRole("button", { name: "표 저장" }));
    await waitFor(() => expect(calls.length).toBe(1));
    expect(calls[0].b!.hold_options).toEqual({ ring_mm: 4.5, blend_mm: 10 });
    await waitFor(() => expect(blend().value).toBe("10"));
    fireEvent.change(ring(), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "표 저장" }));
    await waitFor(() => expect(calls.length).toBe(2));
    expect(calls[1].b!.hold_options).toEqual({ ring_mm: null });
    expect((server.p2.setups["s-cushion"] as { hold_options?: object }).hold_options).toEqual({ blend_mm: 10 });
    await waitFor(() => expect(ring().value).toBe(""));
    expect(blend().value).toBe("10");
  });

  it("④: ρ·b 입력 → 저장 시 PATCH bead.hold.ring_mm/blend_mm, 기본으로 되돌리면 키 제거", async () => {
    const { server } = renderApp(`${STUDY}/4`, { user: "power", geometry: "native" }, (s) => {
      s.paramSets.forEach((p) => (p.is_current = p.id === "ps-n1"));
      shellSet(s);
    });
    const calls = record(server, /\/param-sets\/ps-n1$/);
    fireEvent.click(await screen.findByRole("button", { name: "템플릿 관리" }));
    const card = await screen.findByRole("region", { name: "템플릿 관리" });
    await within(card).findByRole("table", { name: "형상 피처 표" });
    fireEvent.change(within(card).getByLabelText("전이 폭 b (mm)"), { target: { value: "10" } });
    fireEvent.click(within(card).getByTestId("hold-params-save"));
    await waitFor(() => expect(calls[0]?.b).toEqual({ geom_options: { bead: { hold: { blend_mm: 10 } } } }));
    await waitFor(() => expect((within(card).getByLabelText("전이 폭 b (mm)") as HTMLInputElement).value).toBe("10"));
    fireEvent.change(within(card).getByLabelText("전이 폭 b (mm)"), { target: { value: "" } });
    fireEvent.click(within(card).getByTestId("hold-params-save"));
    await waitFor(() => expect(calls[1]?.b).toEqual({ geom_options: null }));
  });
});
