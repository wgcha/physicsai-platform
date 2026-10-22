// job-queues.md §8.2·V-JQ-15: GPU·CPU 대기열 분리 화면(칩·QueuePanel)
import { describe, expect, it } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { openStatusDrawer, renderApp, STUDY } from "../test/render";
import { moveToLane } from "../mock/queueV2";

async function openQueue(opts: Parameters<typeof renderApp>[1] = {}, setup?: Parameters<typeof renderApp>[2]) {
  const r = renderApp(`${STUDY}/3`, { queue: "demo", ...opts }, setup);
  await openStatusDrawer();
  const panel = await screen.findByRole("region", { name: "실행 대기열" });
  await waitFor(() => expect(within(panel).getAllByTestId("queue-row").length).toBeGreaterThan(0));
  return { ...r, panel, gpu: within(panel).getByTestId("queue-gpu"), cpu: within(panel).getByTestId("queue-cpu") };
}

describe("GPU·CPU 대기열 분리 (V-JQ-15)", () => {
  it("두 구역이 따로 렌더되고 칩에 GPU·CPU 개수가 나온다", async () => {
    const { panel, gpu, cpu } = await openQueue();
    expect(within(panel).getByRole("group", { name: "GPU 대기열" })).toBe(gpu);
    expect(within(panel).getByRole("group", { name: "CPU 대기열" })).toBe(cpu);
    // 구역 순서: GPU 위, CPU 아래
    expect(gpu.compareDocumentPosition(cpu) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByTestId("chip-queue").textContent).toBe("GPU 실행 1 · 대기 2 | CPU 실행 3/4 · 대기 3");
  });

  it("GPU: 실행 중 1건 + 대기 순번", async () => {
    const { gpu } = await openQueue();
    expect(within(gpu).getByText("1개씩 · 대기 2건")).toBeTruthy();
    const rows = within(gpu).getAllByTestId("queue-row");
    expect(rows.length).toBe(3);
    expect(rows[0].querySelector(".qrow-progress")).toBeTruthy(); // 실행 중 행만 진행률
    expect(rows.filter((r) => r.querySelector(".qrow-progress")).length).toBe(1);
    expect(rows.slice(1).map((r) => r.querySelector(".qpos")!.textContent)).toEqual(["1", "2"]);
  });

  it("CPU: 실행 n/한도와 자기 대기열 순번", async () => {
    const { cpu } = await openQueue();
    expect(within(cpu).getByText(/동시 4개 · 실행 3 · 대기 3건/)).toBeTruthy();
    const rows = within(cpu).getAllByTestId("queue-row");
    expect(rows.filter((r) => r.querySelector(".qrow-progress")).length).toBe(3);
    expect(rows.filter((r) => !r.querySelector(".qrow-progress")).map((r) => r.querySelector(".qpos")!.textContent)).toEqual(["1", "2", "3"]);
  });

  it("실행 중 행에 지금 단계를 짧게 표시", async () => {
    const { gpu, cpu } = await openQueue();
    expect(within(gpu).getByText(/55% · .* 경과 · 예측/)).toBeTruthy();
    expect(within(cpu).getByText(/30% · .* 경과 · 메싱/)).toBeTruthy();
    expect(within(cpu).getByText(/20% · .* 경과 · 메시 교체/)).toBeTruthy();
  });

  it("memory_gate = low 이면 CPU 구역에만 짧은 안내, ok·null이면 없음", async () => {
    const { cpu, gpu } = await openQueue();
    expect(within(cpu).getByTestId("queue-memory-gate").textContent).toContain("여유 메모리 부족으로 대기");
    expect(within(gpu).queryByTestId("queue-memory-gate")).toBeNull();
  });

  it("memory_gate = ok 이면 안내 없음", async () => {
    const { cpu } = await openQueue({}, (s) => {
      s.qv2.memoryGate = "ok";
    });
    expect(within(cpu).queryByTestId("queue-memory-gate")).toBeNull();
  });

  it("혼합 작업이 구간 경계에서 대기열을 옮기면 현재 있는 대기열에 이어서 · 진행률로 표시", async () => {
    const { server, gpu, cpu } = await openQueue();
    expect(within(gpu).getAllByTestId("queue-resumed").length).toBe(1); // g-q1(GPU 차례 대기)
    expect(within(cpu).getAllByTestId("queue-resumed").length).toBe(1); // c-q1(후처리 대기)
    expect(within(gpu).getByTestId("queue-resumed").textContent).toContain("이어서 · 40%");
    moveToLane(server, "g-q1", "CPU"); // 예측 끝 → CPU 후처리 대기열로
    await waitFor(() => expect(within(cpu).getAllByTestId("queue-resumed").length).toBe(2));
    expect(within(gpu).queryAllByTestId("queue-resumed").length).toBe(0);
    expect(within(gpu).getByText("1개씩 · 대기 1건")).toBeTruthy();
    expect(screen.getByTestId("chip-queue").textContent).toBe("GPU 실행 1 · 대기 1 | CPU 실행 3/4 · 대기 4");
    expect(within(cpu).getAllByTestId("queue-resumed")[0].textContent).toMatch(/이어서 · \d+%/);
  });

  it("관리자 ▲▼는 각 구역 안에서만 움직인다", async () => {
    const { server, gpu, cpu } = await openQueue();
    const cpuBefore = server.jobs.filter((j) => j.lane === "CPU" && j.state === "QUEUED").map((j) => j.queue_position);
    const up = within(gpu).getAllByRole("button", { name: "위로" });
    expect(up.length).toBe(2);
    expect((up[0] as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(up[1]);
    await waitFor(() => expect(server.jobs.find((j) => j.id === "g-q1")!.queue_position).toBe(1));
    expect(server.jobs.find((j) => j.id === "j-q1")!.queue_position).toBe(2);
    expect(server.jobs.filter((j) => j.lane === "CPU" && j.state === "QUEUED").map((j) => j.queue_position)).toEqual(cpuBefore);
    expect((within(cpu).getAllByRole("button", { name: "위로" })[0] as HTMLButtonElement).disabled).toBe(true);
  });

  it("옛 응답(gpu·cpu 없음)에서도 깨지지 않고 단일 대기열로 보인다", async () => {
    renderApp(`${STUDY}/3`, { queue: "legacy" });
    await openStatusDrawer();
    const panel = await screen.findByRole("region", { name: "실행 대기열" });
    await waitFor(() => expect(within(panel).getAllByTestId("queue-row").length).toBeGreaterThan(0));
    expect(within(panel).queryByTestId("queue-gpu")).toBeNull();
    expect(within(panel).queryByTestId("queue-cpu")).toBeNull();
    expect(within(panel).getByText("실행 중")).toBeTruthy();
    expect(within(panel).getByText("대기")).toBeTruthy();
    expect(screen.getByTestId("chip-queue").textContent).toMatch(/^대기열 실행 \d+ · 대기 \d+$/);
  });
});
