// rib-gap.md §8·V-RG-9(화면): 추출 조건 그룹 "리브 간격(피치)"(체크·도움말·프리셋), 종류 표시명·mm 범위 판정(위치형 아님), 변수 표 툴팁(열·가운데 리브·빈 간격)·Δ,
// 경고 문구 매핑(RIB_PITCH_JOINT_RANGE·RIB_PITCH_MIN), 3D 피치 치수선(linear 재사용)·바깥쪽 리브 하이라이트.
import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { renderApp, STUDY } from "../test/render";
import type { MockServer } from "../mock/server";
import { EXCLUDED_LABEL, EXTRACT_GROUPS, RIB_PITCH_HELP, filterText, fromFilter, presetForm, summaryView, toFilter } from "../lib/extractFilter";
import { GEOM_ERROR_TEXT, PITCH_TIP, geomErrorText, isAbsRangeType, isPitchType, isPositionType, pitchTip, rangeText, typeLabel } from "../lib/geometry";
import { NOTE_TEXT, deltaText, noteText } from "../lib/nativeVars";
import { RIB_ROWS, nativeTrainParams, ribFeatures } from "../mock/geometry";
import { mockSummary, normalizeFilter } from "../mock/extractFilter";
import { NOMINAL, cushionFeatures, viewManifest, cushionGlb } from "../mock/geomViewData";
import { buildFaceRows, dimText, rowHighlight } from "../stages/stage4/geomview/viewerCore";
import { resetWebGLCache } from "../stages/stage4/geomview/webgl";
import type { ExtractFilter } from "../api/types";

type Fn = ReturnType<typeof vi.fn>;
const fake = vi.hoisted(() => ({ geom: null as { setHighlight: Fn; setNominal: Fn; [k: string]: Fn } | null }));
vi.mock("../stages/stage4/geomview/threeScene", () => ({
  createGeomScene: () => {
    fake.geom = { setNominal: vi.fn(async () => undefined), setOverlay: vi.fn(async () => undefined), setHighlight: vi.fn(), setBodyVisible: vi.fn(), setFixed: vi.fn(), setPoints: vi.fn(), fit: vi.fn(), dispose: vi.fn() };
    return fake.geom;
  },
  createContourScene: vi.fn(),
}));

const ALL6 = ["thickness", "height", "position", "rib_pitch", "hole_radius", "fillet"] as const;
const FILTER6: ExtractFilter = { groups: [...ALL6], conditions: {}, draft_max_deg: null };

describe("lib — 그룹·표시명·판정", () => {
  it("그룹 6개: 위치 바로 뒤에 '리브 간격(피치)', 도움말은 이 그룹만", () => {
    expect(EXTRACT_GROUPS.map((g) => g.key)).toEqual([...ALL6]);
    expect(EXTRACT_GROUPS[3]).toMatchObject({ key: "rib_pitch", label: "리브 간격(피치)", help: RIB_PITCH_HELP });
    expect(EXTRACT_GROUPS.filter((g) => g.help)).toHaveLength(1);
    expect(RIB_PITCH_HELP).toContain("가운데 리브");
    expect(RIB_PITCH_HELP).toContain("벽에 붙은 리브·격자는 대상이 아닙니다");
  });
  it("프리셋 = 6개 모두 체크, 저장된 조건에 키가 없으면 미체크, 요청·문구에 반영", () => {
    expect(presetForm().groups).toEqual([...ALL6]);
    const old = fromFilter({ groups: ["thickness", "position"], conditions: {}, draft_max_deg: null });
    expect(old.groups).toEqual(["thickness", "position"]);
    expect(toFilter({ groups: ["position", "rib_pitch"], v: {} }).groups).toEqual(["position", "rib_pitch"]);
    expect(filterText({ groups: ["thickness", "position"], conditions: {}, draft_max_deg: null })).toBe("조건 없음 · 제외: 높이·깊이, 리브 간격(피치), 구멍 반경, 필렛");
    expect(filterText(FILTER6)).toBe("전체 종류(조건 없음)");
  });
  it("종류 표시명·위치형 아님·절대 mm 범위·범위 문구(−a / +b)", () => {
    expect(typeLabel("RIB_PITCH_U")).toBe("리브 피치 U");
    expect(typeLabel("RIB_PITCH_V")).toBe("리브 피치 V");
    expect(isPositionType("RIB_PITCH_U")).toBe(false);
    expect(isPitchType("RIB_PITCH_V")).toBe(true);
    expect(isPitchType("RIB_POS_U")).toBe(false);
    expect(isAbsRangeType("RIB_PITCH_U") && isAbsRangeType("HOLE_POS_V")).toBe(true);
    expect(isAbsRangeType("THICKNESS")).toBe(false);
    expect(rangeText(20, 15, 25, "RIB_PITCH_U")).toBe("15 ~ 25 (−5 / +5 mm)");
    expect(rangeText(20, 17, 25, "RIB_PITCH_U")).toBe("17 ~ 25 (−3 / +5 mm)"); // 하한이 빈 간격으로 올라간 비대칭
    expect(rangeText(51.5, 46.5, 56.5, "RIB_POS_U")).toBe("46.5 ~ 56.5 (∓5 mm)");
  });
  it("툴팁: 열·피치 k/(n−1)·고정 리브·빈 간격 + 고정 문구, 짝수 열은 중점, 열 정보가 없으면 고정 문구만", () => {
    expect(PITCH_TIP).toBe("리브 간격 = 이웃 리브 중심 사이 거리(피치). 두께를 함께 바꾸면 빈 간격이 줄어듭니다.");
    const f = ribFeatures()[0];
    expect(pitchTip(f, RIB_ROWS)).toBe(`열 U1 · 피치 1/2 · 가운데 리브 2 고정 · 빈 간격 17.0 mm\n${PITCH_TIP}`);
    const five = { type: "RIB_PITCH_U", nominal: 20, row: { id: "U2", k: 2, n: 5 } };
    const r5 = [{ id: "U2", anchor: "rib:3", ribs: [1, 2, 3, 4, 5].map((i) => ({ index: i, thickness: i === 2 ? 4 : 6, center: i * 20 })) }];
    expect(pitchTip(five, r5)).toBe(`열 U2 · 피치 2/4 · 가운데 리브 3 고정 · 빈 간격 15.0 mm\n${PITCH_TIP}`); // 20 − (4+6)/2
    expect(pitchTip({ type: "RIB_PITCH_U", nominal: 20, row: { id: "U3", k: 2, n: 4 } }, [{ id: "U3", anchor: "mid:2", ribs: [] }])).toBe(`열 U3 · 피치 2/3 · 가운데 리브 2·3 중점 고정\n${PITCH_TIP}`);
    expect(pitchTip({ type: "RIB_PITCH_U", nominal: 20 }, null)).toBe(PITCH_TIP);
    expect(pitchTip({ type: "THICKNESS", nominal: 3, row: { id: "U1", k: 1, n: 3 } }, RIB_ROWS)).toBe(PITCH_TIP);
  });
  it("Δ(공칭 대비)는 피치 행에도 표시(좌표 아님), 경고 문구 매핑", () => {
    expect(deltaText({ nominal: 20, lo: "15", hi: "25", position: false, fixed: false, type: "RIB_PITCH_U" })).toBe("−5 / +5");
    expect(deltaText({ nominal: 20, lo: "15", hi: "25", position: false, fixed: false, type: "THICKNESS" })).toBeNull();
    expect(NOTE_TEXT.RIB_PITCH_JOINT_RANGE).toContain("샘플이 형상 생성에 실패할 수 있습니다");
    expect(NOTE_TEXT.RIB_PITCH_MIN).toContain("빈 간격이 최소 간격보다 작습니다");
    expect(noteText({ code: "RIB_PITCH_JOINT_RANGE", message: "same row warning" })).toBe(NOTE_TEXT.RIB_PITCH_JOINT_RANGE);
    expect(noteText({ code: "RIB_PITCH_JOINT_RANGE", message: "같은 리브 열(U1)의 +쪽 피치 상한 합이 끝 여유 18.0 mm를 넘습니다" })).toContain("U1");
    expect(geomErrorText("RIB_PITCH_MIN", "min gap")).toBe(GEOM_ERROR_TEXT.RIB_PITCH_MIN);
  });
  it("추출 요약: 피치 종류 행·제외 사유(기둥형·이웃 없음·간격 열 소속)", () => {
    expect(EXCLUDED_LABEL).toMatchObject({ not_slender: "기둥형", row_branch: "열 분기", row_single: "이웃 없음", row_member: "간격 열 소속" });
    const v = summaryView(mockSummary([], FILTER6))!;
    const r = v.rows.find((x) => x.type === "RIB_PITCH_U")!;
    expect(r.label).toBe("리브 피치 U");
    expect(r.reasons.map((x) => x.label)).toEqual(["기둥형", "이웃 없음"]);
    expect(v.rows.map((x) => x.type).indexOf("RIB_PITCH_U")).toBeGreaterThan(v.rows.map((x) => x.type).indexOf("RIB_POS_V"));
  });
  it("목 정규화: rib_pitch 그룹 허용·순서·중복·알 수 없는 값 거부", () => {
    expect(normalizeFilter({ groups: ["rib_pitch", "thickness"], conditions: {} }).norm?.groups).toEqual(["thickness", "rib_pitch"]);
    expect(normalizeFilter({ groups: ["rib_row"], conditions: {} }).problems).toHaveLength(1);
  });
});

describe("3D: 피치 치수선(linear 재사용)·바깥쪽 리브 하이라이트", () => {
  it("치수선 = 값 mm, 표 행 선택 → 이동 면(바깥쪽 리브)·고정 면(밑면), 면 → 행", () => {
    const g = cushionGlb(NOMINAL, false);
    const m = viewManifest(g.bodies, g.glb.byteLength, true);
    expect(cushionFeatures(NOMINAL).some((f) => f.type === "RIB_PITCH_U")).toBe(false); // 피치를 고르지 않으면 기존 형상 그대로
    const h = rowHighlight(m, "CUSH_L_RIB_PITCH_U_1");
    expect(h.dims.map((d) => d.text)).toEqual(["20 mm"]);
    expect([...h.moving].sort()).toEqual(["CUSH_L#7", "CUSH_L#8"]);
    expect([...h.fixed]).toEqual(["CUSH_L#1"]);
    const f = m.features.find((x) => x.name === "CUSH_L_RIB_PITCH_U_1")!;
    expect(f.dimension!.kind).toBe("linear");
    expect(dimText(f.dimension!)).toBe("20 mm");
    expect(buildFaceRows(m).get("CUSH_L#8")).toContain("CUSH_L_RIB_PITCH_U_1");
  });
});

// ---------------------------------------------------------------- 화면

const nativeCurrent = (s: MockServer) => {
  s.paramSets.forEach((p) => (p.is_current = p.id === "ps-n1"));
  const ps = s.paramSets.find((p) => p.id === "ps-n1")!;
  Object.assign(ps.native!, { extract_filter: FILTER6 });
  const rec = s.geom.get("ps-n1")!;
  rec.features.push(...ribFeatures());
  rec.ribRows = RIB_ROWS;
};

describe("①-1 추출 조건 체크박스", () => {
  afterEach(() => vi.restoreAllMocks());
  it("'리브 간격(피치)'는 위치 바로 뒤·구멍 반경 앞, ⓘ 도움말, 체크 해제 → 요청 groups에서 빠짐", async () => {
    renderApp(`${STUDY}/1`, { user: "power", geometry: "native", geometryDefault: "native" }, (s) => Object.assign(s.p2.setups["s-cushion"], { parameters: [], used_count: 0, cad: null, tpl: null }));
    const card = await screen.findByRole("region", { name: "CAD 파라미터 추출" });
    const names = within(within(card).getByRole("group", { name: "찾을 종류" })).getAllByRole("checkbox").map((c) => c.closest("label")!.textContent);
    expect(names).toEqual(["두께", "높이·깊이", "위치(구멍·리브)", "리브 간격(피치)", "구멍 반경", "필렛"]);
    expect(within(card).getByTestId("help-rib_pitch").getAttribute("title")).toBe(RIB_PITCH_HELP);
    const box = within(card).getByRole("checkbox", { name: "리브 간격(피치)" }) as HTMLInputElement;
    expect(box.checked).toBe(true);
    fireEvent.click(box);
    expect(box.checked).toBe(false);
    expect(toFilter(fromFilter({ groups: ["thickness"], conditions: {}, draft_max_deg: null })).groups).not.toContain("rib_pitch");
  });
});

describe("①-2 변수 표(Native 추출)", () => {
  afterEach(() => vi.restoreAllMocks());
  it("피치 행: 표시명·'mm 범위'·툴팁(열 U1·피치 1/2·가운데 리브 2 고정·빈 간격 17.0 mm)", async () => {
    renderApp(`${STUDY}/1`, { user: "power" }, (s) => Object.assign(s.p2.setups["s-cushion"], { engine: "native", parameters: nativeTrainParams(true), tpl: null, extract_filter: FILTER6 }));
    const card = await screen.findByRole("region", { name: "파라미터 표" });
    const row = (await within(card).findByText("CUSH_L_RIB_PITCH_U_1")).closest("tr")!;
    await waitFor(() => expect(row.querySelectorAll("td")[2].textContent).toContain("리브 피치 U"));
    const cell = row.querySelectorAll("td")[2];
    expect(cell.textContent).toContain("mm 범위");
    expect(cell.getAttribute("title")).toBe(`열 U1 · 피치 1/2 · 가운데 리브 2 고정 · 빈 간격 17.0 mm\n${PITCH_TIP}`);
    // 위치형 행은 그대로(툴팁 없음)
    const pos = within(card).getByText("CUSH_L_HOLE_U_1").closest("tr")!;
    expect(pos.querySelectorAll("td")[2].getAttribute("title")).toBeNull();
    expect(pos.querySelectorAll("td")[2].textContent).toContain("mm 범위");
  });
});

describe("④ 세트 상세 변수 표", () => {
  afterEach(() => vi.restoreAllMocks());
  const openDetail = async () => {
    fireEvent.click(await screen.findByRole("button", { name: "템플릿 관리" }));
    const card = await screen.findByRole("region", { name: "템플릿 관리" });
    const table = await within(card).findByRole("table", { name: "형상 피처 표" });
    return { card, table };
  };
  it("피치 행: 종류 칸 툴팁·Δ(mm)·절대 범위 문구, 두 피치 상한을 함께 키우면 RIB_PITCH_JOINT_RANGE 경고(저장은 허용)", async () => {
    renderApp(`${STUDY}/4`, { user: "power", geometry: "native" }, nativeCurrent);
    const { card, table } = await openDetail();
    const row = within(table).getByText("CUSH_L_RIB_PITCH_U_2").closest("tr")!;
    const type = row.querySelectorAll("td")[2];
    expect(type.textContent).toContain("리브 피치 U");
    expect(type.getAttribute("title")).toBe(`열 U1 · 피치 2/2 · 가운데 리브 2 고정 · 빈 간격 17.0 mm\n${PITCH_TIP}`);
    expect(row.textContent).toContain("7 ~ 31");
    // 사용 체크 → 상한 30으로 키운다(두 피치 +10씩)
    for (const n of ["CUSH_L_RIB_PITCH_U_1", "CUSH_L_RIB_PITCH_U_2"]) {
      fireEvent.click(within(table).getByLabelText(`${n} 사용`));
      fireEvent.change(within(table).getByLabelText(`${n} 상한`), { target: { value: "30" } });
    }
    expect(within(table).getByText("CUSH_L_RIB_PITCH_U_1").closest("tr")!.textContent).toContain("Δ −5 / +10");
    fireEvent.click(within(within(card).getByTestId("vars-head")).getByRole("button", { name: "저장" }));
    const note = await within(card).findByTestId("vars-general-notes");
    expect(note.textContent).toContain("피치 상한 합이 끝 여유");
    expect(note.textContent).toContain("형상 생성에 실패할 수 있습니다");
  });
  it("3D: 피치 행 선택 → 치수선 20 mm + 바깥쪽 리브 면 하이라이트(기존 치수선 재사용)", async () => {
    resetWebGLCache();
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({} as never);
    renderApp(`${STUDY}/4`, { user: "power", geometry: "native" }, nativeCurrent);
    const { table } = await openDetail();
    await waitFor(() => expect(fake.geom?.setNominal).toHaveBeenCalled());
    fireEvent.click(within(table).getByText("CUSH_L_RIB_PITCH_U_1"));
    await waitFor(() => {
      const hl = fake.geom!.setHighlight.mock.calls[fake.geom!.setHighlight.mock.calls.length - 1][0] as { dims: { text: string }[]; moving: Set<string> };
      expect(hl.dims.map((d) => d.text)).toEqual(["20 mm"]);
      expect([...hl.moving].sort()).toEqual(["CUSH_L#7", "CUSH_L#8"]);
    });
  });
});
