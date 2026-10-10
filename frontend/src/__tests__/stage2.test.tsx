// phase2.md §20 V2-FE-3 (컴포넌트 시험, 목 서버)
import { describe, expect, it } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { renderApp, STUDY } from "../test/render";
import { isUsableComponent, timeSteps, timeStepsText } from "../lib/curation";

describe("V2-FE-3 ② 데이터 정리", () => {
  it("규칙: usable component, time step 미리보기 80자", () => {
    expect(isUsableComponent("vonMises")).toBe(true);
    expect(isUsableComponent("P1 (major)")).toBe(true);
    expect(isUsableComponent("Max Abs Principal")).toBe(false);
    expect(isUsableComponent("Extreme Value")).toBe(false);
    expect(timeSteps(5, 2)).toEqual([1, 3, 5]);
    expect(timeStepsText(5, 2)).toBe("Steps (3개): 1, 3, 5");
    const long = timeStepsText(400, 1);
    expect(long.length).toBeLessThanOrEqual(81);
    expect(long.startsWith("Steps (400개): 1, 2, 3")).toBe(true);
    expect(long.endsWith("…")).toBe(true);
  });

  it("원천 선택·Displacement 고정·usable만 콤보·time step·누락 run", async () => {
    renderApp(`${STUDY}/2`, { user: "power" });
    const counts = await screen.findByTestId("source-counts");
    await waitFor(() => expect(counts.textContent).toContain("기대 run 30"));
    expect(counts.textContent).toContain("h3d 24");
    const card = screen.getByRole("region", { name: "h3d 큐레이션" });
    const dtTable = await within(card).findByRole("table", { name: "DataType Component 표" });
    expect(within(dtTable).getByTestId("displacement-row").textContent).toContain("항상 포함");
    const dtOpts = Array.from((within(dtTable).getByLabelText("DataType 선택") as HTMLSelectElement).options).map((o) => o.value);
    expect(dtOpts).toEqual(["Stress", "Plastic Strain"]);
    const compOpts = Array.from((within(dtTable).getByLabelText("Component 선택") as HTMLSelectElement).options).map((o) => o.value);
    expect(compOpts).toEqual(["vonMises", "P1 (major)"]);
    fireEvent.change(within(card).getByLabelText("Time step 간격"), { target: { value: "2" } });
    expect(within(card).getByTestId("steps-preview").textContent).toMatch(/^Steps \(21개\): 1, 3, 5/);
    const res = within(card).getByTestId("curation-result");
    expect(res.textContent).toContain("성공 23/24");
    expect(res.textContent).toContain("누락 run 6");
    expect(res.textContent).toContain("③-1 데이터셋 생성의 기본 입력으로 연결됩니다");
  });

  it("큐레이션 실행: 선택·Part·간격·제외 파일이 params로", async () => {
    const { server } = renderApp(`${STUDY}/2`, { user: "power" });
    const card = await screen.findByRole("region", { name: "h3d 큐레이션" });
    const dtTable = await within(card).findByRole("table", { name: "DataType Component 표" });
    fireEvent.click(within(dtTable).getByRole("button", { name: "추가" }));
    fireEvent.click(within(card).getByLabelText("Shell 2"));
    fireEvent.change(within(card).getByLabelText("Time step 간격"), { target: { value: "3" } });
    fireEvent.click(within(card).getByText(/^파일 24\/24/));
    fireEvent.click(within(card).getByLabelText("run__00002/m_3/cushion_0000.h3d"));
    fireEvent.click(within(card).getByRole("button", { name: "큐레이션 실행" }));
    await waitFor(() => expect(server.jobs.some((j) => j.job_type === "CU_H3D_CURATE" && j.state === "QUEUED")).toBe(true));
    const j = server.jobs.find((x) => x.job_type === "CU_H3D_CURATE" && x.state === "QUEUED")!;
    expect(j.params).toMatchObject({
      source: { kind: "TRAIN_DOE", doe_id: "doe-1" },
      preview_job_id: "j-h3dprev",
      selection: { items: [{ datatype: "Stress", component: "vonMises" }], parts: { shell: [2], solid: [], rbody: [] }, time_increment: 3 },
      exclude_files: ["run__00002/m_3/cushion_0000.h3d"],
    });
  });

  it("곡선: series 있으면 SVG 그래프, 없으면 JSON 트리 + 형식 미확인", async () => {
    const { unmount } = renderApp(`${STUDY}/2`, { user: "power" });
    expect(await screen.findByTestId("curve-chart")).toBeTruthy();
    expect(screen.getByRole("img", { name: "첫 곡선" })).toBeTruthy();
    unmount();
    const s2 = renderApp(`${STUDY}/2`, { user: "power" }).server;
    s2.artifacts.filter((a) => a.kind === "CURVE_JSON" && a.job_id === "j-cur2").forEach((a) => (a.body = JSON.stringify({ curves: { foo: 1 } })));
    expect(await screen.findByTestId("curve-unknown")).toBeTruthy();
    expect(screen.getByText("곡선 형식 미확인")).toBeTruthy();
  });
});
