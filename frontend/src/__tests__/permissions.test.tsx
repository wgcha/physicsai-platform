import { describe, expect, it } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { renderApp, STUDY } from "../test/render";

describe("권한별 버튼 (V-FE-2)", () => {
  it("general: 실행 버튼 대신 조회 전용", async () => {
    renderApp(`${STUDY}/3`, { user: "general" });
    await screen.findByRole("region", { name: "데이터셋 생성" });
    expect(screen.queryByRole("button", { name: "데이터셋 생성" })).toBeNull();
    expect(screen.queryByRole("button", { name: "모델 등록" })).toBeNull();
    expect(screen.queryByRole("button", { name: "평가" })).toBeNull();
    expect(screen.getAllByText("조회 전용").length).toBeGreaterThanOrEqual(4);
    expect(screen.queryByRole("button", { name: "Final 지정" })).toBeNull();
  });

  it("general: ④도 예측 실행·PBS 버튼 없음", async () => {
    renderApp(`${STUDY}/4`, { user: "general" });
    await screen.findByRole("region", { name: "입력 · 실행" });
    expect(screen.queryByRole("button", { name: "예측 실행" })).toBeNull();
    expect(screen.queryByRole("button", { name: "PBS 검증 해석" })).toBeNull();
  });

  it("power: 실행 버튼이 있고 경로 확인 후 활성", async () => {
    const { server } = renderApp(`${STUDY}/3`, { user: "power" });
    const card = await screen.findByRole("region", { name: "데이터셋 생성" });
    // 2차: 기본 입력은 ② 큐레이션 결과 — "다른 폴더 지정"으로 전환하면 경로 확인이 필요하다
    fireEvent.click(await within(card).findByRole("button", { name: "다른 폴더 지정" }));
    const btn = within(card).getByRole("button", { name: "데이터셋 생성" }) as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    fireEvent.change(within(card).getByLabelText(/h3d 폴더 경로/), { target: { value: "E:/shared/AI_WORK/cushion_v1/00_inbox/h3d_r3" } });
    fireEvent.click(within(card).getByRole("button", { name: "확인" }));
    expect(await within(card).findByText(/학습/, { selector: ".summary-line" })).toBeTruthy();
    await waitFor(() => expect(btn.disabled).toBe(false));
    fireEvent.click(btn);
    await within(card).findByText(/대기 \d+번째/);
    expect(server.jobs.some((j) => j.job_type === "DATASET_CREATE" && j.state === "QUEUED")).toBe(true);
  });

  it("power: Final 재지정", async () => {
    const { server } = renderApp(`${STUDY}/3`, { user: "power" });
    const table = await screen.findByRole("table", { name: "모델 표" });
    const row = within(table).getAllByRole("row").find((r) => r.textContent?.includes("v2"))!;
    fireEvent.click(within(row).getByRole("button", { name: "Final 지정" }));
    await waitFor(() => expect(server.studies[0].final_model_id).toBe("m-2"));
    await waitFor(() => expect(within(row).getByText("Final")).toBeTruthy());
  });
});
