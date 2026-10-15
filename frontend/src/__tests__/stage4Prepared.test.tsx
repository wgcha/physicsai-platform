// V3-S6-13(phase3.md §11.5·§11.6): ④ 입력 방식 토글·준비된 입력 카드
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { renderApp, STUDY } from "../test/render";
import type { MockServer } from "../mock/server";
import { err } from "../mock/route";

const KEY = "physicsai.stage4.inputMode";
const PATH = "E:/shared/AI_WORK/cushion/00_inbox/case_A/Face_Drop_0000.rad";

/** POST /studies/{id}/jobs 본문 기록 */
function recordJobBodies(server: MockServer) {
  const bodies: Record<string, unknown>[] = [];
  const orig = server.handle.bind(server);
  server.handle = (m, p, q, b, h) => {
    if (m === "POST" && /\/studies\/[^/]+\/jobs$/.test(p)) bodies.push(b as Record<string, unknown>);
    return orig(m, p, q, b, h);
  };
  return bodies;
}

const modeRadio = (name: string) => screen.findByRole("radio", { name }) as Promise<HTMLButtonElement>;
const chainLabels = () =>
  within(screen.getByRole("list", { name: "예측 실행 단계" }))
    .getAllByRole("listitem")
    .map((li) => li.querySelector(".chain-label")!.textContent);

async function inspectOk(path = PATH) {
  const card = await screen.findByRole("region", { name: "준비된 입력 파일" });
  fireEvent.change(within(card).getByLabelText("준비된 입력 경로"), { target: { value: path } });
  fireEvent.click(within(card).getByRole("button", { name: "확인" }));
  return card;
}

describe("④ 준비된 입력 예측 (V3-S6-13)", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it("토글: 기본은 파라미터, 선택은 localStorage에 유지되고 다시 열어도 유지", async () => {
    const first = renderApp(`${STUDY}/4`, { user: "power" });
    const param = await modeRadio("파라미터로 형상 생성");
    expect(param.getAttribute("aria-checked")).toBe("true");
    fireEvent.click(await modeRadio("준비된 입력 파일"));
    expect(localStorage.getItem(KEY)).toBe("prepared");
    expect(await screen.findByRole("region", { name: "준비된 입력 파일" })).toBeTruthy();
    // 파라미터 세트 카드·입력 표는 숨김
    expect(screen.queryByRole("region", { name: "파라미터 세트" })).toBeNull();
    expect(screen.queryByRole("table", { name: "파라미터 입력" })).toBeNull();
    expect(screen.getByText(/직계 파일만 복사/)).toBeTruthy();
    first.unmount();

    renderApp(`${STUDY}/4`, { user: "power" });
    expect((await modeRadio("준비된 입력 파일")).getAttribute("aria-checked")).toBe("true");
    expect(await screen.findByRole("region", { name: "준비된 입력 파일" })).toBeTruthy();
  });

  it("localStorage 접근이 실패해도 기본값으로 정상 렌더", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    renderApp(`${STUDY}/4`, { user: "power" });
    expect((await modeRadio("파라미터로 형상 생성")).getAttribute("aria-checked")).toBe("true");
    fireEvent.click(await modeRadio("준비된 입력 파일"));
    expect(await screen.findByRole("region", { name: "준비된 입력 파일" })).toBeTruthy();
  });

  it("확인 → 요약 한 줄, 예측 실행 요청 body는 prepared 형식, 진행은 입력파일 → 예측", async () => {
    localStorage.setItem(KEY, "prepared");
    const { server } = renderApp(`${STUDY}/4`, { user: "power" });
    const bodies = recordJobBodies(server);
    const card = await inspectOk();
    expect((await within(card).findByTestId("prepared-summary")).textContent).toBe("Face_Drop_0000.rad · rad 2 · inc 3");
    expect(within(card).getByText("Final 모델(기본)")).toBeTruthy();
    expect(within(card).getByText("Final")).toBeTruthy();
    const run = within(card).getByRole("button", { name: "예측 실행" }) as HTMLButtonElement;
    await waitFor(() => expect(run.disabled).toBe(false));
    fireEvent.click(run);
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toEqual({ job_type: "PREDICT", params: { input_mode: "prepared", input_path: PATH, model_id: null, param_set_id: null } });
    expect(chainLabels()).toEqual(["입력파일", "예측"]);
    act(() => server.finishAll());
    const job = server.jobs.find((j) => (j.params as { input_mode?: string }).input_mode === "prepared")!;
    expect(job.steps.filter((s) => s.state === "SKIPPED").map((s) => s.step_key)).toEqual(expect.arrayContaining(["TPL_RENDER", "GEOM_UPDATE", "MESH"]));
    const result = await screen.findByRole("region", { name: "결과" });
    await waitFor(() => expect(within(result).getByText("Face_Drop_0000.rad")).toBeTruthy(), { timeout: 3000 });
    expect(within(result).getByText(/준비된 입력/)).toBeTruthy();
    expect(await within(result).findByAltText("예측 컨투어")).toBeTruthy();
    expect(chainLabels()).toEqual(["입력파일", "예측"]);
    expect(screen.queryByText("생략")).toBeNull();
    // PBS 검증 해석: 기존 규칙(PBS 미구성 → 비활성 + 안내)
    const pbs = within(card).getByRole("button", { name: "PBS 검증 해석" }) as HTMLButtonElement;
    expect(pbs.disabled).toBe(true);
    expect(within(card).getByTestId("pbs-note").textContent).toContain("PBS 연결 안 됨");
  });

  it("확인 결과 문제는 회색 참고 문구, 실행 비활성", async () => {
    localStorage.setItem(KEY, "prepared");
    renderApp(`${STUDY}/4`, { user: "power" });
    const card = await inspectOk("E:/shared/AI_WORK/cushion/00_inbox/two_cases");
    const notes = await within(card).findByTestId("prepared-problems");
    expect(notes.textContent).toContain("starter");
    expect(notes.querySelector("li")!.className).toContain("muted");
    expect(within(card).queryByRole("alert")).toBeNull();
    expect((within(card).getByRole("button", { name: "예측 실행" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("422 PREDICT_INPUT_INVALID면 problems를 카드 안에 표시", async () => {
    localStorage.setItem(KEY, "prepared");
    const { server } = renderApp(`${STUDY}/4`, { user: "power" });
    const orig = server.handle.bind(server);
    server.handle = (m, p, q, b, h) =>
      m === "POST" && p.endsWith("/jobs")
        ? err(422, "PREDICT_INPUT_INVALID", "준비된 입력을 쓸 수 없습니다", { problems: [{ code: "FILE_NAME_UNSAFE", message: "파일 이름에 쓸 수 없는 문자가 있습니다: a&b.inc" }] })
        : orig(m, p, q, b, h);
    const card = await inspectOk();
    const run = within(card).getByRole("button", { name: "예측 실행" }) as HTMLButtonElement;
    await waitFor(() => expect(run.disabled).toBe(false));
    fireEvent.click(run);
    expect((await within(card).findByRole("alert")).textContent).toBe("준비된 입력을 쓸 수 없습니다");
    const notes = within(card).getByTestId("prepared-run-problems");
    expect(notes.textContent).toContain("a&b.inc");
    expect(notes.querySelector("li")!.getAttribute("data-code")).toBe("FILE_NAME_UNSAFE");
  });

  it("파라미터 세트가 없어도 토글·카드 표시, 응답 표는 비어 있음", async () => {
    const { server } = renderApp(`${STUDY}/4`, { user: "power" }, (s) => {
      s.paramSets = s.paramSets.filter((p) => p.study_id !== "s-cushion");
      s.jobs = s.jobs.filter((j) => j.job_type !== "PREDICT");
    });
    expect(await screen.findByText(/등록된 파라미터 세트가 없습니다/)).toBeTruthy();
    fireEvent.click(await modeRadio("준비된 입력 파일"));
    const card = await inspectOk("E:/shared/AI_WORK/cushion/00_inbox/case_B");
    expect((await within(card).findByTestId("prepared-summary")).textContent).toBe("Face_Drop_0000.rad · rad 2 · inc 3");
    const run = within(card).getByRole("button", { name: "예측 실행" }) as HTMLButtonElement;
    await waitFor(() => expect(run.disabled).toBe(false));
    fireEvent.click(run);
    await waitFor(() => expect(server.jobs.some((j) => j.job_type === "PREDICT" && j.state === "QUEUED")).toBe(true));
    act(() => server.finishAll());
    const result = await screen.findByRole("region", { name: "결과" });
    expect(await within(result).findByText(/응답 정의 없음/, {}, { timeout: 3000 })).toBeTruthy();
    const job = server.jobs.find((j) => j.job_type === "PREDICT" && j.study_id === "s-cushion")!;
    expect(job.steps.find((s) => s.step_key === "RESPONSE_TABLE")!.state).toBe("SKIPPED");
  });

  it("parametric 회귀 없음: 세트 카드·입력 표·4단계, 요청 body에 input_path 없음", async () => {
    const { server } = renderApp(`${STUDY}/4`, { user: "power" });
    const bodies = recordJobBodies(server);
    expect(await screen.findByRole("region", { name: "파라미터 세트" })).toBeTruthy();
    expect(await screen.findByRole("table", { name: "파라미터 입력" })).toBeTruthy();
    expect(screen.queryByRole("region", { name: "준비된 입력 파일" })).toBeNull();
    await screen.findByRole("table", { name: "응답값" });
    expect(chainLabels()).toEqual(["형상", "메싱", "입력파일", "예측"]);
    const run = screen.getByRole("button", { name: "예측 실행" }) as HTMLButtonElement;
    await waitFor(() => expect(run.disabled).toBe(false));
    fireEvent.click(run);
    await waitFor(() => expect(bodies).toHaveLength(1));
    const params = bodies[0].params as Record<string, unknown>;
    expect(Object.keys(params).sort()).toEqual(["model_id", "param_set_id", "source_run_key", "value_source", "values"]);
    expect(params.param_set_id).toBe("ps-1");
  });

  it("predict_parametric=false: 첫 선택지 비활성 + 툴팁, 준비된 입력으로 표시", async () => {
    localStorage.setItem(KEY, "parametric");
    renderApp(`${STUDY}/4`, { user: "power", disabledFeatures: ["train_resp", "predict_parametric"] });
    const param = await modeRadio("파라미터로 형상 생성");
    await waitFor(() => expect(param.disabled).toBe(true));
    expect(param.title).toBe("형상 갱신 설정 필요(관리자)");
    expect((await modeRadio("준비된 입력 파일")).getAttribute("aria-checked")).toBe("true");
    expect(screen.getByTestId("parametric-off").textContent).toBe("형상 갱신 설정 필요(관리자)");
    expect(await screen.findByRole("region", { name: "준비된 입력 파일" })).toBeTruthy();
    expect(screen.queryByRole("region", { name: "파라미터 세트" })).toBeNull();
    expect(localStorage.getItem(KEY)).toBe("parametric");
  });
});

describe("목 PREDICT params 검증(§11.5)", () => {
  const h = new Headers({ "X-PhysicsAI-Request": "1" });
  const q = new URLSearchParams();
  const post = (s: MockServer, params: Record<string, unknown>) => s.handle("POST", "/studies/s-cushion/jobs", q, { job_type: "PREDICT", params }, h);
  const code = (r: { body?: unknown }) => (r.body as { detail?: { code?: string } }).detail?.code;

  it("inspect PREDICT_INPUT: 기존 모양 + summary에 §11.5 키", async () => {
    const { MockServer } = await import("../mock/server");
    const s = new MockServer({ user: "power" });
    const r = s.handle("POST", "/studies/s-cushion/paths/inspect", q, { purpose: "PREDICT_INPUT", path: "E:/shared/AI_WORK/x/model.hm" }, h);
    expect(r.status).toBe(200);
    const b = r.body as { ok: boolean; normalized_path: string; problems: unknown[]; summary: Record<string, unknown> };
    expect(b.ok).toBe(true);
    expect(Object.keys(b.summary).sort()).toEqual(["file_count", "inc_count", "kind", "rad", "starter", "starter_ok", "total_bytes"]);
    const bad = s.handle("POST", "/studies/s-cushion/paths/inspect", q, { purpose: "PREDICT_INPUT", path: "E:/shared/AI_WORK/x/a.txt" }, h);
    expect((bad.body as { problems: { code: string }[] }).problems[0].code).toBe("INPUT_EXT");
  });

  it("422·409 규칙, input_mode 생략 = parametric", async () => {
    const { MockServer } = await import("../mock/server");
    const s = new MockServer({ user: "power" });
    expect(code(post(s, { input_mode: "prepared", input_path: "E:/shared/AI_WORK/x/two_starters" }))).toBe("PREDICT_INPUT_INVALID");
    expect(code(post(s, { input_mode: "prepared", input_path: "" }))).toBe("INVALID_PARAMS");
    expect(code(post(s, { input_mode: "prepared", input_path: "E:/shared/AI_WORK/x/a.rad", values: { A: 1 } }))).toBe("INVALID_PARAMS");
    expect(code(post(s, { input_mode: "prepared", input_path: "E:/shared/AI_WORK/x/a.rad", param_set_id: "ps-none" }))).toBe("PREREQUISITE_MISSING");
    expect(code(post(s, { param_set_id: "ps-1", values: {}, value_source: "nominal", input_path: "E:/x.rad" }))).toBe("INVALID_PARAMS");
    const ok = post(s, { param_set_id: "ps-1", model_id: null, values: { THK_TOP: 0.6 }, value_source: "nominal", source_run_key: null });
    expect(ok.status).toBe(201);
    const off = new MockServer({ user: "power", disabledFeatures: ["train_resp", "predict_parametric"] });
    expect(code(post(off, { param_set_id: "ps-1", values: {}, value_source: "nominal" }))).toBe("TEMPLATE_NOT_CONFIGURED");
    const prep = post(off, { input_mode: "prepared", input_path: "E:\\shared\\AI_WORK\\x\\a.rad", model_id: null, param_set_id: null });
    expect(prep.status).toBe(201);
    expect((prep.body as { params: Record<string, unknown> }).params).toMatchObject({ input_mode: "prepared", input_path: "E:/shared/AI_WORK/x/a.rad", input_kind: "file", starter_name: "a.rad" });
  });
});

describe("④ 컨투어 결과 목록(JsonTree)", () => {
  it("원본 형식과 이전 형식 모두 표시", async () => {
    const { render } = await import("@testing-library/react");
    const { JsonTree } = await import("../components/JsonTree");
    const { PREVIEW_JSON } = await import("../mock/data");
    const cur = render(<JsonTree data={PREVIEW_JSON} />);
    expect(cur.container.textContent).toContain("num_time_step: 5");
    expect(cur.container.textContent).toContain("label: Subcase 1");
    expect(cur.container.textContent).toContain("binding: element");
    cur.unmount();
    const old = render(<JsonTree data={{ subcases: [{ name: "Subcase 1", datatypes: [{ name: "Stress", components: ["vonMises"] }] }] }} />);
    expect(old.container.textContent).toContain("name: Subcase 1");
    expect(old.container.textContent).toContain("vonMises");
  });
});
