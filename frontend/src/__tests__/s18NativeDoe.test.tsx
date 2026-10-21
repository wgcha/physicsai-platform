// geometry-engine.md §8 ①-3 native DOE(§7.3.3·§7.3.8, phase3 §23.4 S18 통합): native 학습 설정이면 tpl 대기 없이 활성,
// 생성 방식 PLATFORM·표본 LHS(Native) 고정(HyperStudy·다른 방식은 비활성+사유), run 수·시드·동시 수·실패 처리, 스킵 run category 배지,
// 세트 기준 다중 baseline = 층화 안내 + 매칭표 확정 게이트(409 PARAM_MAP_UNCONFIRMED 안내).
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { renderApp, STUDY } from "../test/render";
import type { MockServer } from "../mock/server";
import type { MockOptions } from "../mock/server";
import { nativeTrainParams } from "../mock/geometry";
import { buildNativeParams, initialNative, skippedRuns, stratumCounts } from "../stages/stage1/doeGenParams";

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
const nativeSetup = (s: MockServer) => Object.assign(s.p2.setups["s-cushion"], { engine: "native", parameters: nativeTrainParams(), tpl: null });

async function openCard(opts: MockOptions, setup: (s: MockServer) => void) {
  const r = renderApp(`${STUDY}/1`, { user: "power", ...opts }, setup);
  const card = await screen.findByRole("region", { name: "DOE · Radioss 입력" });
  return { ...r, card };
}
const runBtn = (card: HTMLElement) => within(card).getByRole("button", { name: "입력 생성" }) as HTMLButtonElement;
const seg = (card: HTMLElement, name: string) => within(within(card).getByRole("group", { name: "생성 방식" })).getByRole("button", { name }) as HTMLButtonElement;
const waitNative = (card: HTMLElement) => within(card).findByTestId("doe-native");

describe("①-3 native DOE 생성(§8)", () => {
  afterEach(() => vi.restoreAllMocks());

  it("native 학습 설정: tpl 없이 활성, PLATFORM·LHS(Native) 고정 — HyperStudy·다른 표본 방식 비활성+사유", async () => {
    const { card } = await openCard({}, nativeSetup);
    await waitNative(card);
    expect(seg(card, "플랫폼 생성 · LHS(Native)").getAttribute("aria-pressed")).toBe("true");
    const hs = seg(card, "HyperStudy(레거시)");
    expect(hs.disabled).toBe(true);
    expect(hs.title).toBe("Native 형상 엔진 DOE는 플랫폼 생성 LHS만 됩니다");
    const kind = within(card).getByLabelText("표본 방식") as HTMLSelectElement;
    expect(kind.value).toBe("lhs");
    expect([...kind.options].filter((o) => !o.disabled).map((o) => o.textContent)).toEqual(["LHS(Native)", "다른 DOE 표본표 재사용"]);
    expect([...kind.options].filter((o) => o.disabled).length).toBeGreaterThan(3);
    expect(within(card).getByTestId("native-only-note").textContent).toContain("HyperStudy·다른 표본 방식");
    expect(within(card).queryByText(/tpl을 먼저 생성/)).toBeNull();
    expect(within(card).getByText("조립 폴더를 입력하고 확인하세요")).toBeTruthy();
  });

  it("요청 params: generator platform + sampling lhs(count·seed)·multi_execution·on_run_failure·조립 폴더 → 결과 줄 LHS(Native)·스킵 run category 배지", async () => {
    const { server, card } = await openCard({}, nativeSetup);
    const bodies = recordDoeBodies(server);
    await waitNative(card);
    fireEvent.change(within(card).getByLabelText("Radioss 조립 폴더"), { target: { value: ASSEM } });
    fireEvent.click(within(card).getByRole("button", { name: "확인" }));
    await within(card).findByText(/starter/);
    fireEvent.change(within(card).getByLabelText("run 수"), { target: { value: "12" } });
    fireEvent.change(within(card).getByLabelText("시드"), { target: { value: "7" } });
    fireEvent.change(within(card).getByLabelText("동시 실행 수"), { target: { value: "3" } });
    fireEvent.click(within(card).getByLabelText(/형상 생성에 실패한 run은 건너뛰고/));
    await waitFor(() => expect(runBtn(card).disabled).toBe(false));
    fireEvent.click(runBtn(card));
    await waitFor(() => expect(bodies.length).toBe(1));
    expect(bodies[0]).toEqual({ generator: "platform", sampling: { kind: "lhs", count: 12, seed: 7 }, multi_execution: 3, on_run_failure: "fail", radioss_assem_path: ASSEM });
    act(() => server.finishAll());
    await waitFor(() => expect(within(card).getByTestId("doe-result-line").textContent).toContain("LHS(Native) · 플랫폼 · run 11개"));
    const sk = await within(card).findByTestId("doe-skipped");
    expect(sk.textContent).toContain("run__00012");
    expect(within(sk).getByText("품질 미달").className).toBe("pill bad");
  });

  it("세트 기준 다중 baseline: 조립 폴더 입력 없음·층화 안내, 미확정이면 '매칭표 확정 필요'로 비활성", async () => {
    const { card } = await openCard({ geometry: "multi" }, () => undefined);
    const basis = (await within(card).findByLabelText("형상 기준")) as HTMLSelectElement;
    expect([...basis.options].map((o) => o.textContent)).toEqual(["①-1 추출 피처(조립 폴더 지정)", "템플릿 쿠션 native v1 · baseline 2개"]);
    fireEvent.change(basis, { target: { value: "ps-n1" } });
    expect(within(card).queryByLabelText("Radioss 조립 폴더")).toBeNull();
    expect(seg(card, "HyperStudy(레거시)").disabled).toBe(true);
    expect(within(card).getByTestId("native-strata").textContent).toContain("다중 baseline 2개 — 층화 LHS로 baseline마다 나눠 뽑습니다 (B1 10개 · B2 10개)");
    expect(within(card).getByTestId("native-strata").textContent).toContain("매칭표 확정 필요");
    expect(runBtn(card).disabled).toBe(true);
    expect(within(card).getByText("매칭표 확정 필요(④ 다중 baseline)")).toBeTruthy();
  });

  it("서버 409 PARAM_MAP_UNCONFIRMED → 오류 문구 + 확정 안내, 확정 후에는 param_set_id로 생성", async () => {
    // 화면 목록은 확정으로 보이지만 서버 매칭표는 초안(다른 사용자가 되돌린 경우)
    const { server, card } = await openCard({ geometry: "multi" }, (s) => (s.paramSets.find((p) => p.id === "ps-n1")!.param_map_status = "confirmed"));
    const bodies = recordDoeBodies(server);
    fireEvent.change(await within(card).findByLabelText("형상 기준"), { target: { value: "ps-n1" } });
    await waitFor(() => expect(runBtn(card).disabled).toBe(false));
    fireEvent.click(runBtn(card));
    expect((await within(card).findByRole("alert")).textContent).toContain("다중 baseline 매칭표가 확정되지 않았습니다(미결정 행 4개)");
    expect(within(card).getByTestId("map-unconfirmed").textContent).toContain("[확정]");
    expect(bodies[0]).toEqual({ generator: "platform", sampling: { kind: "lhs", count: 20, seed: 1 }, multi_execution: 4, on_run_failure: "continue", param_set_id: "ps-n1" });
    const rec = server.geom.get("ps-n1")!;
    rec.map = { ...rec.map!, status: "confirmed" };
    fireEvent.click(runBtn(card));
    await waitFor(() => expect(server.jobs.some((j) => j.job_type === "TD_DOE_GEN" && j.params.param_set_id === "ps-n1" && j.params.doe_type === "NATIVE_LHS")).toBe(true));
  });
});

describe("native DOE params 순수 함수", () => {
  it("run 수 2~상한·시드 정수, 세트 기준이면 조립 폴더 대신 param_set_id", () => {
    const s = initialNative();
    expect(buildNativeParams(s, { multi: 2, maxRuns: 500, assemPath: "A", paramSetId: null })).toEqual({ generator: "platform", sampling: { kind: "lhs", count: 20, seed: 1 }, multi_execution: 2, on_run_failure: "continue", radioss_assem_path: "A" });
    expect(buildNativeParams(s, { multi: 2, maxRuns: 500, assemPath: "", paramSetId: "ps-n1" })).toMatchObject({ param_set_id: "ps-n1" });
    expect(buildNativeParams({ ...s, count: "1" }, { multi: 1, maxRuns: 500, assemPath: "A", paramSetId: null })).toBeNull();
    expect(buildNativeParams({ ...s, count: "501" }, { multi: 1, maxRuns: 500, assemPath: "A", paramSetId: null })).toBeNull();
    expect(buildNativeParams({ ...s, seed: "" }, { multi: 1, maxRuns: 500, assemPath: "A", paramSetId: null })).toBeNull();
  });
  it("층화 run 수 = ⌊N/B⌋ + 앞쪽부터 나머지(차 ≤ 1), skipped_runs는 그 DOE 결과만", () => {
    expect(stratumCounts(20, 3)).toEqual([7, 7, 6]);
    expect(stratumCounts(5, 2)).toEqual([3, 2]);
    const res = { doe_id: "d1", skipped_runs: [{ run_key: "R0003", reason: "GEOM_INTERFERENCE", category: "INTERFERENCE", message: "간섭" }] };
    expect(skippedRuns(res, "d1")).toHaveLength(1);
    expect(skippedRuns(res, "d2")).toEqual([]);
    expect(skippedRuns(null, "d1")).toEqual([]);
  });
});
