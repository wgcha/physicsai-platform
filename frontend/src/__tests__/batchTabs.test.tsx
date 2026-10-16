// D3-53: ④ 일괄 예측 서브 탭 "실행 목록" | "새 일괄 예측" — 기본 탭·기억, 목록 전부(완료 포함)·응답 요약, 행 → 결과 화면,
// 결과 화면 "← 실행 목록", 배치 완료 알림 → 결과 화면.
import { afterEach, describe, expect, it } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { renderApp, STUDY } from "../test/render";
import { BATCH_TAB_KEY } from "../stages/stage4/batch/BatchMode";

const KEY = "physicsai.stage4.inputMode";
const tab = (name: string) => screen.findByRole("tab", { name: new RegExp(`^${name}`) }) as Promise<HTMLButtonElement>;

describe("일괄 예측 서브 탭 (D3-53)", () => {
  afterEach(() => localStorage.clear());

  it("진행 중 배치가 없으면 '새 일괄 예측', 실행 목록은 완료 배치도 보이고(응답 요약) 행 클릭 → 결과 화면 → '← 실행 목록'", async () => {
    localStorage.setItem(KEY, "batch");
    renderApp(`${STUDY}/4`, { user: "power" });
    expect((await tab("새 일괄 예측")).getAttribute("aria-selected")).toBe("true");
    expect(await screen.findByRole("region", { name: "1 템플릿·조합" })).toBeTruthy();
    fireEvent.click(await tab("실행 목록"));
    expect(localStorage.getItem(BATCH_TAB_KEY)).toBe("list");
    const table = await screen.findByRole("table", { name: "일괄 예측 실행 목록" });
    const row = within(table).getByTestId("batch-B-002");
    expect(row.textContent).toContain("완료");
    expect(row.textContent).toContain("입력 생성 19/20");
    expect(within(row).getByTestId("summary-B-002").textContent).toMatch(/^MaxStress .+ ~ .+ MPa \(\d+ run\)$/);
    fireEvent.click(row);
    expect(await screen.findByRole("region", { name: "결과 표 — B-002" })).toBeTruthy();
    fireEvent.click(screen.getByRole("link", { name: "← 실행 목록" }));
    expect(await screen.findByRole("table", { name: "일괄 예측 실행 목록" })).toBeTruthy();
    expect((await tab("실행 목록")).getAttribute("aria-selected")).toBe("true");
  });

  it("진행 중 배치가 있으면 기본 '실행 목록'(기억한 탭보다 우선), 상태 집계에 실행 중·대기", async () => {
    localStorage.setItem(KEY, "batch");
    localStorage.setItem(BATCH_TAB_KEY, "new");
    renderApp(`${STUDY}/4`, { user: "power", batchDemo: "running" });
    expect((await tab("실행 목록")).getAttribute("aria-selected")).toBe("true");
    const row = within(await screen.findByRole("table", { name: "일괄 예측 실행 목록" })).getByTestId("batch-B-003");
    expect(row.textContent).toMatch(/실행 중|대기/);
    expect(within(row).getByTestId("summary-B-003")).toBeTruthy();
  });

  it("실행 버튼 → 그 배치 결과 화면, 다음에 돌아오면 '실행 목록'; 배치 완료 알림 클릭 → 결과 화면", async () => {
    localStorage.setItem(KEY, "batch");
    const { server } = renderApp(`${STUDY}/4`, { user: "power" });
    const setup = await screen.findByRole("region", { name: "1 템플릿·조합" });
    fireEvent.change(within(setup).getByLabelText("조합 수"), { target: { value: "2" } });
    fireEvent.click(within(setup).getByRole("button", { name: "조합 만들기" }));
    await screen.findByRole("table", { name: "조합 미리보기" });
    const run = screen.getByRole("button", { name: "입력 생성 + 일괄 예측 실행" }) as HTMLButtonElement;
    await waitFor(() => expect(run.disabled).toBe(false));
    fireEvent.click(run);
    expect(await screen.findByRole("region", { name: "결과 표 — B-003" })).toBeTruthy();
    expect(localStorage.getItem(BATCH_TAB_KEY)).toBe("list");
    // 알림: 다른 화면에서 배치 완료 알림을 누르면 그 배치 결과 화면
    fireEvent.click(screen.getByRole("link", { name: "← 실행 목록" }));
    await screen.findByRole("table", { name: "일괄 예측 실행 목록" });
    const b2 = server.batches.find((b) => b.batch_no === 2)!;
    server.notify("u-power", "PREDICT_BATCH_DONE", server.jobs.find((j) => j.id === b2.job_id)!, "일괄 예측 B-002 완료");
    const bell = await screen.findByRole("button", { name: /알림 [1-9]\d*건 미읽음/ });
    fireEvent.click(bell);
    fireEvent.click(await screen.findByText("일괄 예측 B-002 완료"));
    expect(await screen.findByRole("region", { name: "결과 표 — B-002" })).toBeTruthy();
  });
});
