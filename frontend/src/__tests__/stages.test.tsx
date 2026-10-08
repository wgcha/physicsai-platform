import { describe, expect, it } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { renderApp, STUDY } from "../test/render";

describe("③ 화면 (V-FE-5)", () => {
  it("모델 표 열과 로그 형식 미확인 표시", async () => {
    renderApp(`${STUDY}/3`, { user: "power" });
    const table = await screen.findByRole("table", { name: "모델 표" });
    const heads = within(table).getAllByRole("columnheader").map((h) => h.textContent);
    expect(heads).toEqual(["모델", "데이터셋", "epoch", "최종 loss", "최소 loss (epoch)", "loss 곡선", "평가 점수", "로그", "Final"]);
    const gnn = within(table).getAllByRole("row").find((r) => r.textContent?.includes("cushion_GNN"))!;
    expect(within(gnn).getByText("로그 형식 미확인")).toBeTruthy();
    expect(within(gnn).getByText("평가 전")).toBeTruthy();
  });

  it("③-4 등록 결과: 로그 파싱 실패면 로그 형식 미확인", async () => {
    const { server } = renderApp(`${STUDY}/3`, { user: "power" });
    const card = await screen.findByRole("region", { name: "모델 등록" });
    fireEvent.change(within(card).getByLabelText(/모델 폴더 경로/), { target: { value: "E:/shared/AI_WORK/cushion_v1/00_inbox/model_raw" } });
    fireEvent.click(within(card).getByRole("button", { name: "확인" }));
    await within(card).findByText("model_raw.psmdl");
    const btn = within(card).getByRole("button", { name: "모델 등록" }) as HTMLButtonElement;
    await waitFor(() => expect(btn.disabled).toBe(false));
    fireEvent.click(btn);
    await waitFor(() => expect(server.jobs.some((j) => j.job_type === "MODEL_REGISTER" && j.state === "QUEUED")).toBe(true));
    server.finishAll();
    await waitFor(() => expect(within(card).getByTestId("register-result").textContent).toContain("model_raw"), { timeout: 3000 });
    const result = within(card).getByTestId("register-result");
    expect(within(result).getByText("로그 형식 미확인")).toBeTruthy();
  });

  it("loss 곡선 선형/로그 토글", async () => {
    renderApp(`${STUDY}/3`, { user: "power" });
    const seg = await screen.findByRole("group", { name: "축" });
    fireEvent.click(within(seg).getByRole("button", { name: "선형" }));
    expect(within(seg).getByRole("button", { name: "선형" }).className).toBe("on");
    expect(screen.getByRole("img", { name: "loss 곡선" })).toBeTruthy();
  });
});

describe("④ 화면 (V-FE-6)", () => {
  it("범위 밖이면 배지 없이 작은 참고 문구만", async () => {
    renderApp(`${STUDY}/4`, { user: "power" });
    const input = await screen.findByLabelText("THK_TOP 값");
    await waitFor(() => expect(screen.getByTestId("range-note").textContent).toMatch(/^최근접 run_\d{4} \(거리/));
    fireEvent.change(input, { target: { value: "5" } });
    await waitFor(() => expect(screen.getByTestId("range-note").textContent).toMatch(/^학습 범위 밖 · 최근접 run_\d{4}/));
    const note = screen.getByTestId("range-note");
    expect(note.className).toContain("small");
    expect(screen.queryByRole("alert")).toBeNull();
    expect(document.querySelector(".badge, .warn-badge")).toBeNull();
  });

  it("정수 파라미터는 반올림 반영 안내", async () => {
    renderApp(`${STUDY}/4`, { user: "power" });
    const input = await screen.findByLabelText("RIB_N 값");
    fireEvent.change(input, { target: { value: "4.6" } });
    expect((await screen.findByTestId("rounding-note")).textContent).toContain("RIB_N 4.6 → 5");
  });

  it("값 채우기: 학습 run 불러오기·공칭", async () => {
    renderApp(`${STUDY}/4`, { user: "power" });
    const sel = (await screen.findByLabelText("학습 run 불러오기")) as HTMLSelectElement;
    await waitFor(() => expect(sel.disabled).toBe(false));
    fireEvent.change(sel, { target: { value: "run_0001" } });
    await waitFor(() => expect(screen.getByTestId("range-note").textContent).toContain("최근접 run_0001 (거리 0.00)"));
    fireEvent.click(screen.getByRole("button", { name: "공칭" }));
    expect((screen.getByLabelText("THK_TOP 값") as HTMLInputElement).value).toBe("0.6");
  });

  it("PBS 미구성이면 PBS 버튼 비활성 + 안내", async () => {
    renderApp(`${STUDY}/4`, { user: "power" });
    const pbs = (await screen.findByRole("button", { name: "PBS 검증 해석" })) as HTMLButtonElement;
    await waitFor(() => expect(pbs.title).toBe("PBS 연결 안 됨 — 2차에서 제공(관리자 설정 필요)"));
    expect(pbs.disabled).toBe(true);
    expect(screen.getByTestId("pbs-note").textContent).toContain("PBS 연결 안 됨");
  });

  it("PBS 구성되고 예측 결과가 있으면 활성", async () => {
    renderApp(`${STUDY}/4`, { user: "power", hpcConfigured: true });
    const pbs = (await screen.findByRole("button", { name: "PBS 검증 해석" })) as HTMLButtonElement;
    await waitFor(() => expect(pbs.disabled).toBe(false));
  });

  it("결과: 컨투어·커브·응답값 표, 실행 4단계", async () => {
    renderApp(`${STUDY}/4`, { user: "power" });
    const resp = await screen.findByRole("table", { name: "응답값" });
    expect(within(resp).getByText("MaxStress")).toBeTruthy();
    expect(within(resp).getByText("MPa")).toBeTruthy();
    const chain = screen.getByRole("list", { name: "예측 실행 단계" });
    expect(within(chain).getAllByRole("listitem").map((li) => li.querySelector(".chain-label")!.textContent)).toEqual(["형상", "메싱", "입력파일", "예측"]);
    expect(within(chain).getByText("생략")).toBeTruthy();
    expect(await screen.findByAltText("예측 컨투어")).toBeTruthy();
  });
});
