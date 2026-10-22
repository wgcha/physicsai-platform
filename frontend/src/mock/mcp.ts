// mcp.md §23.4 목: GET /mcp/connection(세션 전용), GET /mcp/ping, GET /mcp/tools?format=mcp&visible=true + HTTP MCP 주소(POST /physicsai/mcp) 흉내.
import { err, ok, type MockResp, type Route } from "./route";
import type { MockServer } from "./server";
import { apiTokenStatus } from "./apiTokens";

const origin = () => (typeof window !== "undefined" ? window.location.origin : "http://localhost");
const TOOLS: [string, string, "read" | "run" | "admin"][] = [
  ["ping", "Connection check / 연결 점검: 서버 버전·토큰 접두·범위·남은 일수", "read"],
  ["whoami", "Who am I / 내 이름·프로젝트 역할", "read"],
  ["list_studies", "List studies / Study 목록", "read"],
  ["get_summary", "Entity summary / 결과 요약 조회", "read"],
  ["plan_job", "Plan a job (dry-run) / 작업 실행 계획과 확인 토큰", "run"],
  ["run_job", "Run a job with confirm token / 확인 토큰으로 작업 실행", "run"],
  ["list_audit", "Audit log / 감사 로그 조회", "admin"],
];

export const mcpRoutes: Route = (srv, { method, seg, me }) => {
  if (seg[0] !== "mcp" || method !== "GET") return null;
  if (!srv.p2.feature("mcp").enabled) return err(404, "MCP_DISABLED", "MCP 기능이 꺼져 있습니다(mcp.enabled: false)");
  if (seg[1] === "connection") {
    const url = `${origin()}/physicsai/mcp`;
    return ok({
      enabled: true,
      http_enabled: srv.p2.feature("mcp_http").enabled,
      url,
      url_source: srv.mcpUrlSource,
      api_base: url.replace(/\/mcp$/, ""),
      stdio_hint: {
        command: "physicsai-mcp",
        command_path: me.is_global_admin ? "E:\\physicsai\\venv\\Scripts\\physicsai-mcp.exe" : null,
        install: "내 PC: 관리자에게 오프라인 묶음 wheels를 받아 pip install --no-index --find-links <wheels> physicsai-platform",
      },
    });
  }
  if (seg[1] === "ping") return ok({ ok: true, server_version: "0.2.7", mcp_enabled: true, tools_count: TOOLS.length, token: null, warnings: [] });
  if (seg[1] === "tools") {
    const tools = TOOLS.map(([name, description, risk]) => ({ name, description, annotations: { "x-risk": risk } }));
    return ok({ schema_version: 1, tools, visible: tools.map((t) => t.name) });
  }
  return null;
};

/** POST {url} JSON-RPC initialize — Bearer 토큰 검사(401: 모르는·폐기·만료 토큰, 404: MCP 꺼짐) */
export function mcpHttp(srv: MockServer, method: string, authorization: string | null): MockResp {
  if (!srv.p2.feature("mcp").enabled) return { status: 404, body: { code: "MCP_DISABLED", message: "MCP 기능이 꺼져 있습니다" } };
  if (method !== "POST") return { status: 405, body: { code: "METHOD_NOT_ALLOWED", message: "POST만 지원합니다" } };
  const m = /^Bearer (pai_([0-9a-z]{8})_\S+)$/i.exec(authorization ?? "");
  if (!m || apiTokenStatus(srv, m[2]) !== "active") return { status: 401, body: { code: "API_TOKEN_INVALID", message: "토큰이 유효하지 않습니다" } };
  return { status: 200, body: { jsonrpc: "2.0", id: 1, result: { protocolVersion: "2025-06-18", serverInfo: { name: "physicsai", version: "0.2.7" }, capabilities: { tools: {} } } } };
}
