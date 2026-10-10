// phase2.md §20 V2-FE-1~6 (컴포넌트 시험, 목 서버)
import { describe, expect, it } from "vitest";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { renderApp, STUDY } from "../test/render";
import type { MockServer } from "../mock/server";
import { FeatureGate } from "../components/FeatureGate";
import { AppContext } from "../app/AppContext";
import { clearApiCache, type StatusInfo } from "../api";
import { USERS } from "../mock/data";
import { setEnvPollMs } from "../pages/AdminEnvCheck";
import { PBS_NONE_TEXT } from "../stages/stage1/SolveCard";
import { isUsableComponent, timeSteps, timeStepsText } from "../lib/curation";
import { METHOD_DEFAULTS, activeRules } from "../stages/stage5/rules";

/** server.handle 호출 기록 */
function recordCalls(server: MockServer) {
  const calls: string[] = [];
  const orig = server.handle.bind(server);
  server.handle = (m, p, q, b, h) => {
    calls.push(`${m} ${p}`);
    return orig(m, p, q, b, h);
  };
  return calls;
}

describe("V2-FE-1 스텝퍼·FeatureGate", () => {
  it("설정이 비면 버튼 비활성 + '관리자 설정 필요: <키>'", async () => {
    renderApp(`${STUDY}/1`, { user: "power", disabledFeatures: ["train_extract"] });
    const card = await screen.findByRole("region", { name: "CAD 파라미터 추출" });
    const note = await within(card).findByTestId("feature-off-train_extract");
    expect(note.textContent).toBe("관리자 설정 필요: resources.pyd_dir, commands.simlab_extract_params");
    expect((within(card).getByRole("button", { name: "파라미터 추출" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("FeatureGate: features가 없으면(1차 백엔드) 활성, enabled=false면 키 3개까지", () => {
    const status = { features: { optimize: { enabled: false, missing: ["a", "b", "c", "d"] } } } as unknown as StatusInfo;
    const ui = (st: StatusInfo | null) => (
      <AppContext.Provider value={{ me: USERS.power, projects: [], status: st }}>
        <FeatureGate feature="optimize">{(en) => <button disabled={!en}>실행</button>}</FeatureGate>
      </AppContext.Provider>
    );
    const { rerender } = render(ui(null));
    expect((screen.getByRole("button", { name: "실행" }) as HTMLButtonElement).disabled).toBe(false);
    rerender(ui(status));
    expect((screen.getByRole("button", { name: "실행" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByTestId("feature-off-optimize").textContent).toBe("관리자 설정 필요: a, b, c 외");
  });
});

describe("③-1·③-5·④ FeatureGate(features.dataset_create/evaluate/predict)", () => {
  it("비활성이면 버튼 비활성 + 설정 필요 안내, 관리자에게만 환경 점검 링크", async () => {
    const off = ["dataset_create", "evaluate", "predict"] as const;
    const p = renderApp(`${STUDY}/3`, { user: "power", disabledFeatures: [...off] });
    const ds = await screen.findByRole("region", { name: "데이터셋 생성" });
    expect((await within(ds).findByTestId("feature-off-dataset_create")).textContent).toBe("관리자 설정 필요: altair.edspy_path");
    expect((within(ds).getByRole("button", { name: "데이터셋 생성" }) as HTMLButtonElement).disabled).toBe(true);
    const ev = screen.getByRole("region", { name: "평가 · Final 지정" });
    expect(within(ev).getByTestId("feature-off-evaluate")).toBeTruthy();
    expect((within(ev).getByRole("button", { name: "평가" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.queryByTestId("feature-off-link-dataset_create")).toBeNull();
    p.unmount();
    clearApiCache();
    renderApp(`${STUDY}/4`, { user: "admin", disabledFeatures: [...off] });
    expect(await screen.findByTestId("feature-off-predict")).toBeTruthy();
    await waitFor(() => expect((screen.getByRole("button", { name: "예측 실행" }) as HTMLButtonElement).disabled).toBe(true));
    expect(screen.getByTestId("feature-off-link-predict").getAttribute("href")).toBe("/admin/env-check");
  });

  it("활성(기본)이면 안내 없음", async () => {
    renderApp(`${STUDY}/3`, { user: "power" });
    await screen.findByRole("region", { name: "데이터셋 생성" });
    expect(screen.queryByTestId("feature-off-dataset_create")).toBeNull();
    expect(screen.queryByTestId("feature-off-evaluate")).toBeNull();
  });
});

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

describe("V2-FE-3 ② 데이터 정리", () => {
  it("규칙: usable component, time step 미리보기 80자", () => {
    expect(isUsableComponent("vonMises")).toBe(true);
    expect(isUsableComponent("P1 (major)")).toBe(true);
    expect(isUsableComponent("Max Abs Principal")).toBe(false);
    expect(isUsableComponent("Extreme Value")).toBe(false);
    expect(timeSteps(5, 2)).toEqual([1, 3, 5]);
    expect(timeStepsText(5, 2)).toBe("Steps (3개): 1, 3, 5");
    const long = timeStepsText(400, 1);
    expect(long.length).toBeLessThanOrEqual(81);
    expect(long.startsWith("Steps (400개): 1, 2, 3")).toBe(true);
    expect(long.endsWith("…")).toBe(true);
  });

  it("원천 선택·Displacement 고정·usable만 콤보·time step·누락 run", async () => {
    renderApp(`${STUDY}/2`, { user: "power" });
    const counts = await screen.findByTestId("source-counts");
    await waitFor(() => expect(counts.textContent).toContain("기대 run 30"));
    expect(counts.textContent).toContain("h3d 24");
    const card = screen.getByRole("region", { name: "h3d 큐레이션" });
    const dtTable = await within(card).findByRole("table", { name: "DataType Component 표" });
    expect(within(dtTable).getByTestId("displacement-row").textContent).toContain("항상 포함");
    const dtOpts = Array.from((within(dtTable).getByLabelText("DataType 선택") as HTMLSelectElement).options).map((o) => o.value);
    expect(dtOpts).toEqual(["Stress", "Plastic Strain"]);
    const compOpts = Array.from((within(dtTable).getByLabelText("Component 선택") as HTMLSelectElement).options).map((o) => o.value);
    expect(compOpts).toEqual(["vonMises", "P1 (major)"]);
    fireEvent.change(within(card).getByLabelText("Time step 간격"), { target: { value: "2" } });
    expect(within(card).getByTestId("steps-preview").textContent).toMatch(/^Steps \(21개\): 1, 3, 5/);
    const res = within(card).getByTestId("curation-result");
    expect(res.textContent).toContain("성공 23/24");
    expect(res.textContent).toContain("누락 run 6");
    expect(res.textContent).toContain("③-1 데이터셋 생성의 기본 입력으로 연결됩니다");
  });

  it("큐레이션 실행: 선택·Part·간격·제외 파일이 params로", async () => {
    const { server } = renderApp(`${STUDY}/2`, { user: "power" });
    const card = await screen.findByRole("region", { name: "h3d 큐레이션" });
    const dtTable = await within(card).findByRole("table", { name: "DataType Component 표" });
    fireEvent.click(within(dtTable).getByRole("button", { name: "추가" }));
    fireEvent.click(within(card).getByLabelText("Shell 2"));
    fireEvent.change(within(card).getByLabelText("Time step 간격"), { target: { value: "3" } });
    fireEvent.click(within(card).getByText(/^파일 24\/24/));
    fireEvent.click(within(card).getByLabelText("run__00002/m_3/cushion_0000.h3d"));
    fireEvent.click(within(card).getByRole("button", { name: "큐레이션 실행" }));
    await waitFor(() => expect(server.jobs.some((j) => j.job_type === "CU_H3D_CURATE" && j.state === "QUEUED")).toBe(true));
    const j = server.jobs.find((x) => x.job_type === "CU_H3D_CURATE" && x.state === "QUEUED")!;
    expect(j.params).toMatchObject({
      source: { kind: "TRAIN_DOE", doe_id: "doe-1" },
      preview_job_id: "j-h3dprev",
      selection: { items: [{ datatype: "Stress", component: "vonMises" }], parts: { shell: [2], solid: [], rbody: [] }, time_increment: 3 },
      exclude_files: ["run__00002/m_3/cushion_0000.h3d"],
    });
  });

  it("곡선: series 있으면 SVG 그래프, 없으면 JSON 트리 + 형식 미확인", async () => {
    const { unmount } = renderApp(`${STUDY}/2`, { user: "power" });
    expect(await screen.findByTestId("curve-chart")).toBeTruthy();
    expect(screen.getByRole("img", { name: "첫 곡선" })).toBeTruthy();
    unmount();
    const s2 = renderApp(`${STUDY}/2`, { user: "power" }).server;
    s2.artifacts.filter((a) => a.kind === "CURVE_JSON" && a.job_id === "j-cur2").forEach((a) => (a.body = JSON.stringify({ curves: { foo: 1 } })));
    expect(await screen.findByTestId("curve-unknown")).toBeTruthy();
    expect(screen.getByText("곡선 형식 미확인")).toBeTruthy();
  });
});

describe("V2-FE-4 ⑤ 최적화", () => {
  it("메서드 기본값·라벨·활성 규칙(단위)", () => {
    expect(METHOD_DEFAULTS.GRSM.max_designs).toBe(50);
    expect(METHOD_DEFAULTS.SQP.dv).toBe(0);
    expect(activeRules({ approach: "OPT", method: "ARSM" })).toEqual({ method: true, absRel: true, dv: true, onFailed: true });
    expect(activeRules({ approach: "OPT", method: "SQP" })).toEqual({ method: true, absRel: false, dv: true, onFailed: true });
    expect(activeRules({ approach: "OPT", method: "GRSM" })).toEqual({ method: true, absRel: false, dv: false, onFailed: true });
    expect(activeRules({ approach: "DOE", method: "ARSM" })).toEqual({ method: false, absRel: false, dv: false, onFailed: false });
  });

  it("응답 표 열, Goal별 Bound/Value 비활성, 목적 필요 → 실행", async () => {
    const { server } = renderApp(`${STUDY}/5`, { user: "power" });
    const card = await screen.findByRole("region", { name: "응답" });
    const table = within(card).getByRole("table", { name: "응답 표" });
    expect(within(table).getAllByRole("columnheader").map((h) => h.textContent)).toEqual([
      "Name", "Source", "Subcase", "DataType/Request", "Component", "Layer", "Stat", "Goal", "Bound", "Value", "",
    ]);
    const add = within(card).getByRole("group", { name: "응답 추가" });
    await waitFor(() => expect((within(add).getByLabelText("DataType") as HTMLSelectElement).tagName).toBe("SELECT"));
    expect((within(add).getByLabelText("Name") as HTMLInputElement).value).toBe("STRESS");
    fireEvent.click(within(add).getByRole("button", { name: "추가" }));
    const run = screen.getByRole("region", { name: "실행" });
    const btn = within(run).getByRole("button", { name: "최적화 실행" }) as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    expect(within(run).getByText("MINIMIZE 또는 MAXIMIZE 응답이 필요합니다")).toBeTruthy();
    expect((within(table).getByLabelText("STRESS Value") as HTMLInputElement).disabled).toBe(true);
    fireEvent.change(within(table).getByLabelText("STRESS Goal"), { target: { value: "CONSTRAINT" } });
    expect((within(table).getByLabelText("STRESS Value") as HTMLInputElement).disabled).toBe(false);
    expect((within(table).getByLabelText("STRESS Bound") as HTMLSelectElement).disabled).toBe(false);
    fireEvent.change(within(table).getByLabelText("STRESS Goal"), { target: { value: "MINIMIZE" } });
    await waitFor(() => expect(btn.disabled).toBe(false));
    fireEvent.click(btn);
    await waitFor(() => expect(server.jobs.some((j) => j.job_type === "OPTIMIZE" && j.state === "QUEUED")).toBe(true));
    const j = server.jobs.find((x) => x.job_type === "OPTIMIZE" && x.state === "QUEUED")!;
    expect(j.params).toMatchObject({ approach: "OPT", opt_method: "ARSM", max_designs: 25, responses: [{ name: "STRESS", source: "H3D", subcase: 1, datatype: "Stress", component: "vonMises", goal: "MINIMIZE" }] });
    expect((j.params.responses as Record<string, unknown>[])[0]).not.toHaveProperty("bound");
  });

  it("메서드 변경 시 기본값·SQP 라벨, DOE면 메서드·고급 비활성 + 버튼 문구", async () => {
    renderApp(`${STUDY}/5`, { user: "power" });
    const run = await screen.findByRole("region", { name: "실행" });
    fireEvent.change(within(run).getByLabelText("Opt Method"), { target: { value: "GRSM" } });
    expect((within(run).getByLabelText("최대 설계 수") as HTMLInputElement).value).toBe("50");
    expect((within(run).getByLabelText("Absolute Convergence") as HTMLInputElement).disabled).toBe(true);
    fireEvent.change(within(run).getByLabelText("Opt Method"), { target: { value: "SQP" } });
    expect(within(run).getByText("Maximum Iterations")).toBeTruthy();
    expect((within(run).getByLabelText("Design Variable Convergence") as HTMLInputElement).value).toBe("0");
    fireEvent.click(within(run).getByRole("radio", { name: "DOE" }));
    expect((within(run).getByLabelText("Opt Method") as HTMLSelectElement).disabled).toBe(true);
    expect((within(run).getByLabelText("On Failed Evaluation") as HTMLSelectElement).disabled).toBe(true);
    expect(within(run).getByText("Number of Evaluations")).toBeTruthy();
    expect(within(run).getByRole("button", { name: "DOE 실행" })).toBeTruthy();
  });

  it("결과: 설계 이력 차트·완료 문구 / 진행 문구 OPT·DOE / 요약 없음 문구", async () => {
    const r1 = renderApp(`${STUDY}/5`, { user: "power" });
    expect(await screen.findByRole("img", { name: "설계 이력" })).toBeTruthy();
    expect(screen.getByTestId("opt-progress").textContent).toContain("완료 · run 25 / 25");
    r1.unmount();

    const prep = (fn: (s: MockServer) => void) => {
      const r = renderApp(`${STUDY}/5`, { user: "power" });
      fn(r.server);
      return r;
    };
    const r2 = prep((s) => Object.assign(s.p2.opts[0], { status: "RUNNING", runs_started: 12 }));
    await waitFor(() => expect(screen.getByTestId("opt-progress").textContent).toContain("run 12 / 25 시작"));
    r2.unmount();
    const r3 = prep((s) => Object.assign(s.p2.opts[0], { status: "RUNNING", runs_started: 12, approach: "DOE" }));
    await waitFor(() => expect(screen.getByTestId("opt-progress").textContent).toMatch(/run 12 시작/));
    r3.unmount();
    prep((s) => Object.assign(s.p2.opts[0], { summary_status: "UNRECOGNIZED" }));
    expect((await screen.findByTestId("summary-unknown")).textContent).toBe("결과 요약 형식 미확인 — 원본 파일 목록을 확인하세요");
    fireEvent.click(await screen.findByRole("button", { name: /opt_summary\.csv$/ }));
    expect(await screen.findByRole("table", { name: "opt_summary.csv" })).toBeTruthy();
  });
});

describe("V2-FE-5 환경 점검(전역 관리자)", () => {
  it("관리 메뉴·빨간 점 → 화면, 실행·폴링·이력", async () => {
    setEnvPollMs(40);
    const { server } = renderApp(`${STUDY}/3`, { user: "admin" });
    const btn = await screen.findByRole("button", { name: /^관리/ });
    await waitFor(() => expect(within(btn).getByTestId("admin-alert-dot")).toBeTruthy());
    fireEvent.click(btn);
    fireEvent.click(screen.getByRole("menuitem", { name: /환경 점검/ }));
    const sum = await screen.findByTestId("env-summary");
    expect(sum.textContent).toContain("실패 2 · 경고 2");
    const table = screen.getByRole("table", { name: "점검 결과" });
    expect(within(table).getByText("hvtrans")).toBeTruthy();
    const hist = screen.getByRole("table", { name: "점검 이력" });
    expect(within(hist).getAllByRole("row")).toHaveLength(4);
    // 다른 이력 보기
    fireEvent.click(within(hist).getAllByRole("row")[2]);
    await waitFor(() => expect(screen.getByTestId("env-summary").textContent).toContain("실패 0 · 경고 2"));
    // 실행
    fireEvent.click(screen.getByRole("button", { name: "점검 실행" }));
    const busy = await screen.findByRole("button", { name: "점검 중…" });
    expect((busy as HTMLButtonElement).disabled).toBe(true);
    await waitFor(() => expect(within(screen.getByRole("table", { name: "점검 결과" })).getAllByText("대기").length).toBeGreaterThan(0));
    act(() => {
      server.tick();
      server.tick();
    });
    await waitFor(() => expect(screen.getByRole("button", { name: "점검 실행" })).toBeTruthy(), { timeout: 3000 });
    await waitFor(() => expect(within(screen.getByRole("table", { name: "점검 이력" })).getAllByRole("row")).toHaveLength(5));
    expect(server.notifs.some((n) => n.event === "ENV_CHECK_DONE" && n.user_id === "u-admin")).toBe(true);
  });

  it("config.warnings: 관리자에게만 빨간 점 + 환경 점검 화면 상단 경고 목록", async () => {
    const warn = ["resources.extract_minmax_tcl 미설정(⑤ 비활성)"];
    const a = renderApp(`${STUDY}/3`, { user: "admin", configWarnings: warn });
    a.server.p2.envChecks.forEach((e) => (e.summary.fail = 0)); // 점검 실패 없이 경고만으로 점이 떠야 한다
    const btn = await screen.findByRole("button", { name: /^관리/ });
    await waitFor(() => expect(within(btn).getByTestId("admin-alert-dot").getAttribute("title")).toBe("설정 경고 1건"));
    fireEvent.click(btn);
    fireEvent.click(screen.getByRole("menuitem", { name: /환경 점검/ }));
    const box = await screen.findByRole("region", { name: "설정 경고" });
    expect(within(box).getByText(warn[0])).toBeTruthy();
    a.unmount();
    clearApiCache();
    renderApp(`${STUDY}/3`, { user: "power", configWarnings: warn });
    await screen.findByRole("navigation", { name: "경로" });
    expect(screen.queryByTestId("admin-alert-dot")).toBeNull();
  });

  it("비관리자: 메뉴 없음, URL로 들어오면 '관리자 전용입니다'", async () => {
    const { server } = renderApp(`${STUDY}/3`, { user: "power" });
    await screen.findByRole("navigation", { name: "경로" });
    expect(screen.queryByRole("button", { name: /^관리/ })).toBeNull();
    const calls = recordCalls(server);
    renderApp("/admin/env-check", { user: "power" });
    expect(await screen.findByText("관리자 전용입니다")).toBeTruthy();
    expect(calls.filter((c) => c.includes("env-checks"))).toEqual([]);
  });
});

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
