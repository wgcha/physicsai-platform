// V3-S16-3: ④ 단일 예측 실행 목록 — 하위 탭 2개·localStorage·기본 탭 규칙(진행 중 → 목록), 목록 열·필터·더 보기·폴링,
// 행 → ?job=, PredictRunView 입력·경로 카드·경로 복사·기존 결과 카드, 일괄 하위는 "← 일괄 예측 결과". 목 서버(mock/predictRuns.ts) 기준.
import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { renderApp, STUDY } from "../test/render";
import { baseJob, iso } from "../mock/data";
import type { MockServer } from "../mock/server";
import { SINGLE_TAB_KEY } from "../stages/stage4/history/SingleTabs";
import { valuesText } from "../stages/stage4/history/runListText";

const MODE_KEY = "physicsai.stage4.inputMode";
const tab = (name: string) => screen.findByRole("tab", { name }) as Promise<HTMLButtonElement>;
const table = () => screen.findByRole("table", { name: "단일 예측 실행 목록" });
const H = { predictRuns: "history" as const };

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

describe("V3-S16-3 하위 탭·기본 탭", () => {
  it("하위 탭 2개(새 예측 | 실행 목록), 진행 중이 없으면 새 예측, 선택은 localStorage에 기억", async () => {
    renderApp(`${STUDY}/4`, { user: "power" });
    expect((await tab("새 예측")).getAttribute("aria-selected")).toBe("true");
    expect(screen.getAllByRole("tab").map((t) => t.textContent)).toEqual(["새 예측", "실행 목록"]);
    expect(await screen.findByRole("region", { name: "템플릿" })).toBeTruthy();
    fireEvent.click(await tab("실행 목록"));
    expect(localStorage.getItem(SINGLE_TAB_KEY)).toBe("list");
    expect(await screen.findByRole("region", { name: "실행 목록" })).toBeTruthy();
  });

  it("기억한 탭 사용, 준비된 입력 방식에서도 같은 하위 탭", async () => {
    localStorage.setItem(SINGLE_TAB_KEY, "list");
    localStorage.setItem(MODE_KEY, "prepared");
    renderApp(`${STUDY}/4`, { user: "power" }, undefined);
    expect((await tab("실행 목록")).getAttribute("aria-selected")).toBe("true");
    fireEvent.click(await tab("새 예측"));
    expect(await screen.findByRole("region", { name: "준비된 입력 파일" })).toBeTruthy();
  });

  it("진행 중(QUEUED·RUNNING) 단일 예측이 있으면 기억한 탭보다 실행 목록", async () => {
    localStorage.setItem(SINGLE_TAB_KEY, "new");
    renderApp(`${STUDY}/4`, { user: "power", ...H });
    await waitFor(async () => expect((await tab("실행 목록")).getAttribute("aria-selected")).toBe("true"));
    expect(await table()).toBeTruthy();
  });

  it("localStorage가 막혀도 렌더(새 예측)", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    renderApp(`${STUDY}/4`, { user: "power" });
    expect((await tab("새 예측")).getAttribute("aria-selected")).toBe("true");
    fireEvent.click(await tab("실행 목록"));
    expect((await tab("실행 목록")).getAttribute("aria-selected")).toBe("true");
  });

  it("일괄 예측 방식에는 하위 탭이 없다(기존 탭 그대로)", async () => {
    localStorage.setItem(MODE_KEY, "batch");
    renderApp(`${STUDY}/4`, { user: "power" });
    expect(await screen.findByRole("tab", { name: /^새 일괄 예측/ })).toBeTruthy();
    expect(screen.queryByRole("tab", { name: "새 예측" })).toBeNull();
  });
});

describe("V3-S16-3 실행 목록", () => {
  it("열·값 앞 3개·응답·재시도 회차·실패, 현재 입력 방식(템플릿)이 기본 필터, 일괄 하위는 없음", async () => {
    localStorage.setItem(SINGLE_TAB_KEY, "list");
    renderApp(`${STUDY}/4`, { user: "power", batchDemo: "running", ...H });
    const t = await table();
    expect(within(t).getAllByRole("columnheader").map((c) => c.textContent)).toEqual(["시작", "입력 방식", "입력", "템플릿 / 입력 파일", "값", "응답", "상태", "소요"]);
    await waitFor(() => expect(within(t).getByTestId("run-j-hf2")).toBeTruthy());
    const retried = within(t).getByTestId("run-j-hf2");
    expect(retried.textContent).toContain("2회차");
    expect(retried.textContent).toContain("THK_TOP=0.6 · THK_FOAM=2.4 · E_FOAM=9.5 …");
    expect(retried.textContent).toMatch(/MaxStress [\d.]+ MPa/);
    expect(within(t).queryByTestId("run-j-hf1")).toBeNull(); // 재시도로 대체된 이전 시도 숨김
    expect(within(t).queryByTestId("run-j-hp1")).toBeNull(); // 필터 = 템플릿
    expect(t.textContent).not.toContain("DOE #");
    // 필터: 준비된 입력 → 그 행만
    fireEvent.click(screen.getByRole("button", { name: "준비된 입력" }));
    const t2 = await screen.findByRole("table", { name: "단일 예측 실행 목록" });
    await waitFor(() => expect(within(t2).getByTestId("run-j-hp1")).toBeTruthy());
    expect(within(t2).getByTestId("run-j-hp1").textContent).toContain("Face_Drop_0000.rad");
    expect(within(t2).queryByTestId("run-j-hf2")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "전체" }));
    const t3 = await screen.findByRole("table", { name: "단일 예측 실행 목록" });
    await waitFor(() => expect(within(t3).getByTestId("run-j-hf2")).toBeTruthy());
    expect(within(t3).getByTestId("run-j-hp1")).toBeTruthy();
    expect(t3.textContent).not.toContain("DOE #"); // 일괄 하위(batch_run)는 어느 필터에도 없다
  });

  it("빈 상태 문구", async () => {
    localStorage.setItem(SINGLE_TAB_KEY, "list");
    renderApp(`${STUDY}/4`, { user: "power" }, (s) => {
      s.jobs = s.jobs.filter((j) => !(j.study_id === "s-cushion" && j.job_type === "PREDICT"));
    });
    expect(await screen.findByText(/아직 실행한 예측이 없습니다/)).toBeTruthy();
  });

  it("더 보기: 커서로 다음 쪽(중복·누락 없음)", async () => {
    localStorage.setItem(SINGLE_TAB_KEY, "list");
    const { server } = renderApp(`${STUDY}/4`, { user: "power" }, (s) => addMany(s, 60));
    const t = await table();
    await waitFor(() => expect(within(t).getAllByRole("row").length).toBe(51)); // 머리 + 50
    fireEvent.click(screen.getByRole("button", { name: "더 보기" }));
    await waitFor(() => expect(within(t).getAllByRole("row").length).toBe(62)); // 머리 + 60 + 시드 1(j-pred)
    expect(screen.queryByRole("button", { name: "더 보기" })).toBeNull();
    const ids = within(t).getAllByRole("row").slice(1).map((r) => r.getAttribute("data-testid"));
    expect(new Set(ids).size).toBe(ids.length);
    expect(server.jobs.length).toBeGreaterThan(60);
  });

  it("진행 중 행이 있으면 폴링으로 상태가 바뀐다", async () => {
    localStorage.setItem(SINGLE_TAB_KEY, "list");
    const { server } = renderApp(`${STUDY}/4`, { user: "power", ...H });
    const t = await table();
    await waitFor(() => expect(within(t).getByTestId("run-j-hr").textContent).toContain("실행 중"));
    server.jobs.find((j) => j.id === "j-hr")!.state = "FAILED";
    server.jobs.find((j) => j.id === "j-hr")!.failure_code = "EXIT_NONZERO";
    await waitFor(() => expect(within(t).getByTestId("run-j-hr").textContent).toContain("실패"), { timeout: 3000 });
  });

  it("행 클릭 → ?job= 실행 결과(머리·입력·경로 카드·경로 복사·기존 결과 카드), ← 실행 목록", async () => {
    localStorage.setItem(SINGLE_TAB_KEY, "list");
    renderApp(`${STUDY}/4`, { user: "power", ...H });
    const t = await table();
    fireEvent.click(await within(t).findByTestId("run-j-h3"));
    expect(await screen.findByRole("region", { name: /^예측 · \d\d-\d\d \d\d:\d\d · params/ })).toBeTruthy();
    const inputs = await screen.findByRole("region", { name: "입력·경로" });
    const params = within(inputs).getByRole("table", { name: "입력 파라미터" });
    expect(within(params).getAllByRole("columnheader").map((c) => c.textContent)).toEqual(["파라미터", "입력값", "반영값", "범위 밖"]);
    expect(within(params).getByText("THK_TOP")).toBeTruthy();
    const dir = within(inputs).getByTestId("path-dir");
    expect(dir.textContent).toContain("04_predict\\j-h3");
    expect(within(dir).getByRole("button", { name: /경로 복사/ })).toBeTruthy();
    expect(within(inputs).getByTestId("path-result_dir")).toBeTruthy();
    // 기존 결과 카드(컨투어·응답 표)
    expect(await screen.findByTestId("contour-media")).toBeTruthy();
    expect(await screen.findByRole("table", { name: "응답값" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "← 실행 목록" }));
    expect(await table()).toBeTruthy();
    expect(localStorage.getItem(SINGLE_TAB_KEY)).toBe("list");
  });

  it("준비된 입력 행: 입력 경로 줄·starter, 파라미터 표 없음", async () => {
    localStorage.setItem(SINGLE_TAB_KEY, "list");
    renderApp(`${STUDY}/4?job=j-hp1`, { user: "power", ...H });
    const inputs = await screen.findByRole("region", { name: "입력·경로" });
    expect(inputs.textContent).toContain("E:/shared/AI_WORK/cushion_v1/00_inbox/case_A");
    expect(inputs.textContent).toContain("Face_Drop_0000.rad");
    expect(within(inputs).queryByRole("table", { name: "입력 파라미터" })).toBeNull();
    expect(within(inputs).queryByTestId("path-geom_dir")).toBeNull(); // prepared는 geom 없음
  });

  it("일괄 하위 작업은 입력·경로 카드 없이 기존 화면 + ← 일괄 예측 결과", async () => {
    const { server } = renderApp(`${STUDY}/4/batch/pb-2`, { user: "power" });
    await screen.findByRole("region", { name: "결과 표 — B-002" });
    const child = server.jobs.find((j) => j.job_type === "PREDICT" && (j.params as { batch_run?: unknown }).batch_run);
    expect(child).toBeTruthy();
    fireEvent.click(await screen.findByRole("button", { name: "DOE #7 선택" }));
    const panel = await screen.findByRole("region", { name: "DOE #7" });
    fireEvent.click(within(panel).getByRole("button", { name: "단일 예측으로 열기" }));
    expect(await screen.findByRole("region", { name: "일괄 예측 B-002 · DOE #7" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "← 일괄 예측 결과" })).toBeTruthy();
    expect(screen.queryByRole("region", { name: "입력·경로" })).toBeNull();
  });
});

describe("V3-S16-3 순수 문구", () => {
  it("valuesText: 앞 3개 + …", () => {
    expect(valuesText({ A: 1, B: 2.5, C: 3 })).toBe("A=1 · B=2.5 · C=3");
    expect(valuesText({ A: 1, B: 2, C: 3, D: 4 })).toBe("A=1 · B=2 · C=3 …");
    expect(valuesText({})).toBe("");
  });
});

function addMany(s: MockServer, n: number) {
  for (let i = 0; i < n; i++)
    s.jobs.push(
      baseJob({
        id: `j-m${String(i).padStart(3, "0")}`, study_id: "s-cushion", project_id: "p-cushion", study_title: "쿠션 두께·리브 예측", job_type: "PREDICT", state: "SUCCEEDED",
        created_at: iso(1000 + i), started_at: iso(999 + i), finished_at: iso(990 + i), params: { param_set_id: "ps-1", model_id: null, values: { THK_TOP: 0.5 }, value_source: "manual", source_run_key: null },
      }),
    );
}
