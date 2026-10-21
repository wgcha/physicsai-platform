// 3D 패널 청크(GeomView3D) 적재 실패(이전 캐시·네트워크) → 빈 패널 대신 그림 폴백 + 이유 + [다시 시도] (geometry-view.md §7.4)
import { describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { renderApp, STUDY } from "../test/render";
import { nativeTrainParams } from "../mock/geometry";
import { setGvMode } from "../mock/geomView";

vi.mock("../stages/stage4/geomview/GeomView3D", () => {
  throw new TypeError("Failed to fetch dynamically imported module: /assets/GeomView3D-old.js");
});

describe("3D 패널 청크 로드 실패", () => {
  it("①-2: 이유 한 줄(이전 캐시·네트워크) + 선택 변수 그림 + 다시 시도 + 진단", async () => {
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({} as never);
    renderApp(`${STUDY}/1`, { user: "power" }, (s) => {
      Object.assign(s.p2.setups["s-cushion"], { engine: "native", parameters: nativeTrainParams(), tpl: null, extract_job_id: "j-x" });
      setGvMode(s, {});
    });
    const table = await screen.findByRole("table", { name: "파라미터 표" });
    await waitFor(() => expect(screen.getByTestId("gv-fallback").textContent).toContain("3D 화면 모듈을 불러오지 못해 그림으로 표시합니다(네트워크 또는 이전 캐시"));
    expect(screen.getByRole("button", { name: "다시 시도" })).toBeTruthy();
    expect(screen.getByTestId("gv-diag").textContent).toContain("마지막 오류: chunk");
    fireEvent.click(table.querySelector('tr[data-row="CUSH_L_THK_1"]')!);
    expect(await screen.findByTestId("feature-png")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "다시 시도" })); // 다시 받아도 같은 실패 → 폴백 유지(빈 패널 없음)
    await waitFor(() => expect(screen.getByTestId("gv-fallback").textContent).toContain("3D 화면 모듈을 불러오지 못해"));
  });
});
