// v0.2.7 mcp.md §23 / V-MCP-21~26: "AI 연결(MCP)" 페이지 — 상태(url_source 짐작 배지)·토큰(자리표시자 → 발급 후 채움 → 이탈하면 다시 자리표시자)·
// AI 도구 4탭 설정(복사·평문 경고·대안 접힘·stdio 안내)·도구 목록(접힘·범위)·연결 시험·/me/api-tokens 리다이렉트·메뉴·저장소 미사용(정적).
import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { renderApp } from "../test/render";
import { parseToml, shellSplit } from "../test/configParse";
import { TOKEN_PLACEHOLDER } from "../lib/mcpSetup";
import aiConnectionSrc from "../pages/AiConnection.tsx?raw";
import apiTokensSrc from "../pages/ApiTokens.tsx?raw";
import mcpSetupSrc from "../lib/mcpSetup.ts?raw";

const PAGE = "/me/ai-connection";
const TABS = ["claudeCode", "desktop", "codex", "gemini"] as const;
const TAB_NAME = { claudeCode: "Claude Code", desktop: "Claude Desktop", codex: "Codex CLI", gemini: "Gemini CLI" } as const;
const cfg = (tab: (typeof TABS)[number]) => screen.getByTestId(`cfg-${tab}`).textContent ?? "";
const openTab = (tab: (typeof TABS)[number]) => fireEvent.click(screen.getByRole("tab", { name: TAB_NAME[tab] }));
async function issue(name = "web-시험", scope?: RegExp) {
  const form = await screen.findByTestId("token-form");
  fireEvent.change(within(form).getByLabelText("토큰 이름"), { target: { value: name } });
  if (scope) fireEvent.click(within(form).getByRole("radio", { name: scope }));
  fireEvent.click(within(form).getByRole("button", { name: "발급" }));
  return (await screen.findByTestId("token-plain")).textContent!;
}

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
  sessionStorage.clear();
});

describe("③ AI 도구에 등록하기 — 자리표시자 → 발급 후 채움 (V-MCP-21)", () => {
  it("발급 전 4탭 모두 ‹발급받은_토큰›, 발급 직후 같은 자리에 그 토큰, 페이지를 떠났다 오면 다시 자리표시자", async () => {
    const a = renderApp(PAGE, { user: "power" });
    await screen.findByTestId("mcp-url");
    for (const t of TABS) {
      openTab(t);
      expect(cfg(t)).toContain(TOKEN_PLACEHOLDER);
      expect(cfg(t)).not.toContain("pai_");
    }
    const plain = await issue();
    for (const t of TABS) {
      openTab(t);
      expect(cfg(t)).toContain(plain);
      expect(cfg(t)).not.toContain(TOKEN_PLACEHOLDER);
    }
    // 1회 표시 상자를 닫아도 페이지를 떠나기 전까지 ③ 채움 유지
    fireEvent.click(within(screen.getByTestId("token-once")).getByRole("button", { name: /닫기/ }));
    expect(cfg("gemini")).toContain(plain);
    a.unmount();
    renderApp(PAGE, { user: "power" });
    await screen.findByTestId("mcp-url");
    expect(cfg("claudeCode")).toContain(TOKEN_PLACEHOLDER);
    expect(document.body.textContent).not.toContain(plain);
  });

  it("탭 4종 설정 문법: Claude Code 셸 분해·Desktop/Gemini JSON·Codex TOML(서버 주소 = /mcp/connection의 url·api_base)", async () => {
    renderApp(PAGE, { user: "power" });
    const url = (await screen.findByTestId("mcp-url")).textContent!;
    expect(url).toBe(`${window.location.origin}/physicsai/mcp`);
    const plain = await issue();
    openTab("claudeCode");
    expect(shellSplit(cfg("claudeCode"))).toEqual(["claude", "mcp", "add", "--transport", "http", "physicsai", url, "--header", `Authorization: Bearer ${plain}`]);
    openTab("desktop");
    const bridge = { command: "npx", args: ["-y", "mcp-remote", url, "--allow-http", "--header", "Authorization:${AUTH}"], env: { AUTH: `Bearer ${plain}`, NODE_OPTIONS: "--use-system-ca" } };
    expect(JSON.parse(`{${cfg("desktop")}}`).physicsai).toEqual(bridge);
    openTab("codex");
    expect((parseToml(cfg("codex")) as { mcp_servers: { physicsai: unknown } }).mcp_servers.physicsai).toEqual(bridge);
    openTab("gemini");
    expect(JSON.parse(`{${cfg("gemini")}}`).physicsai).toEqual(bridge);
    // Gemini 안내: Windows 경로 예시 + 파일이 없을 때 새로 만드는 방법
    const where = within(screen.getByTestId("mcp-pane-gemini")).getByText(/\.gemini\\settings\.json/).textContent!;
    expect(where).toContain("C:\\Users\\<사용자>\\.gemini\\settings.json");
    expect(where).toContain("파일이 없으면 새로 만들고");
    expect(where).toContain('{ "mcpServers": { … } }');
    expect(where).not.toContain("~/.gemini");
  });

  it("평문 경고 한 줄·Node.js 안내·접힌 stdio 대안(토큰 파일, pai_ 없음, 실행기 안내 stdio_hint)", async () => {
    renderApp(PAGE, { user: "admin" });
    await screen.findByTestId("mcp-url");
    expect(screen.getByTestId("plain-warning").textContent).toContain("설정 파일에 평문으로 남습니다");
    const alt = screen.getByTestId("alt-details") as HTMLDetailsElement;
    expect(alt.open).toBe(false);
    expect(alt.textContent).toContain("Node.js를 쓸 수 없는 PC");
    expect(screen.getByTestId("node-note").textContent).toBe("Claude Code를 뺀 셋은 Node.js가 필요합니다(npx 사용).");
    openTab("desktop");
    expect(screen.getByTestId("cfg-desktop").textContent).toContain("mcp-remote"); // 기본 화면은 브리지
    expect(screen.getByTestId("cfg-desktop").textContent).not.toContain("physicsai-mcp");
    const hint = screen.getByTestId("stdio-hint").textContent!;
    expect(hint).toContain("physicsai-mcp");
    expect(hint).toContain("physicsai-mcp.exe"); // 전역 관리자에게는 서버 venv 경로(command_path)
    expect(hint).toContain("Node.js");
    expect(screen.getByTestId("alt-desktop").textContent).toContain("PHYSICSAI_MCP_TOKEN_FILE");
    openTab("codex");
    expect(screen.getByTestId("alt-codex").textContent).toContain("physicsai_stdio");
    expect(alt.textContent).not.toContain("pai_");
    openTab("claudeCode");
    expect(screen.getByTestId("alt-claudeCode-json").textContent).toContain("${PHYSICSAI_MCP_TOKEN}");
    expect(screen.getByTestId("alt-claudeCode-stdio").textContent).toContain("-- physicsai-mcp");
  });

  it("복사: 성공하면 '복사됨', 클립보드가 막혀 있고 선택 복사도 안 되면 '복사됨'을 띄우지 않는다", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    renderApp(PAGE, { user: "power" });
    await screen.findByTestId("mcp-url");
    const btn = () => within(screen.getByTestId("mcp-pane-claudeCode")).getAllByRole("button", { name: /^Claude Code 복사/ })[0];
    fireEvent.click(btn());
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(cfg("claudeCode")));
    await within(screen.getByTestId("mcp-pane-claudeCode")).findByRole("button", { name: "복사됨" });
    // 실패: 클립보드 거부 + execCommand 없음
    Object.defineProperty(navigator, "clipboard", { value: { writeText: vi.fn().mockRejectedValue(new Error("denied")) }, configurable: true });
    openTab("gemini");
    openTab("claudeCode");
    fireEvent.click(btn());
    await new Promise((r) => setTimeout(r, 30));
    expect(within(screen.getByTestId("mcp-pane-claudeCode")).queryByRole("button", { name: "복사됨" })).toBeNull();
  });
});

describe("① 상태", () => {
  it("url_source = config면 '짐작' 배지 없음, guess면 '짐작' 배지, HTTP 꺼짐이면 안내", async () => {
    const a = renderApp(PAGE, { user: "power" });
    await screen.findByTestId("mcp-url");
    expect(screen.queryByTestId("url-guess")).toBeNull();
    expect(screen.getByTestId("mcp-role").textContent).toContain("실행 1개");
    expect(screen.getByTestId("mcp-scopes").textContent).toMatch(/read.*run/);
    expect(screen.getByTestId("mcp-scopes").textContent).not.toContain("admin");
    a.unmount();
    const b = renderApp(PAGE, { user: "power", mcpUrlSource: "guess", disabledFeatures: ["mcp_http"] });
    expect((await screen.findByTestId("url-guess")).textContent).toContain("짐작");
    expect(screen.getByTestId("url-guess").textContent).toContain("mcp.public_url");
    expect(screen.getByTestId("http-off").textContent).toContain("stdio");
    expect(screen.getByTestId("http-off").textContent).not.toContain("http_enabled: true"); // power에게는 켜는 방법 대신 문의 안내
    b.unmount();
    renderApp(PAGE, { user: "admin", disabledFeatures: ["mcp_http"] });
    expect((await screen.findByTestId("http-off")).textContent).toContain("mcp.server.http_enabled: true");
    expect(screen.getByTestId("mcp-role").textContent).toBe("전역 관리자");
  });
});

describe("④ 도구 목록(접힘) · ⑤ 연결 시험", () => {
  it("도구 목록은 접혀 있고 열면 범위 기준으로 거른다(read → run 바꾸면 늘어남)", async () => {
    renderApp(PAGE, { user: "power" });
    await screen.findByTestId("mcp-url");
    const d = screen.getByTestId("tools-details") as HTMLDetailsElement;
    expect(d.open).toBe(false);
    expect(screen.getByTestId("tools-list").children).toHaveLength(0);
    d.open = true;
    fireEvent(d, new Event("toggle"));
    await waitFor(() => expect(screen.getByTestId("tools-list").children.length).toBeGreaterThan(0));
    const names = () => Array.from(screen.getByTestId("tools-list").querySelectorAll("code")).map((c) => c.textContent);
    expect(names()).toContain("ping");
    expect(names()).not.toContain("run_job");
    fireEvent.change(screen.getByLabelText("도구 범위 기준"), { target: { value: "run" } });
    expect(names()).toContain("run_job");
    expect(names()).not.toContain("list_audit");
    // 한국어 설명
    expect(screen.getByTestId("tools-list").textContent).toContain("연결 점검");
  });

  it("발급 직후 run 토큰이면 도구 범위 기준이 그 범위로 바뀐다", async () => {
    renderApp(PAGE, { user: "power" });
    await issue("run-토큰", /^run/);
    expect((screen.getByLabelText("도구 범위 기준") as HTMLSelectElement).value).toBe("run");
  });

  it("연결 시험(토큰 없음): 서버 정상 + 'ping 도구' 안내", async () => {
    renderApp(PAGE, { user: "power" });
    await screen.findByTestId("mcp-url");
    fireEvent.click(screen.getByRole("button", { name: "연결 시험" }));
    const res = await screen.findByTestId("test-result");
    await waitFor(() => expect(res.textContent).toContain("서버 정상"));
    expect(res.textContent).toContain("도구 7개");
    expect(res.textContent).toContain("ping 도구");
    expect(res.textContent).not.toContain("토큰으로 MCP 연결 정상");
  });

  it("연결 시험(방금 발급한 토큰, 같은 origin): initialize → '토큰으로 MCP 연결 정상', 폐기한 뒤에는 401 문구", async () => {
    renderApp(PAGE, { user: "power" });
    const plain = await issue();
    fireEvent.click(screen.getByRole("button", { name: "연결 시험" }));
    await waitFor(() => expect(screen.getByTestId("test-result").textContent).toContain("토큰으로 MCP 연결 정상"));
    // 폐기 → 같은 토큰 시험은 401
    const table = await screen.findByRole("table", { name: "내 API 토큰" });
    const row = (await within(table).findByText("web-시험")).closest("tr")!;
    fireEvent.click(within(row).getByRole("button", { name: "폐기" }));
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "폐기" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(cfg("claudeCode")).toContain(plain); // 화면 상태는 그대로(서버가 거부)
    fireEvent.click(screen.getByRole("button", { name: "연결 시험" }));
    await waitFor(() => expect(screen.getByTestId("test-result").textContent).toContain("토큰 문제(401)"));
  });
});

describe("경로·메뉴·관리자 안내 (V-MCP-26)", () => {
  it("/me/api-tokens → AI 연결 페이지(#tokens 토큰 영역 포함)로 이동", async () => {
    renderApp("/me/api-tokens", { user: "power" });
    expect(await screen.findByRole("heading", { name: "AI 연결(MCP)" })).toBeTruthy();
    expect(await screen.findByRole("table", { name: "내 API 토큰" })).toBeTruthy();
    expect(screen.getByTestId("tokens-anchor").id).toBe("tokens");
  });

  it("features.mcp=false: 메뉴 없음·페이지는 꺼짐 안내(③ 설정 없음)", async () => {
    const a = renderApp("/", { user: "power", disabledFeatures: ["mcp"] });
    await screen.findByText("대시보드로");
    await waitFor(() => expect(screen.queryByRole("link", { name: "AI 연결(MCP)" })).toBeNull());
    a.unmount();
    renderApp(PAGE, { user: "power", disabledFeatures: ["mcp"] });
    expect(await screen.findByTestId("mcp-off")).toBeTruthy();
    expect(screen.queryByTestId("cfg-claudeCode")).toBeNull();
  });

  it("관리 첫 화면(환경 점검): MCP 꺼짐이면 켜는 방법 한 줄, 켜져 있으면 없음", async () => {
    const a = renderApp("/admin/env-check", { user: "admin", disabledFeatures: ["mcp"] });
    const note = await screen.findByTestId("mcp-off-note");
    expect(note.textContent).toContain("mcp.enabled: true");
    expect(note.textContent).toContain("재시작");
    a.unmount();
    renderApp("/admin/env-check", { user: "admin" });
    await screen.findByRole("region", { name: "환경 점검" });
    expect(screen.queryByTestId("mcp-off-note")).toBeNull();
  });
});

describe("저장소 미사용 — 정적 시험 (V-MCP-22)", () => {
  const SRC = [["pages/AiConnection.tsx", aiConnectionSrc], ["pages/ApiTokens.tsx", apiTokensSrc], ["lib/mcpSetup.ts", mcpSetupSrc]] as const;
  it.each(SRC)("%s: localStorage·sessionStorage·쿠키·URL·전역 저장소에 토큰을 쓰는 코드가 없다", (_f, text) => {
    const code = text.replace(/\/\/.*$/gm, "").replace(/\/\*[\s\S]*?\*\//g, ""); // 주석 제외
    expect(code).not.toMatch(/localStorage|sessionStorage|document\.cookie|indexedDB|history\.(push|replace)State|location\.(hash|search|href)\s*=(?!=)/);
    expect(code).not.toMatch(/console\.(log|info|warn|error)/);
    expect(code).not.toMatch(/setSearchParams|navigate\([^)]*token/i);
  });
  it("발급·시험 후에도 저장소에 토큰이 없다", async () => {
    renderApp(PAGE, { user: "power" });
    const plain = await issue();
    fireEvent.click(screen.getByRole("button", { name: "연결 시험" }));
    await waitFor(() => expect(screen.getByTestId("test-result").textContent).toContain("서버 정상"));
    expect(JSON.stringify({ ...localStorage }) + JSON.stringify({ ...sessionStorage })).not.toContain(plain);
    expect(window.location.href).not.toContain(plain);
  });
});
