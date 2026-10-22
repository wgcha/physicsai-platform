// V3-S16-18: V2 화면 — 진입 버튼·기능 꺼짐·기존 검증 링크, 새 검증 카드(조립 라디오·경로 확인 요약·고급·preview problems·body),
// 상세(진행 단계·탭 4개·취소/다시 실행), 목록·폴링. 목 서버(mock/femVerify.ts) 기준.
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { renderApp, STUDY } from "../test/render";

const O = { user: "power" as const, hpcConfigured: true, femVerify: "demo" as const };
afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

describe("V3-S16-18 진입 버튼", () => {
  it("④ 단일 예측: 결과가 있으면 FEM 검증 버튼 → 새 검증 카드(출처 줄)", async () => {
    renderApp(`${STUDY}/4`, O); // 데모의 동반 PREDICT(진행 중)는 최신 작업으로 잡히지 않는다
    await screen.findByRole("tab", { name: "실행 목록" });
    await waitFor(() => expect(screen.getByRole("tab", { name: "실행 목록" }).getAttribute("aria-selected")).toBe("true")); // 동반 예측 진행 중 → 기본은 목록
    fireEvent.click(screen.getByRole("tab", { name: "새 예측" }));
    await waitFor(() => expect((screen.getByRole("button", { name: "FEM 검증" }) as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByRole("button", { name: "FEM 검증" }));
    const card = await screen.findByRole("region", { name: "새 FEM 검증" });
    expect(await within(card).findByTestId("fv-source")).toBeTruthy();
    expect(within(card).getByTestId("assembly-picker")).toBeTruthy();
  });

  it("해석 연결이 없으면 버튼 비활성 + 툴팁·회색 안내", async () => {
    renderApp(`${STUDY}/4`, { user: "power", femVerify: "demo" });
    const btn = (await screen.findByRole("button", { name: "FEM 검증" })) as HTMLButtonElement;
    await waitFor(() => expect(btn.title).toBe("해석 연결 안 됨(관리자 설정 필요)"));
    expect(btn.disabled).toBe(true);
  });

  it("조회 전용(general)에는 버튼이 없다", async () => {
    renderApp(`${STUDY}/4`, { ...O, user: "general" });
    await screen.findByRole("region", { name: "템플릿" });
    expect(screen.queryByRole("button", { name: "FEM 검증" })).toBeNull();
  });

  it("④ 일괄 예측: 고른 DOE에 기존 검증이 있으면 회색 링크 'FV-001 · 완료 · 최대 오차 …'", async () => {
    renderApp(`${STUDY}/4/batch/pb-2`, O);
    fireEvent.click(await screen.findByTestId("row-7"));
    const link = await screen.findByTestId("fem-existing", {}, { timeout: 3000 });
    expect(link.textContent).toMatch(/^FV-001 · 완료 · 최대 오차 \d+\.\d%$/);
    expect(link.querySelector("a")!.getAttribute("href")).toContain("/stage/4/verify/fv-1");
  });
});

describe("V3-S16-18 새 검증 카드", () => {
  const NEW = `${STUDY}/4/verify?new=1&kind=predict_job&job_id=j-pred`;

  it("조립 원본 라디오: 예측 입력 그대로(조립 입력일 때만)·① DOE·직접 지정, 기본 preview", async () => {
    const { server } = renderApp(NEW, O);
    const card = await screen.findByRole("region", { name: "새 FEM 검증" });
    const picker = await within(card).findByTestId("assembly-picker");
    const radios = within(picker).getAllByRole("radio") as HTMLInputElement[];
    expect(radios).toHaveLength(3);
    expect(within(picker).getByLabelText("① DOE 선택")).toBeTruthy();
    expect(server.fems.length).toBe(3); // preview는 저장하지 않는다
  });

  it("직접 지정: 경로 확인 → 요약 한 줄, starter 2개면 문제 표시 + 실행 비활성", async () => {
    renderApp(NEW, O);
    const card = await screen.findByRole("region", { name: "새 FEM 검증" });
    const picker = await within(card).findByTestId("assembly-picker");
    fireEvent.click(within(picker).getAllByRole("radio")[2]);
    const input = await within(picker).findByLabelText("조립 원본 경로");
    fireEvent.change(input, { target: { value: "E:\\shared\\AI_WORK\\cushion\\00_inbox\\two_starters" } });
    fireEvent.click(within(picker).getByRole("button", { name: "확인" }));
    const sum = await within(picker).findByTestId("assembly-summary");
    expect(sum.textContent).toContain("starter");
    const run = within(card).getByRole("button", { name: /FEM 검증 실행/ }) as HTMLButtonElement;
    expect(run.disabled).toBe(true);
  });

  it("SPDM 경로는 확인 통과, 실행 body는 predict_job + custom 조립 + 기본값 null", async () => {
    const { server } = renderApp(NEW, O);
    const bodies: Record<string, unknown>[] = [];
    const orig = server.handle.bind(server);
    server.handle = (m, p, q, b, h) => {
      if (m === "POST" && p.endsWith("/fem-verifications")) bodies.push(b as Record<string, unknown>);
      return orig(m, p, q, b, h);
    };
    const card = await screen.findByRole("region", { name: "새 FEM 검증" });
    const picker = await within(card).findByTestId("assembly-picker");
    fireEvent.click(within(picker).getAllByRole("radio")[2]);
    fireEvent.change(await within(picker).findByLabelText("조립 원본 경로"), { target: { value: "S:\\SPDM\\cushion\\assem_v7" } });
    fireEvent.click(within(picker).getByRole("button", { name: "확인" }));
    await within(picker).findByTestId("assembly-summary");
    const run = within(card).getByRole("button", { name: /FEM 검증 실행/ }) as HTMLButtonElement;
    await waitFor(() => expect(run.disabled).toBe(false));
    fireEvent.click(run);
    await screen.findByRole("region", { name: /^FV-004/ }, { timeout: 3000 });
    expect(bodies.length).toBeGreaterThan(0);
    const b = bodies[0] as { source: { kind: string }; assembly: { kind: string; path: string }; display: unknown; hpc: unknown };
    expect(b.source.kind).toBe("predict_job");
    expect(b.assembly).toEqual({ kind: "custom", path: "S:\\SPDM\\cushion\\assem_v7" });
    expect(b.display).toBeNull();
    expect(b.hpc).toBeNull();
  });

  it("고급(접힘): FEM 결과 이름·격리 부품·범례·CPU 수 입력란", async () => {
    renderApp(NEW, O);
    const card = await screen.findByRole("region", { name: "새 FEM 검증" });
    fireEvent.click(await within(card).findByText("고급"));
    expect(within(card).getByLabelText("FEM 결과 이름")).toBeTruthy();
    expect(within(card).getByLabelText("격리 부품")).toBeTruthy();
    expect(within(card).getByLabelText("CPU 수")).toBeTruthy();
    fireEvent.change(within(card).getByLabelText("CPU 수"), { target: { value: "abc" } });
    expect((within(card).getByRole("button", { name: /FEM 검증 실행/ }) as HTMLButtonElement).disabled).toBe(true);
  });
});

describe("V3-S16-18 상세", () => {
  it("완료 검증(FV-001): 머리·4단 진행·탭 4개·응답 오차표", async () => {
    renderApp(`${STUDY}/4/verify/fv-1`, O);
    const head = await screen.findByRole("region", { name: /^FV-001/ });
    expect(within(head).getByTestId("fv-status").textContent).toBe("완료");
    await waitFor(() => expect(screen.getAllByText("FV-001").length).toBeGreaterThan(0)); // 빵부스러기
    const stages = within(head).getByRole("list", { name: "진행 단계" });
    expect(within(stages).getAllByRole("listitem")).toHaveLength(4); // 동반 예측 없음 → 0단 없음
    expect(screen.getAllByRole("tab").map((t) => t.textContent)).toEqual(["응답", "커브", "컨투어", "입력·경로"]);
    expect(await screen.findByRole("table", { name: "FEM 응답 비교" })).toBeTruthy();
    expect(screen.getByTestId("fv-max-diff").textContent).toMatch(/\d+\.\d%/);
  });

  it("탭: 커브·컨투어(예측|FEM 나란히)·입력·경로(복사)", async () => {
    renderApp(`${STUDY}/4/verify/fv-1`, O);
    await screen.findByRole("table", { name: "FEM 응답 비교" });
    fireEvent.click(screen.getByRole("tab", { name: "커브" }));
    expect(await screen.findByTestId("fv-curves", {}, { timeout: 3000 })).toBeTruthy();
    fireEvent.click(screen.getByRole("tab", { name: "컨투어" }));
    const c = await screen.findByTestId("fv-contours");
    expect(within(c).getByTestId("fv-side-예측")).toBeTruthy();
    expect(within(c).getByTestId("fv-side-FEM")).toBeTruthy();
    fireEvent.click(screen.getByRole("tab", { name: "입력·경로" }));
    const paths = await screen.findByTestId("fv-paths");
    expect(within(paths).getAllByRole("button", { name: /경로 복사/ }).length).toBeGreaterThan(0);
  });

  it("동반 예측 대기(FV-003): 0단 '예측 실행 중'이 붙고 취소 → 취소됨", async () => {
    renderApp(`${STUDY}/4/verify/fv-3`, O);
    const head = await screen.findByRole("region", { name: /^FV-003/ });
    await waitFor(() => expect(within(head).getAllByRole("listitem")).toHaveLength(5));
    expect(within(head).getByTestId("fv-stage-predict")).toBeTruthy();
    fireEvent.click(within(head).getByRole("button", { name: "취소" }));
    const dlg = await screen.findByRole("dialog");
    fireEvent.click(within(dlg).getByRole("button", { name: "검증 취소" }));
    await waitFor(() => expect(within(head).getByTestId("fv-status").textContent).toBe("취소됨"), { timeout: 3000 });
  });

  it("실패(FV-002): 실패 문구 + 다시 실행 → 진행 중", async () => {
    renderApp(`${STUDY}/4/verify/fv-2`, O);
    const head = await screen.findByRole("region", { name: /^FV-002/ });
    expect((await within(head).findByTestId("fv-failure")).textContent).toContain("ASSEM_STARTER_COUNT");
    fireEvent.click(within(head).getByRole("button", { name: "다시 실행" }));
    await waitFor(() => expect(within(head).getByTestId("fv-status").textContent).not.toBe("실패"), { timeout: 3000 });
  });
});

describe("V3-S16-18 목록", () => {
  it("표 7열·행 3개, 행 클릭 → 상세, 진행 중이면 폴링", async () => {
    const { server } = renderApp(`${STUDY}/4/verify`, O);
    const table = await screen.findByRole("table", { name: "FEM 검증 목록" });
    expect(within(table).getAllByRole("columnheader").map((h) => h.textContent)).toEqual(["FV #", "출처", "설계점", "상태", "최대 오차%", "시작", "등록자"]);
    expect(within(table).getAllByRole("row")).toHaveLength(4);
    expect(within(table).getByTestId("fv-FV-001").textContent).toContain("완료");
    // 폴링: 대기 중인 FV-003이 있으니 서버 갱신이 화면에 반영된다
    act(() => server.tick());
    fireEvent.click(within(table).getByTestId("fv-FV-001"));
    expect(await screen.findByRole("region", { name: /^FV-001/ })).toBeTruthy();
  });

  it("잘못된 새 검증 질의는 안내만", async () => {
    renderApp(`${STUDY}/4/verify?new=1&kind=nope`, O);
    expect(await screen.findByText(/검증 대상이 올바르지 않습니다/)).toBeTruthy();
  });

  it("④ 입력 방식 카드에 'FEM 검증 목록' 링크", async () => {
    renderApp(`${STUDY}/4`, O);
    const link = await screen.findByTestId("fv-list-link");
    expect(link.getAttribute("href")).toContain("/stage/4/verify");
  });
});

describe("V3-S16-18 ⑤·⑥ 진입", () => {
  it("⑤ 결과분석: 예측 출처 표에서 행을 골라야 FEM 검증 버튼(batch_run 질의)", async () => {
    renderApp(`${STUDY}/analysis?source=batch&id=pb-2`, O);
    const row = await screen.findByTestId("row-3");
    const card = row.closest("section") as HTMLElement;
    expect(within(card).queryByRole("button", { name: "FEM 검증" })).toBeNull();
    fireEvent.click(row);
    const btn = (await within(card).findByRole("button", { name: "FEM 검증" })) as HTMLButtonElement;
    await waitFor(() => expect(btn.disabled).toBe(false));
    fireEvent.click(btn);
    expect(await screen.findByRole("region", { name: "새 FEM 검증" })).toBeTruthy();
  });

  it("⑥ 최적화 결과: 최적안·마무리 컨투어·검증 run 행에 FEM 검증 버튼, 안내 문구", async () => {
    renderApp(`${STUDY}/5/surrogate/so-1`, O);
    const best = await screen.findByRole("region", { name: "최적안 — 기존안 대비" });
    expect(within(best).getByText(/FEM 검증 버튼으로 조립 상태 해석과 비교/)).toBeTruthy();
    expect(within(best).getByRole("button", { name: "FEM 검증" })).toBeTruthy();
    const cmp = await screen.findByRole("region", { name: /컨투어 비교/ });
    expect(within(cmp).getByRole("button", { name: "FEM 검증" })).toBeTruthy();
    const runs = screen.getByRole("table", { name: "검증 run" });
    expect(within(runs).getAllByRole("button", { name: "FEM 검증" }).length).toBeGreaterThan(0);
  });
});

describe("V3-S16-18 알림 링크·SCX", () => {
  it("FEM_VERIFY_DONE 알림 → 그 검증 상세로 이동", async () => {
    const { server } = renderApp(`${STUDY}/3`, O);
    await screen.findByRole("button", { name: /알림 \d+건 미읽음/ });
    await new Promise((r) => setTimeout(r, 120));
    const job = server.jobs.find((j) => j.id === "j-fv1")!;
    server.notify("u-power", "FEM_VERIFY_DONE", job, "FEM 검증 완료 — FV-001");
    const toast = await screen.findByRole("status");
    fireEvent.click(within(toast).getByRole("button", { name: /FEM 검증 완료/ }));
    expect(await screen.findByRole("region", { name: /^FV-001/ })).toBeTruthy();
  });

  it("scx: 상세에 SCX 잡 상태(확인 필요·잡 폴더)", async () => {
    renderApp(`${STUDY}/4/verify/fv-1`, { ...O, hpcMode: "scx" }, (srv) => {
      const j = srv.jobs.find((x) => x.id === "j-fv1")!;
      j.state = "WAITING_HPC";
      (j as unknown as { _scx: unknown })._scx = { id: "hj-j-fv1", version: 1, remote_dir: "/Users/vd.dashboard/cushion/04_FV-001_20261019T101500", request_id: "pai-hj-j-fv1", submission_unknown: true, resolve: null, error_message: "SCX 제출 결과를 알 수 없습니다 — SCX에서 확인 필요", state: "UNKNOWN" };
    });
    const head = await screen.findByRole("region", { name: /^FV-001/ });
    expect(await within(head).findByTestId("hpc-needs-check", {}, { timeout: 3000 })).toBeTruthy();
    expect(within(head).getByText("/Users/vd.dashboard/cushion/04_FV-001_20261019T101500")).toBeTruthy();
  });
});
