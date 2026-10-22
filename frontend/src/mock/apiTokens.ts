// mcp.md §4.4 목: GET·POST /me/api-tokens, DELETE /me/api-tokens/{id}(204), GET /admin/api-tokens, POST /admin/api-tokens/{id}/revoke.
// 평문 토큰은 발급 응답에만 — 목은 가짜 값(`pai_<id8>_MOCK…`)을 만들고 저장하지 않는다(접두만 남김). 한도 5개·이름 유일·만료 최대 30일.
import type { ApiTokenAdmin } from "../api/types";
import { err, ok, type Route } from "./route";
import type { MockServer } from "./server";

const MAX_PER_USER = 5;
const MAX_DAYS = 30;
const NAME_RE = /^[0-9A-Za-z가-힣 _.-]{1,64}$/;
const DAY = 86400000;
const STORE = new WeakMap<MockServer, ApiTokenAdmin[]>();

function store(srv: MockServer): ApiTokenAdmin[] {
  let t = STORE.get(srv);
  if (!t) {
    const now = Date.now();
    const mk = (id: string, uid: string, uname: string, name: string, scope: ApiTokenAdmin["scope"], ageDays: number, left: number, extra: Partial<ApiTokenAdmin> = {}): ApiTokenAdmin => ({
      id, user_id: uid, username: uname, name, scope, token_prefix: `pai_${id.padEnd(8, "0").slice(0, 8)}`, created_at: new Date(now - ageDays * DAY).toISOString(),
      expires_at: new Date(now + left * DAY).toISOString(), last_used_at: ageDays > 3 ? new Date(now - 2 * 3600000).toISOString() : null, revoked_at: null, revoked_by: null,
      snapshot_at: new Date(now - ageDays * DAY).toISOString(), status: left > 0 ? "active" : "expired", ...extra,
    });
    t = [
      mk("a1b2c3d4", "u-power", "kim.res", "codex-내PC", "read", 9, 21),
      mk("e5f6a7b8", "u-power", "kim.res", "claude-code-작업", "run", 20, 10),
      mk("c9d0e1f2", "u-power", "kim.res", "이전 토큰", "read", 45, -15),
      mk("0a1b2c3d", "u-admin", "admin01", "ops-점검", "admin", 5, 25),
      mk("4e5f6a7b", "u-general", "lee.view", "gemini", "read", 12, 18, { status: "revoked", revoked_at: new Date(now - DAY).toISOString(), revoked_by: "u-admin" }),
    ];
    STORE.set(srv, t);
  }
  return t;
}
/** 목 HTTP MCP 시험용: 토큰 id(8자)로 현재 상태(없으면 null) */
export function apiTokenStatus(srv: MockServer, id: string): ApiTokenAdmin["status"] | null {
  return store(srv).find((t) => t.id === id)?.status ?? null;
}
const mcpOff = (srv: MockServer) => !srv.p2.feature("mcp").enabled;
const pub = ({ user_id: _u, username: _n, ...rest }: ApiTokenAdmin) => rest;

export const apiTokenRoutes: Route = (srv, { method, seg, query, body, me }) => {
  const mine = seg[0] === "me" && seg[1] === "api-tokens";
  const adm = seg[0] === "admin" && seg[1] === "api-tokens";
  if (!mine && !adm) return null;
  if (adm && !me.is_global_admin) return err(403, "PERMISSION_DENIED", "전역 관리자만 할 수 있습니다.", { required: "global_admin" });
  if (mcpOff(srv)) return err(404, "MCP_DISABLED", "MCP 기능이 꺼져 있습니다(mcp.enabled: false)");
  const all = store(srv);
  if (mine && seg.length === 2 && method === "GET") return ok(all.filter((t) => t.user_id === me.user_id).map(pub));
  if (mine && seg.length === 2 && method === "POST") {
    const b = (body ?? {}) as { name?: string; scope?: ApiTokenAdmin["scope"]; expires_in_days?: number | null };
    const name = String(b.name ?? "").trim();
    if (!NAME_RE.test(name)) return err(422, "INVALID_PARAMS", "토큰 이름은 1~64자(영숫자·한글·공백·_.-)입니다");
    const scope = b.scope;
    if (scope !== "read" && scope !== "run" && scope !== "admin") return err(422, "INVALID_PARAMS", "범위는 read·run·admin입니다");
    const power = me.is_global_admin || Object.values(me.roles).some((r) => r === "power" || r === "admin");
    if (scope === "admin" && !me.is_global_admin) return err(403, "API_TOKEN_SCOPE", "admin 범위 토큰은 전역 관리자 권한이 필요합니다", { required: "admin" });
    if (scope === "run" && !power) return err(403, "API_TOKEN_SCOPE", "run 범위 토큰은 power 권한이 필요합니다", { required: "run" });
    const days = b.expires_in_days ?? MAX_DAYS;
    if (!Number.isFinite(days) || days < 1 || days > MAX_DAYS) return err(422, "API_TOKEN_EXPIRY_TOO_LONG", `토큰 만료는 최대 ${MAX_DAYS}일입니다 — 만료 전에 새 토큰을 발급해 교체하세요`);
    const live = all.filter((t) => t.user_id === me.user_id && t.status === "active");
    if (live.length >= MAX_PER_USER) return err(409, "API_TOKEN_LIMIT", `유효한 토큰은 사용자당 ${MAX_PER_USER}개까지입니다 — 쓰지 않는 토큰을 폐기하세요`);
    if (live.some((t) => t.name === name)) return err(409, "API_TOKEN_NAME_EXISTS", "같은 이름의 토큰이 이미 있습니다");
    const id = srv.nid("tk").replace(/[^0-9a-z]/gi, "").padEnd(8, "0").slice(0, 8);
    const now = Date.now();
    const row: ApiTokenAdmin = {
      id, user_id: me.user_id, username: me.username, name, scope, token_prefix: `pai_${id}`, created_at: new Date(now).toISOString(), expires_at: new Date(now + days * DAY).toISOString(),
      last_used_at: null, revoked_at: null, revoked_by: null, snapshot_at: new Date(now).toISOString(), status: "active",
    };
    all.unshift(row);
    return ok({ token: `pai_${id}_MOCKxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`, api_token: pub(row) }, 201);
  }
  if (mine && seg.length === 3 && method === "DELETE") {
    const t = all.find((x) => x.id === seg[2] && x.user_id === me.user_id);
    if (!t) return err(404, "NOT_FOUND", "토큰을 찾을 수 없습니다.");
    if (!t.revoked_at) Object.assign(t, { revoked_at: new Date().toISOString(), revoked_by: me.user_id, status: "revoked" });
    return { status: 204 };
  }
  if (adm && seg.length === 2 && method === "GET") {
    const uid = query.get("user_id");
    const active = query.get("active");
    return ok(all.filter((t) => (!uid || t.user_id === uid) && (active == null || (t.status === "active") === (active === "true"))));
  }
  if (adm && seg.length === 4 && seg[3] === "revoke" && method === "POST") {
    const t = all.find((x) => x.id === seg[2]);
    if (!t) return err(404, "NOT_FOUND", "토큰을 찾을 수 없습니다.");
    if (!t.revoked_at) Object.assign(t, { revoked_at: new Date().toISOString(), revoked_by: me.user_id, status: "revoked" });
    return ok(t);
  }
  return null;
};
