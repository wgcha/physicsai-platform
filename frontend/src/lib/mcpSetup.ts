// mcp.md §23.3: "AI 도구에 등록하기" 탭별 완성 설정 — 순수 함수 한 곳. 클라이언트별 키 이름이 바뀌면 이 파일·mcp.md §21.1·deploy/mcp/examples만 고친다.
// 토큰 평문은 인자로만 받아 문자열에 끼운다(저장·전역 상태 없음). 서버 이름은 `physicsai`.

/** 토큰을 아직 발급받지 않았을 때 설정에 끼워 두는 자리 */
export const TOKEN_PLACEHOLDER = "‹발급받은_토큰›";
export const SERVER_NAME = "physicsai";
/** 토큰 파일 방식 대안의 경로 자리(deploy/mcp/examples와 같은 표기) */
export const TOKEN_FILE_PLACEHOLDER = "<토큰 파일 경로>";
const COMMAND = "physicsai-mcp";

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
  /** HTTP MCP 주소(예 https://host/physicsai/mcp) */
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
    desktop: string;
    codex: string;
    gemini: string;
  };
}

export function buildConfigs({ url, api, token }: McpConfigInput): McpConfigs {
  const tok = token || TOKEN_PLACEHOLDER;
  const claudeCode = `claude mcp add --transport http ${SERVER_NAME} ${shellArg(url)} --header ${shellArg(`Authorization: Bearer ${tok}`)}`;
  const desktop = entry(SERVER_NAME, { command: COMMAND, env: { PHYSICSAI_MCP_URL: api, PHYSICSAI_MCP_TOKEN: tok } });
  const codex = [
    `[mcp_servers.${SERVER_NAME}]`,
    `command = ${tomlStr(COMMAND)}`,
    "args = []",
    "",
    `[mcp_servers.${SERVER_NAME}.env]`,
    `PHYSICSAI_MCP_URL = ${tomlStr(api)}`,
    `PHYSICSAI_MCP_TOKEN = ${tomlStr(tok)}`,
  ].join("\n");
  const gemini = entry(SERVER_NAME, { httpUrl: url, headers: { Authorization: `Bearer ${tok}` }, timeout: 60000, trust: false });

  const stdioEnv = { PHYSICSAI_MCP_URL: api, PHYSICSAI_MCP_TOKEN_FILE: TOKEN_FILE_PLACEHOLDER };
  const alt = {
    claudeCodeJson: JSON.stringify({ mcpServers: { [SERVER_NAME]: { type: "http", url, headers: { Authorization: "Bearer ${PHYSICSAI_MCP_TOKEN}" } } } }, null, 2),
    claudeCodeStdio: `claude mcp add ${SERVER_NAME} --env PHYSICSAI_MCP_URL=${api} --env PHYSICSAI_MCP_TOKEN_FILE=${TOKEN_FILE_PLACEHOLDER} -- ${COMMAND}`,
    desktop: entry(SERVER_NAME, { command: COMMAND, env: stdioEnv }),
    codex: [
      `[mcp_servers.${SERVER_NAME}]`,
      `url = ${tomlStr(url)}`,
      'bearer_token_env_var = "PHYSICSAI_MCP_TOKEN"',
      "",
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
export const MCP_TABS: { key: McpTab; label: string; where: string; stdio: boolean }[] = [
  { key: "claudeCode", label: "Claude Code", where: "터미널에서 한 번 실행합니다(HTTP 연결).", stdio: false },
  { key: "desktop", label: "Claude Desktop", where: "claude_desktop_config.json의 mcpServers 안에 이 항목을 추가합니다(stdio).", stdio: true },
  { key: "codex", label: "Codex CLI", where: "~/.codex/config.toml 끝에 이어 붙입니다(stdio).", stdio: true },
  { key: "gemini", label: "Gemini CLI", where: "~/.gemini/settings.json의 mcpServers 안에 이 항목을 추가합니다(HTTP).", stdio: false },
];

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
