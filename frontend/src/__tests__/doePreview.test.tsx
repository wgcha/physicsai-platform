// doe-preview.md §7·§8 DOE 형상 그리드 미리보기(V-DP-10·12): 버튼 활성 조건 = 실행 검증, 정렬 3종·실패만(렌더된 셀만)·다음 24개 offset,
// 셀 캡션 top_changes·실패 테두리·잘림·범례·낡음·취소, 클릭 → 3D 뷰어 1개(동시 WebGL 컨텍스트 ≤ 1)·WebGL 불가 → 확대 PNG, 생성 후 갤러리(스킵 배지), 외부 URL 0건.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { renderApp, STUDY } from "../test/render";
import type { MockServer } from "../mock/server";
import type { MockOptions } from "../mock/server";
import { nativeTrainParams } from "../mock/geometry";
import { dpRecords, setDpMode, type DpMode } from "../mock/doePreview";
import { POLL } from "../lib/poll";
import { resetWebGLCache } from "../stages/stage4/geomview/webgl";
import type { DoePreviewCell } from "../api/types";
import {
  PAGE_SIZE, TURBO16, turbo16Gradient, buildReq, cellLabel, cellTone, changeText, failInfo, filterFailed, genBadge, hasMore, inputKey, mergeCells, overRange, progressOf, progressText, relPct, shortVarName, valuesTip,
} from "../stages/stage1/doepreview/gridModel";

type Fn = ReturnType<typeof vi.fn>;
const fake = vi.hoisted(() => ({ scenes: [] as { setNominal: Fn; setOverlay: Fn; setHighlight: Fn; setBodyVisible: Fn; setFixed: Fn; setPoints: Fn; fit: Fn; dispose: Fn }[] }));
vi.mock("../stages/stage4/geomview/threeScene", () => ({
  createGeomScene: () => {
    const g = { setNominal: vi.fn(async () => undefined), setOverlay: vi.fn(async () => undefined), setHighlight: vi.fn(), setBodyVisible: vi.fn(), setFixed: vi.fn(), setPoints: vi.fn(), fit: vi.fn(), dispose: vi.fn() };
    fake.scenes.push(g);
    return g;
  },
  createContourScene: vi.fn(),
}));

const last = (f: Fn) => f.mock.calls[f.mock.calls.length - 1];
const cell = (o: Partial<DoePreviewCell> = {}): DoePreviewCell => ({ doe_no: 3, status: "OK", values: {}, ...o });

describe("lib gridModel — 순수 함수", () => {
  it("요청 본문: 첫 페이지 offset 0·limit 24, var 정렬만 var·desc, train_doe는 sampling 생략", () => {
    const samp = { kind: "lhs", count: 40, seed: 1 };
    expect(buildReq({ kind: "train" }, samp, { order: "change" })).toEqual({ source: { kind: "train" }, sampling: samp, select: { order: "change", offset: 0, limit: PAGE_SIZE } });
    expect(buildReq({ kind: "param_set", param_set_id: "ps-n1" }, samp, { order: "var", var: "THK", desc: true, offset: 24 }).select).toEqual({ order: "var", var: "THK", desc: true, offset: 24, limit: 24 });
    expect(buildReq({ kind: "param_set", param_set_id: "ps-n1" }, samp, { order: "var", var: "THK", desc: false }).select).toEqual({ order: "var", var: "THK", offset: 0, limit: 24 });
    const g = buildReq({ kind: "train_doe", doe_id: "doe-1" }, samp, { order: "doe" });
    expect(g).toEqual({ source: { kind: "train_doe", doe_id: "doe-1" }, select: { order: "doe", offset: 0, limit: 24 } });
    expect("sampling" in g).toBe(false);
  });
  it("낡음 키: 출처·표본만(정렬·페이지는 같은 키)", () => {
    const a = inputKey({ kind: "train" }, { kind: "lhs", count: 40, seed: 1 });
    expect(a).toBe(inputKey({ kind: "train" }, { kind: "lhs", count: 40, seed: 1 }));
    expect(a).not.toBe(inputKey({ kind: "train" }, { kind: "lhs", count: 41, seed: 1 }));
    expect(a).not.toBe(inputKey({ kind: "param_set", param_set_id: "p" }, { kind: "lhs", count: 40, seed: 1 }));
    expect(inputKey({ kind: "train_doe", doe_id: "d" }, { x: 1 })).toBe(inputKey({ kind: "train_doe", doe_id: "d" }, null));
  });
  it("캡션: 변경 상위 3 + 외 N, 부호 U+2212, 공칭은 빈 줄, 값 표 툴팁", () => {
    expect(relPct(0.05)).toBe("+5%");
    expect(relPct(-0.08)).toBe("−8%");
    expect(shortVarName("CUSH_L_THK_1")).toBe("THK_1");
    expect(shortVarName("HOLE_R_1")).toBe("HOLE_R_1");
    const c = cell({ values: { CUSH_L_THK_1: 13.1, CUSH_L_HOLE_U_1: 27.6, A_B_C: 1, D: 2, E: 3 }, top_changes: [{ name: "CUSH_L_THK_1", value: 13.1, rel: 0.05 }, { name: "CUSH_L_HOLE_U_1", value: 27.6, rel: -0.08 }] });
    expect(changeText(c)).toBe("THK_1 13.1(+5%) · HOLE_U_1 27.6(−8%) · 외 3");
    expect(changeText(cell({ nominal: true, doe_no: null }))).toBe("");
    expect(valuesTip(c)).toBe("CUSH_L_THK_1 = 13.1\nCUSH_L_HOLE_U_1 = 27.6\nA_B_C = 1\nD = 2\nE = 3");
    expect(valuesTip(cell())).toBe("공칭(변경 없음)");
  });
  it("셀 이름·상태·실패·범위 초과·생성 후 배지", () => {
    expect(cellLabel(cell({ doe_no: 17 }), false)).toBe("#17");
    expect(cellLabel(cell({ doe_no: 17 }), true)).toBe("run 17");
    expect(cellLabel(cell({ nominal: true, doe_no: null }), true)).toBe("공칭");
    expect(cellTone(cell({ nominal: true, doe_no: null }))).toBe("nominal");
    expect(["ok", "fail", "error", "pending"]).toEqual((["OK", "FAIL", "ERROR", "PENDING"] as const).map((s) => cellTone(cell({ status: s }))));
    expect(failInfo(cell())).toBeNull();
    expect(failInfo(cell({ status: "FAIL", code: "GEOM_FEATURE_COLLISION", category: "CAD_FAILED", message_ko: "피처 충돌" }))).toEqual({ badge: "CAD 생성 불가", text: "피처 충돌" });
    expect(overRange(cell({ max_disp_mm: 3 }), [0, 2.5])).toBe(true);
    expect(overRange(cell({ max_disp_mm: 2.5 }), [0, 2.5])).toBe(false);
    expect(overRange(cell({ max_disp_mm: 3 }), undefined)).toBe(false);
    expect(genBadge({ status: "OK" })).toBeNull();
    expect(genBadge({ status: "PENDING" })).toEqual({ tone: "muted", text: "대기" });
    expect(genBadge({ status: "SKIPPED", code: "GEOM_QUALITY", step: "CHECK" })).toEqual({ tone: "bad", text: "스킵 GEOM_QUALITY · 검사" });
  });
  it("범례 팔레트 = paicad TURBO16(16색 이산)", () => {
    expect(TURBO16).toHaveLength(16);
    expect(TURBO16[0]).toEqual([62, 42, 114]);
    expect(TURBO16[15]).toEqual([148, 12, 0]);
    const g = turbo16Gradient();
    expect(g).toContain("rgb(62 42 114) 0% 6.25%");
    expect(g.match(/rgb\(/g)).toHaveLength(16);
  });
  it("진행 문구·실패만(렌더된 셀)·다음 페이지 유무", () => {
    const cs = [cell({ doe_no: 1 }), cell({ doe_no: 2, status: "FAIL" }), cell({ doe_no: 3, status: "ERROR" }), cell({ doe_no: 4, status: "PENDING" })];
    expect(progressText(progressOf(cs))).toBe("3/4 완료 · 실패 1 · 오류 1");
    expect(filterFailed(cs, true).map((c) => c.doe_no)).toEqual([2, 3]);
    expect(filterFailed(cs, false)).toHaveLength(4);
    const p0 = { n_total: 40, cells: [cell({ nominal: true, doe_no: null }), ...Array.from({ length: 23 }, (_, i) => cell({ doe_no: i + 1 }))] };
    expect(hasMore([p0])).toBe(true);
    expect(hasMore([p0, { n_total: 40, cells: Array.from({ length: 17 }, (_, i) => cell({ doe_no: i + 24 })) }])).toBe(false);
    expect(mergeCells([p0, p0])).toHaveLength(48);
    expect(hasMore([])).toBe(false);
  });
});

const nativeSetup = (s: MockServer) => Object.assign(s.p2.setups["s-cushion"], { engine: "native", parameters: nativeTrainParams(), tpl: null });

function record(server: MockServer, re: RegExp) {
  const out: { path: string; body: Record<string, unknown> }[] = [];
  const orig = server.handle.bind(server);
  server.handle = (m, p, q, b, h) => {
    if (re.test(`${m} ${p}`)) out.push({ path: p, body: structuredClone(b ?? {}) as Record<string, unknown> });
    return orig(m, p, q, b, h);
  };
  return out;
}

async function openCard(opts: MockOptions = {}, setup: (s: MockServer) => void = nativeSetup, mode: DpMode = {}, waitNative = true) {
  const r = renderApp(`${STUDY}/1`, { user: "power", ...opts }, (s) => {
    setup(s);
    setDpMode(s, mode);
  });
  const card = await screen.findByRole("region", { name: "DOE · Radioss 입력" });
  if (waitNative) await within(card).findByTestId("doe-native");
  const setRuns = (n: string) => fireEvent.change(within(card).getByLabelText("run 수"), { target: { value: n } });
  return { ...r, card, setRuns };
}
const previewBtn = (card: HTMLElement) => within(card).getByRole("button", { name: "형상 미리보기" }) as HTMLButtonElement;
const gridCard = () => screen.findByRole("region", { name: "형상 미리보기" });
const cellsOf = (g: HTMLElement) => g.querySelectorAll("[data-testid^='dp-cell-']");

beforeEach(() => {
  resetWebGLCache();
  fake.scenes.length = 0;
  POLL.doePreview = 15;
});
afterEach(() => {
  vi.restoreAllMocks();
  resetWebGLCache();
});

describe("①-3 형상 미리보기 버튼(§8)", () => {
  it("native 단일 baseline: 표본 입력이 유효하면 활성 · 무효(run 수)면 비활성+사유 · 요청 전에는 카드 없음", async () => {
    const { card, setRuns } = await openCard();
    await waitFor(() => expect(previewBtn(card).disabled).toBe(false));
    expect(screen.queryByRole("region", { name: "형상 미리보기" })).toBeNull();
    setRuns("1");
    await waitFor(() => expect(previewBtn(card).disabled).toBe(true));
    expect(previewBtn(card).title).toContain("run 수");
    setRuns("40");
    await waitFor(() => expect(previewBtn(card).disabled).toBe(false));
  });
  it("Altair 엔진 = 비활성 + Native 전용 사유", async () => {
    renderApp(`${STUDY}/1`, { user: "power" });
    const card = await screen.findByRole("region", { name: "DOE · Radioss 입력" });
    expect(previewBtn(card).disabled).toBe(true);
    expect(previewBtn(card).title).toBe("형상 미리보기는 Native 형상 엔진에서만 쓸 수 있습니다");
  });
  it("다중 baseline 세트 = 비활성 + 문구 / 기능 꺼짐 = 관리자 설정 문구 / 조회 권한 = 비활성", async () => {
    const m = await openCard({ geometry: "multi" }, () => undefined, {}, false);
    fireEvent.change(await within(m.card).findByLabelText("형상 기준"), { target: { value: "ps-n1" } });
    await waitFor(() => expect(previewBtn(m.card).title).toBe("다중 baseline DOE는 형상 미리보기를 지원하지 않습니다"));
    expect(previewBtn(m.card).disabled).toBe(true);
    m.unmount();
    const off = await openCard({ disabledFeatures: ["doe_preview"] });
    expect(previewBtn(off.card).disabled).toBe(true);
    expect(previewBtn(off.card).title).toContain("관리자 설정 필요");
    off.unmount();
    const ro = await openCard({ user: "general" });
    expect(previewBtn(ro.card).disabled).toBe(true);
  });
});

describe("형상 미리보기 격자(§7)", () => {
  it("요청 본문 · 24셀 격자(첫 셀 공칭) · 캡션(#번호·최대 변위·바뀐 변수) · 공통 범례 1개 · tag 전 안내 · 외부 URL 0건", async () => {
    const { server, card, setRuns } = await openCard();
    setRuns("40");
    const posts = record(server, /^POST .*doe-previews$/);
    fireEvent.click(previewBtn(card));
    const g = await gridCard();
    await waitFor(() => expect(posts.length).toBe(1));
    expect(posts[0].body).toEqual({ source: { kind: "train" }, sampling: { kind: "lhs", count: 40, seed: 1 }, select: { order: "change", offset: 0, limit: 24 } });
    await waitFor(() => expect(within(g).getByTestId("dp-progress").textContent).toContain("24/24 완료"));
    const cs = cellsOf(g);
    expect(cs).toHaveLength(24);
    expect((cs[0] as HTMLElement).dataset.testid).toBe("dp-cell-nominal");
    expect(cs[0].textContent).toContain("공칭");
    expect(cs[1].querySelector(".dp-cap1")!.textContent).toMatch(/^#\d+ · 최대 [\d.]+ mm/);
    expect(cs[1].querySelector(".dp-cap2")?.textContent).toMatch(/\(([+−])\d+%\)/);
    // 범례 1개 + 문구, 변위 색 범위
    expect(within(g).getAllByTestId("dp-legend")).toHaveLength(1);
    expect(within(g).getByTestId("dp-legend").textContent).toContain("공칭 형상과의 거리(mm) — 모든 셀 같은 범위");
    expect(within(g).getByTestId("dp-legend").textContent).toContain("1.5");
    expect(g.querySelector("[data-colormap='turbo16']")).toBeTruthy();
    expect(within(g).getByTestId("dp-tag-note").textContent).toContain("태그 전 미리보기");
    // 이미지는 blob URL뿐(외부 URL 0건)
    await waitFor(() => expect(g.querySelectorAll("img").length).toBe(24));
    g.querySelectorAll("img").forEach((im) => expect(im.getAttribute("src")).toMatch(/^blob:/));
  });
  it("실패 셀: 빨간 테두리 클래스 + 사유 배지·문구, 잘림·범위 초과 표시, 진행 문구 '실패 2'", async () => {
    const { card, setRuns } = await openCard();
    setRuns("40");
    fireEvent.click(previewBtn(card));
    const g = await gridCard();
    await waitFor(() => expect(within(g).getByTestId("dp-progress").textContent).toContain("24/24 완료 · 실패 2 · 오류 0"));
    const fails = [...g.querySelectorAll(".dp-cell.fail")];
    expect(fails).toHaveLength(2);
    expect(within(fails[0] as HTMLElement).getByTestId("dp-fail").textContent).toContain("CAD 생성 불가");
    expect(fails[0].textContent).toContain("피처 충돌");
    expect(g.querySelectorAll(".dp-clip")).toHaveLength(1);
    expect(g.querySelectorAll(".dp-over").length).toBeGreaterThan(0);
  });
  it("정렬: 변화 큰 순(기본) → DOE 순서 → 변수 값 ↑↓ 요청, 바뀔 때마다 처음부터", async () => {
    const { server, card, setRuns } = await openCard();
    setRuns("40");
    const posts = record(server, /^POST .*doe-previews$/);
    fireEvent.click(previewBtn(card));
    const g = await gridCard();
    await waitFor(() => expect(within(g).getByTestId("dp-progress").textContent).toContain("24/24"));
    fireEvent.click(within(g).getByRole("button", { name: "DOE 순서" }));
    await waitFor(() => expect(posts.length).toBe(2));
    expect((posts[1].body.select as Record<string, unknown>).order).toBe("doe");
    await waitFor(() => expect(within(g).getByTestId("dp-progress").textContent).toContain("24/24"));
    const nos = [...cellsOf(g)].slice(1, 4).map((c) => c.textContent!.match(/^#(\d+)/)![1]);
    expect(nos).toEqual(["1", "2", "3"]);
    fireEvent.click(within(g).getByRole("button", { name: "변수 값" }));
    await waitFor(() => expect(posts.length).toBe(3));
    expect(posts[2].body.select).toMatchObject({ order: "var", var: "CUSH_L_THK_1", offset: 0, limit: 24 });
    expect((posts[2].body.select as { desc?: boolean }).desc).toBeUndefined();
    fireEvent.change(within(g).getByLabelText("정렬 변수"), { target: { value: "CUSH_L_HOLE_U_1" } });
    await waitFor(() => expect(posts.length).toBe(4));
    fireEvent.click(within(g).getByRole("button", { name: "오름차순" }));
    await waitFor(() => expect(posts.length).toBe(5));
    expect(posts[4].body.select).toMatchObject({ order: "var", var: "CUSH_L_HOLE_U_1", desc: true });
  });
  it("[다음 24개]: offset 24로 요청해 이어 붙임(공칭 1개만), 끝나면 비활성 · [실패만]은 렌더된 셀에만", async () => {
    const { server, card, setRuns } = await openCard();
    setRuns("40");
    const posts = record(server, /^POST .*doe-previews$/);
    fireEvent.click(previewBtn(card));
    const g = await gridCard();
    await waitFor(() => expect(within(g).getByTestId("dp-progress").textContent).toContain("24/24"));
    const next = within(g).getByRole("button", { name: "다음 24개" }) as HTMLButtonElement;
    await waitFor(() => expect(next.disabled).toBe(false));
    fireEvent.click(next);
    await waitFor(() => expect(posts.length).toBe(2));
    expect((posts[1].body.select as { offset: number }).offset).toBe(24);
    await waitFor(() => expect(cellsOf(g).length).toBe(24 + 17));
    expect(g.querySelectorAll("[data-testid='dp-cell-nominal']")).toHaveLength(1);
    await waitFor(() => expect((within(g).getByRole("button", { name: "다음 24개" }) as HTMLButtonElement).disabled).toBe(true));
    await waitFor(() => expect(within(g).getByTestId("dp-progress").textContent).toContain("41/41 완료 · 실패 4"));
    fireEvent.click(within(g).getByLabelText("실패만"));
    expect(cellsOf(g)).toHaveLength(4);
    expect([...cellsOf(g)].every((c) => c.getAttribute("data-status") === "FAIL")).toBe(true);
  });
  it("진행 중: 진행률·[취소] → 취소하면 이미 만든 셀은 남고 나머지는 만드는 중으로 둔다", async () => {
    const { server, card, setRuns } = await openCard({}, nativeSetup, { hold: true });
    setRuns("40");
    fireEvent.click(previewBtn(card));
    const g = await gridCard();
    await waitFor(() => expect(within(g).getByTestId("dp-progress").textContent).toContain("12/24 완료"));
    expect(within(g).getByRole("progressbar", { name: "형상 미리보기 진행률" })).toBeTruthy();
    expect((within(g).getByRole("button", { name: "다음 24개" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(within(g).getByRole("button", { name: "취소" }));
    await waitFor(() => expect(dpRecords(server)[0].status).toBe("CANCELED"));
    await waitFor(() => expect(within(g).queryByRole("button", { name: "취소" })).toBeNull());
    expect(g.textContent).toContain("이미 만든 셀은 남습니다");
    expect(within(g).getByTestId("dp-progress").textContent).toContain("12/24 완료");
  });
  it("오류 셀: 점선 오류 표시 + [다시] → 같은 페이지 다시 요청", async () => {
    const { server, card, setRuns } = await openCard({}, nativeSetup, { error: true });
    setRuns("40");
    const posts = record(server, /^POST .*doe-previews$/);
    fireEvent.click(previewBtn(card));
    const g = await gridCard();
    await waitFor(() => expect(within(g).getByTestId("dp-progress").textContent).toContain("오류 1"));
    expect(g.querySelectorAll(".dp-cell.error")).toHaveLength(1);
    fireEvent.click(within(g).getByRole("button", { name: "미리보기 오류 — 다시" }));
    await waitFor(() => expect(posts.length).toBe(2));
    expect(posts[1].body.select).toMatchObject({ offset: 0 });
  });
  it("낡음: 요청 뒤 run 수가 바뀌면 안내 + 흐린 격자, [다시 미리보기]로 새 요청", async () => {
    const { server, card, setRuns } = await openCard();
    setRuns("40");
    const posts = record(server, /^POST .*doe-previews$/);
    fireEvent.click(previewBtn(card));
    const g = await gridCard();
    await waitFor(() => expect(within(g).getByTestId("dp-progress").textContent).toContain("24/24"));
    expect(within(g).queryByTestId("dp-stale")).toBeNull();
    setRuns("30");
    expect((await within(g).findByTestId("dp-stale")).textContent).toContain("설정이 바뀌었습니다");
    expect(within(g).getByTestId("dp-grid").className).toContain("stale");
    fireEvent.click(within(g).getByRole("button", { name: "다시 미리보기" }));
    await waitFor(() => expect(posts.length).toBe(2));
    expect((posts[1].body.sampling as { count: number }).count).toBe(30);
    await waitFor(() => expect(within(g).queryByTestId("dp-stale")).toBeNull());
  });
  it("서버 409(다중 baseline 등)·꺼짐 → 카드 안 오류 문구", async () => {
    const { server, card, setRuns } = await openCard();
    setRuns("40");
    const orig = server.handle.bind(server);
    server.handle = (m, p, q, b, h) => (m === "POST" && /doe-previews$/.test(p) ? { status: 409, body: { detail: { code: "DOE_PREVIEW_UNSUPPORTED", message: "x" } } } : orig(m, p, q, b, h));
    fireEvent.click(previewBtn(card));
    const g = await gridCard();
    expect((await within(g).findByTestId("dp-error")).textContent).toBe("다중 baseline DOE는 형상 미리보기를 지원하지 않습니다");
  });
});

describe("셀 클릭 → 3D 뷰어 대화상자(§7)", () => {
  async function openGrid() {
    const r = await openCard();
    r.setRuns("40");
    fireEvent.click(previewBtn(r.card));
    const g = await gridCard();
    await waitFor(() => expect(within(g).getByTestId("dp-progress").textContent).toContain("24/24"));
    await waitFor(() => expect(g.querySelectorAll("img").length).toBe(24));
    return { ...r, g };
  }
  it("뷰어 1개(WebGL 컨텍스트 ≤ 1): 공칭 GLB + 셀 GLB 겹침(같은 색 범위), 다른 셀을 열기 전 닫아 dispose, 실패 셀은 겹침 없이 빨강", async () => {
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({} as never);
    resetWebGLCache();
    const { g } = await openGrid();
    // ①-2 공칭 3D 뷰(같은 화면)가 쓰는 장면은 제외 — 격자(PNG)와 닫힌 대화상자는 WebGL을 더하지 않는다
    const base = fake.scenes.length;
    const alive = () => fake.scenes.filter((s) => !s.dispose.mock.calls.length).length;
    const baseAlive = alive();
    fireEvent.click(g.querySelectorAll("[data-testid^='dp-cell-']")[1]);
    const dlg = await screen.findByRole("dialog");
    await waitFor(() => expect(fake.scenes).toHaveLength(base + 1));
    const sc = () => fake.scenes[base];
    await waitFor(() => expect(sc().setNominal).toHaveBeenCalled());
    await waitFor(() => expect(sc().setOverlay).toHaveBeenCalled());
    expect(alive()).toBe(baseAlive + 1);
    const ov = last(sc().setOverlay);
    expect(ov[0]).toBeInstanceOf(ArrayBuffer);
    expect(ov[1]).toBe("shape");
    expect(ov[2]).toBe(1.5);
    expect(within(dlg).getByTestId("dp-dialog-legend")).toBeTruthy();
    expect(within(dlg).getByRole("table", { name: "표본 변수 값" })).toBeTruthy();
    fireEvent.click(within(dlg).getByRole("button", { name: "닫기" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(sc().dispose).toHaveBeenCalled();
    expect(alive()).toBe(baseAlive);
    // 실패 셀 → 빨강 면 + 겹침 없음
    fireEvent.click(g.querySelector(".dp-cell.fail")!);
    const dlg2 = await screen.findByRole("dialog");
    expect(within(dlg2).getByTestId("dp-dialog-fail").textContent).toContain("CAD 생성 불가");
    await waitFor(() => expect(fake.scenes).toHaveLength(base + 2));
    const sc2 = fake.scenes[base + 1];
    await waitFor(() => expect(sc2.setHighlight).toHaveBeenCalled());
    const hl = last(sc2.setHighlight)[0] as { red: Set<string> };
    expect(hl.red.size).toBeGreaterThan(0);
    expect(last(sc2.setOverlay)[0]).toBeNull();
    expect(alive()).toBe(baseAlive + 1); // 대화상자의 장면은 한 번에 1개
  });
  it("WebGL 불가: 격자는 그대로 동작하고, 셀 클릭은 같은 PNG 2배 + 값 표", async () => {
    const { g } = await openGrid();
    expect(webglOff()).toBe(true);
    fireEvent.click(g.querySelectorAll("[data-testid^='dp-cell-']")[2]);
    const dlg = await screen.findByRole("dialog");
    expect(within(dlg).getByTestId("dp-dialog-fallback").textContent).toContain("WebGL");
    const big = await within(dlg).findByTestId("dp-big-png");
    await waitFor(() => expect(big.querySelector("img")?.getAttribute("width")).toBe("640"));
    expect(within(dlg).getByRole("table", { name: "표본 변수 값" })).toBeTruthy();
  });
});
const webglOff = () => document.createElement("canvas").getContext("webgl2") === null;

describe("생성 후 갤러리(V-DP-12)", () => {
  const platformDoe = (s: MockServer) => {
    nativeSetup(s);
    Object.assign(s.p2.does[0], { generator: "platform", gen: { total: 30, done: 30, failed: 2 } });
  };
  it("[형상 갤러리] → train_doe 요청(표본 생략) · run 번호 · SKIPPED 코드·단계 배지 · tag 안내 없음", async () => {
    const { server, card } = await openCard({}, platformDoe);
    const posts = record(server, /^POST .*doe-previews$/);
    fireEvent.click(await within(card).findByTestId("dp-open-gallery"));
    const g = await screen.findByRole("region", { name: "형상 갤러리" });
    await waitFor(() => expect(posts.length).toBe(1));
    expect(posts[0].body).toEqual({ source: { kind: "train_doe", doe_id: "doe-1" }, select: { order: "change", offset: 0, limit: 24 } });
    await waitFor(() => expect(within(g).getByTestId("dp-progress").textContent).toContain("24/24"));
    fireEvent.click(within(g).getByRole("button", { name: "DOE 순서" }));
    await waitFor(() => expect(posts.length).toBe(2));
    await waitFor(() => expect(within(g).getByTestId("dp-progress").textContent).toContain("24/24"));
    expect(cellsOf(g)[1].textContent).toMatch(/^run 1 /);
    const badges = within(g).getAllByTestId("dp-gen").map((b) => b.textContent);
    expect(badges).toContain("스킵 GEOM_QUALITY · 검사");
    expect(badges).toContain("스킵 GEOM_FEATURE_COLLISION · 형상 갱신");
    // 미리보기는 OK인데 생성은 스킵인 셀: 테두리는 그대로(OK), 배지만 빨강
    const skipped = within(g).getAllByTestId("dp-gen")[0].closest(".dp-cell")!;
    expect(skipped.getAttribute("data-status")).toBe("OK");
    expect(within(g).getAllByTestId("dp-gen")[0].className).toContain("bad");
    expect(within(g).queryByTestId("dp-tag-note")).toBeNull();
  });
  it("Altair(HyperStudy) DOE에는 갤러리 버튼이 없다", async () => {
    const { card } = await openCard({}, nativeSetup);
    await within(card).findByTestId("doe-result-line");
    expect(within(card).queryByTestId("dp-open-gallery")).toBeNull();
  });
});

describe("셀 목 산출물", () => {
  it("PNG는 목 서버가 진짜 PNG 바이트로 서빙(GEOM_THUMB_PNG)", async () => {
    const { server, card, setRuns } = await openCard();
    setRuns("40");
    fireEvent.click(previewBtn(card));
    const g = await gridCard();
    await waitFor(() => expect(within(g).getByTestId("dp-progress").textContent).toContain("24/24"));
    const pv = dpRecords(server)[0];
    expect(pv.cells[0].png_artifact_id).toBeTruthy();
    const r = server.handle("GET", `/artifacts/${pv.cells[1].png_artifact_id}/media`, new URLSearchParams(), null, new Headers());
    expect(r.bytes?.slice(0, 4)).toEqual(new Uint8Array([137, 80, 78, 71]));
    expect(r.contentType).toBe("image/png");
    act(() => undefined);
  });
});
