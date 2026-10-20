// V-EQ-11(equiv-check.md §7, 화면): ⑤ "등가성 판정" 탭 — 탭 표시·레시피 드롭다운 3그룹·편집 접힘, 시스템 기본은 그대로 실행 불가(복제·확인한
// 사용자 레시피만), 응답 미연결 지표(필수·참고 모두)면 실행 비활성, 실행 → 결과 배지·지표 표·곡선 겹쳐 그림, 이력 → 레시피 불러오기(스냅숏 적재)·메모.
// 순수 함수(recipeState) 골든 포함. 목 서버(mock/equivCheck.ts) 기준.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { renderApp, STUDY } from "../test/render";
import type { MockServer } from "../mock/server";
import { SYS_KEY } from "../mock/equivCheck";
import { SYSTEM_RUN_TEXT, UNBOUND_TEXT } from "../analysis/equiv/EquivTab";
import { isSystemRef, recipeBody, RECIPE_KEY, toRows, unboundMetrics, versionNote } from "../analysis/equiv/recipeState";
import type { EqDefinition } from "../api/equivCheck";

const EQ = `${STUDY}/analysis?tab=equiv`;
const O = { user: "power" as const, equiv: "demo" as const };

/** 비GET 요청 본문 기록 */
function record(server: MockServer, re: RegExp, method = "POST") {
  const bodies: Record<string, unknown>[] = [];
  const orig = server.handle.bind(server);
  server.handle = (m, p, q, b, h) => {
    if (m === method && re.test(p)) bodies.push(b as Record<string, unknown>);
    return orig(m, p, q, b, h);
  };
  return bodies;
}

const addGlobal = (s: MockServer) => {
  const r = s.eqRecipes.find((x) => x.key === "rcp-1" && x.version === 2)!;
  s.eqRecipes.push({ ...r, key: "rcp-g", version: 1, scope: "global", study_id: null, name: "전역 낙하 레시피" });
};

async function pickSides() {
  const a = await screen.findByRole("group", { name: "A(기준) 대상" });
  const b = screen.getByRole("group", { name: "B(비교) 대상" });
  fireEvent.change(within(a).getByLabelText("A(기준) 종류"), { target: { value: "train_doe" } });
  fireEvent.change(within(b).getByLabelText("B(비교) 종류"), { target: { value: "train_doe" } });
  await waitFor(() => expect(within(a).getAllByRole("option").length).toBeGreaterThan(1));
  fireEvent.change(within(a).getByLabelText("A(기준) 대상 선택"), { target: { value: "doe-1" } });
  fireEvent.change(within(b).getByLabelText("B(비교) 대상 선택"), { target: { value: "doe-1" } });
}

const recipeSelect = () => screen.findByRole("combobox", { name: "레시피 선택" }) as Promise<HTMLSelectElement>;
const runBtn = () => screen.getByRole("button", { name: "판정 실행" }) as HTMLButtonElement;

describe("⑤ 등가성 판정 탭 (V-EQ-11)", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it("탭 표시·레시피 드롭다운 3그룹(시스템 기본·이 Study·전역)·편집 접힘, 시스템 기본은 실행 불가 안내", async () => {
    renderApp(EQ, O, addGlobal);
    expect(await screen.findByTestId("equiv-tab")).toBeTruthy();
    expect(screen.getByRole("tab", { name: "등가성 판정" }).getAttribute("aria-selected")).toBe("true");
    const sel = await recipeSelect();
    await waitFor(() => expect(sel.querySelectorAll("optgroup")).toHaveLength(3));
    expect(Array.from(sel.querySelectorAll("optgroup")).map((g) => g.getAttribute("label"))).toEqual(["시스템 기본", "이 Study", "전역"]);
    await waitFor(() => expect(sel.value).toBe(SYS_KEY)); // 저장값 없으면 시스템 기본(제안값)
    expect(screen.queryByTestId("eq-editor-open")).toBeNull(); // 편집은 접힘
    expect(screen.getByTestId("eq-system-block").textContent).toBe(SYSTEM_RUN_TEXT);
    await pickSides();
    await waitFor(() => expect(screen.getByTestId("eq-problems").textContent).toContain("시스템 기본 레시피는 제안값입니다"));
    expect(runBtn().disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "편집" }));
    expect(await screen.findByTestId("eq-editor-open")).toBeTruthy();
    expect((screen.getByRole("button", { name: "이번만 사용" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("시스템 기본 → 다른 이름으로 저장(Study) → 사용자 레시피 선택·저장값 기억", async () => {
    const { server } = renderApp(EQ, O);
    const posts = record(server, /\/equiv\/recipes$/);
    const sel = await recipeSelect();
    await waitFor(() => expect(sel.value).toBe(SYS_KEY));
    fireEvent.click(screen.getByRole("button", { name: "편집" }));
    fireEvent.click(await screen.findByRole("button", { name: "다른 이름으로 저장" }));
    const box = await screen.findByTestId("eq-saveas");
    fireEvent.change(within(box).getByLabelText("레시피 이름"), { target: { value: "현장 레시피" } });
    fireEvent.click(within(box).getByRole("button", { name: "저장" }));
    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0]).toMatchObject({ name: "현장 레시피", scope: "study", study_id: "s-cushion" });
    const created = server.eqRecipes.find((r) => r.name === "현장 레시피")!;
    await waitFor(() => expect(sel.value).toBe(created.key));
    expect(localStorage.getItem(RECIPE_KEY)).toBe(created.key);
    expect(screen.queryByTestId("eq-system-block")).toBeNull();
    // 복제본은 시스템 기본처럼 응답이 비어 있음 → 연결 전 실행 불가
    expect(screen.getByTestId("eq-unbound").textContent).toContain(UNBOUND_TEXT);
  });

  it("사용자 레시피: 참고 지표도 응답 미연결이면 실행 비활성, 연결하면 bindings로 실행 → 결과 배지·지표 표·곡선 겹쳐 그림", async () => {
    const { server } = renderApp(EQ, O, (s) => {
      for (const r of s.eqRecipes) r.definition = { ...r.definition, metrics: r.definition.metrics.map((m) => (m.id === "contact_peak" ? { ...m, source: null, required: false } : m)) };
    });
    const creates = record(server, /\/equiv-checks$/);
    const sel = await recipeSelect();
    await waitFor(() => expect(sel.querySelectorAll("option").length).toBeGreaterThan(1));
    fireEvent.change(sel, { target: { value: "rcp-1" } });
    await waitFor(() => expect(sel.value).toBe("rcp-1"));
    await pickSides();
    await waitFor(() => expect(screen.getByTestId("eq-unbound").textContent).toContain("접촉력 피크"));
    expect(runBtn().disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "편집" }));
    const row = await screen.findByTestId("eq-row-contact_peak");
    expect(row.className).toContain("eq-row-unbound");
    await waitFor(() => expect(screen.getByTestId("eq-pair-preview")).toBeTruthy());
    fireEvent.change(within(row).getByLabelText("접촉력 피크 원천 종류"), { target: { value: "perf" } });
    await waitFor(() => expect(screen.queryByTestId("eq-unbound")).toBeNull());
    await waitFor(() => expect(runBtn().disabled).toBe(false));
    fireEvent.click(runBtn());
    await waitFor(() => expect(creates).toHaveLength(1));
    expect(creates[0].recipe).toEqual({ key: "rcp-1", version: 2 });
    expect(creates[0].recipe_inline ?? null).toBeNull();
    expect(creates[0].bindings).toEqual({ contact_peak: { type: "perf", perf: "MaxStress" } });
    act(() => server.finishAll());
    const result = await screen.findByTestId("eq-result", {}, { timeout: 3000 });
    expect(within(result).getByTestId("eq-verdict").textContent).toMatch(/통과|미달|판정 불가/);
    expect(within(result).getByTestId("eq-summary-line").textContent).toContain("쿠션 기본 레시피 v2");
    expect(within(result).getByRole("table", { name: "지표 판정" })).toBeTruthy();
    expect(await within(result).findByTestId("eq-curve")).toBeTruthy();
    expect(within(result).getByTestId("eq-curve-stats").textContent).toMatch(/^r = /);
    expect(server.eqChecks.find((c) => c.eq_no === 3)?.status).toBe("DONE");
  });

  it("이력: 목록 → 열기, 이 레시피 불러오기(스냅숏 적재, '현재 v2 · 이력 v1'), 메모 저장(PATCH note)", async () => {
    const { server } = renderApp(EQ, O);
    const patches = record(server, /\/equiv-checks\/[^/]+$/, "PATCH");
    const hist = await screen.findByTestId("eq-history");
    const row = within(hist).getByTestId("eq-hist-EQ-001");
    expect(row.textContent).toContain("쿠션 기본 레시피 v1");
    fireEvent.click(within(row).getByRole("button", { name: "이 레시피 불러오기" }));
    expect((await screen.findByTestId("eq-recipe-note")).textContent).toBe("현재 v2 · 이력 v1");
    expect(await screen.findByTestId("eq-editor-open")).toBeTruthy();
    expect((within(screen.getByTestId("eq-row-stress_peak")).getByLabelText("응력 피크 구분") as HTMLSelectElement).value).toBe("reference"); // v1 스냅숏(v2는 필수)
    fireEvent.click(within(row).getByRole("button", { name: "열기" }));
    const result = await screen.findByTestId("eq-result");
    const note = within(result).getByLabelText("판정 메모") as HTMLInputElement;
    expect(note.value).toBe("같은 해석을 A·B에 — 기준 확인");
    fireEvent.change(note, { target: { value: "현장 회신 완료" } });
    fireEvent.click(within(result).getByRole("button", { name: "메모 저장" }));
    await waitFor(() => expect(patches).toEqual([{ note: "현장 회신 완료" }]));
    await waitFor(() => expect(within(screen.getByTestId("eq-history")).getByTestId("eq-hist-EQ-001").textContent).toContain("현장 회신 완료"));
  });

  it("결과분석 탭 전환: 등가성 판정 → 결과 표·그래프(?tab 제거)", async () => {
    renderApp(EQ, O);
    await screen.findByTestId("equiv-tab");
    fireEvent.click(screen.getByRole("tab", { name: "결과 표·그래프" }));
    await waitFor(() => expect(screen.queryByTestId("equiv-tab")).toBeNull());
  });
});

describe("레시피 상태 순수 함수", () => {
  const def: EqDefinition = {
    schema_version: 1,
    pair_rule: { mode: "all" },
    verdict_rule: "required_all",
    metrics: [
      { id: "accel_peak", label: "가속도 피크", kind: "scalar", source: null, tol: { rel_pct: 5, abs: null }, required: true },
      { id: "stress_peak", label: "응력 피크", kind: "scalar", source: null, tol: { rel_pct: 10, abs: null }, required: false },
      { id: "volume_diff", label: "쿠션 부피 차", kind: "mesh_volume", source: null, tol: { rel_pct: 0.1, abs: null }, required: true },
    ],
  };
  const ref = { key: "rcp-1", version: 3 };

  it("미연결 = 사용 중인 지표(필수·참고 모두, mesh_volume 제외)", () => {
    const rows = toRows(def);
    expect(unboundMetrics(rows).map((r) => r.id)).toEqual(["accel_peak", "stress_peak"]);
    rows[1].use = false;
    expect(unboundMetrics(rows).map((r) => r.id)).toEqual(["accel_peak"]);
  });

  it("빈 원천만 채우면 recipe + bindings, 그 밖 변경은 recipe_inline(base), ref 없음(1회용 스냅숏)은 항상 inline", () => {
    const rows = toRows(def);
    rows[0].source = { type: "perf", perf: "AccPeak" };
    expect(recipeBody(def, rows, ref)).toEqual({ recipe: ref, bindings: { accel_peak: { type: "perf", perf: "AccPeak" } } });
    rows[1].tol = { rel_pct: 15, abs: null };
    const b = recipeBody(def, rows, ref);
    expect(b.recipe).toBeUndefined();
    expect(b.recipe_inline?.base).toEqual(ref);
    expect(b.recipe_inline?.definition.metrics[1].tol.rel_pct).toBe(15);
    const c = recipeBody(def, toRows(def), null);
    expect(c.recipe_inline?.base).toBeNull();
    expect(c.recipe_inline?.definition.metrics).toHaveLength(3);
  });

  it("시스템 기본 판별·이력 버전 안내", () => {
    expect(isSystemRef({ key: SYS_KEY }, SYS_KEY)).toBe(true);
    expect(isSystemRef({ key: "rcp-1" }, SYS_KEY)).toBe(false);
    expect(isSystemRef(null, SYS_KEY)).toBe(false);
    expect(versionNote({ version: 3, current_version: 5, deleted: false, source: "user" })).toBe("현재 v5 · 이력 v3");
    expect(versionNote({ version: 1, current_version: 1, deleted: true, source: "user" })).toBe("삭제된 레시피(스냅숏으로 불러옵니다)");
    expect(versionNote({ version: null, current_version: null, deleted: false, source: "adhoc" })).toBe("1회용(저장되지 않은) 레시피 스냅숏");
  });
});
