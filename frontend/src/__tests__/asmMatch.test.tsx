// v0.2.9 조립 매칭 화면(asm-match.md §3.2·§6.5) + v0.2.10 AM-C3: 표 편집(1:N)·N:1 차단·추천 자동 채움·검사 없이 저장·
// 고급(접힘) 경계 검사(일치율·거리·공유 노드·원점 차이)와 불합격 경고(저장은 막지 않음)·검사 취소 → ①-3 Native DOE 문구 전환.
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { render } from "@testing-library/react";
import { TestApp } from "../app/App";
import { renderApp, STUDY } from "../test/render";
import type { MockServer } from "../mock/server";
import { nativeTrainParams } from "../mock/geometry";
import { ASM_ERROR_TEXT, ASM_FIRST_TEXT, ASM_PROBLEM_TEXT, addPart, checkNotice, excludeBlock, isAsmMissing, rowNotes, stateLabel, worstPoints, asmCodeText, draftProblems, failLines, partChoice, recommendDraft, removePart, saveBlock, setExcluded, suggestText, toPut, usedBy } from "../lib/asmMatch";
import { ApiError, errorMessage, type AsmCheckRow, type AsmMatch, type AsmPart } from "../api";
import { nearestScreenPoint } from "../stages/stage4/geomview/viewerCore";
import { err } from "../mock/route";

const ASSEM = "E:/shared/AI_WORK/cushion/00_inbox/radioss_assem";
const nativeSetup = (s: MockServer) => Object.assign(s.p2.setups["s-cushion"], { engine: "native", parameters: nativeTrainParams(), tpl: null });

async function open(suffix = "") {
  const r = renderApp(`${STUDY}/1`, { user: "power" }, nativeSetup);
  const card = await screen.findByRole("region", { name: "조립 매칭" });
  const doe = await screen.findByRole("region", { name: "DOE · Radioss 입력" });
  const calls: { method: string; path: string; body: unknown }[] = [];
  const orig = r.server.handle.bind(r.server);
  r.server.handle = (m, p, q, b, h) => {
    if (p.includes("/asm-matches") || p.includes("/asm-matches/") || (p.endsWith("/jobs") && m === "POST")) calls.push({ method: m, path: p, body: structuredClone(b) });
    return orig(m, p, q, b, h);
  };
  fireEvent.change(within(card).getByLabelText("조립 폴더"), { target: { value: ASSEM + suffix } });
  fireEvent.click(within(card).getByRole("button", { name: "확인" }));
  await within(card).findByText(/starter/);
  return { ...r, card, doe, calls };
}

async function scan(ctx: Awaited<ReturnType<typeof open>>) {
  fireEvent.click(within(ctx.card).getByRole("button", { name: "목록 읽기" }));
  await waitFor(() => expect(ctx.server.jobs.some((j) => j.job_type === "ASM_MATCH")).toBe(true));
  act(() => ctx.server.finishAll());
  return within(ctx.card).findByRole("table", { name: "조립 매칭 표" });
}
const pick = (card: HTMLElement, body: string, pid: number) => fireEvent.change(within(card).getByLabelText(`${body} component 추가`), { target: { value: String(pid) } });
const btn = (card: HTMLElement, name: string) => within(card).getByRole("button", { name }) as HTMLButtonElement;
async function check(ctx: Awaited<ReturnType<typeof open>>) {
  await waitFor(() => expect(btn(ctx.card, "검사").disabled).toBe(false));
  fireEvent.click(btn(ctx.card, "검사"));
  await waitFor(() => expect(ctx.server.jobs.filter((j) => j.job_type === "ASM_MATCH").length).toBe(2));
  act(() => ctx.server.finishAll());
  await waitFor(() => expect(within(ctx.card).getByTestId("asm-state").textContent).toMatch(/^(검사 통과|초안)/));
  await waitFor(() => expect(within(ctx.card).getByTestId("asm-verdict-CUSH_L")).toBeTruthy()); // 검사하면 고급이 펼쳐져 판정 열이 보인다
}
const advanced = (card: HTMLElement) => within(card).getByTestId("asm-advanced") as HTMLDetailsElement;
const matchCount = (ctx: Awaited<ReturnType<typeof open>>) => ctx.server.jobs.filter((j) => j.job_type === "ASM_MATCH").length;

describe("조립 매칭 카드", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it("목록 읽기 → 추천으로 미리 채운 표(바디 부피·bbox 요약, 추천 표지) · 매칭 안 한 component 수 안내", async () => {
    const ctx = await open();
    await scan(ctx);
    const l = within(ctx.card).getByTestId("asm-row-CUSH_L");
    expect(l.textContent).toContain("812 cm³");
    expect(l.textContent).toContain("120×80×20.5 mm");
    expect(within(ctx.card).getByTestId("asm-chips-CUSH_L").textContent).toContain("PART 3000001 · CUSH_L · TETRA4 41,230개 · 추천");
    expect(within(ctx.card).getByTestId("asm-chips-CUSH_R").textContent).toContain("PART 3000002 · CUSH_R_A");
    expect(within(ctx.card).getByTestId("asm-recommended")).toBeTruthy();
    expect(within(ctx.card).getByTestId("asm-summary").textContent).toContain("component 6개(TETRA4 4개)");
    expect(ctx.card.textContent).toContain("매칭하지 않은 component 4개는 바꾸지 않습니다");
    // AM-C3: 추천으로 모든 바디가 채워지면 검사 없이 바로 저장할 수 있다. 검사는 고급(기본 접힘) 안에만 있다
    expect(btn(ctx.card, "저장").disabled).toBe(false);
    expect(advanced(ctx.card).open).toBe(false);
    expect(advanced(ctx.card).textContent).toContain("고급 — 경계 검사(선택)");
    expect(within(advanced(ctx.card)).getByRole("button", { name: "검사" })).toBeTruthy();
    expect(advanced(ctx.card).contains(btn(ctx.card, "저장"))).toBe(false);
    expect(advanced(ctx.card).textContent).toContain("오래 걸릴 수 있음(대형 모델은 수십 분)");
    expect(within(ctx.card).queryByTestId("asm-verdict-CUSH_L")).toBeNull(); // 판정·거리 열은 고급을 펼칠 때만
    expect(within(ctx.card).queryByTestId("asm-check-warning")).toBeNull();
  });

  it("기본 흐름 = 목록 읽기 → 추천 자동 채움 → [저장]만: 검사 작업 없이 PUT rows → confirm, 상태 '저장됨'", async () => {
    const ctx = await open();
    await scan(ctx);
    expect(ctx.calls.some((c) => c.method === "PUT")).toBe(false); // 추천은 화면 초안 — 저장 전에는 서버에 쓰지 않는다
    fireEvent.click(btn(ctx.card, "저장"));
    await within(ctx.card).findByTestId("asm-confirmed");
    const put = ctx.calls.find((c) => c.method === "PUT")!;
    expect(put.body).toEqual({ rows: [{ body: "CUSH_L", pids: [3000001] }, { body: "CUSH_R", pids: [3000002] }], excluded_bodies: [] });
    expect(ctx.calls.findIndex((c) => c.method === "PUT")).toBeLessThan(ctx.calls.findIndex((c) => c.path.endsWith("/confirm")));
    expect(ctx.calls.some((c) => c.path.endsWith("/check"))).toBe(false);
    expect(matchCount(ctx)).toBe(1); // 목록 읽기 작업뿐 — 검사 작업 없음
    expect(within(ctx.card).getByTestId("asm-state").textContent).toBe("저장됨");
    expect(within(ctx.card).queryByTestId("asm-warnings")).toBeNull(); // 검사를 안 했으니 경고 없음
  });

  it("표 편집: 1:N 추가·빼기·'매칭 안 함'(사용 파라미터가 있으면 불가) → 검사 전 PUT rows", async () => {
    const ctx = await open();
    await scan(ctx);
    pick(ctx.card, "CUSH_R", 3000003);
    const chips = () => within(ctx.card).getByTestId("asm-chips-CUSH_R");
    expect(chips().textContent).toContain("PART 3000003 · CUSH_R_B");
    fireEvent.click(within(chips()).getByLabelText("CUSH_R에서 PART 3000003 빼기"));
    expect(chips().textContent).not.toContain("CUSH_R_B");
    pick(ctx.card, "CUSH_R", 3000003);
    // CUSH_L은 사용 파라미터가 있어 '매칭 안 함' 불가, CUSH_R은 가능
    expect((within(ctx.card).getByLabelText("CUSH_L 매칭 안 함") as HTMLInputElement).disabled).toBe(true);
    expect(within(ctx.card).getByTestId("asm-row-CUSH_L").textContent).toContain("선택한 파라미터가 있는 바디라 '매칭 안 함'으로 둘 수 없습니다");
    await check(ctx);
    const put = ctx.calls.find((c) => c.method === "PUT")!;
    expect(put.path).toMatch(/\/asm-matches\/[^/]+\/rows$/);
    expect(put.body).toEqual({ rows: [{ body: "CUSH_L", pids: [3000001] }, { body: "CUSH_R", pids: [3000002, 3000003] }], excluded_bodies: [] });
  });

  it("N:1 차단: 다른 행이 쓰는 PART·TETRA4 아닌 PART는 회색 + 사유, 선택해도 들어가지 않는다", async () => {
    const ctx = await open();
    await scan(ctx);
    const sel = within(ctx.card).getByLabelText("CUSH_R component 추가") as HTMLSelectElement;
    const opt = (pid: number) => [...sel.options].find((o) => o.value === String(pid))!;
    expect(opt(3000001).disabled).toBe(true);
    expect(opt(3000001).textContent).toContain("CUSH_L 행에서 사용");
    expect(opt(2001).disabled).toBe(true);
    expect(opt(2001).textContent).toContain("TETRA4가 아님: /SHELL 1,200개");
    expect(opt(3000003).disabled).toBe(false);
    pick(ctx.card, "CUSH_R", 3000001);
    expect(within(ctx.card).getByTestId("asm-chips-CUSH_R").textContent).not.toContain("PART 3000001");
    expect(within(ctx.card).getByTestId("asm-chips-CUSH_L").textContent).toContain("PART 3000001");
  });

  it("추천 채움: 모두 비워도 [추천 적용]이 추천(1:1 초안)을 다시 채운다 · 미결정 바디가 있으면 검사·저장 불가+사유", async () => {
    const ctx = await open();
    await scan(ctx);
    fireEvent.click(within(ctx.card).getByLabelText("CUSH_L에서 PART 3000001 빼기"));
    expect(btn(ctx.card, "검사").disabled).toBe(true);
    expect(btn(ctx.card, "저장").disabled).toBe(true);
    expect(within(ctx.card).getByTestId("asm-block").textContent).toContain("component를 고르지 않은 바디: CUSH_L");
    expect(within(ctx.card).getByTestId("asm-check-block").textContent).toContain("component를 고르지 않은 바디: CUSH_L");
    fireEvent.click(btn(ctx.card, "추천 적용"));
    expect(within(ctx.card).getByTestId("asm-chips-CUSH_L").textContent).toContain("PART 3000001");
    expect(btn(ctx.card, "검사").disabled).toBe(false);
    expect(btn(ctx.card, "저장").disabled).toBe(false);
  });

  it("고급 검사 PASS: 판정·일치율·최대/p95 거리·허용오차(고급이 펼쳐짐), 표를 바꾸면 '검사 필요' + 낡음 안내지만 저장은 가능", async () => {
    const ctx = await open();
    await scan(ctx);
    pick(ctx.card, "CUSH_R", 3000003);
    await check(ctx);
    expect(advanced(ctx.card).open).toBe(true);
    for (const b of ["CUSH_L", "CUSH_R"]) {
      expect(within(ctx.card).getByTestId(`asm-verdict-${b}`).textContent).toBe("일치");
      expect(within(ctx.card).getByTestId(`asm-dist-${b}`).textContent).toContain("최대 0.041 · p95 0.011 mm · 일치율 99.9%");
    }
    expect(within(ctx.card).getByTestId("asm-dist-CUSH_L").textContent).toContain("허용 0.05 mm");
    expect(within(ctx.card).getByTestId("asm-state").textContent).toBe("검사 통과 — 저장 전");
    expect(within(ctx.card).queryByTestId("asm-check-warning")).toBeNull();
    // 표를 바꾸면 검사 필요 + 낡음 안내 — 저장은 막지 않는다
    fireEvent.click(within(ctx.card).getByLabelText("CUSH_R에서 PART 3000003 빼기"));
    expect(within(ctx.card).getByTestId("asm-verdict-CUSH_R").textContent).toBe("검사 필요");
    expect(within(ctx.card).getByTestId("asm-check-warning").getAttribute("data-code")).toBe("ASM_CHECK_STALE_WARN");
    expect(btn(ctx.card, "저장").disabled).toBe(false);
    pick(ctx.card, "CUSH_R", 3000003);
    expect(within(ctx.card).queryByTestId("asm-check-warning")).toBeNull();
    fireEvent.click(btn(ctx.card, "저장"));
    await within(ctx.card).findByTestId("asm-confirmed");
    expect(within(ctx.card).getByTestId("asm-state").textContent).toBe("저장됨");
    expect(btn(ctx.card, "목록 읽기").disabled).toBe(false);
  });

  it("검사 FAIL(바디 바꿔 매칭): 불일치·일치율·최대 거리 문구 + 경고, 저장은 막지 않고 저장하면 경고(ASM_CHECK_FAILED_WARN)가 남는다", async () => {
    const ctx = await open();
    await scan(ctx);
    fireEvent.click(within(ctx.card).getByLabelText("CUSH_L에서 PART 3000001 빼기"));
    fireEvent.click(within(ctx.card).getByLabelText("CUSH_R에서 PART 3000002 빼기"));
    pick(ctx.card, "CUSH_L", 3000002);
    pick(ctx.card, "CUSH_R", 3000001);
    await check(ctx);
    expect(within(ctx.card).getByTestId("asm-verdict-CUSH_L").textContent).toBe("불일치");
    expect(within(ctx.card).getByTestId("asm-fail-lines").textContent).toContain("외곽 노드가 CAD 경계면과 맞지 않습니다 — 일치율 31.2%, 최대 41.20 mm");
    expect(within(ctx.card).getByTestId("asm-state").textContent).toBe("초안 — 경계 검사 불합격(저장은 가능)");
    expect(within(ctx.card).getByTestId("asm-check-warning").getAttribute("data-code")).toBe("ASM_CHECK_FAILED_WARN");
    expect(within(ctx.card).getByTestId("asm-check-warning").textContent).toContain("저장은 막지 않지만");
    expect(btn(ctx.card, "저장").disabled).toBe(false);
    fireEvent.click(btn(ctx.card, "저장"));
    await within(ctx.card).findByTestId("asm-confirmed");
    const warn = within(ctx.card).getByTestId("asm-warnings");
    expect(warn.textContent).toContain("불합격한 행이 있는 채로 저장했습니다");
    expect(within(ctx.card).queryByTestId("asm-check-warning")).toBeNull(); // 확정 뒤에는 서버 warnings 한 곳에서만 보인다
  });

  it("원점 차이: CUSH_L 불일치 + 'X 10.0 mm 어긋남' 안내를 보이되 저장은 막지 않는다(경고만, 서버 confirm 200)", async () => {
    const ctx = await open("_offset");
    await scan(ctx);
    pick(ctx.card, "CUSH_R", 3000003);
    await check(ctx);
    expect(within(ctx.card).getByTestId("asm-verdict-CUSH_L").textContent).toBe("불일치");
    expect(within(ctx.card).getByTestId("asm-verdict-CUSH_R").textContent).toBe("일치");
    expect(within(ctx.card).getByTestId("asm-fail-lines").textContent).toContain("CAD가 조립보다 X 10.0 mm 어긋나 있습니다 — CAD를 조립과 같은 원점·mm로 다시 내보내세요(저장 불가)");
    expect(btn(ctx.card, "저장").disabled).toBe(false);
    const id = [...ctx.server.jobs].reverse().find((j) => j.job_type === "ASM_MATCH")!.params.match_id as string;
    const res = await fetch(`/physicsai/api/asm-matches/${id}/confirm`, { method: "POST", headers: { "X-PhysicsAI-Request": "1" } });
    expect(res.status).toBe(200);
    const m = (await res.json()) as AsmMatch;
    expect(m.state).toBe("CONFIRMED");
    expect(m.warnings.map((w) => w.code)).toEqual(["ASM_CHECK_FAILED_WARN"]);
  });

  it("노드 공유: 상대 PART(id·제목)와 노드 수 안내(고급), 저장은 가능", async () => {
    const ctx = await open("_shared");
    await scan(ctx);
    pick(ctx.card, "CUSH_R", 3000003);
    await check(ctx);
    expect(within(ctx.card).getByTestId("asm-verdict-CUSH_R").textContent).toBe("불일치");
    expect(within(ctx.card).getByTestId("asm-fail-lines").textContent).toContain("PART 2001(PRODUCT_TIE)과 노드 37개 공유");
    expect(btn(ctx.card, "저장").disabled).toBe(false);
  });

  it("고급 검사 진행: '오래 걸릴 수 있음' 안내·진행 표시·[취소] → 작업이 멈추고 표는 그대로, 저장은 계속 가능", async () => {
    const ctx = await open();
    await scan(ctx);
    expect(within(ctx.card).queryByRole("button", { name: "취소" })).toBeNull();
    fireEvent.click(btn(ctx.card, "검사"));
    await waitFor(() => expect(matchCount(ctx)).toBe(2));
    expect(advanced(ctx.card).open).toBe(true); // 검사하면 진행률·취소가 보이게 펼쳐진다
    expect(within(ctx.card).getByTestId("asm-check-note").textContent).toContain("오래 걸릴 수 있음(대형 모델은 수십 분)");
    expect(within(ctx.card).getByTestId("asm-state").textContent).toBe("경계 검사 중");
    expect(btn(ctx.card, "취소")).toBeTruthy();
    expect(btn(ctx.card, "저장").disabled).toBe(true); // 진행 중에는 표를 바꿀 수 없다
    fireEvent.click(btn(ctx.card, "취소"));
    await waitFor(() => expect(ctx.calls.some((c) => c.method === "POST" && c.path.endsWith("/cancel"))).toBe(true));
    await waitFor(() => expect(within(ctx.card).getByTestId("asm-state").textContent).toBe("초안 — 저장 전"));
    expect(ctx.server.jobs.filter((j) => j.job_type === "ASM_MATCH").map((j) => j.state)).toEqual(["SUCCEEDED", "CANCELED"]);
    expect(within(ctx.card).queryByRole("button", { name: "취소" })).toBeNull();
    expect(within(ctx.card).getByTestId("asm-chips-CUSH_L").textContent).toContain("PART 3000001");
    expect(btn(ctx.card, "저장").disabled).toBe(false);
    expect(btn(ctx.card, "검사").disabled).toBe(false); // 취소 뒤 다시 검사할 수 있다
  });

  it("목록 읽기 실패(TETRA4 PART 없음): 코드를 한국어로 안내", async () => {
    const ctx = await open("_nosolid");
    fireEvent.click(within(ctx.card).getByRole("button", { name: "목록 읽기" }));
    await waitFor(() => expect(ctx.server.jobs.some((j) => j.job_type === "ASM_MATCH")).toBe(true));
    act(() => ctx.server.finishAll());
    expect((await within(ctx.card).findByTestId("asm-failed")).textContent).toContain("조립에 TETRA4 PART가 없습니다");
  });

  it("①-3 Native DOE 문구 전환: 매칭 없으면 매칭 카드 안내(기존 조립 폴더 입력 유지) → 저장하면 '조립 매칭 사용 중' 한 줄 + asm_match_id 전송", async () => {
    const ctx = await open();
    expect(within(ctx.doe).getByTestId("asm-guide").textContent).toContain("조립 매칭");
    expect(within(ctx.doe).getByLabelText("Radioss 조립 폴더")).toBeTruthy();
    expect(within(ctx.doe).queryByTestId("asm-in-use")).toBeNull();
    await scan(ctx);
    pick(ctx.card, "CUSH_R", 3000003);
    expect(btn(ctx.card, "저장").disabled).toBe(false); // 검사 없이 저장(AM-C3)
    fireEvent.click(btn(ctx.card, "저장"));
    const line = await within(ctx.doe).findByTestId("asm-in-use");
    expect(line.textContent).toBe(`조립 매칭 사용 중 — ${ASSEM} · STEP 바디 2개`);
    expect(within(ctx.doe).queryByLabelText("Radioss 조립 폴더")).toBeNull();
    expect(within(ctx.doe).queryByTestId("asm-guide")).toBeNull();
    expect(ctx.doe.textContent).not.toMatch(/renum|baseline\.inc|104_replace/i);
    fireEvent.change(within(ctx.doe).getByLabelText("run 수"), { target: { value: "12" } });
    fireEvent.change(within(ctx.doe).getByLabelText("시드"), { target: { value: "7" } });
    const gen = within(ctx.doe).getByRole("button", { name: "입력 생성" }) as HTMLButtonElement;
    await waitFor(() => expect(gen.disabled).toBe(false));
    fireEvent.click(gen);
    await waitFor(() => expect(ctx.calls.some((c) => c.method === "POST" && (c.body as { job_type?: string } | null)?.job_type === "TD_DOE_GEN")).toBe(true));
    const body = (ctx.calls.find((c) => (c.body as { job_type?: string } | null)?.job_type === "TD_DOE_GEN")!.body as { params: Record<string, unknown> }).params;
    expect(body.radioss_assem_path).toBe(ASSEM);
    expect(body.asm_match_id).toMatch(/^am-/);
    expect(matchCount(ctx)).toBe(1); // 검사 작업 없이도 ①-3 DOE가 쓸 수 있다
  });
});


describe("조립 매칭 — 서버 API 연동(확정 API)", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it("목록 API로 마지막 매칭을 복원한다(localStorage 없음): 다시 열면 같은 표·검사 결과", async () => {
    const ctx = await open();
    await scan(ctx);
    pick(ctx.card, "CUSH_R", 3000003);
    await check(ctx);
    expect(Object.keys(localStorage).filter((k) => k.startsWith("physicsai.asmMatch"))).toEqual([]);
    ctx.unmount();
    const calls: string[] = [];
    const orig = ctx.server.handle.bind(ctx.server);
    ctx.server.handle = (m, p, q, b, h) => (m === "GET" && p.includes("/asm-matches") && calls.push(`${p}?${q.toString()}`), orig(m, p, q, b, h));
    render(<TestApp path={`${STUDY}/1`} />);
    const card = await screen.findByRole("region", { name: "조립 매칭" });
    await within(card).findByRole("table", { name: "조립 매칭 표" });
    expect(calls[0]).toMatch(/\/studies\/s-cushion\/asm-matches\?source=train&latest=true&limit=1$/);
    expect(within(card).getByTestId("asm-state").textContent).toBe("검사 통과 — 저장 전");
    expect(within(card).getByTestId("asm-chips-CUSH_R").textContent).toContain("PART 3000003");
    expect((within(card).getByTestId("asm-advanced") as HTMLDetailsElement).open).toBe(false); // 복원해도 고급은 접힘
    expect(within(card).queryByTestId("asm-verdict-CUSH_L")).toBeNull();
    expect((within(card).getByLabelText("조립 폴더") as HTMLInputElement).value).toBe(ASSEM);
    expect(Object.keys(localStorage).filter((k) => k.startsWith("physicsai.asmMatch"))).toEqual([]);
  });

  it("목록 API의 최신 항목이 없으면(매칭 없음) 빈 카드", async () => {
    const ctx = await open();
    expect(within(ctx.card).queryByRole("table", { name: "조립 매칭 표" })).toBeNull();
    const res = await fetch("/physicsai/api/studies/s-cushion/asm-matches?source=path&latest=true&limit=1");
    expect(((await res.json()) as { items: unknown[] }).items).toEqual([]);
  });

  it("'매칭 안 함' 차단은 서버 use_bodies를 따른다(바디 이름 접두사 추측 없음)", async () => {
    const ctx = await open();
    const orig = ctx.server.handle.bind(ctx.server);
    ctx.server.handle = (m, p, q, b, h) => {
      const r = orig(m, p, q, b, h);
      if (m === "GET" && /\/asm-matches\/[^/]+$/.test(p) && r && r.status === 200) (r.body as AsmMatch).use_bodies = ["CUSH_R"]; // 서버가 CUSH_R만 막는다
      return r;
    };
    await scan(ctx);
    expect((within(ctx.card).getByLabelText("CUSH_R 매칭 안 함") as HTMLInputElement).disabled).toBe(true);
    expect((within(ctx.card).getByLabelText("CUSH_L 매칭 안 함") as HTMLInputElement).disabled).toBe(false);
    expect(within(ctx.card).getByTestId("asm-row-CUSH_R").textContent).toContain("선택한 파라미터가 있는 바디라 '매칭 안 함'으로 둘 수 없습니다");
    expect(excludeBlock("A", ["A"])).toContain("매칭 안 함");
    expect(excludeBlock("A_", [])).toBeNull();
  });

  it("422 ASM_ROW_INVALID problems[]를 행 옆 안내로: 코드별 한국어, 바디 없는 사유(ROWS_EMPTY)는 아래 줄", async () => {
    const ctx = await open();
    await scan(ctx);
    const orig = ctx.server.handle.bind(ctx.server);
    ctx.server.handle = (m, p, q, b, h) =>
      m === "PUT" && p.endsWith("/rows")
        ? err(422, "ASM_ROW_INVALID", "매칭 표가 올바르지 않습니다", { problems: [{ code: "USE_PARAM", body: "CUSH_L" }, { code: "PID_DUPLICATE", body: "CUSH_R", pid: 3000001 }, { code: "ROWS_EMPTY" }] })
        : orig(m, p, q, b, h);
    pick(ctx.card, "CUSH_R", 3000003);
    fireEvent.click(btn(ctx.card, "저장"));
    expect((await within(ctx.card).findByTestId("asm-note-CUSH_L")).textContent).toBe(ASM_PROBLEM_TEXT.USE_PARAM);
    expect(within(ctx.card).getByTestId("asm-note-CUSH_R").textContent).toBe("PART 3000001: 다른 행이 이미 쓰는 component입니다");
    expect(within(ctx.card).getByTestId("asm-notes-general").textContent).toBe(ASM_PROBLEM_TEXT.ROWS_EMPTY);
    expect(within(ctx.card).getByTestId("asm-error").textContent).toContain("매칭 표가 올바르지 않습니다");
    // 표를 고치면 안내가 사라진다
    fireEvent.click(within(ctx.card).getByLabelText("CUSH_R에서 PART 3000003 빼기"));
    expect(within(ctx.card).queryByTestId("asm-note-CUSH_L")).toBeNull();
  });

  it("check.current=false면 '검사가 최신이 아님' 경고(저장은 가능) + 고급을 펼치면 판정 '검사 필요'", async () => {
    const ctx = await open();
    await scan(ctx);
    pick(ctx.card, "CUSH_R", 3000003);
    await check(ctx);
    expect(within(ctx.card).queryByTestId("asm-check-warning")).toBeNull();
    const orig = ctx.server.handle.bind(ctx.server);
    ctx.server.handle = (m, p, q, b, h) => {
      const r = orig(m, p, q, b, h);
      if (m === "GET" && /\/asm-matches(\/[^/]+)?$/.test(p) && r && r.status === 200) {
        const items = "items" in (r.body as object) ? (r.body as { items: AsmMatch[] }).items : [r.body as AsmMatch];
        for (const mm of items) {
          mm.state = "DRAFT";
          mm.check!.current = false;
        }
      }
      return r;
    };
    ctx.unmount();
    render(<TestApp path={`${STUDY}/1`} />);
    const card = await screen.findByRole("region", { name: "조립 매칭" });
    const warn = await within(card).findByTestId("asm-check-warning");
    expect(warn.textContent).toBe("경계 검사가 최신이 아님 — 고급 영역에서 다시 검사할 수 있습니다");
    expect(warn.getAttribute("data-code")).toBe("ASM_CHECK_STALE_WARN");
    expect(within(card).getByTestId("asm-state").textContent).toBe("초안 — 저장 전");
    expect(btn(card, "저장").disabled).toBe(false);
    expect(btn(card, "검사").disabled).toBe(false);
    const adv = within(card).getByTestId("asm-advanced") as HTMLDetailsElement;
    expect(adv.open).toBe(false);
    adv.open = true;
    fireEvent(adv, new Event("toggle"));
    expect((await within(card).findByTestId("asm-verdict-CUSH_L")).textContent).toBe("검사 필요");
  });

  it("검사 PASS 뒤 행을 바꾼 상태(current=false)로 확정해도 200 + ASM_CHECK_STALE_WARN(서버가 허용)", async () => {
    const ctx = await open();
    await scan(ctx);
    pick(ctx.card, "CUSH_R", 3000003);
    await check(ctx);
    const id = [...ctx.server.jobs].reverse().find((j) => j.job_type === "ASM_MATCH")!.params.match_id as string;
    const put = await fetch(`/physicsai/api/asm-matches/${id}/rows`, { method: "PUT", headers: { "X-PhysicsAI-Request": "1", "Content-Type": "application/json" }, body: JSON.stringify({ rows: [{ body: "CUSH_L", pids: [3000001] }, { body: "CUSH_R", pids: [3000002] }], excluded_bodies: [] }) });
    const m = (await put.json()) as AsmMatch;
    expect(m.state).toBe("DRAFT");
    expect(m.check?.current).toBe(false);
    expect(m.rows_complete).toBe(true);
    const res = await fetch(`/physicsai/api/asm-matches/${id}/confirm`, { method: "POST", headers: { "X-PhysicsAI-Request": "1" } });
    expect(res.status).toBe(200);
    const c = (await res.json()) as AsmMatch;
    expect(c.state).toBe("CONFIRMED");
    expect(c.warnings.map((w) => w.code)).toEqual(["ASM_CHECK_STALE_WARN"]);
  });

  it("행이 완전하지 않으면 확정은 409 ASM_ROWS_INCOMPLETE(검사와 무관한 확정 조건)", async () => {
    const ctx = await open();
    await scan(ctx);
    const id = [...ctx.server.jobs].reverse().find((j) => j.job_type === "ASM_MATCH")!.params.match_id as string;
    const res = await fetch(`/physicsai/api/asm-matches/${id}/confirm`, { method: "POST", headers: { "X-PhysicsAI-Request": "1" } });
    expect(res.status).toBe(409);
    expect(((await res.json()) as { detail: { code: string } }).detail.code).toBe("ASM_ROWS_INCOMPLETE");
  });

  it("목록 읽기 실패는 last_job.failure_code를 한국어로", async () => {
    const ctx = await open("_nosolid");
    fireEvent.click(within(ctx.card).getByRole("button", { name: "목록 읽기" }));
    await waitFor(() => expect(ctx.server.jobs.some((j) => j.job_type === "ASM_MATCH")).toBe(true));
    act(() => ctx.server.finishAll());
    expect((await within(ctx.card).findByTestId("asm-failed")).textContent).toBe("조립에 TETRA4 PART가 없습니다");
    expect(within(ctx.card).getByTestId("asm-state").textContent).toBe("목록 읽기 실패");
  });
});

describe("조립 매칭 ④ 등록 연결", () => {
  const FOLDER = "E:/shared/AI_WORK/cushion/00_inbox/native_project";
  afterEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
  });

  async function openRegister() {
    const r = renderApp(`${STUDY}/4`, { user: "power" });
    const calls: { m: string; p: string; b: Record<string, unknown> | null }[] = [];
    const orig = r.server.handle.bind(r.server);
    r.server.handle = (m, p, q, b, h) => (m === "POST" && /\/(param-sets(\/discover)?|asm-matches)$/.test(p) && calls.push({ m, p, b: structuredClone(b) }), orig(m, p, q, b, h));
    fireEvent.click(await screen.findByRole("button", { name: "템플릿 관리" }));
    const card = await screen.findByRole("region", { name: "템플릿 관리" });
    fireEvent.click(within(card).getByRole("button", { name: "새로 등록" }));
    const form = within(card).getByTestId("ps-discover");
    fireEvent.click(within(form).getByRole("radio", { name: "Native" }));
    const find = async (path = FOLDER) => {
      fireEvent.change(within(form).getByLabelText("프로젝트 폴더 경로"), { target: { value: path } });
      fireEvent.click(within(form).getByRole("button", { name: "찾기" }));
      await within(form).findByText("01_CAD/cushion_base.step");
    };
    return { ...r, form, find, calls };
  }
  const reg = (form: HTMLElement) => within(form).getByRole("button", { name: "등록" }) as HTMLButtonElement;

  it("기본 = 조립 매칭 사용: discover 본문에 asm_match:true, 기준본·번호 표 문구는 숨김, 매칭 저장 전에는 등록 불가", async () => {
    const { form, find, calls } = await openRegister();
    expect((within(form).getByRole("checkbox", { name: "조립 매칭 사용" }) as HTMLInputElement).checked).toBe(true);
    expect(form.textContent).not.toMatch(/104_replace|기준 메시 104|renum|RENUM/);
    expect(form.textContent).toContain("기준 메시·번호 표 파일 불필요");
    await find(`${FOLDER}_noinc`); // 기준본 inc 없는 폴더도 문제 없이 후보가 뜬다(서버가 BASELINE_INC_MISSING 제외)
    expect(calls.find((c) => c.p.endsWith("/discover"))!.b).toMatchObject({ engine: "native", asm_match: true });
    expect(within(form).queryByText(/104_replace_node_elem\.inc가 없습니다/)).toBeNull();
    await within(form).findByTestId("asm-embedded");
    expect(reg(form).disabled).toBe(true);
  });

  it("매칭 사용을 끄면 기존 RENUM·기준본 방식 그대로(문구·discover에 asm_match 없음)", async () => {
    const { form, find, calls } = await openRegister();
    fireEvent.click(within(form).getByRole("checkbox", { name: "조립 매칭 사용" }));
    expect(form.textContent).toMatch(/104_replace_node_elem\.inc 필요/);
    await find(`${FOLDER}_noinc`);
    expect(calls.find((c) => c.p.endsWith("/discover"))!.b).not.toHaveProperty("asm_match");
    expect(within(form).getByText(/104_replace_node_elem\.inc가 없습니다/)).toBeTruthy();
    expect(within(form).queryByTestId("asm-embedded")).toBeNull();
    expect(reg(form).disabled).toBe(true);
  });

  it("매칭(목록 읽기·저장, 검사 없이) 후 등록 → POST /param-sets에 asm_match_id(source=path 확정본), STEP·조립 경로는 이 폴더 기준", async () => {
    const { server, form, find, calls } = await openRegister();
    await find();
    const emb = await within(form).findByTestId("asm-embedded");
    fireEvent.click(within(emb).getByRole("button", { name: "목록 읽기" }));
    await waitFor(() => expect(server.jobs.some((j) => j.job_type === "ASM_MATCH")).toBe(true));
    act(() => server.finishAll());
    await within(emb).findByRole("table", { name: "조립 매칭 표" });
    const create = calls.find((c) => c.p.endsWith("/asm-matches"))!.b as { radioss_assem_path: string; cad: { kind: string; path: string } };
    expect(create.radioss_assem_path).toBe(`${FOLDER}/RADIOSS_ASSEM`);
    expect(create.cad).toEqual({ kind: "path", path: `${FOLDER}/01_CAD/cushion_base.step` });
    pick(emb, "CUSH_R", 3000003);
    await waitFor(() => expect(btn(emb, "저장").disabled).toBe(false)); // 검사 없이 저장(AM-C3)
    expect(reg(form).disabled).toBe(true); // 확정 전
    fireEvent.click(btn(emb, "저장"));
    expect((await within(emb).findByTestId("asm-confirmed")).textContent).toContain("템플릿 등록이 이 매칭을 씁니다");
    await waitFor(() => expect(reg(form).disabled).toBe(false));
    const matchId = ((await (await fetch(`/physicsai/api/studies/s-cushion/asm-matches?source=path&latest=true`)).json()) as { items: AsmMatch[] }).items[0].match_id;
    fireEvent.click(reg(form));
    await waitFor(() => expect(calls.filter((c) => c.p.endsWith("/param-sets")).length).toBe(1));
    const body = calls.find((c) => c.p.endsWith("/param-sets"))!.b!;
    expect(body).toMatchObject({ engine: "native", mode: "discover", asm_match_id: matchId, choice: { cad: "01_CAD/cushion_base.step", radioss_assem: "RADIOSS_ASSEM" } });
    expect(server.jobs.find((j) => j.job_type === "PARAM_SET_NATIVE")!.params).toMatchObject({ asm_match_id: matchId });
  });

  it("같은 STEP·조립 폴더로 다시 열면 서버 목록에서 저장된 매칭을 이어 쓴다(다시 매칭 불필요)", async () => {
    const { server, form, find } = await openRegister();
    await find();
    let emb = await within(form).findByTestId("asm-embedded");
    fireEvent.click(within(emb).getByRole("button", { name: "목록 읽기" }));
    await waitFor(() => expect(server.jobs.some((j) => j.job_type === "ASM_MATCH")).toBe(true));
    act(() => server.finishAll());
    await within(emb).findByRole("table", { name: "조립 매칭 표" });
    pick(emb, "CUSH_R", 3000003);
    await waitFor(() => expect(btn(emb, "저장").disabled).toBe(false)); // 검사 없이 저장(AM-C3)
    fireEvent.click(btn(emb, "저장"));
    await within(emb).findByTestId("asm-confirmed");
    // 매칭 사용을 껐다 켜고 다시 찾기 → 카드가 새로 만들어져도 저장된 매칭을 되찾는다
    fireEvent.click(within(form).getByRole("checkbox", { name: "조립 매칭 사용" }));
    fireEvent.click(within(form).getByRole("checkbox", { name: "조립 매칭 사용" }));
    await find();
    emb = await within(form).findByTestId("asm-embedded");
    await within(emb).findByTestId("asm-confirmed");
    await waitFor(() => expect(reg(form).disabled).toBe(false));
  });

  it("STEP 폴더(parts)를 고르면 조립 매칭 불가 안내 + 등록 불가", async () => {
    const { form, find } = await openRegister();
    await find(`${FOLDER}_multi`);
    fireEvent.change(within(form).getByLabelText("CAD 선택"), { target: { value: "01_CAD/parts" } });
    expect((await within(form).findByTestId("asm-unsupported")).textContent).toContain("STEP 폴더(parts)는 조립 매칭을 지원하지 않습니다");
    expect(within(form).queryByTestId("asm-embedded")).toBeNull();
    expect(reg(form).disabled).toBe(true);
  });

  it("서버 게이트: 확정본 없이 등록하면 409 PREREQUISITE_MISSING → '조립 매칭을 먼저 하세요'", async () => {
    const { server } = await openRegister();
    const res = await fetch(`/physicsai/api/studies/s-cushion/param-sets`, {
      method: "POST", headers: { "X-PhysicsAI-Request": "1", "Content-Type": "application/json" },
      body: JSON.stringify({ path: FOLDER, engine: "native", mode: "discover", choice: { cad: "01_CAD/cushion_base.step", radioss_assem: "RADIOSS_ASSEM" }, asm_match_id: "am-none" }),
    });
    expect(res.status).toBe(409);
    const detail = ((await res.json()) as { detail: { code: string; message: string; missing: string[] } }).detail;
    expect(detail.missing).toEqual(["ASM_MATCH"]);
    expect(isAsmMissing(detail)).toBe(true);
    expect(errorMessage(new ApiError(409, detail))).toBe("조립 매칭을 먼저 하세요");
    expect(server.jobs.some((j) => j.job_type === "PARAM_SET_NATIVE")).toBe(false);
  });
});

describe("조립 매칭 ①-3 DOE 파라미터", () => {
  afterEach(() => localStorage.clear());
  it("TD_DOE_GEN은 source=train 확정본 asm_match_id를 보내고, 세트 기준 DOE는 보내지 않는다(서버 422)", async () => {
    const { buildNativeParams, buildReuseParams, initialNative } = await import("../stages/stage1/doeGenParams");
    const nat = initialNative();
    const base = { multi: 1, maxRuns: 5000, assemPath: ASSEM };
    expect(buildNativeParams(nat, { ...base, paramSetId: null, asmMatchId: "am-1" })).toMatchObject({ generator: "platform", radioss_assem_path: ASSEM, asm_match_id: "am-1" });
    expect(buildNativeParams(nat, { ...base, paramSetId: null })).not.toHaveProperty("asm_match_id");
    expect(buildNativeParams(nat, { ...base, paramSetId: "ps-1", asmMatchId: "am-1" })).not.toHaveProperty("asm_match_id");
    expect(buildNativeParams(nat, { ...base, paramSetId: "ps-1", asmMatchId: "am-1" })).toMatchObject({ param_set_id: "ps-1" });
    expect(buildReuseParams({ doeId: "d1", multi: 1, assemPath: ASSEM, paramSetId: null, asmMatchId: "am-1", continueOnFailure: true })).toMatchObject({ asm_match_id: "am-1" });
    const res = await (async () => {
      const r = renderApp(`${STUDY}/1`, { user: "power" }, nativeSetup);
      await screen.findByRole("region", { name: "조립 매칭" });
      return fetch("/physicsai/api/studies/s-cushion/jobs", { method: "POST", headers: { "X-PhysicsAI-Request": "1", "Content-Type": "application/json" }, body: JSON.stringify({ job_type: "TD_DOE_GEN", params: { ...buildNativeParams(nat, { ...base, paramSetId: "ps-1", asmMatchId: "am-1" }), asm_match_id: "am-1" } }) }).finally(() => r.unmount());
    })();
    expect(res.status).toBe(422);
  });
});

describe("조립 매칭 순수 로직", () => {
  const parts: AsmPart[] = [
    { pid: 1, title: "P1", elems: { TETRA4: 10 }, nodes: 5, volume: 1, solid_ok: true },
    { pid: 2, title: "P2", elems: { TETRA4: 10 }, nodes: 5, volume: 1, solid_ok: true },
    { pid: 3, title: "S", elems: { SHELL: 4 }, nodes: 5, volume: null, solid_ok: false },
  ];
  const m = {
    bodies: [{ body: "A", volume: 1000, bbox: [0, 0, 0, 1, 2, 3] }, { body: "B", volume: 2000, bbox: [0, 0, 0, 1, 1, 1] }],
    parts,
    recommend: [{ body: "A", pids: [1], score: 0.9 }, { body: "B", pids: [1, 2], score: 0.7 }],
  };

  it("추천은 TETRA4만·이미 쓴 PART 제외(N:1 금지), 편집·N:1 검증·PUT 모양", () => {
    let d = recommendDraft(m);
    expect(d.pids).toEqual({ A: [1], B: [2] });
    expect(addPart(d, "B", 1)).toBe(d); // N:1 → 그대로
    expect(usedBy(d, 1)).toBe("A");
    expect(partChoice(parts[0], "B", d)).toEqual({ disabled: true, reason: "A 행에서 사용" });
    expect(partChoice(parts[2], "B", d).reason).toBe("TETRA4가 아님: /SHELL 4개");
    d = removePart(d, "B", 2);
    expect(d.pids.B).toBeUndefined();
    d = setExcluded(d, "B", true);
    expect(toPut(m, d)).toEqual({ rows: [{ body: "A", pids: [1] }], excluded_bodies: ["B"] });
    expect(draftProblems(m, { pids: { A: [1], B: [1] }, excluded: [] }).map((p) => p.message)).toEqual(["PART 1이(가) A·B 두 행에 있습니다 — component는 한 행에만 쓸 수 있습니다"]);
    expect(draftProblems(m, { pids: { A: [3] }, excluded: [] })[0].message).toContain("TETRA4가 아닙니다");
  });

  it("오류 코드 한국어(계약 코드표): 서버 문구가 한국어면 그것 우선, 아니면 표", () => {
    for (const c of ["ASM_BOUNDARY_MISMATCH", "ASM_SHARED_NODES", "ASM_OFFSET_SUSPECT", "ASM_UNIT_SUSPECT", "ASM_INCLUDE_OUTSIDE", "ASM_INCLUDE_MISSING", "ASM_NO_SOLID_PART", "ASM_TOO_MANY_PARTS", "ASM_MATCH_INVALID", "ASM_ROW_INVALID", "ASM_ROWS_INCOMPLETE", "ASM_CHECK_FAILED_WARN", "ASM_CHECK_STALE_WARN", "ASM_MATCH_CONFIRMED", "ASM_MATCH_STALE", "ASM_MATCH_UNSUPPORTED"])
      expect(ASM_ERROR_TEXT[c], c).toMatch(/[가-힣]/);
    expect(asmCodeText("ASM_MATCH_STALE", "stale")).toContain("조립 폴더 또는 STEP이 바뀌었습니다");
    expect(asmCodeText("ASM_MATCH_STALE", "서버가 준 한국어 문구")).toBe("서버가 준 한국어 문구");
  });

  it("원점·단위 진단 문구, 저장 조건(검사 불필요 — 행이 완전하면 저장 가능, AM-C3), 검사 경고", () => {
    expect(suggestText({ code: "ASM_OFFSET_SUSPECT", translate_mm: [10, -2.5, 0] })).toContain("X 10.0 · Y -2.5 mm 어긋나 있습니다");
    expect(suggestText({ code: "ASM_UNIT_SUSPECT", factor: 0.001 })).toContain("×0.001 배 차이");
    const row: AsmCheckRow = { body: "A", pids: [1], status: "FAIL", code: "ASM_BOUNDARY_MISMATCH", match_ratio: 0.5, tol_mm: 0.05, dist_mm: { mean: 1, p95: 2, p99: 3, max: 4 }, shared: { nodes: 0, parts: [] }, suggest: { code: "ASM_UNIT_SUSPECT", factor: 1000 } };
    expect(failLines(row)).toHaveLength(2);
    const base = { ...m, state: "DRAFT", rows: [], excluded_bodies: [], check: null } as unknown as AsmMatch;
    expect(saveBlock(base, { pids: { A: [1], B: [2] }, excluded: [] })).toBeNull(); // 검사 없이 저장 가능
    expect(saveBlock(base, { pids: { A: [1] }, excluded: [] })).toContain("component를 고르지 않은 바디: B");
    expect(saveBlock(base, { pids: {}, excluded: ["A", "B"] })).toContain("1개 이상");
    expect(saveBlock({ ...base, state: "CONFIRMED" } as AsmMatch, { pids: { A: [1], B: [2] }, excluded: [] })).toBe("이미 저장되었습니다");
    expect(saveBlock({ ...base, state: "CHECKING" } as AsmMatch, { pids: { A: [1], B: [2] }, excluded: [] })).toContain("진행 중");
    // 검사 경고: 불합격·낡음 모두 경고일 뿐 저장은 막지 않는다
    const withCheck = (status: "PASS" | "FAIL", current: boolean, rows = [{ body: "A", pids: [1] }, { body: "B", pids: [2] }]) =>
      ({ ...base, state: "DRAFT", rows, check: { seq: 1, status, rows_sha256: "x", current, rows: [], glb_url: null, glb_artifact_id: null } }) as unknown as AsmMatch;
    const d = { pids: { A: [1], B: [2] }, excluded: [] };
    expect(checkNotice(base, d)).toBeNull();
    expect(checkNotice(withCheck("PASS", true), d)).toBeNull();
    expect(checkNotice(withCheck("FAIL", true), d)?.code).toBe("ASM_CHECK_FAILED_WARN");
    expect(checkNotice(withCheck("PASS", false), d)?.code).toBe("ASM_CHECK_STALE_WARN");
    expect(checkNotice(withCheck("FAIL", true), { pids: { A: [1, 2] }, excluded: [] })?.code).toBe("ASM_CHECK_STALE_WARN"); // 표를 바꿈 = 낡음
    expect(checkNotice({ ...withCheck("FAIL", true), state: "CONFIRMED" } as AsmMatch, d)).toBeNull(); // 확정 뒤는 서버 warnings
    expect(saveBlock(withCheck("FAIL", true), d)).toBeNull();
  });

  it("problems[].code 8종 → 행별 한국어 안내(알 수 없는 코드는 서버 문구)", () => {
    const codes = ["USE_PARAM", "UNKNOWN_BODY", "BODY_DUPLICATE", "UNKNOWN_PID", "PID_DUPLICATE", "NOT_SOLID", "BODY_MISSING", "ROWS_EMPTY"];
    for (const c of codes) expect(ASM_PROBLEM_TEXT[c], c).toMatch(/[가-힣]/);
    const n = rowNotes([
      { code: "UNKNOWN_PID", body: "A", pid: 7 },
      { code: "NOT_SOLID", body: "A", pid: 8 },
      { code: "BODY_MISSING", body: "B" },
      { code: "ROWS_EMPTY" },
      { code: "NEW_CODE", body: "B", message: "서버 문구" },
    ]);
    expect(n.byBody.A).toEqual(["PART 7: 조립에 없는 PART입니다", "PART 8: TETRA4만 가진 component가 아닙니다"]);
    expect(n.byBody.B).toEqual([ASM_PROBLEM_TEXT.BODY_MISSING, "서버 문구"]);
    expect(n.general).toEqual([ASM_PROBLEM_TEXT.ROWS_EMPTY]);
    expect(rowNotes(null)).toEqual({ byBody: {}, general: [] });
  });

  it("추가 오류 코드 한국어(BUSY·INCOMPLETE·STALE·UNSUPPORTED)·PREREQUISITE_MISSING 문구, 폐지된 ASM_CHECK_REQUIRED는 표에 없다", () => {
    expect(ASM_ERROR_TEXT.ASM_CHECK_REQUIRED).toBeUndefined();
    for (const c of ["ASM_MATCH_BUSY", "ASM_ROWS_INCOMPLETE", "ASM_MATCH_STALE", "ASM_MATCH_UNSUPPORTED"]) expect(asmCodeText(c, "english"), c).toMatch(/[가-힣]/);
    expect(ASM_FIRST_TEXT).toBe("조립 매칭을 먼저 하세요");
    expect(isAsmMissing({ code: "PREREQUISITE_MISSING", missing: ["PARAM_SET"] })).toBe(false);
    expect(isAsmMissing({ code: "PREREQUISITE_MISSING", missing: ["ASM_MATCH"] })).toBe(true);
  });

  it("worst 점: 거리 내림차순 그대로, 툴팁에 node_id, 첫 점만 글자 · 화면 가장 가까운 점 고르기", () => {
    const row = { body: "CUSH_L", worst: { count: 2, points: [{ node_id: 710001, xyz: [1, 2, 3] as [number, number, number], dist_mm: 0.0413 }, { node_id: 710038, xyz: [4, 5, 6] as [number, number, number], dist_mm: 0.02 }] } };
    const pts = worstPoints(row);
    expect(pts.map((p) => p.xyz)).toEqual([[1, 2, 3], [4, 5, 6]]);
    expect(pts[0].label).toBe("CUSH_L 최대 0.04 mm");
    expect(pts[1].label).toBe("");
    expect(pts.map((p) => p.title)).toEqual(["node 710001 · 0.041 mm", "node 710038 · 0.020 mm"]);
    expect(worstPoints(null)).toEqual([]);
    const screen2 = [{ x: 10, y: 10, ok: true }, { x: 100, y: 100, ok: true }, { x: 102, y: 101, ok: false }];
    expect(nearestScreenPoint(screen2, 101, 100, 8)).toBe(1); // 보이지 않는 점(ok=false)은 제외
    expect(nearestScreenPoint(screen2, 50, 50, 8)).toBe(-1);
  });

  it("상태 알약: DRAFT는 최신 검사가 불합격일 때만 구분(저장은 막지 않는다)", () => {
    const ck = (current: boolean, status = "FAIL") => ({ state: "DRAFT", check: { current, status } }) as unknown as AsmMatch;
    expect(stateLabel({ state: "DRAFT", check: null } as unknown as AsmMatch)).toBe("초안 — 저장 전");
    expect(stateLabel(ck(true))).toContain("불합격(저장은 가능)");
    expect(stateLabel(ck(false))).toBe("초안 — 저장 전");
    expect(stateLabel({ state: "CONFIRMED", check: null } as unknown as AsmMatch)).toBe("저장됨");
  });
});
