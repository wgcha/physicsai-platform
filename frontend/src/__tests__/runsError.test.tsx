// 재발 방지: run 목록 조회 실패를 삼키지 않고 ①-4에 한 줄로 보여준다 + 목 서버의 limit 상한 422
import { describe, expect, it } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import { renderApp, STUDY } from "../test/render";
import { MockServer } from "../mock/server";

const H = new Headers();

describe("목 서버 limit 상한(openapi maximum)", () => {
  it("train-does runs: 500은 422 INVALID_PARAMS, 200은 통과", () => {
    const s = new MockServer({ user: "power" });
    const doeId = s.p2.does[0].id;
    const over = s.handle("GET", `/train-does/${doeId}/runs`, new URLSearchParams({ limit: "500" }), null, H);
    expect(over.status).toBe(422);
    expect((over.body as { detail: { code: string } }).detail.code).toBe("INVALID_PARAMS");
    expect(s.handle("GET", `/train-does/${doeId}/runs`, new URLSearchParams({ limit: "200" }), null, H).status).toBe(200);
    expect(s.handle("GET", `/train-does/${doeId}/runs`, new URLSearchParams({ limit: "0" }), null, H).status).toBe(422);
    // 상한이 큰 경로(jobs/{id}/log 262144)와 limit 없는 호출은 영향 없음
    expect(s.handle("GET", `/train-does/${doeId}/runs`, new URLSearchParams(), null, H).status).toBe(200);
  });
});

describe("① run 목록 조회 실패 표시", () => {
  it("runs 조회 실패 시 '불러오지 못했습니다 — 메시지' 한 줄, 제출 비활성 사유가 그 문구를 우선한다", async () => {
    renderApp(`${STUDY}/1`, { user: "power", hpcConfigured: true }, (srv) => {
      for (const j of srv.jobs) if (j.job_type === "TD_SOLVE") j.state = "SUCCEEDED"; // 실행 중이면 버튼 title이 '이미 실행 중'이 된다
      const orig = srv.handle.bind(srv);
      srv.handle = (m, p, q, b, h) =>
        m === "GET" && /^\/train-does\/[^/]+\/runs$/.test(p)
          ? { status: 422, body: { detail: { code: "INVALID_PARAMS", message: "요청 값이 올바르지 않습니다" } } }
          : orig(m, p, q, b, h);
    });
    const card = await screen.findByRole("region", { name: "PBS 해석 제출" });
    const line = await within(card).findByTestId("runs-error");
    expect(line.textContent).toBe("run 목록을 불러오지 못했습니다 — 요청 값이 올바르지 않습니다");
    expect(within(card).queryByText("제출할 run이 없습니다")).toBeNull();
    const btn = await within(card).findByRole("button", { name: "PBS 제출" });
    await waitFor(() => expect((btn as HTMLButtonElement).title).toBe(line.textContent));
    expect((btn as HTMLButtonElement).disabled).toBe(true);
  });
});
