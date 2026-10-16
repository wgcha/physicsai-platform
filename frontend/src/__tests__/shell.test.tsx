import { describe, expect, it } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import { renderApp, STUDY } from "../test/render";

describe("공통 셸 (V-FE-1, V-FE-7)", () => {
  it("경로바·스텝퍼·우측 패널 3종을 그린다", async () => {
    renderApp(`${STUDY}/3`, { user: "power" });
    const nav = await screen.findByRole("navigation", { name: "경로" });
    expect(within(nav).getByText("AI 예측")).toBeTruthy();
    expect(await within(nav).findByText("쿠션 두께·리브 예측")).toBeTruthy();
    expect(within(nav).getByText(/데이터셋·모델/)).toBeTruthy();
    expect(screen.getByRole("region", { name: "실행 대기열" })).toBeTruthy();
    expect(screen.getByRole("region", { name: "워커 자원" })).toBeTruthy();
    expect(screen.getByRole("region", { name: "모델 목록" })).toBeTruthy();
    const stepper = screen.getByRole("list", { name: "단계" });
    expect(within(stepper).queryAllByText("2차")).toHaveLength(0);
    expect(within(stepper).getAllByRole("link")).toHaveLength(5);
  });

  it("V2-FE-1: ①②⑤도 실제 화면(2차 안내 없음)", async () => {
    renderApp(`${STUDY}/1`, { user: "power" });
    expect(await screen.findByRole("region", { name: "CAD 파라미터 추출" })).toBeTruthy();
    expect(screen.queryByText("2차에서 제공 예정입니다.")).toBeNull();
  });

  it("401이면 대시보드 로그인 안내", async () => {
    renderApp(`${STUDY}/3`, { user: "anon" });
    expect(await screen.findByText("대시보드에서 로그인하세요")).toBeTruthy();
    expect(screen.getByRole("link", { name: "대시보드로 이동" }).getAttribute("href")).toBe("/");
  });

  it("phase3 D3-38: 상단 바 '대시보드로'는 /status.auth.login_url과 같은 값", async () => {
    renderApp(`${STUDY}/3`, { user: "power", loginUrl: "/home/" });
    await screen.findByRole("navigation", { name: "경로" });
    const link = screen.getByRole("link", { name: "대시보드로" });
    await waitFor(() => expect(link.getAttribute("href")).toBe("/home/"));
    expect(localStorage.getItem("physicsai.loginUrl")).toBe("/home/");
    localStorage.removeItem("physicsai.loginUrl");
  });

  it("demo=true면 상단 바에 '시연 모드' 배지, 기본은 없음", async () => {
    const r = renderApp(`${STUDY}/3`, { user: "power", demo: true });
    expect((await screen.findByTestId("demo-badge")).textContent).toBe("시연 모드");
    r.unmount();
    renderApp(`${STUDY}/3`, { user: "power" });
    await screen.findByRole("navigation", { name: "경로" });
    await screen.findByText("쿠션 두께·리브 예측", { selector: ".crumb a" });
    expect(screen.queryByTestId("demo-badge")).toBeNull();
  });

  it("phase3 D3-45: GPU 목록이 비면 회색 한 줄(숨기지 않음), 있으면 GPU 막대", async () => {
    const first = renderApp(`${STUDY}/3`, { user: "power" });
    let panel = await screen.findByRole("region", { name: "워커 자원" });
    expect(await within(panel).findByRole("meter", { name: "GPU" })).toBeTruthy();
    expect(within(panel).queryByTestId("gpu-none")).toBeNull();
    first.unmount();
    renderApp(`${STUDY}/3`, { user: "power" }, (server) => {
      const orig = server.handle.bind(server);
      server.handle = (m, p, q, b, h) => {
        const r = orig(m, p, q, b, h);
        if (m === "GET" && p === "/resources" && r.status === 200)
          return { ...r, body: { ...(r.body as object), gpu: [], gpu_status: "NOT_FOUND", gpu_message: "nvidia-smi를 찾지 못했습니다(시도: nvidia-smi)" } };
        return r;
      };
    });
    panel = await screen.findByRole("region", { name: "워커 자원" });
    const none = await within(panel).findByTestId("gpu-none");
    expect(none.textContent).toBe("GPU 정보 없음 — nvidia-smi를 찾지 못했습니다");
    expect(none.className).toContain("muted");
    expect(none.getAttribute("title")).toContain("시도: nvidia-smi");
    expect(within(panel).queryByRole("meter", { name: "GPU" })).toBeNull();
  });

  it("phase3 D3-45: gpuNoneText 상태별 문구", async () => {
    const { gpuNoneText } = await import("../panels/WorkerResourcePanel");
    expect(gpuNoneText({ gpu_status: "NOT_FOUND" })).toBe("GPU 정보 없음 — nvidia-smi를 찾지 못했습니다");
    expect(gpuNoneText({ gpu_status: "ERROR" })).toBe("GPU 정보 없음 — nvidia-smi 실행에 실패했습니다");
    expect(gpuNoneText({ gpu_status: null })).toBe("GPU 정보 없음");
  });
});
