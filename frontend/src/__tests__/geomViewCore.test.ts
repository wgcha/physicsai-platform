// 형상 3D 뷰 순수 로직(geometry-view.md §4.2·§7): 면 ↔ 행 매핑, 선택 전이, 치수선 데이터 변환, 슬라이더 범위, 실패 표시,
// 면 그룹(하이라이트 = tri 구간), WebGL 확인, 410 재요청. three 미적재. 목 GLB(_FACE_ID ↔ faces[].tri) 정합도 확인.
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "../api";
import { buildFaceRows, detectWebGL, dimDraw, dimText, dispMax, failureBadge, failureHighlight, faceGroups, faceKey, faceNo, hasRow3d, outsideFeasible, parameterRows, previewPhase, previewValues, paintFixedMat, paintMovingMat, rowHighlight, SELECTION_COLORS, selectionColor, lightColor, sliderSpec, type PreviewManifest, type ViewManifest } from "../stages/stage4/geomview/viewerCore";
import { chooseRow, clickRow, NO_SELECTION, pickFace } from "../stages/stage4/geomview/selection";
import { isExpired, withReRequest } from "../stages/stage4/geomview/expire";
import { cushionFeatures, cushionGlb, NOMINAL, previewManifest, previewOutcome, viewManifest } from "../mock/geomViewData";
import { readGlb } from "../mock/glb";
import type { GeomPreview } from "../api/types";

const nominal = (): ViewManifest => {
  const g = cushionGlb(NOMINAL, false);
  return viewManifest(g.bodies, g.glb.byteLength);
};

describe("면 ↔ 행 매핑", () => {
  it("face id 문자열·키", () => {
    expect(faceNo("F12")).toBe(12);
    expect(Number.isNaN(faceNo("E3"))).toBe(true);
    expect(faceKey("CUSH_L", "F2")).toBe("CUSH_L#2");
    expect(faceKey("CUSH_L", 2)).toBe("CUSH_L#2");
  });

  it("행 = parameter(그룹 대표), 면 → 그 면을 쓰는 행들(이동·고정)", () => {
    const m = nominal();
    expect(parameterRows(m)).toEqual(["CUSH_L_THK_1", "CUSH_L_POCKET_D_1", "CUSH_L_RIB_T_2", "CUSH_L_HOLE_U_1", "CUSH_L_FILLET_R_1"]);
    const rows = buildFaceRows(m);
    expect(rows.get("CUSH_L#2")).toEqual(["CUSH_L_THK_1", "CUSH_L_POCKET_D_1"]); // 두께 이동 면 = 포켓 고정 면
    expect(rows.get("CUSH_R#2")).toEqual(["CUSH_L_THK_1"]); // 대칭 구성원은 대표 행
    expect(rows.get("CUSH_L#12")).toEqual(["CUSH_L_HOLE_U_1"]);
    expect(rows.get("CUSH_L#4")).toBeUndefined(); // 피처 없는 면
  });

  it("행 선택 → 대칭 그룹 구성원 면 전부 하이라이트(이동 주황 > 고정 파랑) + 치수선", () => {
    const h = rowHighlight(nominal(), "CUSH_L_THK_1");
    expect([...h.moving].sort()).toEqual(["CUSH_L#2", "CUSH_R#2"]);
    expect([...h.fixed].sort()).toEqual(["CUSH_L#1", "CUSH_R#1"]);
    expect(h.dims.map((d) => d.text)).toEqual(["12.5 mm", "12.5 mm"]);
    expect(rowHighlight(nominal(), null).moving.size).toBe(0);
    const m = nominal();
    m.features.push({ ...m.features[2], name: "X", parameter: "X", faces: { moving: ["F2"], fixed: ["F2"] } });
    const x = rowHighlight(m, "X");
    expect(x.moving.has("CUSH_L#2") && !x.fixed.has("CUSH_L#2")).toBe(true);
  });

  it("3D 대응 없음: manifest에 없는 행(쉘 두께 PROP)", () => {
    expect(hasRow3d(nominal(), "CUSH_L_HOLE_U_1")).toBe(true);
    expect(hasRow3d(nominal(), "BOX_SHELL_T")).toBe(false);
  });
});

describe("선택 전이(표 ↔ 3D, 다중)", () => {
  const rows = buildFaceRows(nominal());
  const order = ["A", "B", "C", "D", "E"];
  it("행 클릭: 단일 선택, 같은 행 다시 = 해제, 다른 행 = 교체", () => {
    const s = clickRow(NO_SELECTION, order, "A");
    expect(s).toEqual({ rows: ["A"], anchor: "A" });
    expect(clickRow(s, order, "A")).toEqual(NO_SELECTION);
    expect(clickRow(s, order, "C").rows).toEqual(["C"]);
  });
  it("Ctrl/⌘+클릭: 토글 추가(선택 순서 유지), 다중 중 한 행 일반 클릭 = 그 행만", () => {
    let s = clickRow(NO_SELECTION, order, "A");
    s = clickRow(s, order, "C", { ctrl: true });
    s = clickRow(s, order, "B", { ctrl: true });
    expect(s.rows).toEqual(["A", "C", "B"]);
    expect(clickRow(s, order, "C", { ctrl: true }).rows).toEqual(["A", "B"]);
    expect(clickRow(s, order, "C").rows).toEqual(["C"]);
  });
  it("Shift+클릭: 기준 행~클릭 행 범위(역방향 포함), Ctrl+Shift = 기존에 합침, 기준 없으면 추가", () => {
    const s = clickRow(NO_SELECTION, order, "B");
    expect(clickRow(s, order, "D", { shift: true }).rows).toEqual(["B", "C", "D"]);
    expect(clickRow(s, order, "A", { shift: true }).rows).toEqual(["B", "A"]);
    const t = clickRow(clickRow(s, order, "E", { ctrl: true }), order, "C", { shift: true });
    expect(t.rows).toEqual(["E", "D", "C"]); // Ctrl로 추가한 E가 새 기준 → E~C 범위
    expect(clickRow(clickRow(s, order, "D", { shift: true }), order, "A", { shift: true, ctrl: true }).rows).toEqual(["B", "C", "D", "A"]);
    expect(clickRow(NO_SELECTION, order, "C", { shift: true }).rows).toEqual(["C"]);
  });
  it("면 클릭: 1개 → 그 행, Ctrl → 토글 추가, 여럿 → 선택 목록(이미 선택된 행이 있으면 그 행 유지), 피처 없는 면 → 해제(Ctrl이면 유지)", () => {
    expect(pickFace([], rows, { body: "CUSH_L", face: 12 })).toEqual({ kind: "set", rows: ["CUSH_L_HOLE_U_1"], focus: "CUSH_L_HOLE_U_1" });
    expect(pickFace(["CUSH_L_THK_1"], rows, { body: "CUSH_L", face: 12 }, true)).toEqual({ kind: "set", rows: ["CUSH_L_THK_1", "CUSH_L_HOLE_U_1"], focus: "CUSH_L_HOLE_U_1" });
    expect(pickFace(["CUSH_L_HOLE_U_1"], rows, { body: "CUSH_L", face: 12 }, true)).toEqual({ kind: "set", rows: [], focus: null });
    expect(pickFace([], rows, { body: "CUSH_L", face: 2 })).toEqual({ kind: "choices", choices: ["CUSH_L_THK_1", "CUSH_L_POCKET_D_1"] });
    expect(pickFace(["CUSH_L_THK_1", "X"], rows, { body: "CUSH_L", face: 2 })).toEqual({ kind: "set", rows: ["CUSH_L_THK_1"], focus: "CUSH_L_THK_1" });
    expect(pickFace(["X"], rows, { body: "CUSH_L", face: 4 })).toEqual({ kind: "set", rows: [], focus: null });
    expect(pickFace(["X"], rows, { body: "CUSH_L", face: 4 }, true)).toEqual({ kind: "set", rows: ["X"], focus: null });
    expect(pickFace(["X"], rows, null)).toEqual({ kind: "set", rows: [], focus: null });
    expect(chooseRow(["a"], "b")).toEqual(["b"]);
    expect(chooseRow(["a"], "b", true)).toEqual(["a", "b"]);
  });
});

describe("다중 선택 하이라이트(색 팔레트·치수선)", () => {
  it("팔레트 8색 순환, 고정색 = 같은 색을 옅게", () => {
    expect(SELECTION_COLORS).toHaveLength(8);
    expect(new Set(SELECTION_COLORS).size).toBe(8);
    expect(selectionColor(0)).toBe(selectionColor(8));
    expect(selectionColor(9)).toBe(SELECTION_COLORS[1]);
    expect(paintMovingMat(8)).toBe(paintMovingMat(0));
    expect(paintFixedMat(0)).toBe(paintMovingMat(0) + 8);
    expect(lightColor("#000000", 0.5)).toBe("#808080");
    expect(lightColor("#f08c28")).not.toBe("#f08c28");
  });
  it("행마다 다른 색: 이동 면 = 그 색, 고정 면 = 옅은 색, 이동 우선·먼저 선택한 행 우선", () => {
    const m = nominal();
    const h = rowHighlight(m, ["CUSH_L_THK_1", "CUSH_L_HOLE_U_1"]);
    expect(h.paint!.get("CUSH_L#2")).toBe(paintMovingMat(0));
    expect(h.paint!.get("CUSH_R#2")).toBe(paintMovingMat(0));
    expect(h.paint!.get("CUSH_L#1")).toBe(paintFixedMat(0));
    const hole = m.features.find((f) => f.parameter === "CUSH_L_HOLE_U_1")!;
    for (const id of hole.faces.moving) expect(h.paint!.get(faceKey(hole.body, id))).toBe(paintMovingMat(1));
    // 같은 면을 한 행은 이동·다른 행은 고정으로 쓰면 이동 색
    const m2 = nominal();
    m2.features.push({ ...m2.features[2], name: "X", parameter: "X", faces: { moving: ["F1"], fixed: [] } });
    const x = rowHighlight(m2, ["CUSH_L_THK_1", "X"]);
    expect(x.paint!.get("CUSH_L#1")).toBe(paintMovingMat(1));
    expect(x.moving.has("CUSH_L#1") && !x.fixed.has("CUSH_L#1")).toBe(true);
  });
  it("치수선: 선택 1개일 때만(다중·호버만 = 생략), 호버 행은 다음 색으로 임시 표시", () => {
    const m = nominal();
    expect(rowHighlight(m, ["CUSH_L_THK_1"]).dims.map((d) => d.text)).toEqual(["12.5 mm", "12.5 mm"]);
    expect(rowHighlight(m, ["CUSH_L_THK_1", "CUSH_L_HOLE_U_1"]).dims).toEqual([]);
    expect(rowHighlight(m, [], "CUSH_L_THK_1").dims).toEqual([]);
    const hv = rowHighlight(m, ["CUSH_L_THK_1"], "CUSH_L_HOLE_U_1");
    expect(hv.dims).toHaveLength(2); // 선택 1개의 치수선은 유지
    expect([...hv.paint!.values()]).toContain(paintMovingMat(1));
    expect(rowHighlight(m, [], null)).toBe(rowHighlight(m, null));
    const h = rowHighlight(m, ["CUSH_L_THK_1", "CUSH_L_HOLE_U_1"]);
    const g = faceGroups(m.bodies[0], h);
    expect(g.some((x) => x.mat === paintMovingMat(1))).toBe(true);
  });
});

describe("치수선 데이터 변환", () => {
  it("라벨: 선형·위치 'v mm', 반경 'R v mm'(값 = dimension.value, 소수 4자리)", () => {
    expect(dimText({ kind: "linear", p0: [0, 0, 0], p1: [0, 0, 1], label: [0, 0, 0], value: 12.5, unit: "mm" })).toBe("12.5 mm");
    expect(dimText({ kind: "radius", p0: [0, 0, 0], p1: [0, 0, 1], label: [0, 0, 0], value: 2, unit: "mm" })).toBe("R 2 mm");
    expect(dimText({ kind: "position", p0: [0, 0, 0], p1: [0, 0, 1], label: [0, 0, 0], value: 30.123456, unit: "mm" })).toBe("30.1235 mm");
  });
  it("선 = p0–p1, 라벨 위치 없으면 중점, 비유한 점은 그리지 않음", () => {
    const d = dimDraw({ kind: "linear", p0: [0, 0, 0], p1: [0, 0, 10], label: null as unknown as [number, number, number], value: 10, unit: "mm" })!;
    expect(d.line).toEqual([
      [0, 0, 0],
      [0, 0, 10],
    ]);
    expect(d.label).toEqual([0, 0, 5]);
    expect(dimDraw({ kind: "linear", p0: [0, NaN, 0], p1: [0, 0, 1], label: [0, 0, 0], value: 1, unit: "mm" })).toBeNull();
    expect(dimDraw(null)).toBeNull();
  });
  it("미리보기 manifest 치수 = 입력 값", () => {
    const out = previewOutcome({ CUSH_L_THK_1: 14 });
    const pm = previewManifest({ CUSH_L_THK_1: 14 }, out, cushionGlb((out as { params: typeof NOMINAL }).params, true));
    expect(rowHighlight(pm, "CUSH_L_THK_1").dims[0].text).toBe("14 mm");
  });
});

describe("미리보기 입력·결과", () => {
  const f = cushionFeatures(NOMINAL);
  it("슬라이더 범위 = feasible(envelope/추정), 띠 = 표 사용자 범위 우선, feasible 없으면 range", () => {
    expect(sliderSpec(f[0], { min: 12, max: 13 })).toMatchObject({ min: 6.2, max: 18, source: "envelope", sourceText: "envelope 측정", band: { min: 12, max: 13 } });
    expect(sliderSpec(f[2])).toMatchObject({ min: 4, max: 11, sourceText: "추정", band: { min: 7.6, max: 8.4 } });
    expect(sliderSpec(f[5])).toMatchObject({ min: 1.9, max: 2.1, source: "range" });
    expect(sliderSpec(f[0])!.step).toBeGreaterThan(0);
    expect(outsideFeasible(f[0], 18.5)).toBe(true);
    expect(outsideFeasible(f[0], 12)).toBe(false);
  });
  it("요청 값 = 공칭과 다른 것만", () => {
    expect(previewValues(nominal(), { CUSH_L_THK_1: 12.5, CUSH_L_HOLE_U_1: 33, BAD: NaN })).toEqual({ CUSH_L_HOLE_U_1: 33 });
  });
  it("상태 전이: 없음 → 실행 → 결과 OK/FAIL, 작업 실패·만료", () => {
    const p = (x: Partial<GeomPreview>) => ({ id: "g", param_set_id: "p", values: {}, status: "QUEUED", ...x }) as GeomPreview;
    expect(previewPhase(null)).toBe("idle");
    expect(previewPhase(p({ status: "QUEUED" }))).toBe("running");
    expect(previewPhase(p({ status: "RUNNING" }))).toBe("running");
    expect(previewPhase(p({ status: "DONE", result_status: "OK" }))).toBe("ok");
    expect(previewPhase(p({ status: "DONE", result_status: "FAIL" }))).toBe("fail");
    expect(previewPhase(p({ status: "FAILED" }))).toBe("error");
    expect(previewPhase(p({ status: "EXPIRED" }))).toBe("expired");
  });
  it("실패 배지(category 우선, 코드로 추정) · 실패 피처 면 빨강 · 변위 범위", () => {
    expect(failureBadge("CAD_FAILED", "GEOM_FEATURE_COLLISION")).toBe("CAD 생성 불가");
    expect(failureBadge(null, "GEOM_FEATURE_COLLISION")).toBe("충돌");
    expect(failureBadge(null, "GEOM_QUALITY")).toBe("품질 미달");
    expect(failureBadge("FIXED", "SHELL_FIXED_REGION_VIOLATION")).toBe("고정 영역 침범");
    expect(failureBadge(null, "VIEW_TOO_LARGE")).toBe("3D 변환 실패");
    const out = previewOutcome({ CUSH_L_HOLE_U_1: 45 });
    expect(out.ok).toBe(false);
    const pm = previewManifest({ CUSH_L_HOLE_U_1: 45 }, out, null);
    const fh = failureHighlight({ ...pm, failure: { ...pm.failure, clusters: [3], points: [{ xyz: [1, 2, 3], label: "최악" }] } } as PreviewManifest);
    expect([...fh.red].sort()).toEqual(["CUSH_L#12", "CUSH_L#3", "CUSH_L#8", "CUSH_L#9"]);
    expect([...fh.clusters]).toEqual(["3"]);
    expect(fh.points).toEqual([{ xyz: [1, 2, 3], label: "최악" }]);
    expect(failureHighlight(null).red.size).toBe(0);
    expect(dispMax({ disp: { max_mm: 1.5 }, fe: { mode: "check", max_disp_mm: 0.4 } } as PreviewManifest, false)).toBe(1.5);
    expect(dispMax({ disp: { max_mm: 1.5 }, fe: { mode: "check", max_disp_mm: 0.4 } } as PreviewManifest, true)).toBe(0.4);
  });
});

describe("하이라이트 그룹(faces[].tri 구간)", () => {
  it("선택 없음 = 한 그룹, 선택 = 이동·고정·흐림 구간(같은 재질 연속 면 병합)", () => {
    const m = nominal();
    const body = m.bodies[0];
    const total = body.faces.reduce((a, f) => a + f.tri[1], 0) * 3;
    expect(faceGroups(body, rowHighlight(m, null))).toEqual([{ start: 0, count: total, mat: 0 }]);
    const g = faceGroups(body, rowHighlight(m, "CUSH_L_THK_1"));
    expect(g.map((x) => x.mat)).toEqual([2, 1, 4]); // F1 고정 · F2 이동 · 나머지 흐림
    expect(g.reduce((a, x) => a + x.count, 0)).toBe(total);
    expect(g[1].start).toBe(body.faces[1].tri[0] * 3);
  });

  it("목 GLB: _FACE_ID 오름차순 연속 = faces[].tri, 면 사이 정점 비공유", () => {
    const g = cushionGlb(NOMINAL, true);
    const { json, bin } = readGlb(g.glb);
    const j = json as { accessors: { bufferView: number; count: number; componentType: number }[]; bufferViews: { byteOffset: number; byteStride?: number }[]; meshes: { primitives: { attributes: Record<string, number> }[] }[] };
    const acc = j.accessors[j.meshes[0].primitives[0].attributes._FACE_ID];
    expect(acc.componentType).toBe(5123);
    const bv = j.bufferViews[acc.bufferView];
    const dv = new DataView(bin.buffer, bin.byteOffset + bv.byteOffset);
    const ids = Array.from({ length: acc.count }, (_, i) => dv.getUint16(i * (bv.byteStride ?? 2), true));
    for (const f of g.bodies[0].faces) {
      const k = faceNo(f.id);
      const slice = ids.slice(f.tri[0] * 3, (f.tri[0] + f.tri[1]) * 3);
      expect(slice.length).toBe(f.tri[1] * 3);
      expect(slice.every((x) => x === k)).toBe(true);
    }
    expect(ids).toEqual([...ids].sort((a, b) => a - b));
    expect(g.maxDisp).toBe(0); // 공칭값 미리보기 = 변위 0
    expect(g.glb.byteLength).toBeLessThan(100 * 1024);
  });
});

describe("WebGL 확인·410 재요청", () => {
  it("WebGL2 → WebGL1 시도, 둘 다 없으면 false", () => {
    const doc = (ctx: Record<string, unknown>) => ({ createElement: () => ({ getContext: (k: string) => ctx[k] ?? null }) }) as unknown as Document;
    expect(detectWebGL(doc({ webgl2: {} }))).toBe(true);
    expect(detectWebGL(doc({ webgl: {} }))).toBe(true);
    expect(detectWebGL(doc({}))).toBe(false);
    expect(detectWebGL({ createElement: () => { throw new Error("x"); } } as unknown as Document)).toBe(false);
  });
  it("410 ARTIFACT_EXPIRED면 다시 요청 후 1회 재시도, 그 밖 오류는 그대로", async () => {
    const gone = new ApiError(410, { code: "ARTIFACT_EXPIRED", message: "정리됨" });
    expect(isExpired(gone)).toBe(true);
    expect(isExpired(new ApiError(404, { code: "NOT_FOUND", message: "" }))).toBe(false);
    const load = vi.fn().mockRejectedValueOnce(gone).mockResolvedValueOnce("ok");
    const again = vi.fn(async () => undefined);
    await expect(withReRequest(load, again)).resolves.toBe("ok");
    expect(again).toHaveBeenCalledTimes(1);
    const always = vi.fn().mockRejectedValue(gone);
    await expect(withReRequest(always, again)).rejects.toBe(gone);
    expect(always).toHaveBeenCalledTimes(2);
    const other = vi.fn().mockRejectedValue(new Error("boom"));
    await expect(withReRequest(other, again)).rejects.toThrow("boom");
    expect(other).toHaveBeenCalledTimes(1);
  });
});
