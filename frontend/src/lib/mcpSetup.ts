// mcp.md §23.3: "AI 도구에 등록하기" 탭별 완성 설정 — 순수 함수 한 곳. 클라이언트별 키 이름이 바뀌면 이 파일·mcp.md §21.1·deploy/mcp/examples만 고친다.
// 토큰 평문은 인자로만 받아 문자열에 끼운다(저장·전역 상태 없음). 서버 이름은 `physicsai`.
// v0.2.8(이슈 #10, matnexus McpSetup 규칙): Claude Code는 HTTP 직결, Desktop·Codex·Gemini는 `npx mcp-remote` 브리지(Node.js 필요)가 기본.
// 헤더 값에 공백(`Bearer …`)이 있어 args에 토큰을 넣지 않고 env AUTH + `${AUTH}` 참조(치환은 mcp-remote). stdio `physicsai-mcp`는 접힌 대안.

/** 토큰을 아직 발급받지 않았을 때 설정에 끼워 두는 자리 */
export const TOKEN_PLACEHOLDER = "‹발급받은_토큰›";
export const SERVER_NAME = "physicsai";
/** 토큰 파일 방식 대안의 경로 자리(deploy/mcp/examples와 같은 표기) */
export const TOKEN_FILE_PLACEHOLDER = "<토큰 파일 경로>";
const COMMAND = "physicsai-mcp";
const BRIDGE_COMMAND = "npx";
/** mcp-remote 헤더 인자: 값은 env AUTH 참조(문자 그대로 `${AUTH}`) */
const BRIDGE_HEADER = "Authorization:${AUTH}";

/** TOML 기본 문자열 이스케이프(따옴표·역슬래시·제어문자) */
export function tomlStr(s: string): string {
  const esc = s.replace(/\\/g, "\\\\").replace(/"/g, '\\"').replace(/\n/g, "\\n").replace(/\r/g, "\\r").replace(/\t/g, "\\t");
  return `"${esc}"`;
}
/** 셸 인자 하나로 안전하게(큰따옴표 안에서 \ " $ ` 이스케이프) */
export function shellArg(s: string): string {
  return `"${s.replace(/(["\\$`])/g, "\\$1")}"`;
}
const entry = (name: string, value: unknown) => `${JSON.stringify(name)}: ${JSON.stringify(value, null, 2)}`;

export interface McpConfigInput {
  /** HTTP MCP 주소(예 https://host/physicsai/mcp) — 브리지·Claude Code가 쓴다 */
  url: string;
  /** stdio 기본 주소 = url에서 끝의 /mcp를 뗀 값 */
  api: string;
  /** 발급 직후 평문. 없으면 자리표시자 */
  token?: string | null;
}

export interface McpConfigs {
  /** 실제로 끼운 토큰 문자열(자리표시자 포함) */
  tokenText: string;
  claudeCode: string;
  desktop: string;
  codex: string;
  gemini: string;
  alt: {
    /** .mcp.json(HTTP, 환경변수 확장) */
    claudeCodeJson: string;
    /** stdio 명령(토큰 파일) */
    claudeCodeStdio: string;
    /** stdio 항목(Node.js를 쓸 수 없는 PC) */
    desktop: string;
    /** stdio 서버 `physicsai_stdio`(브리지 `physicsai`와 함께 둘 수 있다) */
    codex: string;
    gemini: string;
  };
}

export function buildConfigs({ url, api, token }: McpConfigInput): McpConfigs {
  const tok = token || TOKEN_PLACEHOLDER;
  const claudeCode = `claude mcp add --transport http ${SERVER_NAME} ${shellArg(url)} --header ${shellArg(`Authorization: Bearer ${tok}`)}`;
  const bridge = {
    command: BRIDGE_COMMAND,
    args: ["-y", "mcp-remote", url, "--allow-http", "--header", BRIDGE_HEADER],
    env: { AUTH: `Bearer ${tok}`, NODE_OPTIONS: "--use-system-ca" },
  };
  const desktop = entry(SERVER_NAME, bridge);
  const codex = [
    `[mcp_servers.${SERVER_NAME}]`,
    `command = ${tomlStr(BRIDGE_COMMAND)}`,
    `args = [${bridge.args.map(tomlStr).join(", ")}]`,
    "",
    `[mcp_servers.${SERVER_NAME}.env]`,
    `AUTH = ${tomlStr(bridge.env.AUTH)}`,
    `NODE_OPTIONS = ${tomlStr(bridge.env.NODE_OPTIONS)}`,
  ].join("\n");
  const gemini = desktop; // Gemini 항목 모양 = Claude Desktop과 같다

  const stdioEnv = { PHYSICSAI_MCP_URL: api, PHYSICSAI_MCP_TOKEN_FILE: TOKEN_FILE_PLACEHOLDER };
  const alt = {
    claudeCodeJson: JSON.stringify({ mcpServers: { [SERVER_NAME]: { type: "http", url, headers: { Authorization: "Bearer ${PHYSICSAI_MCP_TOKEN}" } } } }, null, 2),
    claudeCodeStdio: `claude mcp add ${SERVER_NAME} --env PHYSICSAI_MCP_URL=${api} --env PHYSICSAI_MCP_TOKEN_FILE=${TOKEN_FILE_PLACEHOLDER} -- ${COMMAND}`,
    desktop: entry(SERVER_NAME, { command: COMMAND, env: stdioEnv }),
    codex: [
      `[mcp_servers.${SERVER_NAME}_stdio]`,
      `command = ${tomlStr(COMMAND)}`,
      "args = []",
      "",
      `[mcp_servers.${SERVER_NAME}_stdio.env]`,
      `PHYSICSAI_MCP_URL = ${tomlStr(api)}`,
      `PHYSICSAI_MCP_TOKEN_FILE = ${tomlStr(TOKEN_FILE_PLACEHOLDER)}`,
    ].join("\n"),
    gemini: entry(SERVER_NAME, { command: COMMAND, env: stdioEnv, timeout: 60000, trust: false }),
  };
  return { tokenText: tok, claudeCode, desktop, codex, gemini, alt };
}

export type McpTab = "claudeCode" | "desktop" | "codex" | "gemini";
export const MCP_TABS: { key: McpTab; label: string; where: string; bridge: boolean }[] = [
  { key: "claudeCode", label: "Claude Code", where: "터미널에서 한 번 실행합니다(HTTP 연결).", bridge: false },
  { key: "desktop", label: "Claude Desktop", where: "claude_desktop_config.json의 mcpServers 안에 이 항목을 추가합니다(mcp-remote 브리지).", bridge: true },
  { key: "codex", label: "Codex CLI", where: "~/.codex/config.toml 끝에 이어 붙입니다(mcp-remote 브리지).", bridge: true },
  { key: "gemini", label: "Gemini CLI", where: "C:\\Users\\<사용자>\\.gemini\\settings.json(Windows 기준)의 mcpServers 안에 이 항목을 추가합니다. 파일이 없으면 새로 만들고, 아래 항목을 { \"mcpServers\": { … } } 안에 넣어 저장합니다(mcp-remote 브리지).", bridge: true },
];
/** 브리지 탭 안내(npx 사용) */
export const NODE_NOTE = "Claude Code를 뺀 셋은 Node.js가 필요합니다(npx 사용).";

/** 범위 순서: 도구 x-risk가 선택 범위 이하면 보인다(표시 편의 — 권한 판정은 백엔드) */
const RANK = { read: 0, run: 1, admin: 2 } as const;
export function scopeAllows(scope: keyof typeof RANK, risk: string | undefined): boolean {
  return (RANK[risk as keyof typeof RANK] ?? 0) <= RANK[scope];
}

/** 도구 description "영문 / 한국어" → 한국어 쪽 */
export function toolSummaryKo(description: string): string {
  const i = description.lastIndexOf(" / ");
  return i >= 0 ? description.slice(i + 3) : description;
}

/** mcp.md §23.2 ⑤(b): 같은 origin인지(다르면 브라우저에서 직접 시험하지 않는다) */
export function sameOrigin(url: string, origin: string): boolean {
  try {
    return new URL(url).origin === origin;
  } catch {
    return false;
  }
}
