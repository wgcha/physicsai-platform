// 2026-10-17 대시보드 톤·테마 동기화·레이아웃 A(phase3.md D3-55)
import { afterEach, describe, expect, it } from "vitest";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { openStatusDrawer, renderApp, STUDY } from "../test/render";
import { LEGACY_THEME_KEY, THEME_KEY, readTheme } from "../design/theme";
import shellCss from "../styles/shell.css?raw";
import tokensCss from "../design/tokens.css?raw";

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

  it("단계 버튼 ①~⑥(S14): 현재 단계 aria-current, 큰 번호 01~06 없음", async () => {
    renderApp(`${STUDY}/4`, { user: "power" });
    const stepper = await screen.findByRole("list", { name: "단계" });
    const links = within(stepper).getAllByRole("link");
    expect(links.map((a) => a.querySelector(".sr-only")?.textContent)).toEqual(["①", "②", "③", "④", "⑤", "⑥"]);
    expect(links[3].getAttribute("aria-current")).toBe("step");
    expect(links.filter((a) => a.hasAttribute("aria-current"))).toHaveLength(1);
    expect(stepper.textContent).not.toMatch(/0[1-6]/);
  });

  it("D3-56·S14 단계 버튼: 6칸 같은 폭 격자 + 숫자 배지 1~6(원 문자 글리프 대신), 읽기용 이름은 '① 학습데이터 생성' 그대로, Study 관리는 같은 줄 끝", async () => {
    renderApp(`${STUDY}/4`, { user: "power" });
    const stepper = await screen.findByRole("list", { name: "단계" });
    expect(stepper.classList.contains("stepper")).toBe(true);
    const items = within(stepper).getAllByRole("listitem");
    expect(items).toHaveLength(6);
    const badges = items.map((li) => li.querySelector(".step-num"));
    expect(badges.map((b) => b?.textContent)).toEqual(["1", "2", "3", "4", "5", "6"]);
    expect(badges.every((b) => b?.getAttribute("aria-hidden") === "true")).toBe(true);
    expect(within(stepper).getByRole("link", { name: /^① 학습데이터 생성/ })).toBeTruthy();
    const cur = within(stepper).getByRole("link", { name: /^④ 예측/ });
    expect(cur.getAttribute("aria-current")).toBe("step");
    expect(cur.closest("li")?.classList.contains("current")).toBe(true);
    const row = stepper.parentElement!;
    expect(row.classList.contains("stepper-row")).toBe(true);
    expect(row.lastElementChild?.textContent).toBe("Study 관리");
  });

  it("D3-56·S14 CSS: 스텝퍼 repeat(6, minmax(0, 1fr)), 버튼 높이 --step-h 52px·글자 15px", () => {
    expect(shellCss).toMatch(/\.stepper\s*\{[^}]*grid-template-columns:\s*repeat\(6,\s*minmax\(0,\s*1fr\)\)/);
    expect(shellCss).toMatch(/\.step a\s*\{[^}]*min-height:\s*var\(--step-h\)/);
    expect(tokensCss).toMatch(/--step-h:\s*52px/);
    expect(tokensCss).toMatch(/--step-size:\s*15px/);
  });
});
