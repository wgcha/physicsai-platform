// v0.2.1 핫픽스: ①-1 CAD 경로 확인은 선택한 엔진(engine)으로 확장자를 검사한다 — native는 .step/.stp, altair는 .prt.
import { describe, expect, it } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { renderApp, STUDY } from "../test/render";
import { recordCalls } from "../test/recordCalls";

const STEP = "E:/shared/AI_WORK/cushion/00_inbox/cad/base.step";
const PRT = "E:/shared/AI_WORK/cushion/00_inbox/cad/base.prt";

async function openCard(opts: { geometryDefault?: "altair" | "native" } = {}) {
  const utils = renderApp(`${STUDY}/1`, { user: "power", geometry: "native", ...opts });
  const card = await screen.findByRole("region", { name: "CAD 파라미터 추출" });
  const input = () => within(card).getByRole("textbox") as HTMLInputElement;
  const check = async () => {
    fireEvent.click(within(card).getByRole("button", { name: "확인" }));
    await waitFor(() => expect(within(card).queryByRole("button", { name: "확인 중…" })).toBeNull());
  };
  const type = (v: string) => fireEvent.change(input(), { target: { value: v } });
  const run = () => within(card).getByRole("button", { name: "파라미터 추출" }) as HTMLButtonElement;
  const pick = (name: string) => fireEvent.click(within(card).getByRole("radio", { name }));
  return { ...utils, card, check, type, run, pick };
}

describe("① CAD 경로 확인 — 엔진별 확장자", () => {
  it("native + .step → 확인 통과, 실행 가능, 요청에 engine=native", async () => {
    const { card, check, type, run, server } = await openCard({ geometryDefault: "native" });
    const bodies: unknown[] = [];
    const orig = server.handle.bind(server);
    server.handle = (m, p, q, b, h) => (p.endsWith("/paths/inspect") && bodies.push(b), orig(m, p, q, b, h));
    expect(within(card).getByLabelText("CAD 파일 경로 (.step)")).toBeTruthy();
    type(STEP);
    await check();
    expect(within(card).queryByText(/확장자 불가/)).toBeNull();
    await waitFor(() => expect(run().disabled).toBe(false));
    expect(bodies[0]).toMatchObject({ purpose: "CAD_FILE", engine: "native" });
  });

  it("native + .prt → 확장자 불가(STEP_EXTENSION), 실행 불가", async () => {
    const { card, check, type, run } = await openCard({ geometryDefault: "native" });
    type(PRT);
    await check();
    expect(within(card).getByText(/확장자 불가/)).toBeTruthy();
    expect(within(card).getByText("STEP_EXTENSION")).toBeTruthy();
    expect(run().disabled).toBe(true);
  });

  it("altair + .prt → 통과, .step → CAD_EXTENSION (기존 동작)", async () => {
    const { card, check, type, run } = await openCard({ geometryDefault: "altair" });
    type(PRT);
    await check();
    expect(within(card).queryByText(/확장자 불가/)).toBeNull();
    await waitFor(() => expect(run().disabled).toBe(false));
    type(STEP); // 경로를 고치면 확인 결과 초기화
    expect(run().disabled).toBe(true);
    await check();
    expect(within(card).getByText("CAD_EXTENSION")).toBeTruthy();
    expect(run().disabled).toBe(true);
  });

  it("엔진 전환 시 확인 결과를 초기화하고 같은 경로를 새 엔진 기준으로 재확인", async () => {
    const { card, check, type, run, pick, server } = await openCard({ geometryDefault: "altair" });
    type(STEP);
    await check();
    expect(within(card).getByText("CAD_EXTENSION")).toBeTruthy();
    const calls = recordCalls(server);
    pick("Native");
    await waitFor(() => expect(within(card).queryByText("CAD_EXTENSION")).toBeNull());
    await waitFor(() => expect(run().disabled).toBe(false));
    expect(calls.filter((c) => c.endsWith("/paths/inspect"))).toHaveLength(1);
    // 되돌리면 다시 altair 기준 불가
    pick("Altair");
    await waitFor(() => expect(within(card).getByText("CAD_EXTENSION")).toBeTruthy());
    expect(run().disabled).toBe(true);
  });

  it("확인 전에 엔진을 바꾸면 재확인 요청을 보내지 않는다", async () => {
    const { pick, server, type } = await openCard({ geometryDefault: "altair" });
    type(STEP);
    const calls = recordCalls(server);
    pick("Native");
    await new Promise((r) => setTimeout(r, 50));
    expect(calls.filter((c) => c.endsWith("/paths/inspect"))).toHaveLength(0);
  });
});
