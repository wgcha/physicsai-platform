// V3-S9-14·17·18(화면, phase3.md §14.8·§14.9): 입력 방식 3개·기억, A 템플릿 요청 body·mesh_only 진행 단계, 템플릿 관리(조립 "없음"·응답 추가),
// B 미리보기·실행 body, 결과 표 정렬·행 선택·실패만 다시, 응답 그래프 선택 규칙(2D·3D·안내), 커브 강조, 다운샘플. 목 서버(mock/predictBatch.ts) 기준.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { renderApp, STUDY } from "../test/render";
import type { MockServer } from "../mock/server";
import { ok } from "../mock/route";
import { downsampleMinMax } from "../lib/downsample";
import { PLOT_HINT, plotKind, sortRows } from "../stages/stage4/batch/batchTable";
import { overlayLines } from "../stages/stage4/batch/CurveOverlay";
import { NO_WEBGL_TEXT } from "../stages/stage4/batch/ResponsePlot3D";
import type { BatchCurves, PredictBatchRow } from "../api";

const plotly = vi.hoisted(() => ({ react: vi.fn(async (el: HTMLElement) => el), purge: vi.fn() }));
vi.mock("plotly.js-gl3d-dist-min", () => ({ default: plotly }));

const KEY = "physicsai.stage4.inputMode";
const BATCH = `${STUDY}/4/batch/pb-2`;

/** 비GET 요청 본문 기록(경로 정규식별) */
function record(server: MockServer, re: RegExp, method = "POST") {
  const bodies: Record<string, unknown>[] = [];
  const orig = server.handle.bind(server);
  server.handle = (m, p, q, b, h) => {
    if (m === method && re.test(p)) bodies.push(b as Record<string, unknown>);
    return orig(m, p, q, b, h);
  };
  return bodies;
}
const radio = (name: string) => screen.findByRole("radio", { name }) as Promise<HTMLInputElement>;
const stepLabels = () =>
  within(screen.getByRole("list", { name: "예측 실행 단계" }))
    .getAllByRole("listitem")
    .map((li) => li.querySelector(".pstep-label")!.textContent);
const rowOrder = () => screen.getAllByTestId(/^row-\d+$/).map((r) => Number(r.getAttribute("data-testid")!.slice(4)));

describe("④ 입력 방식·템플릿 값 입력 (V3-S9-14)", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it("입력 방식 3개: 기본 템플릿 값 입력, 바꾸면 기억(새로 열어도 유지), 옛 값 parametric → 템플릿 값 입력", async () => {
    const first = renderApp(`${STUDY}/4`, { user: "power" });
    expect((await radio("템플릿 값 입력")).getAttribute("aria-checked")).toBe("true");
    expect(screen.getAllByRole("radio").map((r) => r.textContent).slice(0, 3)).toEqual(["템플릿 값 입력", "일괄 예측(DOE)", "준비된 입력 파일"]);
    expect(screen.getByTestId("input-mode-note").textContent).toBe("값 몇 개로 형상 1개를 바로 예측합니다.");
    fireEvent.click(await radio("일괄 예측(DOE)"));
    expect(localStorage.getItem(KEY)).toBe("batch");
    expect(await screen.findByRole("region", { name: "1 템플릿·조합" })).toBeTruthy();
    expect(screen.queryByRole("region", { name: "템플릿" })).toBeNull();
    first.unmount();

    const second = renderApp(`${STUDY}/4`, { user: "power" });
    expect((await radio("일괄 예측(DOE)")).getAttribute("aria-checked")).toBe("true");
    expect(await screen.findByRole("region", { name: "2 조합 미리보기" })).toBeTruthy();
    second.unmount();

    localStorage.setItem(KEY, "parametric");
    renderApp(`${STUDY}/4`, { user: "power" });
    expect((await radio("템플릿 값 입력")).getAttribute("aria-checked")).toBe("true");
    expect(localStorage.getItem(KEY)).toBe("parametric"); // 읽기만으로는 덮어쓰지 않는다
  });

  it("localStorage가 막혀도 기본(템플릿 값 입력)으로 렌더하고 전환된다", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    renderApp(`${STUDY}/4`, { user: "power" });
    expect((await radio("템플릿 값 입력")).getAttribute("aria-checked")).toBe("true");
    fireEvent.click(await radio("일괄 예측(DOE)"));
    expect(await screen.findByRole("region", { name: "1 템플릿·조합" })).toBeTruthy();
  });

  it("A: 템플릿 드롭다운(이름 — N개 파라미터·옆 회색 정보), 메시 단독 템플릿 → 진행 3단, 요청 body param_set_id = 고른 템플릿", async () => {
    const { server } = renderApp(`${STUDY}/4`, { user: "power" });
    const bodies = record(server, /\/studies\/[^/]+\/jobs$/);
    const card = await screen.findByRole("region", { name: "템플릿" });
    const sel = within(card).getByLabelText("형상 템플릿") as HTMLSelectElement;
    expect(Array.from(sel.options).map((o) => o.textContent)).toEqual(["params — 4개 파라미터", "쿠션 단독 v1 — 4개 파라미터"]);
    expect(within(card).getByTestId("template-meta").textContent).toMatch(/^tpl · CAD · 조립 폴더 포함 · \d\d-\d\d 등록$/);
    expect(stepLabels()).toEqual(["1 형상 생성(SimLab)", "2 메시 연결(HyperMesh)", "3 조립(Radioss 입력)", "4 예측(PhysicsAI)", "5 결과"]);

    fireEvent.change(sel, { target: { value: "ps-2" } });
    const card2 = await screen.findByRole("region", { name: "템플릿" });
    await waitFor(() => expect(within(card2).getByTestId("template-meta").textContent).toContain("조립 폴더 없음(메시 단독)"));
    await waitFor(() => expect(stepLabels()).toEqual(["1 형상 생성(SimLab)", "2 예측(PhysicsAI)", "3 결과"]));
    const run = within(card2).getByRole("button", { name: "예측 실행" }) as HTMLButtonElement;
    await waitFor(() => expect(run.disabled).toBe(false));
    fireEvent.click(run);
    await waitFor(() => expect(bodies).toHaveLength(1));
    const params = bodies[0].params as Record<string, unknown>;
    expect(bodies[0].job_type).toBe("PREDICT");
    expect(Object.keys(params).sort()).toEqual(["model_id", "param_set_id", "source_run_key", "value_source", "values"]);
    expect(params.param_set_id).toBe("ps-2");
    // 서버가 template_kind를 확정 기록 → 진행 3단, MESH는 SKIPPED(표시 안 함)
    const job = server.jobs.find((j) => j.job_type === "PREDICT" && (j.params as { param_set_id?: string }).param_set_id === "ps-2")!;
    expect((job.params as { template_kind?: string }).template_kind).toBe("mesh_only");
    act(() => server.finishAll());
    await waitFor(() => expect(within(screen.getByRole("list", { name: "예측 실행 단계" })).getAllByText(/^완료/).length).toBe(3));
  });

  it("메시 단독 템플릿인데 predict_mesh_only=false면 실행 비활성 + 설정 필요 안내", async () => {
    renderApp(`${STUDY}/4`, { user: "power", disabledFeatures: ["train_resp", "predict_mesh_only"] });
    const card = await screen.findByRole("region", { name: "템플릿" });
    fireEvent.change(within(card).getByLabelText("형상 템플릿"), { target: { value: "ps-2" } });
    const c2 = await screen.findByRole("region", { name: "템플릿" });
    await waitFor(() => expect(within(c2).getByTestId("feature-off-predict_mesh_only").textContent).toBe("관리자 설정 필요: commands.geom_update"));
    expect((within(c2).getByRole("button", { name: "예측 실행" }) as HTMLButtonElement).disabled).toBe(true);
  });
});

describe("④ 템플릿 관리: 조립 폴더 없음·응답 추가 (V3-S9-14·17)", () => {
  afterEach(() => vi.restoreAllMocks());

  async function openDiscover(path: string) {
    fireEvent.click(await screen.findByRole("button", { name: "템플릿 관리" }));
    const card = await screen.findByRole("region", { name: "템플릿 관리" });
    fireEvent.click(within(card).getByRole("button", { name: "새로 등록" }));
    const form = within(card).getByTestId("ps-discover");
    fireEvent.change(within(form).getByLabelText("프로젝트 폴더 경로"), { target: { value: path } });
    fireEvent.click(within(form).getByRole("button", { name: "찾기" }));
    await within(form).findByTestId("ps-discover-result");
    return { card, form };
  }

  it("조립 폴더 드롭다운 끝 '없음(쿠션만 — 메시로 바로 예측)' → choice.radioss_assem = null, 입력 종류 표시", async () => {
    const { server } = renderApp(`${STUDY}/4`, { user: "power" });
    const bodies = record(server, /\/studies\/[^/]+\/param-sets$/);
    const { form } = await openDiscover("E:/shared/AI_WORK/cushion/00_inbox/project");
    const assem = within(form).getByLabelText("조립 폴더 선택") as HTMLSelectElement;
    expect(Array.from(assem.options).map((o) => o.textContent)).toEqual(["RADIOSS_ASSEM · cushion_0000.rad", "없음(쿠션만 — 메시로 바로 예측)"]);
    expect(within(form).getByTestId("ps-discover-kind").textContent).toContain("조립 포함(assembly)");
    fireEvent.change(assem, { target: { value: "__none__" } });
    expect(within(form).getByTestId("ps-discover-kind").textContent).toContain("메시 단독(mesh_only)");
    fireEvent.click(within(form).getByRole("button", { name: "등록" }));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect((bodies[0].choice as Record<string, unknown>).radioss_assem).toBeNull();
    await waitFor(() => expect(server.paramSets[0].input_kind).toBe("mesh_only"));
    expect(server.paramSets[0].starter_name).toBeNull();
  });

  it("조립 폴더 후보 0개 → 회색 안내, 등록 가능(null)", async () => {
    const { server } = renderApp(`${STUDY}/4`, { user: "power" });
    const bodies = record(server, /\/studies\/[^/]+\/param-sets$/);
    const { card, form } = await openDiscover("E:/shared/AI_WORK/cushion/00_inbox/cushion_only");
    expect(within(form).getByTestId("assem-zero").textContent).toBe("조립 폴더 없음 — 메시 단독 템플릿으로 등록됩니다");
    expect(within(form).getByText("조립 폴더 없음 — m1 메시로 바로 예측합니다")).toBeTruthy();
    fireEvent.click(within(form).getByRole("button", { name: "등록" }));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect((bodies[0].choice as Record<string, unknown>).radioss_assem).toBeNull();
    expect((await within(card).findByTestId("ps-input-kind")).textContent).toContain("조립 폴더 없음(메시 단독)");
  });

  it("응답 추가: 후보 목록에서 datatype·component 고르기, stat·단위 → 저장 body(spec H3D)", async () => {
    const { server } = renderApp(`${STUDY}/4`, { user: "power" });
    const puts = record(server, /\/param-sets\/[^/]+\/responses$/, "PUT");
    fireEvent.click(await screen.findByRole("button", { name: "템플릿 관리" }));
    const card = await screen.findByRole("region", { name: "템플릿 관리" });
    const defs = within(card).getByTestId("resp-defs");
    expect(within(defs).getAllByRole("row").length).toBe(4); // 머리 + 3
    const add = within(defs).getByRole("group", { name: "응답 추가" });
    const dt = (await within(add).findByLabelText("datatype")) as HTMLInputElement;
    const opts = (id: string) => Array.from(within(add).getByTestId(id).querySelectorAll("option")).map((o) => o.value);
    await waitFor(() => expect(opts("resp-add-dt-list")).toEqual(["Stress", "Displacement"]));
    expect(dt.tagName).toBe("INPUT"); // D3-53: 직접 입력 + datalist 후보
    await waitFor(() => expect(dt.value).toBe("Stress"));
    fireEvent.change(dt, { target: { value: "Displacement" } });
    const comp = within(add).getByLabelText("component") as HTMLInputElement;
    expect(opts("resp-add-comp-list")).toEqual(["X", "Y", "Z", "Mag"]);
    fireEvent.change(comp, { target: { value: "Z" } });
    fireEvent.change(within(add).getByLabelText("stat"), { target: { value: "ABSMAX" } });
    fireEvent.change(within(add).getByLabelText("단위"), { target: { value: "mm" } });
    expect((within(add).getByLabelText("응답 이름") as HTMLInputElement).value).toBe("DISPLACEMENT");
    fireEvent.change(within(add).getByLabelText("응답 이름"), { target: { value: "DispZ" } });
    fireEvent.click(within(add).getByRole("button", { name: "응답 추가" }));
    expect(within(defs).getByText("DispZ")).toBeTruthy();
    fireEvent.click(within(defs).getByRole("button", { name: "Energy 삭제" }));
    fireEvent.click(within(defs).getByRole("button", { name: "응답 저장" }));
    await waitFor(() => expect(puts).toHaveLength(1));
    const list = puts[0].responses as { name: string; unit: string; spec: Record<string, unknown> | null }[];
    expect(list.map((r) => r.name)).toEqual(["MaxStress", "MaxDisp", "DispZ"]);
    expect(list[2]).toEqual({ name: "DispZ", unit: "mm", spec: { source: "H3D", subcase: 1, datatype: "Displacement", component: "Z", layer: "", stat: "ABSMAX" } });
    await waitFor(() => expect(server.paramSets.find((p) => p.id === "ps-1")!.responses.map((r) => r.name)).toEqual(["MaxStress", "MaxDisp", "DispZ"]));
  });

  it("응답 후보가 없으면 회색 안내 + 직접 입력, 잘못된 이름은 추가 거부", async () => {
    renderApp(`${STUDY}/4`, { user: "power" }, (s) => {
      const orig = s.handle.bind(s);
      s.handle = (m, p, q, b, h) => (p.endsWith("/optimize/response-candidates") ? ok({ source_job_id: null, h3d: null, xydata: null }) : orig(m, p, q, b, h));
    });
    fireEvent.click(await screen.findByRole("button", { name: "템플릿 관리" }));
    const card = await screen.findByRole("region", { name: "템플릿 관리" });
    const add = within(card).getByRole("group", { name: "응답 추가" });
    const hint = (await within(card).findByTestId("no-candidates")).textContent;
    expect(hint).toContain("예측을 한 번 실행하면 목록이 채워집니다");
    expect(hint).toContain("예측 결과 목록이 없으면 직접 입력하세요(예: CornerStress)");
    expect((within(add).getByLabelText("datatype") as HTMLInputElement).placeholder).toBe("CornerStress");
    fireEvent.change(within(add).getByLabelText("datatype"), { target: { value: "Stress" } });
    fireEvent.change(within(add).getByLabelText("component"), { target: { value: "vonMises" } });
    fireEvent.change(within(add).getByLabelText("응답 이름"), { target: { value: "1bad" } });
    fireEvent.click(within(add).getByRole("button", { name: "응답 추가" }));
    expect(within(card).getByRole("alert").textContent).toContain("영문자로 시작");
  });

  it("D3-54: component는 선택 — CornerStress면 후보 vonMises, 비워 두고 추가하면 spec component \"\"", async () => {
    const { server } = renderApp(`${STUDY}/4`, { user: "power" }, (s) => {
      const orig = s.handle.bind(s);
      s.handle = (m, p, q, b, h) => (p.endsWith("/optimize/response-candidates") ? ok({ source_job_id: null, h3d: null, xydata: null }) : orig(m, p, q, b, h));
    });
    const puts = record(server, /\/param-sets\/[^/]+\/responses$/, "PUT");
    fireEvent.click(await screen.findByRole("button", { name: "템플릿 관리" }));
    const card = await screen.findByRole("region", { name: "템플릿 관리" });
    const defs = within(card).getByTestId("resp-defs");
    const add = within(card).getByRole("group", { name: "응답 추가" });
    const comp = within(add).getByLabelText("component") as HTMLInputElement;
    const opts = (id: string) => Array.from(within(add).getByTestId(id).querySelectorAll("option")).map((o) => o.value);
    expect(comp.placeholder).toBe("없음");
    fireEvent.change(within(add).getByLabelText("datatype"), { target: { value: "CornerStress" } });
    expect(comp.placeholder).toBe("없음(예: vonMises)");
    expect(opts("resp-add-comp-list")).toEqual(["vonMises"]);
    fireEvent.change(within(add).getByLabelText("응답 이름"), { target: { value: "Corner" } });
    fireEvent.click(within(add).getByRole("button", { name: "응답 추가" }));
    expect(within(card).queryByRole("alert")).toBeNull();
    fireEvent.click(within(defs).getByRole("button", { name: "응답 저장" }));
    await waitFor(() => expect(puts).toHaveLength(1));
    const list = puts[0].responses as { name: string; spec: Record<string, unknown> | null }[];
    expect(list[list.length - 1]).toEqual({ name: "Corner", unit: "", spec: { source: "H3D", subcase: 1, datatype: "CornerStress", component: "", layer: "", stat: "MAX" } });
  });
});

describe("④ B 일괄 예측 설정 (V3-S9-14)", () => {
  beforeEach(() => localStorage.setItem(KEY, "batch"));
  afterEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it("LHS: 범위·개수·시드 → 미리보기(DOE # ↔ run 폴더 ↔ 값) → 실행 body → 결과 화면으로 이동", async () => {
    const { server } = renderApp(`${STUDY}/4`, { user: "power" });
    const previews = record(server, /\/predict-batches\/preview$/);
    const jobs = record(server, /\/studies\/[^/]+\/jobs$/);
    const setup = await screen.findByRole("region", { name: "1 템플릿·조합" });
    expect((await radio("범위·개수로 자동(LHS)")).checked).toBe(true);
    const run = screen.getByRole("button", { name: "입력 생성 + 일괄 예측 실행" }) as HTMLButtonElement;
    expect(run.disabled).toBe(true); // 미리보기 전
    fireEvent.change(within(setup).getByLabelText("THK_TOP 최대"), { target: { value: "1.5" } });
    fireEvent.change(within(setup).getByLabelText("조합 수"), { target: { value: "4" } });
    fireEvent.change(within(setup).getByLabelText("시드"), { target: { value: "7" } });
    fireEvent.click(within(setup).getByRole("button", { name: "조합 만들기" }));
    const table = await screen.findByRole("table", { name: "조합 미리보기" });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows.map((r) => within(r).getAllByRole("cell").slice(0, 2).map((c) => c.textContent))).toEqual([
      ["1", "run__00001"], ["2", "run__00002"], ["3", "run__00003"], ["4", "run__00004"],
    ]);
    expect(screen.getByText("4개 · DOE 번호 = 입력 폴더 run 번호")).toBeTruthy();
    expect(previews[0]).toEqual({
      param_set_id: "ps-1",
      source: { kind: "lhs", count: 4, seed: 7, ranges: { THK_TOP: [0.3, 1.5], THK_FOAM: [1, 3], E_FOAM: [2, 20], RIB_N: [2, 8] } },
    });
    // THK_TOP 1.2 초과 값은 범위 밖 점
    expect(table.querySelectorAll(".oor-dot").length).toBeGreaterThan(0);
    const multi = screen.getByLabelText(/입력 생성 동시 실행 수/) as HTMLInputElement;
    expect(multi.value).toBe("4");
    expect(screen.getByText("1–8")).toBeTruthy();
    fireEvent.change(multi, { target: { value: "2" } });
    await waitFor(() => expect(run.disabled).toBe(false));
    fireEvent.click(run);
    await waitFor(() => expect(jobs).toHaveLength(1));
    expect(jobs[0]).toEqual({
      job_type: "PREDICT_BATCH",
      params: { param_set_id: "ps-1", model_id: null, multi_execution: 2, source: previews[0].source },
    });
    expect(await screen.findByRole("region", { name: "결과 표 — B-003" })).toBeTruthy();
    // 진행 → 하위 PREDICT 4개 → 완료 알림 1건(하위 알림 억제)
    const before = server.notifs.length;
    act(() => server.finishAll());
    const b = server.batches.find((x) => x.batch_no === 3)!;
    expect(b.runs.every((r) => r.predict_job_id)).toBe(true);
    const added = server.notifs.slice(before).filter((n) => n.user_id === "u-power");
    const kids = new Set(b.runs.map((r) => r.predict_job_id));
    expect(added.filter((n) => kids.has(n.job_id ?? null))).toEqual([]); // 하위 알림 억제
    const parentEvents = added.filter((n) => n.job_id === b.job_id).map((n) => n.event);
    expect(parentEvents).toContain("JOB_STARTED");
    expect(parentEvents).not.toContain("JOB_SUCCEEDED"); // 부모 성공 알림 없음(배치 완료 1건으로 대신)
    expect(parentEvents.filter((e) => e === "PREDICT_BATCH_DONE")).toHaveLength(1);
    expect(added.find((n) => n.event === "PREDICT_BATCH_DONE")!.title).toBe("일괄 예측 B-003 완료 — 완료 4 · 실패 0");
    await waitFor(() => expect(screen.getByTestId("gen-count").textContent).toBe("4 / 4"), { timeout: 3000 });
  });

  it("표 붙여넣기: 머리 줄 오류는 회색 problems, 고치면 미리보기", async () => {
    renderApp(`${STUDY}/4`, { user: "power" });
    fireEvent.click(await radio("표 붙여넣기 / CSV"));
    const setup = screen.getByRole("region", { name: "1 템플릿·조합" });
    const ta = within(setup).getByLabelText(/조합 표/);
    fireEvent.change(ta, { target: { value: "THK_TOP\tRIB_N\n0.5\t4\n" } });
    fireEvent.click(within(setup).getByRole("button", { name: "조합 만들기" }));
    const probs = await screen.findByTestId("batch-problems");
    expect(probs.textContent).toContain("없음: THK_FOAM, E_FOAM");
    expect(probs.className).toContain("muted");
    fireEvent.change(ta, { target: { value: "\uFEFFdoe,RIB_N,THK_TOP,THK_FOAM,E_FOAM\n1,4.6,0.5,2,8\n2,3,0.7,2.5,9\n" } });
    fireEvent.click(within(setup).getByRole("button", { name: "조합 만들기" }));
    const table = await screen.findByRole("table", { name: "조합 미리보기" });
    expect(within(table).getAllByRole("row")).toHaveLength(3);
    expect(within(table).getAllByRole("row")[1].textContent).toContain("run__00001");
    // 정수 파라미터는 반영값(4.6 → 5)
    expect(within(table).getAllByRole("row")[1].textContent).toContain("5");
  });

  it("① 학습 DOE 재사용: 파라미터 이름이 다르면 DOE_PARAM_MISMATCH 안내", async () => {
    renderApp(`${STUDY}/4`, { user: "power" });
    fireEvent.click(await radio("① 학습 DOE 그대로 재사용"));
    const setup = screen.getByRole("region", { name: "1 템플릿·조합" });
    await waitFor(() => expect((within(setup).getByLabelText("① 학습 DOE") as HTMLSelectElement).value).toBe("doe-1"));
    fireEvent.click(within(setup).getByRole("button", { name: "조합 만들기" }));
    expect((await screen.findByTestId("batch-problems")).textContent).toContain("템플릿 파라미터");
    expect((screen.getByRole("button", { name: "입력 생성 + 일괄 예측 실행" }) as HTMLButtonElement).disabled).toBe(true);
  });
});

describe("④ B 결과 표·그래프·커브 (V3-S9-14·18)", () => {
  afterEach(() => vi.restoreAllMocks());

  it("진행 3칸·결과 표: 기본 정렬 첫 응답 낮은 순(값 없는 행은 뒤), DOE # 순으로 바꾸기, 실패 행 사유·실패만 다시 실행", async () => {
    const { server } = renderApp(BATCH, { user: "power" });
    const retries = record(server, /\/predict-batches\/[^/]+\/retry-failed$/);
    const card = await screen.findByRole("region", { name: "결과 표 — B-002" });
    expect(screen.getByTestId("gen-count").textContent).toBe("19 / 20");
    expect(screen.getByRole("region", { name: "파일 위치" }).textContent).toContain("파일 이름은 모두 같고 폴더 번호로 구분합니다");
    expect((within(card).getByLabelText("정렬") as HTMLSelectElement).value).toBe("MaxStress:asc");
    await waitFor(() => expect(rowOrder()).toHaveLength(20));
    const b = server.batches.find((x) => x.id === "pb-2")!;
    const vals = rowOrder().slice(0, 18).map((n) => b.runs[n - 1]);
    expect(vals.length).toBe(18);
    expect(rowOrder().slice(-2)).toEqual([5, 12]); // 예측 실패·생성 실패(값 없음)
    const got = screen.getAllByTestId(/^row-\d+$/).slice(0, 18).map((r) => Number(r.querySelectorAll("td")[6].textContent));
    expect([...got].sort((x, y) => x - y)).toEqual(got);
    fireEvent.change(within(card).getByLabelText("정렬"), { target: { value: "MaxStress:desc" } });
    const desc = screen.getAllByTestId(/^row-\d+$/).slice(0, 18).map((r) => Number(r.querySelectorAll("td")[6].textContent));
    expect([...desc].sort((x, y) => y - x)).toEqual(desc);
    fireEvent.change(within(card).getByLabelText("정렬"), { target: { value: "doe" } });
    expect(rowOrder()).toEqual(Array.from({ length: 20 }, (_, i) => i + 1));
    expect(within(screen.getByTestId("row-12")).getByText(/OUTPUT_MISSING/)).toBeTruthy();
    expect(within(screen.getByTestId("row-5")).getByRole("button", { name: "다시 실행" })).toBeTruthy();
    expect(within(card).queryByRole("button", { name: "일괄 취소" })).toBeNull(); // 끝난 배치
    fireEvent.click(within(card).getByRole("button", { name: "실패만 다시 실행" }));
    await waitFor(() => expect(retries).toHaveLength(1));
    await waitFor(() => expect(server.jobs.some((j) => j.job_type === "PREDICT_BATCH" && j.state === "QUEUED")).toBe(true));
  });

  it("행 선택: 오른쪽 DOE 칸(run_key·결과 목록·경로 복사·단일 예측으로 열기)", async () => {
    renderApp(BATCH, { user: "power" });
    await screen.findByRole("region", { name: "결과 표 — B-002" });
    fireEvent.click(await screen.findByRole("button", { name: "DOE #7 선택" }));
    const panel = await screen.findByRole("region", { name: "DOE #7" });
    expect(panel.textContent).toContain("run__00007");
    expect(within(panel).getByRole("button", { name: /경로 복사/ })).toBeTruthy();
    await waitFor(() => expect(panel.textContent).toContain("num_time_step: 5")); // 결과 목록(컨투어 JSON 트리)
    expect(screen.getByTestId("row-7").className).toContain("selected");
    fireEvent.click(within(panel).getByRole("button", { name: "단일 예측으로 열기" }));
    expect(await screen.findByRole("region", { name: "일괄 예측 B-002 · DOE #7" })).toBeTruthy();
    expect(await screen.findByAltText(/^예측 컨투어 — /)).toBeTruthy();
  });

  it("응답 그래프 선택 규칙: 변수 1+응답 1 = 2D, 변수 2+응답 1 = 3D(plotly 동적 import), 그 밖 = 회색 안내", async () => {
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation((() => ({})) as never);
    renderApp(BATCH, { user: "power" });
    await screen.findByRole("region", { name: "결과 표 — B-002" });
    const plot = screen.getByRole("region", { name: "응답 그래프" });
    // 기본: 첫 파라미터 체크 + 첫 응답 → 2D 점 18개(값 있는 run)
    expect(((await screen.findByRole("checkbox", { name: "THK_TOP" })) as HTMLInputElement).checked).toBe(true);
    expect((screen.getByRole("radio", { name: "MaxStress" }) as HTMLInputElement).checked).toBe(true);
    expect(within(plot).getByTestId("plot2d")).toBeTruthy();
    expect(within(plot).getAllByRole("button", { name: /^점 DOE #\d+$/ })).toHaveLength(18);
    // 점 클릭 = 행 선택
    fireEvent.click(within(plot).getByRole("button", { name: "점 DOE #3" }));
    expect(await screen.findByRole("region", { name: "DOE #3" })).toBeTruthy();
    // 응답 바꾸기
    fireEvent.click(screen.getByRole("radio", { name: "MaxDisp" }));
    expect(within(plot).getByRole("img").getAttribute("aria-label")).toBe("응답 그래프 2D: THK_TOP – MaxDisp");
    // 변수 2개 → 3D
    fireEvent.click(screen.getByRole("checkbox", { name: "RIB_N" }));
    expect(await within(plot).findByTestId("plot3d")).toBeTruthy();
    await waitFor(() => expect(plotly.react).toHaveBeenCalled());
    const [, data] = plotly.react.mock.calls[plotly.react.mock.calls.length - 1] as unknown as [HTMLElement, Record<string, unknown>[]];
    expect(data[0].type).toBe("scatter3d");
    expect((data[0].customdata as number[]).length).toBe(18);
    fireEvent.click(within(plot).getByRole("checkbox", { name: "보간면" }));
    await waitFor(() => expect(((plotly.react.mock.calls[plotly.react.mock.calls.length - 1] as unknown[])[1] as Record<string, unknown>[])[1]).toMatchObject({ type: "mesh3d", delaunayaxis: "z" }));
    // 변수 3개 → 안내
    fireEvent.click(screen.getByRole("checkbox", { name: "E_FOAM" }));
    expect(within(plot).getByTestId("plot-hint").textContent).toBe(PLOT_HINT);
    expect(within(plot).getByTestId("plot-hint").className).toContain("muted");
    // 변수 0개 → 안내
    for (const n of ["THK_TOP", "RIB_N", "E_FOAM"]) fireEvent.click(screen.getByRole("checkbox", { name: n }));
    expect(within(plot).getByTestId("plot-hint").textContent).toBe(PLOT_HINT);
  });

  it("WebGL이 없으면 3D 자리에 안내 한 줄", async () => {
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation((() => null) as never);
    renderApp(BATCH, { user: "power" });
    await screen.findByRole("region", { name: "결과 표 — B-002" });
    fireEvent.click(await screen.findByRole("checkbox", { name: "RIB_N" }));
    expect((await screen.findByTestId("plot3d-nogl")).textContent).toBe(NO_WEBGL_TEXT);
  });

  it("커브 겹쳐보기: 완료 run 모두 흐리게, 고른 run만 진하게(표에서 바꾸면 따라감)", async () => {
    renderApp(BATCH, { user: "power" });
    await screen.findByRole("region", { name: "결과 표 — B-002" });
    const curves = screen.getByRole("region", { name: "커브 겹쳐보기" });
    await waitFor(() => expect(curves.querySelectorAll("path.overlay").length).toBe(18));
    fireEvent.click(screen.getByRole("button", { name: "DOE #9 선택" }));
    await waitFor(() => expect(curves.querySelectorAll("path.overlay.on").length).toBe(1));
    const on = curves.querySelector("path.overlay.on")!;
    expect(on).toBe(curves.querySelectorAll("path.overlay")[17]); // 맨 위(마지막)에 그린다
    expect(within(curves).getByLabelText("계열")).toBeTruthy(); // 계열 2개 → 드롭다운
    fireEvent.click(screen.getByRole("button", { name: "DOE #1 선택" }));
    await waitFor(() => expect(curves.querySelectorAll("path.overlay.on").length).toBe(1));
  });

  it("진행 중 배치: 실행 중·대기 수, 일괄 취소(확인) → 하위 대기 작업 취소", async () => {
    const { server } = renderApp(`${STUDY}/4/batch/pb-3`, { user: "power", batchDemo: "running" });
    const card = await screen.findByRole("region", { name: "결과 표 — B-003" });
    expect(screen.getByTestId("predict-counts").textContent).toBe("1실행 중12대기7완료");
    fireEvent.click(within(card).getByRole("button", { name: "일괄 취소" }));
    const dlg = await screen.findByRole("dialog");
    fireEvent.click(within(dlg).getByRole("button", { name: "일괄 취소" }));
    await waitFor(() => expect(server.batches.find((b) => b.id === "pb-3")!.canceled).toBe(true));
    const kids = server.jobs.filter((j) => (j.params as { batch_run?: { batch_id: string } }).batch_run?.batch_id === "pb-3");
    expect(kids.filter((j) => j.state === "CANCELED")).toHaveLength(12);
    expect(kids.filter((j) => j.cancel_requested)).toHaveLength(1);
  });

  it("응답 정의가 없으면 응답 열 대신 '응답 추출 미구성'", async () => {
    renderApp(BATCH, { user: "power" }, (s) => (s.paramSets.find((p) => p.id === "ps-1")!.responses = []));
    await screen.findByRole("region", { name: "결과 표 — B-002" });
    expect((await screen.findByTestId("no-resp")).textContent).toBe("응답 추출 미구성");
    expect(screen.queryByRole("radio", { name: "MaxStress" })).toBeNull();
  });
});

describe("일괄 예측 규칙(순수 함수)·목 계약", () => {
  const row = (doe: number, v: number | null): PredictBatchRow => ({
    doe_no: doe, run_key: `run__${doe}`, folder: "", values: {}, applied_values: {}, out_of_range: [], state: v == null ? "FAILED" : "SUCCEEDED", code: null, message: null, job_id: null, responses: { R: v },
  });

  it("plotKind 3경우", () => {
    expect(plotKind(["A"], ["R"])).toBe("2d");
    expect(plotKind(["A", "B"], ["R"])).toBe("3d");
    expect(plotKind(["A", "B", "C"], ["R"])).toBe("none");
    expect(plotKind([], ["R"])).toBe("none");
    expect(plotKind(["A"], [])).toBe("none");
  });

  it("sortRows: 값 없는 행은 방향과 무관하게 뒤", () => {
    const rows = [row(1, 3), row(2, null), row(3, 1), row(4, 2)];
    expect(sortRows(rows, "R:asc").map((r) => r.doe_no)).toEqual([3, 4, 1, 2]);
    expect(sortRows(rows, "R:desc").map((r) => r.doe_no)).toEqual([1, 4, 3, 2]);
    expect(sortRows(rows, "doe").map((r) => r.doe_no)).toEqual([1, 2, 3, 4]);
  });

  it("downsampleMinMax: 점 수 ≤ 상한, 처음·끝·전체 최소·최대 보존", () => {
    const x = Array.from({ length: 5000 }, (_, i) => i);
    const y = x.map((i) => Math.sin(i / 37) * (i === 2718 ? 9 : 1) - (i === 4321 ? 7 : 0));
    const d = downsampleMinMax(x, y, 500);
    expect(d.x.length).toBeLessThanOrEqual(500);
    expect(d.x[0]).toBe(0);
    expect(d.x[d.x.length - 1]).toBe(4999);
    expect(Math.max(...d.y)).toBe(Math.max(...y));
    expect(Math.min(...d.y)).toBe(Math.min(...y));
    expect([...d.x].sort((a, b) => a - b)).toEqual(d.x);
    expect(downsampleMinMax([1, 2], [3, 4], 500)).toEqual({ x: [1, 2], y: [3, 4] });
  });

  it("overlayLines: 상한 200 run, 고른 run 하나만 진하게·마지막", () => {
    const series = Array.from({ length: 230 }, (_, i) => ({ doe_no: i + 1, run_key: `run__${i + 1}`, x: [0, 1], y: [i, i + 1] }));
    const c: BatchCurves = { names: ["a"], name: "a", truncated: true, downsampled: false, series };
    const lines = overlayLines(c, 5);
    expect(lines).toHaveLength(200);
    expect(lines.filter((l) => l.className.includes(" on"))).toHaveLength(1);
    expect(lines[lines.length - 1].name).toBe("run__5");
  });

  it("목: API 생성 요청의 batch_run은 422, 잘못된 조합은 422 BATCH_SOURCE_INVALID, 동시 수 범위", async () => {
    const { MockServer } = await import("../mock/server");
    const s = new MockServer({ user: "power" });
    const h = new Headers({ "X-PhysicsAI-Request": "1" });
    const post = (job_type: string, params: Record<string, unknown>) => s.handle("POST", "/studies/s-cushion/jobs", new URLSearchParams(), { job_type, params }, h);
    const code = (r: { body?: unknown }) => (r.body as { detail?: { code?: string } }).detail?.code;
    expect(code(post("PREDICT", { input_mode: "prepared", input_path: "E:/shared/AI_WORK/x/a.rad", batch_run: { batch_id: "pb-2", doe_no: 1 } }))).toBe("INVALID_PARAMS");
    expect(code(post("PREDICT_BATCH", { param_set_id: "ps-1", model_id: null, multi_execution: 2, source: { kind: "table", text: "A\n1\n" } }))).toBe("BATCH_SOURCE_INVALID");
    expect(code(post("PREDICT_BATCH", { param_set_id: "ps-1", model_id: null, multi_execution: 9, source: { kind: "lhs", count: 3, seed: 1 } }))).toBe("INVALID_PARAMS");
    expect(code(post("PREDICT_BATCH", { param_set_id: "ps-x", model_id: null, multi_execution: 2, source: { kind: "lhs", count: 3, seed: 1 } }))).toBe("PREREQUISITE_MISSING");
    const okr = post("PREDICT_BATCH", { param_set_id: "ps-1", model_id: null, multi_execution: 2, source: { kind: "lhs", count: 3, seed: 1 } });
    expect(okr.status).toBe(201);
    expect((okr.body as { params: Record<string, unknown> }).params).toMatchObject({ batch_no: 3 });
    const csv = s.handle("GET", "/predict-batches/pb-2/table.csv", new URLSearchParams(), null, h);
    expect(csv.text!.startsWith("\uFEFFdoe_no,run_key,folder,THK_TOP,THK_FOAM,E_FOAM,RIB_N,MaxStress,MaxDisp,Energy,state\n")).toBe(true);
    const list = s.handle("GET", "/jobs", new URLSearchParams("study_id=s-cushion&job_type=PREDICT&limit=50"), null, h);
    expect((list.body as { batch?: { label: string; doe_no: number | null } | null }[]).some((j) => j.batch?.label === "B-002" && typeof j.batch.doe_no === "number")).toBe(true);
  });
});
