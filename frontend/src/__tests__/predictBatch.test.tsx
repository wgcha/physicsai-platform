// V3-S9-14·17·18(화면, phase3.md §14.8·§14.9): 입력 방식 3개·기억, A 템플릿 요청 body·mesh_only 진행 단계, 템플릿 관리(조립 "없음"·응답 추가),
// B 미리보기·실행 body, 결과 표 정렬·행 선택·실패만 다시, ⑤ 링크 카드, 다운샘플. (응답 그래프·커브 화면 시험은 S14로 analysisScreen.test.tsx에 있다) 목 서버(mock/predictBatch.ts) 기준.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { renderApp, STUDY } from "../test/render";
import type { MockServer } from "../mock/server";
import { ok } from "../mock/route";
import { downsampleMinMax } from "../lib/downsample";
import { plotKind, sortRows } from "../stages/stage4/batch/batchTable";
import { overlayLines } from "../analysis/viz/CurveOverlay";
import type { BatchCurves, PredictBatchRow } from "../api";
import { DESCRIPTIONS, SAMPLING_LABEL } from "../lib/sampling";

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
/** S15: 표본 방식 드롭다운에서 kind 고르기(기본은 최적화 LHS) */
const pickKind = (setup: HTMLElement, kind: string) => fireEvent.change(within(setup).getByLabelText("표본 방식"), { target: { value: kind } });
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
    // input-kind.md §10: 회색 메타 줄 대신 능력 배지(툴팁에 tpl·CAD·등록일)
    expect(within(card).getByTestId("template-badge").textContent).toBe("조립·쿠션 가능");
    expect(within(card).getByTestId("template-meta").title).toMatch(/^tpl · CAD · 조립 폴더 포함 · \d\d-\d\d 등록$/);
    expect(stepLabels()).toEqual(["1 형상 생성(SimLab)", "2 메시 연결(HyperMesh)", "3 조립(Radioss 입력)", "4 예측(PhysicsAI)", "5 결과"]);

    fireEvent.change(sel, { target: { value: "ps-2" } });
    const card2 = await screen.findByRole("region", { name: "템플릿" });
    await waitFor(() => expect(within(card2).getByTestId("template-badge").textContent).toBe("쿠션만"));
    expect(within(card2).getByTestId("template-meta").title).toContain("조립 폴더 없음(메시 단독)");
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
    const kindLine = await within(card).findByTestId("ps-input-kind");
    expect(kindLine.textContent).toContain("쿠션만");
    expect(kindLine.title).toContain("조립 폴더 없음(메시 단독)");
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
    expect((within(setup).getByLabelText("표본 방식") as HTMLSelectElement).value).toBe("lhs_opt"); // S15: 기본 = 최적화 LHS(추천)
    pickKind(setup, "lhs"); // 기존 LHS body 불변(V3-S9-14)
    expect(within(setup).getByRole("option", { name: "LHS(무작위 층화)" })).toBeTruthy();
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
    const setup = await screen.findByRole("region", { name: "1 템플릿·조합" });
    pickKind(setup, "table");
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
    const setup = await screen.findByRole("region", { name: "1 템플릿·조합" });
    pickKind(setup, "train_doe");
    await waitFor(() => expect((within(setup).getByLabelText("① 학습 DOE") as HTMLSelectElement).value).toBe("doe-1"));
    fireEvent.click(within(setup).getByRole("button", { name: "조합 만들기" }));
    expect((await screen.findByTestId("batch-problems")).textContent).toContain("템플릿 파라미터");
    expect((screen.getByRole("button", { name: "입력 생성 + 일괄 예측 실행" }) as HTMLButtonElement).disabled).toBe(true);
  });
});

describe("④ B 표본 방식 (V3-S15-12)", () => {
  beforeEach(() => localStorage.setItem(KEY, "batch"));
  afterEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
  });
  const NAMES4 = ["THK_TOP", "THK_FOAM", "E_FOAM", "RIB_N"];
  const open = async () => {
    const r = renderApp(`${STUDY}/4`, { user: "power" });
    const setup = await screen.findByRole("region", { name: "1 템플릿·조합" });
    const previews = record(r.server, /\/predict-batches\/preview$/);
    return { ...r, setup, previews };
  };
  const make = async (setup: HTMLElement) => {
    fireEvent.click(within(setup).getByRole("button", { name: "조합 만들기" }));
    await screen.findByTestId("preview-sampling");
  };

  it("드롭다운: 4묶음·10방식 순서, 기본 최적화 LHS + 추천 배지 + 설명 4줄(계약 문구)·권장 run 계산값, 저장하지 않음, 고를 때마다 설명이 바뀐다", async () => {
    const { setup } = await open();
    const sel = within(setup).getByLabelText("표본 방식") as HTMLSelectElement;
    expect(sel.value).toBe("lhs_opt");
    const groups = [...sel.querySelectorAll("optgroup")];
    expect(groups.map((g) => [g.label, [...g.querySelectorAll("option")].map((o) => o.value)])).toEqual([
      ["공간 채움(AI 학습·대리모델)", ["lhs_opt", "sobol", "lhs"]],
      ["요인 설계(경향·선별)", ["fullfact", "fracfact", "pb"]],
      ["2차 응답면", ["bbd", "ccd"]],
      ["직접 지정", ["table", "train_doe"]],
    ]);
    expect([...sel.options].map((o) => o.textContent)).toEqual([
      "최적화 LHS · 추천", "Sobol(스크램블 QMC)", "LHS(무작위 층화)", "전체 요인", "부분 요인(2수준)", "Plackett–Burman", "Box–Behnken", "중심 합성(CCD)", "표 붙여넣기 / CSV", "① 학습 DOE 그대로 재사용",
    ]);
    const desc = () => within(setup).getByTestId("samp-desc");
    expect(desc().getAttribute("data-desc-id")).toBe("lhs_opt");
    expect(within(desc()).getByTestId("samp-badge").textContent).toBe("추천");
    expect([1, 2, 3, 4].map((n) => within(desc()).getByTestId(`samp-line-${n}`).firstChild!.textContent)).toEqual(DESCRIPTIONS.lhs_opt.lines);
    expect(within(desc()).getByTestId("samp-calc").textContent!.trim()).toBe("현재 변수 4개 → 권장 40");
    expect((within(setup).getByLabelText("조합 수") as HTMLInputElement).value).toBe("40"); // 기본 = 권장 계산값
    expect(Object.keys(localStorage).filter((k) => /sampl|method/i.test(k))).toEqual([]);
    fireEvent.change(sel, { target: { value: "sobol" } });
    expect(desc().getAttribute("data-desc-id")).toBe("sobol");
    expect(within(desc()).queryByTestId("samp-badge")).toBeNull(); // 추천 배지는 최적화 LHS만
    expect(within(desc()).getByTestId("samp-line-2").textContent).toBe(DESCRIPTIONS.sobol.lines[1]);
    fireEvent.change(sel, { target: { value: "bbd" } });
    expect(within(desc()).getByTestId("samp-calc").textContent!.trim()).toBe("현재 변수 4개 → 25 run");
    fireEvent.change(sel, { target: { value: "table" } });
    expect(desc().getAttribute("data-desc-id")).toBe("table");
    expect(within(desc()).queryByTestId("samp-calc")).toBeNull();
    expect(SAMPLING_LABEL.table).toBe("표 붙여넣기 / CSV");
  });

  it("최적화 LHS: body(범위는 고친 변수만, 기준 세그먼트), 미리보기 머리 '실제 run N개 · 방식' + quality, 7개 kind 모두 같은 규칙", async () => {
    const { setup, previews } = await open();
    fireEvent.change(within(setup).getByLabelText("THK_TOP 최대"), { target: { value: "1.5" } });
    fireEvent.change(within(setup).getByLabelText("조합 수"), { target: { value: "12" } });
    fireEvent.click(within(setup).getByRole("button", { name: "상관 최소" }));
    await make(setup);
    expect(previews[0]).toEqual({ param_set_id: "ps-1", source: { kind: "lhs_opt", count: 12, seed: 1, ranges: { THK_TOP: [0.3, 1.5] }, criterion: "corr" } });
    expect(screen.getByTestId("preview-sampling").textContent).toContain("실제 run 12개 · 최적화 LHS");
    expect(screen.getByTestId("preview-quality").textContent).toMatch(/최소 거리 [\d.]+ · 최대 상관 [\d.]+/);
    expect(within(screen.getByRole("table", { name: "조합 미리보기" })).getAllByRole("row")).toHaveLength(13); // 머리 + 12행(20행 이하)
    // 범위를 고치지 않으면 ranges null, 조합 수는 권장값을 따라간다
    fireEvent.change(within(setup).getByLabelText("THK_TOP 최대"), { target: { value: "1.2" } });
    fireEvent.change(within(setup).getByLabelText("조합 수"), { target: { value: "40" } });
    fireEvent.click(within(setup).getByRole("button", { name: "최소 거리" }));
    await make(setup);
    expect(previews[1].source).toEqual({ kind: "lhs_opt", count: 40, seed: 1, ranges: null, criterion: "maximin" });
  });

  it("Sobol: run 수 드롭다운(2^m, 기본 권장 64), 시드, body, 2의 거듭제곱이 아니면 서버 problems(COUNT_NOT_POW2)", async () => {
    const { server, setup, previews } = await open();
    fireEvent.change(within(setup).getByLabelText("표본 방식"), { target: { value: "sobol" } });
    const cnt = within(setup).getByLabelText("run 수") as HTMLSelectElement;
    expect([...cnt.options].map((o) => o.value)).toEqual(["4", "8", "16", "32", "64", "128"]);
    expect(cnt.value).toBe("64");
    fireEvent.change(cnt, { target: { value: "16" } });
    fireEvent.change(within(setup).getByLabelText("시드"), { target: { value: "5" } });
    await make(setup);
    expect(previews[0].source).toEqual({ kind: "sobol", count: 16, seed: 5, ranges: null, continue_from: null });
    expect(screen.getByTestId("preview-sampling").textContent).toContain("실제 run 16개 · Sobol(스크램블 QMC)");
    // 서버가 막는 조합: 목에서 직접 확인(드롭다운은 2^m만 허용)
    const r = server.handle("POST", "/studies/s-cushion/predict-batches/preview", new URLSearchParams(), { param_set_id: "ps-1", source: { kind: "sobol", count: 12, seed: 1, ranges: null, continue_from: null } }, new Headers({ "X-PhysicsAI-Request": "1" }));
    expect((r.body as { problems: { code: string }[] }).problems.map((p) => p.code)).toEqual(["COUNT_NOT_POW2"]);
    expect((r.body as { sampling: { kind: string } }).sampling.kind).toBe("sobol"); // problems가 있어도 sampling은 채운다
  });

  it("Sobol 이어서 추가: 같은 템플릿 Sobol 배치만 후보, 범위·시드 비활성(이전 값), run 수 기본 = 이전 합계, body, 미리보기 notes", async () => {
    const r = renderApp(`${STUDY}/4`, { user: "power" }, (srv) => {
      // 시드 배치 B-002(LHS) → Sobol 16개·시드 3으로 바꿔 후보로 만든다
      const b = srv.batches.find((x) => x.id === "pb-2")!;
      b.source_kind = "SOBOL";
      b.meta = { count: 16, m: 4, seed: 3, offset: 0, scramble: true, continue_from: null, generator: "scipy 1.17.1", active: NAMES4, fixed: [], ranges: { THK_TOP: [0.3, 1.1], THK_FOAM: [1, 3], E_FOAM: [2, 20], RIB_N: [2, 8] } };
    });
    const setup = await screen.findByRole("region", { name: "1 템플릿·조합" });
    const previews = record(r.server, /\/predict-batches\/preview$/);
    fireEvent.change(within(setup).getByLabelText("표본 방식"), { target: { value: "sobol" } });
    const check = within(setup).getByRole("checkbox", { name: "이전 Sobol 배치에 이어서 추가" }) as HTMLInputElement;
    await waitFor(() => expect(check.disabled).toBe(false));
    fireEvent.click(check);
    const pick = within(setup).getByLabelText("이어서 추가할 배치") as HTMLSelectElement;
    expect([...pick.options].map((o) => o.textContent)).toEqual(["B-002 · 16개 · 시드 3"]);
    expect((within(setup).getByLabelText("시드") as HTMLInputElement).disabled).toBe(true);
    expect((within(setup).getByLabelText("시드") as HTMLInputElement).value).toBe("3");
    await waitFor(() => expect((within(setup).getByLabelText("THK_TOP 최대") as HTMLInputElement).value).toBe("1.1")); // 이전 범위를 보여 준다
    expect((within(setup).getByLabelText("THK_TOP 최대") as HTMLInputElement).disabled).toBe(true);
    expect((within(setup).getByLabelText("run 수") as HTMLSelectElement).value).toBe("16"); // 이전 합계
    await make(setup);
    expect(previews[0].source).toEqual({ kind: "sobol", count: 16, seed: null, ranges: null, continue_from: "pb-2" });
    expect(screen.getByTestId("preview-note").textContent).toBe("B-002과 합치면 32개(균형 유지)");
    // 체크를 끄면 다시 새 수열(시드·범위 입력 활성)
    fireEvent.click(check);
    expect((within(setup).getByLabelText("시드") as HTMLInputElement).disabled).toBe(false);
  });

  it("Sobol 이어서 추가 후보가 없으면 체크 비활성 + 안내(LHS 배치는 후보가 아님)", async () => {
    const { setup } = await open();
    fireEvent.change(within(setup).getByLabelText("표본 방식"), { target: { value: "sobol" } });
    await waitFor(() => expect(within(setup).getByText("같은 템플릿의 Sobol 배치가 없습니다.")).toBeTruthy());
    expect((within(setup).getByRole("checkbox", { name: "이전 Sobol 배치에 이어서 추가" }) as HTMLInputElement).disabled).toBe(true);
  });

  it("전체 요인: 범위 표 '수준' 열(기본 3^k ≤ R이면 3), 곱 run 수 표시, body levels, 상한 초과는 안내", async () => {
    const { setup, previews } = await open();
    fireEvent.change(within(setup).getByLabelText("표본 방식"), { target: { value: "fullfact" } });
    expect(NAMES4.map((n) => (within(setup).getByLabelText(`${n} 수준`) as HTMLInputElement).value)).toEqual(["3", "3", "3", "3"]);
    expect(within(setup).getByTestId("fullfact-runs").textContent).toContain("3 × 3 × 3 × 3 = 81");
    fireEvent.change(within(setup).getByLabelText("RIB_N 수준"), { target: { value: "2" } });
    expect(within(setup).getByTestId("fullfact-runs").textContent).toContain("= 54");
    await make(setup);
    expect(previews[0].source).toEqual({ kind: "fullfact", levels: { THK_TOP: 3, THK_FOAM: 3, E_FOAM: 3, RIB_N: 2 }, ranges: null });
    expect(screen.getByTestId("preview-sampling").textContent).toContain("실제 run 54개 · 전체 요인");
    fireEvent.change(within(setup).getByLabelText("RIB_N 수준"), { target: { value: "10" } });
    expect(within(setup).getByTestId("fullfact-runs").textContent).toContain("상한 200개 초과");
  });

  it("부분 요인 해상도 V(기본)·IV, CCD α 면중심(기본)·내접, PB·BBD는 범위 표만 — kind별 body와 run 수", async () => {
    const { setup, previews } = await open();
    const sel = within(setup).getByLabelText("표본 방식");
    fireEvent.change(sel, { target: { value: "fracfact" } });
    expect(within(setup).getByRole("button", { name: "V" }).getAttribute("aria-pressed")).toBe("true");
    await make(setup);
    fireEvent.click(within(setup).getByRole("button", { name: "IV" }));
    await make(setup);
    expect(previews.map((p) => p.source)).toEqual([{ kind: "fracfact", resolution: 5, ranges: null }, { kind: "fracfact", resolution: 4, ranges: null }]);
    expect(screen.getByTestId("preview-sampling").textContent).toContain("실제 run 8개"); // k = 4, 해상도 IV
    expect(screen.getByTestId("samp-calc").textContent!.trim()).toBe("현재 변수 4개 · 해상도 IV → 8 run");
    fireEvent.change(sel, { target: { value: "ccd" } });
    expect(within(setup).getByRole("button", { name: "면중심" }).getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(within(setup).getByRole("button", { name: "내접" }));
    await make(setup);
    expect(previews[2].source).toEqual({ kind: "ccd", alpha: "inscribed", ranges: null });
    expect(screen.getByTestId("preview-sampling").textContent).toContain("실제 run 25개");
    for (const [kind, runs] of [["pb", 8], ["bbd", 25]] as const) {
      fireEvent.change(sel, { target: { value: kind } });
      expect(within(setup).queryByRole("group", { name: "해상도" })).toBeNull();
      await make(setup);
      expect(previews[previews.length - 1].source).toEqual({ kind, ranges: null });
      expect(screen.getByTestId("preview-sampling").textContent).toContain(`실제 run ${runs}개`);
    }
  });

  it("미리보기 notes: run 부족 안내는 회색 줄, 범위 오류(RANGE_INVALID)·변수 수 밖(DESIGN_UNSUPPORTED)은 problems", async () => {
    const { setup } = await open();
    fireEvent.change(within(setup).getByLabelText("조합 수"), { target: { value: "4" } });
    await make(setup);
    expect(screen.getAllByTestId("preview-note").map((n) => n.textContent)).toEqual(["run이 6개보다 적어 ⑤ 영향도는 계산되지 않습니다"]);
    fireEvent.change(within(setup).getByLabelText("THK_TOP 최대"), { target: { value: "0.3" } }); // 최소 = 최대
    fireEvent.click(within(setup).getByRole("button", { name: "조합 만들기" }));
    await waitFor(() => expect(screen.getByTestId("batch-problems").textContent).toContain("THK_TOP 범위는 최소 < 최대"));
  });

  it("Box–Behnken은 변수 3개 이상: 템플릿 변수가 2개면 DESIGN_UNSUPPORTED 안내", async () => {
    renderApp(`${STUDY}/4`, { user: "power" }, (srv) => {
      srv.paramSets[0].parameters = srv.paramSets[0].parameters.slice(0, 2);
    });
    const setup = await screen.findByRole("region", { name: "1 템플릿·조합" });
    pickKind(setup, "bbd");
    fireEvent.click(within(setup).getByRole("button", { name: "조합 만들기" }));
    expect((await screen.findByTestId("batch-problems")).textContent).toContain("Box–Behnken은 범위가 있는 변수가 3개 이상이어야 합니다");
  });

  it("작업 생성 body = 미리본 source, DB source_kind·sampling(상세)·목록 sampling, 배치 결과 머리 '표본: …'", async () => {
    const { server, setup, previews } = await open();
    const jobs = record(server, /\/studies\/[^/]+\/jobs$/);
    fireEvent.change(within(setup).getByLabelText("표본 방식"), { target: { value: "sobol" } });
    fireEvent.change(within(setup).getByLabelText("run 수"), { target: { value: "16" } });
    await make(setup);
    const run = screen.getByRole("button", { name: "입력 생성 + 일괄 예측 실행" }) as HTMLButtonElement;
    fireEvent.change(screen.getByLabelText(/입력 생성 동시 실행 수/), { target: { value: "2" } });
    await waitFor(() => expect(run.disabled).toBe(false));
    fireEvent.click(run);
    await waitFor(() => expect(jobs).toHaveLength(1));
    expect((jobs[0].params as { source: unknown }).source).toEqual(previews[0].source);
    expect(await screen.findByRole("region", { name: "결과 표 — B-003" })).toBeTruthy();
    expect(server.batches.find((b) => b.batch_no === 3)!.source_kind).toBe("SOBOL");
    expect((await screen.findByTestId("batch-sampling")).textContent).toBe("표본: Sobol 16개 · 시드 1");
    const d = server.handle("GET", "/predict-batches/" + server.batches.find((b) => b.batch_no === 3)!.id, new URLSearchParams(), null, new Headers()).body as { sampling: { influence_class: string; kind: string } };
    expect(d.sampling).toMatchObject({ kind: "sobol", influence_class: "formal" });
    const list = server.handle("GET", "/studies/s-cushion/predict-batches", new URLSearchParams(), null, new Headers()).body as { label: string; sampling: unknown }[];
    expect(list.find((b) => b.label === "B-003")!.sampling).toMatchObject({ kind: "sobol", count: 16, seed: 1, offset: 0 });
  });

  it("배치 결과 머리: 이어서 추가·부분 요인 요약 문구", async () => {
    renderApp(BATCH, { user: "power" }, (srv) => {
      const b = srv.batches.find((x) => x.id === "pb-2")!;
      b.source_kind = "SOBOL";
      b.meta = { count: 16, seed: 3, offset: 16, continue_from: { batch_id: "pb-1", label: "B-001" }, active: NAMES4, fixed: [], ranges: {} };
    });
    expect((await screen.findByTestId("batch-sampling")).textContent).toBe("표본: Sobol 16개 · 시드 3 · B-001에 이어서");
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

  it("S14: 그래프 카드 대신 '⑤ 결과분석에서 열기' 링크 카드(/stage/analysis?source=batch&id=…), ④에는 분석 그래프·커브 카드 없음", async () => {
    renderApp(BATCH, { user: "power" });
    await screen.findByRole("region", { name: "결과 표 — B-002" });
    const card = screen.getByRole("region", { name: "결과분석" });
    expect(within(card).getByTestId("analysis-link").getAttribute("href")).toBe(`${STUDY}/analysis?source=batch&id=pb-2`);
    expect(screen.queryByRole("region", { name: "응답 그래프" })).toBeNull();
    expect(screen.queryByRole("region", { name: "커브 겹쳐보기" })).toBeNull();
    expect(screen.queryByRole("checkbox", { name: "THK_TOP" })).toBeNull(); // 그래프 변수 체크는 ⑤로 이동
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
