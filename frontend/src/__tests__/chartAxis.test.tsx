// v0.2.8 "반복-성능" 그래프 축 규칙(C1~C4): 정수 눈금·0 시작, 지수 3자리, 최소/최대·잘못된 입력 거부, 기본값 복원, localStorage 실패.
import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { Chart } from "../components/Chart";
import { HvChart } from "../stages/stage5/surrogate/HvChart";
import {
  DEFAULT_AXIS,
  axisStorageKey,
  checkAxisInput,
  fmtAxisY,
  fmtExp,
  intTicks,
  isDefaultAxis,
  parseBound,
  readAxisPrefs,
  resolveXDomain,
  resolveYDomain,
  sanitizePrefs,
  writeAxisPrefs,
} from "../lib/chartAxis";
import { convergence } from "../stages/stage5/surrogate/soRules";

afterEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

const xTicks = (c: HTMLElement) => [...c.querySelectorAll("text.chart-tick")].filter((t) => t.getAttribute("text-anchor") === "middle").map((t) => t.textContent);
const yTicks = (c: HTMLElement) => [...c.querySelectorAll("text.chart-tick")].filter((t) => t.getAttribute("text-anchor") === "end").map((t) => t.textContent);

describe("C1 x축: 0 시작·정수 눈금", () => {
  it("intTicks: 정수만, 0부터, 개수 상한", () => {
    expect(intTicks(0, 5)).toEqual([0, 1, 2, 3, 4, 5]);
    expect(intTicks(0, 100, 10).every(Number.isInteger)).toBe(true);
    expect(intTicks(0, 100, 10)).toEqual([0, 20, 40, 60, 80, 100]);
    expect(intTicks(0, 1)).toEqual([0, 1]);
    expect(intTicks(0.5, 3.2)).toEqual([1, 2, 3]); // 범위 안의 정수만
    expect(intTicks(0, 37, 6).every((v) => Number.isInteger(v) && v >= 0)).toBe(true);
    expect(intTicks(0, 37, 6).length).toBeLessThanOrEqual(6);
    expect(intTicks(3, 1)).toEqual([]);
  });

  it("resolveXDomain: 자동 = 0 ~ 마지막 반복(데이터가 1부터여도 시작은 0)", () => {
    expect(resolveXDomain(DEFAULT_AXIS, 7)).toEqual([0, 7]);
    expect(resolveXDomain(DEFAULT_AXIS, 0)).toEqual([0, 1]);
    expect(resolveXDomain({ xMin: 2, xMax: null }, 7)).toEqual([2, 7]);
    expect(resolveXDomain({ xMin: null, xMax: 20 }, 7)).toEqual([0, 20]);
    expect(resolveXDomain({ xMin: 10, xMax: null }, 3)).toEqual([10, 11]); // 마지막 반복보다 큰 최소 → 최소+1
  });

  it("Chart: 데이터가 반복 1부터여도 축은 0부터, 눈금은 정수, 데이터 값(점 위치 제목)은 그대로", () => {
    const { container } = render(
      <Chart height={200} ariaLabel="t" iterAxis={{ kind: "convergence", xLast: 4 }} points={[1, 2, 3, 4].map((x) => ({ x, y: x * 0.01, title: (fy: (v: number) => string) => `반복 ${x} ${fy(x * 0.01)}` }))} />,
    );
    expect(xTicks(container)).toEqual(["0", "1", "2", "3", "4"]);
    expect([...container.querySelectorAll("circle title")].map((t) => t.textContent)).toEqual(["반복 1 1.000e-2", "반복 2 2.000e-2", "반복 3 3.000e-2", "반복 4 4.000e-2"]);
  });

  it("수렴 자료 convergence(): 반복 번호는 데이터 그대로(1부터면 1부터)", () => {
    const c = convergence({
      settings: { iterations: 3 },
      runs: [{ iter_no: 1, batch_id: "b", batch_label: "B-1", doe_no: 1, run_key: "r", values: {}, objective: 5, constraints: [], state: "SUCCEEDED" }],
      iterations: [{ iter_no: 1, kind: "EXPLORE", best_value: 5 }],
    } as never);
    expect(c.verified.map((p) => p.x)).toEqual([1]);
    expect(c.best).toEqual([[1, 5]]);
    expect(c.verified[0].title(fmtExp)).toContain("5.000e+0");
  });
});

describe("C2 y축: 지수 3자리", () => {
  it("fmtExp: 양수·음수·0·매우 작은/큰 값", () => {
    expect(fmtExp(123.456)).toBe("1.235e+2");
    expect(fmtExp(-0.00412)).toBe("-4.120e-3");
    expect(fmtExp(0)).toBe("0.000e+0");
    expect(fmtExp(-0)).toBe("0.000e+0");
    expect(fmtExp(1.23456e-12)).toBe("1.235e-12");
    expect(fmtExp(9.8765e300)).toBe("9.877e+300");
    expect(fmtExp(5e-324)).toBe("4.941e-324");
    expect(fmtExp(Number.NaN)).toBe("–");
    expect(fmtExp(Infinity)).toBe("–");
  });

  it("fmtAxisY: 기본 지수 3자리 / 자리수 0~6 / 일반 표기", () => {
    expect(fmtAxisY(123.456)).toBe("1.235e+2");
    expect(fmtAxisY(123.456, { yFormat: "exp", yDigits: 0 })).toBe("1e+2");
    expect(fmtAxisY(123.456, { yFormat: "exp", yDigits: 6 })).toBe("1.234560e+2");
    expect(fmtAxisY(123.456, { yFormat: "plain", yDigits: 2 })).toBe("123.46");
    expect(fmtAxisY(-0.5, { yFormat: "plain", yDigits: 0 })).toBe("-1"); // toFixed 반올림
    expect(fmtAxisY(1, { yFormat: "exp", yDigits: 99 })).toBe("1.000000e+0"); // 상한 6
  });

  it("Chart: y 눈금·툴팁이 같은 지수 형식", () => {
    const { container } = render(<Chart height={200} ariaLabel="t" iterAxis={{ kind: "convergence", xLast: 3 }} points={[{ x: 0, y: 123.456 }, { x: 3, y: -4.12 }]} />);
    const ys = yTicks(container);
    expect(ys.length).toBeGreaterThan(1);
    for (const t of ys) expect(t).toMatch(/^-?\d\.\d{3}e[+-]\d+$/);
  });
});

describe("C3 최소·최대 적용과 입력 검증", () => {
  it("parseBound: 빈 칸 = 자동, 숫자만 허용", () => {
    expect(parseBound("")).toEqual({ ok: true, value: null });
    expect(parseBound("  ")).toEqual({ ok: true, value: null });
    expect(parseBound("-1.5e-3")).toEqual({ ok: true, value: -0.0015 });
    expect(parseBound(".5")).toEqual({ ok: true, value: 0.5 });
    for (const bad of ["abc", "1,5", "1e", "0x10", "Infinity", "NaN", "1 2", "--1"]) expect(parseBound(bad).ok, bad).toBe(false);
  });

  it("checkAxisInput: 최소 < 최대만 통과, 한쪽만 넣으면 자동값과 비교", () => {
    expect(checkAxisInput("0", "10", 0, 5)).toEqual({ ok: true, min: 0, max: 10 });
    expect(checkAxisInput("", "", 0, 5)).toEqual({ ok: true, min: null, max: null });
    expect(checkAxisInput("5", "5", 0, 9).ok).toBe(false);
    expect(checkAxisInput("6", "5", 0, 9).maxError).toContain("최소는 최대보다");
    expect(checkAxisInput("7", "", 0, 5).minError).toContain("최소는 최대보다"); // 자동 최대 5보다 큼
    expect(checkAxisInput("", "-1", 0, 5).maxError).toBeTruthy(); // 자동 최소 0보다 작은 최대
    expect(checkAxisInput("a", "5", 0, 9).minError).toBe("숫자만 입력하세요");
  });

  it("resolveYDomain: 자동 = 데이터 범위, 지정값 우선, 전부 같으면 펼침", () => {
    expect(resolveYDomain(DEFAULT_AXIS, -2, 8)).toEqual([-2, 8]);
    expect(resolveYDomain({ yMin: 0, yMax: null }, -2, 8)).toEqual([0, 8]);
    expect(resolveYDomain({ yMin: null, yMax: 3 }, -2, 8)).toEqual([-2, 3]);
    const [a, b] = resolveYDomain(DEFAULT_AXIS, 4, 4);
    expect(a).toBeLessThan(4);
    expect(b).toBeGreaterThan(4);
  });

  function open() {
    const r = render(<Chart height={200} ariaLabel="t" iterAxis={{ kind: "convergence", xLast: 10 }} points={[{ x: 0, y: 1 }, { x: 10, y: 9 }]} />);
    fireEvent.click(screen.getByTestId("axis-btn"));
    return r;
  }
  const field = (name: string) => screen.getByLabelText(name) as HTMLInputElement;

  it("팝오버: 최소·최대 적용 → 눈금 변경 + 저장, 잘못된 입력은 적용 안 됨·경고", () => {
    const { container } = open();
    expect(screen.getByRole("dialog", { name: "축 편집" })).toBeTruthy();
    expect(xTicks(container)).toContain("10");
    fireEvent.change(field("x 최대"), { target: { value: "4" } });
    expect(xTicks(container)).toEqual(["0", "1", "2", "3", "4"]);
    expect(JSON.parse(localStorage.getItem(axisStorageKey("convergence"))!).xMax).toBe(4);
    // 최소 >= 최대 → 적용 안 함(이전 값 유지) + 경고
    fireEvent.change(field("x 최소"), { target: { value: "4" } });
    expect(screen.getAllByRole("alert").map((a) => a.textContent)).toContain("최소는 최대보다 작아야 합니다");
    expect(xTicks(container)).toEqual(["0", "1", "2", "3", "4"]);
    expect(JSON.parse(localStorage.getItem(axisStorageKey("convergence"))!).xMin).toBeNull();
    // 숫자 아님
    fireEvent.change(field("y 최소"), { target: { value: "abc" } });
    expect(screen.getAllByRole("alert").map((a) => a.textContent)).toContain("숫자만 입력하세요");
    expect(JSON.parse(localStorage.getItem(axisStorageKey("convergence"))!).yMin).toBeNull();
    // 정상 y 범위
    fireEvent.change(field("y 최소"), { target: { value: "0" } });
    fireEvent.change(field("y 최대"), { target: { value: "20" } });
    expect(JSON.parse(localStorage.getItem(axisStorageKey("convergence"))!)).toMatchObject({ yMin: 0, yMax: 20 });
    // 소수 자리·표기
    fireEvent.change(field("소수 자리"), { target: { value: "1" } });
    for (const t of yTicks(container)) expect(t).toMatch(/^-?\d\.\de[+-]\d+$/);
    fireEvent.change(field("소수 자리"), { target: { value: "9" } }); // 범위 밖 → 거부
    expect(screen.getAllByRole("alert").map((a) => a.textContent)).toContain("0~6 정수");
    fireEvent.change(screen.getByLabelText("y 표기"), { target: { value: "plain" } });
    for (const t of yTicks(container)) expect(t).toMatch(/^-?\d+\.\d$/);
  });

  it("기본값 버튼: C1·C2로 복원하고 저장 항목을 지운다", () => {
    const { container } = open();
    fireEvent.change(field("x 최대"), { target: { value: "4" } });
    fireEvent.change(screen.getByLabelText("y 표기"), { target: { value: "plain" } });
    expect(localStorage.getItem(axisStorageKey("convergence"))).not.toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "기본값" }));
    expect(xTicks(container)).toContain("10");
    expect(field("x 최대").value).toBe("");
    expect(localStorage.getItem(axisStorageKey("convergence"))).toBeNull();
    for (const t of yTicks(container)) expect(t).toMatch(/e[+-]\d+$/);
    expect(isDefaultAxis(DEFAULT_AXIS)).toBe(true);
  });
});

describe("C4 저장(localStorage)", () => {
  it("그래프 종류별로 따로 저장하고 다시 읽는다", () => {
    expect(writeAxisPrefs("hv", { ...DEFAULT_AXIS, xMax: 8, yDigits: 2 })).toBe(true);
    expect(readAxisPrefs("hv")).toMatchObject({ xMax: 8, yDigits: 2 });
    expect(readAxisPrefs("convergence")).toEqual(DEFAULT_AXIS);
    expect(readAxisPrefs("history")).toEqual(DEFAULT_AXIS);
  });

  it("깨진 저장값은 기본값으로", () => {
    localStorage.setItem(axisStorageKey("hv"), "{not json");
    expect(readAxisPrefs("hv")).toEqual(DEFAULT_AXIS);
    expect(sanitizePrefs({ xMin: 5, xMax: 2, yFormat: "zzz", yDigits: 99 })).toEqual({ ...DEFAULT_AXIS, yDigits: 6 });
    expect(sanitizePrefs(null)).toEqual(DEFAULT_AXIS);
    expect(sanitizePrefs({ xMin: "1", yMin: NaN })).toEqual(DEFAULT_AXIS);
  });

  it("localStorage 읽기·쓰기 예외에도 기본값으로 동작하고 던지지 않는다", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("denied");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("quota");
    });
    expect(readAxisPrefs("hv")).toEqual(DEFAULT_AXIS);
    expect(writeAxisPrefs("hv", { ...DEFAULT_AXIS, xMax: 3 })).toBe(false);
    // 화면: 저장이 막혀도 그리기·편집은 된다
    const { container } = render(<Chart height={200} ariaLabel="t" iterAxis={{ kind: "convergence", xLast: 10 }} points={[{ x: 0, y: 1 }, { x: 10, y: 9 }]} />);
    expect(xTicks(container)).toContain("10");
    fireEvent.click(screen.getByTestId("axis-btn"));
    fireEvent.change(screen.getByLabelText("x 최대") as HTMLInputElement, { target: { value: "3" } });
    expect(xTicks(container)).toEqual(["0", "1", "2", "3"]);
  });

  it("저장된 값은 새로 그릴 때 적용된다", () => {
    writeAxisPrefs("convergence", { ...DEFAULT_AXIS, xMax: 2 });
    const { container } = render(<Chart height={200} ariaLabel="t" iterAxis={{ kind: "convergence", xLast: 10 }} points={[{ x: 0, y: 1 }]} />);
    expect(xTicks(container)).toEqual(["0", "1", "2"]);
  });
});

describe("HV 그래프도 같은 규칙", () => {
  it("x 0부터 정수 눈금, y 지수 3자리, 툴팁 같은 형식, 축 버튼 1개", () => {
    const opt = { settings: { iterations: 3, tol_rel: 0.01 }, hv_history: [{ iter_no: 1, hv: 0.0123456, front_size: 4, improvement_rel: null }, { iter_no: 2, hv: 0.02, front_size: 5, improvement_rel: 0.5 }] } as never;
    render(<HvChart opt={opt} />);
    const svg = screen.getByRole("img", { name: "HV 그래프" }) as unknown as SVGElement;
    const ticks = [...svg.querySelectorAll("text.chart-tick")];
    expect(ticks.filter((t) => t.getAttribute("text-anchor") === "middle" && !t.classList.contains("so-hv-imp")).map((t) => t.textContent)).toEqual(["0", "1", "2", "3"]);
    for (const t of ticks.filter((t) => t.getAttribute("text-anchor") === "end")) expect(t.textContent).toMatch(/^-?\d\.\d{3}e[+-]\d+$/);
    expect(screen.getByTestId("hv-pt-1").querySelector("title")!.textContent).toContain("HV 1.235e-2");
    expect(screen.getAllByTestId("axis-btn")).toHaveLength(1);
  });
});
