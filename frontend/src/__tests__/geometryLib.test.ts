// native 형상 엔진 화면 순수 함수(geometry-engine.md §4.3·§4.9·§6.2·§11.4) + 오류 코드 한국어
import { describe, expect, it } from "vitest";
import { ApiError, errorMessage, type ParamMap } from "../api";
import {
  exceedsFeasible, featureTypeFromName, geomErrorText, getOpt, isSplit, nameConflicts, optProblems, parseOpt, pendingRows, rangeText, setOpt, toggleSplit, GEOM_OPT_FIELDS,
} from "../lib/geometry";
import { validateGeomOptions } from "../mock/geometry";

const field = (k: string) => GEOM_OPT_FIELDS.flatMap((g) => g.fields).find((f) => f.path.join(".") === k)!;

describe("피처 이름·범위(§4.3)", () => {
  it("이름 약어 → 종류(해시 접미·3S 쉘 두께 포함)", () => {
    expect(featureTypeFromName("CUSH_L_THK_1")).toBe("THICKNESS");
    expect(featureTypeFromName("CUSH_L_POCKET_W_2")).toBe("POCKET_WIDTH");
    expect(featureTypeFromName("CUSH_L_HOLE_U_1")).toBe("HOLE_POS_U");
    expect(featureTypeFromName("VERY_LONG_COMP_RIB_H_3_a1b2")).toBe("RIB_HEIGHT");
    expect(featureTypeFromName("BOX_SHELL_T")).toBe("SHELL_T");
    expect(featureTypeFromName("THK_TOP")).toBeNull();
  });

  it("위치형은 공칭 ∓ mm, 치수형은 ±%", () => {
    expect(rangeText(30, 25, 35, "HOLE_POS_U")).toBe("25 ~ 35 (∓5 mm)");
    expect(rangeText(12.5, 11.875, 13.125, "THICKNESS")).toBe("11.875 ~ 13.125 (±5%)");
    expect(rangeText(null, 1, 2, "THICKNESS")).toBe("1 ~ 2");
  });

  it("모핑 가능 범위 초과 판정(경고만)", () => {
    expect(exceedsFeasible(25, 35, { min: 27, max: 40 })).toBe(true);
    expect(exceedsFeasible(28, 35, { min: 27, max: 40 })).toBe(false);
    expect(exceedsFeasible(28, 35, null)).toBe(false);
  });
});

describe("geom_options 편집(§4.9)", () => {
  it("넣기·지우기(기본값으로) — 빈 절은 없앤다", () => {
    let o = setOpt(null, ["quality", "min_edge_ratio"], 0.7);
    o = setOpt(o, ["position_ref"], "proportional");
    expect(o).toEqual({ quality: { min_edge_ratio: 0.7 }, position_ref: "proportional" });
    expect(getOpt(o, ["quality", "min_edge_ratio"])).toBe(0.7);
    o = setOpt(o, ["quality", "min_edge_ratio"], undefined);
    expect(o).toEqual({ position_ref: "proportional" });
  });

  it("칸 값 검사: 빈칸 = 키 제거, 범위 밖은 문구", () => {
    expect(parseOpt(field("quality.min_edge_ratio"), "")).toEqual({ value: undefined });
    expect(parseOpt(field("quality.min_edge_ratio"), "1.5")).toEqual({ error: "0 초과 1 이하" });
    expect(parseOpt(field("quality.max_aspect"), "0.5")).toEqual({ error: "1 이상" });
    expect(parseOpt(field("extract.position_range_mm"), "abc")).toEqual({ error: "숫자를 입력하세요" });
    expect(parseOpt(field("tie.required"), "false")).toEqual({ value: false });
  });

  it("대칭 그룹 분리·묶기(symmetry_split)", () => {
    const a = toggleSplit({ quality: { max_aspect: 8 } }, "G1");
    expect(a.symmetry_split).toEqual(["G1"]);
    expect(isSplit(a, "G1")).toBe(true);
    const b = toggleSplit(a, "G1");
    expect(b).toEqual({ quality: { max_aspect: 8 } });
  });

  it("422 problems → 칸별 문구, 목 검사기 범위(§4.9)", () => {
    expect(optProblems({ problems: [{ path: "quality.min_stretch", message: "0 < min_stretch ≤ 1" }] })).toEqual({ "quality.min_stretch": "0 < min_stretch ≤ 1" });
    expect(validateGeomOptions({ quality: { min_stretch: 2 }, engine: "native" }, []).map((p) => p.path)).toEqual(["engine", "quality.min_stretch"]);
    expect(validateGeomOptions({ symmetry_split: ["G9"] }, ["G1"])[0].path).toBe("symmetry_split");
  });
});

describe("다중 baseline 매칭표(§4.10)", () => {
  const map = (): ParamMap => ({
    schema_version: 1, status: "draft", confirmed_by: null, confirmed_at: null, usage: "topology",
    baselines: [{ id: "B1", rel: "." }, { id: "B2", rel: "baselines/B2" }],
    common: [
      { row_id: "r1", type: "thickness", unit: "mm", needs_review: false, proposed: { name: "A", score: 0.9, grade: "recommend", map: { B1: "a1", B2: "a2" } }, decision: null },
      { row_id: "r2", type: "height", unit: "mm", needs_review: false, proposed: { name: "B", score: 0.6, grade: "check", map: { B1: "b1", B2: "b2" } }, decision: null },
      { row_id: "r3", type: "height", unit: "mm", needs_review: true, proposed: { name: "C", score: 0.3, grade: "unmatched", map: { B1: "c1", B2: null } }, decision: null },
    ],
    warnings: [],
  });

  it("확정 전 결정 필요 행 = 재확인·확인 필요 중 미결정", () => {
    expect(pendingRows(map()).map((r) => r.row_id)).toEqual(["r2", "r3"]);
  });

  it("이름 충돌: 중복 이름·예약어 baseline·같은 원 파라미터 중복", () => {
    const m = map();
    m.common[1].decision = { action: "change", name: "A", map: { B1: "b1", B2: "b2" } };
    expect([...nameConflicts(m)].sort()).toEqual(["r1", "r2"]);
    m.common[1].decision = { action: "change", name: "baseline", map: { B1: "b1", B2: "a2" } };
    expect([...nameConflicts(m)].sort()).toEqual(["r1", "r2"]);
  });
});

describe("오류 코드 한국어(§7.6·§7.7)", () => {
  it("서버 문구가 한국어가 아니면 코드 표 문구", () => {
    expect(errorMessage(new ApiError(409, { code: "ENGINE_MISMATCH", message: "engine mismatch" }))).toBe("모델과 템플릿의 형상 엔진이 다릅니다(SimLab·native 혼용 불가)");
    expect(errorMessage(new ApiError(409, { code: "GEOM_PREP_STALE", message: "준비본이 STALE입니다(B2)" }))).toBe("준비본이 STALE입니다(B2)");
    expect(geomErrorText("ENGINE_MIXED", "")).toBe("SimLab·native 학습데이터를 한 데이터셋에 섞을 수 없습니다");
    expect(geomErrorText("SOMETHING", "plain")).toBe("plain");
  });
});
