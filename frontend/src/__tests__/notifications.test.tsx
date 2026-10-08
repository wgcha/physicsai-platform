import { describe, expect, it } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { renderApp, STUDY } from "../test/render";

describe("알림 (V-FE-4)", () => {
  it("로드 이전 알림은 토스트 없이 벨 미읽음만, 새 알림은 토스트 + 배지 증가", async () => {
    const { server } = renderApp(`${STUDY}/3`, { user: "power" });
    const bell = await screen.findByRole("button", { name: /알림 \d+건 미읽음/ });
    await waitFor(() => expect(within(bell).getByTestId("bell-badge").textContent).toBe("1"));
    await new Promise((r) => setTimeout(r, 150));
    expect(screen.queryAllByRole("status")).toHaveLength(0);

    const job = server.jobs.find((j) => j.id === "j-q1")!;
    server.notify("u-power", "JOB_SUCCEEDED", job, "완료: 평가 (쿠션 두께·리브 예측)");
    expect(await screen.findByRole("status")).toBeTruthy();
    expect(screen.getByRole("status").textContent).toContain("완료: 평가");
    await waitFor(() => expect(within(bell).getByTestId("bell-badge").textContent).toBe("2"));
  });

  it("이력 패널에서 모두 읽음", async () => {
    renderApp(`${STUDY}/3`, { user: "power" });
    const bell = await screen.findByRole("button", { name: /알림 \d+건 미읽음/ });
    await waitFor(() => expect(within(bell).queryByTestId("bell-badge")).not.toBeNull());
    fireEvent.click(bell);
    const drawer = await screen.findByRole("dialog", { name: "알림 이력" });
    await within(drawer).findByText("완료: 예측 (쿠션 두께·리브 예측)");
    fireEvent.click(within(drawer).getByRole("button", { name: "모두 읽음" }));
    await waitFor(() => expect(within(bell).queryByTestId("bell-badge")).toBeNull());
  });
});
