import { describe, expect, it } from "vitest";
import { screen, within } from "@testing-library/react";
import { renderApp, STUDY } from "../test/render";

describe("공통 셸 (V-FE-1, V-FE-7)", () => {
  it("경로바·스텝퍼·우측 패널 3종을 그린다", async () => {
    renderApp(`${STUDY}/3`, { user: "power" });
    const nav = await screen.findByRole("navigation", { name: "경로" });
    expect(within(nav).getByText("AI 예측")).toBeTruthy();
    expect(await within(nav).findByText("쿠션 두께·리브 예측")).toBeTruthy();
    expect(within(nav).getByText(/데이터셋·모델/)).toBeTruthy();
    expect(screen.getByRole("region", { name: "실행 대기열" })).toBeTruthy();
    expect(screen.getByRole("region", { name: "워커 자원" })).toBeTruthy();
    expect(screen.getByRole("region", { name: "모델 목록" })).toBeTruthy();
    const stepper = screen.getByRole("list", { name: "단계" });
    expect(within(stepper).queryAllByText("2차")).toHaveLength(0);
    expect(within(stepper).getAllByRole("link")).toHaveLength(5);
  });

  it("V2-FE-1: ①②⑤도 실제 화면(2차 안내 없음)", async () => {
    renderApp(`${STUDY}/1`, { user: "power" });
    expect(await screen.findByRole("region", { name: "CAD 파라미터 추출" })).toBeTruthy();
    expect(screen.queryByText("2차에서 제공 예정입니다.")).toBeNull();
  });

  it("401이면 대시보드 로그인 안내", async () => {
    renderApp(`${STUDY}/3`, { user: "anon" });
    expect(await screen.findByText("대시보드에서 로그인하세요")).toBeTruthy();
    expect(screen.getByRole("link", { name: "대시보드로 이동" }).getAttribute("href")).toBe("/");
  });
});
