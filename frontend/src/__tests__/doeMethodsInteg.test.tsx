// v0.2.9 통합 보정(doe-methods.md DM-C3·C4·C6, job-queues 통합): ① table 미리 검사가 서버 규칙·문구와 같다 · ①-3 Native lhs 상한 = /status native_doe_max_runs ·
// ④ 다중 baseline 기본 lhs · ⑥ 다중 baseline은 sobol만 회색.
import { describe, expect, it } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { renderApp, STUDY } from "../test/render";
import type { MockServer } from "../mock/server";
import { nativeTrainParams } from "../mock/geometry";
import { MULTI_BASELINE_REASON, SITE_DEFAULT, SITE_KINDS, checkTable, fmtG } from "../lib/sampling";
import { buildNativeParams, doeLimits, initialNative } from "../stages/stage1/doeGenParams";
import { initialSampling, kindForTemplate, resetForTemplate } from "../stages/stage4/batch/samplingSource";
import type { ParamSet } from "../api/types";

const NAMES = ["A", "B"];
const R = { A: [0, 10], B: [1, 2] } as Record<string, [number, number]>;
const codes = (t: string, ranges: Record<string, [number, number]> | null = R, max = 500, bytes?: number) => checkTable(t, NAMES, ranges, max, bytes).problems;

describe("① table 미리 검사 = 서버 규칙(matrix_basic._table + doe_platform._finish)", () => {
  it("구분자: 첫 줄에 탭이 있으면 탭(쉼표 소수는 값 오류), 없으면 쉼표", () => {
    expect(codes("A\tB\n1\t1.5\n2\t1.2")).toEqual([]);
    expect(codes("A,B\n1,1.5\n2,1.2")).toEqual([]);
    expect(codes("A\tB\n1\t1,5\n2\t1.2")[0]).toMatchObject({ code: "TABLE_VALUE", row: 1 });
    expect(codes("A B\n1 1\n2 1")[0]).toMatchObject({ code: "TABLE_HEADER" }); // 공백은 구분자가 아님
  });
  it("크기: table_max_bytes(기본 1 MiB) 초과는 TEXT_TOO_LARGE(바이트 기준), 내용은 읽지 않는다", () => {
    expect(codes("A,B\n1,1\n2,2", R, 500, 5)).toEqual([{ code: "TEXT_TOO_LARGE", message: "표 내용이 5 바이트를 넘습니다" }]);
    expect(codes("가".repeat(2), R, 500, 5)[0].code).toBe("TEXT_TOO_LARGE"); // 3바이트 문자 2개 = 6바이트
    expect(codes("A,B\n1,1\n2,2".padEnd(1048577, " "))[0].code).toBe("TEXT_TOO_LARGE");
    expect(codes("A,B\n1,1\n2,2".padEnd(1048576, " "))).toEqual([]);
  });
  it("행 수: 0행·1행은 TOO_FEW_ROWS(서버 문구 그대로), 상한 초과는 TOO_MANY_ROWS(platform_max_runs)", () => {
    expect(codes("A,B")).toEqual([{ code: "TOO_FEW_ROWS", message: "데이터 행이 1개 이상 필요합니다" }]);
    expect(codes("A,B\n1,1")).toEqual([{ code: "TOO_FEW_ROWS", message: "행은 2개 이상이어야 합니다(현재 1개)" }]);
    expect(codes("A,B\n1,1\n2,2\n3,2", R, 2)).toEqual([{ code: "TOO_MANY_ROWS", message: "행은 최대 2개입니다(현재 3개)" }]);
    expect(codes("A,B\n1,1\n2,2", R, 2)).toEqual([]); // 상한 값 자체는 허용
    expect(codes("")[0]).toMatchObject({ code: "TABLE_HEADER", message: "첫 줄에 파라미터 이름 헤더가 필요합니다" });
  });
  it("헤더: 대소문자 구분 정확 일치, doe 열은 대소문자 무시로 건너뜀, 모르는·중복·누락 열은 TABLE_HEADER", () => {
    expect(codes("a,B\n1,1\n2,2").map((p) => p.message)).toEqual(["'a'는 템플릿 파라미터가 아닙니다", "파라미터 열이 없습니다: A"]);
    expect(codes("DOE,A,B\n1,1,1\n2,2,2")).toEqual([]);
    expect(codes("doe,A,B\n1,1,1\n2,2,2")).toEqual([]);
    expect(codes("A,B,C\n1,1,1\n2,2,2").map((p) => p.message)).toEqual(["'C'는 템플릿 파라미터가 아닙니다"]);
    expect(codes("A,A,B\n1,1,1\n2,2,2").map((p) => p.message)).toEqual(["'A' 열이 중복됩니다"]);
    expect(codes("A\n1\n2").map((p) => p.message)).toEqual(["파라미터 열이 없습니다: B"]);
    for (const p of codes("a,A,A,Z\n1,1,1,1\n2,2,2,2")) expect(p.code).toBe("TABLE_HEADER");
  });
  it("값: float로 읽어 유한해야 한다(1e1·밑줄 숫자 허용, 0x·nan·inf·빈 칸·열 수 불일치는 TABLE_VALUE + row)", () => {
    expect(codes("A,B\n1e1,1_0\n+2.5,.5", { A: [0, 10], B: [0, 10] })).toEqual([]);
    expect(codes("A,B\n0x1,1\n2,2")[0]).toMatchObject({ code: "TABLE_VALUE", row: 1, message: "1행 값이 유한한 숫자가 아닙니다: A" });
    expect(codes("A,B\n1,1\n2,nan")[0]).toMatchObject({ code: "TABLE_VALUE", row: 2 });
    expect(codes("A,B\n1,1\ninf,2")[0]).toMatchObject({ code: "TABLE_VALUE", row: 2 });
    expect(codes("A,B\n1,\n2,2")[0]).toMatchObject({ code: "TABLE_VALUE", row: 1 });
    expect(codes("A,B\n1,1,5\n2,2")[0]).toMatchObject({ code: "TABLE_VALUE", row: 1, message: "1행 열 수(3)가 헤더(2)와 다릅니다" });
    // 값 오류가 있으면 행 수 2 미만·범위 밖 판정은 하지 않는다(서버 _finish는 problems가 비었을 때만)
    expect(codes("A,B\n99,x").map((p) => p.code)).toEqual(["TABLE_VALUE"]);
    expect(codes("A,B\n99,1\n1,x").map((p) => p.code)).toEqual(["TABLE_VALUE"]);
  });
  it("범위: 학습 범위 밖이면 TABLE_OUT_OF_RANGE(행별·row, %g 숫자 표기), 경계값은 허용", () => {
    expect(codes("A,B\n0,1\n10,2")).toEqual([]);
    expect(codes("A,B\n-0.001,1\n10.5,2.5")).toEqual([
      { code: "TABLE_OUT_OF_RANGE", message: "'A' 값 -0.001가 학습 범위 0~10 밖입니다", row: 1 },
      { code: "TABLE_OUT_OF_RANGE", message: "'A' 값 10.5가 학습 범위 0~10 밖입니다", row: 2 },
      { code: "TABLE_OUT_OF_RANGE", message: "'B' 값 2.5가 학습 범위 1~2 밖입니다", row: 2 },
    ]);
    expect(codes("A,B\n1234567,1\n1,1", R)[0].message).toBe("'A' 값 1.23457e+06가 학습 범위 0~10 밖입니다");
    expect(codes("A,B\n99,9\n1,1", null)).toEqual([]); // 범위를 모르면 범위 검사 없음
  });
  it("fmtG = Python %g", () => {
    const cases: [number, string][] = [[0, "0"], [11, "11"], [2.5, "2.5"], [0.0001, "0.0001"], [0.00001, "1e-05"], [1234567, "1.23457e+06"], [123456, "123456"], [-0.5, "-0.5"], [1e21, "1e+21"], [100000, "100000"], [0.1 + 0.2, "0.3"]];
    for (const [x, t] of cases) expect(fmtG(x), String(x)).toBe(t);
  });
});

describe("①-3 Native lhs run 상한 = /status limits.configured.native_doe_max_runs", () => {
  it("doeLimits: native_doe_max_runs가 있으면 그 값, 없으면 platform 상한(옛 서버)", () => {
    const st = (c: Record<string, unknown>) => ({ limits: { configured: c } });
    expect(doeLimits(st({ doe_platform_max_runs: 500, native_doe_max_runs: 2000 }))).toMatchObject({ maxRuns: 500, nativeLhsMaxRuns: 2000 });
    expect(doeLimits(st({ doe_platform_max_runs: 300 }))).toMatchObject({ maxRuns: 300, nativeLhsMaxRuns: 300 });
    expect(doeLimits(null)).toMatchObject({ maxRuns: 500, nativeLhsMaxRuns: 500 });
  });
  it("buildNativeParams: lhs는 lhs 상한까지, 비lhs·표는 platform 상한(500)", () => {
    const o = { multi: 2, maxRuns: 2000, otherMaxRuns: 500, assemPath: "A", paramSetId: null as string | null, names: ["A", "B"] };
    expect(buildNativeParams({ ...initialNative(), count: "1500" }, o)).toMatchObject({ sampling: { kind: "lhs", count: 1500, seed: 1 } });
    expect(buildNativeParams({ ...initialNative(), count: "2001" }, o)).toBeNull();
    expect(buildNativeParams({ ...initialNative(), kind: "halton", count: "500" }, o)).toMatchObject({ sampling: { kind: "halton", count: 500 } });
    expect(buildNativeParams({ ...initialNative(), kind: "halton", count: "501" }, o)).toBeNull();
    const rows = (n: number) => `A,B\n${Array.from({ length: n }, () => "1,1").join("\n")}`;
    expect(buildNativeParams({ ...initialNative(), kind: "table", text: rows(500) }, { ...o, table: { ranges: R } })).toMatchObject({ sampling: { kind: "table" } });
    expect(buildNativeParams({ ...initialNative(), kind: "table", text: rows(501) }, { ...o, table: { ranges: R } })).toBeNull();
  });
  it("화면: lhs 1500은 생성 가능(상한 2000), 방식을 halton으로 바꾸면 같은 1500이 상한 500 초과로 막힌다", async () => {
    const setup = (s: MockServer) => Object.assign(s.p2.setups["s-cushion"], { engine: "native", parameters: nativeTrainParams(), tpl: null });
    renderApp(`${STUDY}/1`, { user: "power" }, setup);
    const card = await screen.findByRole("region", { name: "DOE · Radioss 입력" });
    await within(card).findByTestId("doe-native");
    const count = within(card).getByLabelText("run 수") as HTMLInputElement;
    fireEvent.change(count, { target: { value: "1500" } });
    expect(within(card).getByTestId("td-runs").textContent).not.toContain("초과");
    fireEvent.change(count, { target: { value: "2001" } });
    expect(within(card).getByTestId("td-runs").textContent).toContain("상한 2000개 초과");
    fireEvent.change(within(card).getByLabelText("표본 방식"), { target: { value: "halton" } });
    fireEvent.change(within(card).getByLabelText("run 수"), { target: { value: "1500" } });
    await waitFor(() => expect(within(card).getByTestId("td-runs").textContent).toContain("상한 500개 초과"));
  });
});

const multiPs = { id: "ps-m", parameters: [{ name: "A", min: 0, max: 1 }], baselines: [{ id: "B1" }, { id: "B2" }] } as unknown as ParamSet;
const singlePs = { id: "ps-s", parameters: [{ name: "A", min: 0, max: 1 }], baselines: [{ id: "B1" }] } as unknown as ParamSet;

describe("④ 다중 baseline 기본값 = lhs(registry.SITE_DEFAULT batch_multi)", () => {
  it("initialSampling: 단일은 lhs_opt, 다중 baseline은 lhs", () => {
    expect(SITE_DEFAULT.batch_multi).toBe("lhs");
    expect(initialSampling(singlePs).kind).toBe("lhs_opt");
    expect(initialSampling(null).kind).toBe("lhs_opt");
    expect(initialSampling(multiPs).kind).toBe("lhs");
  });
  it("템플릿이 다중 baseline으로 바뀌면 기본(lhs_opt)·허용 밖(sobol 등)은 lhs로, 허용 안의 다른 선택(halton)은 유지, 같은 템플릿이면 그대로", () => {
    const s = initialSampling(singlePs);
    expect(resetForTemplate(s, multiPs).kind).toBe("lhs");
    expect(resetForTemplate({ ...s, kind: "sobol" }, multiPs).kind).toBe("lhs");
    expect(resetForTemplate({ ...s, kind: "halton" }, multiPs).kind).toBe("halton");
    expect(resetForTemplate({ ...s, kind: "sobol" }, singlePs)).toEqual({ ...s, kind: "sobol" });
    expect(resetForTemplate(initialSampling(multiPs), singlePs).kind).toBe("lhs"); // 단일로 돌아와도 고른 방식은 유지
    for (const k of SITE_KINDS.batch_multi) expect(kindForTemplate(k, singlePs)).toBe(k);
  });
});

describe("④ 다중 baseline 화면", () => {
  it("다중 baseline 템플릿을 고르면 표본 방식 기본이 lhs(추천 표시)", async () => {
    localStorage.setItem("physicsai.stage4.inputMode", "batch");
    renderApp(`${STUDY}/4`, { user: "power", geometry: "multi" });
    const setup = await screen.findByRole("region", { name: "1 템플릿·조합" });
    const sel = () => within(setup).getByLabelText("표본 방식") as HTMLSelectElement;
    const tpl = within(setup).getByLabelText("형상 템플릿") as HTMLSelectElement;
    await waitFor(() => expect([...tpl.options].map((o) => o.value)).toContain("ps-n1"));
    fireEvent.change(tpl, { target: { value: "ps-n1" } });
    await waitFor(() => expect(sel().value).toBe("lhs"));
    expect([...sel().options].find((o) => o.value === "lhs")!.textContent).toContain("추천");
    expect([...sel().options].find((o) => o.value === "lhs_opt")!.textContent).not.toContain("추천");
    localStorage.clear();
  });
});

describe("⑥ 탐색 방식: 다중 baseline에서는 sobol만 회색", () => {
  it("다중 baseline 세트: sobol만 disabled + DM-C4 사유, lhs·lhs_opt·halton·random은 선택 가능", async () => {
    renderApp(`${STUDY}/5`, { user: "power", geometry: "multi" });
    fireEvent.click(await screen.findByRole("tab", { name: /새 최적화/ }));
    const tpl = (await screen.findByLabelText("형상 템플릿")) as HTMLSelectElement;
    await waitFor(() => expect([...tpl.options].map((o) => o.value)).toContain("ps-n1"));
    fireEvent.change(tpl, { target: { value: "ps-n1" } });
    const m = (await screen.findByLabelText("탐색 방식")) as HTMLSelectElement;
    await waitFor(() => expect([...m.options].find((o) => o.value === "sobol")!.disabled).toBe(true));
    expect([...m.options].filter((o) => o.disabled).map((o) => o.value)).toEqual(["sobol"]);
    expect([...m.options].find((o) => o.value === "sobol")!.title).toBe(MULTI_BASELINE_REASON);
    expect(m.value).toBe("lhs");
  });
});
