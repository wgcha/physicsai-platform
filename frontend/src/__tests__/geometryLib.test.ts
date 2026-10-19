// native 형상 엔진 화면 순수 함수(geometry-engine.md §4.3·§4.9·§6.2·§11.4) + 오류 코드 한국어
import { describe, expect, it } from "vitest";
import { ApiError, errorMessage, type ParamMap } from "../api";
import {
  effectiveMap, effectiveName, exceedsFeasible, genCategoryText, geomErrorText, getOpt, isSplit, nameConflicts, optProblems, originalNames, parseOpt, pendingRows, rangeText, setOpt,
  splitParts, toggleSplit, GEOM_OPT_FIELDS,
} from "../lib/geometry";
import { stepLabel, currentStepText } from "../lib/steps";
import { validateGeomOptions } from "../mock/geometry";

const field = (k: string) => GEOM_OPT_FIELDS.flatMap((g) => g.fields).find((f) => f.path.join(".") === k)!;

describe("피처 이름·범위(§4.3)", () => {
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
  const P = (name: string, score: number, grade: "recommend" | "check" | "unmatched", map: Record<string, string | null>) => ({ name, score, grade, map, nominal: {}, candidates: [] });
  const map = (): ParamMap => ({
    status: "draft", confirmed_by: null, confirmed_at: null, usage: "topology", unresolved_rows: ["r2", "r3"], undecided_count: 3, variables: ["A", "B", "C"],
    baselines: [{ id: "B1", rel: "." }, { id: "B2", rel: "baselines/B2" }],
    common: [
      { row_id: "r1", type: "thickness", unit: "mm", signature: "", needs_review: false, requires_decision: false, proposed: P("A", 0.9, "recommend", { B1: "a1", B2: "a2" }), decision: null },
      { row_id: "r2", type: "height", unit: "mm", signature: "", needs_review: false, requires_decision: true, proposed: { ...P("B", 0.6, "check", { B1: "b1", B2: "b2" }), candidates: [{ map: { B1: "b1", B2: "b9" }, score: 0.5 }] }, decision: null },
      { row_id: "r3", type: "height", unit: "mm", signature: "", needs_review: true, requires_decision: true, proposed: P("C", 0.3, "unmatched", { B1: "c1", B2: null }), decision: null },
    ],
    warnings: [],
  });

  it("확정 전 결정 필요 행 = 재확인·확인 필요 중 미결정(requires_decision)", () => {
    expect(pendingRows(map()).map((r) => r.row_id)).toEqual(["r2", "r3"]);
    const m = map();
    m.common[1].decision = { action: "accept" };
    expect(pendingRows(m).map((r) => r.row_id)).toEqual(["r3"]);
  });

  it("이름 충돌: 중복 이름·예약어 baseline·같은 원 파라미터 중복", () => {
    const m = map();
    m.common[1].decision = { action: "change", name: "A", map: { B1: "b1", B2: "b2" } };
    expect([...nameConflicts(m)].sort()).toEqual(["r1", "r2"]);
    m.common[1].decision = { action: "change", name: "baseline", map: { B1: "b1", B2: "a2" } };
    expect([...nameConflicts(m)].sort()).toEqual(["r1", "r2"]);
  });

  it("분리 = baseline별 parts(이름_baseline, 나머지 N/A), 표시는 부분 이름·대응을 합친다", () => {
    const m = map();
    const parts = splitParts(m.common[0], ["B1", "B2"]);
    expect(parts).toEqual([{ name: "A_B1", map: { B1: "a1", B2: null } }, { name: "A_B2", map: { B1: null, B2: "a2" } }]);
    expect(splitParts(m.common[2], ["B1", "B2"])).toHaveLength(1);
    m.common[0].decision = { action: "split", name: "A_B1", map: { B1: null, B2: null }, parts };
    expect(effectiveName(m.common[0])).toBe("A_B1 / A_B2");
    expect(effectiveMap(m.common[0])).toEqual({ B1: "a1", B2: "a2" });
    expect(nameConflicts(m).size).toBe(0);
  });

  it("변경 칸 후보 = 제안·후보·결정의 원 이름", () => {
    expect(originalNames(map(), "B2")).toEqual(["a2", "b2", "b9"]);
  });
});

describe("category·step 표시명(§6.5·§7.3)", () => {
  it("gen_category → 한국어(모르는 값은 그대로)", () => {
    expect(genCategoryText("INTERFERENCE")).toBe("간섭");
    expect(genCategoryText("CAD_FAILED")).toBe("CAD 생성 불가");
    expect(genCategoryText("NEW_CAT")).toBe("NEW_CAT");
    expect(genCategoryText(null)).toBeNull();
  });
  it("native step 이름: NP_*·BL_MAP, native 작업은 HST_GEN_RADIOSS 등 덮어쓰기, 서버 값 우선", () => {
    expect(stepLabel("BL_MAP")).toBe("baseline 변수 매칭");
    expect(stepLabel("NP_TAG", "native")).toBe("경계 노드 분류");
    expect(stepLabel("HST_GEN_RADIOSS")).toBe("입력 생성(run별)");
    expect(stepLabel("HST_GEN_RADIOSS", "native")).toBe("형상 모핑 입력 생성");
    expect(stepLabel("UNKNOWN_STEP")).toBe("UNKNOWN_STEP");
    expect(currentStepText({ job_type: "PARAM_SET_NATIVE", current_step_key: "NP_EXTRACT", current_step_label: null })).toBe("형상 피처 추출");
    expect(currentStepText({ job_type: "TD_DOE_GEN", current_step_key: "MESH", current_step_label: null, params: { engine: "native" } })).toBe("메시 모핑·검사");
    expect(currentStepText({ job_type: "TD_DOE_GEN", current_step_key: "MESH", current_step_label: "서버 표시" })).toBe("서버 표시");
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
