// v0.2.5 후속(native-vars.md §7.2 NV-C1 ⑥): ⑥ 결과 카드 "범위" 막대 — Native 결과는 실행 스냅숏 settings.vars.variables[].train 기준("학습 범위"),
// 학습 범위가 없으면 이 실행의 템플릿 범위("템플릿 범위"), 스냅숏이 없으면(Altair·옛 결과) 기존 세트 범위 = "학습 범위".
import { describe, expect, it } from "vitest";
import { screen, within } from "@testing-library/react";
import { renderApp, STUDY } from "../test/render";
import { boundNote, compareRows, rangeBasis, rangeHeader } from "../stages/stage5/surrogate/soRules";
import type { SoParameter } from "../api/surrogateOpt";

const P = (name: string, min: number, max: number, nominal = (min + max) / 2): SoParameter => ({ name, nominal, min, max, unit: "mm" });

describe("범위 막대 기준 (순수)", () => {
  it("스냅숏 없음(Altair·옛 결과): 세트 범위 = 학습 범위, 기존 문구 그대로", () => {
    expect(rangeBasis({})).toEqual({ native: false, train: null });
    const rows = compareRows([P("A", 0, 2), P("B", 2, 8)], null, { A: 2, B: 4 });
    expect(rows.map((r) => [r.min, r.max, r.rangeLabel])).toEqual([[0, 2, "학습 범위"], [2, 8, "학습 범위"]]);
    expect(rangeHeader(rows)).toBe("학습 범위");
    expect(boundNote(rows)).toBe("A(상한)이(가) 학습 범위 끝에 닿았습니다 — 범위를 넓혀 학습하면 추가 개선 여지가 있습니다");
  });

  it("Native 스냅숏: train 이 있는 변수는 train 범위(막대 위치·끝 도달 모두 train 기준), 없는 변수는 템플릿 범위", () => {
    const basis = rangeBasis({ vars: { variables: [{ name: "A", train: { min: 0.5, max: 1.5 } }, { name: "B", train: null }] } });
    expect(basis).toEqual({ native: true, train: { A: { min: 0.5, max: 1.5 }, B: null } });
    const rows = compareRows([P("A", 0, 2, 1), P("B", 2, 8, 5)], { A: 1, B: 5 }, { A: 1.5, B: 8 }, basis);
    const [a, b] = rows;
    expect([a.min, a.max, a.rangeLabel, a.basePos, a.optPos, a.bound]).toEqual([0.5, 1.5, "학습 범위", 0.5, 1, "upper"]); // 세트 범위(0~2)였다면 0.75·끝 아님
    expect([b.min, b.max, b.rangeLabel, b.optPos, b.bound]).toEqual([2, 8, "템플릿 범위", 1, "upper"]);
    expect(rangeHeader(rows)).toBe("학습 범위");
    expect(boundNote(rows)).toBe("A(상한)이(가) 학습 범위 끝에 닿았습니다 — 범위를 넓혀 학습하면 추가 개선 여지가 있습니다 · B(상한)이(가) 템플릿 범위 끝에 닿았습니다 — 범위를 넓혀 다시 실행하면 추가 개선 여지가 있습니다");
  });

  it("Native 스냅숏인데 학습 범위가 하나도 없으면 머리글 '템플릿 범위'(세트 범위 막대)", () => {
    const rows = compareRows([P("A", 0, 2)], null, { A: 1 }, rangeBasis({ vars: { variables: [{ name: "A" }] } }));
    expect(rows[0]).toMatchObject({ min: 0, max: 2, rangeLabel: "템플릿 범위" });
    expect(rangeHeader(rows)).toBe("템플릿 범위");
  });
});

describe("⑥ 결과 카드 화면", () => {
  const header = () => {
    const best = screen.getByRole("region", { name: "최적안 — 기준안 대비" });
    return within(within(best).getByRole("table", { name: "기준안 대비" })).getAllByRole("columnheader").map((h) => h.textContent)[1];
  };

  it("스냅숏 없음(기본 목) = '학습 범위', train 이 있는 Native 스냅숏 = '학습 범위'+train 값, train 없는 Native = '템플릿 범위'", async () => {
    const r1 = renderApp(`${STUDY}/5/surrogate/so-1`, { user: "power" });
    await screen.findByTestId("so-status");
    expect(header()).toBe("학습 범위");
    r1.unmount();

    const withVars = (train: boolean) => (s: ReturnType<typeof renderApp>["server"]) => {
      const o = s.surrogate[0];
      const params = (s.handle("GET", "/surrogate-opts/so-1", new URLSearchParams(), null, new Headers()).body as { parameters: SoParameter[] }).parameters;
      o.settings.vars = { set_revision: 1, variables: params.map((p, i) => ({ name: p.name, origin: "set", nominal: p.nominal, min: p.min, max: p.max, unit: p.unit, train: train && i === 0 ? { min: p.min + 0.01, max: p.max - 0.01 } : null })) };
    };
    const r2 = renderApp(`${STUDY}/5/surrogate/so-1`, { user: "power" }, withVars(true));
    await screen.findByTestId("so-status");
    expect(header()).toBe("학습 범위");
    const first = (r2.server.handle("GET", "/surrogate-opts/so-1", new URLSearchParams(), null, new Headers()).body as { parameters: SoParameter[] }).parameters[0];
    const row = screen.getByTestId(`cmp-${first.name}`);
    expect(row.textContent).toContain(`${first.min + 0.01}`.slice(0, 4));
    expect(screen.getAllByText(/\(템플릿\)/).length).toBeGreaterThan(0); // train 없는 변수는 템플릿 범위로 보이고 표시
    r2.unmount();

    renderApp(`${STUDY}/5/surrogate/so-1`, { user: "power" }, withVars(false));
    await screen.findByTestId("so-status");
    expect(header()).toBe("템플릿 범위");
  });
});
