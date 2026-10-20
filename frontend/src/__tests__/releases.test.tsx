import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { renderApp, STUDY } from "../test/render";
import { compareVersion, isNewVersion, LAST_SEEN_KEY } from "../lib/releases";
import specJson from "../../../backend/openapi.json";
import { api } from "../api";

afterEach(() => {
  localStorage.removeItem(LAST_SEEN_KEY);
  vi.restoreAllMocks();
});

describe("버전 표시·버전 게시판(읽기 전용)", () => {
  it("버전 비교·새 버전 판정", () => {
    expect(compareVersion("0.10.0", "0.9.9")).toBeGreaterThan(0);
    expect(compareVersion("0.2.0", "0.2.0")).toBe(0);
    expect(isNewVersion("0.2.0", null)).toBe(true);
    expect(isNewVersion("0.2.0", "0.2.0")).toBe(false);
    expect(isNewVersion("0.3.0", "0.2.0")).toBe(true);
  });

  it("상단 바 배지 v0.2.0(처음엔 새 버전 점) → 게시판: 버전·날짜·주요 기능, 최신 강조, 본 뒤 점 사라짐", async () => {
    renderApp(`${STUDY}/3`, { user: "general" });
    const badge = await screen.findByTestId("version-badge");
    expect(badge.textContent).toContain("v0.2.0");
    expect(within(badge).getByTestId("version-new")).toBeTruthy();
    fireEvent.click(badge);
    const main = await screen.findByRole("main", { name: "버전 게시판" });
    const latest = await within(main).findByTestId("release-0.2.0");
    expect(latest.className).toContain("latest");
    expect(within(latest).getByText("최신")).toBeTruthy();
    expect(within(latest).getByText("새 버전")).toBeTruthy();
    expect(within(latest).getByText("2026-10-20")).toBeTruthy();
    expect(within(latest).getByText(/native 형상 엔진/)).toBeTruthy();
    expect(within(main).getByTestId("release-0.1.0").className).not.toContain("latest");
    expect(within(within(main).getByTestId("release-0.1.0")).queryByText("새 버전")).toBeNull(); // 본 기록 없으면 최신만
    await waitFor(() => expect(localStorage.getItem(LAST_SEEN_KEY)).toBe("0.2.0"));
    await waitFor(() => expect(screen.queryByTestId("version-new")).toBeNull());
    // 작성·수정·삭제 수단 없음
    expect(within(main).queryByRole("button")).toBeNull();
    expect(within(main).queryByRole("textbox")).toBeNull();
  });

  it("이미 본 버전이면 점 없음, 새 배포(0.3.0)면 다시 점과 '새 버전' 표시", async () => {
    localStorage.setItem(LAST_SEEN_KEY, "0.2.0");
    const r = renderApp(`${STUDY}/3`, { user: "general" });
    await screen.findByTestId("version-badge");
    expect(screen.queryByTestId("version-new")).toBeNull();
    r.unmount();
    renderApp("/releases", { user: "general" }, (srv) => {
      srv.releases = { current_version: "0.3.0", releases: [{ version: "0.3.0", date: "2026-11-01", items: ["새 기능"] }, ...srv.releases.releases] };
    });
    const latest = await screen.findByTestId("release-0.3.0");
    expect(within(latest).getByText("새 버전")).toBeTruthy();
    expect(within(screen.getByTestId("release-0.2.0")).queryByText("새 버전")).toBeNull();
  });

  it("localStorage가 실패해도 화면은 동작", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("denied");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("denied");
    });
    renderApp("/releases", { user: "general" });
    expect(await screen.findByTestId("release-0.2.0")).toBeTruthy();
    expect(await screen.findByTestId("version-badge")).toBeTruthy();
  });

  it("버전 조회 실패면 배지를 숨기고 게시판은 오류 문구", async () => {
    renderApp("/releases", { user: "general" }, (srv) => {
      srv.versionFails = true;
    });
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.queryByTestId("version-badge")).toBeNull();
  });

  it("API는 조회만: openapi에 GET만, 프런트 api에 쓰기 함수 없음", () => {
    const paths = (specJson as unknown as { paths: Record<string, Record<string, unknown>> }).paths;
    expect(Object.keys(paths["/physicsai/api/version"])).toEqual(["get"]);
    expect(Object.keys(paths["/physicsai/api/releases"])).toEqual(["get"]);
    const names = Object.keys(api).filter((k) => /release|version/i.test(k));
    expect(names.sort()).toEqual(["releases", "version"]);
  });
});
