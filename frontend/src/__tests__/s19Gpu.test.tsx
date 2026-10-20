// V3-S19-13(s19_followup.md §24.3): GPU 조회 실패 툴팁·서랍 gpu-message·연속 실패 줄. (GPU 동시 예측 레인 화면은 사용자 결정으로 철회)
import { afterEach, describe, expect, it } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import { openStatusDrawer, renderApp, STUDY } from "../test/render";
import type { MockServer } from "../mock/server";
import type { Resources } from "../api";
import { clockText, gpuFailTip, gpuStreakText } from "../shell/gpuText";

/** GET 응답 본문을 고쳐 돌려주는 목 서버 훅 */
function patchGet(server: MockServer, path: string, fn: (body: Record<string, unknown>) => void) {
  const orig = server.handle.bind(server);
  server.handle = (m, p, q, b, h) => {
    const r = orig(m, p, q, b, h);
    if (m === "GET" && p === path && r.status === 200) fn(r.body as Record<string, unknown>);
    return r;
  };
}
const NEXT = "2026-10-19T09:30:15";
const failing = (over: Record<string, unknown>) => (server: MockServer) =>
  patchGet(server, "/resources", (b) => Object.assign(b, { gpu: [], gpu_status: "ERROR", gpu_message: "nvidia-smi 응답 시간 초과(15초): nvidia-smi", gpu_fail_streak: 1, gpu_next_query_at: null, ...over }));

describe("V3-S19-13 gpuFailTip·문구 순수 함수", () => {
  it("ERROR·NOT_FOUND만 문구, streak ≥ 2면 연속 횟수·다음 조회 시각, 다음 시각 없으면 `· …` 생략, OK·없음은 null", () => {
    const base = { gpu_message: "응답 시간 초과(15초)", gpu_fail_streak: 0, gpu_next_query_at: null } as const;
    expect(gpuFailTip({ ...base, gpu_status: "ERROR" })).toBe("GPU 조회 실패 — 응답 시간 초과(15초)");
    expect(gpuFailTip({ ...base, gpu_status: "ERROR", gpu_fail_streak: 1 })).toBe("GPU 조회 실패 — 응답 시간 초과(15초)");
    expect(gpuFailTip({ ...base, gpu_status: "ERROR", gpu_fail_streak: 3, gpu_next_query_at: NEXT })).toBe("GPU 조회 실패 — 응답 시간 초과(15초) (연속 3회 · 다음 조회 09:30:15)");
    expect(gpuFailTip({ ...base, gpu_status: "ERROR", gpu_fail_streak: 2 })).toBe("GPU 조회 실패 — 응답 시간 초과(15초) (연속 2회)");
    expect(gpuFailTip({ ...base, gpu_status: "NOT_FOUND", gpu_message: "nvidia-smi를 찾지 못했습니다", gpu_fail_streak: 4, gpu_next_query_at: NEXT })).toBe("GPU 없음 — nvidia-smi를 찾지 못했습니다 (연속 4회 · 다음 조회 09:30:15)");
    expect(gpuFailTip({ ...base, gpu_status: "OK", gpu_fail_streak: 5 })).toBeNull();
    expect(gpuFailTip({ gpu_status: null })).toBeNull();
    expect(gpuFailTip({})).toBeNull(); // 옛 워커 표본(키 없음)
    expect(clockText("not a date")).toBeNull();
    expect(gpuStreakText({ gpu_fail_streak: 1 })).toBeNull();
    expect(gpuStreakText({ gpu_fail_streak: 3, gpu_next_query_at: NEXT })).toBe("연속 3회 실패 · 다음 조회 09:30:15");
    expect(gpuStreakText({ gpu_fail_streak: 3 })).toBe("연속 3회 실패");
  });
});

describe("V3-S19-13 상단 자원 칩·서랍", () => {
  afterEach(() => localStorage.clear());

  it("평소(OK): 칩 title = 워커 자원 열기, 서랍에 gpu-message 없음", async () => {
    renderApp(`${STUDY}/3`, { user: "power" });
    const chip = await screen.findByTestId("chip-resources");
    await waitFor(() => expect(chip.textContent).toMatch(/GPU \d+%/));
    expect(chip.getAttribute("title")).toBe("워커 자원 열기");
    await openStatusDrawer();
    const panel = await screen.findByRole("region", { name: "워커 자원" });
    expect(within(panel).queryByTestId("gpu-message")).toBeNull();
  });

  it("ERROR 연속 3회: 칩 title에 연속 횟수·다음 조회 시각, 칩 문구는 GPU —, 서랍에 회색 줄 2개", async () => {
    renderApp(`${STUDY}/3`, { user: "power" }, failing({ gpu_fail_streak: 3, gpu_next_query_at: NEXT }));
    const chip = await screen.findByTestId("chip-resources");
    await waitFor(() => expect(chip.getAttribute("title")).toContain("GPU 조회 실패"));
    expect(chip.getAttribute("title")).toBe("GPU 조회 실패 — nvidia-smi 응답 시간 초과(15초): nvidia-smi (연속 3회 · 다음 조회 09:30:15)");
    expect(chip.textContent).toMatch(/GPU —/);
    await openStatusDrawer();
    const panel = await screen.findByRole("region", { name: "워커 자원" });
    expect((await within(panel).findByTestId("gpu-none")).textContent).toBe("GPU 정보 없음 — nvidia-smi 실행에 실패했습니다");
    const msg = within(panel).getByTestId("gpu-message");
    expect(msg.textContent).toBe("nvidia-smi 응답 시간 초과(15초): nvidia-smi");
    expect(msg.className).toContain("muted");
    expect(within(panel).getByTestId("gpu-streak").textContent).toBe("연속 3회 실패 · 다음 조회 09:30:15");
  });

  it("NOT_FOUND 첫 실패: 앞말 `GPU 없음 — `, 연속 줄 없음", async () => {
    renderApp(`${STUDY}/3`, { user: "power" }, failing({ gpu_status: "NOT_FOUND", gpu_message: "nvidia-smi를 찾지 못했습니다(시도: nvidia-smi)" }));
    const chip = await screen.findByTestId("chip-resources");
    await waitFor(() => expect(chip.getAttribute("title")).toContain("GPU 없음"));
    expect(chip.getAttribute("title")).toBe("GPU 없음 — nvidia-smi를 찾지 못했습니다(시도: nvidia-smi)");
    await openStatusDrawer();
    const panel = await screen.findByRole("region", { name: "워커 자원" });
    expect((await within(panel).findByTestId("gpu-message")).textContent).toContain("시도: nvidia-smi");
    expect(within(panel).queryByTestId("gpu-streak")).toBeNull();
  });

  it("목 /resources 모양: 새 키 3개(기본값)", async () => {
    const { server } = renderApp(`${STUDY}/3`, { user: "power" });
    const r = server.handle("GET", "/resources", new URLSearchParams(), null, new Headers()).body as Resources;
    expect(r).toMatchObject({ gpu_fail_streak: 0, gpu_next_query_at: null });
    expect(typeof r.gpu_sampled_at).toBe("string");
  });
});
