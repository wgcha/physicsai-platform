// v0.2.4 native-vars.md V-NV-9: Native 변수 선택·범위 화면 — 순수 규칙(경고 허용오차·스냅숏 요약), ④ 세트 상세 변수 표(편집·다중 선택 일괄·저장·409·이력·읽기 전용),
// ⑥ 변수 범위(추가·제외·고정 구분·경고 표시·Altair 무변경), ④ 일괄 예측(그 자리 편집·경고·① DOE 재사용), 결과·배치 상세 스냅숏 한 줄.
import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { renderApp, STUDY } from "../test/render";
import type { MockServer } from "../mock/server";
import { err } from "../mock/route";
import { seedParamSet } from "../mock/seed";
import type { NativeVars } from "../api";
import { NO_EDIT, deltaText, detailRows, editOf, effectiveParamSet, putBody, rowError, rowWarnings, runRows, signature, snapshotText } from "../lib/nativeVars";
import { buildBody, type SoForm } from "../stages/stage5/surrogate/soRules";

type Call = { m: string; p: string; b: Record<string, unknown> | null };
function record(server: MockServer, re: RegExp, methods = ["POST", "PUT"]): Call[] {
  const calls: Call[] = [];
  const orig = server.handle.bind(server);
  server.handle = (m, p, q, b, h) => {
    if (methods.includes(m) && re.test(p)) calls.push({ m, p, b });
    return orig(m, p, q, b, h);
  };
  return calls;
}
/** 다음 PUT 변수 정의 요청을 409 충돌로 바꾼다 */
function conflictOnce(server: MockServer) {
  const orig = server.handle.bind(server);
  let done = false;
  server.handle = (m, p, q, b, h) => {
    if (!done && m === "PUT" && /\/variables$/.test(p)) {
      done = true;
      return err(409, "NATIVE_VARS_CONFLICT", "다른 사용자가 먼저 저장했습니다 — 새로 불러온 뒤 다시 저장하세요");
    }
    return orig(m, p, q, b, h);
  };
}
const nativeCurrent = (s: MockServer) => {
  s.paramSets.forEach((p) => (p.is_current = p.id === "ps-n1"));
  s.paramSets.find((p) => p.id === "ps-n1")!.responses = seedParamSet().responses; // ⑥ 성능 표용
};
const input = (root: HTMLElement, label: string) => within(root).getByLabelText(label) as HTMLInputElement;
const check = (root: HTMLElement, name: string) => input(root, `${name} 사용`);

async function openDetail() {
  fireEvent.click(await screen.findByRole("button", { name: "템플릿 관리" }));
  const card = await screen.findByRole("region", { name: "템플릿 관리" });
  const table = await within(card).findByRole("table", { name: "형상 피처 표" });
  return { card, table };
}
/** 변수 정의 머리줄의 저장·되돌리기·새로 불러오기(다른 '저장' 버튼과 구분) */
const head = (card: HTMLElement) => within(within(card).getByTestId("vars-head"));
const clickRow = (table: HTMLElement, name: string, mods: { ctrlKey?: boolean; shiftKey?: boolean } = {}) =>
  fireEvent.click(within(table).getByText(name).closest("tr")!, mods);

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

// ------------------------------------------------------------------ 순수 규칙

const POOL = (extra: Partial<NativeVars["pool"][number]> = {}) =>
  ({ name: "A", type: "THICKNESS", body: "B", nominal: 10, unit: "mm", position: false, default_range: { min: 9, max: 11 }, feasible: { min: 5, max: 15, source: "envelope" }, ref_locked: false, group: null, train: { min: 9, max: 11 }, ...extra }) as NativeVars["pool"][number];
const VARS = (): NativeVars => ({ revision: 2, editable: true, engine: "native", variables: [{ name: "A", min: 9.5, max: 10.5 }], pool: [POOL(), POOL({ name: "C", nominal: 3, default_range: { min: 2.8, max: 3.2 }, train: null })], notes: [], warnings: [], history: [] }) as NativeVars;

describe("lib/nativeVars — 경고(막지 않음)·행·본문", () => {
  it("경고: 학습 범위 밖·모핑 가능 범위 밖·양면 접촉·공칭 밖, 허용오차 안은 경고 없음, 사용 해제 행은 경고 없음", () => {
    const [a] = detailRows(VARS());
    const w = (p: Partial<typeof a>) => rowWarnings({ ...a, ...p }).map((x) => x.code);
    expect(w({})).toEqual([]);
    expect(w({ hi: "11.0000000001" })).toEqual([]); // 학습 허용오차 1e-9·max(1,|x|)
    expect(w({ hi: "11.5" })).toEqual(["VAR_OUT_OF_TRAIN"]);
    expect(w({ lo: "4", hi: "16" })).toEqual(["VAR_OUT_OF_TRAIN", "VAR_OUT_OF_FEASIBLE"]);
    expect(w({ lo: "11", hi: "11.2" })).toEqual(["VAR_OUT_OF_TRAIN", "VAR_NOMINAL_OUTSIDE"]);
    expect(w({ refLocked: true })).toEqual(["VAR_REF_LOCKED"]);
    expect(w({ train: null, lo: "0", hi: "1" })).toEqual(["VAR_OUT_OF_FEASIBLE", "VAR_NOMINAL_OUTSIDE"]); // 학습 범위 모름 = 외삽 경고 없음
    expect(w({ use: false, lo: "0", hi: "99" })).toEqual([]);
    expect(rowWarnings({ ...a, hi: "11.5" })[0].message).toBe("학습 형상 분포 밖 — 외삽 주의(학습 9~11)");
  });

  it("검사(차단)는 숫자·하한 ≤ 상한뿐, 범위 밖은 막지 않는다 · 위치형 Δ", () => {
    const [a] = detailRows(VARS());
    expect(rowError({ ...a, lo: "", hi: "1" })).toBe("숫자를 입력하세요");
    expect(rowError({ ...a, lo: "5", hi: "4" })).toBe("하한 ≤ 상한");
    expect(rowError({ ...a, lo: "-100", hi: "100" })).toBeNull();
    expect(rowError({ ...a, lo: "5", hi: "4", use: false })).toBeNull();
    expect(deltaText({ ...a, position: true, lo: "5", hi: "13" })).toBe("−5 / +3");
    expect(deltaText({ ...a, position: false })).toBeNull();
  });

  it("④ 상세 행: 풀 전체, 사용 = 세트 정의에 있는 행(없는 행은 피처 기본 범위), 저장 본문 = 사용 행 + base_revision", () => {
    const rows = detailRows(VARS());
    expect(rows.map((r) => [r.name, r.use, r.lo, r.hi])).toEqual([["A", true, "9.5", "10.5"], ["C", false, "2.8", "3.2"]]);
    const next = rows.map((r) => ({ ...r, use: true, hi: r.name === "C" ? "3.5" : r.hi }));
    expect(putBody(next, 2)).toEqual({ base_revision: 2, variables: [{ name: "A", min: 9.5, max: 10.5 }, { name: "C", min: 2.8, max: 3.5 }] });
    expect(signature(next)).not.toBe(signature(rows));
    expect(signature(rows.map((r) => (r.name === "C" ? { ...r, hi: "9" } : r)))).toBe(signature(rows)); // 사용 해제 행의 값은 변경으로 보지 않는다
  });

  it("⑥·일괄 행: (세트 − 제외) + 추가, 요청 vars는 비면 null · 제외 ≠ 고정", () => {
    const d = VARS();
    expect(editOf(runRows(d, NO_EDIT))).toBeNull();
    const rows = runRows(d, { add: ["C"], exclude: ["A"] });
    expect(rows.map((r) => [r.name, r.origin, r.use])).toEqual([["A", "set", false], ["C", "added", true]]);
    expect(editOf(rows)).toEqual({ add: ["C"], exclude: ["A"] });
    const fixed = runRows({ ...d, variables: [{ name: "A", min: 10, max: 10 }] }, NO_EDIT);
    expect(fixed[0]).toMatchObject({ use: true, fixed: true }); // 고정 = 하한 = 상한(목록에 남음)
    expect(editOf(fixed)).toBeNull();
  });

  it("⑥ buildBody(Native): 기준 범위와 다른 사용 행·고정만 bounds, 제외·추가는 vars, Altair 본문은 그대로", () => {
    const rows = runRows(VARS(), { add: ["C"], exclude: [] }).map((r) => (r.name === "A" ? { ...r, lo: "9.8", fixed: true } : r));
    const f = { paramSetId: "p", modelId: "m", explore: "new", count: "", exploreSeed: "1", batchId: "", sels: {}, weights: {}, rows: [], surrogate: "gp", iterations: "3", candidates: "4", tolPct: "1", seed: "1", multi: "1", capture: false } as SoForm;
    const b = buildBody({ ...f, nrows: rows }, []);
    expect(b.bounds).toEqual({ A: [9.8, 9.8] });
    expect((b as { vars?: unknown }).vars).toEqual({ add: ["C"], exclude: [] });
    const off = buildBody({ ...f, nrows: rows.map((r) => (r.name === "A" ? { ...r, use: false } : r)) }, []);
    expect(off.bounds).toBeNull();
    expect((off as { vars?: unknown }).vars).toEqual({ add: ["C"], exclude: ["A"] });
    expect("vars" in buildBody({ ...f, rows: [] }, [])).toBe(false);
  });

  it("스냅숏 요약 한 줄 · 없으면 null · ④ 일괄용 유효 템플릿(PROP 보존)", () => {
    expect(snapshotText(null)).toBeNull();
    expect(snapshotText({ set_revision: 3, edited: true, variables: [{ name: "A", origin: "set" }, { name: "C", origin: "added" }], excluded: ["X", "Y"] })).toBe("변수 2개 · 세트 정의 rev 3 · 추가 1 · 제외 2 · 이 실행에서 편집");
    expect(snapshotText({ set_revision: 0, edited: false, variables: [{ name: "A", origin: "set" }], excluded: [] })).toBe("변수 1개 · 세트 정의 rev 0");
    const ps = { ...seedParamSet(), parameters: [{ name: "A", nominal: 10, min: 9, max: 11, unit: "mm" }, { name: "T_PROP", nominal: 1, min: 0.9, max: 1.1, unit: "mm", source: "prop" }] } as never;
    const rows = runRows(VARS(), { add: ["C"], exclude: [] }).filter((r) => r.name !== "A");
    expect(effectiveParamSet(ps, rows).parameters.map((p) => p.name)).toEqual(["C"]);
  });
});

// ------------------------------------------------------------------ ④ 세트 상세

describe("④ 세트 상세 변수 표(V-NV-9)", () => {
  it("풀 전체 표: 사용·하한·상한·모핑 가능 범위·경고 아이콘, 위치형 절대 mm + Δ, 학습 범위 열 없음", async () => {
    renderApp(`${STUDY}/4`, { user: "power", geometry: "native" }, nativeCurrent);
    const { card, table } = await openDetail();
    expect(within(card).getByTestId("vars-head").textContent).toMatch(/변수 정의 rev 0 · 사용 6\/6/);
    expect(within(table).getAllByRole("columnheader").map((h) => h.textContent)).toEqual(["사용", "이름", "종류", "바디", "공칭", "모핑 가능 범위", "하한", "상한", "대칭 그룹", "기준면", "경고"]);
    const hole = within(table).getByText("CUSH_L_HOLE_U_1").closest("tr")!;
    expect(input(hole, "CUSH_L_HOLE_U_1 하한").value).toBe("25");
    expect(hole.textContent).toContain("Δ −5 / +5");
    expect(hole.textContent).toContain("27 ~ 40");
    const warn = within(hole).getByRole("img", { name: /모핑 실패 가능/ });
    expect(warn.getAttribute("title")).toMatch(/모핑 가능 27~40/); // 툴팁
    expect(within(table).getByText("CUSH_L_THK_1").closest("tr")!.querySelectorAll(".nv-warn").length).toBe(0);
    expect(within(card).getByText(/목록에 없는 변수는 추출 조건을 바꿔 새 템플릿으로 등록하세요/)).toBeTruthy();
    expect((head(card).getByRole("button", { name: "저장" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("다중 선택(클릭·Ctrl) 후 사용 해제 → 선택 밖은 그대로 → 사용 체크 · 선택한 행의 체크박스 = 선택 전체 토글", async () => {
    renderApp(`${STUDY}/4`, { user: "power", geometry: "native" }, nativeCurrent);
    const { card, table } = await openDetail();
    expect(screen.queryByTestId("bulk-use-bar")).toBeNull();
    clickRow(table, "CUSH_L_THK_1");
    clickRow(table, "CUSH_L_POCKET_D_1", { ctrlKey: true });
    clickRow(table, "CUSH_L_HOLE_U_1", { ctrlKey: true });
    const bar = screen.getByTestId("bulk-use-bar");
    expect(bar.textContent).toContain("3개 선택");
    fireEvent.click(within(bar).getByRole("button", { name: "사용 해제" }));
    expect(["CUSH_L_THK_1", "CUSH_L_POCKET_D_1", "CUSH_L_HOLE_U_1"].map((n) => check(table, n).checked)).toEqual([false, false, false]);
    expect(check(table, "CUSH_L_RIB_U_1").checked).toBe(true);
    expect(within(table).getByText("CUSH_L_THK_1").closest("tr")!.className).toContain("unused");
    expect(input(table, "CUSH_L_THK_1 하한").disabled).toBe(true); // 해제 행은 입력 비활성(값은 유지)
    expect(within(card).getByTestId("vars-head").textContent).toMatch(/사용 3\/6/);
    fireEvent.click(check(table, "CUSH_L_THK_1")); // 선택된 행의 체크박스 → 선택 3행 모두 토글
    expect(["CUSH_L_THK_1", "CUSH_L_POCKET_D_1", "CUSH_L_HOLE_U_1"].map((n) => check(table, n).checked)).toEqual([true, true, true]);
    fireEvent.click(within(bar).getByRole("button", { name: "선택 해제" }));
    expect(screen.queryByTestId("bulk-use-bar")).toBeNull();
    expect(screen.queryAllByRole("button", { name: "선택 해제" }).length).toBe(0);
  });

  it("편집 → 저장(PUT base_revision·사용 행) → rev 1·변경 이력·읽기 전용 리비전 보기, 되돌리기", async () => {
    const { server } = renderApp(`${STUDY}/4`, { user: "power", geometry: "native" }, nativeCurrent);
    const puts = record(server, /\/param-sets\/ps-n1\/variables$/, ["PUT"]);
    const { card, table } = await openDetail();
    fireEvent.click(check(table, "CUSH_L_RIB_T_2"));
    fireEvent.click(check(table, "CUSH_L_FILLET_R_1"));
    fireEvent.change(input(table, "CUSH_L_THK_1 상한"), { target: { value: "14" } });
    const save = head(card).getByRole("button", { name: "저장" }) as HTMLButtonElement;
    expect(save.disabled).toBe(false);
    fireEvent.click(head(card).getByRole("button", { name: "되돌리기" }));
    expect(check(table, "CUSH_L_RIB_T_2").checked).toBe(true);
    expect(input(table, "CUSH_L_THK_1 상한").value).toBe("13.125");
    expect(save.disabled).toBe(true);
    fireEvent.click(check(table, "CUSH_L_RIB_T_2"));
    fireEvent.click(check(table, "CUSH_L_FILLET_R_1"));
    fireEvent.change(input(table, "CUSH_L_THK_1 상한"), { target: { value: "14" } });
    fireEvent.click(save);
    await waitFor(() => expect(puts.length).toBe(1));
    expect(puts[0].b).toEqual({
      base_revision: 0,
      variables: [{ name: "CUSH_L_THK_1", min: 11.875, max: 14 }, { name: "CUSH_L_POCKET_D_1", min: 7.6, max: 8.4 }, { name: "CUSH_L_HOLE_U_1", min: 25, max: 35 }, { name: "CUSH_L_RIB_U_1", min: 46.5, max: 56.5 }],
    });
    await waitFor(() => expect(within(card).getByTestId("vars-head").textContent).toMatch(/rev 1 · 사용 4\/6/));
    expect((head(card).getByRole("button", { name: "저장" }) as HTMLButtonElement).disabled).toBe(true);
    const hist = within(card).getByTestId("vars-history");
    expect(hist.textContent).toContain("rev 1");
    expect(hist.textContent).toContain("rev 0");
    fireEvent.click(within(hist).getAllByRole("button", { name: "보기" })[1]); // rev 0(등록 정의)
    const view = await within(hist).findByTestId("vars-rev-view");
    expect(within(view).getByText("CUSH_L_FILLET_R_1")).toBeTruthy();
    expect(within(view).queryAllByRole("textbox").length).toBe(0); // 읽기 전용
    expect(check(table, "CUSH_L_FILLET_R_1").checked).toBe(false); // 편집 표는 현재 리비전 그대로
  });

  it("저장 409 → 충돌 문구 + [새로 불러오기](편집 폐기·다시 읽기), 422 problems는 줄마다 표시", async () => {
    const { server } = renderApp(`${STUDY}/4`, { user: "power", geometry: "native" }, nativeCurrent);
    conflictOnce(server);
    const { card, table } = await openDetail();
    fireEvent.click(check(table, "CUSH_L_FILLET_R_1"));
    fireEvent.click(head(card).getByRole("button", { name: "저장" }));
    expect((await within(card).findAllByRole("alert"))[0].textContent).toBe("다른 사용자가 먼저 저장했습니다 — 새로 불러온 뒤 다시 저장하세요");
    fireEvent.click(head(card).getByRole("button", { name: "새로 불러오기" }));
    await waitFor(() => expect(check(table, "CUSH_L_FILLET_R_1").checked).toBe(true));
    expect(head(card).queryByRole("button", { name: "새로 불러오기" })).toBeNull();
    // 변수 0개 → VARS_EMPTY(서버 문구 줄)
    fireEvent.click(check(table, "CUSH_L_THK_1"));
    clickRow(table, "CUSH_L_THK_1");
    clickRow(table, "CUSH_L_FILLET_R_1", { shiftKey: true });
    fireEvent.click(within(screen.getByTestId("bulk-use-bar")).getByRole("button", { name: "사용 해제" }));
    fireEvent.click(head(card).getByRole("button", { name: "저장" }));
    expect((await within(card).findByLabelText("변수 정의 오류")).textContent).toContain("변수를 하나 이상 고르세요");
  });

  it("하한 > 상한이면 저장 불가(행 문구), 범위 밖 값은 저장 허용(경고만)", async () => {
    renderApp(`${STUDY}/4`, { user: "power", geometry: "native" }, nativeCurrent);
    const { card, table } = await openDetail();
    const thk = within(table).getByText("CUSH_L_THK_1").closest("tr")!;
    fireEvent.change(input(thk, "CUSH_L_THK_1 하한"), { target: { value: "20" } });
    expect(thk.textContent).toContain("하한 ≤ 상한");
    expect((head(card).getByRole("button", { name: "저장" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(input(thk, "CUSH_L_THK_1 하한"), { target: { value: "1" } });
    fireEvent.change(input(thk, "CUSH_L_THK_1 상한"), { target: { value: "30" } });
    expect(within(thk).getByRole("img", { name: /모핑 실패 가능/ })).toBeTruthy();
    expect((head(card).getByRole("button", { name: "저장" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("editable=false(다중 baseline): 사유 표시 · 입력·체크 비활성 · 저장 없음", async () => {
    renderApp(`${STUDY}/4`, { user: "power", geometry: "multi" }, nativeCurrent);
    const { card, table } = await openDetail();
    expect((await within(card).findByTestId("vars-reason")).textContent).toContain("다중 baseline");
    expect(check(table, "CUSH_L_THK_1").disabled).toBe(true);
    expect(input(table, "CUSH_L_THK_1 하한").disabled).toBe(true);
    expect(head(card).queryByRole("button", { name: "저장" })).toBeNull();
  });

});

// ------------------------------------------------------------------ ⑥ 변수 범위

async function openSetup() {
  fireEvent.click(await screen.findByRole("tab", { name: /새 최적화/ }));
  await screen.findByRole("columnheader", { name: "사용" }); // 변수 정의를 불러온 뒤(그 전엔 표 없음)
  const vars = screen.getByRole("table", { name: "변수 범위" });
  await within(vars).findByTestId("var-CUSH_L_THK_1");
  return vars;
}
const soRole = async () => fireEvent.change(await screen.findByLabelText("MaxStress 역할"), { target: { value: "min" } });

describe("⑥ 내장 최적화 변수 범위 — Native(V-NV-9)", () => {
  it("세트 정의로 초기화: 학습 범위·모핑 가능 범위·고정 열, 학습 범위 모름 = 모름 + 안내, '이 실행에만 적용' 한 줄", async () => {
    renderApp(`${STUDY}/5`, { user: "power", geometry: "native" }, nativeCurrent);
    const vars = await openSetup();
    expect(within(vars).getAllByRole("columnheader").map((h) => h.textContent)).toEqual(["사용", "변수", "종류", "공칭", "학습 범위", "모핑 가능 범위", "하한", "상한", "고정", "경고"]);
    expect(within(vars).getByTestId("train-CUSH_L_THK_1").textContent).toBe("11.88 ~ 13.13");
    await waitFor(() => expect(within(vars).getByTestId("train-CUSH_L_POCKET_D_1").textContent).toBe("모름")); // 그 변수만 추적 불가
    expect(screen.getByTestId("vars-run-note").textContent).toContain("이 실행에만 적용(세트 정의는 ④에서)");
    expect(screen.getByText("범위 자유 · 학습 범위·모핑 가능 범위 밖은 경고 · 하한 = 상한이면 고정")).toBeTruthy();
    expect(screen.queryByText("학습 범위 안만 · 하한 = 상한이면 고정")).toBeNull();
    expect(screen.queryByLabelText("변수 추가")).toBeNull(); // 세트에 풀 전체가 있어 추가 후보 없음
    expect((await screen.findByTestId("var-note-TRAIN_RANGE_UNMATCHED")).textContent).toMatch(/학습/); // 안내(이름 없음)는 카드 아래 한 줄
  });

  it("범위 밖 = 차단 대신 경고(학습 범위·모핑 가능 범위·양면 접촉) · 시작은 막지 않는다 · 요청 bounds", async () => {
    const { server } = renderApp(`${STUDY}/5`, { user: "power", geometry: "native" }, nativeCurrent);
    const posts = record(server, /\/surrogate-opts$/);
    const vars = await openSetup();
    fireEvent.change(within(vars).getByLabelText("CUSH_L_THK_1 상한"), { target: { value: "30" } });
    const row = within(vars).getByTestId("var-CUSH_L_THK_1");
    expect(row.textContent).not.toContain("학습 범위 11.875~13.125 안"); // 기존 차단 문구 없음
    expect(within(row).getByRole("img", { name: /학습 형상 분포 밖 — 외삽 주의/ })).toBeTruthy();
    expect(within(row).getByRole("img", { name: /모핑 실패 가능/ })).toBeTruthy();
    expect(within(vars).getByTestId("var-CUSH_L_RIB_T_2").querySelector('[data-code="VAR_REF_LOCKED"]')).toBeTruthy();
    await soRole();
    const start = (await screen.findByRole("button", { name: "최적화 시작" })) as HTMLButtonElement;
    await waitFor(() => expect(start.disabled).toBe(false));
    fireEvent.click(start);
    await waitFor(() => expect(posts.length).toBe(1));
    expect((posts[0].b as { bounds: unknown }).bounds).toEqual({ CUSH_L_THK_1: [11.875, 30] });
    expect("vars" in posts[0].b!).toBe(false);
  });

  it("제외 vs 고정: 제외(체크 해제) = vars.exclude(bounds 없음), 고정 = bounds[이름]=[v,v](vars 없음) · 변수 추가 = vars.add + 기본 범위", async () => {
    const { server } = renderApp(`${STUDY}/5`, { user: "power", geometry: "native" }, (s) => {
      nativeCurrent(s);
      // 세트 정의를 4개로 줄여 추가 후보를 만든다
      const ps = s.paramSets.find((p) => p.id === "ps-n1")!;
      ps.parameters = ps.parameters.filter((p) => p.name !== "CUSH_L_FILLET_R_1");
    });
    const posts = record(server, /\/surrogate-opts(\/preview)?$/);
    const vars = await openSetup();
    // 제외
    fireEvent.click(check(vars, "CUSH_L_POCKET_D_1"));
    expect(within(vars).getByTestId("var-CUSH_L_POCKET_D_1").className).toContain("unused");
    // 고정(별도 열)
    fireEvent.click(within(vars).getByLabelText("CUSH_L_THK_1 고정"));
    expect(within(vars).getByTestId("var-CUSH_L_THK_1").textContent).toContain("고정");
    expect(check(vars, "CUSH_L_THK_1").checked).toBe(true); // 고정은 목록에 남는다
    // 추가
    const add = screen.getByLabelText("변수 추가") as HTMLSelectElement;
    expect([...add.options].map((o) => o.value)).toEqual(["", "CUSH_L_FILLET_R_1"]);
    fireEvent.change(add, { target: { value: "CUSH_L_FILLET_R_1" } });
    const added = await within(vars).findByTestId("var-CUSH_L_FILLET_R_1");
    expect(added.textContent).toContain("추가");
    expect(input(added, "CUSH_L_FILLET_R_1 하한").value).toBe("1.9"); // 피처 기본 범위
    await soRole();
    await waitFor(() => expect(posts.some((p) => p.p.endsWith("/preview") && (p.b as { vars?: unknown }).vars)).toBe(true));
    const last = [...posts].reverse().find((p) => p.p.endsWith("/preview"))!.b as { bounds: unknown; vars: unknown };
    expect(last.vars).toEqual({ add: ["CUSH_L_FILLET_R_1"], exclude: ["CUSH_L_POCKET_D_1"] });
    expect(last.bounds).toEqual({ CUSH_L_THK_1: [11.875, 11.875] });
    // 미리보기 문구: 자유 변수에서 고정·제외는 빠진다(THK 고정 + POCKET 제외 → 자유 3)
    await waitFor(() => expect(screen.getByTestId("so-preview").textContent).toMatch(/예측 최대/));
    // 추가 행은 [빼기]
    fireEvent.click(within(added).getByRole("button", { name: "빼기" }));
    expect(screen.queryByTestId("var-CUSH_L_FILLET_R_1")).toBeNull();
  });

  it("다중 선택 일괄 사용 해제(엑셀식)", async () => {
    renderApp(`${STUDY}/5`, { user: "power", geometry: "native" }, nativeCurrent);
    const vars = await openSetup();
    fireEvent.click(within(vars).getByTestId("var-CUSH_L_THK_1"));
    fireEvent.click(within(vars).getByTestId("var-CUSH_L_HOLE_U_1"), { ctrlKey: true });
    fireEvent.click(within(screen.getByTestId("bulk-use-bar")).getByRole("button", { name: "사용 해제" }));
    expect([check(vars, "CUSH_L_THK_1").checked, check(vars, "CUSH_L_HOLE_U_1").checked, check(vars, "CUSH_L_RIB_U_1").checked]).toEqual([false, false, true]);
  });

  it("Altair 템플릿: 기존 화면 그대로(차단 문구·안내·열, 추가·사용 열 없음) · 요청에 vars 없음", async () => {
    const { server } = renderApp(`${STUDY}/5`, { user: "power" });
    const posts = record(server, /\/surrogate-opts(\/preview)?$/);
    fireEvent.click(await screen.findByRole("tab", { name: /새 최적화/ }));
    const vars = await screen.findByRole("table", { name: "변수 범위" });
    expect(within(vars).getAllByRole("columnheader").map((h) => h.textContent)).toEqual(["변수", "학습 범위", "하한", "상한", "정수", "고정", ""]);
    expect(screen.getByText("학습 범위 안만 · 하한 = 상한이면 고정")).toBeTruthy();
    expect(screen.queryByLabelText("변수 추가")).toBeNull();
    expect(screen.queryByTestId("bulk-use-bar")).toBeNull();
    fireEvent.change(within(vars).getByLabelText("THK_TOP 상한"), { target: { value: "9" } });
    expect(within(vars).getByTestId("var-THK_TOP").textContent).toContain("학습 범위 0.3~1.2 안");
    fireEvent.change(within(vars).getByLabelText("THK_TOP 상한"), { target: { value: "1.0" } });
    await soRole();
    await waitFor(() => expect(posts.length).toBeGreaterThan(0));
    expect(posts.every((p) => !("vars" in (p.b as object)))).toBe(true);
  });
});

// ------------------------------------------------------------------ ④ 일괄 예측

async function openBatch() {
  fireEvent.click(await screen.findByRole("radio", { name: "일괄 예측(DOE)" }));
  const setup = await screen.findByRole("region", { name: "1 템플릿·조합" });
  await within(setup).findByRole("columnheader", { name: "사용" });
  const table = within(setup).getByRole("table", { name: "파라미터 범위" });
  await within(table).findByTestId("var-CUSH_L_THK_1");
  return { setup, table };
}

describe("④ 일괄 예측 — Native 범위 표·그 자리 편집(V-NV-9)", () => {
  it("공용 변수 표(사용·학습 범위·모핑 가능 범위·경고) → 제외·추가가 미리보기·실행 본문 vars로, 미리보기 notes에 경고", async () => {
    const { server } = renderApp(`${STUDY}/4`, { user: "power", geometry: "native" }, (s) => {
      nativeCurrent(s);
      const ps = s.paramSets.find((p) => p.id === "ps-n1")!;
      ps.parameters = ps.parameters.filter((p) => p.name !== "CUSH_L_FILLET_R_1");
    });
    const previews = record(server, /\/predict-batches\/preview$/);
    const { setup, table } = await openBatch();
    expect(within(table).getAllByRole("columnheader").map((h) => h.textContent)).toEqual(["사용", "파라미터", "종류", "공칭", "학습 범위", "모핑 가능 범위", "최소", "최대", "경고"]);
    expect(within(setup).getByTestId("vars-run-note").textContent).toContain("이 실행에만 적용");
    fireEvent.click(check(table, "CUSH_L_POCKET_D_1")); // 제외
    fireEvent.change(within(setup).getByLabelText("변수 추가"), { target: { value: "CUSH_L_FILLET_R_1" } });
    const added = await within(table).findByTestId("var-CUSH_L_FILLET_R_1");
    fireEvent.change(input(added, "CUSH_L_FILLET_R_1 최대"), { target: { value: "2.6" } }); // 모핑 가능 범위(없음) · 학습 범위 밖
    fireEvent.change(input(table, "CUSH_L_HOLE_U_1 최소"), { target: { value: "20" } }); // 모핑 가능 27~40 밖
    expect(within(table).getByTestId("var-CUSH_L_HOLE_U_1").querySelector('[data-code="VAR_OUT_OF_FEASIBLE"]')).toBeTruthy();
    fireEvent.click(within(setup).getByRole("button", { name: "조합 만들기" }));
    await waitFor(() => expect(previews.length).toBe(1));
    const b = previews[0].b as { vars: unknown; model_id: unknown; source: { ranges: unknown; kind: string } };
    expect(b.vars).toEqual({ add: ["CUSH_L_FILLET_R_1"], exclude: ["CUSH_L_POCKET_D_1"] });
    expect(b.model_id).toBeTruthy();
    const pv = await screen.findByRole("table", { name: "조합 미리보기" });
    expect(within(pv).getAllByRole("columnheader").map((h) => h.textContent)).toContain("CUSH_L_FILLET_R_1");
    expect(within(pv).getAllByRole("columnheader").map((h) => h.textContent)).not.toContain("CUSH_L_POCKET_D_1");
    const notes = screen.getAllByTestId("preview-note").map((n) => n.textContent);
    expect(notes.some((t) => /CUSH_L_HOLE_U_1.*모핑 실패 가능/.test(t ?? ""))).toBe(true);
    expect(notes.some((t) => /CUSH_L_FILLET_R_1.*학습 형상 분포 밖/.test(t ?? ""))).toBe(true);
  });

  it("실행: params.vars 포함, 배치 상세에 사용 변수 스냅숏 한 줄", async () => {
    const { server } = renderApp(`${STUDY}/4`, { user: "power", geometry: "native" }, nativeCurrent);
    const jobs = record(server, /\/studies\/s-cushion\/jobs$/);
    const { setup, table } = await openBatch();
    fireEvent.click(check(table, "CUSH_L_RIB_T_2"));
    fireEvent.click(within(setup).getByRole("button", { name: "조합 만들기" }));
    await screen.findByRole("table", { name: "조합 미리보기" });
    const run = (await screen.findByRole("button", { name: /입력 생성 \+ 일괄 예측 실행/ })) as HTMLButtonElement;
    await waitFor(() => expect(run.disabled).toBe(false));
    fireEvent.click(run);
    await waitFor(() => expect(jobs.length).toBe(1));
    expect((jobs[0].b as { params: { vars: unknown } }).params.vars).toEqual({ add: [], exclude: ["CUSH_L_RIB_T_2"] });
    const line = await screen.findByTestId("batch-vars");
    expect(line.textContent).toBe("사용 변수 — 변수 5개 · 세트 정의 rev 0 · 제외 1 · 이 실행에서 편집");
  });

  it("① DOE 재사용: 변수 표 대신 안내, 요청에 vars 없음 · table 방식: 표는 잠금", async () => {
    const { server } = renderApp(`${STUDY}/4`, { user: "power", geometry: "native" }, nativeCurrent);
    const previews = record(server, /\/predict-batches\/preview$/);
    const { setup, table } = await openBatch();
    fireEvent.click(check(table, "CUSH_L_RIB_T_2"));
    fireEvent.change(within(setup).getByLabelText("표본 방식"), { target: { value: "table" } });
    expect(input(await within(setup).findByRole("table", { name: "파라미터 범위" }), "CUSH_L_THK_1 최소").disabled).toBe(true);
    fireEvent.change(within(setup).getByLabelText("표본 방식"), { target: { value: "train_doe" } });
    expect((await within(setup).findByTestId("vars-from-doe")).textContent).toBe("① DOE의 변수 구성을 그대로 씁니다");
    expect(within(setup).queryByRole("table", { name: "파라미터 범위" })).toBeNull();
    fireEvent.click(within(setup).getByRole("button", { name: "조합 만들기" }));
    await waitFor(() => expect(previews.length).toBe(1));
    expect("vars" in previews[0].b!).toBe(false);
  });

  it("Altair 템플릿: 기존 범위 표 그대로(사용 열·변수 추가 없음), 요청에 vars·model_id 없음", async () => {
    const { server } = renderApp(`${STUDY}/4`, { user: "power" });
    const previews = record(server, /\/predict-batches\/preview$/);
    fireEvent.click(await screen.findByRole("radio", { name: "일괄 예측(DOE)" }));
    const setup = await screen.findByRole("region", { name: "1 템플릿·조합" });
    const table = await within(setup).findByRole("table", { name: "파라미터 범위" });
    expect(within(table).getAllByRole("columnheader").map((h) => h.textContent)).toEqual(["파라미터", "최소", "최대"]);
    expect(within(setup).queryByLabelText("변수 추가")).toBeNull();
    expect(screen.queryByTestId("bulk-use-bar")).toBeNull();
    fireEvent.click(within(setup).getByRole("button", { name: "조합 만들기" }));
    await waitFor(() => expect(previews.length).toBe(1));
    expect(Object.keys(previews[0].b!).sort()).toEqual(["param_set_id", "source"]);
  });
});

// ------------------------------------------------------------------ 결과·배치 상세 스냅숏

describe("스냅숏 요약 한 줄", () => {
  it("⑥ 결과: settings.vars가 있으면 한 줄, 없으면(Altair·이전 기록) 줄 없음", async () => {
    renderApp(`${STUDY}/5/surrogate/so-1`, { user: "power" }, (s) => {
      s.surrogate[0].settings.vars = { set_revision: 2, edited: true, variables: [{ name: "THK_TOP", origin: "set" }, { name: "X", origin: "added" }], excluded: ["E_FOAM"] };
    });
    expect((await screen.findByTestId("so-vars")).textContent).toBe("사용 변수 — 변수 2개 · 세트 정의 rev 2 · 추가 1 · 제외 1 · 이 실행에서 편집");
  });
  it("⑥ 결과(스냅숏 없음)·배치 상세(스냅숏 없음): 줄 없음", async () => {
    renderApp(`${STUDY}/5/surrogate/so-1`, { user: "power" });
    await screen.findByTestId("so-status");
    expect(screen.queryByTestId("so-vars")).toBeNull();
  });
});
