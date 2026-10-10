// phase2.md §20 V2-FE-4 (컴포넌트 시험, 목 서버)
import { describe, expect, it } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { renderApp, STUDY } from "../test/render";
import type { MockServer } from "../mock/server";
import { METHOD_DEFAULTS, activeRules } from "../stages/stage5/rules";

describe("V2-FE-4 ⑤ 최적화", () => {
  it("메서드 기본값·라벨·활성 규칙(단위)", () => {
    expect(METHOD_DEFAULTS.GRSM.max_designs).toBe(50);
    expect(METHOD_DEFAULTS.SQP.dv).toBe(0);
    expect(activeRules({ approach: "OPT", method: "ARSM" })).toEqual({ method: true, absRel: true, dv: true, onFailed: true });
    expect(activeRules({ approach: "OPT", method: "SQP" })).toEqual({ method: true, absRel: false, dv: true, onFailed: true });
    expect(activeRules({ approach: "OPT", method: "GRSM" })).toEqual({ method: true, absRel: false, dv: false, onFailed: true });
    expect(activeRules({ approach: "DOE", method: "ARSM" })).toEqual({ method: false, absRel: false, dv: false, onFailed: false });
  });

  it("응답 표 열, Goal별 Bound/Value 비활성, 목적 필요 → 실행", async () => {
    const { server } = renderApp(`${STUDY}/5`, { user: "power" });
    const card = await screen.findByRole("region", { name: "응답" });
    const table = within(card).getByRole("table", { name: "응답 표" });
    expect(within(table).getAllByRole("columnheader").map((h) => h.textContent)).toEqual([
      "Name", "Source", "Subcase", "DataType/Request", "Component", "Layer", "Stat", "Goal", "Bound", "Value", "",
    ]);
    const add = within(card).getByRole("group", { name: "응답 추가" });
    await waitFor(() => expect((within(add).getByLabelText("DataType") as HTMLSelectElement).tagName).toBe("SELECT"));
    expect((within(add).getByLabelText("Name") as HTMLInputElement).value).toBe("STRESS");
    fireEvent.click(within(add).getByRole("button", { name: "추가" }));
    const run = screen.getByRole("region", { name: "실행" });
    const btn = within(run).getByRole("button", { name: "최적화 실행" }) as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    expect(within(run).getByText("MINIMIZE 또는 MAXIMIZE 응답이 필요합니다")).toBeTruthy();
    expect((within(table).getByLabelText("STRESS Value") as HTMLInputElement).disabled).toBe(true);
    fireEvent.change(within(table).getByLabelText("STRESS Goal"), { target: { value: "CONSTRAINT" } });
    expect((within(table).getByLabelText("STRESS Value") as HTMLInputElement).disabled).toBe(false);
    expect((within(table).getByLabelText("STRESS Bound") as HTMLSelectElement).disabled).toBe(false);
    fireEvent.change(within(table).getByLabelText("STRESS Goal"), { target: { value: "MINIMIZE" } });
    await waitFor(() => expect(btn.disabled).toBe(false));
    fireEvent.click(btn);
    await waitFor(() => expect(server.jobs.some((j) => j.job_type === "OPTIMIZE" && j.state === "QUEUED")).toBe(true));
    const j = server.jobs.find((x) => x.job_type === "OPTIMIZE" && x.state === "QUEUED")!;
    expect(j.params).toMatchObject({ approach: "OPT", opt_method: "ARSM", max_designs: 25, responses: [{ name: "STRESS", source: "H3D", subcase: 1, datatype: "Stress", component: "vonMises", goal: "MINIMIZE" }] });
    expect((j.params.responses as Record<string, unknown>[])[0]).not.toHaveProperty("bound");
  });

  it("메서드 변경 시 기본값·SQP 라벨, DOE면 메서드·고급 비활성 + 버튼 문구", async () => {
    renderApp(`${STUDY}/5`, { user: "power" });
    const run = await screen.findByRole("region", { name: "실행" });
    fireEvent.change(within(run).getByLabelText("Opt Method"), { target: { value: "GRSM" } });
    expect((within(run).getByLabelText("최대 설계 수") as HTMLInputElement).value).toBe("50");
    expect((within(run).getByLabelText("Absolute Convergence") as HTMLInputElement).disabled).toBe(true);
    fireEvent.change(within(run).getByLabelText("Opt Method"), { target: { value: "SQP" } });
    expect(within(run).getByText("Maximum Iterations")).toBeTruthy();
    expect((within(run).getByLabelText("Design Variable Convergence") as HTMLInputElement).value).toBe("0");
    fireEvent.click(within(run).getByRole("radio", { name: "DOE" }));
    expect((within(run).getByLabelText("Opt Method") as HTMLSelectElement).disabled).toBe(true);
    expect((within(run).getByLabelText("On Failed Evaluation") as HTMLSelectElement).disabled).toBe(true);
    expect(within(run).getByText("Number of Evaluations")).toBeTruthy();
    expect(within(run).getByRole("button", { name: "DOE 실행" })).toBeTruthy();
  });

  it("결과: 설계 이력 차트·완료 문구 / 진행 문구 OPT·DOE / 요약 없음 문구", async () => {
    const r1 = renderApp(`${STUDY}/5`, { user: "power" });
    expect(await screen.findByRole("img", { name: "설계 이력" })).toBeTruthy();
    expect(screen.getByTestId("opt-progress").textContent).toContain("완료 · run 25 / 25");
    r1.unmount();

    const prep = (fn: (s: MockServer) => void) => {
      const r = renderApp(`${STUDY}/5`, { user: "power" });
      fn(r.server);
      return r;
    };
    const r2 = prep((s) => Object.assign(s.p2.opts[0], { status: "RUNNING", runs_started: 12 }));
    await waitFor(() => expect(screen.getByTestId("opt-progress").textContent).toContain("run 12 / 25 시작"));
    r2.unmount();
    const r3 = prep((s) => Object.assign(s.p2.opts[0], { status: "RUNNING", runs_started: 12, approach: "DOE" }));
    await waitFor(() => expect(screen.getByTestId("opt-progress").textContent).toMatch(/run 12 시작/));
    r3.unmount();
    prep((s) => Object.assign(s.p2.opts[0], { summary_status: "UNRECOGNIZED" }));
    expect((await screen.findByTestId("summary-unknown")).textContent).toBe("결과 요약 형식 미확인 — 원본 파일 목록을 확인하세요");
    fireEvent.click(await screen.findByRole("button", { name: /opt_summary\.csv$/ }));
    expect(await screen.findByRole("table", { name: "opt_summary.csv" })).toBeTruthy();
  });
});
