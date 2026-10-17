// phase3 §16.5 S11 SCX 잡(D3-58): 게이트웨이 중립 단계·드라이브 잡 폴더·"확인 필요" 배지·결과 모름 조치 3개
import { describe, expect, it } from "vitest";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { renderApp, STUDY } from "../test/render";
import { SCX_MARK_WARNING, SCX_UNKNOWN_TEXT, hpcPhaseText } from "../components/HpcScx";
import { baseJob, iso } from "../mock/data";
import type { MockServer } from "../mock/server";

/** server.handle 호출(본문 포함) 기록 */
function recordBodies(server: MockServer) {
  const calls: { call: string; body: Record<string, unknown> | null }[] = [];
  const orig = server.handle.bind(server);
  server.handle = (m, p, q, b, h) => {
    calls.push({ call: `${m} ${p}`, body: (b ?? null) as Record<string, unknown> | null });
    return orig(m, p, q, b, h);
  };
  return calls;
}

const UNKNOWN_RUN = "run__00030";
const SCX = { user: "admin" as const, hpcConfigured: true, hpcMode: "scx" as const, scxUnknown: true };

async function unknownRow() {
  const card = await screen.findByRole("region", { name: "PBS 해석 제출" });
  const table = await within(card).findByRole("table", { name: "PBS 제출 표" });
  const panel = await within(table).findByTestId("hpc-resolve");
  return { card, table, panel };
}

describe("S11 SCX 잡 화면(D3-58)", () => {
  it("단계 글자: 업로드 중 → 대기 → 실행 → 완료 → 결과 회수, 결과 모름은 확인 필요", () => {
    const t = (state: string, collect_state = "NONE", submission_unknown = false) => hpcPhaseText({ state, collect_state, submission_unknown });
    expect(["SUBMITTING", "QUEUED", "RUNNING"].map((s) => t(s))).toEqual(["업로드 중", "대기", "실행"]);
    expect(t("SUCCEEDED", "PENDING")).toBe("완료");
    expect(t("SUCCEEDED", "COLLECTING")).toBe("결과 회수 중");
    expect(t("SUCCEEDED", "COLLECTED")).toBe("결과 회수됨");
    expect(t("UNKNOWN", "NONE", true)).toBe("확인 필요");
    expect(t("UNKNOWN")).toBe("확인 중");
  });

  it("① 확인 필요 배지·설명·드라이브 폴더(표시·복사), 나머지 run은 중립 단계", async () => {
    renderApp(`${STUDY}/1`, SCX);
    const { table, panel } = await unknownRow();
    expect(within(table).getByText("드라이브 폴더")).toBeTruthy();
    expect(within(table).getByText("잡 ID")).toBeTruthy();
    const row = within(table).getAllByRole("row").find((r) => r.textContent?.includes(UNKNOWN_RUN))!;
    expect(within(row).getByTestId("hpc-needs-check").textContent).toBe("확인 필요");
    expect(within(row).getByText(`01_D-001_${UNKNOWN_RUN}_20261017T105700`).getAttribute("title")).toBe(`/Users/vd.dashboard/cushion_v1/01_D-001_${UNKNOWN_RUN}_20261017T105700`);
    expect(within(row).getByRole("button", { name: /^복사: \/Users\/vd\.dashboard/ })).toBeTruthy();
    expect(panel.textContent).toContain(SCX_UNKNOWN_TEXT);
    for (const name of ["다시 확인", "잡 ID 연결", "제출 안 됨으로 처리"]) expect(within(panel).getByRole("button", { name })).toBeTruthy();
    // 확인 필요는 한 행만, 실행 중 run은 "(실행)"
    expect(within(table).getAllByTestId("hpc-needs-check")).toHaveLength(1);
    const running = within(table).getAllByRole("row").find((r) => r.textContent?.includes("run__00028"))!;
    expect(running.textContent).toContain("(실행)");
  });

  it("다시 확인 → POST resolve(recheck, version) → 요청됨 → 워커 처리 후 배지 사라짐", async () => {
    const { server } = renderApp(`${STUDY}/1`, SCX);
    const { table, panel } = await unknownRow();
    const calls = recordBodies(server);
    fireEvent.click(within(panel).getByRole("button", { name: "다시 확인" }));
    expect(await within(panel).findByTestId("hpc-resolve-pending")).toBeTruthy();
    const post = calls.filter((c) => c.call.endsWith("/resolve"));
    expect(post).toHaveLength(1);
    expect(post[0].call).toBe(`POST /jobs/j-solve/hpc-jobs/hj-j-solve-${UNKNOWN_RUN}-1/resolve`);
    expect(post[0].body).toEqual({ action: "recheck", version: 1 });
    act(() => server.tick());
    await waitFor(() => expect(within(table).queryByTestId("hpc-needs-check")).toBeNull(), { timeout: 3000 });
    const row = within(table).getAllByRole("row").find((r) => r.textContent?.includes(UNKNOWN_RUN))!;
    expect(row.textContent).toMatch(/scx-\d+/);
  });

  it("잡 ID 연결: 입력 전 비활성, 입력한 ID로 attach", async () => {
    const { server } = renderApp(`${STUDY}/1`, SCX);
    const { panel } = await unknownRow();
    const btn = within(panel).getByRole("button", { name: "잡 ID 연결" }) as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    fireEvent.change(within(panel).getByLabelText("SCX 잡 ID"), { target: { value: " J-778899 " } });
    const calls = recordBodies(server);
    fireEvent.click(btn);
    await within(panel).findByTestId("hpc-resolve-pending");
    expect(calls.find((c) => c.call.endsWith("/resolve"))!.body).toEqual({ action: "attach", external_job_id: "J-778899", version: 1 });
    act(() => server.tick());
    const card = screen.getByRole("region", { name: "PBS 해석 제출" });
    await waitFor(() => expect(within(card).getByText("J-778899")).toBeTruthy(), { timeout: 3000 });
  });

  it("제출 안 됨으로 처리: 중복 해석 경고 확인 후 mark_not_submitted, 취소하면 요청 없음", async () => {
    const { server } = renderApp(`${STUDY}/1`, SCX);
    const { table, panel } = await unknownRow();
    const calls = recordBodies(server);
    fireEvent.click(within(panel).getByRole("button", { name: "제출 안 됨으로 처리" }));
    let dlg = await screen.findByRole("dialog", { name: "제출 안 됨으로 처리" });
    expect(dlg.textContent).toContain(SCX_MARK_WARNING);
    fireEvent.click(within(dlg).getByRole("button", { name: "취소" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(calls.filter((c) => c.call.endsWith("/resolve"))).toHaveLength(0);
    fireEvent.click(within(panel).getByRole("button", { name: "제출 안 됨으로 처리" }));
    dlg = await screen.findByRole("dialog", { name: "제출 안 됨으로 처리" });
    fireEvent.click(within(dlg).getByRole("button", { name: "제출 안 됨으로 처리" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(calls.find((c) => c.call.endsWith("/resolve"))!.body).toEqual({ action: "mark_not_submitted", version: 1 });
    act(() => server.tick());
    await waitFor(() => {
      const row = within(table).getAllByRole("row").find((r) => r.textContent?.includes(UNKNOWN_RUN))!;
      expect(within(row).getByText("해석 실패")).toBeTruthy();
    }, { timeout: 3000 });
  });

  it("409(이미 요청됨)이면 오류 문구를 보이고 행을 다시 읽는다", async () => {
    const { server } = renderApp(`${STUDY}/1`, SCX);
    const { panel } = await unknownRow();
    const run = server.p2.runs[Object.keys(server.p2.runs).find((k) => server.p2.runs[k].some((r) => r._job === "j-solve"))!].find((r) => r.run_key === UNKNOWN_RUN)! as unknown as { _scx: { resolve: unknown } };
    run._scx.resolve = { action: "recheck" };
    fireEvent.click(within(panel).getByRole("button", { name: "다시 확인" }));
    expect((await within(panel).findByRole("alert")).textContent).toContain("이미 요청한 조치");
    expect(await within(panel).findByTestId("hpc-resolve-pending")).toBeTruthy();
  });

  it("PBS(command) 모드는 기존 표 그대로 — hpc-jobs를 읽지 않음", async () => {
    const { server } = renderApp(`${STUDY}/1`, { user: "admin", hpcConfigured: true });
    const calls = recordBodies(server);
    const table = await screen.findByRole("table", { name: "PBS 제출 표" });
    await waitFor(() => expect(within(table).getAllByRole("row").length).toBe(31));
    expect(within(table).getByText("PBS job")).toBeTruthy();
    expect(within(table).queryByText("드라이브 폴더")).toBeNull();
    expect(within(table).queryByTestId("hpc-needs-check")).toBeNull();
    expect(calls.some((c) => c.call.includes("/hpc-jobs"))).toBe(false);
  });

  it("④ scx: 버튼 '검증 해석(SCX)', 결과 모름 검증 잡에 확인 필요·잡 폴더·조치", async () => {
    const { server } = renderApp(`${STUDY}/4`, { user: "power", hpcConfigured: true, hpcMode: "scx" }, (srv) => {
      const v = baseJob({ id: "j-pv", study_id: "s-cushion", project_id: "p-cushion", study_title: "쿠션", job_type: "PREDICT_VERIFY", state: "WAITING_HPC", created_by: "u-power", created_at: iso(1), started_at: iso(1), params: { predict_job_id: "j-pred", hpc: {} } });
      (v as unknown as { _scx: unknown })._scx = { id: "hj-j-pv", version: 3, remote_dir: "/Users/vd.dashboard/cushion_v1/04_V-001_20261017T105700", request_id: "pai-hj-j-pv", submission_unknown: true, resolve: null, error_message: "SCX 제출 결과를 알 수 없습니다 — SCX에서 확인 필요", state: "UNKNOWN" };
      srv.jobs.push(v);
    });
    expect(await screen.findByRole("button", { name: "검증 해석(SCX)" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "PBS 검증 해석" })).toBeNull();
    const panel = await screen.findByTestId("hpc-resolve");
    expect(within(panel).getByTestId("hpc-needs-check")).toBeTruthy();
    expect(within(panel).getByText("/Users/vd.dashboard/cushion_v1/04_V-001_20261017T105700")).toBeTruthy();
    const calls = recordBodies(server);
    fireEvent.click(within(panel).getByRole("button", { name: "다시 확인" }));
    await within(panel).findByTestId("hpc-resolve-pending");
    expect(calls.find((c) => c.call.endsWith("/resolve"))).toEqual({ call: "POST /jobs/j-pv/hpc-jobs/hj-j-pv/resolve", body: { action: "recheck", version: 3 } });
    act(() => server.tick());
    expect(await screen.findByTestId("scx-phase", {}, { timeout: 3000 })).toBeTruthy();
    expect(screen.getByTestId("scx-phase").textContent).toBe("대기");
  });
});
