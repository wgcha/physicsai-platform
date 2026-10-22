// native 형상 엔진 화면(geometry-engine.md §8): ④ 등록 엔진 선택·202 작업, 세트 상세(준비 상태·피처 표·PNG·대칭 분리),
// 검사 기준(고급), 3S 쉘 두께 PROP, 4B 다중 baseline 매칭표, ① native 파라미터 표, 엔진 혼용 안내.
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { renderApp, STUDY } from "../test/render";
import type { MockServer } from "../mock/server";
import { nativeTrainParams } from "../mock/geometry";

const ROOT = "E:/shared/AI_WORK/cushion/00_inbox";
type Call = { m: string; p: string; b: Record<string, unknown> | null };

function record(server: MockServer, re: RegExp): Call[] {
  const calls: Call[] = [];
  const orig = server.handle.bind(server);
  server.handle = (m, p, q, b, h) => {
    if (m !== "GET" && re.test(p)) calls.push({ m, p, b });
    return orig(m, p, q, b, h);
  };
  return calls;
}

const nativeCurrent = (s: MockServer) => s.paramSets.forEach((p) => (p.is_current = p.id === "ps-n1"));

async function openManage() {
  fireEvent.click(await screen.findByRole("button", { name: "템플릿 관리" }));
  return screen.findByRole("region", { name: "템플릿 관리" });
}

describe("④ 등록: 형상 엔진 선택(§8)", () => {
  afterEach(() => vi.restoreAllMocks());

  it("native: tpl 칸 숨김·기준 메시 안내 → 등록 = 202 작업 진행 → 끝나면 native 세트", async () => {
    const { server } = renderApp(`${STUDY}/4`, { user: "power" });
    const calls = record(server, /\/param-sets$/);
    const card = await openManage();
    fireEvent.click(within(card).getByRole("button", { name: "새로 등록" }));
    const form = within(card).getByTestId("ps-discover");
    const group = within(form).getByRole("radiogroup", { name: "형상 엔진" });
    expect(within(group).getByRole("radio", { name: "Altair" }).getAttribute("aria-checked")).toBe("true"); // 기본 = engine_default
    fireEvent.click(within(group).getByRole("radio", { name: "Native" }));
    fireEvent.click(within(form).getByRole("checkbox", { name: "조립 매칭 사용" })); // 기본 = 조립 매칭 — 끄면 기존 기준본·RENUM 방식
    expect(within(form).getByText(/104_replace_node_elem\.inc 필요/)).toBeTruthy();
    fireEvent.change(within(form).getByLabelText("프로젝트 폴더 경로"), { target: { value: `${ROOT}/native_project` } });
    fireEvent.click(within(form).getByRole("button", { name: "찾기" }));
    expect(await within(form).findByText("01_CAD/cushion_base.step")).toBeTruthy();
    expect(within(form).queryByText("tpl")).toBeNull();
    expect(within(form).getByTestId("ps-discover-params").textContent).toBe("형상 준비에서 피처로 만듭니다");
    fireEvent.click(within(form).getByRole("button", { name: "등록" }));
    await waitFor(() => expect(calls.length).toBe(1));
    expect(calls[0].b).toMatchObject({ engine: "native", mode: "discover", choice: { cad: "01_CAD/cushion_base.step", radioss_assem: "RADIOSS_ASSEM" } });
    expect((calls[0].b!.choice as Record<string, unknown>).tpl).toBeUndefined();
    const job = server.jobs.find((j) => j.job_type === "PARAM_SET_NATIVE")!;
    expect(job.params).toMatchObject({ mode: "new" });
    act(() => server.finishAll());
    await waitFor(() => expect(server.paramSets[0].engine).toBe("native"));
    expect(await screen.findByTestId("native-detail")).toBeTruthy();
    expect(job.steps.find((s) => s.step_key === "BL_MAP")?.state).toBe("SKIPPED"); // 단일 baseline
  });

  it("기준 메시 inc가 없으면 문제 표시·등록 불가", async () => {
    renderApp(`${STUDY}/4`, { user: "power" });
    const card = await openManage();
    fireEvent.click(within(card).getByRole("button", { name: "새로 등록" }));
    const form = within(card).getByTestId("ps-discover");
    fireEvent.click(within(form).getByRole("radio", { name: "Native" }));
    fireEvent.click(within(form).getByRole("checkbox", { name: "조립 매칭 사용" }));
    fireEvent.change(within(form).getByLabelText("프로젝트 폴더 경로"), { target: { value: `${ROOT}/noinc` } });
    fireEvent.click(within(form).getByRole("button", { name: "찾기" }));
    expect(await within(form).findByText(/104_replace_node_elem\.inc가 없습니다/)).toBeTruthy();
    expect((within(form).getByRole("button", { name: "등록" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("native를 쓸 수 없으면 비활성 + 사유", async () => {
    renderApp(`${STUDY}/4`, { user: "power", disabledFeatures: ["train_resp", "geometry_native"] });
    const card = await openManage();
    fireEvent.click(within(card).getByRole("button", { name: "새로 등록" }));
    await waitFor(() => expect((within(card).getByRole("radio", { name: "Native" }) as HTMLButtonElement).disabled).toBe(true));
    expect(within(card).getByTestId("native-off-reason").textContent).toMatch(/paicad/);
  });
});

describe("④ native 세트 상세(§8)", () => {
  afterEach(() => vi.restoreAllMocks());

  it("엔진 배지·준비 상태, 피처 표(종류·위치형 mm·가능 범위 초과·기준면 자동), 행 클릭 = PNG(없으면 생략)", async () => {
    renderApp(`${STUDY}/4`, { user: "power", geometry: "native" }, nativeCurrent);
    const card = await openManage();
    expect(within(card).getByTestId("engine-badge").textContent).toBe("Native");
    expect(within(card).getByTestId("prep-status").textContent).toBe("형상 준비됨");
    const table = await within(card).findByRole("table", { name: "형상 피처 표" });
    const hole = within(table).getByText("CUSH_L_HOLE_U_1").closest("tr")!;
    expect(hole.textContent).toContain("구멍 위치 U");
    expect((within(hole).getByLabelText("CUSH_L_HOLE_U_1 하한") as HTMLInputElement).value).toBe("25");
    expect((within(hole).getByLabelText("CUSH_L_HOLE_U_1 상한") as HTMLInputElement).value).toBe("35");
    expect(hole.textContent).toContain("Δ −5 / +5"); // 위치형 = 절대 mm + 공칭 대비 Δ
    expect(within(hole).getByRole("img", { name: /모핑 실패 가능/ })).toBeTruthy(); // 가능 범위 27~40 밖(25) = 경고 아이콘
    const rib = within(table).getByText("CUSH_L_RIB_T_2").closest("tr")!;
    expect(rib.textContent).toContain("변경 불가(양면 접촉)");
    expect((within(rib).getByLabelText("CUSH_L_RIB_T_2 사용") as HTMLInputElement).checked).toBe(true); // 세트 정의에 있으면 사용(양면 접촉 = 경고)
    expect(within(rib).getByRole("img", { name: /양면 접촉/ })).toBeTruthy();
    expect(within(table).getByText("CUSH_L_THK_1").closest("tr")!.textContent).toContain("자동");
    fireEvent.click(hole);
    const fig = await within(card).findByTestId("feature-png");
    await waitFor(() => expect(fig.querySelector("img")?.getAttribute("alt")).toBe("CUSH_L_HOLE_U_1 하이라이트"));
    fireEvent.click(within(table).getByText("CUSH_L_FILLET_R_1"));
    await waitFor(() => expect(within(card).queryByTestId("feature-png")).toBeNull());
    expect(within(card).getByText("하이라이트 그림을 만들지 못했습니다")).toBeTruthy(); // PNG_RENDER_FAILED 한국어
  });

  it("대칭 그룹 분리 → PATCH symmetry_split, 다시 묶기", async () => {
    const { server } = renderApp(`${STUDY}/4`, { user: "power", geometry: "native" }, nativeCurrent);
    const calls = record(server, /\/param-sets\/ps-n1$/);
    const card = await openManage();
    const table = await within(card).findByRole("table", { name: "형상 피처 표" });
    fireEvent.click(within(table).getByRole("button", { name: "분리" }));
    await waitFor(() => expect(calls[0]?.b).toEqual({ geom_options: { symmetry_split: ["G1"] } }));
    expect(await within(card).findByRole("button", { name: "묶기" })).toBeTruthy();
    fireEvent.click(within(card).getByRole("button", { name: "묶기" }));
    await waitFor(() => expect(calls[1]?.b).toEqual({ geom_options: null }));
  });

  it("STALE이면 '형상 준비 다시' → 작업 → READY", async () => {
    const { server } = renderApp(`${STUDY}/4`, { user: "power", geometry: "native" }, (s) => {
      nativeCurrent(s);
      s.paramSets.find((p) => p.id === "ps-n1")!.native = { prep_status: "STALE", prep_reason: "엔진 버전이 바뀌었습니다", feature_count: 5, props_scanned: false, shell_only: false, kind: "solid", view_status: "MISSING", vars_revision: 0, vars_count: 5 };
    });
    const card = await openManage();
    expect(within(card).getByTestId("prep-status").textContent).toBe("형상 다시 준비 필요");
    fireEvent.click(within(card).getByRole("button", { name: "형상 준비 다시" }));
    await waitFor(() => expect(server.jobs.some((j) => j.job_type === "PARAM_SET_NATIVE" && j.params.mode === "reprep")).toBe(true));
    act(() => server.finishAll());
    await waitFor(() => expect(within(card).getByTestId("prep-status").textContent).toBe("형상 준비됨"));
  });

  it("검사 기준(고급): 접힘 기본 닫힘, 칸 검사·저장(PATCH)·기본값으로, 서버 422 문구", async () => {
    const { server } = renderApp(`${STUDY}/4`, { user: "power", geometry: "native" }, nativeCurrent);
    const calls = record(server, /\/param-sets\/ps-n1$/);
    const card = await openManage();
    const box = (await within(card).findByTestId("geom-options")).closest("details")!;
    expect(box.open).toBe(false);
    expect(within(box).getByText("검사 기준(고급)")).toBeTruthy();
    const ratio = within(box).getByLabelText("최소 엣지 비(기준 대비)") as HTMLInputElement;
    expect(ratio.placeholder).toBe("0.8");
    fireEvent.change(ratio, { target: { value: "1.5" } });
    fireEvent.click(within(box).getByRole("button", { name: "저장" }));
    expect(await within(box).findByText("0 초과 1 이하")).toBeTruthy();
    expect(calls.length).toBe(0);
    fireEvent.change(ratio, { target: { value: "0.7" } });
    fireEvent.change(within(box).getByLabelText("위치 기준"), { target: { value: "proportional" } });
    fireEvent.change(within(box).getByLabelText("기본 범위 ∓mm"), { target: { value: "3" } });
    fireEvent.click(within(box).getByRole("button", { name: "저장" }));
    await waitFor(() => expect(calls[0]?.b).toEqual({ geom_options: { quality: { min_edge_ratio: 0.7 }, position_ref: "proportional", extract: { position_range_mm: 3 } } }));
    await waitFor(() => expect(server.paramSets.find((p) => p.id === "ps-n1")!.geom_options_effective).toMatchObject({ quality: { min_edge_ratio: 0.7, dt_ratio_min: 0.8 } }));
    // 기본값으로 = 해당 키 제거
    const posRef = within(box).getByLabelText("위치 기준").closest("label")!;
    fireEvent.click(within(posRef).getByRole("button", { name: "기본값으로" }));
    fireEvent.click(within(box).getByRole("button", { name: "저장" }));
    await waitFor(() => expect(calls[1]?.b).toEqual({ geom_options: { quality: { min_edge_ratio: 0.7 }, extract: { position_range_mm: 3 } } }));
    // 서버 422 GEOM_OPTIONS_INVALID problems → 칸 옆 + 오류 줄
    const orig = server.handle.bind(server);
    server.handle = (m, p, q, b, h) =>
      m === "PATCH" ? { status: 422, body: { detail: { code: "GEOM_OPTIONS_INVALID", message: "invalid", problems: [{ path: "interference.body_mm", message: "body_mm > 0" }] } } } : orig(m, p, q, b, h);
    fireEvent.change(within(box).getByLabelText("바디 간 mm"), { target: { value: "0.02" } });
    fireEvent.click(within(box).getByRole("button", { name: "저장" }));
    expect(await within(box).findByText("body_mm > 0")).toBeTruthy();
    expect(within(box).getByRole("alert").textContent).toBe("검사 기준 값이 허용 범위를 벗어났습니다");
  });
});

describe("3S 쉘 두께 PROP(§11.1)", () => {
  afterEach(() => vi.restoreAllMocks());

  it("스캔 전 → PROP 스캔(202 작업) → 목록: 미지원·요소별 두께 선택 불가, 공유 PART 경고 → 선택 저장(이름·min·max) → source prop 행", async () => {
    const { server } = renderApp(`${STUDY}/4`, { user: "power", geometry: "native" }, nativeCurrent);
    const calls = record(server, /\/props(\/scan)?$/);
    const card = await openManage();
    const box = await within(card).findByTestId("shell-props");
    expect(box.querySelector("summary")!.textContent).toBe("쉘 두께(PROP) — 스캔 전");
    fireEvent.click(within(box).getByRole("button", { name: "PROP 스캔" }));
    await waitFor(() => expect(calls[0]).toMatchObject({ m: "POST", p: "/param-sets/ps-n1/props/scan" }));
    expect(server.jobs.some((j) => j.job_type === "PARAM_SET_NATIVE" && j.params.mode === "props_scan")).toBe(true);
    act(() => server.finishAll());
    const t = await within(box).findByRole("table", { name: "쉘 두께 PROP" });
    expect(box.querySelector("summary")!.textContent).toBe("쉘 두께(PROP) — 선택 0 / 후보 2");
    expect((within(t).getByLabelText("PROP 201 선택") as HTMLInputElement).disabled).toBe(true);
    expect(within(t).getByLabelText("PROP 201 선택").closest("tr")!.textContent).toContain("미지원");
    expect((within(t).getByLabelText("PROP 103 선택") as HTMLInputElement).disabled).toBe(true);
    expect(within(t).getByLabelText("PROP 103 선택").closest("tr")!.textContent).toContain("요소별 두께가 PROP 두께를 덮어써");
    const shared = within(t).getByLabelText("PROP 101 선택").closest("tr")!;
    expect(within(shared).getByText("공유 PART 2개")).toBeTruthy();
    fireEvent.click(within(t).getByLabelText("PROP 101 선택"));
    fireEvent.change(within(t).getByLabelText("PROP 101 상한"), { target: { value: "1.5" } });
    fireEvent.click(within(box).getByRole("button", { name: "선택 저장" }));
    await waitFor(() => expect(calls[1]?.b).toEqual({ selected: [{ name: "BOX_SHELL_SHELL_T", min: 1.14, max: 1.5 }], include_geometry: true }));
    await waitFor(() => expect(box.querySelector("summary")!.textContent).toBe("쉘 두께(PROP) — 선택 1 / 후보 2"));
    const row = server.paramSets.find((p) => p.id === "ps-n1")!.parameters.find((p) => p.name === "BOX_SHELL_SHELL_T");
    expect(row).toMatchObject({ source: "prop", prop_id: 101, nominal: 1.2, min: 1.14, max: 1.5 });
  });

  it("범위가 공칭을 벗어나면 422 PROP_SELECTION_INVALID — 행 사유 표시, 저장 안 됨", async () => {
    const { server } = renderApp(`${STUDY}/4`, { user: "power", geometry: "native" }, (s) => {
      nativeCurrent(s);
      s.geom.get("ps-n1")!.propsScanned = true;
    });
    const card = await openManage();
    const box = await within(card).findByTestId("shell-props");
    const t = await within(box).findByRole("table", { name: "쉘 두께 PROP" });
    fireEvent.click(within(t).getByLabelText("PROP 102 선택"));
    fireEvent.change(within(t).getByLabelText("PROP 102 하한"), { target: { value: "0.9" } });
    fireEvent.click(within(box).getByRole("button", { name: "선택 저장" }));
    expect((await within(box).findByRole("alert")).textContent).toBe("쉘 두께 선택이 올바르지 않습니다");
    expect(within(t).getByLabelText("PROP 102 선택").closest("tr")!.textContent).toContain("0 < min ≤ 공칭(0.8) ≤ max");
    expect(server.paramSets.find((p) => p.id === "ps-n1")!.parameters.some((p) => p.source === "prop")).toBe(false);
  });
});

describe("4B 다중 baseline(§11.4)", () => {
  afterEach(() => vi.restoreAllMocks());

  it("기본 닫힘·단일 안내 → baseline 추가(discover 재사용) → 작업 → 매칭표 초안", async () => {
    const { server } = renderApp(`${STUDY}/4`, { user: "power", geometry: "native" }, nativeCurrent);
    const card = await openManage();
    const box = (await within(card).findByTestId("multi-baseline")).closest("details")!;
    expect(box.open).toBe(false);
    expect(within(box).getByText(/단일 baseline\(기본\)/)).toBeTruthy();
    fireEvent.change(within(box).getByLabelText("baseline id"), { target: { value: "B2" } });
    fireEvent.change(within(box).getByLabelText("baseline 폴더 경로"), { target: { value: `${ROOT}/rib5_project` } });
    fireEvent.click(within(box).getByRole("button", { name: "찾기" }));
    await within(box).findByLabelText("baseline CAD");
    fireEvent.change(within(box).getByLabelText("baseline 용도"), { target: { value: "range" } });
    const calls = record(server, /\/baselines$/);
    fireEvent.click(within(box).getByRole("button", { name: "baseline 추가" }));
    await waitFor(() => expect(server.jobs.some((j) => j.job_type === "PARAM_SET_NATIVE" && j.params.mode === "add_baseline")).toBe(true));
    expect(calls[0].b).toEqual({ id: "B2", path: `${ROOT}/rib5_project`, choice: { cad: "01_CAD/cushion_base.step", radioss_assem: "RADIOSS_ASSEM" }, usage: "range" });
    act(() => server.finishAll());
    expect(await within(box).findByRole("table", { name: "공통 변수 매칭표" })).toBeTruthy();
    expect(within(box).getByTestId("map-status").textContent).toBe("초안");
    expect(within(box).getByText(/범위 분할/).textContent).toContain("B1 12.5 · B2 15");
    expect(server.paramSets.find((p) => p.id === "ps-n1")!.param_map_status).toBe("draft");
  });

  it("baseline 2개: 삭제 대신 '단일로 되돌리기'(POST disable) → 단일 baseline", async () => {
    const { server } = renderApp(`${STUDY}/4`, { user: "power", geometry: "multi" }, nativeCurrent);
    const calls = record(server, /\/baselines/);
    const card = await openManage();
    const box = await within(card).findByTestId("multi-baseline");
    const list = await within(box).findByRole("list", { name: "baseline 목록" });
    expect(within(list).getByText("B1").closest("li")!.textContent).toContain("기준");
    expect(within(list).queryByRole("button", { name: "삭제" })).toBeNull();
    fireEvent.click(within(list).getByRole("button", { name: "단일로 되돌리기" }));
    await waitFor(() => expect(calls[0]).toMatchObject({ m: "POST", p: "/param-sets/ps-n1/baselines/disable" }));
    expect(await within(box).findByText(/단일 baseline\(기본\)/)).toBeTruthy();
    expect(server.paramSets.find((p) => p.id === "ps-n1")!.baselines).toBeNull();
  });

  it("매칭표: 등급 색·점수, 확인 필요 행 결정 전 [확정] 불가 → 수락 → 확정(사용자·시각)", async () => {
    const { server } = renderApp(`${STUDY}/4`, { user: "power", geometry: "multi" }, nativeCurrent);
    const calls = record(server, /\/param-map/);
    const card = await openManage();
    const box = await within(card).findByTestId("multi-baseline");
    const t = await within(box).findByRole("table", { name: "공통 변수 매칭표" });
    const grade = (id: string) => within(t).getByTestId(`map-row-${id}`).querySelector("[data-grade]")!;
    expect(grade("r1").className).toBe("pill ok");
    expect(grade("r1").textContent).toBe("추천 0.93");
    expect(grade("r2").className).toBe("pill warn");
    expect(grade("r3").className).toBe("pill ");
    expect(grade("r3").textContent).toBe("미매칭 제안 0.41");
    expect(within(t).getByTestId("map-row-r3").textContent).toContain("N/A");
    const confirm = within(box).getByRole("button", { name: "확정" }) as HTMLButtonElement;
    expect(confirm.disabled).toBe(true);
    expect(within(box).getByText(/결정하지 않은 행 1개/)).toBeTruthy();
    fireEvent.click(within(within(t).getByTestId("map-row-r2")).getByRole("button", { name: "수락" }));
    await waitFor(() => expect(calls[0]?.b).toEqual({ decisions: [{ row_id: "r2", decision: { action: "accept" } }] }));
    await waitFor(() => expect(confirm.disabled).toBe(false));
    fireEvent.click(confirm);
    await waitFor(() => expect(within(box).getByTestId("map-status").textContent).toMatch(/^확정\(김연구 · /));
    expect(calls[1]).toMatchObject({ m: "POST", p: "/param-sets/ps-n1/param-map/confirm" });
    await waitFor(() => expect(server.paramSets.find((p) => p.id === "ps-n1")!.param_map_status).toBe("confirmed"));
  });

  it("분리 = baseline별 행, 변경(이름·N/A) 충돌은 PARAM_NAME_CONFLICT 문구, 재확인 배지", async () => {
    const { server } = renderApp(`${STUDY}/4`, { user: "power", geometry: "multi" }, (s) => {
      nativeCurrent(s);
      s.geom.get("ps-n1")!.map!.common[3].needs_review = true;
    });
    const card = await openManage();
    const box = await within(card).findByTestId("multi-baseline");
    const t = await within(box).findByRole("table", { name: "공통 변수 매칭표" });
    expect(within(within(t).getByTestId("map-row-r4")).getByText("재확인")).toBeTruthy();
    const calls = record(server, /\/param-map$/);
    fireEvent.click(within(within(t).getByTestId("map-row-r1")).getByRole("button", { name: "분리" }));
    await waitFor(() => expect(within(t).getByTestId("map-row-r1").textContent).toContain("CUSH_THK_B1 / CUSH_THK_B2"));
    expect(calls[0].b).toEqual({ decisions: [{ row_id: "r1", decision: { action: "split", parts: [{ name: "CUSH_THK_B1", map: { B1: "CUSH_L_THK_1", B2: null } }, { name: "CUSH_THK_B2", map: { B1: null, B2: "CUSH_L_THK_1" } }] } }] });
    const r2 = within(t).getByTestId("map-row-r2");
    fireEvent.click(within(r2).getByRole("button", { name: "변경" }));
    fireEvent.change(within(t).getByLabelText("r2 공통 이름"), { target: { value: "baseline" } });
    fireEvent.change(within(t).getByLabelText("r2 B2 대응"), { target: { value: "__na__" } });
    fireEvent.click(within(t).getByRole("button", { name: "적용" }));
    expect((await within(box).findByRole("alert")).textContent).toContain("공통 이름 'baseline'은 규칙에 맞지 않거나 예약어입니다");
    expect(within(t).getByTestId("map-row-r2").textContent).toContain("예약어");
    expect(server.geom.get("ps-n1")!.map!.common.find((r) => r.row_id === "r2")!.decision).toBeNull();
    fireEvent.change(within(t).getByLabelText("r2 공통 이름"), { target: { value: "POCKET_D" } });
    fireEvent.click(within(t).getByRole("button", { name: "적용" }));
    await waitFor(() => expect(within(t).getByTestId("map-row-r2").textContent).toContain("POCKET_D"));
    expect(server.geom.get("ps-n1")!.map!.common.find((r) => r.row_id === "r2")!.decision).toEqual({ action: "change", name: "POCKET_D", map: { B1: "CUSH_L_POCKET_D_1", B2: null } });
  });
});

describe("① native 파라미터 표·엔진 혼용(§8·§7.7)", () => {
  afterEach(() => vi.restoreAllMocks());

  it("① native: 종류 열(위치형 mm 범위), tpl 생성 대신 표 저장", async () => {
    const { server } = renderApp(`${STUDY}/1`, { user: "power" }, (s) => {
      Object.assign(s.p2.setups["s-cushion"], { engine: "native", parameters: nativeTrainParams(), tpl: null });
    });
    const calls = record(server, /\/train\//);
    const table = await screen.findByRole("table", { name: "파라미터 표" });
    // 종류·PNG는 GET /studies/{id}/train/features(이름 약어 추정 없음)
    await waitFor(() => expect(within(table).getByText("CUSH_L_HOLE_U_1").closest("tr")!.textContent).toContain("구멍 위치 U · mm 범위"));
    expect(within(table).getByText("CUSH_L_THK_1").closest("tr")!.textContent).toContain("두께");
    expect(within(table).getByText("BOX_SHELL_T").closest("tr")!.textContent).not.toContain("쉘 두께");
    expect(within(table).queryByLabelText("CUSH_L_FILLET_R_1 하이라이트")).toBeNull();
    fireEvent.click(within(table).getByText("CUSH_L_THK_1")); // 행 클릭 = 선택 → 그림 탭이 없으면 3D(폴백이면 PNG)
    expect((await screen.findByTestId("feature-png")).textContent).toContain("CUSH_L_THK_1");
    expect(screen.queryByRole("button", { name: "tpl 생성" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "표 저장" }));
    await waitFor(() => expect(calls.length).toBe(1));
    expect(calls[0].p).toBe("/studies/s-cushion/train/params");
  });

  it("④ 모델 엔진 ≠ 템플릿 엔진이면 안내, 데이터셋·모델 엔진 배지", async () => {
    renderApp(`${STUDY}/4`, { user: "power" }, (s) => s.models.forEach((m) => (m.engine = "native")));
    expect((await screen.findByTestId("engine-mismatch")).textContent).toBe("모델(Native)과 템플릿(Altair)의 형상 엔진이 다릅니다 — 같은 엔진의 모델·템플릿을 고르세요.");
  });
});
