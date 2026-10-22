// ①-3 "다른 DOE 표본표 재사용"(equiv-check.md EQ-C1 4): 표본 방식 목록 항목 → 같은 스터디 DOE 선택(이름 집합 같을 때만 활성, 아니면 비활성+사유),
// 요청 sampling {kind:"train_doe", doe_id}(run 수·시드 없음) — 플랫폼·native 모두, 서버 오류는 한국어.
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { renderApp, STUDY } from "../test/render";
import type { MockServer } from "../mock/server";
import type { MockOptions } from "../mock/server";
import { nativeTrainParams } from "../mock/geometry";
import { buildReuseParams, reuseParamNames, reuseState, sameNameSet } from "../stages/stage1/doeGenParams";

const ASSEM = "E:/shared/AI_WORK/cushion/00_inbox/radioss_assem";

function recordDoeBodies(server: MockServer) {
  const bodies: Record<string, unknown>[] = [];
  const orig = server.handle.bind(server);
  server.handle = (m, p, q, b, h) => {
    if (m === "POST" && /\/studies\/[^/]+\/jobs$/.test(p) && (b as { job_type?: string } | null)?.job_type === "TD_DOE_GEN") bodies.push(structuredClone((b as { params: Record<string, unknown> }).params));
    return orig(m, p, q, b, h);
  };
  return bodies;
}
/** 시드 DOE(doe-1, 이름 4개)와 이름이 다른 DOE·미준비 DOE를 더한다 */
function addOtherDoes(s: MockServer) {
  const base = s.p2.does[0];
  s.p2.does.push({ ...base, id: "doe-x", doe_label: "다른 변수 DOE", run_count: 5 }, { ...base, id: "doe-b", doe_label: "생성 중 DOE", status: "BUILDING", sample_status: "PENDING", run_count: null });
  s.p2.doeSamples["doe-x"] = [{ run_key: "run__00001", values: { THK_TOP: 0.5, EXTRA_X: 1 }, measured: {} }];
}
const nativeSetup = (s: MockServer) => {
  Object.assign(s.p2.setups["s-cushion"], { engine: "native", parameters: nativeTrainParams(), tpl: null });
  addOtherDoes(s);
  // 이름 집합이 native 파라미터 표와 같은 원본 DOE
  const names = nativeTrainParams().filter((p) => p.use).map((p) => p.name);
  s.p2.does.push({ ...s.p2.does[0], id: "doe-n", doe_label: "native 원본", run_count: 2 });
  s.p2.doeSamples["doe-n"] = [1, 2].map((k) => ({ run_key: `run__0000${k}`, values: Object.fromEntries(names.map((n) => [n, k])), measured: {} }));
};
async function openCard(opts: MockOptions, setup: (s: MockServer) => void) {
  const r = renderApp(`${STUDY}/1`, { user: "power", ...opts }, setup);
  const card = await screen.findByRole("region", { name: "DOE · Radioss 입력" });
  return { ...r, card };
}
const runBtn = (card: HTMLElement) => within(card).getByRole("button", { name: "입력 생성" }) as HTMLButtonElement;
const pickReuse = (card: HTMLElement) => fireEvent.change(within(card).getByLabelText("표본 방식"), { target: { value: "train_doe" } });
const doeSelect = (card: HTMLElement) => within(card).getByLabelText("재사용할 DOE") as HTMLSelectElement;
const opt = (sel: HTMLSelectElement, text: string) => [...sel.options].find((o) => o.textContent?.includes(text))!;

describe("①-3 표본표 재사용 규칙", () => {
  it("파라미터 이름 집합(순서 무관)·columns에서 run_key·resp: 제외·상태별 사유", () => {
    expect(reuseParamNames(["run_key", "A", "B", "resp:peak"])).toEqual(["A", "B"]);
    expect(sameNameSet(["A", "B"], ["B", "A"])).toBe(true);
    expect(sameNameSet(["A"], ["A", "B"])).toBe(false);
    const ready = { status: "READY", sample_status: "PARSED" };
    expect(reuseState(ready, ["A"], ["A"])).toEqual({ ok: true, reason: null });
    expect(reuseState(ready, ["A"], ["A", "B"])).toEqual({ ok: false, reason: "파라미터 이름이 다릅니다" });
    expect(reuseState(ready, null, ["A"]).ok).toBe(false);
    expect(reuseState({ status: "BUILDING", sample_status: "PENDING" }, undefined, ["A"]).reason).toBe("표본표가 준비되지 않았습니다");
    expect(buildReuseParams({ doeId: "", multi: 2, assemPath: "x", paramSetId: null, continueOnFailure: false })).toBeNull();
    expect(buildReuseParams({ doeId: "d1", multi: 2, assemPath: "x", paramSetId: null, continueOnFailure: false })).toEqual({ generator: "platform", sampling: { kind: "train_doe", doe_id: "d1" }, multi_execution: 2, on_run_failure: "fail", radioss_assem_path: "x" });
    expect(buildReuseParams({ doeId: "d1", multi: 2, assemPath: "x", paramSetId: "ps", continueOnFailure: true })).toEqual({ generator: "platform", sampling: { kind: "train_doe", doe_id: "d1" }, multi_execution: 2, on_run_failure: "continue", param_set_id: "ps" });
  });
});

describe("①-3 플랫폼: 다른 DOE 표본표 재사용", () => {
  afterEach(() => vi.restoreAllMocks());

  it("표본 방식에 항목 → DOE 목록(이름 같은 것만 활성·다른 것은 사유) + 도움말 → 요청 sampling train_doe(run 수·시드 없음)", async () => {
    const { server, card } = await openCard({}, addOtherDoes);
    const bodies = recordDoeBodies(server);
    fireEvent.change(within(card).getByLabelText("Radioss 조립 폴더"), { target: { value: ASSEM } });
    fireEvent.click(within(card).getByRole("button", { name: "확인" }));
    await within(card).findByText(/starter/);
    pickReuse(card);
    expect(within(card).queryByLabelText("run 수")).toBeNull();
    expect(within(card).getByTestId("reuse-help").textContent).toContain("등가성 판정");
    expect(runBtn(card).disabled).toBe(true);
    await waitFor(() => expect(opt(doeSelect(card), "LatinHyperCube").disabled).toBe(false));
    expect(opt(doeSelect(card), "다른 변수 DOE").disabled).toBe(true);
    expect(opt(doeSelect(card), "다른 변수 DOE").textContent).toContain("파라미터 이름이 다릅니다");
    expect(opt(doeSelect(card), "생성 중 DOE").disabled).toBe(true);
    expect(opt(doeSelect(card), "생성 중 DOE").textContent).toContain("표본표가 준비되지 않았습니다");
    fireEvent.change(doeSelect(card), { target: { value: "doe-1" } });
    await waitFor(() => expect(runBtn(card).disabled).toBe(false));
    fireEvent.click(runBtn(card));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({ generator: "platform", sampling: { kind: "train_doe", doe_id: "doe-1" }, radioss_assem_path: ASSEM, on_run_failure: "fail" });
    expect(bodies[0].sampling).toEqual({ kind: "train_doe", doe_id: "doe-1" });
    act(() => server.finishAll());
    await waitFor(() => expect(within(card).getByTestId("doe-result-line").textContent).toContain("표본표 재사용 · 플랫폼 · run 30개"), { timeout: 4000 });
    // 원본 표본값·run 이름 그대로
    expect(server.p2.doeSamples[server.p2.does[0].id]).toEqual(server.p2.doeSamples["doe-1"]);
  });

  it("다른 표본 방식으로 돌아가면 기존 입력이 돌아온다", async () => {
    const { card } = await openCard({}, addOtherDoes);
    pickReuse(card);
    fireEvent.change(within(card).getByLabelText("표본 방식"), { target: { value: "lhs" } });
    expect(within(card).getByLabelText("run 수")).toBeTruthy();
    expect(within(card).queryByLabelText("재사용할 DOE")).toBeNull();
  });

  it("서버 오류(422 DOE_SAMPLING_INVALID)는 한국어 problems로 보인다", async () => {
    const { server, card } = await openCard({}, addOtherDoes);
    fireEvent.change(within(card).getByLabelText("Radioss 조립 폴더"), { target: { value: ASSEM } });
    fireEvent.click(within(card).getByRole("button", { name: "확인" }));
    await within(card).findByText(/starter/);
    pickReuse(card);
    await waitFor(() => expect(opt(doeSelect(card), "LatinHyperCube").disabled).toBe(false));
    fireEvent.change(doeSelect(card), { target: { value: "doe-1" } });
    server.p2.doeSamples["doe-1"] = [{ run_key: "run__00001", values: { THK_TOP: 0.5 }, measured: {} }]; // 이름 집합이 화면 확인 뒤 바뀐 경우
    fireEvent.click(runBtn(card));
    const list = await within(card).findByTestId("doe-problems");
    expect(list.textContent).toContain("파라미터 이름이 다릅니다");
    expect(list.textContent).toContain("원본 DOE에 없음");
  });
});

describe("①-3 native: 다른 DOE 표본표 재사용", () => {
  afterEach(() => vi.restoreAllMocks());

  it("native도 같은 항목(LHS(Native) 옆) — 이름 같은 DOE만 활성, 요청 sampling train_doe(run 수·시드 없음)·조립 폴더", async () => {
    const { server, card } = await openCard({}, nativeSetup);
    const bodies = recordDoeBodies(server);
    await within(card).findByTestId("doe-native");
    const kind = within(card).getByLabelText("표본 방식") as HTMLSelectElement;
    expect([...kind.options].map((o) => o.value).slice(-1)).toEqual(["train_doe"]); // doe-methods.md DM-C2: Altair와 같은 목록 끝에 재사용 항목
    expect(kind.value).toBe("lhs");
    pickReuse(card);
    expect(within(card).queryByLabelText("run 수")).toBeNull();
    expect(within(card).getByTestId("reuse-help").textContent).toContain("등가성 판정");
    fireEvent.change(within(card).getByLabelText("Radioss 조립 폴더"), { target: { value: ASSEM } });
    fireEvent.click(within(card).getByRole("button", { name: "확인" }));
    await within(card).findByText(/starter/);
    await waitFor(() => expect(opt(doeSelect(card), "native 원본").disabled).toBe(false));
    expect(opt(doeSelect(card), "LatinHyperCube").disabled).toBe(true);
    expect(opt(doeSelect(card), "LatinHyperCube").textContent).toContain("파라미터 이름이 다릅니다");
    fireEvent.change(doeSelect(card), { target: { value: "doe-n" } });
    await waitFor(() => expect(runBtn(card).disabled).toBe(false));
    fireEvent.click(runBtn(card));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({ generator: "platform", sampling: { kind: "train_doe", doe_id: "doe-n" }, radioss_assem_path: ASSEM, on_run_failure: "continue" });
    expect(bodies[0].sampling).toEqual({ kind: "train_doe", doe_id: "doe-n" });
    act(() => server.finishAll());
    await waitFor(() => expect(within(card).getByTestId("doe-result-line").textContent).toContain("표본표 재사용(Native) · 플랫폼 · run 2개"), { timeout: 4000 });
  });
});
