// V-DM-8·9(docs/contracts/doe-methods.md): 지점별 허용 목록(SITE_KINDS)·방식별 칸·①-3 Native 기본 lhs(Altair와 같은 목록)·다중 baseline 층 안 생성기만·
// ① 표(CSV) 학습 범위 밖 막기(TABLE_OUT_OF_RANGE)·run 수 상한·불가 방식 회색·⑥ 탐색 방식(기본 lhs, 생략 body 불변)·④ halton·random.
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { renderApp, STUDY } from "../test/render";
import type { MockServer, MockOptions } from "../mock/server";
import { nativeTrainParams } from "../mock/geometry";
import {
  MULTI_BASELINE_REASON, SAMPLING_LABEL, SITE_DEFAULT, SITE_KINDS, checkTable, siteGroups, unavailableNote, type SamplingKind, type SiteId,
} from "../lib/sampling";
import { buildNativeParams, buildPlatformParams, buildSampling, initialNative, initialPlatform, platformRuns } from "../stages/stage1/doeGenParams";
import { buildBody, exploreIssue, type SoForm } from "../stages/stage5/surrogate/soRules";
import { buildSource, initialSampling } from "../stages/stage4/batch/samplingSource";
import type { ParamSet } from "../api/types";
import { DoePlatformFields } from "../stages/stage1/DoePlatformFields";

const ASSEM = "E:/shared/AI_WORK/cushion/00_inbox/radioss_assem";
const NAMES = ["THK_TOP", "THK_FOAM", "RIB_H", "RIB_N"]; // ①-2 사용 변수 4개(목 시드)
const FULL = ["lhs_opt", "sobol", "halton", "lhs", "random", "fullfact", "fracfact", "pb", "bbd", "ccd", "table", "train_doe"];

const nativeSetup = (s: MockServer) => Object.assign(s.p2.setups["s-cushion"], { engine: "native", parameters: nativeTrainParams(), tpl: null });
async function openCard(opts: MockOptions = {}, setup?: (s: MockServer) => void) {
  const r = renderApp(`${STUDY}/1`, { user: "power", ...opts }, setup);
  const card = await screen.findByRole("region", { name: "DOE · Radioss 입력" });
  return { ...r, card };
}
const sel = (card: HTMLElement) => within(card).getByLabelText("표본 방식") as HTMLSelectElement;
const pick = (card: HTMLElement, kind: string) => fireEvent.change(sel(card), { target: { value: kind } });
const optValues = (card: HTMLElement) => [...sel(card).options].map((o) => o.value);
const runsText = (card: HTMLElement) => within(card).getByTestId("td-runs").textContent;
const runBtn = (card: HTMLElement) => within(card).getByRole("button", { name: "입력 생성" }) as HTMLButtonElement;
function recordDoeBodies(server: MockServer) {
  const bodies: Record<string, unknown>[] = [];
  const orig = server.handle.bind(server);
  server.handle = (m, p, q, b, h) => {
    if (m === "POST" && /\/studies\/[^/]+\/jobs$/.test(p) && (b as { job_type?: string } | null)?.job_type === "TD_DOE_GEN") bodies.push(structuredClone((b as { params: Record<string, unknown> }).params));
    return orig(m, p, q, b, h);
  };
  return bodies;
}
async function confirmPath(card: HTMLElement) {
  fireEvent.change(within(card).getByLabelText("Radioss 조립 폴더"), { target: { value: ASSEM } });
  fireEvent.click(within(card).getByRole("button", { name: "확인" }));
  await within(card).findByText(/starter/);
}

describe("지점별 허용 목록 SITE_KINDS(DM-C1, §3)", () => {
  it("표 그대로: 6개 지점의 허용 kind·순서·화면 기본", () => {
    expect(SITE_KINDS.train_platform).toEqual(FULL);
    expect(SITE_KINDS.train_native).toEqual(FULL);
    expect(SITE_KINDS.batch).toEqual(FULL);
    expect(SITE_KINDS.train_native_multi).toEqual(["lhs_opt", "halton", "lhs", "random"]);
    expect(SITE_KINDS.batch_multi).toEqual(["lhs_opt", "halton", "lhs", "random"]);
    expect(SITE_KINDS.opt_explore).toEqual(["lhs", "lhs_opt", "sobol", "halton", "random"]);
    expect(SITE_DEFAULT).toEqual({ train_platform: "lhs_opt", train_native: "lhs", train_native_multi: "lhs", batch: "lhs_opt", batch_multi: "lhs", opt_explore: "lhs" });
  });
  it("siteGroups: 묶음 머리·순서(halton은 sobol 뒤, random은 lhs 뒤) 안에서 허용된 방식만, 지점 순서를 따른다", () => {
    expect(siteGroups("train_platform").map((g) => [g.label, g.kinds])).toEqual([
      ["공간 채움(AI 학습·대리모델)", ["lhs_opt", "sobol", "halton", "lhs", "random"]],
      ["요인 설계(경향·선별)", ["fullfact", "fracfact", "pb"]],
      ["2차 응답면", ["bbd", "ccd"]],
      ["직접 지정", ["table", "train_doe"]],
    ]);
    expect(siteGroups("train_native_multi")).toEqual([{ label: "공간 채움(AI 학습·대리모델)", kinds: ["lhs_opt", "halton", "lhs", "random"] }]);
    expect(siteGroups("opt_explore")[0].kinds).toEqual(["lhs", "lhs_opt", "sobol", "halton", "random"]);
  });
  it("모든 지점 kind에 표시 이름이 있다", () => {
    for (const site of Object.keys(SITE_KINDS) as SiteId[]) for (const k of SITE_KINDS[site]) expect(SAMPLING_LABEL[k as SamplingKind], `${site}/${k}`).toBeTruthy();
    expect(SAMPLING_LABEL.halton).toBe("Halton(스크램블 QMC)");
    expect(SAMPLING_LABEL.random).toBe("균일 랜덤");
  });
});

describe("①-3 Altair 플랫폼: 방식별 칸·run 수 경고·불가 회색", () => {
  afterEach(() => vi.restoreAllMocks());

  it("드롭다운 = train_platform 12항목(재사용 포함), 기본 lhs_opt, 방식별 칸만 보인다", async () => {
    const { card } = await openCard();
    expect(optValues(card)).toEqual(FULL);
    expect(sel(card).value).toBe("lhs_opt");
    const has = (name: string) => !!within(card).queryByLabelText(name) || !!within(card).queryByRole("group", { name });
    // lhs_opt: run 수·시드·기준
    expect([has("run 수"), has("시드"), has("최적화 기준")]).toEqual([true, true, true]);
    pick(card, "halton");
    expect((within(card).getByLabelText("run 수") as HTMLInputElement).value).toBe("40"); // 권장 10 × 변수 4
    expect((within(card).getByLabelText("시드") as HTMLInputElement).value).toBe("1");
    expect(has("최적화 기준")).toBe(false);
    expect(within(card).getByTestId("samp-desc").getAttribute("data-desc-id")).toBe("td_halton");
    expect(runsText(card)).toBe("실제 run 40개");
    pick(card, "random");
    expect([has("run 수"), has("시드"), has("최적화 기준")]).toEqual([true, true, false]);
    expect(within(card).getByTestId("samp-desc").getAttribute("data-desc-id")).toBe("td_random");
    pick(card, "pb");
    expect([has("run 수"), has("시드"), has("최적화 기준")]).toEqual([false, false, false]);
    pick(card, "table");
    expect([has("run 수"), has("시드")]).toEqual([false, false]);
    expect(within(card).getByLabelText("표 붙여넣기")).toBeTruthy();
    expect(within(card).getByTestId("samp-desc").getAttribute("data-desc-id")).toBe("td_table");
  });

  it("run 수 경고: 상한(500) 초과는 실제 run 수·상한값을 보이고 막는다(halton·random 포함)", async () => {
    const { card } = await openCard();
    await confirmPath(card);
    for (const k of ["halton", "random"]) {
      pick(card, k);
      fireEvent.change(within(card).getByLabelText("run 수"), { target: { value: "501" } });
      expect(runsText(card)).toBe("실제 run 501개 (상한 500개 초과)");
      expect(runBtn(card).disabled, k).toBe(true);
      fireEvent.change(within(card).getByLabelText("run 수"), { target: { value: "500" } });
      expect(runsText(card)).toBe("실제 run 500개");
      expect(runBtn(card).disabled, k).toBe(false);
    }
    pick(card, "fullfact");
    for (const n of NAMES) fireEvent.change(within(card).getByLabelText(`${n} 수준`), { target: { value: "10" } });
    expect(runsText(card)).toBe("실제 run 10000개 (상한 500개 초과 — 수준을 줄이세요)");
    expect(runBtn(card).disabled).toBe(true);
  });

  it("run 수가 폭증하는 방식은 변수 수에서 불가면 '— 변수 k개에서 불가'(상한 R 기준), 그 밖 방식은 항상 가능", () => {
    expect(unavailableNote("fullfact", 8, 500)).toBeNull(); // 2^8 = 256 ≤ 500
    expect(unavailableNote("fullfact", 9, 500)).toBe("— 변수 9개에서 불가"); // 모든 수준 2일 때도 2^9 = 512 > 500
    expect(unavailableNote("bbd", 2, 500)).toBe("— 변수 2개에서 불가");
    expect(unavailableNote("bbd", 16, 500)).toBeNull(); // 2·16·15 + 1 = 481
    expect(unavailableNote("bbd", 17, 500)).toBe("— 변수 17개에서 불가");
    expect(unavailableNote("bbd", 10, 200)).toBeNull();
    expect(unavailableNote("bbd", 11, 200)).toBe("— 변수 11개에서 불가"); // R=200 → k ≤ 10
    expect(unavailableNote("ccd", 12, 500)).toBe("— 변수 12개에서 불가");
    expect(unavailableNote("fracfact", 12, 500)).toBe("— 변수 12개에서 불가");
    expect(unavailableNote("pb", 1, 500)).toBe("— 변수 1개에서 불가");
    for (const k of ["lhs_opt", "sobol", "halton", "lhs", "random", "table", "train_doe"] as SamplingKind[]) expect(unavailableNote(k, 40, 500), k).toBeNull();
  });

  it("드롭다운 회색: 변수 12개에서 ccd·fracfact·fullfact(2^12)는 선택 불가 + 사유, halton·random은 가능", () => {
    const names = Array.from({ length: 12 }, (_, i) => `V${i + 1}`);
    render(<DoePlatformFields state={initialPlatform()} onChange={() => undefined} names={names} maxRuns={500} disabled={false} />);
    const o = (v: string) => [...(screen.getByLabelText("표본 방식") as HTMLSelectElement).options].find((x) => x.value === v)!;
    for (const k of ["fullfact", "fracfact", "ccd"]) {
      expect(o(k).disabled, k).toBe(true);
      expect(o(k).textContent, k).toContain("— 변수 12개에서 불가");
    }
    for (const k of ["lhs_opt", "halton", "random", "pb", "bbd", "table"]) expect(o(k).disabled, k).toBe(false);
  });
});

describe("①-3 표(CSV) 붙여넣기: 미리 검사와 학습 범위 밖 차단(TABLE_OUT_OF_RANGE)", () => {
  const names = ["A", "B"];
  const ranges = { A: [0, 10], B: [1, 2] } as Record<string, [number, number]>;
  it("순수 검사: 머리줄·행 수(2~상한)·값 유한·범위 밖", () => {
    expect(checkTable("A\tB\n1\t1.5\n9\t2", names, ranges, 500)).toEqual({ rows: 2, problems: [] });
    expect(checkTable("A,B\n1,1.5\n9,2", names, ranges, 500).problems).toEqual([]); // 쉼표도 허용
    expect(checkTable("A\n1\n2", names, ranges, 500).problems[0]).toMatchObject({ code: "TABLE_HEADER" });
    expect(checkTable("A,B,C\n1,1,1\n2,2,2", names, ranges, 500).problems[0].message).toContain("'C'");
    expect(checkTable("A,B\n1,1", names, ranges, 500).problems[0]).toMatchObject({ code: "TOO_FEW_ROWS" });
    expect(checkTable("A,B\n1,1\n2,2\n3,2", names, ranges, 2).problems[0]).toMatchObject({ code: "TOO_MANY_ROWS" });
    expect(checkTable("A,B\n1,x\n2,2", names, ranges, 500).problems[0]).toMatchObject({ code: "TABLE_VALUE" });
    expect(checkTable("A,B\n1,1\n2,2", names, ranges, 500, 3).problems[0]).toMatchObject({ code: "TEXT_TOO_LARGE" });
    const oor = checkTable("A,B\n1,1\n11,2", names, ranges, 500);
    expect(oor.problems).toEqual([{ code: "TABLE_OUT_OF_RANGE", message: "'A' 값 11가 학습 범위 0~10 밖입니다" }]);
    expect(checkTable("A,B\n1,1\n2,2.5", names, ranges, 500).problems[0].message).toBe("'B' 값 2.5가 학습 범위 1~2 밖입니다");
    expect(checkTable("A,B\n1,1\n99,9", names, null, 500).problems).toEqual([]); // 범위를 모르면(④ 같은 허용) 범위 검사 없음
  });
  it("params: 범위 안이면 {kind:'table', text}, 밖이면 null(생성 막음), 실제 run 수 = 행 수", () => {
    const ok = { ...initialPlatform(), kind: "table" as const, text: "A,B\n1,1\n2,2" };
    const t = { ranges };
    expect(buildSampling(ok, names, 500, t)).toEqual({ kind: "table", text: ok.text });
    expect(platformRuns(ok, names, 500, t)).toEqual({ n: 2, over: false });
    const out = { ...ok, text: "A,B\n1,1\n20,2" };
    expect(buildSampling(out, names, 500, t)).toBeNull();
    expect(platformRuns(out, names, 500, t).n).toBeNull();
    expect(buildPlatformParams(out, names, { multi: 2, assemPath: "A", maxRuns: 500, continueOnFailure: false, table: t })).toBeNull();
    expect(buildPlatformParams(ok, names, { multi: 2, assemPath: "A", maxRuns: 500, continueOnFailure: false, table: t })).toMatchObject({ generator: "platform", sampling: { kind: "table" } });
  });

  it("Altair 화면: 범위 밖 값을 붙여넣으면 TABLE_OUT_OF_RANGE 안내가 보이고 [입력 생성]이 막힌다, 범위 안으로 고치면 열린다", async () => {
    const { server, card } = await openCard();
    const bodies = recordDoeBodies(server);
    await confirmPath(card);
    pick(card, "table");
    const ta = within(card).getByLabelText("표 붙여넣기");
    const head = NAMES.join("\t");
    const setup = server.p2.setups["s-cushion"].parameters.filter((p) => p.use);
    const row = (f: (p: (typeof setup)[number]) => number) => setup.map((p) => f(p)).join("\t");
    const mid = row((p) => ((p.min ?? 0) + (p.max ?? 1)) / 2);
    const hi = row((p) => (p.max ?? 1) * 1.5 + 1);
    fireEvent.change(ta, { target: { value: `${head}\n${mid}\n${hi}` } });
    const alert = await within(card).findByTestId("td-table-problems");
    expect(alert.querySelector("[data-code]")!.getAttribute("data-code")).toBe("TABLE_OUT_OF_RANGE");
    expect(alert.textContent).toMatch(/학습 범위 .* 밖입니다/);
    expect(runBtn(card).disabled).toBe(true);
    fireEvent.change(ta, { target: { value: `${head}\n${mid}\n${mid}` } });
    expect(within(card).queryByTestId("td-table-problems")).toBeNull();
    expect(runsText(card)).toBe("실제 run 2개");
    await waitFor(() => expect(runBtn(card).disabled).toBe(false));
    fireEvent.click(runBtn(card));
    await waitFor(() => expect(bodies.length).toBe(1));
    expect(bodies[0]).toMatchObject({ generator: "platform", sampling: { kind: "table", text: `${head}\n${mid}\n${mid}` } });
  });
});

describe("①-3 Native: Altair 플랫폼 생성과 같은 목록, 기본 lhs", () => {
  afterEach(() => vi.restoreAllMocks());

  it("드롭다운 = train_native 12항목(회색·'LHS만' 문구 없음), 기본 lhs·run 수 20·시드 1, lhs 요청 body는 지금 그대로", async () => {
    const { server, card } = await openCard({}, nativeSetup);
    const bodies = recordDoeBodies(server);
    await within(card).findByTestId("doe-native");
    expect(optValues(card)).toEqual(FULL);
    expect(sel(card).value).toBe("lhs");
    expect([...sel(card).options].filter((o) => o.disabled)).toHaveLength(0);
    expect(card.textContent).not.toContain("LHS만");
    expect((within(card).getByLabelText("run 수") as HTMLInputElement).value).toBe("20");
    await confirmPath(card);
    await waitFor(() => expect(runBtn(card).disabled).toBe(false));
    fireEvent.click(runBtn(card));
    await waitFor(() => expect(bodies.length).toBe(1));
    expect(bodies[0]).toEqual({ generator: "platform", sampling: { kind: "lhs", count: 20, seed: 1 }, multi_execution: 4, on_run_failure: "continue", radioss_assem_path: ASSEM });
  });

  it("방식을 halton으로: 그 방식의 칸(run 수·시드)만, body = sampling {kind:'halton',count,seed}, 결과 줄 'Halton(스크램블 QMC)(Native)'", async () => {
    const { server, card } = await openCard({}, nativeSetup);
    const bodies = recordDoeBodies(server);
    await within(card).findByTestId("doe-native");
    await confirmPath(card);
    pick(card, "halton");
    expect(within(card).queryByRole("group", { name: "최적화 기준" })).toBeNull();
    fireEvent.change(within(card).getByLabelText("run 수"), { target: { value: "12" } });
    fireEvent.change(within(card).getByLabelText("시드"), { target: { value: "5" } });
    expect(runsText(card)).toBe("실제 run 12개");
    await waitFor(() => expect(runBtn(card).disabled).toBe(false));
    fireEvent.click(runBtn(card));
    await waitFor(() => expect(bodies.length).toBe(1));
    expect(bodies[0]).toEqual({ generator: "platform", sampling: { kind: "halton", count: 12, seed: 5 }, multi_execution: 4, on_run_failure: "continue", radioss_assem_path: ASSEM });
    act(() => server.finishAll());
    await waitFor(() => expect(within(card).getByTestId("doe-result-line").textContent).toContain("Halton(스크램블 QMC)(Native) · 플랫폼 · run 11개"));
    expect(server.p2.does[0]).toMatchObject({ doe_type: "HALTON", engine: "native", sampling: { kind: "halton", desc_id: "td_halton", meta: null } });
  });

  it("Native 표(CSV): 범위 밖이면 막고(TABLE_OUT_OF_RANGE), 서버 검사도 같은 코드로 422", async () => {
    const { server, card } = await openCard({}, nativeSetup);
    await within(card).findByTestId("doe-native");
    await confirmPath(card);
    pick(card, "table");
    const used = server.p2.setups["s-cushion"].parameters.filter((p) => p.use);
    const head = used.map((p) => p.name).join(",");
    const mid = used.map((p) => ((p.min ?? 0) + (p.max ?? 1)) / 2).join(",");
    const bad = used.map((p) => (p.max ?? 1) + 100).join(",");
    fireEvent.change(within(card).getByLabelText("표 붙여넣기"), { target: { value: `${head}\n${mid}\n${bad}` } });
    expect((await within(card).findByTestId("td-table-problems")).textContent).toContain("학습 범위");
    expect(runBtn(card).disabled).toBe(true);
    const res = server.handle("POST", "/studies/s-cushion/jobs", new URLSearchParams(), { job_type: "TD_DOE_GEN", params: { generator: "platform", sampling: { kind: "table", text: `${head}\n${mid}\n${bad}` }, radioss_assem_path: ASSEM } }, new Headers({ "X-PhysicsAI-Request": "1" })) as { status: number; body: { detail: { code: string; problems: { code: string }[] } } };
    expect(res.status).toBe(422);
    expect(res.body.detail.code).toBe("DOE_SAMPLING_INVALID");
    expect(res.body.detail.problems[0].code).toBe("TABLE_OUT_OF_RANGE");
  });

  it("다중 baseline 세트: 층 안 생성기(lhs_opt·halton·lhs·random)만, 그 밖은 회색 + DM-C4 사유, 층화 안내 줄 유지", async () => {
    const { card } = await openCard({ geometry: "multi" });
    fireEvent.change(await within(card).findByLabelText("형상 기준"), { target: { value: "ps-n1" } });
    await within(card).findByTestId("doe-native");
    expect(sel(card).value).toBe("lhs");
    const enabled = [...sel(card).options].filter((o) => !o.disabled).map((o) => o.value);
    expect(enabled).toEqual(["lhs_opt", "halton", "lhs", "random"]);
    const blocked = [...sel(card).options].filter((o) => o.disabled && o.value !== "train_doe");
    expect(blocked.map((o) => o.value)).toEqual(["sobol", "fullfact", "fracfact", "pb", "bbd", "ccd", "table"]);
    for (const o of blocked) expect(o.title).toBe(MULTI_BASELINE_REASON);
    expect([...sel(card).options].find((o) => o.value === "train_doe")!.title).toContain("표본표 재사용을 지원하지 않습니다");
    expect(within(card).getByTestId("native-strata").textContent).toContain("층화 LHS로 baseline마다");
    pick(card, "halton");
    expect(within(card).getByTestId("native-strata").textContent).toContain("층화로 baseline마다");
  });

  it("순수: lhs는 지금 body(count 2~상한), 그 밖은 buildSampling, 표 범위 밖·상한 초과는 null", () => {
    const o = { multi: 2, maxRuns: 500, assemPath: "A", paramSetId: null as string | null, names: ["A", "B"] };
    expect(buildNativeParams(initialNative(), o)).toEqual({ generator: "platform", sampling: { kind: "lhs", count: 20, seed: 1 }, multi_execution: 2, on_run_failure: "continue", radioss_assem_path: "A" });
    expect(buildNativeParams({ ...initialNative(), kind: "random", count: "30" }, o)).toMatchObject({ sampling: { kind: "random", count: 30, seed: 1 } });
    expect(buildNativeParams({ ...initialNative(), kind: "halton", count: "501" }, o)).toBeNull();
    expect(buildNativeParams({ ...initialNative(), kind: "pb" }, o)).toMatchObject({ sampling: { kind: "pb" } });
    expect(buildNativeParams({ ...initialNative(), kind: "table", text: "A,B\n1,1\n50,2" }, { ...o, table: { ranges: { A: [0, 10], B: [1, 2] } } })).toBeNull();
  });
});

describe("⑥ 탐색 새 DOE: explore.method(기본 lhs)", () => {
  const base = (over: Partial<SoForm> = {}): SoForm => ({
    paramSetId: "ps-1", modelId: null, explore: "new", count: "", exploreSeed: "1", batchId: "", sels: {}, weights: {}, rows: [],
    surrogate: "gp", iterations: "3", candidates: "4", tolPct: "1", seed: "1", multi: "1", capture: false, ...over,
  });
  it("lhs(생략·기본)는 method·criterion을 body에 보내지 않는다(def0517 body 불변), 그 밖은 method, lhs_opt만 criterion", () => {
    expect(buildBody(base(), []).explore).toEqual({ kind: "new", count: null, seed: 1 });
    expect(buildBody(base({ exploreMethod: "lhs" }), []).explore).toEqual({ kind: "new", count: null, seed: 1 });
    expect(buildBody(base({ exploreMethod: "halton", count: "16" }), []).explore).toEqual({ kind: "new", count: 16, seed: 1, method: "halton" });
    expect(buildBody(base({ exploreMethod: "random" }), []).explore).toEqual({ kind: "new", count: null, seed: 1, method: "random" });
    expect(buildBody(base({ exploreMethod: "lhs_opt", exploreCriterion: "corr" }), []).explore).toEqual({ kind: "new", count: null, seed: 1, method: "lhs_opt", criterion: "corr" });
    expect(buildBody(base({ exploreMethod: "halton", exploreCriterion: "corr" }), []).explore).not.toHaveProperty("criterion");
  });
  it("Sobol은 run 수가 2의 거듭제곱(≥4)이어야 한다(빈 값 = 서버 기본)", () => {
    expect(exploreIssue(base({ exploreMethod: "sobol", count: "" }))).toBeNull();
    expect(exploreIssue(base({ exploreMethod: "sobol", count: "16" }))).toBeNull();
    expect(exploreIssue(base({ exploreMethod: "sobol", count: "10" }))).toContain("2의 거듭제곱");
    expect(exploreIssue(base({ exploreMethod: "halton", count: "10" }))).toBeNull();
  });
  it("화면: 방식 드롭다운 1개(lhs 기본, 5개), lhs_opt만 기준 세그먼트, Sobol이면 안내·검사", async () => {
    renderApp(`${STUDY}/5`, { user: "power" });
    fireEvent.click(await screen.findByRole("tab", { name: /새 최적화/ }));
    const m = (await screen.findByLabelText("탐색 방식")) as HTMLSelectElement;
    expect(m.value).toBe("lhs");
    expect([...m.options].map((o) => o.value)).toEqual(SITE_KINDS.opt_explore);
    expect(screen.queryByRole("group", { name: "최적화 기준" })).toBeNull();
    fireEvent.change(m, { target: { value: "lhs_opt" } });
    expect(screen.getByRole("group", { name: "최적화 기준" })).toBeTruthy();
    fireEvent.change(m, { target: { value: "sobol" } });
    expect(screen.queryByRole("group", { name: "최적화 기준" })).toBeNull();
    expect(screen.getByText(/2의 거듭제곱/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText("탐색 run 수"), { target: { value: "10" } });
    expect(screen.getByTestId("explore-issue").textContent).toContain("2의 거듭제곱");
    fireEvent.change(screen.getByLabelText("탐색 run 수"), { target: { value: "16" } });
    expect(screen.queryByTestId("explore-issue")).toBeNull();
  });
});

describe("④ 일괄 예측: halton·random 추가, 다중 baseline은 층 안 생성기만", () => {
  it("buildSource: halton·random = lhs와 같은 입력 키(count·seed·ranges)", () => {
    const ps = { id: "ps-x", parameters: [{ name: "A", min: 0, max: 1 }, { name: "B", min: 0, max: 1 }] } as unknown as ParamSet;
    const s = initialSampling(ps);
    expect(buildSource({ ...s, kind: "halton", count: "12", seed: "3" }, ps)).toEqual({ kind: "halton", count: 12, seed: 3, ranges: null });
    expect(buildSource({ ...s, kind: "random", count: "8" }, ps)).toEqual({ kind: "random", count: 8, seed: 1, ranges: null });
  });
  it("화면: 드롭다운에 Halton·균일 랜덤(조합 수·시드 칸), 기본 lhs_opt 불변", async () => {
    localStorage.setItem("physicsai.stage4.inputMode", "batch");
    renderApp(`${STUDY}/4`, { user: "power" });
    const setup = await screen.findByRole("region", { name: "1 템플릿·조합" });
    const s = within(setup).getByLabelText("표본 방식") as HTMLSelectElement;
    expect(s.value).toBe("lhs_opt");
    expect([...s.options].map((o) => o.value)).toEqual(FULL);
    fireEvent.change(s, { target: { value: "halton" } });
    expect((within(setup).getByLabelText("조합 수") as HTMLInputElement).value).toBe("40");
    expect(within(setup).queryByRole("group", { name: "최적화 기준" })).toBeNull();
    localStorage.clear();
  });
});
