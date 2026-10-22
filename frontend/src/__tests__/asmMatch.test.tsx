// v0.2.9 조립 매칭 화면(asm-match.md §3.2·§6.5): 표 편집(1:N)·N:1 차단·추천 채움·검사 결과(일치율·거리·공유 노드)·원점 차이 차단·저장 → ①-3 Native DOE 문구 전환.
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { renderApp, STUDY } from "../test/render";
import type { MockServer } from "../mock/server";
import { nativeTrainParams } from "../mock/geometry";
import { ASM_ERROR_TEXT, addPart, asmCodeText, draftProblems, failLines, glbArtifactId, partChoice, recommendDraft, removePart, saveBlock, setExcluded, suggestText, toPut, usedBy } from "../lib/asmMatch";
import type { AsmCheckRow, AsmMatch, AsmPart } from "../api";

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
  await waitFor(() => expect(within(ctx.card).getByTestId("asm-state").textContent).toBe("검사 완료"));
}

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
    // 저장 전에는 검사 필요 안내만 — 저장은 막혀 있다
    expect(btn(ctx.card, "저장").disabled).toBe(true);
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
    expect(within(ctx.card).getByTestId("asm-row-CUSH_L").textContent).toContain("선택한 파라미터 3개가 이 바디에 있습니다");
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

  it("추천 채움: 모두 비워도 [추천 적용]이 추천(1:1 초안)을 다시 채운다 · 미결정 바디가 있으면 검사 불가+사유", async () => {
    const ctx = await open();
    await scan(ctx);
    fireEvent.click(within(ctx.card).getByLabelText("CUSH_L에서 PART 3000001 빼기"));
    expect(btn(ctx.card, "검사").disabled).toBe(true);
    expect(within(ctx.card).getByTestId("asm-block").textContent).toContain("component를 고르지 않은 바디: CUSH_L");
    fireEvent.click(btn(ctx.card, "추천 적용"));
    expect(within(ctx.card).getByTestId("asm-chips-CUSH_L").textContent).toContain("PART 3000001");
    expect(btn(ctx.card, "검사").disabled).toBe(false);
  });

  it("검사 PASS: 판정·일치율·최대/p95 거리·허용오차, 3D 범례 없이도 표시, 저장 → 저장됨", async () => {
    const ctx = await open();
    await scan(ctx);
    pick(ctx.card, "CUSH_R", 3000003);
    await check(ctx);
    for (const b of ["CUSH_L", "CUSH_R"]) {
      expect(within(ctx.card).getByTestId(`asm-verdict-${b}`).textContent).toBe("일치");
      expect(within(ctx.card).getByTestId(`asm-dist-${b}`).textContent).toContain("최대 0.041 · p95 0.011 mm · 일치율 99.9%");
    }
    expect(within(ctx.card).getByTestId("asm-dist-CUSH_L").textContent).toContain("허용 0.05 mm");
    // 표를 바꾸면 검사 필요 + 저장 불가
    fireEvent.click(within(ctx.card).getByLabelText("CUSH_R에서 PART 3000003 빼기"));
    expect(within(ctx.card).getByTestId("asm-verdict-CUSH_R").textContent).toBe("검사 필요");
    expect(btn(ctx.card, "저장").disabled).toBe(true);
    pick(ctx.card, "CUSH_R", 3000003);
    await waitFor(() => expect(btn(ctx.card, "저장").disabled).toBe(false));
    fireEvent.click(btn(ctx.card, "저장"));
    await within(ctx.card).findByTestId("asm-confirmed");
    expect(within(ctx.card).getByTestId("asm-state").textContent).toBe("저장됨");
    expect(btn(ctx.card, "목록 읽기").disabled).toBe(false);
  });

  it("검사 FAIL(바디 바꿔 매칭): 불일치·일치율·최대 거리 문구, 저장 불가", async () => {
    const ctx = await open();
    await scan(ctx);
    fireEvent.click(within(ctx.card).getByLabelText("CUSH_L에서 PART 3000001 빼기"));
    fireEvent.click(within(ctx.card).getByLabelText("CUSH_R에서 PART 3000002 빼기"));
    pick(ctx.card, "CUSH_L", 3000002);
    pick(ctx.card, "CUSH_R", 3000001);
    await check(ctx);
    expect(within(ctx.card).getByTestId("asm-verdict-CUSH_L").textContent).toBe("불일치");
    expect(within(ctx.card).getByTestId("asm-fail-lines").textContent).toContain("외곽 노드가 CAD 경계면과 맞지 않습니다 — 일치율 31.2%, 최대 41.20 mm");
    expect(btn(ctx.card, "저장").disabled).toBe(true);
  });

  it("원점 차이: CUSH_L 불일치 + 'X 10.0 mm 어긋남' 안내, 저장 불가(서버도 409 ASM_CHECK_REQUIRED)", async () => {
    const ctx = await open("_offset");
    await scan(ctx);
    pick(ctx.card, "CUSH_R", 3000003);
    await check(ctx);
    expect(within(ctx.card).getByTestId("asm-verdict-CUSH_L").textContent).toBe("불일치");
    expect(within(ctx.card).getByTestId("asm-verdict-CUSH_R").textContent).toBe("일치");
    expect(within(ctx.card).getByTestId("asm-fail-lines").textContent).toContain("CAD가 조립보다 X 10.0 mm 어긋나 있습니다 — CAD를 조립과 같은 원점·mm로 다시 내보내세요(저장 불가)");
    expect(btn(ctx.card, "저장").disabled).toBe(true);
    const id = [...ctx.server.jobs].reverse().find((j) => j.job_type === "ASM_MATCH")!.params.match_id as string;
    const res = await fetch(`/physicsai/api/asm-matches/${id}/confirm`, { method: "POST", headers: { "X-PhysicsAI-Request": "1" } });
    expect(res.status).toBe(409);
    expect(((await res.json()) as { detail: { code: string } }).detail.code).toBe("ASM_CHECK_REQUIRED");
  });

  it("노드 공유: 상대 PART(id·제목)와 노드 수 안내, 저장 불가", async () => {
    const ctx = await open("_shared");
    await scan(ctx);
    pick(ctx.card, "CUSH_R", 3000003);
    await check(ctx);
    expect(within(ctx.card).getByTestId("asm-verdict-CUSH_R").textContent).toBe("불일치");
    expect(within(ctx.card).getByTestId("asm-fail-lines").textContent).toContain("PART 2001(PRODUCT_TIE)과 노드 37개 공유");
    expect(btn(ctx.card, "저장").disabled).toBe(true);
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
    await check(ctx);
    await waitFor(() => expect(btn(ctx.card, "저장").disabled).toBe(false));
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
    for (const c of ["ASM_BOUNDARY_MISMATCH", "ASM_SHARED_NODES", "ASM_OFFSET_SUSPECT", "ASM_UNIT_SUSPECT", "ASM_INCLUDE_OUTSIDE", "ASM_INCLUDE_MISSING", "ASM_NO_SOLID_PART", "ASM_TOO_MANY_PARTS", "ASM_MATCH_INVALID", "ASM_ROW_INVALID", "ASM_ROWS_INCOMPLETE", "ASM_CHECK_REQUIRED", "ASM_MATCH_CONFIRMED", "ASM_MATCH_STALE", "ASM_MATCH_UNSUPPORTED"])
      expect(ASM_ERROR_TEXT[c], c).toMatch(/[가-힣]/);
    expect(asmCodeText("ASM_MATCH_STALE", "stale")).toContain("조립 폴더 또는 STEP이 바뀌었습니다");
    expect(asmCodeText("ASM_MATCH_STALE", "서버가 준 한국어 문구")).toBe("서버가 준 한국어 문구");
  });

  it("원점·단위 진단 문구, 저장 조건(검사 PASS + 표 불변), GLB 산출물 id", () => {
    expect(suggestText({ code: "ASM_OFFSET_SUSPECT", translate_mm: [10, -2.5, 0] })).toContain("X 10.0 · Y -2.5 mm 어긋나 있습니다");
    expect(suggestText({ code: "ASM_UNIT_SUSPECT", factor: 0.001 })).toContain("×0.001 배 차이");
    const row: AsmCheckRow = { body: "A", pids: [1], status: "FAIL", code: "ASM_BOUNDARY_MISMATCH", match_ratio: 0.5, tol_mm: 0.05, dist_mm: { mean: 1, p95: 2, p99: 3, max: 4 }, shared: { nodes: 0, parts: [] }, suggest: { code: "ASM_UNIT_SUSPECT", factor: 1000 } };
    expect(failLines(row)).toHaveLength(2);
    const base = { ...m, state: "CHECKED", rows: [{ body: "A", pids: [1] }], excluded_bodies: ["B"], check: { seq: 1, status: "PASS", rows_sha256: "x", rows: [], glb_url: null } } as unknown as AsmMatch;
    expect(saveBlock(base, { pids: { A: [1] }, excluded: ["B"] })).toBeNull();
    expect(saveBlock(base, { pids: { A: [1, 2] }, excluded: ["B"] })).toContain("검사를 다시 하세요");
    expect(saveBlock({ ...base, check: { ...base.check!, status: "FAIL" } }, { pids: { A: [1] }, excluded: ["B"] })).toContain("통과");
    expect(glbArtifactId("/physicsai/api/artifacts/a-12/media")).toBe("a-12");
    expect(glbArtifactId("a-12")).toBe("a-12");
    expect(glbArtifactId(null)).toBeNull();
  });
});
