import { describe, expect, it } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { renderApp, STUDY } from "../test/render";

describe("③ 화면 (V-FE-5)", () => {
  it("패키지 폴더는 package_display_path로 표시", async () => {
    renderApp(`${STUDY}/3`, { user: "power" });
    expect(await screen.findByText("E:\\shared\\AI_WORK\\cushion_v1\\03_package\\ds-2")).toBeTruthy();
  });

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
