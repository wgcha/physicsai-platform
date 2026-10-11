import { beforeEach, describe, expect, it } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { renderApp, STUDY } from "../test/render";
import { recordCalls } from "../test/recordCalls";
import { makeSteps } from "../mock/data";
import type { MockServer } from "../mock/server";
import type { Job } from "../api";
import { retryStartText } from "../components/JobRetryButton";

const MANAGE = "/p/p-cushion/s/s-cushion/manage";

/** j-mr(MODEL_REGISTER, 김연구)을 3번째 step에서 실패한 작업으로 바꾼다 */
function failModelRegister(s: MockServer) {
  const j = s.jobs.find((x) => x.id === "j-mr")!;
  Object.assign(j, {
    state: "FAILED",
    steps: makeSteps("MODEL_REGISTER", 2, null, { failedIdx: 2 }),
    failure_code: "LOG_PARSE_FAILED",
    failure_message: "로그 해석 실패",
  });
  // 실제 서버처럼 실패 작업의 current_step = 실패한 step
  const orig = s.p2.summaryExtra.bind(s.p2);
  s.p2.summaryExtra = (x: Job) => (x.id === "j-mr" ? { ...orig(x), current_step_key: "MR_PARSE_LOG", current_step_label: "학습 로그 해석" } : orig(x));
}

function dialog() {
  return screen.getByRole("dialog");
}

beforeEach(() => {
  try {
    localStorage.clear();
  } catch {
    /* 무시 */
  }
});

describe("V3-S1-3 재시도", () => {
  it("can_retry이고 Study가 사용 중이면 버튼, 확인 후 POST retry 1회·새 작업 표시", async () => {
    const { server } = renderApp(`${STUDY}/3`, { user: "power" }, failModelRegister);
    const card = await screen.findByRole("region", { name: "모델 등록" });
    const btn = await within(card).findByRole("button", { name: "재시도" });
    const calls = recordCalls(server);
    fireEvent.click(btn);
    const d = dialog();
    expect(within(d).getByRole("heading").textContent).toBe("작업 재시도");
    expect(d.textContent).toContain("‘모델 등록’을 다시 실행할까요?");
    expect(d.textContent).toContain("3. 학습 로그 해석부터 새 작업으로 대기열에 등록됩니다. 이전 작업 기록은 그대로 남습니다.");
    fireEvent.click(within(d).getByRole("button", { name: "재시도" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(calls.filter((c) => c === "POST /jobs/j-mr/retry")).toHaveLength(1);
    const nj = server.jobs.find((j) => j.retry_of_job_id === "j-mr")!;
    expect(nj.state).toBe("QUEUED");
    await waitFor(() => expect(within(card).queryByRole("button", { name: "재시도" })).toBeNull());
    expect(within(card).getByText("대기")).toBeTruthy();
  });

  it("Esc는 취소, 호출 없음", async () => {
    const { server } = renderApp(`${STUDY}/3`, { user: "power" }, failModelRegister);
    const card = await screen.findByRole("region", { name: "모델 등록" });
    fireEvent.click(await within(card).findByRole("button", { name: "재시도" }));
    const calls = recordCalls(server);
    fireEvent.keyDown(dialog(), { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(calls.some((c) => c.endsWith("/retry"))).toBe(false);
  });

  it("409 오류는 버튼 아래 문구", async () => {
    const { server } = renderApp(`${STUDY}/3`, { user: "power" }, failModelRegister);
    const card = await screen.findByRole("region", { name: "모델 등록" });
    fireEvent.click(await within(card).findByRole("button", { name: "재시도" }));
    // 같은 유형 활성 작업이 생기면 STUDY_JOB_BUSY
    server.createJob(server.studies[0], "MODEL_REGISTER", { model_path: "x" });
    fireEvent.click(within(dialog()).getByRole("button", { name: "재시도" }));
    expect((await within(card).findByRole("alert")).textContent).toContain("같은 종류의 작업이 이미 실행 중이거나 대기 중입니다.");
  });

  it("보관된 Study·권한 없음이면 버튼 없음", async () => {
    renderApp(`${STUDY}/3`, { user: "power" }, (s) => {
      failModelRegister(s);
      s.studies[0].status = "ARCHIVED";
    });
    const card = await screen.findByRole("region", { name: "모델 등록" });
    await within(card).findByText(/로그 해석 실패/);
    expect(within(card).queryByRole("button", { name: "재시도" })).toBeNull();
  });

  it("조회 사용자(general)는 can_retry=false라 버튼 없음", async () => {
    renderApp(`${STUDY}/3`, { user: "general" }, failModelRegister);
    const card = await screen.findByRole("region", { name: "모델 등록" });
    await within(card).findByText(/로그 해석 실패/);
    expect(within(card).queryByRole("button", { name: "재시도" })).toBeNull();
  });

  it("시작 지점: TD_SOLVE·PREDICT_VERIFY는 처음(1단계)", () => {
    const j = { job_type: "TD_SOLVE", steps: makeSteps("TD_SOLVE", 2, null, { failedIdx: 3 }), current_step_key: null } as unknown as Job;
    expect(retryStartText(j)).toBe("처음(1단계)");
    expect(retryStartText({ ...j, job_type: "PREDICT_VERIFY", steps: makeSteps("PREDICT_VERIFY", 2, null, { failedIdx: 2 }) } as Job)).toBe("처음(1단계)");
    const ds = { job_type: "DATASET_CREATE", steps: makeSteps("DATASET_CREATE", 2, null, { failedIdx: 2 }), current_step_key: null } as unknown as Job;
    expect(retryStartText(ds)).toBe("3. EDSPY_DATASET_TRAIN");
  });
});

describe("V3-S1-4 Study 관리 화면", () => {
  it("이름 변경 저장, 폴더 이름 안내", async () => {
    const { server } = renderApp(MANAGE, { user: "power" });
    const input = (await screen.findByLabelText(/표시 이름/)) as HTMLInputElement;
    expect(screen.getByText("폴더 이름 cushion_v1은 바뀌지 않습니다(표시 이름만 변경)")).toBeTruthy();
    fireEvent.change(input, { target: { value: "쿠션 v1 (정리)" } });
    fireEvent.click(screen.getByRole("button", { name: "저장" }));
    await screen.findByText("저장했습니다");
    expect(server.studies[0].title).toBe("쿠션 v1 (정리)");
  });

  it("VERSION_CONFLICT면 문구와 자동 재조회", async () => {
    const { server } = renderApp(MANAGE, { user: "power" });
    const input = (await screen.findByLabelText(/표시 이름/)) as HTMLInputElement;
    server.studies[0].title = "다른 사람이 바꾼 이름";
    server.studies[0].version++;
    fireEvent.change(input, { target: { value: "내 이름" } });
    fireEvent.click(screen.getByRole("button", { name: "저장" }));
    expect((await screen.findByRole("alert")).textContent).toBe("다른 사용자가 먼저 수정했습니다. 새로 고친 뒤 다시 시도하세요");
    await waitFor(() => expect(input.value).toBe("다른 사람이 바꾼 이름"));
  });

  it("보관 → 보관 해제 대화상자 문구·호출", async () => {
    const { server } = renderApp(MANAGE, { user: "power" });
    const calls = recordCalls(server);
    fireEvent.click(await screen.findByRole("button", { name: "보관" }));
    let d = dialog();
    expect(within(d).getByRole("heading").textContent).toBe("Study 보관");
    expect(d.textContent).toContain("‘쿠션 두께·리브 예측’ Study를 보관할까요?");
    expect(d.textContent).toContain("보관하면 새 작업을 실행할 수 없습니다(조회와 용량 정리는 가능). 파일은 그대로 남고, 나중에 보관 해제할 수 있습니다.");
    // 대기 중 작업(j-q1)이 있으면 서버 문구 그대로
    fireEvent.click(within(d).getByRole("button", { name: "보관" }));
    expect((await within(d).findByRole("alert")).textContent).toBe("대기 중이거나 실행 중인 작업이 있어 보관할 수 없습니다");
    server.jobs.forEach((j) => j.study_id === "s-cushion" && j.state === "QUEUED" && (j.state = "CANCELED"));
    fireEvent.click(within(d).getByRole("button", { name: "보관" }));
    await waitFor(() => expect(screen.getByTestId("study-status").textContent).toBe("보관"));
    expect(server.studies[0].status).toBe("ARCHIVED");
    fireEvent.click(screen.getByRole("button", { name: "보관 해제" }));
    d = dialog();
    expect(within(d).getByRole("heading").textContent).toBe("보관 해제");
    expect(d.textContent).toContain("‘쿠션 두께·리브 예측’ Study를 다시 사용 중으로 바꿀까요? 작업을 다시 실행할 수 있게 됩니다.");
    fireEvent.click(within(d).getByRole("button", { name: "보관 해제" }));
    await waitFor(() => expect(screen.getByTestId("study-status").textContent).toBe("사용 중"));
    expect(calls.filter((c) => c.startsWith("POST /studies/s-cushion/"))).toEqual([
      "POST /studies/s-cushion/archive",
      "POST /studies/s-cushion/archive",
      "POST /studies/s-cushion/unarchive",
    ]);
  });

  it("보관 해제: 폴더 없음 409 서버 문구", async () => {
    renderApp("/p/p-cushion/s/s-cushion-old/manage", { user: "power" }, (s) => s.manage.missingFolders.add("s-cushion-old"));
    fireEvent.click(await screen.findByRole("button", { name: "보관 해제" }));
    fireEvent.click(within(dialog()).getByRole("button", { name: "보관 해제" }));
    expect((await within(dialog()).findByRole("alert")).textContent).toBe("AI 루트에서 Study 폴더를 찾을 수 없습니다");
  });

  it("권한 없으면 버튼 대신 조회 전용", async () => {
    renderApp(MANAGE, { user: "general" });
    await screen.findByTestId("study-status");
    expect(screen.queryByRole("button", { name: "저장" })).toBeNull();
    expect(screen.queryByRole("button", { name: "보관" })).toBeNull();
    expect(screen.getAllByText(/조회 전용/).length).toBe(2);
  });

  it("Study 화면 → 관리 링크, 보관 Study 경고 상자의 보관 해제 링크(power만)", async () => {
    renderApp("/p/p-cushion/s/s-cushion-old/stage/3", { user: "power" });
    const warn = await screen.findByText(/보관된 Study입니다/);
    expect(within(warn).getByRole("link", { name: "보관 해제" }).getAttribute("href")).toBe("/p/p-cushion/s/s-cushion-old/manage");
    expect(screen.getByRole("link", { name: "Study 관리" })).toBeTruthy();
  });

  it("조회 사용자는 경고 상자에 보관 해제 링크 없음", async () => {
    renderApp("/p/p-cushion/s/s-cushion-old/stage/3", { user: "general" });
    const warn = await screen.findByText(/보관된 Study입니다/);
    expect(within(warn).queryByRole("link")).toBeNull();
  });
});

describe("V3-S1-4 Study 목록 필터·행 동작", () => {
  it("기본 사용 중, 보관·전체 탭과 기억", async () => {
    const { unmount } = renderApp("/p/p-cushion", { user: "power" });
    const group = await screen.findByRole("group", { name: "상태 필터" });
    expect(within(group).getByRole("button", { name: "사용 중" }).getAttribute("aria-pressed")).toBe("true");
    await screen.findByText("쿠션 두께·리브 예측");
    expect(screen.queryByText("쿠션 파일럿")).toBeNull();
    fireEvent.click(within(group).getByRole("button", { name: "보관" }));
    await screen.findByText("쿠션 파일럿");
    expect(screen.queryByText("쿠션 두께·리브 예측")).toBeNull();
    fireEvent.click(within(group).getByRole("button", { name: "전체" }));
    await screen.findByText("쿠션 두께·리브 예측");
    expect(screen.getByText("쿠션 파일럿")).toBeTruthy();
    unmount();
    renderApp("/p/p-cushion", { user: "power" });
    const g2 = await screen.findByRole("group", { name: "상태 필터" });
    expect(within(g2).getByRole("button", { name: "전체" }).getAttribute("aria-pressed")).toBe("true");
  });

  it("행의 관리 링크와 보관 버튼(사용 중·power만)", async () => {
    const { server } = renderApp("/p/p-cushion", { user: "power" }, (s) => {
      s.jobs.forEach((j) => j.study_id === "s-cushion" && j.state === "QUEUED" && (j.state = "CANCELED"));
    });
    const row = (await screen.findByText("쿠션 두께·리브 예측")).closest("tr")!;
    expect(within(row).getByRole("link", { name: "관리" }).getAttribute("href")).toBe("/p/p-cushion/s/s-cushion/manage");
    fireEvent.click(within(row).getByRole("button", { name: "보관" }));
    fireEvent.click(within(dialog()).getByRole("button", { name: "보관" }));
    await waitFor(() => expect(screen.queryByText("쿠션 두께·리브 예측")).toBeNull());
    expect(server.studies[0].status).toBe("ARCHIVED");
  });

  it("조회 사용자는 행 보관 버튼 없음", async () => {
    renderApp("/p/p-cushion", { user: "general" });
    const row = (await screen.findByText("쿠션 두께·리브 예측")).closest("tr")!;
    expect(within(row).getByRole("link", { name: "관리" })).toBeTruthy();
    expect(within(row).queryByRole("button", { name: "보관" })).toBeNull();
  });
});
