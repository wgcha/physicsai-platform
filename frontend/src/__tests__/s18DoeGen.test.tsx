// V3-S18-10(phase3.md §23.11): ①-3 DOE 생성 카드 — 생성 방식 세그먼트(기본 = /status 값)·방식별 FeatureGate·표본 방식 8종 드롭다운(추천)·td_* 설명 상자·
// 방식별 요청 body(hyperstudy body는 기존과 동일)·실제 run 수·동시 수·실패 처리 체크·422 problems·결과 줄 gen·호환 회색 줄.
import { describe, expect, it } from "vitest";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { renderApp, STUDY } from "../test/render";
import type { MockServer } from "../mock/server";
import text from "./fixtures/samplingText.json";
import { HS_COMPAT_NOTE, HS_NOTE, PLATFORM_KINDS, SAMPLING_LABEL, type PlatformKind } from "../lib/sampling";
import { buildHyperstudyParams, buildPlatformParams, buildSampling, doeLimits, initialPlatform, platformRuns, type PlatformState } from "../stages/stage1/doeGenParams";
import type { MockOptions } from "../mock/server";

const ASSEM = "E:/shared/AI_WORK/cushion/00_inbox/radioss_assem";
const fx = text.descriptions as Record<string, { name: string; lines: string[] }>;
const NAMES = ["THK_TOP", "THK_FOAM", "RIB_H", "RIB_N"]; // ①-2 사용 변수 4개(목 시드)

async function openCard(opts: MockOptions = {}) {
  const r = renderApp(`${STUDY}/1`, { user: "power", ...opts });
  const card = await screen.findByRole("region", { name: "DOE · Radioss 입력" });
  return { ...r, card };
}
/** 조립 폴더를 입력하고 확인(목은 ok) */
async function confirmPath(card: HTMLElement) {
  fireEvent.change(within(card).getByLabelText("Radioss 조립 폴더"), { target: { value: ASSEM } });
  fireEvent.click(within(card).getByRole("button", { name: "확인" }));
  await within(card).findByText(/starter/);
}
const runBtn = (card: HTMLElement) => within(card).getByRole("button", { name: "입력 생성" }) as HTMLButtonElement;
const seg = (card: HTMLElement, group: string, name: string) => within(within(card).getByRole("group", { name: group })).getByRole("button", { name });
const lines = (card: HTMLElement) => [1, 2, 3, 4].map((n) => within(card).getByTestId(`samp-line-${n}`).firstChild!.textContent);
const pick = (card: HTMLElement, kind: PlatformKind) => fireEvent.change(within(card).getByLabelText("표본 방식"), { target: { value: kind } });
const runsText = (card: HTMLElement) => within(card).getByTestId("td-runs").textContent;

/** POST /studies/{id}/jobs(TD_DOE_GEN) 요청 본문 기록(목이 params를 고치기 전 사본) */
function recordDoeBodies(server: MockServer) {
  const bodies: { job_type: string; params: Record<string, unknown> }[] = [];
  const orig = server.handle.bind(server);
  server.handle = (m, p, q, b, h) => {
    if (m === "POST" && /\/studies\/[^/]+\/jobs$/.test(p) && (b as { job_type?: string } | null)?.job_type === "TD_DOE_GEN") bodies.push(structuredClone(b) as (typeof bodies)[number]);
    return orig(m, p, q, b, h);
  };
  return bodies;
}

describe("V3-S18-10 ①-3 생성 방식 세그먼트·FeatureGate", () => {
  it("기본 = /status.limits.configured.doe_generator_default(플랫폼). 설정이 hyperstudy면 호환 모드로 열린다. 저장하지 않는다", async () => {
    const a = await openCard();
    expect(seg(a.card, "생성 방식", "플랫폼 생성(동시 실행)").getAttribute("aria-pressed")).toBe("true");
    expect(seg(a.card, "생성 방식", "원본 HyperStudy(호환)").getAttribute("aria-pressed")).toBe("false");
    expect(within(a.card).getByTestId("doe-platform")).toBeTruthy();
    expect(within(a.card).queryByLabelText("DOE 유형")).toBeNull();
    fireEvent.click(seg(a.card, "생성 방식", "원본 HyperStudy(호환)"));
    expect(await within(a.card).findByLabelText("DOE 유형")).toBeTruthy();
    expect(within(a.card).queryByTestId("doe-platform")).toBeNull();
    a.unmount();

    const b = await openCard({ doeGenerator: "hyperstudy" });
    expect(seg(b.card, "생성 방식", "원본 HyperStudy(호환)").getAttribute("aria-pressed")).toBe("true");
    expect(await within(b.card).findByLabelText("DOE 유형")).toBeTruthy();
    expect(Object.keys(localStorage).filter((k) => /doe|generator/i.test(k))).toEqual([]); // 방식 선택은 저장하지 않는다
  });

  it("실행 버튼의 FeatureGate는 방식별: platform = train_doe_platform, hyperstudy = train_doe", async () => {
    const a = await openCard({ disabledFeatures: ["train_resp", "train_doe_platform"] });
    await confirmPath(a.card);
    expect(within(a.card).getByTestId("feature-off-train_doe_platform")).toBeTruthy();
    expect(runBtn(a.card).disabled).toBe(true);
    fireEvent.click(seg(a.card, "생성 방식", "원본 HyperStudy(호환)"));
    await within(a.card).findByLabelText("Random Seed");
    expect(within(a.card).queryByTestId("feature-off-train_doe_platform")).toBeNull();
    expect(within(a.card).queryByTestId("feature-off-train_doe")).toBeNull();
    expect(runBtn(a.card).disabled).toBe(false);
    a.unmount();

    const b = await openCard({ disabledFeatures: ["train_resp", "train_doe"] });
    await confirmPath(b.card);
    expect(within(b.card).queryByTestId("feature-off-train_doe")).toBeNull();
    expect(runBtn(b.card).disabled).toBe(false);
    fireEvent.click(seg(b.card, "생성 방식", "원본 HyperStudy(호환)"));
    expect(await within(b.card).findByTestId("feature-off-train_doe")).toBeTruthy();
    expect(runBtn(b.card).disabled).toBe(true);
  });
});

describe("V3-S18-10 표본 방식 드롭다운·설명 상자", () => {
  it("8개(묶음 3), 기본 lhs_opt + 추천 배지, 고를 때마다 td_* 설명문 4줄이 픽스처와 같다", async () => {
    const { card } = await openCard();
    const sel = within(card).getByLabelText("표본 방식") as HTMLSelectElement;
    expect(sel.value).toBe("lhs_opt");
    expect([...sel.options].map((o) => o.value)).toEqual(PLATFORM_KINDS);
    expect([...sel.options].map((o) => o.textContent)).toEqual(PLATFORM_KINDS.map((k) => SAMPLING_LABEL[k] + (k === "lhs_opt" ? " · 추천" : "")));
    expect([...sel.querySelectorAll("optgroup")].map((g) => g.label)).toEqual(["공간 채움(AI 학습·대리모델)", "요인 설계(경향·선별)", "2차 응답면"]);
    expect(within(card).getByTestId("samp-desc").getAttribute("data-desc-id")).toBe("td_lhs_opt");
    expect(within(card).getByTestId("samp-badge").textContent).toBe("추천");
    expect(within(card).getByTestId("samp-calc").textContent!.trim()).toBe("현재 변수 4개 → 권장 40");
    for (const kind of PLATFORM_KINDS) {
      pick(card, kind);
      expect(within(card).getByTestId("samp-desc").getAttribute("data-desc-id"), kind).toBe(`td_${kind}`);
      expect(within(card).getByTestId("samp-desc").querySelector("b")!.textContent, kind).toBe(fx[`td_${kind}`].name);
      expect(lines(card), kind).toEqual(fx[`td_${kind}`].lines);
      expect(!!within(card).queryByTestId("samp-badge"), kind).toBe(kind === "lhs_opt");
    }
    // ①은 HyperStudy 회색 줄(HS_NOTE)이 플랫폼 모드에는 없다
    expect(within(card).queryByTestId("hs-note")).toBeNull();
  });

  it("방식별 입력과 실제 run 수(§23.9): lhs·lhs_opt·sobol·fullfact·fracfact·pb·bbd·ccd", async () => {
    const { card } = await openCard();
    // lhs_opt: run 수(권장 40)·시드·기준
    expect((within(card).getByLabelText("run 수") as HTMLInputElement).value).toBe("40");
    expect((within(card).getByLabelText("시드") as HTMLInputElement).value).toBe("1");
    expect(seg(card, "최적화 기준", "최소 거리").getAttribute("aria-pressed")).toBe("true");
    expect(runsText(card)).toBe("실제 run 40개");
    fireEvent.change(within(card).getByLabelText("run 수"), { target: { value: "25" } });
    expect(runsText(card)).toBe("실제 run 25개");
    fireEvent.change(within(card).getByLabelText("run 수"), { target: { value: "501" } });
    expect(runsText(card)).toBe("실제 run 501개 (상한 500개 초과)");
    fireEvent.change(within(card).getByLabelText("run 수"), { target: { value: "" } });
    expect(runsText(card)).toContain("run 수를 확인하세요");
    expect(runBtn(card).disabled).toBe(true);
    // lhs: 기준 없음, 권장 40
    pick(card, "lhs");
    expect((within(card).getByLabelText("run 수") as HTMLInputElement).value).toBe("40");
    expect(within(card).queryByRole("group", { name: "최적화 기준" })).toBeNull();
    // sobol: 2^m 드롭다운(≤ 상한 500 → 4~256), 권장 = 10×4 이상인 가장 작은 2^m = 64
    pick(card, "sobol");
    const so = within(card).getByLabelText("run 수") as HTMLSelectElement;
    expect([...so.options].map((o) => o.value)).toEqual(["4", "8", "16", "32", "64", "128", "256"]);
    expect(so.value).toBe("64");
    expect(runsText(card)).toBe("실제 run 64개");
    // fullfact: 변수별 수준(기본 3^4 = 81 ≤ 500이면 3)
    pick(card, "fullfact");
    for (const n of NAMES) expect((within(card).getByLabelText(`${n} 수준`) as HTMLInputElement).value).toBe("3");
    expect(runsText(card)).toBe("실제 run 81개");
    fireEvent.change(within(card).getByLabelText("THK_TOP 수준"), { target: { value: "4" } });
    expect(runsText(card)).toBe("실제 run 108개");
    for (const n of NAMES) fireEvent.change(within(card).getByLabelText(`${n} 수준`), { target: { value: "10" } });
    expect(runsText(card)).toBe("실제 run 10000개 (상한 500개 초과 — 수준을 줄이세요)");
    // fracfact: 해상도 V(기본)·IV
    pick(card, "fracfact");
    expect(runsText(card)).toBe("실제 run 16개");
    fireEvent.click(seg(card, "해상도", "IV"));
    expect(runsText(card)).toBe("실제 run 8개");
    // pb·bbd·ccd: 설계가 정하는 run 수
    pick(card, "pb");
    expect(runsText(card)).toBe("실제 run 8개");
    pick(card, "bbd");
    expect(runsText(card)).toBe("실제 run 25개");
    pick(card, "ccd");
    expect(runsText(card)).toBe("실제 run 25개");
    expect(seg(card, "CCD α", "면중심").getAttribute("aria-pressed")).toBe("true");
  });
});

describe("V3-S18-10 요청 body", () => {
  it("플랫폼 기본: lhs_opt 40·시드 1·maximin, 동시 4(상한 8 안으로 보정), on_run_failure=fail → 체크하면 continue", async () => {
    const { card, server } = await openCard();
    const bodies = recordDoeBodies(server);
    await confirmPath(card);
    const multi = within(card).getByLabelText("동시 실행 수") as HTMLInputElement;
    expect(multi.value).toBe("4");
    expect(within(card).getByText(/^1~8 · run마다 SimLab·HyperMesh를 동시에 실행합니다/)).toBeTruthy();
    expect(within(card).queryByText(/multiexec/)).toBeNull();
    fireEvent.change(multi, { target: { value: "99" } });
    expect(multi.value).toBe("8");
    fireEvent.change(multi, { target: { value: "4" } });
    const chk = within(card).getByRole("checkbox", { name: "실패한 run이 있어도 성공한 run으로 DOE 완료" }) as HTMLInputElement;
    expect(chk.checked).toBe(false);
    fireEvent.click(runBtn(card));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0].params).toEqual({
      generator: "platform",
      sampling: { kind: "lhs_opt", count: 40, seed: 1, criterion: "maximin" },
      multi_execution: 4,
      radioss_assem_path: ASSEM,
      on_run_failure: "fail",
    });
    // 작업 하나가 끝나야 다음 실행(버튼은 실행 중 비활성) — 끝낸 뒤 체크하고 다시 보낸다
    act(() => server.finishAll());
    await waitFor(() => expect(runBtn(card).disabled).toBe(false));
    fireEvent.click(chk);
    fireEvent.click(seg(card, "최적화 기준", "상관 최소"));
    fireEvent.change(within(card).getByLabelText("시드"), { target: { value: "7" } });
    fireEvent.click(runBtn(card));
    await waitFor(() => expect(bodies).toHaveLength(2));
    expect(bodies[1].params).toMatchObject({ generator: "platform", sampling: { kind: "lhs_opt", count: 40, seed: 7, criterion: "corr" }, on_run_failure: "continue" });
  });

  it("원본 HyperStudy(호환): body는 기존과 같다(generator·sampling·on_run_failure 없음), 동시 수 기본 1, 회색 줄 2개", async () => {
    const { card, server } = await openCard();
    const bodies = recordDoeBodies(server);
    fireEvent.click(seg(card, "생성 방식", "원본 HyperStudy(호환)"));
    await within(card).findByLabelText("Random Seed");
    await confirmPath(card);
    expect(within(card).getByTestId("hs-note").textContent).toBe(HS_NOTE);
    expect(within(card).getByTestId("hs-compat-note").textContent).toBe(HS_COMPAT_NOTE);
    expect((within(card).getByLabelText("동시 실행 수") as HTMLInputElement).value).toBe("1");
    expect(within(card).getByText("1~8 · 높일수록 빠르지만 CPU·라이선스를 더 씀")).toBeTruthy();
    fireEvent.click(runBtn(card));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0].params).toEqual({ doe_label: "LatinHyperCube", options: { RANDOM_SEED: 1 }, multi_execution: 1, radioss_assem_path: ASSEM, num_runs: 30 });
    expect(Object.keys(bodies[0].params).sort()).toEqual(["doe_label", "multi_execution", "num_runs", "options", "radioss_assem_path"]);
  });

  it("순수 함수: 8개 kind의 sampling 입력 모양(§23.4), 입력이 올바르지 않으면 null", () => {
    const base = initialPlatform();
    const b = (p: Partial<PlatformState>) => buildSampling({ ...base, ...p }, NAMES, 500);
    expect(b({ kind: "lhs", count: "30", seed: "3" })).toEqual({ kind: "lhs", count: 30, seed: 3 });
    expect(b({ kind: "lhs_opt", criterion: "corr" })).toEqual({ kind: "lhs_opt", count: 40, seed: 1, criterion: "corr" });
    expect(b({ kind: "sobol", count: "32" })).toEqual({ kind: "sobol", count: 32, seed: 1 });
    expect(b({ kind: "fullfact", levels: { THK_TOP: "5" } })).toEqual({ kind: "fullfact", levels: { THK_TOP: 5, THK_FOAM: 3, RIB_H: 3, RIB_N: 3 } });
    expect(b({ kind: "fracfact", resolution: 4 })).toEqual({ kind: "fracfact", resolution: 4 });
    expect(b({ kind: "pb" })).toEqual({ kind: "pb" });
    expect(b({ kind: "bbd" })).toEqual({ kind: "bbd" });
    expect(b({ kind: "ccd", alpha: "inscribed" })).toEqual({ kind: "ccd", alpha: "inscribed" });
    expect(b({ kind: "lhs", count: "1" })).toBeNull();
    expect(b({ kind: "sobol", count: "3" })).toBeNull();
    expect(b({ kind: "lhs_opt", seed: "" })).toBeNull();
    expect(b({ kind: "lhs_opt", count: "2.5" })).toBeNull();
    expect(buildPlatformParams({ ...base, count: "" }, NAMES, { multi: 4, assemPath: ASSEM, maxRuns: 500, continueOnFailure: false })).toBeNull();
    expect(buildHyperstudyParams({ label: "Sobol", options: { SEED: 0 }, multi: 2, assemPath: ASSEM, runsEditable: false, runs: "32" })).toEqual({ doe_label: "Sobol", options: { SEED: 0 }, multi_execution: 2, radioss_assem_path: ASSEM });
    expect(platformRuns({ ...base, kind: "bbd" }, ["A", "B"], 500)).toEqual({ n: null, over: false }); // 변수 3개 미만 = 지원 범위 밖
  });

  it("status 값: 상한·동시 수 기본을 /status.limits.configured에서 읽고, 없으면 설정 기본값", () => {
    expect(doeLimits(null)).toEqual({ generatorDefault: "platform", parallelDefault: 4, maxRuns: 500, maxMulti: 8 });
    expect(doeLimits({ limits: { configured: { max_multi_execution: 2, doe_generator_default: "hyperstudy", doe_platform_parallel_default: 4, doe_platform_max_runs: 120 } } })).toEqual({ generatorDefault: "hyperstudy", parallelDefault: 2, maxRuns: 120, maxMulti: 2 });
  });
});

describe("V3-S18-10 422 problems·결과 줄", () => {
  it("422 DOE_SAMPLING_INVALID: problems 문구를 목록으로 보여 준다", async () => {
    const { card } = await openCard();
    await confirmPath(card);
    pick(card, "fullfact");
    for (const n of NAMES) fireEvent.change(within(card).getByLabelText(`${n} 수준`), { target: { value: "10" } });
    fireEvent.click(runBtn(card));
    const list = await within(card).findByTestId("doe-problems");
    expect([...list.querySelectorAll("li")].map((li) => li.textContent)).toEqual(["전체 요인 run 수 10000개가 상한 500개를 넘습니다 — 수준 수를 줄이세요"]);
    // 다른 오류(run 수 상한)도 같은 목록
    pick(card, "lhs");
    fireEvent.change(within(card).getByLabelText("run 수"), { target: { value: "501" } });
    fireEvent.click(runBtn(card));
    await waitFor(() => expect([...within(card).getByTestId("doe-problems").querySelectorAll("li")].map((li) => li.textContent)).toEqual(["run 수는 500개까지입니다"]));
  });

  it("결과 줄: <이름> · <방식> · run N개 · 상태 — platform이면 생성 완료·실패 / 전체, hyperstudy는 gen 없음", async () => {
    const { card, server } = await openCard();
    expect((await within(card).findByTestId("doe-result-line")).textContent).toBe("LatinHyperCube · HyperStudy · run 30개 · 샘플 표 있음"); // 시드 DOE
    await confirmPath(card);
    pick(card, "bbd");
    fireEvent.click(runBtn(card));
    await waitFor(() => expect(server.p2.does[0].generator).toBe("platform")); // 작업 생성 = BUILDING 행(gen 집계 전부 대기)
    expect(server.p2.does[0]).toMatchObject({ status: "BUILDING", gen: { total: 25, pending: 25, running: 0, done: 0, failed: 0 } });
    act(() => server.finishAll());
    await waitFor(() => expect(within(card).getByTestId("doe-result-line").textContent).toBe("Box–Behnken · 플랫폼 · run 25개 · 샘플 표 있음 · 생성 완료 25 · 실패 0 / 전체 25"), { timeout: 4000 });
    const d = server.p2.does[0];
    expect(d).toMatchObject({ generator: "platform", doe_type: "BBD", doe_label: "Box–Behnken", num_runs_requested: 25, multi_execution: 4, options: {} });
    expect(d.sampling).toMatchObject({ kind: "bbd", desc_id: "td_bbd" });
  });
});
