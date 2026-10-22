// V-MCP-23(mcp.md §23.6): buildConfigs 출력의 설정 문법 — JSON.parse(Claude Desktop·Gemini 항목은 {…}로 감싸서)·TOML 간이 파싱(Codex)·셸 분해(Claude Code)·
// 대안 블록 `pai_` 0건 + 예시 파일(deploy/mcp/examples, V-MCP-19)과 키 모양 일치. 순수 함수 시험.
import { describe, expect, it } from "vitest";
import { parseToml, shellSplit } from "../test/configParse";
import { TOKEN_PLACEHOLDER, buildConfigs, scopeAllows, shellArg, toolSummaryKo, tomlStr, sameOrigin } from "../lib/mcpSetup";

const URL_ = "https://sim.example.co.kr/physicsai/mcp";
const API = "https://sim.example.co.kr/physicsai";
const REAL = "pai_a1b2c3d4_Zx9Qk-LmN_pQrStUvWxYz0123456789abcdefghij";
// 저장소 루트 deploy/mcp/examples의 예시 파일을 읽기만 한다(?raw)
import claudeMcp from "../../../deploy/mcp/examples/claude.mcp.json?raw";
import desktopCfg from "../../../deploy/mcp/examples/claude_desktop_config.json?raw";
import geminiStdio from "../../../deploy/mcp/examples/gemini.settings.stdio.json?raw";
import codexToml from "../../../deploy/mcp/examples/codex.config.toml?raw";
import desktopStdio from "../../../deploy/mcp/examples/claude_desktop_config.stdio.json?raw";
import geminiBridge from "../../../deploy/mcp/examples/gemini.settings.json?raw";
import codexStdio from "../../../deploy/mcp/examples/codex.config.stdio.toml?raw";
const EXAMPLES: Record<string, string> = {
  "claude.mcp.json": claudeMcp,
  "claude_desktop_config.json": desktopCfg,
  "claude_desktop_config.stdio.json": desktopStdio,
  "gemini.settings.json": geminiBridge,
  "gemini.settings.stdio.json": geminiStdio,
  "codex.config.toml": codexToml,
  "codex.config.stdio.toml": codexStdio,
};
const example = (name: string) => EXAMPLES[name];

const shape = (v: unknown): unknown => (v && typeof v === "object" && !Array.isArray(v) ? Object.fromEntries(Object.entries(v).map(([k, x]) => [k, shape(x)])) : Array.isArray(v) ? [] : "");

describe.each([
  ["자리표시자", null, TOKEN_PLACEHOLDER],
  ["실제 형식 토큰", REAL, REAL],
])("buildConfigs — %s", (_n, token, shown) => {
  const c = buildConfigs({ url: URL_, api: API, token });

  it("Claude Code: HTTP 직결 유지 — 셸 분해하면 인자 9개, --header 값 1개(공백 포함)", () => {
    const a = shellSplit(c.claudeCode);
    expect(a).toEqual(["claude", "mcp", "add", "--transport", "http", "physicsai", URL_, "--header", `Authorization: Bearer ${shown}`]);
  });
  const BRIDGE = { command: "npx", args: ["-y", "mcp-remote", URL_, "--allow-http", "--header", "Authorization:${AUTH}"], env: { AUTH: `Bearer ${shown}`, NODE_OPTIONS: "--use-system-ca" } };
  it("Claude Desktop: 항목만 — {…}로 감싸면 JSON, npx mcp-remote 브리지(토큰은 env AUTH, args는 ${AUTH} 참조)", () => {
    const o = JSON.parse(`{${c.desktop}}`);
    expect(o.physicsai).toEqual(BRIDGE);
    expect(c.desktop.trim().startsWith('"physicsai":')).toBe(true); // 바깥 중괄호 없음(기존 설정 덮어쓰기 방지)
    expect(o.physicsai.args.join(" ")).not.toContain("Bearer"); // 헤더 값 공백 때문에 토큰은 args에 넣지 않는다
  });
  it("Gemini CLI: 항목 = Claude Desktop 항목과 같다(브리지)", () => {
    expect(c.gemini).toBe(c.desktop);
    expect(JSON.parse(`{${c.gemini}}`).physicsai).toEqual(BRIDGE);
  });
  it("Codex CLI: TOML — [mcp_servers.physicsai] npx mcp-remote 브리지 + env AUTH", () => {
    const t = parseToml(c.codex) as { mcp_servers: { physicsai: { command: string; args: unknown[]; env: Record<string, string> } } };
    expect(t.mcp_servers.physicsai).toEqual({ command: BRIDGE.command, args: BRIDGE.args, env: BRIDGE.env });
    expect(c.codex).toContain("Authorization:${AUTH}"); // 문자 그대로(mcp-remote가 치환)
  });
  it("대안 블록(stdio): `pai_` 0건·토큰 파일 키, 예시 파일과 키 모양 일치(V-MCP-19)", () => {
    const all = Object.values(c.alt).join("\n");
    expect(all).not.toContain("pai_");
    expect(all).not.toContain(TOKEN_PLACEHOLDER);
    expect(shape(JSON.parse(c.alt.claudeCodeJson))).toEqual(shape(JSON.parse(example("claude.mcp.json"))));
    expect(shape(JSON.parse(`{"mcpServers":{${c.alt.desktop}}}`))).toEqual(shape(JSON.parse(example("claude_desktop_config.stdio.json"))));
    expect(shape(JSON.parse(`{"mcpServers":{${c.alt.gemini}}}`))).toEqual(shape(JSON.parse(example("gemini.settings.stdio.json"))));
    expect(shape(parseToml(c.alt.codex))).toEqual(shape(parseToml(example("codex.config.stdio.toml"))));
    expect(c.alt.claudeCodeStdio).toContain("--env PHYSICSAI_MCP_TOKEN_FILE=");
    expect(shellSplit(c.alt.claudeCodeStdio).slice(-2)).toEqual(["--", "physicsai-mcp"]);
  });
  it("브리지 기본 블록은 예시 파일(deploy/mcp/examples)과 키 모양 일치, 예시 AUTH는 자리표시자", () => {
    expect(shape(JSON.parse(`{"mcpServers":{${c.desktop}}}`))).toEqual(shape(JSON.parse(example("claude_desktop_config.json"))));
    expect(shape(JSON.parse(`{"mcpServers":{${c.gemini}}}`))).toEqual(shape(JSON.parse(example("gemini.settings.json"))));
    expect(shape(parseToml(c.codex))).toEqual(shape(parseToml(example("codex.config.toml"))));
    expect(JSON.parse(example("claude_desktop_config.json")).mcpServers.physicsai.args[5]).toBe("Authorization:${AUTH}");
  });
});

describe("이스케이프", () => {
  it("TOML 문자열: 따옴표·역슬래시", () => {
    const s = 'a"b\\c';
    expect(parseToml(`k = ${tomlStr(s)}`)).toEqual({ k: s });
  });
  it("셸 인자: $·`·따옴표·역슬래시를 이스케이프하면 한 인자", () => {
    const s = 'x"y$z`w\\v u';
    expect(shellSplit(`cmd ${shellArg(s)}`)).toEqual(["cmd", s]);
  });
  it("주소·토큰에 특수문자가 있어도 JSON·TOML이 깨지지 않는다", () => {
    const c = buildConfigs({ url: 'https://h/p"q/mcp', api: "https://h/p\"q", token: 'ab"c\\d' });
    expect(() => JSON.parse(`{${c.desktop}}`)).not.toThrow();
    expect(() => JSON.parse(`{${c.gemini}}`)).not.toThrow();
    expect(() => parseToml(c.codex)).not.toThrow();
    expect(JSON.parse(`{${c.desktop}}`).physicsai.env.AUTH).toBe('Bearer ab"c\\d');
  });
});

describe("보조 규칙", () => {
  it("도구 범위: read ⊂ run ⊂ admin", () => {
    expect(scopeAllows("read", "read")).toBe(true);
    expect(scopeAllows("read", "run")).toBe(false);
    expect(scopeAllows("run", "run")).toBe(true);
    expect(scopeAllows("run", "admin")).toBe(false);
    expect(scopeAllows("admin", "admin")).toBe(true);
  });
  it("도구 설명 '영문 / 한국어' → 한국어", () => {
    expect(toolSummaryKo("Cancel a job / 작업 취소(토큰은 …)")).toBe("작업 취소(토큰은 …)");
    expect(toolSummaryKo("plain")).toBe("plain");
  });
  it("같은 origin 판정", () => {
    expect(sameOrigin("http://localhost:3000/physicsai/mcp", "http://localhost:3000")).toBe(true);
    expect(sameOrigin("https://other/physicsai/mcp", "http://localhost:3000")).toBe(false);
    expect(sameOrigin("not a url", "http://localhost:3000")).toBe(false);
  });
});
