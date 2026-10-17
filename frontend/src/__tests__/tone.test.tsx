// 2026-10-17 대시보드 톤·테마 동기화·레이아웃 A(phase3.md D3-55)
import { afterEach, describe, expect, it } from "vitest";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { openStatusDrawer, renderApp, STUDY } from "../test/render";
import { LEGACY_THEME_KEY, THEME_KEY, readTheme } from "../design/theme";

afterEach(() => {
  localStorage.removeItem(THEME_KEY);
  localStorage.removeItem(LEGACY_THEME_KEY);
  delete document.documentElement.dataset.theme;
});

describe("테마 동기화(대시보드 localStorage)", () => {
  it("새 키 'simdashboard.workspace.theme.v1'이 있으면 그 값(레거시보다 우선)", async () => {
    localStorage.setItem(THEME_KEY, "light");
    localStorage.setItem(LEGACY_THEME_KEY, "dark");
    renderApp(`${STUDY}/3`, { user: "power" });
    await screen.findByRole("navigation", { name: "경로" });
    expect(document.documentElement.dataset.theme).toBe("light");
  });

  it("새 키가 없으면 레거시 'vd-workbench-theme', 둘 다 없거나 값이 이상하거나 저장소가 실패하면 dark", () => {
    localStorage.setItem(LEGACY_THEME_KEY, "light");
    expect(readTheme()).toBe("light");
    localStorage.removeItem(LEGACY_THEME_KEY);
    expect(readTheme()).toBe("dark");
    localStorage.setItem(THEME_KEY, "sepia");
    expect(readTheme()).toBe("dark");
    const broken = {
      getItem: () => {
        throw new Error("SecurityError");
      },
    };
    expect(readTheme(broken)).toBe("dark");
    expect(readTheme(undefined)).toBe("dark");
  });

  it("대시보드(다른 탭)에서 바꾸면 storage 이벤트로 따라간다", async () => {
    renderApp(`${STUDY}/3`, { user: "power" });
    await screen.findByRole("navigation", { name: "경로" });
    expect(document.documentElement.dataset.theme).toBe("dark");
    localStorage.setItem(THEME_KEY, "light");
    act(() => {
      window.dispatchEvent(new StorageEvent("storage", { key: THEME_KEY, newValue: "light" }));
    });
    expect(document.documentElement.dataset.theme).toBe("light");
    localStorage.setItem(THEME_KEY, "dark");
    act(() => {
      window.dispatchEvent(new StorageEvent("storage", { key: THEME_KEY, newValue: "dark" }));
    });
    expect(document.documentElement.dataset.theme).toBe("dark");
  });
});

describe("레이아웃 A: 상태 칩 → 서랍", () => {
  it("칩 문구(대기열 실행·대기, CPU·RAM·GPU), 클릭하면 서랍(aria-modal), Esc로 닫고 칩으로 포커스 복귀", async () => {
    renderApp(`${STUDY}/3`, { user: "power" });
    const chip = await screen.findByTestId("chip-queue");
    await waitFor(() => expect(chip.textContent).toMatch(/^대기열 실행 \d+ · 대기 \d+$/));
    await waitFor(() => expect(screen.getByTestId("chip-resources").textContent).toMatch(/^CPU \d+% · RAM \d+\/\d+ · GPU (\d+%|—)$/));
    expect(chip.getAttribute("aria-expanded")).toBe("false");
    chip.focus();
    const drawer = await openStatusDrawer();
    expect(drawer.getAttribute("aria-modal")).toBe("true");
    expect(chip.getAttribute("aria-expanded")).toBe("true");
    expect(within(drawer).getByRole("region", { name: "실행 대기열" })).toBeTruthy();
    expect(within(drawer).getByRole("region", { name: "워커 자원" })).toBeTruthy();
    expect(drawer.contains(document.activeElement)).toBe(true);
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "실행 상태" })).toBeNull());
    expect(document.activeElement).toBe(chip);
    expect(chip.getAttribute("aria-expanded")).toBe("false");
  });

  it("바깥(가림막)을 누르면 닫히고, Tab은 서랍 안에서 돈다(포커스 트랩)", async () => {
    renderApp(`${STUDY}/3`, { user: "admin" });
    const res = await screen.findByTestId("chip-resources");
    fireEvent.click(res);
    const drawer = await screen.findByRole("dialog", { name: "실행 상태" });
    const close = within(drawer).getByRole("button", { name: "닫기" });
    expect(document.activeElement).toBe(close);
    fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
    expect(drawer.contains(document.activeElement)).toBe(true);
    expect(document.activeElement).not.toBe(close);
    fireEvent.click(screen.getByTestId("status-scrim"));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "실행 상태" })).toBeNull());
    expect(document.activeElement).toBe(res);
  });

  it("③에는 모델 카드(Final 지정 그대로), ④에는 우측 열 없이 작업 영역만 + '모델' 한 줄", async () => {
    const r = renderApp(`${STUDY}/3`, { user: "power" });
    const work = await screen.findByRole("main", { name: "작업영역" });
    const models = await within(work).findByRole("region", { name: "모델 목록" });
    expect(await within(models).findAllByRole("button", { name: "Final로 지정" })).not.toHaveLength(0);
    expect(document.querySelector(".rightpanel, .cell.rail")).toBeNull();
    r.unmount();
    renderApp(`${STUDY}/4`, { user: "power" });
    const work4 = await screen.findByRole("main", { name: "작업영역" });
    await within(work4).findByRole("region", { name: "입력 방식" });
    expect(screen.queryByRole("region", { name: "모델 목록" })).toBeNull();
    expect(screen.queryByRole("region", { name: "실행 대기열" })).toBeNull();
    expect(screen.queryByRole("complementary", { name: "공통 패널" })).toBeNull();
    expect(document.querySelector(".rightpanel, .cell.rail")).toBeNull();
    const grid = work4.parentElement!;
    expect(Array.from(grid.children)).toEqual([work4]);
    expect(await within(work4).findByText("모델", { selector: ".field-label" })).toBeTruthy();
  });

  it("단계 버튼 ①~⑤: 현재 단계 aria-current, 큰 번호 01~05 없음", async () => {
    renderApp(`${STUDY}/4`, { user: "power" });
    const stepper = await screen.findByRole("list", { name: "단계" });
    const links = within(stepper).getAllByRole("link");
    expect(links.map((a) => a.textContent?.trim().slice(0, 1))).toEqual(["①", "②", "③", "④", "⑤"]);
    expect(links[3].getAttribute("aria-current")).toBe("step");
    expect(stepper.textContent).not.toMatch(/0[1-5]/);
  });
});
