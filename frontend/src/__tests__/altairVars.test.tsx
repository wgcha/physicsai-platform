// v0.2.8 altair-vars.md V-AV-9(UI): Altair 변수 표(④ 세트 상세 편집·정수 검증·범위 모름·읽기 전용 안내, ⑥·④ 일괄 공용 표), ①-2 tpl 요약 한 줄,
// from-train tpl_source 선택·오류 안내. Native 열은 Altair에서 숨기고 Native 표는 그대로.
import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { renderApp, STUDY } from "../test/render";
import type { MockServer } from "../mock/server";
import type { NativeVars, TplSummary } from "../api";
import { TPL_ERROR_TEXT, tplErrorText, tplSummaryNotes, tplSummaryText } from "../lib/altairVars";
import { ApiError } from "../api";
import { detailRows, putBody, reasonText, rowError, runRows, usesVarTable, TPL_PARTIAL_TEXT } from "../lib/nativeVars";
import { ALTAIR_POOL } from "../mock/altairVars";
import { err } from "../mock/route";

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
const current = (id: string) => (s: MockServer) => s.paramSets.forEach((p) => (p.is_current = p.id === id));
const input = (root: HTMLElement, label: string) => within(root).getByLabelText(label) as HTMLInputElement;
const check = (root: HTMLElement, name: string) => input(root, `${name} 사용`);
const heads = (t: HTMLElement) => within(t).getAllByRole("columnheader").map((h) => h.textContent);

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

// ------------------------------------------------------------------ 순수 규칙

const NV = (extra: Partial<NativeVars> = {}): NativeVars =>
  ({ revision: 1, editable: true, engine: "altair", variables: [{ name: "THK_TOP", min: 0.3, max: 1.2 }, { name: "RIB_N", min: 2, max: 8 }], pool: ALTAIR_POOL, notes: [], warnings: [], history: [], ...extra }) as NativeVars;

describe("lib — Altair 행 규칙", () => {
  it("풀 행: type·body null 허용, 정수 표시, 범위 모름 행은 빈칸으로 시작", () => {
    const rows = detailRows(NV());
    const by = Object.fromEntries(rows.map((r) => [r.name, r]));
    expect(by.THK_TOP.use).toBe(true);
    expect(by.E_FOAM).toMatchObject({ use: false, lo: "2", hi: "20", type: "", body: "" }); // 미사용 = 표 범위 승계
    expect(by.RIB_N.integer).toBe(true);
    expect(by.HOLE_D).toMatchObject({ rangeUnset: true, lo: "", hi: "" });
    expect(runRows(NV(), { add: ["HOLE_D"], exclude: [] }).find((r) => r.name === "HOLE_D")).toMatchObject({ origin: "added", lo: "" });
  });

  it("검사: 정수 파라미터는 정수만, 범위 모름은 안내, 사용 해제 행은 검사 없음, PUT 본문은 사용 행", () => {
    const rows = detailRows(NV());
    const rib = rows.find((r) => r.name === "RIB_N")!;
    expect(rowError({ ...rib, hi: "6.5" })).toBe("정수만 입력하세요");
    expect(rowError({ ...rib, lo: "2.5", hi: "6" })).toBe("정수만 입력하세요");
    expect(rowError({ ...rib, lo: "3", hi: "6" })).toBeNull();
    expect(rowError({ ...rib, lo: "7", hi: "6" })).toBe("하한 ≤ 상한");
    expect(rowError({ ...rib, use: false, hi: "6.5" })).toBeNull();
    const hole = rows.find((r) => r.name === "HOLE_D")!;
    expect(rowError({ ...hole, use: true })).toBe("범위를 입력하세요");
    expect(rowError({ ...hole, use: true, lo: "5", hi: "" })).toBe("범위를 입력하세요");
    expect(putBody(rows, 1)).toEqual({ base_revision: 1, variables: [{ name: "THK_TOP", min: 0.3, max: 1.2 }, { name: "RIB_N", min: 2, max: 8 }] });
  });

  it("변수 표를 쓰는 세트 = Native 또는 Altair 전체 tpl, 사유 코드는 한국어 안내", () => {
    expect(usesVarTable({ engine: "native" })).toBe(true);
    expect(usesVarTable({ engine: "altair", vars_scope: "full" })).toBe(true);
    expect(usesVarTable({ engine: "altair", vars_scope: "partial" })).toBe(false);
    expect(usesVarTable({ engine: "altair" })).toBe(false);
    expect(reasonText("TPL_SCOPE_PARTIAL")).toBe(TPL_PARTIAL_TEXT);
    expect(TPL_PARTIAL_TEXT).toContain("①-2에서 tpl을 다시 생성");
    expect(reasonText("다중 baseline")).toBe("다중 baseline");
  });

  it("tpl_summary 문구: 전체·사용·미사용 / 표기 손실·제외 경고 / 옛 tpl", () => {
    const s: TplSummary = { total: 12, used: 4, skipped: ["BAD"], format_loss: ["X_1"], scope: "full" };
    expect(tplSummaryText(s)).toBe("전체 12개 포함(사용 4개 = DOE 범위, 미사용 8개 공칭 고정)");
    expect(tplSummaryNotes(s)).toEqual([expect.stringContaining("공칭 표기 손실 1개(X_1)"), expect.stringContaining("유효하지 않은 미사용 1개")]);
    expect(tplSummaryNotes({ ...s, skipped: [], format_loss: [] })).toEqual([]);
    expect(tplSummaryText({ ...s, scope: "partial" })).toContain("옛 tpl");
  });

  it("from-train 오류 코드 → 안내 문구(그 밖의 오류는 서버 문구)", () => {
    for (const code of ["TPL_DOE_MISMATCH", "TPL_SCOPE_PARTIAL", "TPL_REQUIRED"]) {
      expect(tplErrorText(new ApiError(409, { code, message: "x" } as never))).toBe(TPL_ERROR_TEXT[code]);
      expect(TPL_ERROR_TEXT[code]).toMatch(/[가-힣]/);
    }
    expect(tplErrorText(new ApiError(409, { code: "DOE_NOT_READY", message: "준비된 DOE가 필요합니다." } as never))).toBe("준비된 DOE가 필요합니다.");
  });
});

// ------------------------------------------------------------------ ④ 세트 상세

async function openDetail() {
  fireEvent.click(await screen.findByRole("button", { name: "템플릿 관리" }));
  const card = await screen.findByRole("region", { name: "템플릿 관리" });
  const table = await within(card).findByRole("table", { name: "템플릿 변수 표" });
  return { card, table };
}
const head = (card: HTMLElement) => within(within(card).getByTestId("vars-head"));

describe("④ Altair 세트 상세 변수 표", () => {
  it("전체 tpl: Native 전용 열 없이 사용·이름·공칭·하한·상한·경고, 머리줄 rev·사용 k/풀, 정수 표시", async () => {
    renderApp(`${STUDY}/4`, { user: "power", altairVars: true }, current("ps-a1"));
    const { card, table } = await openDetail();
    expect(heads(table)).toEqual(["사용", "이름", "공칭", "하한", "상한", "경고"]);
    expect(within(card).getByTestId("vars-head").textContent).toMatch(/rev 0 · 사용 3\/6/);
    expect(within(table).getByTestId("av-RIB_N").textContent).toContain("정수");
    expect(check(table, "THK_TOP").checked).toBe(true);
    expect(check(table, "E_FOAM").checked).toBe(false);
    expect(within(table).getByTestId("av-E_FOAM").className).toContain("unused"); // 미사용 행은 흐리게
    expect(within(card).queryByTestId("vars-reason")).toBeNull();
  });

  it("미사용 파라미터를 켜면 표 범위가 입력되고, 정수 비정수 범위는 막고, 저장 PUT은 사용 행(리비전 증가)", async () => {
    const { server } = renderApp(`${STUDY}/4`, { user: "power", altairVars: true }, current("ps-a1"));
    const puts = record(server, /\/param-sets\/ps-a1\/variables$/, ["PUT"]);
    const { card, table } = await openDetail();
    const save = head(card).getByRole("button", { name: "저장" }) as HTMLButtonElement;
    expect(save.disabled).toBe(true);
    fireEvent.click(check(table, "E_FOAM"));
    expect(input(table, "E_FOAM 하한").value).toBe("2");
    expect(input(table, "E_FOAM 상한").value).toBe("20");
    fireEvent.change(input(table, "RIB_N 상한"), { target: { value: "6.5" } });
    expect(within(table).getByTestId("av-RIB_N").textContent).toContain("정수만 입력하세요");
    expect(save.disabled).toBe(true);
    fireEvent.change(input(table, "RIB_N 상한"), { target: { value: "6" } });
    expect(save.disabled).toBe(false);
    fireEvent.click(save);
    await waitFor(() => expect(puts.length).toBe(1));
    expect(puts[0].b).toEqual({
      base_revision: 0,
      variables: [{ name: "THK_TOP", min: 0.3, max: 1.2 }, { name: "THK_FOAM", min: 1, max: 3 }, { name: "E_FOAM", min: 2, max: 20 }, { name: "RIB_N", min: 2, max: 6 }],
    });
    await waitFor(() => expect(within(card).getByTestId("vars-head").textContent).toMatch(/rev 1 · 사용 4\/6/));
  });

  it("범위 모름(HOLE_D): 빈칸 + 안내, 켜면 입력 전까지 저장 불가", async () => {
    renderApp(`${STUDY}/4`, { user: "power", altairVars: true }, current("ps-a1"));
    const { card, table } = await openDetail();
    const row = within(table).getByTestId("av-HOLE_D");
    expect(row.textContent).toContain("범위를 입력하세요");
    expect(input(table, "HOLE_D 하한").value).toBe("");
    fireEvent.click(check(table, "HOLE_D"));
    expect(row.textContent).toContain("범위를 입력하세요");
    expect((head(card).getByRole("button", { name: "저장" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(input(table, "HOLE_D 하한"), { target: { value: "5" } });
    fireEvent.change(input(table, "HOLE_D 상한"), { target: { value: "7" } });
    expect((head(card).getByRole("button", { name: "저장" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("옛 부분 tpl(editable=false): 읽기 전용 + 재생성 안내, 저장 없음", async () => {
    renderApp(`${STUDY}/4`, { user: "power", altairVars: true }, current("ps-a2"));
    const { card, table } = await openDetail();
    const reason = await within(card).findByTestId("vars-reason");
    expect(reason.textContent).toContain("①-2에서 tpl을 다시 생성");
    expect(check(table, "THK_TOP").disabled).toBe(true);
    expect(input(table, "THK_TOP 하한").disabled).toBe(true);
    expect(head(card).queryByRole("button", { name: "저장" })).toBeNull();
  });

  it("Native 표는 종류·바디·모핑 가능 범위 열 그대로(회귀)", async () => {
    renderApp(`${STUDY}/4`, { user: "power", geometry: "native" }, (s) => s.paramSets.forEach((p) => (p.is_current = p.id === "ps-n1")));
    fireEvent.click(await screen.findByRole("button", { name: "템플릿 관리" }));
    const card = await screen.findByRole("region", { name: "템플릿 관리" });
    const table = await within(card).findByRole("table", { name: "형상 피처 표" });
    expect(heads(table)).toEqual(expect.arrayContaining(["종류", "바디", "모핑 가능 범위"]));
    expect(within(card).queryByRole("table", { name: "템플릿 변수 표" })).toBeNull();
  });
});

// ------------------------------------------------------------------ ⑥·④ 일괄

describe("⑥ 변수 범위·④ 일괄 — Altair 공용 표", () => {
  it("⑥: 전체 tpl은 학습 범위·고정 열이 있는 공용 표(Native 열 없음), 정수 오류, 부분 tpl은 기존 표 + 안내", async () => {
    renderApp(`${STUDY}/5`, { user: "power", altairVars: true }, current("ps-a1"));
    fireEvent.click(await screen.findByRole("tab", { name: /새 최적화/ }));
    const vars = await screen.findByRole("table", { name: "변수 범위" });
    await within(vars).findByTestId("var-THK_TOP");
    expect(heads(vars)).toEqual(["사용", "변수", "공칭", "학습 범위", "하한", "상한", "고정", "경고"]);
    expect(screen.getByText("범위 자유 · 학습 범위 밖은 경고 · 하한 = 상한이면 고정")).toBeTruthy();
    await waitFor(() => expect(within(vars).getByTestId("train-THK_TOP").textContent).toBe("0.3 ~ 1.2"));
    fireEvent.change(screen.getByLabelText("변수 추가"), { target: { value: "E_FOAM" } }); // 미사용이던 파라미터를 이 실행에만 추가
    await waitFor(() => expect(within(vars).getByTestId("train-E_FOAM").textContent).toBe("8 ~ 8")); // 학습 범위 = [공칭, 공칭]
    expect(within(vars).getByTestId("var-E_FOAM").querySelector('[data-code="VAR_OUT_OF_TRAIN"]')).toBeTruthy(); // 표 범위 2~20 = 외삽 경고(막지 않음)
    fireEvent.change(within(vars).getByLabelText("RIB_N 상한"), { target: { value: "5.5" } });
    expect(within(vars).getByTestId("var-RIB_N").textContent).toContain("정수만 입력하세요");
    // 학습 범위 밖은 경고만
    fireEvent.change(within(vars).getByLabelText("THK_TOP 상한"), { target: { value: "3" } });
    expect(within(vars).getByTestId("var-THK_TOP").querySelector('[data-code="VAR_OUT_OF_TRAIN"]')).toBeTruthy();
    expect(within(vars).getByTestId("var-THK_TOP").textContent).not.toContain("학습 범위 0.3~1.2 안");
  });

  it("⑥ 부분 tpl: 기존 표(학습 범위 안만) + 재생성 안내 1줄", async () => {
    renderApp(`${STUDY}/5`, { user: "power", altairVars: true }, current("ps-a2"));
    fireEvent.click(await screen.findByRole("tab", { name: /새 최적화/ }));
    expect(await screen.findByText("학습 범위 안만 · 하한 = 상한이면 고정")).toBeTruthy();
    expect(screen.getByTestId("tpl-partial-note").textContent).toContain("①-2에서 tpl을 다시 생성");
  });

  it("④ 일괄: 미사용 파라미터 추가 → 미리보기 본문 vars.add, 정수 비정수 범위는 조합 만들기 비활성", async () => {
    const { server } = renderApp(`${STUDY}/4`, { user: "power", altairVars: true }, current("ps-a1"));
    const previews = record(server, /\/predict-batches\/preview$/);
    fireEvent.click(await screen.findByRole("radio", { name: "일괄 예측(DOE)" }));
    const setup = await screen.findByRole("region", { name: "1 템플릿·조합" });
    await within(setup).findByRole("columnheader", { name: "사용" });
    const table = within(setup).getByRole("table", { name: "파라미터 범위" });
    await within(table).findByTestId("var-THK_TOP");
    expect(heads(table)).toEqual(["사용", "파라미터", "공칭", "학습 범위", "최소", "최대", "경고"]);
    const make = within(setup).getByRole("button", { name: "조합 만들기" }) as HTMLButtonElement;
    fireEvent.change(input(table, "RIB_N 최대"), { target: { value: "6.5" } });
    expect(within(table).getByTestId("var-RIB_N").textContent).toContain("정수만 입력하세요");
    expect(make.disabled).toBe(true);
    fireEvent.change(input(table, "RIB_N 최대"), { target: { value: "6" } });
    expect(make.disabled).toBe(false);
    fireEvent.change(within(setup).getByLabelText("변수 추가"), { target: { value: "E_FOAM" } });
    const added = await within(table).findByTestId("var-E_FOAM");
    expect(input(added, "E_FOAM 최소").value).toBe("2");
    fireEvent.click(make);
    await waitFor(() => expect(previews.length).toBe(1));
    expect((previews[0].b as { vars: unknown }).vars).toEqual({ add: ["E_FOAM"], exclude: [] });
  });

  it("④ 일괄 부분 tpl: 기존 표 + 재생성 안내", async () => {
    renderApp(`${STUDY}/4`, { user: "power", altairVars: true }, current("ps-a2"));
    fireEvent.click(await screen.findByRole("radio", { name: "일괄 예측(DOE)" }));
    const setup = await screen.findByRole("region", { name: "1 템플릿·조합" });
    expect((await within(setup).findByTestId("tpl-partial-note")).textContent).toContain("①-2에서 tpl을 다시 생성");
    expect(within(setup).queryByLabelText("변수 추가")).toBeNull();
  });
});

// ------------------------------------------------------------------ ①-2 tpl 요약 · from-train

describe("①-2 tpl 요약 한 줄", () => {
  it("전체/사용/미사용 한 줄 + 제외 경고, 미사용 행은 '공칭 고정' 표시", async () => {
    renderApp(`${STUDY}/1`, { user: "power" });
    const card = await screen.findByRole("region", { name: "파라미터 표" });
    await within(card).findByRole("table", { name: "파라미터 표" });
    const st = within(card).getByTestId("tpl-state");
    expect(st.textContent).toContain("tpl 생성됨 · 전체 5개 포함(사용 4개 = DOE 범위, 미사용 1개 공칭 고정)");
    expect(within(st).getByTestId("tpl-summary-note").textContent).toContain("유효하지 않은 미사용 1개");
    expect(within(within(card).getByLabelText("FILLET_R 사용").closest("tr")!).getByText("tpl에 공칭 고정")).toBeTruthy();
    expect(within(card).getByLabelText("THK_TOP 사용").closest("tr")!.textContent).not.toContain("tpl에 공칭 고정");
  });
});

describe("④ ① 결과로 만들기 — tpl 출처", () => {
  async function openFromTrain() {
    fireEvent.click(await screen.findByRole("button", { name: "템플릿 관리" }));
    const card = await screen.findByRole("region", { name: "템플릿 관리" });
    fireEvent.click(within(card).getByRole("button", { name: "새로 등록" }));
    fireEvent.click(within(card).getByRole("button", { name: "① 결과로 만들기" }));
    const form = await within(card).findByTestId("from-train");
    await waitFor(() => expect((within(form).getByLabelText("DOE 선택") as HTMLSelectElement).value).toBe("doe-1"));
    return form;
  }

  it("기본 'DOE 기준'·선택지 '현재 tpl', 요청에 tpl_source(기본 doe)", async () => {
    const { server } = renderApp(`${STUDY}/4`, { user: "power" });
    const posts = record(server, /\/param-sets\/from-train$/);
    const form = await openFromTrain();
    const group = within(form).getByRole("radiogroup", { name: "tpl 출처" });
    expect(within(group).getByRole("radio", { name: "DOE 기준" }).getAttribute("aria-checked")).toBe("true");
    fireEvent.click(within(form).getByRole("button", { name: "① 결과로 만들기" }));
    await waitFor(() => expect(posts.length).toBe(1));
    expect(posts[0].b).toMatchObject({ doe_id: "doe-1", tpl_source: "doe" });
  });

  it("'현재 tpl' 선택 → tpl_source current, 성공하면 전체 tpl 세트", async () => {
    const { server } = renderApp(`${STUDY}/4`, { user: "power" });
    const posts = record(server, /\/param-sets\/from-train$/);
    const form = await openFromTrain();
    const group = within(form).getByRole("radiogroup", { name: "tpl 출처" });
    fireEvent.click(within(group).getByRole("radio", { name: "현재 tpl" }));
    expect(within(group).getByRole("radio", { name: "현재 tpl" }).getAttribute("aria-checked")).toBe("true");
    fireEvent.click(within(form).getByRole("button", { name: "① 결과로 만들기" }));
    await waitFor(() => expect(posts.length).toBe(1));
    expect(posts[0].b).toMatchObject({ doe_id: "doe-1", tpl_source: "current" });
    await waitFor(() => expect(server.paramSets[0].vars_scope).toBe("full"));
  });

  it("현재 tpl 오류 코드는 안내 문구로(TPL_DOE_MISMATCH·TPL_REQUIRED·TPL_SCOPE_PARTIAL)", async () => {
    for (const [code, status] of [["TPL_DOE_MISMATCH", 409], ["TPL_REQUIRED", 409], ["TPL_SCOPE_PARTIAL", 422]] as const) {
      const { server, unmount } = renderApp(`${STUDY}/4`, { user: "power" });
      const orig = server.handle.bind(server);
      server.handle = (m, p, q, b, h) => (m === "POST" && /from-train$/.test(p) ? err(status, code, "서버 원문") : orig(m, p, q, b, h));
      const form = await openFromTrain();
      fireEvent.click(within(within(form).getByRole("radiogroup", { name: "tpl 출처" })).getByRole("radio", { name: "현재 tpl" }));
      fireEvent.click(within(form).getByRole("button", { name: "① 결과로 만들기" }));
      const alert = await within(form).findByRole("alert");
      expect(alert.textContent).toBe(TPL_ERROR_TEXT[code]);
      unmount();
    }
  });
});
