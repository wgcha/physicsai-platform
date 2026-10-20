// opt-native V-ON-3(화면)·V-ON-13: ⑥ 모드 탭 레거시 숨김·localStorage 보정·레거시 라벨, ①-3 HyperStudy 생성 옵션 숨김/라벨,
// 새 최적화 알고리즘 드롭다운(비활성 규칙·자동 되돌림)·검증 방식(입력 숨김·안내)·고급 옵션(접힘·자리표시자·기본값으로·범위 문구)·요청 본문,
// 결과 상태 칸·품질 표 "탐색기" 열·미검증 배지·후보 표 예측 검증·algo_history 파일 안내, 목 라우트(problems·미리보기 키).
import { afterEach, describe, expect, it } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { renderApp, STUDY } from "../test/render";
import type { MockServer } from "../mock/server";
import type { SoRec } from "../mock/surrogateOpt";
import {
  ALGO_REVERT_NOTE, EMPTY_ALGO, NONE_NOTE, SO_MODE_KEY, UNVERIFIED_BADGE, algoIssues, algoStatusText, algoTip, buildBody,
  defaultPopSize, fmtVar, previewText, searcherText, varRows, type SoForm,
} from "../stages/stage5/surrogate/soRules";

const radio = (group: string, name: string) => within(screen.getByRole("radiogroup", { name: group })).getByRole("radio", { name }) as HTMLButtonElement;

function bodyOf(server: MockServer, path: string) {
  const out: Record<string, unknown>[] = [];
  const orig = server.handle.bind(server);
  server.handle = (m, p, q, b, h) => {
    if (m === "POST" && p === path) out.push(b as Record<string, unknown>);
    return orig(m, p, q, b, h);
  };
  return out;
}

describe("V-ON-3 레거시(HyperStudy) 숨김", () => {
  afterEach(() => localStorage.clear());

  it("features.optimize 꺼짐 → 원본 탭 숨김, 저장 값 original → builtin 보정", async () => {
    localStorage.setItem(SO_MODE_KEY, "original");
    renderApp(`${STUDY}/5`, { user: "power", disabledFeatures: ["train_resp", "optimize"] });
    expect((await screen.findByRole("radio", { name: "플랫폼 내장" })).getAttribute("aria-checked")).toBe("true");
    expect(within(screen.getByRole("radiogroup", { name: "최적화 방식" })).queryByRole("radio", { name: /원본 최적화/ })).toBeNull();
    expect(await screen.findByRole("tab", { name: /실행 목록/ })).toBeTruthy();
    await waitFor(() => expect(localStorage.getItem(SO_MODE_KEY)).toBe("builtin"));
  });

  it("features.optimize 켜짐 → 레거시 라벨로 원본 탭 표시·선택 기억", async () => {
    renderApp(`${STUDY}/5`, { user: "power" });
    fireEvent.click(await screen.findByRole("radio", { name: "원본 최적화(HyperStudy·레거시)" }));
    expect(localStorage.getItem(SO_MODE_KEY)).toBe("original");
  });

  it("①-3: train_doe 켜짐 → HyperStudy(레거시) 라벨, 꺼짐 → 플랫폼만", async () => {
    const a = renderApp(`${STUDY}/1`, { user: "power" });
    const g1 = await screen.findByRole("group", { name: "생성 방식" });
    expect(within(g1).getByRole("button", { name: "HyperStudy(레거시)" })).toBeTruthy();
    a.unmount();
    renderApp(`${STUDY}/1`, { user: "power", disabledFeatures: ["train_resp", "train_doe"] });
    const g2 = await screen.findByRole("group", { name: "생성 방식" });
    expect(within(g2).queryByRole("button", { name: /HyperStudy/ })).toBeNull();
    expect(within(g2).getByRole("button", { name: "플랫폼 생성(동시 실행)" })).toBeTruthy();
  });
});

describe("V-ON-13 ⑥ 알고리즘·검증 방식·고급 옵션", () => {
  afterEach(() => localStorage.clear());

  it("드롭다운 비활성 규칙·자동 되돌림 · 검증 방식 전환 · 고급 옵션 · 요청 본문", async () => {
    const { server } = renderApp(`${STUDY}/5`, { user: "power" });
    const posts = bodyOf(server, "/studies/s-cushion/surrogate-opts");
    fireEvent.click(await screen.findByRole("tab", { name: /새 최적화/ }));
    await screen.findByRole("table", { name: "성능" });
    fireEvent.change(screen.getByLabelText("MaxStress 역할"), { target: { value: "min" } });
    const sel = screen.getByTestId("algo-select") as HTMLSelectElement;
    const opt = (v: string) => [...sel.options].find((o) => o.value === v)!;
    expect(opt("nsga2").disabled).toBe(true);
    expect(opt("nsga2").title).toBe("NSGA-II는 목적 2개 이상");
    expect(opt("ga").disabled).toBe(false);
    expect(screen.queryByTestId("algo-options")).toBeNull(); // EGO는 고급 옵션 없음
    fireEvent.change(sel, { target: { value: "ga" } });
    const adv = await screen.findByTestId("algo-options");
    expect((adv as HTMLDetailsElement).open).toBe(false); // 기본 접힘
    const pop = within(adv).getByLabelText("집단 크기") as HTMLInputElement;
    expect(pop.placeholder).toBe("40"); // clamp(10·n, 40, 200) — 자유 변수 수 기준
    expect((within(adv).getByLabelText("세대 수") as HTMLInputElement).placeholder).toBe("150");
    expect((within(adv).getByLabelText("η_c(SBX)") as HTMLInputElement).placeholder).toBe("15");
    fireEvent.change(pop, { target: { value: "7" } });
    expect(within(adv).getByTestId("algo-issue").textContent).toBe("집단 크기는 8~1000의 짝수입니다");
    expect((screen.getByRole("button", { name: "최적화 시작" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(within(adv).getByRole("button", { name: "기본값으로" }));
    expect(pop.value).toBe("");
    expect(within(adv).queryByTestId("algo-issue")).toBeNull();
    fireEvent.change(within(adv).getByLabelText("세대 수"), { target: { value: "60" } });
    // 검증 방식: 대리모델만 → 반복·개선 기준 숨김 + 안내
    expect(screen.getByLabelText("반복")).toBeTruthy();
    fireEvent.click(radio("검증 방식", "대리모델만(검증 없음)"));
    expect(screen.queryByLabelText("반복")).toBeNull();
    expect(screen.queryByLabelText("개선 기준")).toBeNull();
    expect(screen.getByTestId("none-note").textContent).toBe(NONE_NOTE);
    await waitFor(() => expect(screen.getByTestId("so-preview").textContent).toContain("대리모델만"));
    await waitFor(() => expect((screen.getByRole("button", { name: "최적화 시작" }) as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByRole("button", { name: "최적화 시작" }));
    await screen.findByTestId("so-status");
    expect(posts[0]).toMatchObject({ algorithm: "ga", verification: "none",
      algo_options: { pop_size: null, generations: 60, crossover_prob: null, mutation_prob: null, eta_c: null, eta_m: null } });
  });

  it("목적이 2개가 되면 GA → EGO로 되돌리고 회색 한 줄", async () => {
    renderApp(`${STUDY}/5`, { user: "power" });
    fireEvent.click(await screen.findByRole("tab", { name: /새 최적화/ }));
    await screen.findByRole("table", { name: "성능" });
    fireEvent.change(screen.getByLabelText("MaxStress 역할"), { target: { value: "min" } });
    fireEvent.change(screen.getByTestId("algo-select"), { target: { value: "ga" } });
    fireEvent.change(screen.getByLabelText("MaxDisp 역할"), { target: { value: "min" } });
    await waitFor(() => expect((screen.getByTestId("algo-select") as HTMLSelectElement).value).toBe("ego"));
    expect(screen.getByTestId("algo-revert-note").textContent).toBe(ALGO_REVERT_NOTE);
    const sel = screen.getByTestId("algo-select") as HTMLSelectElement;
    expect([...sel.options].find((o) => o.value === "ga")!.disabled).toBe(true);
    expect([...sel.options].find((o) => o.value === "nsga2")!.disabled).toBe(false);
  });

  it("결과: 상태 칸 알고리즘·품질 표 탐색기 열·algo_history 안내 / 대리모델만: 미검증 배지·후보 예측 검증", async () => {
    const { server } = renderApp(`${STUDY}/5/surrogate/so-1`, { user: "power" }, (s) => {
      const o = s.surrogate.find((x) => x.id === "so-1") as SoRec;
      o.settings.algorithm = "ga";
      for (const it of o.iters) if (it.fit) (it.fit as Record<string, unknown>).algo = { name: "ga", pop_size: 40, generations: 150, generations_run: 97, stop: "STALL" };
    });
    expect((await screen.findByTestId("so-algo")).textContent).toBe("알고리즘: GA · 세대 150(정체 종료 97)");
    expect(screen.getByTestId("searcher-1").textContent).toBe("GA 97/150 정체 종료");
    expect(screen.getByTestId("so-algo-files").textContent).toContain("algo_history.csv");
    expect(screen.queryByTestId("unverified-badge")).toBeNull();
    void server;
  });

  it("대리모델만(단일): 미검증 후보 카드·배지 → 선택 해 예측 검증 = verify 요청", async () => {
    const { server } = renderApp(`${STUDY}/5/surrogate/so-1`, { user: "power" }, (s) => {
      const o = s.surrogate.find((x) => x.id === "so-1") as SoRec;
      o.settings.verification = "none";
      o.settings.algorithm = "ga";
      const it0 = o.iters[0];
      it0.candidates = (o.iters[1].candidates ?? []).map((c) => ({ ...c, state: "UNVERIFIED", verified: null, role: "ga_ei" }));
      o.iters = [it0];
      o.runs = o.runs.filter((r) => r.iter_no === 0);
      o.stop_reason = "SURROGATE_ONLY";
    });
    const posts = bodyOf(server, "/surrogate-opts/so-1/verify");
    const badge = await screen.findByTestId("unverified-badge");
    expect(badge.textContent).toBe(UNVERIFIED_BADGE);
    const btn = screen.getByTestId("unverified-verify") as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    fireEvent.click(screen.getByLabelText("후보 1 선택"));
    fireEvent.click(screen.getByLabelText("후보 2 선택"));
    expect(btn.textContent).toBe("선택 해 예측 검증 (2)");
    fireEvent.click(btn);
    expect(await screen.findByTestId("unverified-done")).toBeTruthy();
    expect((posts[0].points as unknown[]).length).toBe(2);
  });

  it("대리모델만(다목적): 파레토 카드 배지·예측 검증 강조", async () => {
    renderApp(`${STUDY}/5/surrogate/so-2`, { user: "power" }, (s) => {
      const o = s.surrogate.find((x) => x.id === "so-2") as SoRec;
      o.settings.verification = "none";
      o.settings.algorithm = "nsga2";
    });
    expect((await screen.findByTestId("unverified-badge")).textContent).toBe(UNVERIFIED_BADGE);
    expect(screen.getByTestId("none-verify-hint")).toBeTruthy();
    expect(screen.getByTestId("pareto-verify").className).not.toContain("small");
  });

  it("다중 baseline 위상 세트: baseline 행(수준 체크박스)·N/A 표시·levels 본문", async () => {
    const { server } = renderApp(`${STUDY}/5`, { user: "power" }, (s) => {
      s.paramSets.forEach((p) => (p.is_current = p.id === "ps-2"));
      const ps = s.paramSets.find((p) => p.id === "ps-2")!;
      ps.baselines = [{ id: "base", rel: "." }, { id: "B2", rel: "baselines/B2" }] as never;
      const p0 = ps.parameters[0] as { name: string; baselines?: Record<string, unknown> | null };
      p0.baselines = { base: { param: p0.name }, B2: null };
    });
    const posts = bodyOf(server, "/studies/s-cushion/surrogate-opts/preview");
    fireEvent.click(await screen.findByRole("tab", { name: /새 최적화/ }));
    await screen.findByRole("table", { name: "성능" });
    fireEvent.change(screen.getByLabelText("MaxStress 역할"), { target: { value: "min" } });
    const row = await screen.findByTestId("var-baseline");
    const vars = screen.getByRole("table", { name: "변수 범위" });
    expect(within(vars).getAllByText(/N\/A: B2/).length).toBe(1);
    fireEvent.click(within(row).getByLabelText("baseline B2"));
    await waitFor(() => expect(posts.some((b) => JSON.stringify(b.levels) === JSON.stringify({ baseline: ["base"] }))).toBe(true));
    await waitFor(() => expect(screen.getByTestId("var-baseline").textContent).toContain("1개 = 고정"));
  });

  it("순수 규칙: 툴팁·기본 집단 크기·범위 문구·본문·탐색기·상태 문구·미리보기", () => {
    expect(algoTip("ga", 2)).toBe("GA는 단일 목적 전용");
    expect(algoTip("nsga2", 1)).toBe("NSGA-II는 목적 2개 이상");
    expect(algoTip("ego", 3)).toBeNull();
    expect(defaultPopSize("ga", 3)).toBe(40);
    expect(defaultPopSize("nsga2", 13)).toBe(132);
    expect(algoIssues("nsga2", { ...EMPTY_ALGO, pop_size: "102" }, 3, undefined, 100000)).toEqual(["집단 크기는 8~1000의 4의 배수입니다"]);
    expect(algoIssues("ga", { ...EMPTY_ALGO, pop_size: "1000", generations: "200" }, 3, undefined, 100000)[0]).toContain("상한 100000");
    expect(algoIssues("ga", { ...EMPTY_ALGO, eta_c: "0", crossover_prob: "2" }, 3, undefined, 100000)).toEqual(["교차 확률은 0~1입니다", "η_c는 1~100입니다"]);
    expect(algoIssues("ego", { ...EMPTY_ALGO, pop_size: "3" }, 3, undefined, 100000)).toEqual([]);
    const f = { paramSetId: "ps", modelId: null, explore: "new", count: "", exploreSeed: "1", batchId: "", sels: {}, weights: {}, rows: [],
      surrogate: "gp", iterations: "3", candidates: "4", tolPct: "1", seed: "1", multi: "1", capture: false } as SoForm;
    expect(buildBody(f, [])).not.toHaveProperty("algorithm"); // 기존 폼(키 없음)은 기존 본문 그대로
    expect(buildBody({ ...f, algorithm: "ego", verification: "loop" }, [])).toMatchObject({ algorithm: "ego", verification: "loop" });
    expect(buildBody({ ...f, algorithm: "ego" }, [])).not.toHaveProperty("algo_options");
    expect(searcherText({ name: "nsga2", generations: 200, generations_run: 200, stop: "MAX_GEN" })).toBe("NSGA-II 200/200 최대 세대");
    expect(searcherText({ name: "ego" })).toBe("EGO");
    expect(searcherText(null)).toBe("—");
    expect(algoStatusText({ iterations: [], settings: { algorithm: "ego", verification: "none" } } as never)).toBe("알고리즘: EGO · 대리모델만(검증 없음)");
    expect(previewText({ explore_count: 12, max_total_runs: 12, verification: "none" }, 3, 4)).toBe("예측 최대 12 run(탐색 12 · 대리모델만)");
    expect(previewText({ explore_count: 12, max_total_runs: 24 }, 3, 4)).toBe("예측 최대 24 run(탐색 12 + 3 × 4)");
    expect(fmtVar("baseline", 1, ["base", "B2"])).toBe("B2");
    expect(fmtVar("THK", 1.5, ["base"])).toBe("1.5");
    expect(varRows({ parameters: [{ name: "D", min: 0, max: 1, baselines: { base: null, B2: {} } }], tpl_params: [] } as never)[0].na).toEqual(["base"]);
  });
});
