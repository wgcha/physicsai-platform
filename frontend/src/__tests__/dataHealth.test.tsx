// data-health.md V-DH-14(화면)·V-DH-19(화면 부분): 버튼·표·[추천만]·기본 선택(제외 필수만)·[추천 항목 선택]·제출 params·입력 변경 시 초기화·한국어·표 최대 높이.
import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import css from "../styles/stages.css?raw";
import { renderApp, STUDY } from "../test/render";
import { dataHealthReport } from "../mock/dataHealth";
import { CONFIRM_KEEP, clearSelection, initialSelection, keptRequired, reasonCell, selectRecommended, sortRuns, submitExtras, toggle, visibleRuns } from "../stages/stage3/health/healthModel";

afterEach(() => vi.unstubAllGlobals());

const R1 = "run_001/cushion_001.h3d";
const R2 = "run_002/cushion_002.h3d";

async function runHealth(opts: Parameters<typeof renderApp>[1] = { user: "power" }) {
  const utils = renderApp(`${STUDY}/3`, opts);
  const btn = (await screen.findByRole("button", { name: "데이터 점검" })) as HTMLButtonElement;
  expect(screen.queryByRole("table", { name: "데이터 점검 표" })).toBeNull(); // 점검 전에는 결과 카드 없음
  await waitFor(() => expect(btn.disabled).toBe(false));
  fireEvent.click(btn);
  await waitFor(() => expect(utils.server.jobs.some((j) => j.job_type === "DATA_HEALTH" && j.state === "QUEUED")).toBe(true));
  utils.server.finishAll();
  const table = await screen.findByRole("table", { name: "데이터 점검 표" }, { timeout: 4000 });
  return { ...utils, table };
}
const checked = (table: HTMLElement) =>
  within(table).getAllByRole("checkbox").filter((c) => (c as HTMLInputElement).checked && /^제외 /.test(c.getAttribute("aria-label") ?? "")).map((c) => c.getAttribute("aria-label")!.slice(3));

describe("healthModel — 순수 함수", () => {
  const runs = dataHealthReport().runs;
  it("기본 선택 = 제외 필수만, 통계 추천은 선택 없음", () => {
    expect([...initialSelection(runs)].sort()).toEqual([R1, R2]);
  });
  it("추천 선택은 더하고, 선택 해제는 제외 필수를 남긴다", () => {
    const rec = selectRecommended(initialSelection(runs), runs);
    expect(rec.size).toBe(5);
    expect([...clearSelection(rec, runs)].sort()).toEqual([R1, R2]);
  });
  it("정렬: 제외 필수 맨 위, 점수 내림차순. 필터는 선택 행을 숨기지 않는다", () => {
    expect(sortRuns(runs).slice(0, 3).map((r) => r.file_rel)).toEqual([R1, R2, "run_003/cushion_003.h3d"]);
    expect(visibleRuns(runs, true, new Set()).length).toBe(5);
    expect(visibleRuns(runs, true, new Set(["run_009/cushion_009.h3d"])).length).toBe(6);
    expect(visibleRuns(runs, false, new Set()).length).toBe(12);
  });
  it("제출 params: exclude_files 정렬·health_job_id, 해제된 제외 필수는 kept_required", () => {
    const sel = toggle(selectRecommended(initialSelection(runs), runs), R2, false);
    expect(keptRequired(runs, sel)).toEqual([R2]);
    const p = submitExtras({ ...dataHealthReport() }, sel, "j-1");
    expect(p.health_job_id).toBe("j-1");
    expect(p.exclude_files).toEqual([...sel].sort());
    expect(p.kept_required).toEqual([R2]);
    expect("kept_required" in submitExtras(dataHealthReport(), initialSelection(runs), "j-1")).toBe(false);
  });
  it("사유 칸: 첫 2개 + 외 n, 코드는 툴팁", () => {
    const rs = [1, 2, 3].map((i) => ({ code: `C${i}`, message: `사유${i}` }));
    expect(reasonCell(rs)).toEqual({ text: "사유1 · 사유2 외 1", tip: "C1: 사유1\nC2: 사유2\nC3: 사유3" });
  });
});

describe("③-1 데이터 점검 화면 (V-DH-14·19)", () => {
  it("점검 전에는 결과 카드가 없고, 점검 후 표·머리 줄·경고가 한국어로 보인다", async () => {
    const { table } = await runHealth();
    const heads = within(table).getAllByRole("columnheader").map((h) => h.textContent);
    expect(heads).toEqual(["선택", "run", "추천", "점수", "사유", "종료", "프레임", "마지막 시각", "에너지 오차%", "추가 질량", "최대 견고 z (지표)", "3σ"]);
    const head = screen.getByTestId("dh-head").textContent!;
    expect(head).toContain("추천 5");
    expect(head).toContain("견고 z 3.5 / kNN 3.5 / 3σ 3");
    expect(screen.getByTestId("dh-ref").textContent).toBe("기준 프레임 22 · 종료 0.012 s · 출처: 최빈");
    expect(screen.getByTestId("dh-frames-unknown").textContent).toBe("프레임 확인 불가 2건");
    expect(screen.getByText("①-6 run 응답 추출을 먼저 실행하면 응답 지표를 함께 봅니다")).toBeTruthy();
    expect(screen.getByTestId("dh-status").textContent).toContain("추천 5 / 12");
  });

  it("[추천만] 기본 켬: 추천 5행, 제외 필수가 맨 위·배지, 사유·점수 표시, 끄면 전체 12행", async () => {
    const { table } = await runHealth();
    const body = within(table).getAllByRole("row").slice(1);
    expect(body.length).toBe(5);
    expect(within(body[0]).getByText("제외 필수")).toBeTruthy();
    expect(body[0].textContent).toContain(R1);
    expect(body[0].textContent).toContain("프레임 수 18 — 기준 22와 다름");
    expect(body[0].textContent).toContain("100.0");
    expect(body[2].textContent).toContain("정상 종료 아님 — 오류 종료");
    fireEvent.click(screen.getByRole("checkbox", { name: "추천만" }));
    expect(within(table).getAllByRole("row").length - 1).toBe(12);
    const sigma = within(table).getAllByRole("row").find((r) => r.textContent?.includes("run_006"))!;
    expect(within(sigma).getByText("3σ만")).toBeTruthy();
    const unknown = within(table).getAllByRole("row").find((r) => r.textContent?.includes("run_007"))!;
    expect(within(unknown).getByText("확인 불가")).toBeTruthy();
  });

  it("기본 선택은 제외 필수 2개뿐 — 추천은 선택되지 않음, [추천 항목 선택]·[선택 해제]", async () => {
    const { table } = await runHealth();
    expect(checked(table).sort()).toEqual([R1, R2]);
    expect(screen.getByTestId("dh-count").textContent).toBe("제외 2개 — 데이터셋 생성에 반영");
    fireEvent.click(screen.getByRole("button", { name: "추천 항목 선택" }));
    expect(checked(table).length).toBe(5);
    fireEvent.click(screen.getByRole("button", { name: "선택 해제" }));
    expect(checked(table).sort()).toEqual([R1, R2]);
  });

  it("제외 필수 해제: 확인 대화상자 — 취소는 유지, 포함하면 경고 아이콘", async () => {
    const { table } = await runHealth();
    fireEvent.click(within(table).getByRole("checkbox", { name: `제외 ${R1}` }));
    let dlg = await screen.findByRole("dialog");
    expect(dlg.textContent).toContain(CONFIRM_KEEP);
    fireEvent.click(within(dlg).getByRole("button", { name: "취소" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(checked(table)).toContain(R1);
    fireEvent.click(within(table).getByRole("checkbox", { name: `제외 ${R1}` }));
    dlg = await screen.findByRole("dialog");
    fireEvent.click(within(dlg).getByRole("button", { name: "포함" }));
    expect(checked(table)).toEqual([R2]);
    expect(within(screen.getByTestId(`dh-row-${R1}`)).getByLabelText("경고")).toBeTruthy();
  });

  it("추천 행(통계)은 확인 없이 선택·해제된다", async () => {
    const { table } = await runHealth();
    const r3 = "run_003/cushion_003.h3d";
    fireEvent.click(within(table).getByRole("checkbox", { name: `제외 ${r3}` }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(checked(table)).toContain(r3);
  });

  it("행 펼침: 지표 전부(값·z·견고 z·kNN 점수)", async () => {
    const { table } = await runHealth();
    fireEvent.click(within(table).getByRole("button", { name: /지표 펼치기 run_004/ }));
    const d = await screen.findByRole("table", { name: "지표 run_004/cushion_004.h3d" });
    expect(d.textContent).toContain("쿠션 부피");
    expect(d.textContent).toContain("5.2");
  });

  it("데이터셋 생성 제출 params에 exclude_files·health_job_id·kept_required, 목록 '제외 n'", async () => {
    const { server, table } = await runHealth();
    fireEvent.click(within(table).getByRole("checkbox", { name: "제외 run_003/cushion_003.h3d" }));
    fireEvent.click(within(table).getByRole("checkbox", { name: `제외 ${R2}` }));
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "포함" }));
    const create = within(screen.getByRole("region", { name: "데이터셋 생성" })).getByRole("button", { name: "데이터셋 생성" });
    await waitFor(() => expect((create as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(create);
    await waitFor(() => expect(server.jobs.some((j) => j.job_type === "DATASET_CREATE" && j.state === "QUEUED")).toBe(true));
    const j = server.jobs.find((x) => x.job_type === "DATASET_CREATE" && x.state === "QUEUED")!;
    const hj = server.jobs.find((x) => x.job_type === "DATA_HEALTH")!;
    expect(j.params).toMatchObject({ health_job_id: hj.id, exclude_files: [R1, "run_003/cushion_003.h3d"], kept_required: [R2] });
    server.finishAll();
    await waitFor(() => expect(server.datasets[0].excluded_count).toBe(2));
    expect(await screen.findByText("제외 2")).toBeTruthy();
  });

  it("입력을 바꾸면 이전 점검은 '다른 입력', 선택 초기화·결과 카드 숨김", async () => {
    const { table } = await runHealth();
    expect(table).toBeTruthy();
    const card = screen.getByRole("region", { name: "데이터셋 생성" });
    fireEvent.click(within(card).getByRole("button", { name: "다른 폴더 지정" }));
    await waitFor(() => expect(screen.queryByRole("table", { name: "데이터 점검 표" })).toBeNull());
    expect(screen.getByTestId("dh-status").textContent).toBe("최근 점검은 다른 입력입니다");
    // 다시 돌아오면 같은 점검이 복원되고 선택은 기본(제외 필수만)
    fireEvent.click(within(card).getByRole("button", { name: "② 큐레이션 결과 사용" }));
    const t2 = await screen.findByRole("table", { name: "데이터 점검 표" });
    expect(checked(t2).sort()).toEqual([R1, R2]);
  });

  it("표는 최대 높이 안에서만 스크롤(1440 한 화면)", async () => {
    await runHealth();
    expect(document.querySelector(".dh-scroll")).toBeTruthy();
    expect(css).toMatch(/\.dh-scroll\s*\{[^}]*max-height:\s*\d+px;[^}]*overflow:\s*auto/);
  });

  it("조회 전용 사용자는 점검 버튼 없음", async () => {
    renderApp(`${STUDY}/3`, { user: "general" });
    await screen.findByRole("region", { name: "데이터셋 생성" });
    expect(screen.queryByRole("button", { name: "데이터 점검" })).toBeNull();
  });
});
