// geometry-engine.md §7.6·§8: ④ 일괄 예측 결과 표의 생성 실패 행 = gen_category 배지(+ 한국어 사유), 작업 목록 native step 이름(STEP_LABELS_NATIVE).
import { afterEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import { openStatusDrawer, renderApp, STUDY } from "../test/render";
import { retryStartText } from "../components/JobRetryButton";
import type { Job } from "../api";

describe("gen_category 배지(§6.5)", () => {
  afterEach(() => vi.restoreAllMocks());

  it("GEOM_* 생성 실패 행: category 배지 + 사유(코드 대신), 그 밖의 실패는 기존 코드 표시", async () => {
    renderApp(`${STUDY}/4/batch/pb-2`, { user: "power" }, (s) => {
      const b = s.batches.find((x) => x.id === "pb-2")!;
      Object.assign(b.runs[11], { gen_code: "GEOM_INTERFERENCE", gen_message: "간섭 — 바디 간 0.004 mm < 0.01 mm" });
    });
    await screen.findByRole("region", { name: "결과 표 — B-002" });
    const row = await screen.findByTestId("row-12");
    await waitFor(() => expect(within(row).getByTestId("gen-category-12").textContent).toBe("간섭"));
    expect(within(row).getByTestId("gen-category-12").className).toBe("pill bad");
    expect(row.textContent).toContain("간섭 — 바디 간 0.004 mm");
    expect(row.textContent).not.toContain("GEOM_INTERFERENCE");
    expect(within(screen.getByTestId("row-5")).queryByTestId("gen-category-5")).toBeNull();
  });
});

describe("작업 목록 native step 이름(§7.3)", () => {
  afterEach(() => vi.restoreAllMocks());

  it("PARAM_SET_NATIVE 실행 중: 서버 current_step_label이 없으면 대기열 step 이름을 표(NP_*·BL_MAP)로 채운다", async () => {
    const { server } = renderApp(`${STUDY}/4`, { user: "power" }, (s) => {
      const orig = s.p2.summaryExtra.bind(s.p2);
      s.p2.summaryExtra = (x: Job) => (x.job_type === "PARAM_SET_NATIVE" ? { ...orig(x), current_step_key: "BL_MAP", current_step_label: null } : orig(x));
    });
    const st = server.studies.find((x) => x.id === "s-cushion")!;
    const { createJobFor } = await import("../mock/jobs");
    const r = createJobFor(server, st, "PARAM_SET_NATIVE", { mode: "remap", param_set_id: "ps-1" });
    const id = (r.body as Job).id;
    for (const j of server.jobs) if (j.state === "RUNNING" && j.lane === "SLOT") j.state = "SUCCEEDED";
    const nj = server.jobs.find((j) => j.id === id)!;
    Object.assign(nj, { state: "RUNNING", started_at: new Date().toISOString() });
    nj.steps[3].state = "RUNNING";
    const drawer = await openStatusDrawer();
    await waitFor(() => expect(drawer.textContent).toContain("형상 준비(native)"));
    await waitFor(() => expect(drawer.textContent).toContain("baseline 변수 매칭"));
  });

  it("재시도 시작 지점: 현재가 아닌 step도 표시명(native 덮어쓰기)", () => {
    const step = (no: number, key: string, state: string) => ({ step_no: no, step_key: key, kind: "LOCAL", state });
    const job = {
      job_type: "TD_DOE_GEN", params: { engine: "native" }, current_step_key: null, current_step_label: null,
      steps: [step(1, "DG_PREP", "SUCCEEDED"), step(2, "HST_GEN_RADIOSS", "FAILED"), step(3, "DG_SCAN", "PENDING")],
    } as unknown as Job;
    expect(retryStartText(job)).toBe("2. 형상 모핑 입력 생성");
    const nat = { ...job, job_type: "PARAM_SET_NATIVE", params: {}, steps: [step(1, "NP_PREP", "SUCCEEDED"), step(2, "NP_EXTRACT", "SUCCEEDED"), step(3, "NP_TAG", "FAILED")] } as unknown as Job;
    expect(retryStartText(nat)).toBe("3. 경계 노드 분류");
  });
});
