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
const EXAMPLES: Record<string, string> = { "claude.mcp.json": claudeMcp, "claude_desktop_config.json": desktopCfg, "gemini.settings.stdio.json": geminiStdio, "codex.config.toml": codexToml };
const example = (name: string) => EXAMPLES[name];

const shape = (v: unknown): unknown => (v && typeof v === "object" && !Array.isArray(v) ? Object.fromEntries(Object.entries(v).map(([k, x]) => [k, shape(x)])) : Array.isArray(v) ? [] : "");

describe.each([
  ["자리표시자", null, TOKEN_PLACEHOLDER],
  ["실제 형식 토큰", REAL, REAL],
])("buildConfigs — %s", (_n, token, shown) => {
  const c = buildConfigs({ url: URL_, api: API, token });

  it("Claude Code: 셸 분해하면 인자 9개, --header 값 1개(공백 포함)", () => {
    const a = shellSplit(c.claudeCode);
    expect(a).toEqual(["claude", "mcp", "add", "--transport", "http", "physicsai", URL_, "--header", `Authorization: Bearer ${shown}`]);
  });
  it("Claude Desktop: 항목만 — {…}로 감싸면 JSON, command·env 키", () => {
    const o = JSON.parse(`{${c.desktop}}`);
    expect(o.physicsai).toEqual({ command: "physicsai-mcp", env: { PHYSICSAI_MCP_URL: API, PHYSICSAI_MCP_TOKEN: shown } });
    expect(c.desktop.trim().startsWith('"physicsai":')).toBe(true); // 바깥 중괄호 없음(기존 설정 덮어쓰기 방지)
  });
  it("Gemini CLI: 항목만 — httpUrl·headers.Authorization·timeout 60000·trust false", () => {
    const o = JSON.parse(`{${c.gemini}}`);
    expect(o.physicsai).toEqual({ httpUrl: URL_, headers: { Authorization: `Bearer ${shown}` }, timeout: 60000, trust: false });
  });
  it("Codex CLI: TOML — [mcp_servers.physicsai] command·args + env", () => {
    const t = parseToml(c.codex) as { mcp_servers: { physicsai: { command: string; args: unknown[]; env: Record<string, string> } } };
    expect(t.mcp_servers.physicsai.command).toBe("physicsai-mcp");
    expect(t.mcp_servers.physicsai.args).toEqual([]);
    expect(t.mcp_servers.physicsai.env).toEqual({ PHYSICSAI_MCP_URL: API, PHYSICSAI_MCP_TOKEN: shown });
  });
  it("대안 블록: `pai_` 0건·토큰 파일 키, 예시 파일과 키 모양 일치(V-MCP-19)", () => {
    const all = Object.values(c.alt).join("\n");
    expect(all).not.toContain("pai_");
    expect(all).not.toContain(TOKEN_PLACEHOLDER);
    expect(shape(JSON.parse(c.alt.claudeCodeJson))).toEqual(shape(JSON.parse(example("claude.mcp.json"))));
    expect(shape(JSON.parse(`{"mcpServers":{${c.alt.desktop}}}`))).toEqual(shape(JSON.parse(example("claude_desktop_config.json"))));
    expect(shape(JSON.parse(`{"mcpServers":{${c.alt.gemini}}}`))).toEqual(shape(JSON.parse(example("gemini.settings.stdio.json"))));
    expect(shape(parseToml(c.alt.codex))).toEqual(shape(parseToml(example("codex.config.toml"))));
    expect(c.alt.claudeCodeStdio).toContain("--env PHYSICSAI_MCP_TOKEN_FILE=");
    expect(shellSplit(c.alt.claudeCodeStdio).slice(-2)).toEqual(["--", "physicsai-mcp"]);
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
