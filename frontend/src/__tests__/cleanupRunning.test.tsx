// phase3.md D3-24: 정리(STUDY_CLEANUP) 대기·실행 중에는 스캔 생성·Final 지정 PUT도 409 STUDY_CLEANUP_RUNNING.
import { describe, expect, it } from "vitest";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { renderApp, STUDY } from "../test/render";
import { recordCalls } from "../test/recordCalls";
import { MockServer } from "../mock/server";
import { CLEANUP_POLL, cleanupRunningMessage, isCleanupRunningError } from "../hooks/useCleanupRunning";
import { STORAGE_POLL } from "../pages/manage/StorageSection";
import { ApiError } from "../api";

const H = new Headers({ "X-PhysicsAI-Request": "1" });
const Q = new URLSearchParams();
const TERMINAL = ["SUCCEEDED", "FAILED", "CANCELED", "INTERRUPTED"];
const MANAGE = "/p/p-cushion/s/s-cushion/manage";
const BUSY_FINAL = "Study 정리가 진행 중이라 Final 모델을 바꿀 수 없습니다. 정리가 끝난 뒤 다시 시도하세요";
const BUSY_SCAN = "Study 정리가 진행 중이라 용량을 다시 계산할 수 없습니다. 정리가 끝난 뒤 다시 시도하세요";

/** 시드 작업을 끝내고 스캔 → 정리(QUEUED)를 만든다. 정리 Job id 반환 */
function startCleanup(s: MockServer): string {
  s.jobs.forEach((j) => j.study_id === "s-cushion" && !TERMINAL.includes(j.state) && ((j.state = "CANCELED"), (j.finished_at = "2026-01-01T00:00:00Z")));
  const scan = s.handle("POST", "/studies/s-cushion/jobs", Q, { job_type: "STUDY_STORAGE_SCAN", params: {} }, H);
  expect(scan.status).toBe(201);
  s.finishAll();
  const cl = s.handle("POST", "/studies/s-cushion/jobs", Q, { job_type: "STUDY_CLEANUP", params: { scan_job_id: (scan.body as { id: string }).id, categories: ["JOB_LOGS"] } }, H);
  expect(cl.status).toBe(201);
  return (cl.body as { id: string }).id;
}

const code = (r: { body?: unknown }) => (r.body as { detail: { code: string } }).detail.code;

describe("D3-24 목: 정리 중 스캔·Final 지정 409", () => {
  it("정리 대기 중 스캔 생성·PUT final-model(지정·해제) 409, 끝나면 200·201", () => {
    const s = new MockServer({ user: "power" });
    startCleanup(s);
    const scan = s.handle("POST", "/studies/s-cushion/jobs", Q, { job_type: "STUDY_STORAGE_SCAN", params: {} }, H);
    expect(scan.status).toBe(409);
    expect(code(scan)).toBe("STUDY_CLEANUP_RUNNING");
    const put = s.handle("PUT", "/studies/s-cushion/final-model", Q, { model_id: "m-2" }, H);
    expect(put.status).toBe(409);
    expect(code(put)).toBe("STUDY_CLEANUP_RUNNING");
    expect(code(s.handle("PUT", "/studies/s-cushion/final-model", Q, { model_id: null }, H))).toBe("STUDY_CLEANUP_RUNNING");
    expect(s.studies.find((x) => x.id === "s-cushion")!.final_model_id).toBe("m-1");
    s.finishAll();
    expect(s.handle("PUT", "/studies/s-cushion/final-model", Q, { model_id: "m-2" }, H).status).toBe(200);
    expect(s.handle("POST", "/studies/s-cushion/jobs", Q, { job_type: "STUDY_STORAGE_SCAN", params: {} }, H).status).toBe(201);
  });

  it("권한 검사가 먼저(general은 403)", () => {
    const s = new MockServer({ user: "power" });
    startCleanup(s);
    const g = new MockServer({ user: "general" });
    g.jobs.splice(0, g.jobs.length, ...s.jobs);
    const r = g.handle("PUT", "/studies/s-cushion/final-model", Q, { model_id: "m-2" }, H);
    expect(r.status).toBe(403);
  });

  it("문구 함수: 409 STUDY_CLEANUP_RUNNING만 한국어 문구", () => {
    const e = new ApiError(409, { code: "STUDY_CLEANUP_RUNNING", message: "x" });
    expect(isCleanupRunningError(e)).toBe(true);
    expect(cleanupRunningMessage(e, "Final 모델을 바꿀")).toBe(BUSY_FINAL);
    expect(cleanupRunningMessage(new ApiError(409, { code: "MODEL_NOT_ACTIVE", message: "x" }), "a")).toBeNull();
    expect(cleanupRunningMessage(new Error("x"), "a")).toBeNull();
  });
});

describe("D3-24 화면: 정리 진행 중 안내", () => {
  it("③-5: 정리 중이면 Final 지정·해제·비교 표 Final 지정 비활성 + 안내, 끝나면 다시 활성", async () => {
    CLEANUP_POLL.ms = 60;
    const { server } = renderApp(`${STUDY}/3`, { user: "power" }, startCleanup);
    const card = await screen.findByRole("region", { name: "평가 · Final 지정" });
    await within(card).findByTestId("final-cleanup-running");
    const table = within(card).getByRole("table", { name: "모델 표" });
    const v2 = within(table).getAllByRole("row").find((r) => r.textContent?.includes("cushion_TNS v2"))!;
    const btn = within(v2).getByRole("button", { name: "Final 지정" }) as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    expect(btn.title).toContain("정리가 진행 중");
    expect((within(table).getByRole("button", { name: "해제" }) as HTMLButtonElement).disabled).toBe(true);

    for (const n of ["cushion_TNS v1", "cushion_TNS v2"]) fireEvent.click(within(card).getByLabelText(`${n} 비교 선택`));
    fireEvent.click(within(card).getByRole("button", { name: /^선택 비교/ }));
    const panel = await within(card).findByRole("region", { name: "모델 비교" });
    const score = await within(panel).findByRole("table", { name: "모델 비교 점수" });
    const head = await waitFor(() => within(score).getAllByRole("columnheader").find((h) => h.textContent?.includes("cushion_TNS v2") && within(h).queryByRole("button"))!);
    expect((within(head).getByRole("button", { name: "Final 지정" }) as HTMLButtonElement).disabled).toBe(true);
    expect(within(head).getByText("정리 진행 중")).toBeTruthy();

    const calls = recordCalls(server);
    fireEvent.click(btn);
    expect(calls.filter((c) => c.startsWith("PUT "))).toHaveLength(0);

    act(() => server.finishAll());
    await waitFor(() => expect(within(card).queryByTestId("final-cleanup-running")).toBeNull(), { timeout: 3000 });
    expect((within(v2).getByRole("button", { name: "Final 지정" }) as HTMLButtonElement).disabled).toBe(false);
    expect((within(head).getByRole("button", { name: "Final 지정" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("③-5: 화면을 연 뒤 정리가 시작되면 Final 지정 409 → 한국어 문구 + 안내", async () => {
    const { server } = renderApp(`${STUDY}/3`, { user: "power" });
    const card = await screen.findByRole("region", { name: "평가 · Final 지정" });
    const table = await within(card).findByRole("table", { name: "모델 표" });
    await waitFor(() => expect(within(card).queryByTestId("final-cleanup-running")).toBeNull());
    startCleanup(server);
    const v2 = within(table).getAllByRole("row").find((r) => r.textContent?.includes("cushion_TNS v2"))!;
    fireEvent.click(within(v2).getByRole("button", { name: "Final 지정" }));
    expect(await within(card).findByText(BUSY_FINAL)).toBeTruthy();
    await within(card).findByTestId("final-cleanup-running");
    expect(server.studies.find((x) => x.id === "s-cushion")!.final_model_id).toBe("m-1");
  });

  it("Study 관리: 정리 중이면 다시 계산 비활성 + 안내, 스캔 409 → 한국어 문구", async () => {
    STORAGE_POLL.ms = 60;
    const { server } = renderApp(MANAGE, { user: "power" }, startCleanup);
    const card = await screen.findByRole("region", { name: "용량·정리" });
    await within(card).findByTestId("scan-cleanup-running");
    const btn = within(card).getByRole("button", { name: "다시 계산" }) as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    expect(btn.title).toContain("정리가 진행 중");
    act(() => server.finishAll());
    await waitFor(() => expect(within(card).queryByTestId("scan-cleanup-running")).toBeNull(), { timeout: 3000 });
    await waitFor(() => expect(btn.disabled).toBe(false));

    // 화면이 모르는 사이 정리가 시작된 경우: 서버 409를 한국어로
    const orig = server.handle.bind(server);
    server.handle = (m, p, q, b, h) =>
      m === "POST" && p === "/studies/s-cushion/jobs"
        ? { status: 409, body: { detail: { code: "STUDY_CLEANUP_RUNNING", message: "Study 정리가 진행 중입니다" } } }
        : orig(m, p, q, b, h);
    fireEvent.click(btn);
    expect(await within(card).findByText(BUSY_SCAN)).toBeTruthy();
  });

  it("우측 모델 패널: 정리 중이면 Final로 지정 비활성 + 안내, 끝나면 활성", async () => {
    CLEANUP_POLL.ms = 60;
    const { server } = renderApp(`${STUDY}/3`, { user: "power" }, startCleanup);
    const panel = await screen.findByRole("region", { name: "모델 목록" });
    await within(panel).findByTestId("panel-cleanup-running");
    const btns = within(panel).getAllByRole("button", { name: "Final로 지정" }) as HTMLButtonElement[];
    expect(btns.length).toBeGreaterThan(0);
    expect(btns.every((b) => b.disabled && b.title.includes("정리가 진행 중"))).toBe(true);
    act(() => server.finishAll());
    await waitFor(() => expect(within(panel).queryByTestId("panel-cleanup-running")).toBeNull(), { timeout: 3000 });
    expect((within(panel).getAllByRole("button", { name: "Final로 지정" }) as HTMLButtonElement[]).every((b) => !b.disabled)).toBe(true);
  });
});
