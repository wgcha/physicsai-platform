// phase2.md §20 V2-FE-5 (컴포넌트 시험, 목 서버)
import { describe, expect, it } from "vitest";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { renderApp, STUDY } from "../test/render";
import { clearApiCache } from "../api";
import { setEnvPollMs } from "../pages/AdminEnvCheck";
import { recordCalls } from "../test/recordCalls";

describe("V2-FE-5 환경 점검(전역 관리자)", () => {
  it("관리 메뉴·빨간 점 → 화면, 실행·폴링·이력", async () => {
    setEnvPollMs(40);
    const { server } = renderApp(`${STUDY}/3`, { user: "admin" });
    const btn = await screen.findByRole("button", { name: /^관리/ });
    await waitFor(() => expect(within(btn).getByTestId("admin-alert-dot")).toBeTruthy());
    fireEvent.click(btn);
    fireEvent.click(screen.getByRole("menuitem", { name: /환경 점검/ }));
    const sum = await screen.findByTestId("env-summary");
    expect(sum.textContent).toContain("실패 2 · 경고 2");
    const table = screen.getByRole("table", { name: "점검 결과" });
    expect(within(table).getByText("hvtrans")).toBeTruthy();
    const hist = screen.getByRole("table", { name: "점검 이력" });
    expect(within(hist).getAllByRole("row")).toHaveLength(4);
    // 다른 이력 보기
    fireEvent.click(within(hist).getAllByRole("row")[2]);
    await waitFor(() => expect(screen.getByTestId("env-summary").textContent).toContain("실패 0 · 경고 2"));
    // 실행
    fireEvent.click(screen.getByRole("button", { name: "점검 실행" }));
    const busy = await screen.findByRole("button", { name: "점검 중…" });
    expect((busy as HTMLButtonElement).disabled).toBe(true);
    await waitFor(() => expect(within(screen.getByRole("table", { name: "점검 결과" })).getAllByText("대기").length).toBeGreaterThan(0));
    act(() => {
      server.tick();
      server.tick();
    });
    await waitFor(() => expect(screen.getByRole("button", { name: "점검 실행" })).toBeTruthy(), { timeout: 3000 });
    await waitFor(() => expect(within(screen.getByRole("table", { name: "점검 이력" })).getAllByRole("row")).toHaveLength(5));
    expect(server.notifs.some((n) => n.event === "ENV_CHECK_DONE" && n.user_id === "u-admin")).toBe(true);
  });

  it("config.warnings: 관리자에게만 빨간 점 + 환경 점검 화면 상단 경고 목록", async () => {
    const warn = ["resources.extract_minmax_tcl 미설정(⑤ 비활성)"];
    const a = renderApp(`${STUDY}/3`, { user: "admin", configWarnings: warn });
    a.server.p2.envChecks.forEach((e) => (e.summary.fail = 0)); // 점검 실패 없이 경고만으로 점이 떠야 한다
    const btn = await screen.findByRole("button", { name: /^관리/ });
    await waitFor(() => expect(within(btn).getByTestId("admin-alert-dot").getAttribute("title")).toBe("설정 경고 1건"));
    fireEvent.click(btn);
    fireEvent.click(screen.getByRole("menuitem", { name: /환경 점검/ }));
    const box = await screen.findByRole("region", { name: "설정 경고" });
    expect(within(box).getByText(warn[0])).toBeTruthy();
    a.unmount();
    clearApiCache();
    renderApp(`${STUDY}/3`, { user: "power", configWarnings: warn });
    await screen.findByRole("navigation", { name: "경로" });
    expect(screen.queryByTestId("admin-alert-dot")).toBeNull();
  });

  it("비관리자: 메뉴 없음, URL로 들어오면 '관리자 전용입니다'", async () => {
    const { server } = renderApp(`${STUDY}/3`, { user: "power" });
    await screen.findByRole("navigation", { name: "경로" });
    expect(screen.queryByRole("button", { name: /^관리/ })).toBeNull();
    const calls = recordCalls(server);
    renderApp("/admin/env-check", { user: "power" });
    expect(await screen.findByText("관리자 전용입니다")).toBeTruthy();
    expect(calls.filter((c) => c.includes("env-checks"))).toEqual([]);
  });
});
