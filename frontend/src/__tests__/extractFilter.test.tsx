// v0.2.3 native 추출 조건(extract-filter.md §3~§8): 순수 함수(그룹·검증·표시 문구·요약·위치형 종류) + ①-1 블록(U1 미리 채움·U2 확인 창·altair 숨김·422 행 표시)
// + ①-2 적용 조건 줄·추출 요약 + ④ 등록 폼(①-1 조건 가져오기·안내)·세트 상세 적용 조건 + 다중 선택 일괄 사용 체크·해제(엑셀식).
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { renderApp, STUDY } from "../test/render";
import type { MockServer } from "../mock/server";
import { nativeTrainParams } from "../mock/geometry";
import { mockSummary, normalizeFilter } from "../mock/extractFilter";
import { err } from "../mock/route";
import { baseJob } from "../mock/steps";
import type { ExtractFilter } from "../api/types";
import { STEP_LABELS } from "../lib/steps";
import { isPositionType, rangeText, typeLabel } from "../lib/geometry";
import { bulkTargets } from "../stages/stage4/geomview/selection";
import { buildFaceRows, dimText, rowHighlight, sliderSpec, type ViewManifest } from "../stages/stage4/geomview/viewerCore";
import { cushionFeatures, cushionGlb, NOMINAL, viewManifest } from "../mock/geomViewData";
import {
  EXTRACT_GROUPS, MSG, extractProblems, filterText, fromFilter, presetForm, sameFilter, summaryView, toFilter, validateForm,
} from "../lib/extractFilter";

const STEP = "E:/shared/AI_WORK/cushion/00_inbox/cad/base.step";
const ROOT = "E:/shared/AI_WORK/cushion/00_inbox";
const SAVED: ExtractFilter = {
  groups: ["thickness", "position", "fillet"],
  conditions: { thickness_mm: { min: 2, max: 30 }, face_area_min_mm2: 50, position_min_size_mm: 3, fillet_radius_min_mm: 1 },
  draft_max_deg: null,
};

describe("lib/extractFilter — 그룹·검증·문구", () => {
  it("U1: 저장된 조건이 없으면 다섯 그룹 모두 체크·빈칸, 있으면 그 값", () => {
    expect(EXTRACT_GROUPS.map((g) => g.label)).toEqual(["두께", "높이·깊이", "위치(구멍·리브)", "구멍 반경", "필렛"]);
    expect(fromFilter(null)).toEqual(presetForm());
    expect(presetForm().groups).toEqual(["thickness", "height", "position", "hole_radius", "fillet"]);
    expect(toFilter(presetForm())).toEqual({ groups: ["thickness", "height", "position", "hole_radius", "fillet"], conditions: {}, draft_max_deg: null });
    const f = fromFilter(SAVED);
    expect(f.groups).toEqual(["thickness", "position", "fillet"]);
    expect(f.v).toMatchObject({ "thickness_mm.min": "2", "thickness_mm.max": "30", face_area_min_mm2: "50", position_min_size_mm: "3", fillet_radius_min_mm: "1" });
    expect(toFilter(f)).toEqual(SAVED);
  });

  it("체크하지 않은 그룹의 조건은 보내지 않고 검사하지도 않는다", () => {
    const f = { groups: ["fillet" as const], v: { "thickness_mm.min": "-1", fillet_radius_min_mm: "1.5" } };
    expect(validateForm(f)).toEqual([]);
    expect(toFilter(f)).toEqual({ groups: ["fillet"], conditions: { fillet_radius_min_mm: 1.5 }, draft_max_deg: null });
  });

  it("클라이언트 검증: §6.1 문구(그룹 0개·0 이하·min>max·구배 범위)", () => {
    expect(validateForm({ groups: [], v: {} })).toEqual([{ key: "groups", message: "찾을 종류를 하나 이상 고르세요" }]);
    const all = presetForm().groups;
    const msg = (v: Record<string, string>) => validateForm({ groups: all, v }).map((p) => [p.key, p.message]);
    expect(msg({ "thickness_mm.min": "5", "thickness_mm.max": "3" })).toEqual([["conditions.thickness_mm", "최솟값이 최댓값보다 큽니다"]]);
    expect(msg({ face_area_min_mm2: "0" })).toEqual([["conditions.face_area_min_mm2", "0보다 큰 값을 넣으세요"]]);
    expect(msg({ fillet_radius_min_mm: "-2" })).toEqual([["conditions.fillet_radius_min_mm", "0보다 큰 값을 넣으세요"]]);
    expect(msg({ "height_mm.max": "0" })).toEqual([["conditions.height_mm.max", "0보다 큰 값을 넣으세요"]]);
    expect(msg({ "thickness_mm.min": "0", "thickness_mm.max": "3" })).toEqual([]); // min은 0 허용
    expect(msg({ hole_radius_min_mm: "abc" })).toEqual([["conditions.hole_radius_min_mm", "0보다 큰 값을 넣으세요"]]);
    expect(msg({ draft_max_deg: "45" })).toEqual([["draft_max_deg", MSG.draft]]);
    expect(msg({ draft_max_deg: "5" })).toEqual([]);
  });

  it("422 problems 추출 — EXTRACT_FILTER_INVALID만", () => {
    expect(extractProblems({ code: "EXTRACT_FILTER_INVALID", message: "x", problems: [{ key: "groups", message: "m" }] } as never)).toEqual([{ key: "groups", message: "m" }]);
    expect(extractProblems({ code: "OTHER", message: "x", problems: [{ key: "a", message: "b" }] } as never)).toEqual([]);
    expect(extractProblems(null)).toEqual([]);
  });

  it("같은 조건 비교(U2): 그룹 순서·미선택 그룹 조건·빈 값은 무시, 없음 ≠ 있음", () => {
    expect(sameFilter(SAVED, { ...SAVED, groups: ["fillet", "thickness", "position"] })).toBe(true);
    expect(sameFilter(SAVED, { ...SAVED, conditions: { ...SAVED.conditions, height_mm: { min: 1, max: 2 } } })).toBe(true); // height 그룹 미선택 → 효과 없음
    expect(sameFilter(SAVED, { ...SAVED, draft_max_deg: 4 })).toBe(false);
    expect(sameFilter(null, null)).toBe(true);
    expect(sameFilter(null, toFilter(presetForm()))).toBe(false);
  });

  it("적용 조건 문구(§6.4): 조건·제외 그룹·구배, 없음 = 전체 종류(조건 없음)", () => {
    expect(filterText(null)).toBe("전체 종류(조건 없음)");
    expect(filterText(toFilter(presetForm()))).toBe("전체 종류(조건 없음)");
    expect(filterText({ ...SAVED, draft_max_deg: 3 })).toBe("두께 2~30 mm · 면적 ≥ 50 mm² · 위치 최소 3 mm · 필렛 r ≥ 1 mm · 구배 3° · 제외: 높이·깊이, 구멍 반경");
    expect(filterText({ groups: ["height", "hole_radius"], conditions: { height_mm: { min: null, max: 20 }, hole_radius_min_mm: 0.5 }, draft_max_deg: null })).toBe("높이·깊이 ≤ 20 mm · 구멍 반경 r ≥ 0.5 mm · 제외: 두께, 위치(구멍·리브), 필렛");
    expect(filterText({ groups: ["thickness"], conditions: {}, draft_max_deg: null })).toBe("조건 없음 · 제외: 높이·깊이, 위치(구멍·리브), 구멍 반경, 필렛");
  });

  it("추출 요약(§7.2): 선택한 종류의 채택·제외(사유 표기), 리브 탈락 사유는 §7.2 표기·모르는 키는 원래 이름", () => {
    const v = summaryView({
      types: {
        THICKNESS: { selected: true, kept: 12, excluded: { face_area: 180, thickness_range: 9, not_mutual: 21 } },
        HOLE_RADIUS: { selected: false, kept: 0, excluded: {} },
        FILLET_RADIUS: { selected: true, kept: 4, excluded: { fillet_radius_min: 26, brand_new: 2 } },
      },
      rib_rejects: { cap_not_convex: 14, lateral_not_plane: 6, lateral_draft: 3, base_mismatch: 2, weird_key: 1, cap_inner_wire: 0 },
    })!;
    expect(v.rows.map((r) => [r.label, r.kept, r.excluded])).toEqual([["두께", 12, 210], ["필렛 반경", 4, 28]]);
    expect(v.rows[0].reasons.map((r) => `${r.label} ${r.count}`)).toEqual(["면적 180", "범위 9", "비상호 21"]);
    expect(v.rows[1].reasons.map((r) => r.label)).toEqual(["반경", "brand_new"]);
    expect(v.ribTotal).toBe(26);
    expect(v.ribRejects.map((r) => `${r.label} ${r.count}`)).toEqual(["윗면 볼록 아님 14", "측면 곡면 6", "측면 구배 3", "밑면 불일치 2", "weird_key 1"]);
    expect(summaryView(null)).toBeNull();
    expect(summaryView({ nope: 1 })).toBeNull();
  });

  it("엑셀식 대상: 선택 안의 행이면 선택 전체, 밖이면 그 행만", () => {
    expect(bulkTargets(["a", "b"], "a")).toEqual(["a", "b"]);
    expect(bulkTargets(["a", "b"], "c")).toEqual(["c"]);
    expect(bulkTargets([], "c")).toEqual(["c"]);
  });

  it("steps: Altair 파라미터 추출 표기(백엔드와 일치)", () => {
    expect(STEP_LABELS.SIMLAB_EXTRACT).toBe("Altair 파라미터 추출");
  });
});

describe("RIB_POS_U/V 종류 표기·위치형·3D", () => {
  it("표시명·위치형(mm 범위)", () => {
    expect(typeLabel("RIB_POS_U")).toBe("리브 위치 U");
    expect(typeLabel("RIB_POS_V")).toBe("리브 위치 V");
    expect(typeLabel("HOLE_POS_U")).toBe("구멍 위치 U");
    expect(["RIB_POS_U", "RIB_POS_V", "HOLE_POS_U", "HOLE_POS_V"].every(isPositionType)).toBe(true);
    expect(isPositionType("RIB_THICKNESS")).toBe(false);
    expect(rangeText(51.5, 46.5, 56.5, "RIB_POS_U")).toBe("46.5 ~ 56.5 (∓5 mm)");
  });

  it("3D: moving(주황)·fixed(파랑) 면 하이라이트·치수선(위치 선분) — RIB_POS_U 피처", () => {
    const g = cushionGlb(NOMINAL, false);
    const m: ViewManifest = viewManifest(g.bodies, g.glb.byteLength);
    const base = cushionFeatures(NOMINAL)[3];
    m.features.push({
      ...base, name: "CUSH_L_RIB_U_1", parameter: "CUSH_L_RIB_U_1", type: "RIB_POS_U", value: 51.5, nominal: 51.5, range: { min: 46.5, max: 56.5 },
      feasible: { min: 47, max: 60, source: "estimate" }, faces: { moving: ["F7", "F8", "F9", "F10", "F11"], fixed: ["F1"] },
      dimension: { kind: "position", p0: [0, 40, 12.5], p1: [51.5, 40, 12.5], label: [25, 40, 24], value: 51.5, unit: "mm", geom_len: 51.5 },
    });
    const h = rowHighlight(m, "CUSH_L_RIB_U_1");
    expect([...h.moving].sort()).toEqual(["CUSH_L#10", "CUSH_L#11", "CUSH_L#7", "CUSH_L#8", "CUSH_L#9"]);
    expect([...h.fixed]).toEqual(["CUSH_L#1"]);
    expect(h.dims.map((d) => d.text)).toEqual(["51.5 mm"]);
    expect(dimText(m.features[m.features.length - 1].dimension!)).toBe("51.5 mm");
    expect(buildFaceRows(m).get("CUSH_L#9")).toContain("CUSH_L_RIB_U_1");
    expect(sliderSpec(m.features[m.features.length - 1])).toMatchObject({ min: 47, max: 60 });
  });
});

// ---------------------------------------------------------------- 화면

async function openCard(opts: { geometryDefault?: "altair" | "native" } = {}, setup?: (s: MockServer) => void) {
  const utils = renderApp(`${STUDY}/1`, { user: "power", geometry: "native", geometryDefault: "native", ...opts }, setup);
  const card = await screen.findByRole("region", { name: "CAD 파라미터 추출" });
  const check = async () => {
    fireEvent.click(within(card).getByRole("button", { name: "확인" }));
    await waitFor(() => expect(within(card).queryByRole("button", { name: "확인 중…" })).toBeNull());
  };
  const type = (v: string) => fireEvent.change(within(card).getByLabelText(/CAD 파일 경로/), { target: { value: v } });
  const run = () => within(card).getByRole("button", { name: "파라미터 추출" }) as HTMLButtonElement;
  const box = (name: string) => within(card).getByRole("checkbox", { name }) as HTMLInputElement;
  const openCond = () => fireEvent.click(within(card).getByRole("button", { name: /조건\(선택\)/ }));
  return { ...utils, card, check, type, run, box, openCond };
}

function jobBodies(server: MockServer) {
  const out: Record<string, unknown>[] = [];
  const orig = server.handle.bind(server);
  server.handle = (m, p, q, b, h) => {
    if (m === "POST" && /\/jobs$/.test(p)) out.push(b as Record<string, unknown>);
    return orig(m, p, q, b, h);
  };
  return out;
}

describe("①-1 찾을 종류·조건 블록", () => {
  afterEach(() => vi.restoreAllMocks());

  it("native: 체크 5개(모두 체크) + 조건 접힘(기본 닫힘) · 칸은 체크한 그룹만 · 빈칸 placeholder", async () => {
    const { card, box, openCond } = await openCard();
    const block = within(card).getByTestId("extract-filter");
    for (const g of ["두께", "높이·깊이", "위치(구멍·리브)", "구멍 반경", "필렛"]) expect(box(g).checked).toBe(true);
    expect(within(block).queryByTestId("extract-filter-cond")).toBeNull();
    openCond();
    const cond = within(block).getByTestId("extract-filter-cond");
    expect(within(cond).getByText("두께 범위 (mm)")).toBeTruthy();
    expect(within(cond).getByLabelText("최소 면 면적 (mm²)").getAttribute("placeholder")).toBe("비우면 조건 없음");
    expect(within(cond).getByText("높이·깊이 범위 (mm)")).toBeTruthy();
    expect(within(cond).getByText("최소 크기 (mm) — 구멍 지름·리브 폭")).toBeTruthy();
    expect(within(cond).getByText("구멍 반경 하한 r ≥ (mm)")).toBeTruthy();
    expect(within(cond).getByText("필렛 반경 하한 r ≥ (mm)")).toBeTruthy();
    fireEvent.click(box("높이·깊이")); // 해제 → 그 그룹 칸 숨김
    expect(within(cond).queryByText("높이·깊이 범위 (mm)")).toBeNull();
    // ①-1 가로 배치: 구배 칸은 고급 접힘 없이 같은 줄 끝, 도움말은 ⓘ(title)
    expect(within(cond).queryByRole("button", { name: /고급/ })).toBeNull();
    expect(within(cond).getByLabelText("구배 허용각 (°)")).toBeTruthy();
    expect(within(cond).getByTitle(/리브로 인식되지 않습니다/)).toBeTruthy();
  });

  it("altair: 블록 숨김(화면 무변경), 요청에 extract_filter 없음 · native로 바꾸면 나타남", async () => {
    const { card, check, type, run, server } = await openCard({ geometryDefault: "altair" });
    const bodies = jobBodies(server);
    expect(within(card).queryByTestId("extract-filter")).toBeNull();
    expect(within(card).queryByText("찾을 종류")).toBeNull();
    type("E:/shared/AI_WORK/cushion/00_inbox/cad/base.prt");
    await check();
    await waitFor(() => expect(run().disabled).toBe(false));
    fireEvent.click(run()); // 기존 표가 있어도 altair는 확인 창 없음
    await waitFor(() => expect(bodies.length).toBe(1));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(bodies[0].params).toEqual({ cad_path: "E:/shared/AI_WORK/cushion/00_inbox/cad/base.prt" });
    fireEvent.click(within(card).getByRole("radio", { name: "Native" }));
    expect(within(card).getByTestId("extract-filter")).toBeTruthy();
  });

  it("U1: Study의 마지막 사용 조건이 있으면 미리 채움(체크·조건 칸)", async () => {
    const { card, box, openCond } = await openCard({}, (s) => Object.assign(s.p2.setups["s-cushion"], { engine: "native", extract_filter: SAVED }));
    await waitFor(() => expect(box("높이·깊이").checked).toBe(false));
    expect(box("두께").checked).toBe(true);
    expect(box("위치(구멍·리브)").checked).toBe(true);
    expect(box("구멍 반경").checked).toBe(false);
    expect(box("필렛").checked).toBe(true);
    expect(within(card).getByText("조건 4개 지정됨")).toBeTruthy();
    openCond();
    expect((within(card).getByLabelText("두께 범위 (mm) 최소") as HTMLInputElement).value).toBe("2");
    expect((within(card).getByLabelText("두께 범위 (mm) 최대") as HTMLInputElement).value).toBe("30");
    expect((within(card).getByLabelText("최소 면 면적 (mm²)") as HTMLInputElement).value).toBe("50");
    expect((within(card).getByLabelText("필렛 반경 하한 r ≥ (mm)") as HTMLInputElement).value).toBe("1");
  });

  it("조건 없음 → 요청 params에 extract_filter(모두 체크·빈칸), 기존 표 없음 → 확인 창 없음", async () => {
    const { check, type, run, server } = await openCard({}, (s) => Object.assign(s.p2.setups["s-cushion"], { parameters: [], used_count: 0, cad: null, tpl: null }));
    const bodies = jobBodies(server);
    type(STEP);
    await check();
    await waitFor(() => expect(run().disabled).toBe(false));
    fireEvent.click(run());
    await waitFor(() => expect(bodies.length).toBe(1));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(bodies[0].params).toEqual({ cad_path: STEP, engine: "native", extract_filter: { groups: ["thickness", "height", "position", "hole_radius", "fillet"], conditions: {}, draft_max_deg: null } });
  });

  it("0개 선택 → 실행 비활성 + 문구 · 값 오류 → 칸 아래 문구·비활성(min>max)", async () => {
    const { card, check, type, run, box, openCond } = await openCard();
    type(STEP);
    await check();
    await waitFor(() => expect(run().disabled).toBe(false));
    for (const g of ["두께", "높이·깊이", "위치(구멍·리브)", "구멍 반경", "필렛"]) fireEvent.click(box(g));
    expect(run().disabled).toBe(true);
    expect(within(card).getAllByText("찾을 종류를 하나 이상 고르세요").length).toBeGreaterThan(0);
    fireEvent.click(box("두께"));
    expect(run().disabled).toBe(false);
    openCond();
    fireEvent.change(within(card).getByLabelText("두께 범위 (mm) 최소"), { target: { value: "9" } });
    fireEvent.change(within(card).getByLabelText("두께 범위 (mm) 최대"), { target: { value: "3" } });
    expect(within(card).getByText("최솟값이 최댓값보다 큽니다")).toBeTruthy();
    expect(run().disabled).toBe(true);
    fireEvent.change(within(card).getByLabelText("두께 범위 (mm) 최대"), { target: { value: "30" } });
    expect(run().disabled).toBe(false);
  });

  it("서버 422 EXTRACT_FILTER_INVALID problems → 해당 칸 아래 행별 표시(접힘이면 자동으로 펼침), 고치면 사라짐", async () => {
    const { card, check, type, run, server } = await openCard({}, (s) => Object.assign(s.p2.setups["s-cushion"], { parameters: [], used_count: 0, tpl: null }));
    const orig = server.handle.bind(server);
    server.handle = (m, p, q, b, h) =>
      m === "POST" && /\/jobs$/.test(p)
        ? err(422, "EXTRACT_FILTER_INVALID", "추출 조건을 확인하세요", {
            problems: [{ key: "conditions.fillet_radius_min_mm", message: "0보다 큰 값을 넣으세요" }, { key: "draft_max_deg", message: "구배 허용각은 0°보다 크고 45°보다 작아야 합니다" }],
          })
        : orig(m, p, q, b, h);
    type(STEP);
    await check();
    await waitFor(() => expect(run().disabled).toBe(false));
    fireEvent.click(run());
    const cond = await within(card).findByTestId("extract-filter-cond");
    const fillet = within(cond).getByLabelText("필렛 반경 하한 r ≥ (mm)").closest(".field") as HTMLElement;
    expect(within(fillet).getByText("0보다 큰 값을 넣으세요")).toBeTruthy();
    expect(within(cond).getByText("구배 허용각은 0°보다 크고 45°보다 작아야 합니다")).toBeTruthy();
    fireEvent.change(within(cond).getByLabelText("필렛 반경 하한 r ≥ (mm)"), { target: { value: "1" } });
    await waitFor(() => expect(within(cond).queryByText("0보다 큰 값을 넣으세요")).toBeNull());
  });

  it("U2: 기존 표가 있는데 조건이 다르면 확인 창 → 취소 = 요청 없음, 바꾸기 = 실행 / 같은 조건이면 창 없음", async () => {
    const native = (s: MockServer) => Object.assign(s.p2.setups["s-cushion"], { engine: "native", parameters: nativeTrainParams(), tpl: null, extract_filter: SAVED });
    const { card, check, type, run, box, server } = await openCard({}, native);
    const bodies = jobBodies(server);
    type(STEP);
    await check();
    await waitFor(() => expect(run().disabled).toBe(false));
    await waitFor(() => expect(box("높이·깊이").checked).toBe(false)); // U1 미리 채움 = 마지막 조건과 같음
    fireEvent.click(box("높이·깊이")); // 다르게
    fireEvent.click(run());
    const dlg = await screen.findByRole("dialog");
    expect(within(dlg).getByText(/기존 파라미터 표\(6개, 적용 조건: 두께 2~30 mm/)).toBeTruthy();
    expect(within(dlg).getByText(/백업 후 새 결과로 바뀝니다/)).toBeTruthy();
    fireEvent.click(within(dlg).getByRole("button", { name: "취소" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(bodies.length).toBe(0);
    fireEvent.click(run());
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "바꾸기" }));
    await waitFor(() => expect(bodies.length).toBe(1));
    expect((bodies[0].params as { extract_filter: ExtractFilter }).extract_filter.groups).toEqual(["thickness", "height", "position", "fillet"]);
    // 같은 조건 → 창 없이 바로
    fireEvent.click(box("높이·깊이"));
    act(() => server.finishAll());
    await waitFor(() => expect(run().disabled).toBe(false));
    expect(within(card).queryByRole("dialog")).toBeNull();
  });
});

// ---------------------------------------------------------------- ①-2

const nativeTrain = (extra: Record<string, unknown> = {}) => (s: MockServer) =>
  Object.assign(s.p2.setups["s-cushion"], { engine: "native", parameters: nativeTrainParams(), tpl: null, extract_job_id: "j-x", ...extra });

async function paramTable() {
  const t = await screen.findByRole("table", { name: "파라미터 표" });
  const rowOf = (name: string) => t.querySelector(`tr[data-row="${name}"]`) as HTMLElement;
  const use = (name: string) => within(t).getByLabelText(`${name} 사용`) as HTMLInputElement;
  const click = (name: string, mods: { ctrlKey?: boolean; shiftKey?: boolean } = {}) => fireEvent.click(rowOf(name).querySelector("td.mono")!, mods);
  return { t, rowOf, use, click };
}

describe("①-2 적용 조건 줄·추출 요약", () => {
  it("적용 조건 한 줄(마지막 사용 조건)", async () => {
    renderApp(`${STUDY}/1`, { user: "power" }, nativeTrain({ extract_filter: { ...SAVED, draft_max_deg: 3 } }));
    await paramTable();
    expect((await screen.findByTestId("applied-filter-text")).textContent).toBe("두께 2~30 mm · 면적 ≥ 50 mm² · 위치 최소 3 mm · 필렛 r ≥ 1 mm · 구배 3° · 제외: 높이·깊이, 구멍 반경");
    expect(screen.getByTestId("applied-filter").textContent).toContain("적용 조건:");
  });

  it("조건이 없으면 전체 종류, 요약 없으면 요약 버튼 없음", async () => {
    renderApp(`${STUDY}/1`, { user: "power" }, nativeTrain({ extract_filter: null, extract_summary: null }));
    await paramTable();
    expect((await screen.findByTestId("applied-filter-text")).textContent).toBe("전체 종류(조건 없음)");
    expect(screen.queryByRole("button", { name: /추출 요약/ })).toBeNull();
  });

  it("추출 요약 접힘: 종류별 채택·제외 + 리브 탈락 사유(§7.2 표기, 모르는 키는 원래 이름)", async () => {
    const kinds = [{ type: "THICKNESS" }, { type: "THICKNESS" }, { type: "FILLET_RADIUS" }];
    renderApp(`${STUDY}/1`, { user: "power" }, nativeTrain({ extract_filter: SAVED, extract_summary: mockSummary(kinds, normalizeFilter(SAVED).norm) }));
    await paramTable();
    const btn = await screen.findByRole("button", { name: /추출 요약/ });
    expect(screen.queryByLabelText("추출 요약")).toBeNull();
    fireEvent.click(btn);
    const list = screen.getByLabelText("추출 요약");
    expect(within(list).getByText("두께: 채택 2 · 제외 210(면적 180, 범위 9, 비상호 21)")).toBeTruthy();
    expect(within(list).getByText("필렛 반경: 채택 1 · 제외 26(반경 26)")).toBeTruthy();
    expect(within(list).queryByText(/구멍 반경/)).toBeNull(); // 선택 안 한 종류는 줄 없음
    expect(within(list).getByText("리브 후보 탈락 20(윗면 볼록 아님 14, 측면 구배 3, 밑면 불일치 2, new_reason_x 1)")).toBeTruthy();
  });

  it("Altair 표: 적용 조건 줄·일괄 버튼 없음(화면 무변경)", async () => {
    renderApp(`${STUDY}/1`, { user: "power" });
    await paramTable();
    expect(screen.queryByTestId("applied-filter")).toBeNull();
    expect(screen.queryByTestId("bulk-use-bar")).toBeNull();
  });
});

describe("다중 선택 → 사용 체크·해제", () => {
  it("선택이 있을 때만 [사용 체크|사용 해제|선택 해제] — 선택 행 일괄 적용(사용 불가 행은 체크에서 제외)", async () => {
    renderApp(`${STUDY}/1`, { user: "power" }, nativeTrain());
    const { use, click } = await paramTable();
    expect(screen.queryByTestId("bulk-use-bar")).toBeNull();
    click("CUSH_L_THK_1");
    click("CUSH_L_RIB_T_2", { ctrlKey: true });
    click("CUSH_L_RIB_U_1", { ctrlKey: true });
    const bar = screen.getByTestId("bulk-use-bar");
    expect(bar.textContent).toContain("3개 선택");
    expect(use("CUSH_L_THK_1").checked).toBe(true);
    expect(use("CUSH_L_RIB_T_2").checked).toBe(false);
    fireEvent.click(within(bar).getByRole("button", { name: "사용 해제" }));
    expect(["CUSH_L_THK_1", "CUSH_L_RIB_T_2", "CUSH_L_RIB_U_1"].map((n) => use(n).checked)).toEqual([false, false, false]);
    expect(use("CUSH_L_HOLE_U_1").checked).toBe(true); // 선택 밖은 그대로
    fireEvent.click(within(bar).getByRole("button", { name: "사용 체크" }));
    expect(["CUSH_L_THK_1", "CUSH_L_RIB_T_2", "CUSH_L_RIB_U_1"].map((n) => use(n).checked)).toEqual([true, true, true]);
    expect(use("CUSH_L_POCKET_D_1").checked).toBe(true);
    fireEvent.click(within(bar).getByRole("button", { name: "선택 해제" }));
    expect(screen.queryByTestId("bulk-use-bar")).toBeNull();
    expect(screen.queryAllByRole("button", { name: "선택 해제" }).length).toBe(0);
  });

  it("Shift 범위 선택 후 일괄 해제", async () => {
    renderApp(`${STUDY}/1`, { user: "power" }, nativeTrain());
    const { use, click } = await paramTable();
    click("CUSH_L_THK_1");
    click("CUSH_L_RIB_T_2", { shiftKey: true });
    expect(screen.getByTestId("bulk-use-bar").textContent).toContain("3개 선택");
    fireEvent.click(within(screen.getByTestId("bulk-use-bar")).getByRole("button", { name: "사용 해제" }));
    expect(["CUSH_L_THK_1", "CUSH_L_POCKET_D_1", "CUSH_L_RIB_T_2"].map((n) => use(n).checked)).toEqual([false, false, false]);
    expect(use("CUSH_L_HOLE_U_1").checked).toBe(true);
  });

  it("엑셀식: 선택된 행의 체크박스 → 선택 행 전체가 같은 상태 / 선택 밖 행 → 그 행만", async () => {
    renderApp(`${STUDY}/1`, { user: "power" }, nativeTrain());
    const { use, click } = await paramTable();
    click("CUSH_L_THK_1");
    click("CUSH_L_POCKET_D_1", { ctrlKey: true });
    click("CUSH_L_RIB_T_2", { ctrlKey: true }); // THK·POCKET 사용, RIB_T 미사용 섞임
    fireEvent.click(use("CUSH_L_RIB_T_2")); // 미사용 → 사용: 선택 전체가 사용
    expect(["CUSH_L_THK_1", "CUSH_L_POCKET_D_1", "CUSH_L_RIB_T_2"].map((n) => use(n).checked)).toEqual([true, true, true]);
    fireEvent.click(use("CUSH_L_THK_1")); // 사용 → 해제: 선택 전체가 해제
    expect(["CUSH_L_THK_1", "CUSH_L_POCKET_D_1", "CUSH_L_RIB_T_2"].map((n) => use(n).checked)).toEqual([false, false, false]);
    fireEvent.click(use("CUSH_L_HOLE_U_1")); // 선택 밖: 그 행만
    expect(use("CUSH_L_HOLE_U_1").checked).toBe(false);
    expect(["CUSH_L_THK_1", "CUSH_L_POCKET_D_1", "CUSH_L_RIB_T_2"].map((n) => use(n).checked)).toEqual([false, false, false]);
    expect(use("CUSH_L_THK_1").closest("tr")!.getAttribute("aria-selected")).toBe("true"); // 체크박스 조작은 선택을 바꾸지 않는다
  });

  it("④ 쉘 두께 PROP 표: 선택 행 일괄 체크·해제(선택할 수 없는 PROP은 건너뜀) · 선택 행 체크박스 = 엑셀식", async () => {
    renderApp(`${STUDY}/4`, { user: "power", geometry: "native" }, (s) => {
      s.paramSets.forEach((p) => (p.is_current = p.id === "ps-n1"));
      s.geom.get("ps-n1")!.propsScanned = true;
    });
    fireEvent.click(await screen.findByRole("button", { name: "템플릿 관리" }));
    const card = await screen.findByRole("region", { name: "템플릿 관리" });
    const box = await within(card).findByTestId("shell-props");
    const t = await within(box).findByRole("table", { name: "쉘 두께 PROP" });
    const chk = (id: number) => within(t).getByLabelText(`PROP ${id} 선택`) as HTMLInputElement;
    const pick = (id: number, mods: { ctrlKey?: boolean } = {}) => fireEvent.click(chk(id).closest("tr")!.querySelectorAll("td")[1], mods);
    pick(101);
    pick(102, { ctrlKey: true });
    pick(201, { ctrlKey: true }); // 미지원 — 선택은 되지만 체크 대상 아님
    const bar = within(box).getByTestId("bulk-use-bar");
    fireEvent.click(within(bar).getByRole("button", { name: "사용 체크" }));
    expect([101, 102, 201].map((i) => chk(i).checked)).toEqual([true, true, false]);
    fireEvent.click(chk(102)); // 엑셀식: 선택 행 전체 해제
    expect([101, 102, 201].map((i) => chk(i).checked)).toEqual([false, false, false]);
    fireEvent.click(within(bar).getByRole("button", { name: "선택 해제" }));
    expect(within(box).queryByTestId("bulk-use-bar")).toBeNull();
  });
});

// ---------------------------------------------------------------- ④

async function openNativeForm(setup?: (s: MockServer) => void) {
  const utils = renderApp(`${STUDY}/4`, { user: "power" }, setup);
  fireEvent.click(await screen.findByRole("button", { name: "템플릿 관리" }));
  const card = await screen.findByRole("region", { name: "템플릿 관리" });
  fireEvent.click(within(card).getByRole("button", { name: "새로 등록" }));
  const form = within(card).getByTestId("ps-discover");
  const nativeBox = () => within(form).getByTestId("ps-extract-filter");
  const find = async (path: string) => {
    fireEvent.change(within(form).getByLabelText("프로젝트 폴더 경로"), { target: { value: path } });
    fireEvent.click(within(form).getByRole("button", { name: "찾기" }));
    await within(form).findByText("01_CAD/cushion_base.step");
  };
  return { ...utils, card, form, nativeBox, find, toNative: () => fireEvent.click(within(form).getByRole("radio", { name: "Native" })) };
}

describe("④ native 세트 등록 — 추출 조건", () => {
  it("altair: 조건 블록 없음 · native: 블록·안내 문구 표시", async () => {
    const { form, toNative } = await openNativeForm();
    expect(within(form).queryByTestId("ps-extract-filter")).toBeNull();
    toNative();
    expect(within(form).queryByTestId("ps-extract-filter")).toBeNull(); // 기본 해제 = 블록·안내 숨김(기존 동작)
    fireEvent.click(within(form).getByRole("checkbox", { name: "추출 조건 적용(새로 추출)" }));
    expect(within(form).getByTestId("ps-extract-filter")).toBeTruthy();
    expect(within(form).getByTestId("ps-extract-note").textContent).toBe("폴더의 기존 피처 파일 대신 새로 추출 · 등록 후 조건 변경 불가(새 세트로 등록)");
  });

  it("기본 해제: 요청에 extract_filter 없음(폴더의 피처 파일·parameters.json 사용) — 체크하면 포함은 아래 시험들", async () => {
    const { server, form, toNative, find } = await openNativeForm();
    const bodies: Record<string, unknown>[] = [];
    const orig = server.handle.bind(server);
    server.handle = (m, p, q, b, h) => (m === "POST" && /\/param-sets$/.test(p) && bodies.push(b as Record<string, unknown>), orig(m, p, q, b, h));
    toNative();
    const use = within(form).getByRole("checkbox", { name: "추출 조건 적용(새로 추출)" }) as HTMLInputElement;
    expect(use.checked).toBe(false);
    await find(`${ROOT}/native_project`);
    fireEvent.click(within(form).getByRole("button", { name: "등록" }));
    await waitFor(() => expect(bodies.length).toBe(1));
    expect("extract_filter" in bodies[0]).toBe(false);
    expect(server.jobs.filter((j) => j.job_type === "PARAM_SET_NATIVE").slice(-1)[0].params.extract_filter).toBeUndefined();
  });

  it("①-1 조건이 없으면 가져오기 비활성·프리셋(모두 체크) → 등록 요청에 extract_filter", async () => {
    const { server, form, toNative, find } = await openNativeForm();
    const bodies: Record<string, unknown>[] = [];
    const orig = server.handle.bind(server);
    server.handle = (m, p, q, b, h) => (m === "POST" && /\/param-sets$/.test(p) && bodies.push(b as Record<string, unknown>), orig(m, p, q, b, h));
    toNative();
    fireEvent.click(within(form).getByRole("checkbox", { name: "추출 조건 적용(새로 추출)" }));
    const imp = within(form).getByRole("checkbox", { name: /①-1 조건 가져오기/ }) as HTMLInputElement;
    expect(imp.disabled).toBe(true);
    expect(imp.checked).toBe(false);
    expect((within(form).getByRole("checkbox", { name: "두께" }) as HTMLInputElement).checked).toBe(true);
    await find(`${ROOT}/native_project`);
    fireEvent.click(within(form).getByRole("button", { name: "등록" }));
    await waitFor(() => expect(bodies.length).toBe(1));
    expect(bodies[0].extract_filter).toEqual({ groups: ["thickness", "height", "position", "hole_radius", "fillet"], conditions: {}, draft_max_deg: null });
    const job = server.jobs.filter((j) => j.job_type === "PARAM_SET_NATIVE").slice(-1)[0];
    expect(job.params.extract_filter).toEqual(bodies[0].extract_filter);
  });

  it("①-1 조건 가져오기: 기본 체크 = 복사본(수정 불가) → 풀면 편집 → 등록 요청 반영 · 세트 상세에 적용 조건", async () => {
    const { server, form, toNative, find, nativeBox } = await openNativeForm((s) => Object.assign(s.p2.setups["s-cushion"], { engine: "native", extract_filter: SAVED }));
    const bodies: Record<string, unknown>[] = [];
    const orig = server.handle.bind(server);
    server.handle = (m, p, q, b, h) => (m === "POST" && /\/param-sets$/.test(p) && bodies.push(b as Record<string, unknown>), orig(m, p, q, b, h));
    toNative();
    fireEvent.click(within(form).getByRole("checkbox", { name: "추출 조건 적용(새로 추출)" }));
    const imp = (await within(form).findByRole("checkbox", { name: /①-1 조건 가져오기/ })) as HTMLInputElement;
    await waitFor(() => expect(imp.disabled).toBe(false));
    expect(imp.checked).toBe(true);
    const thick = within(nativeBox()).getByRole("checkbox", { name: "두께" }) as HTMLInputElement;
    expect(thick.disabled).toBe(true); // 복사본 = 읽기 전용
    expect((within(nativeBox()).getByRole("checkbox", { name: "높이·깊이" }) as HTMLInputElement).checked).toBe(false);
    fireEvent.click(within(nativeBox()).getByRole("button", { name: /조건\(선택\)/ }));
    expect((within(nativeBox()).getByLabelText("필렛 반경 하한 r ≥ (mm)") as HTMLInputElement).value).toBe("1");
    expect((within(nativeBox()).getByLabelText("필렛 반경 하한 r ≥ (mm)") as HTMLInputElement).disabled).toBe(true);
    fireEvent.click(imp); // 해제 → 편집 가능
    expect(thick.disabled).toBe(false);
    fireEvent.change(within(nativeBox()).getByLabelText("필렛 반경 하한 r ≥ (mm)"), { target: { value: "2.5" } });
    fireEvent.click(within(nativeBox()).getByRole("checkbox", { name: "높이·깊이" }));
    await find(`${ROOT}/native_project`);
    fireEvent.click(within(form).getByRole("button", { name: "등록" }));
    await waitFor(() => expect(bodies.length).toBe(1));
    expect(bodies[0].extract_filter).toEqual({
      groups: ["thickness", "height", "position", "fillet"],
      conditions: { thickness_mm: { min: 2, max: 30 }, face_area_min_mm2: 50, position_min_size_mm: 3, fillet_radius_min_mm: 2.5 },
      draft_max_deg: null,
    });
    act(() => server.finishAll());
    await waitFor(() => expect(server.paramSets[0].engine).toBe("native"));
    expect(server.paramSets[0].native!.extract_filter).toMatchObject({ groups: ["thickness", "height", "position", "fillet"] });
    expect((await screen.findAllByTestId("applied-filter-text")).slice(-1)[0].textContent).toBe("두께 2~30 mm · 면적 ≥ 50 mm² · 위치 최소 3 mm · 필렛 r ≥ 2.5 mm · 제외: 구멍 반경");
    expect(screen.getByText("조건을 바꾸려면 새 세트로 등록하세요")).toBeTruthy();
  });

  it("서버 422 problems → 조건 칸 아래 표시, 0개 선택은 등록 비활성", async () => {
    const { server, form, toNative, find, nativeBox } = await openNativeForm();
    toNative();
    fireEvent.click(within(form).getByRole("checkbox", { name: "추출 조건 적용(새로 추출)" }));
    await find(`${ROOT}/native_project`);
    const orig = server.handle.bind(server);
    server.handle = (m, p, q, b, h) =>
      m === "POST" && /\/param-sets$/.test(p)
        ? err(422, "EXTRACT_FILTER_INVALID", "추출 조건을 확인하세요", { problems: [{ key: "conditions.hole_radius_min_mm", message: "0보다 큰 값을 넣으세요" }] })
        : orig(m, p, q, b, h);
    fireEvent.click(within(form).getByRole("button", { name: "등록" }));
    const cond = await within(nativeBox()).findByTestId("ps-extract-fields-cond");
    expect(within((within(cond).getByLabelText("구멍 반경 하한 r ≥ (mm)").closest(".field")) as HTMLElement).getByText("0보다 큰 값을 넣으세요")).toBeTruthy();
    for (const g of ["두께", "높이·깊이", "위치(구멍·리브)", "구멍 반경", "필렛"]) fireEvent.click(within(nativeBox()).getByRole("checkbox", { name: g }));
    expect((within(form).getByRole("button", { name: "등록" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("작업 경고 PARAMS_JSON_IGNORED(등록 뒤)·실패 GEOM_EXTRACT_EMPTY 문구 표시", async () => {
    const { server, form, toNative, find } = await openNativeForm();
    toNative();
    fireEvent.click(within(form).getByRole("checkbox", { name: "추출 조건 적용(새로 추출)" }));
    await find(`${ROOT}/native_params`);
    fireEvent.click(within(form).getByRole("button", { name: "등록" }));
    await waitFor(() => expect(server.jobs.some((j) => j.job_type === "PARAM_SET_NATIVE")).toBe(true));
    act(() => server.finishAll());
    expect(await within(form).findByLabelText("등록 경고")).toBeTruthy();
    expect(within(within(form).getByLabelText("등록 경고")).getByText("추출 조건이 지정되어 폴더의 parameters.json 범위를 쓰지 않았습니다")).toBeTruthy();
  });

  it("실패한 작업: GEOM_EXTRACT_EMPTY — 조건을 넓히라는 안내 문구", async () => {
    const { form, toNative } = await openNativeForm((s) => {
      s.jobs.push(baseJob({
        id: "j-empty", study_id: "s-cushion", project_id: "p-cushion", study_title: "x", job_type: "PARAM_SET_NATIVE", state: "FAILED", created_at: new Date().toISOString(),
        failure_code: "GEOM_EXTRACT_EMPTY", failure_message: "조건에 맞는 피처가 없습니다 — 찾을 종류·조건을 넓혀 보세요", params: { mode: "new" },
      }));
    });
    toNative();
    await waitFor(() => expect(within(form).getByText(/GEOM_EXTRACT_EMPTY — 조건에 맞는 피처가 없습니다 — 찾을 종류·조건을 넓혀 보세요/)).toBeTruthy());
  });
});

describe("목 라우트 계약", () => {
  it("normalizeFilter: 미선택 그룹 조건 제거·그룹 순서, 오류 problems 키", () => {
    const n = normalizeFilter({ groups: ["fillet", "thickness"], conditions: { thickness_mm: { min: 2 }, fillet_radius_min_mm: 1, height_mm: { min: 1, max: 2 } } });
    expect(n.norm).toEqual({ groups: ["thickness", "fillet"], conditions: { thickness_mm: { min: 2, max: null }, fillet_radius_min_mm: 1 }, draft_max_deg: null });
    expect(normalizeFilter({ groups: [], conditions: {} }).problems).toEqual([{ key: "groups", message: "찾을 종류를 하나 이상 고르세요" }]);
    expect(normalizeFilter({ groups: ["fillet"], conditions: { fillet_radius_min_mm: 0 }, draft_max_deg: 50 }).problems.map((p) => p.key)).toEqual(["conditions.fillet_radius_min_mm", "draft_max_deg"]);
  });

  it("altair 요청의 extract_filter = 422 EXTRACT_FILTER_UNSUPPORTED(①-1·④), native-prepare의 extract_filter = 422", async () => {
    const { server } = renderApp(`${STUDY}/1`, { user: "power", geometry: "native" });
    await screen.findByRole("region", { name: "CAD 파라미터 추출" });
    const a = server.handle("POST", "/studies/s-cushion/jobs", new URLSearchParams(), { job_type: "TD_EXTRACT_PARAMS", params: { cad_path: "E:/x.prt", extract_filter: SAVED } }, new Headers({ "X-PhysicsAI-Request": "1" }));
    expect(a.status).toBe(422);
    expect((a.body as { detail: { code: string } }).detail.code).toBe("EXTRACT_FILTER_UNSUPPORTED");
    const b = server.handle("POST", "/studies/s-cushion/param-sets", new URLSearchParams(), { path: `${ROOT}/p`, extract_filter: SAVED }, new Headers({ "X-PhysicsAI-Request": "1" }));
    expect((b.body as { detail: { code: string } }).detail.code).toBe("EXTRACT_FILTER_UNSUPPORTED");
    const c = server.handle("POST", "/param-sets/ps-n1/native-prepare", new URLSearchParams(), { extract_filter: SAVED }, new Headers({ "X-PhysicsAI-Request": "1" }));
    expect((c.body as { detail: { code: string } }).detail.code).toBe("EXTRACT_FILTER_INVALID");
  });
});
