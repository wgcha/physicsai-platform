// phase2.md §20 V2-FE-6 (컴포넌트 시험, 목 서버)
import { describe, expect, it } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { renderApp, STUDY } from "../test/render";
import type { MockServer } from "../mock/server";
import { clearApiCache } from "../api";
import { recordCalls } from "../test/recordCalls";

describe("V2-FE-6 오류 묶음·딥링크·③④ 연결·대기열", () => {
  const failLatest = (s: MockServer, owner = "u-power") => {
    const j = s.jobs.find((x) => x.id === "j-ds2")!;
    Object.assign(j, { state: "FAILED", failure_code: "EXIT_NONZERO", failure_message: "종료코드 1", created_by: owner });
  };

  it("오류 묶음 받기: 등록자 본인에게 보이고 내려받는다", async () => {
    const r = renderApp(`${STUDY}/3`, { user: "power" });
    failLatest(r.server);
    const card = await screen.findByRole("region", { name: "데이터셋 생성" });
    const btn = await within(card).findByRole("button", { name: "오류 묶음 받기" });
    const calls = recordCalls(r.server);
    fireEvent.click(btn);
    await waitFor(() => expect(calls).toContain("GET /jobs/j-ds2/error-bundle.zip"));
    expect(within(card).queryByText(/권한|PERMISSION/)).toBeNull();
  });

  it("오류 묶음 받기: 타인 작업이면 power·general에게 없음, 관리자에게 있음", async () => {
    const a = renderApp(`${STUDY}/3`, { user: "power" });
    failLatest(a.server, "u-other");
    const card = await screen.findByRole("region", { name: "데이터셋 생성" });
    await within(card).findByText(/EXIT_NONZERO/);
    expect(within(card).queryByRole("button", { name: "오류 묶음 받기" })).toBeNull();
    a.unmount();
    clearApiCache();
    const g = renderApp(`${STUDY}/3`, { user: "general" });
    failLatest(g.server);
    const card2 = await screen.findByRole("region", { name: "데이터셋 생성" });
    await within(card2).findByText(/EXIT_NONZERO/);
    expect(within(card2).queryByRole("button", { name: "오류 묶음 받기" })).toBeNull();
    g.unmount();
    clearApiCache(); // 같은 시험 안에서 사용자를 바꾸므로 ETag 캐시를 비운다
    const ad = renderApp(`${STUDY}/3`, { user: "admin" });
    failLatest(ad.server, "u-other");
    const card3 = await screen.findByRole("region", { name: "데이터셋 생성" });
    expect(await within(card3).findByRole("button", { name: "오류 묶음 받기" })).toBeTruthy();
  });

  it("딥링크: 열기만으로 작업을 만들지 않고, Study 선택 후 가져오기 → ② 원천 선택", async () => {
    const path = "\\\\spdm\\master\\FD-X\\Case_0013\\Scene 01";
    const { server } = renderApp(`/import?spdm_path=${encodeURIComponent(path)}&project_id=p-cushion`, { user: "power" });
    const before = server.jobs.length;
    expect(await screen.findByText(path)).toBeTruthy();
    expect((screen.getByLabelText("프로젝트") as HTMLSelectElement).value).toBe("p-cushion");
    await waitFor(() => expect((screen.getByLabelText("Study") as HTMLSelectElement).value).toBe("s-cushion"));
    expect((await screen.findByTestId("import-inspect")).textContent).toContain("이름 정리 1개");
    expect(server.jobs.length).toBe(before);
    fireEvent.click(screen.getByRole("button", { name: "가져오기" }));
    await waitFor(() => expect(server.jobs.some((j) => j.job_type === "SPDM_IMPORT" && j.params.spdm_path === path)).toBe(true));
    const src = await screen.findByRole("radiogroup", { name: "원천" });
    expect(within(src).getByRole("radio", { name: "SPDM 가져오기" }).getAttribute("aria-checked")).toBe("true");
  });

  it("딥링크: general은 가져오기 버튼 없음, spdm 비활성이면 안내", async () => {
    renderApp(`/import?spdm_path=${encodeURIComponent("\\\\spdm\\master\\A")}&project_id=p-cushion`, { user: "general", disabledFeatures: ["spdm_import"] });
    expect(await screen.findByTestId("feature-off-spdm_import")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "가져오기" })).toBeNull();
  });

  it("③-1 기본 입력 = 최근 READY 큐레이션(curation_id로 실행)", async () => {
    const { server } = renderApp(`${STUDY}/3`, { user: "power" });
    const card = await screen.findByRole("region", { name: "데이터셋 생성" });
    expect((await within(card).findByTestId("curation-default")).textContent).toMatch(/② 큐레이션 결과 사용 · .* · 23개/);
    fireEvent.click(within(card).getByRole("button", { name: "데이터셋 생성" }));
    await waitFor(() => expect(server.jobs.some((j) => j.job_type === "DATASET_CREATE" && j.state === "QUEUED")).toBe(true));
    const j = server.jobs.find((x) => x.job_type === "DATASET_CREATE" && x.state === "QUEUED")!;
    expect(j.params.curation_id).toBe("cur-1");
    expect(j.params).not.toHaveProperty("input_path");
  });

  it("④ '① 결과로 만들기' → 파라미터 세트(origin TRAIN_DOE)", async () => {
    const { server } = renderApp(`${STUDY}/4`, { user: "power" });
    const card = await screen.findByRole("region", { name: "파라미터 세트" });
    fireEvent.click(within(card).getByRole("button", { name: "새로 등록" }));
    fireEvent.click(within(card).getByRole("button", { name: "① 결과로 만들기" }));
    const form = await within(card).findByTestId("from-train");
    await waitFor(() => expect((within(form).getByLabelText("DOE 선택") as HTMLSelectElement).value).toBe("doe-1"));
    fireEvent.click(within(form).getByRole("button", { name: "① 결과로 만들기" }));
    await waitFor(() => expect(server.paramSets[0].origin).toBe("TRAIN_DOE"));
    expect(server.paramSets[0].sample_count).toBe(24);
    await waitFor(() => expect(within(card).getByText(/① 결과 · ① DOE doe-1/)).toBeTruthy());
  });

  it("대기열: 단계 배지와 PBS run 집계", async () => {
    renderApp(`${STUDY}/1`, { user: "power", hpcConfigured: true });
    const q = await screen.findByRole("region", { name: "실행 대기열" });
    const hpc = await within(q).findByTestId("hpc-summary");
    expect(hpc.textContent).toBe("PBS 2/6 완료 · 실패 1");
    const row = hpc.closest("li")!;
    expect(within(row as HTMLElement).getByTestId("stage-badge").textContent).toBe("①-4");
    const badges = within(q).getAllByTestId("stage-badge").map((b) => b.textContent);
    expect(badges).toContain("③-5");
  });

  it("알림: HPC_PARTIAL_FAILED·ENV_CHECK_DONE 토스트", async () => {
    const { server } = renderApp(`${STUDY}/3`, { user: "admin" });
    await screen.findByRole("button", { name: /알림 \d+건 미읽음/ });
    await new Promise((r) => setTimeout(r, 120));
    server.notify("u-admin", "ENV_CHECK_DONE", null, "환경 점검 완료 — 실패 2 · 경고 1");
    const toast = await screen.findByRole("status");
    expect(toast.className).toContain("ev-env_check_done");
    fireEvent.click(within(toast).getByRole("button", { name: /환경 점검 완료/ }));
    expect(await screen.findByTestId("env-summary")).toBeTruthy();
  });
});
