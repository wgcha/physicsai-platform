// v0.2.4 mcp.md §4.5 + v0.2.7 §23: "AI 연결(MCP)" 페이지의 토큰 영역(features.mcp일 때만) — 표·발급(평문 1회·복사·닫으면 상자 사라짐)·폐기(확인)·범위 비활성, 관리자 "API 토큰 관리".
// (AI 도구 등록·도구 목록·연결 시험은 aiConnection.test.tsx)
import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { renderApp } from "../test/render";
import type { MockServer } from "../mock/server";

const PAGE = "/me/ai-connection";
type Call = { m: string; p: string; b: Record<string, unknown> | null };
function record(server: MockServer, re: RegExp, methods = ["POST", "DELETE"]): Call[] {
  const calls: Call[] = [];
  const orig = server.handle.bind(server);
  server.handle = (m, p, q, b, h) => {
    if (methods.includes(m) && re.test(p)) calls.push({ m, p, b });
    return orig(m, p, q, b, h);
  };
  return calls;
}
const stubClipboard = () => {
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
  return writeText;
};
async function issue(name: string, scope?: RegExp) {
  const form = await screen.findByTestId("token-form");
  fireEvent.change(within(form).getByLabelText("토큰 이름"), { target: { value: name } });
  if (scope) fireEvent.click(within(form).getByRole("radio", { name: scope }));
  fireEvent.click(within(form).getByRole("button", { name: "발급" }));
}

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
  sessionStorage.clear();
});

describe("내 API 토큰(AI 연결 페이지 ②)", () => {
  it("표: 이름·범위·접두·만료·마지막 사용·상태(유효·만료·폐기)를 보인다", async () => {
    renderApp(PAGE, { user: "power" });
    const table = await screen.findByRole("table", { name: "내 API 토큰" });
    const row = await within(table).findByText("codex-내PC");
    expect(within(row.closest("tr")!).getByText("유효")).toBeTruthy();
    expect(within(row.closest("tr")!).getByText(/pai_a1b2c3d4/)).toBeTruthy();
    expect(within(row.closest("tr")!).getByText(/일 남음/)).toBeTruthy();
    expect(within(within(table).getByText("이전 토큰").closest("tr")!).getByText("만료")).toBeTruthy();
    expect(within(table).queryByText("ops-점검")).toBeNull(); // 남의 토큰은 안 보인다
  });

  it("발급: 평문은 한 번만 — 복사 버튼·'다시 볼 수 없음' 경고, 닫으면 사라지고 저장소에 남지 않는다", async () => {
    const writeText = stubClipboard();
    const { server } = renderApp(PAGE, { user: "power" });
    const calls = record(server, /\/me\/api-tokens$/);
    await issue("새-토큰", /^run/);
    const once = await screen.findByTestId("token-once");
    const plain = within(once).getByTestId("token-plain").textContent!;
    expect(plain).toMatch(/^pai_\w{8}_/);
    expect(calls[0].b).toMatchObject({ name: "새-토큰", scope: "run", expires_in_days: 30 });
    expect(within(once).getByText(/다시 볼 수 없습니다/)).toBeTruthy();
    // 표에는 접두만, 평문 전체는 없다
    const table = await screen.findByRole("table", { name: "내 API 토큰" });
    await within(table).findByText("새-토큰");
    expect(table.textContent).not.toContain(plain);
    fireEvent.click(within(once).getByRole("button", { name: "복사" }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(plain));
    await within(once).findByRole("button", { name: "복사됨" });
    expect(JSON.stringify(localStorage) + JSON.stringify(sessionStorage)).not.toContain(plain);
    fireEvent.click(within(once).getByRole("button", { name: /닫기/ }));
    expect(screen.queryByTestId("token-once")).toBeNull();
    // 1회 표시 상자는 사라지지만 같은 페이지의 ③ 설정에는 남는다(mcp.md §23.2 — 페이지를 떠나면 사라짐, aiConnection.test)
    expect(screen.queryByTestId("token-plain")).toBeNull();
  });

  it("범위 라디오: 일반 사용자는 run·admin이 이유와 함께 비활성, power는 run만 가능·admin 비활성", async () => {
    renderApp(PAGE, { user: "general" });
    const form = await screen.findByTestId("token-form");
    expect((within(form).getByRole("radio", { name: /^read/ }) as HTMLInputElement).disabled).toBe(false);
    expect((within(form).getByRole("radio", { name: /^run/ }) as HTMLInputElement).disabled).toBe(true);
    expect((within(form).getByRole("radio", { name: /^admin/ }) as HTMLInputElement).disabled).toBe(true);
    expect(within(form).getByTestId("scope-reason-run").textContent).toMatch(/power/);
    expect(within(form).getByTestId("scope-reason-admin").textContent).toMatch(/전역 관리자/);
  });

  it("범위 라디오: power는 run 가능, admin은 비활성 / 전역 관리자는 admin도 가능", async () => {
    const a = renderApp(PAGE, { user: "power" });
    let form = await screen.findByTestId("token-form");
    expect((within(form).getByRole("radio", { name: /^run/ }) as HTMLInputElement).disabled).toBe(false);
    expect((within(form).getByRole("radio", { name: /^admin/ }) as HTMLInputElement).disabled).toBe(true);
    a.unmount();
    renderApp(PAGE, { user: "admin" });
    form = await screen.findByTestId("token-form");
    expect((within(form).getByRole("radio", { name: /^admin/ }) as HTMLInputElement).disabled).toBe(false);
  });

  it("만료일: 30 초과면 발급 비활성(기본 30)", async () => {
    renderApp(PAGE, { user: "power" });
    const form = await screen.findByTestId("token-form");
    const days = within(form).getByLabelText("만료일 수") as HTMLInputElement;
    expect(days.value).toBe("30");
    fireEvent.change(within(form).getByLabelText("토큰 이름"), { target: { value: "x" } });
    expect((within(form).getByRole("button", { name: "발급" }) as HTMLButtonElement).disabled).toBe(false);
    fireEvent.change(days, { target: { value: "31" } });
    expect((within(form).getByRole("button", { name: "발급" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("오류: 이름 중복·한도 초과를 한국어로 보인다", async () => {
    renderApp(PAGE, { user: "power" });
    await issue("codex-내PC"); // 이미 유효한 같은 이름
    expect((await screen.findByRole("alert", { name: "" })).textContent).toMatch(/같은 이름/);
    // 한도(5개): 3개 더 발급 → 유효 5개
    for (const n of ["t3", "t4", "t5"]) {
      await issue(n);
      fireEvent.click(await within(await screen.findByTestId("token-once")).findByRole("button", { name: /닫기/ }));
    }
    await issue("t6");
    await waitFor(() => expect(screen.getAllByRole("alert").some((e) => /5개까지/.test(e.textContent ?? ""))).toBe(true));
  });

  it("폐기: 확인 대화상자 뒤 DELETE, 표 상태가 '폐기'로", async () => {
    const { server } = renderApp(PAGE, { user: "power" });
    const calls = record(server, /\/me\/api-tokens\/[^/]+$/);
    const table = await screen.findByRole("table", { name: "내 API 토큰" });
    const row = (await within(table).findByText("codex-내PC")).closest("tr")!;
    fireEvent.click(within(row).getByRole("button", { name: "폐기" }));
    const dlg = await screen.findByRole("dialog");
    expect(calls).toHaveLength(0);
    fireEvent.click(within(dlg).getByRole("button", { name: "폐기" }));
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]).toMatchObject({ m: "DELETE", p: expect.stringContaining("/me/api-tokens/a1b2c3d4") });
    await waitFor(() => expect(within(within(table).getByText("codex-내PC").closest("tr")!).getByText("폐기", { selector: "span" })).toBeTruthy());
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});

describe("메뉴 노출(features.mcp)", () => {
  it("켜져 있으면 상단 바에 'AI 연결(MCP)' 링크(옛 '내 API 토큰' 대체)", async () => {
    renderApp("/", { user: "power" });
    const link = await screen.findByRole("link", { name: "AI 연결(MCP)" });
    expect(link.getAttribute("href")).toBe("/me/ai-connection");
    expect(screen.queryByRole("link", { name: "내 API 토큰" })).toBeNull();
  });
  it("꺼져 있으면 메뉴가 없고 페이지는 꺼짐 안내", async () => {
    const a = renderApp("/", { user: "power", disabledFeatures: ["mcp"] });
    await screen.findByText("대시보드로");
    await waitFor(() => expect(screen.queryByRole("link", { name: "AI 연결(MCP)" })).toBeNull());
    a.unmount();
    renderApp(PAGE, { user: "power", disabledFeatures: ["mcp"] });
    expect(await screen.findByTestId("mcp-off")).toBeTruthy();
  });
});

describe("API 토큰 관리(전역 관리자)", () => {
  it("관리 메뉴에 항목, 목록은 모든 사용자 토큰 + user_id·active 필터 + 폐기", async () => {
    const { server } = renderApp("/admin/api-tokens", { user: "admin" });
    const calls = record(server, /\/admin\/api-tokens\/[^/]+\/revoke$/);
    const table = await screen.findByRole("table", { name: "API 토큰 관리" });
    await within(table).findByText("codex-내PC");
    expect(within(table).getByText("ops-점검")).toBeTruthy();
    expect(within(table).getByText("gemini")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("유효 필터"), { target: { value: "true" } });
    await waitFor(() => expect(within(table).queryByText("gemini")).toBeNull());
    expect(within(table).queryByText("이전 토큰")).toBeNull();
    fireEvent.change(screen.getByLabelText("사용자 id 필터"), { target: { value: "u-admin" } });
    await waitFor(() => expect(within(table).queryByText("codex-내PC")).toBeNull());
    const row = within(table).getByText("ops-점검").closest("tr")!;
    fireEvent.click(within(row).getByRole("button", { name: "폐기" }));
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "폐기" }));
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0].p).toContain("/admin/api-tokens/0a1b2c3d/revoke");
  });
  it("일반·power 사용자에게는 관리자 전용 안내", async () => {
    renderApp("/admin/api-tokens", { user: "power" });
    expect((await screen.findByRole("alert")).textContent).toMatch(/관리자 전용/);
  });
  it("관리 메뉴에 'API 토큰 관리' 항목", async () => {
    renderApp("/", { user: "admin" });
    fireEvent.click(await screen.findByRole("button", { name: /^관리/ }));
    expect(await screen.findByRole("menuitem", { name: "API 토큰 관리" })).toBeTruthy();
  });
});
