// V3-S14-3(phase3.md §19.3·§19.9): 메뉴 — 6버튼 순서·번호 배지 1~6·읽기용 이름("⑤ 결과분석"·"⑥ 최적화"), URL /stage/4·/stage/5 불변 + /stage/analysis,
// stage_label 표시 매핑(서버 값 ⑤ → 표시 ⑥, 서버 값 불변), 알림 링크 유지, 좁은 화면 스텝퍼 가로 스크롤 규칙 유지.
import { describe, expect, it } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { clearApiCache } from "../api";
import { openStatusDrawer, renderApp, STUDY } from "../test/render";
import { baseJob } from "../mock/data";
import { STAGES, stageCircled, stageMark, stageMarkOf, stageNo, stageTitle } from "../lib/format";
import shellCss from "../styles/shell.css?raw";

describe("S14 메뉴 6버튼 (V3-S14-3)", () => {
  it("표시 순서 ①~④ · ⑤ 결과분석(analysis) · ⑥ 최적화(내부 5): 번호·원 문자·읽기용 이름", () => {
    expect(STAGES.map((s) => s.path)).toEqual(["1", "2", "3", "4", "analysis", "5"]);
    expect(STAGES.map((s) => s.name)).toEqual(["학습데이터 생성", "데이터 정리", "데이터셋·모델", "예측", "결과분석", "최적화"]);
    expect(STAGES.map((s) => stageNo(s.path))).toEqual([1, 2, 3, 4, 5, 6]);
    expect(STAGES.map((s) => stageCircled(s.path))).toEqual(["①", "②", "③", "④", "⑤", "⑥"]);
    expect(stageTitle("analysis")).toBe("⑤ 결과분석");
    expect(stageTitle("5")).toBe("⑥ 최적화");
    expect(stageTitle("4")).toBe("④ 예측");
    // 내부 단계 번호(jobs.stage)는 불변: 결과분석은 작업이 없다(null)
    expect(STAGES.map((s) => s.n)).toEqual([1, 2, 3, 4, null, 5]);
    expect(stageMarkOf(5)).toBe("⑥");
    expect(stageMarkOf(4)).toBe("④");
  });

  it("스텝퍼: 링크 6개·URL(/stage/4, /stage/analysis, /stage/5)·배지 1~6·읽기용 이름, 결과분석에서 aria-current", async () => {
    renderApp(`${STUDY}/analysis`, { user: "power" });
    const stepper = await screen.findByRole("list", { name: "단계" });
    const links = within(stepper).getAllByRole("link");
    expect(links.map((a) => a.getAttribute("href"))).toEqual(["1", "2", "3", "4", "analysis", "5"].map((p) => `${STUDY}/${p}`));
    expect(links.map((a) => a.querySelector(".step-num")?.textContent)).toEqual(["1", "2", "3", "4", "5", "6"]);
    expect(within(stepper).getByRole("link", { name: /^⑤ 결과분석/ }).getAttribute("aria-current")).toBe("step");
    expect(within(stepper).getByRole("link", { name: /^⑥ 최적화/ })).toBeTruthy();
    expect(within(stepper).getByRole("link", { name: /^④ 예측/ }).hasAttribute("aria-current")).toBe(false);
    expect(links.filter((a) => a.hasAttribute("aria-current"))).toHaveLength(1);
    // 경로바 마지막 = "⑤ 결과분석"
    expect(within(screen.getByRole("navigation", { name: "경로" })).getByText("⑤ 결과분석")).toBeTruthy();
    // ⑥ 최적화를 누르면 /stage/5 화면(내부 5)
    fireEvent.click(within(stepper).getByRole("link", { name: /^⑥ 최적화/ }));
    await waitFor(() => expect(within(screen.getByRole("navigation", { name: "경로" })).getByText("⑥ 최적화")).toBeTruthy());
    expect(screen.queryByRole("region", { name: "응답 그래프" })).toBeNull();
  });

  it("URL 불변: /stage/4 = ④ 예측, /stage/5 = ⑥ 최적화, 알 수 없는 단계·analysis 하위 경로는 ③으로", async () => {
    const r1 = renderApp(`${STUDY}/4`, { user: "power" });
    expect(await screen.findByRole("region", { name: "입력 방식" })).toBeTruthy();
    expect(within(screen.getByRole("list", { name: "단계" })).getByRole("link", { name: /^④ 예측/ }).getAttribute("aria-current")).toBe("step");
    r1.unmount();
    const r2 = renderApp(`${STUDY}/9`, { user: "power" });
    const r2unmount = () => (r2.unmount(), clearApiCache());
    await screen.findByRole("region", { name: "데이터셋 생성" });
    r2unmount();
    renderApp(`${STUDY}/analysis/batch/pb-2`, { user: "power" });
    await screen.findByRole("region", { name: "데이터셋 생성" });
  });

  it("stageMark: OPTIMIZE·SURROGATE_OPT의 서버 값 ⑤ → 표시 ⑥, 나머지 불변(서버 값 자체는 안 바뀜)", () => {
    const j = (job_type: string, stage: number, stage_label: string | null) => ({ job_type, stage, stage_label }) as Parameters<typeof stageMark>[0];
    expect(stageMark(j("OPTIMIZE", 5, "⑤"))).toBe("⑥");
    expect(stageMark(j("SURROGATE_OPT", 5, "⑤"))).toBe("⑥");
    expect(stageMark(j("PREDICT", 4, "④"))).toBe("④");
    expect(stageMark(j("PREDICT_BATCH", 4, "④"))).toBe("④");
    expect(stageMark(j("TD_SOLVE", 1, "①-4"))).toBe("①-4");
    expect(stageMark(j("DATASET_CREATE", 3, "③-1"))).toBe("③-1");
    expect(stageMark(j("OPTIMIZE", 5, null))).toBe("⑥");
    expect(stageMark(j("PREDICT", 4, null))).toBe("④");
    expect(stageMark(j("STUDY_CLEANUP", 0, null))).toBe("0");
  });

  it("대기열 배지: 서버 stage_label ⑤(최적화)는 ⑥로 표시, 다른 작업은 그대로", async () => {
    const { server } = renderApp(`${STUDY}/3`, { user: "admin" }, (s) => {
      s.jobs.push(baseJob({ id: "j-qopt", study_id: "s-cushion", project_id: "p-cushion", study_title: "쿠션", job_type: "OPTIMIZE", state: "QUEUED", created_at: new Date(Date.now() - 60_000).toISOString(), params: {} }));
      s.queueOrder.set("j-qopt", ++s.queueSeq);
    });
    await openStatusDrawer();
    const q = await screen.findByRole("region", { name: "실행 대기열" });
    await waitFor(() => expect(within(q).getAllByTestId("queue-row").length).toBeGreaterThan(2));
    const badges = within(q).getAllByTestId("stage-badge");
    const opt = badges.find((b) => b.closest("[data-testid=queue-row]")?.textContent?.includes("최적화"))!;
    expect(opt.textContent).toBe("⑥");
    expect(opt.getAttribute("title")).toBe("6단계");
    expect(badges.map((b) => b.textContent)).toContain("③-5"); // j-q1 EVALUATE
    // 서버(목) 값은 그대로 ⑤
    const raw = server.handle("GET", "/queue", new URLSearchParams(), null, new Headers()).body as { queued: { id: string; stage_label: string }[] };
    expect(JSON.stringify(raw)).toContain('"stage_label":"⑤"');
  });

  it("알림 링크 유지: PREDICT_BATCH_DONE → ④ 배치 결과(/stage/4/batch/…), SURROGATE_OPT_DONE → ⑥(/stage/5)", async () => {
    const { server } = renderApp(`${STUDY}/analysis`, { user: "power" }, (s) => {
      s.jobs.push(baseJob({ id: "j-so", study_id: "s-cushion", project_id: "p-cushion", study_title: "쿠션", job_type: "SURROGATE_OPT", state: "SUCCEEDED", params: {} }));
    });
    await screen.findByRole("list", { name: "단계" });
    server.notify("u-power", "PREDICT_BATCH_DONE", server.jobs.find((j) => j.id === server.batches.find((b) => b.batch_no === 2)!.job_id)!, "일괄 예측 B-002 완료");
    fireEvent.click(await screen.findByRole("button", { name: /알림 [1-9]\d*건 미읽음/ }));
    fireEvent.click(await screen.findByText("일괄 예측 B-002 완료"));
    const path = () => within(screen.getByRole("navigation", { name: "경로" }));
    await waitFor(() => expect(path().getByText("일괄 예측")).toBeTruthy()); // ④ 배치 결과 화면(⑤ 화면에는 없는 경로)
    expect(path().getByText("④ 예측")).toBeTruthy();
    server.notify("u-power", "SURROGATE_OPT_DONE" as never, server.jobs.find((j) => j.id === "j-so")!, "내장 최적화 SO-001 완료");
    fireEvent.click(await screen.findByRole("button", { name: /알림 [1-9]\d*건 미읽음/ }));
    fireEvent.click(await screen.findByText("내장 최적화 SO-001 완료"));
    await waitFor(() => expect(within(screen.getByRole("navigation", { name: "경로" })).getByText("⑥ 최적화")).toBeTruthy());
  });

  it("CSS: 6등분 격자와 좁은 화면 규칙(최소 폭 170, 스텝퍼 안에서만 가로 스크롤)이 유지된다", () => {
    expect(shellCss).toMatch(/\.stepper\s*\{[^}]*repeat\(6,\s*minmax\(0,\s*1fr\)\)/);
    const media = shellCss.match(/@media \(max-width: (\d+)px\)\s*\{\s*\.stepper\s*\{([^}]*)\}/);
    expect(media).toBeTruthy();
    expect(media![2]).toMatch(/repeat\(6,\s*minmax\(170px,\s*1fr\)\)/);
    expect(media![2]).toMatch(/overflow-x:\s*auto/);
  });
});
