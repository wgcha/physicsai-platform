import { describe, expect, it } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { renderApp, STUDY } from "../test/render";

describe("대기열 관리 (V-FE-2)", () => {
  it("전역 관리자만 순서 이동·취소 버튼", async () => {
    renderApp(`${STUDY}/3`, { user: "power" });
    const q = await screen.findByRole("region", { name: "실행 대기열" });
    await waitFor(() => expect(within(q).getAllByTestId("queue-row").length).toBeGreaterThan(0));
    expect(within(q).queryByRole("button", { name: "위로" })).toBeNull();
    expect(within(q).queryByRole("button", { name: "취소" })).toBeNull();
    expect(within(q).getByText("내 작업")).toBeTruthy();
  });

  it("관리자: 순서 이동과 취소", async () => {
    const { server } = renderApp(`${STUDY}/3`, { user: "admin" });
    const q = await screen.findByRole("region", { name: "실행 대기열" });
    await waitFor(() => expect(within(q).getAllByRole("button", { name: "위로" }).length).toBe(2));
    fireEvent.click(within(q).getAllByRole("button", { name: "위로" })[1]);
    await waitFor(() => expect(server.jobs.find((j) => j.id === "j-q2")!.queue_position).toBe(1));
    const rows = within(q).getAllByTestId("queue-row");
    fireEvent.click(within(rows[rows.length - 1]).getByRole("button", { name: "취소" }));
    fireEvent.click(await within(q).findByRole("button", { name: "취소 확인" }));
    await waitFor(() => expect(server.jobs.filter((j) => j.state === "CANCELED").length).toBe(1));
  });
});
