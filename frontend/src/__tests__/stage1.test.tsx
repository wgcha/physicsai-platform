// phase2.md §20 V2-FE-2 (컴포넌트 시험, 목 서버)
import { describe, expect, it } from "vitest";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { renderApp, STUDY } from "../test/render";
import { PBS_NONE_TEXT } from "../stages/stage1/SolveCard";
import { recordCalls } from "../test/recordCalls";

describe("V2-FE-2 ① 학습데이터 생성", () => {
  it("카드 6개, 권한 없으면 조회 전용", async () => {
    renderApp(`${STUDY}/1`, { user: "general" });
    for (const name of ["CAD 파라미터 추출", "파라미터 표", "DOE · Radioss 입력", "PBS 해석 제출", "결과 회수", "run 응답 추출 (선택)"])
      expect(await screen.findByRole("region", { name })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "파라미터 추출" })).toBeNull();
    expect(screen.queryByRole("button", { name: "tpl 생성" })).toBeNull();
    expect(screen.getAllByText("조회 전용").length).toBeGreaterThanOrEqual(5);
  });

  it("파라미터 표: 사용 체크·범위 편집 → stale 문구, tpl 생성은 PUT 후 POST", async () => {
    const { server } = renderApp(`${STUDY}/1`, { user: "power" });
    const card = await screen.findByRole("region", { name: "파라미터 표" });
    await within(card).findByRole("table", { name: "파라미터 표" });
    expect((within(card).getByLabelText("bad name 사용") as HTMLInputElement).disabled).toBe(true);
    expect(within(card).getByTestId("tpl-state").textContent).toContain("tpl 생성됨 · 사용 4개");
    fireEvent.click(within(card).getByLabelText("FILLET_R 사용"));
    expect(within(card).getByTestId("tpl-state").textContent).toContain("표가 바뀌었습니다 — tpl을 다시 생성하세요");
    // 고급: 형식·단위 열
    expect(within(card).queryByLabelText("THK_TOP 형식")).toBeNull();
    fireEvent.click(within(card).getByRole("button", { name: /고급/ }));
    expect(within(card).getByLabelText("THK_TOP 형식")).toBeTruthy();
    const calls = recordCalls(server);
    fireEvent.click(within(card).getByRole("button", { name: "tpl 생성" }));
    await waitFor(() => expect(within(card).getByTestId("tpl-state").textContent).toContain("사용 5개"));
    const order = calls.filter((c) => c.includes("/train/"));
    expect(order).toEqual(["PUT /studies/s-cushion/train/params", "POST /studies/s-cushion/train/tpl"]);
  });

  it("tpl 생성: PUT 실패(VERSION_CONFLICT)면 POST를 보내지 않는다", async () => {
    const { server } = renderApp(`${STUDY}/1`, { user: "power" });
    const card = await screen.findByRole("region", { name: "파라미터 표" });
    await within(card).findByRole("table", { name: "파라미터 표" });
    server.p2.setups["s-cushion"].version += 1;
    const calls = recordCalls(server);
    fireEvent.click(within(card).getByRole("button", { name: "tpl 생성" }));
    expect(await within(card).findByRole("alert")).toBeTruthy();
    expect(calls.filter((c) => c.includes("/train/"))).toEqual(["PUT /studies/s-cushion/train/params"]);
  });

  it("DOE 유형별 동적 옵션(int·bool·combo)과 runs_editable", async () => {
    renderApp(`${STUDY}/1`, { user: "power" });
    const card = await screen.findByRole("region", { name: "DOE · Radioss 입력" });
    await within(card).findByLabelText("Random Seed");
    expect(within(card).getByText("Nominal run 포함")).toBeTruthy();
    expect((within(card).getByLabelText("run 수") as HTMLInputElement).disabled).toBe(false);
    fireEvent.change(within(card).getByLabelText("DOE 유형"), { target: { value: "FullFactorial" } });
    expect((within(card).getByLabelText("run 수") as HTMLInputElement).disabled).toBe(true);
    expect(within(card).getByText("자동 계산(HyperStudy 결정)")).toBeTruthy();
    expect((within(card).getByLabelText("Levels") as HTMLSelectElement).value).toBe("3");
    expect(within(card).queryByLabelText("Random Seed")).toBeNull();
  });

  it("PBS none: ①-4 버튼 비활성 + 안내 + DOE 폴더 경로, ①-5 수동 결과 폴더", async () => {
    renderApp(`${STUDY}/1`, { user: "power" });
    const card = await screen.findByRole("region", { name: "PBS 해석 제출" });
    const none = await within(card).findByTestId("pbs-none");
    expect(none.textContent).toContain(PBS_NONE_TEXT);
    expect((within(none).getByRole("button", { name: "PBS 제출" }) as HTMLButtonElement).disabled).toBe(true);
    expect(await within(none).findByText(/01_train\\doe\\doe-1$/)).toBeTruthy();
    const col = screen.getByRole("region", { name: "결과 회수" });
    expect(within(col).getByText("PBS 연결 안 됨 — 해석한 결과 폴더를 직접 지정하세요")).toBeTruthy();
    expect(await within(col).findByTestId("tile-collected")).toBeTruthy();
    await waitFor(() => expect(within(col).getByTestId("tile-collected").textContent).toBe("24/30"));
  });

  it("PBS 구성: run 상태 막대·제출 표, 관리자만 취소/재제출", async () => {
    const { server } = renderApp(`${STUDY}/1`, { user: "admin", hpcConfigured: true });
    const card = await screen.findByRole("region", { name: "PBS 해석 제출" });
    const table = await within(card).findByRole("table", { name: "PBS 제출 표" });
    await waitFor(() => expect(within(card).getByTestId("runbar-col").textContent).toContain("24"));
    expect(within(card).getByTestId("runbar-fail").textContent).toContain("1");
    const failedRow = within(table).getAllByRole("row").find((r) => r.textContent?.includes("run__00027"))!;
    expect(within(failedRow).getByText("해석 실패")).toBeTruthy();
    expect(within(failedRow).getByRole("button", { name: "재제출" })).toBeTruthy();
    const subRow = within(table).getAllByRole("row").find((r) => r.textContent?.includes("run__00028"))!;
    fireEvent.click(await within(subRow).findByRole("button", { name: "취소" }));
    fireEvent.click(within(subRow).getByRole("button", { name: "작업 전체 취소" }));
    await waitFor(() => expect(server.jobs.find((j) => j.id === "j-solve")!.cancel_requested).toBe(true));
  });

  it("C18: PBS 취소 실패 → '취소 실패, 재시도 중'(① 표·작업 상태·대기열) + 알림", async () => {
    const { server } = renderApp(`${STUDY}/1`, { user: "admin", hpcConfigured: true, hpcCancelFails: true });
    const card = await screen.findByRole("region", { name: "PBS 해석 제출" });
    const table = await within(card).findByRole("table", { name: "PBS 제출 표" });
    const subRow = within(table).getAllByRole("row").find((r) => r.textContent?.includes("run__00028"))!;
    fireEvent.click(await within(subRow).findByRole("button", { name: "취소" }));
    fireEvent.click(within(subRow).getByRole("button", { name: "작업 전체 취소" }));
    await waitFor(() => expect(server.jobs.find((j) => j.id === "j-solve")!.cancel_requested).toBe(true));
    act(() => server.tick());
    const j = server.jobs.find((x) => x.id === "j-solve")!;
    expect(j.state).toBe("WAITING_HPC");
    expect(j.attention_code).toBe("HPC_CANCEL_FAILED");
    expect(server.notifs.filter((n) => n.event === "HPC_CANCEL_FAILED")).toHaveLength(1);
    act(() => server.tick());
    expect(server.notifs.filter((n) => n.event === "HPC_CANCEL_FAILED")).toHaveLength(1); // 1회만
    const q = screen.getByRole("region", { name: "실행 대기열" });
    await waitFor(() => expect(within(q).getByTestId("queue-attention").textContent).toContain("취소 실패, 재시도 중"), { timeout: 3000 });
    expect((await within(card).findByTestId("attention", {}, { timeout: 3000 })).textContent).toBe("취소 실패, 재시도 중");
    await waitFor(() => expect(within(card).getAllByTestId("run-cancel-failed")[0].textContent).toContain("취소 실패, 재시도 중"), { timeout: 3000 });
  });

  it("PBS 구성: power에게는 행 조치 버튼 없음", async () => {
    renderApp(`${STUDY}/1`, { user: "power", hpcConfigured: true });
    const table = await screen.findByRole("table", { name: "PBS 제출 표" });
    await waitFor(() => expect(within(table).getAllByRole("row").length).toBe(31));
    expect(within(table).queryByRole("button", { name: "재제출" })).toBeNull();
    expect(within(table).queryByRole("button", { name: "취소" })).toBeNull();
  });
});
