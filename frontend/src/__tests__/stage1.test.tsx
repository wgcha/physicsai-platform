// phase2.md §20 V2-FE-2 (컴포넌트 시험, 목 서버)
import { describe, expect, it } from "vitest";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { openStatusDrawer, renderApp, STUDY } from "../test/render";
import { PBS_NONE_TEXT } from "../stages/stage1/SolveCard";
import { recordCalls } from "../test/recordCalls";
import { DOE_TYPES } from "../mock/catalog";
import { DESCRIPTIONS, HS_NOTE } from "../lib/sampling";

/** S18: ①-3 화면 기본은 플랫폼 생성 — 기존 HyperStudy 시험은 호환 모드로 먼저 전환한다 */
const openHyperstudy = (card: HTMLElement) => fireEvent.click(within(card).getByRole("button", { name: "HyperStudy(레거시)" }));

describe("V2-FE-2 ① 학습데이터 생성", () => {
  it("카드 6개, 권한 없으면 조회 전용", async () => {
    renderApp(`${STUDY}/1`, { user: "general" });
    for (const name of ["CAD 파라미터 추출", "파라미터 표", "DOE · Radioss 입력", "PBS 해석 제출", "결과 회수", "run 응답 추출 (선택)"])
      expect(await screen.findByRole("region", { name })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "파라미터 추출" })).toBeNull();
    expect(screen.queryByRole("button", { name: "tpl 생성" })).toBeNull();
    expect(screen.getAllByText("조회 전용").length).toBeGreaterThanOrEqual(5);
  });

  it("파라미터 표: 사용 체크·범위 편집 → stale 문구, tpl 생성은 PUT 후 POST", async () => {
    const { server } = renderApp(`${STUDY}/1`, { user: "power" });
    const card = await screen.findByRole("region", { name: "파라미터 표" });
    await within(card).findByRole("table", { name: "파라미터 표" });
    expect((within(card).getByLabelText("bad name 사용") as HTMLInputElement).disabled).toBe(true);
    expect(within(card).getByTestId("tpl-state").textContent).toContain("tpl 생성됨 · 전체 5개 포함(사용 4개 = DOE 범위, 미사용 1개 공칭 고정)");
    fireEvent.click(within(card).getByLabelText("FILLET_R 사용"));
    expect(within(card).getByTestId("tpl-state").textContent).toContain("표가 바뀌었습니다 — tpl을 다시 생성하세요");
    // 고급: 형식·단위 열
    expect(within(card).queryByLabelText("THK_TOP 형식")).toBeNull();
    fireEvent.click(within(card).getByRole("button", { name: /고급/ }));
    expect(within(card).getByLabelText("THK_TOP 형식")).toBeTruthy();
    const calls = recordCalls(server);
    fireEvent.click(within(card).getByRole("button", { name: "tpl 생성" }));
    await waitFor(() => expect(within(card).getByTestId("tpl-state").textContent).toContain("사용 5개"));
    const order = calls.filter((c) => c.includes("/train/"));
    expect(order).toEqual(["PUT /studies/s-cushion/train/params", "POST /studies/s-cushion/train/tpl"]);
  });

  it("tpl 생성: PUT 실패(VERSION_CONFLICT)면 POST를 보내지 않는다", async () => {
    const { server } = renderApp(`${STUDY}/1`, { user: "power" });
    const card = await screen.findByRole("region", { name: "파라미터 표" });
    await within(card).findByRole("table", { name: "파라미터 표" });
    server.p2.setups["s-cushion"].version += 1;
    const calls = recordCalls(server);
    fireEvent.click(within(card).getByRole("button", { name: "tpl 생성" }));
    expect(await within(card).findByRole("alert")).toBeTruthy();
    expect(calls.filter((c) => c.includes("/train/"))).toEqual(["PUT /studies/s-cushion/train/params"]);
  });

  it("DOE 유형별 동적 옵션(int·bool·combo)과 runs_editable — 기본 선택은 추천 유형(S15)", async () => {
    renderApp(`${STUDY}/1`, { user: "power" });
    const card = await screen.findByRole("region", { name: "DOE · Radioss 입력" });
    openHyperstudy(card);
    await within(card).findByLabelText("Random Seed");
    const sel = within(card).getByLabelText("DOE 유형") as HTMLSelectElement;
    expect(sel.value).toBe("LatinHyperCube"); // 목록 첫 항목(FullFact)이 아니라 recommended
    expect([...sel.options].map((o) => o.value)).toEqual(["FullFact", "FracFact", "LatinHyperCube", "Sobol"]);
    expect((within(card).getByLabelText("run 수") as HTMLInputElement).disabled).toBe(false);
    fireEvent.change(sel, { target: { value: "Sobol" } });
    expect(within(card).getByText("Scramble")).toBeTruthy(); // bool
    expect(within(card).getByLabelText("Sequence Offset")).toBeTruthy(); // int
    fireEvent.change(sel, { target: { value: "FracFact" } });
    expect((within(card).getByLabelText("run 수") as HTMLInputElement).disabled).toBe(true);
    expect(within(card).getByText("자동 계산(HyperStudy 결정)")).toBeTruthy();
    expect((within(card).getByLabelText("Resolution") as HTMLSelectElement).value).toBe("3"); // combo
    expect(within(card).queryByLabelText("Random Seed")).toBeNull();
  });

  it("DOE 동시 실행 수(multiexec)는 고급 없이 기본 표시 · 상한은 /status 설정값", async () => {
    renderApp(`${STUDY}/1`, { user: "power" });
    const card = await screen.findByRole("region", { name: "DOE · Radioss 입력" });
    openHyperstudy(card);
    await within(card).findByLabelText("Random Seed");
    expect(within(card).queryByRole("button", { name: /고급/ })).toBeNull();
    const input = within(card).getByLabelText("동시 실행 수") as HTMLInputElement;
    expect(input.value).toBe("1");
    await waitFor(() => expect(within(card).getByText("1~8 · 높일수록 빠르지만 CPU·라이선스를 더 씀")).toBeTruthy());
    fireEvent.change(input, { target: { value: "4" } });
    expect(input.value).toBe("4");
    fireEvent.change(input, { target: { value: "99" } });
    expect(input.value).toBe("8");
  });

  it("PBS none: ①-4 버튼 비활성 + 안내 + DOE 폴더 경로, ①-5 수동 결과 폴더", async () => {
    renderApp(`${STUDY}/1`, { user: "power" });
    const card = await screen.findByRole("region", { name: "PBS 해석 제출" });
    const none = await within(card).findByTestId("pbs-none");
    expect(none.textContent).toContain(PBS_NONE_TEXT);
    expect((within(none).getByRole("button", { name: "PBS 제출" }) as HTMLButtonElement).disabled).toBe(true);
    expect(await within(none).findByText(/01_train\\doe\\doe-1$/)).toBeTruthy();
    const col = screen.getByRole("region", { name: "결과 회수" });
    expect(within(col).getByText("PBS 연결 안 됨 — 해석한 결과 폴더를 직접 지정하세요")).toBeTruthy();
    expect(await within(col).findByTestId("tile-collected")).toBeTruthy();
    await waitFor(() => expect(within(col).getByTestId("tile-collected").textContent).toBe("24/30"));
  });

  it("PBS 구성: run 상태 막대·제출 표, 관리자만 취소/재제출", async () => {
    const { server } = renderApp(`${STUDY}/1`, { user: "admin", hpcConfigured: true });
    const card = await screen.findByRole("region", { name: "PBS 해석 제출" });
    const table = await within(card).findByRole("table", { name: "PBS 제출 표" });
    await waitFor(() => expect(within(card).getByTestId("runbar-col").textContent).toContain("24"));
    expect(within(card).getByTestId("runbar-fail").textContent).toContain("1");
    const failedRow = within(table).getAllByRole("row").find((r) => r.textContent?.includes("run__00027"))!;
    expect(within(failedRow).getByText("해석 실패")).toBeTruthy();
    expect(within(failedRow).getByRole("button", { name: "재제출" })).toBeTruthy();
    const subRow = within(table).getAllByRole("row").find((r) => r.textContent?.includes("run__00028"))!;
    fireEvent.click(await within(subRow).findByRole("button", { name: "취소" }));
    fireEvent.click(within(subRow).getByRole("button", { name: "작업 전체 취소" }));
    await waitFor(() => expect(server.jobs.find((j) => j.id === "j-solve")!.cancel_requested).toBe(true));
  });

  it("C18: PBS 취소 실패 → '취소 실패, 재시도 중'(① 표·작업 상태·대기열) + 알림", async () => {
    const { server } = renderApp(`${STUDY}/1`, { user: "admin", hpcConfigured: true, hpcCancelFails: true });
    const card = await screen.findByRole("region", { name: "PBS 해석 제출" });
    const table = await within(card).findByRole("table", { name: "PBS 제출 표" });
    const subRow = within(table).getAllByRole("row").find((r) => r.textContent?.includes("run__00028"))!;
    fireEvent.click(await within(subRow).findByRole("button", { name: "취소" }));
    fireEvent.click(within(subRow).getByRole("button", { name: "작업 전체 취소" }));
    await waitFor(() => expect(server.jobs.find((j) => j.id === "j-solve")!.cancel_requested).toBe(true));
    act(() => server.tick());
    const j = server.jobs.find((x) => x.id === "j-solve")!;
    expect(j.state).toBe("WAITING_HPC");
    expect(j.attention_code).toBe("HPC_CANCEL_FAILED");
    expect(server.notifs.filter((n) => n.event === "HPC_CANCEL_FAILED")).toHaveLength(1);
    act(() => server.tick());
    expect(server.notifs.filter((n) => n.event === "HPC_CANCEL_FAILED")).toHaveLength(1); // 1회만
    await openStatusDrawer();
    const q = screen.getByRole("region", { name: "실행 대기열" });
    await waitFor(() => expect(within(q).getByTestId("queue-attention").textContent).toContain("취소 실패, 재시도 중"), { timeout: 3000 });
    expect((await within(card).findByTestId("attention", {}, { timeout: 3000 })).textContent).toBe("취소 실패, 재시도 중");
    await waitFor(() => expect(within(card).getAllByTestId("run-cancel-failed")[0].textContent).toContain("취소 실패, 재시도 중"), { timeout: 3000 });
  });

  it("PBS 구성: power에게는 행 조치 버튼 없음", async () => {
    renderApp(`${STUDY}/1`, { user: "power", hpcConfigured: true });
    const table = await screen.findByRole("table", { name: "PBS 제출 표" });
    await waitFor(() => expect(within(table).getAllByRole("row").length).toBe(31));
    expect(within(table).queryByRole("button", { name: "재제출" })).toBeNull();
    expect(within(table).queryByRole("button", { name: "취소" })).toBeNull();
  });
});

describe("V3-S15-13 ① DOE 생성: 추천 기본값·설명 상자", () => {
  const lines = (card: HTMLElement) => [1, 2, 3, 4].map((n) => within(card).getByTestId(`samp-line-${n}`).firstChild!.textContent);

  it("기본 선택 = 서버가 추천한 유형(목록 첫 항목이 아님), 이름 옆 추천 표시, 설명문 4줄·계산값·회색 한 줄", async () => {
    renderApp(`${STUDY}/1`, { user: "power" });
    const card = await screen.findByRole("region", { name: "DOE · Radioss 입력" });
    openHyperstudy(card);
    await within(card).findByLabelText("Random Seed");
    const sel = within(card).getByLabelText("DOE 유형") as HTMLSelectElement;
    expect(sel.value).toBe("LatinHyperCube");
    expect([...sel.options].map((o) => o.textContent)).toEqual(["FullFact", "FracFact", "LatinHyperCube · 추천", "Sobol"]);
    expect(within(card).getByTestId("samp-desc").getAttribute("data-desc-id")).toBe("hs_lhs");
    expect(lines(card)).toEqual(DESCRIPTIONS.hs_lhs.lines);
    expect(within(card).getByTestId("samp-badge").textContent).toBe("추천");
    expect(within(card).getByTestId("samp-calc").textContent!.trim()).toMatch(/^현재 변수 \d+개 → 권장 \d+$/);
    expect(within(card).getByTestId("hs-note").textContent).toBe(HS_NOTE);
    // 고를 때마다 바뀐다(추천 배지는 추천 유형만, 계산값은 hs_lhs·hs_sobol만)
    fireEvent.change(sel, { target: { value: "Sobol" } });
    expect(within(card).getByTestId("samp-desc").getAttribute("data-desc-id")).toBe("hs_sobol");
    expect(lines(card)).toEqual(DESCRIPTIONS.hs_sobol.lines);
    expect(within(card).queryByTestId("samp-badge")).toBeNull();
    fireEvent.change(sel, { target: { value: "FullFact" } });
    expect(lines(card)).toEqual(DESCRIPTIONS.hs_fullfact.lines);
    expect(within(card).queryByTestId("samp-calc")).toBeNull();
    fireEvent.change(sel, { target: { value: "FracFact" } });
    expect(lines(card)).toEqual(DESCRIPTIONS.hs_fracfact.lines);
    expect(within(card).getByTestId("hs-note").textContent).toBe(HS_NOTE); // 고정
  });

  it("추천 유형이 없으면 첫 항목이 기본, desc_id가 null이면 일반 문구", async () => {
    const saved = DOE_TYPES.map((t) => [t.recommended, t.desc_id] as const);
    DOE_TYPES.forEach((t) => ((t.recommended = false), (t.desc_id = null)));
    try {
      renderApp(`${STUDY}/1`, { user: "power" });
      const card = await screen.findByRole("region", { name: "DOE · Radioss 입력" });
      openHyperstudy(card);
      await waitFor(() => expect((within(card).getByLabelText("DOE 유형") as HTMLSelectElement).value).toBe("FullFact"));
      expect(within(card).getByTestId("samp-desc").getAttribute("data-desc-id")).toBe("generic");
      expect(lines(card)).toEqual(DESCRIPTIONS.generic.lines);
      expect(within(card).queryByTestId("samp-badge")).toBeNull();
    } finally {
      DOE_TYPES.forEach((t, i) => ((t.recommended = saved[i][0]), (t.desc_id = saved[i][1])));
    }
  });
});
