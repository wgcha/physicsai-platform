// fetch 가로채기: /physicsai/api/* 요청을 MockServer.handle로 보낸다(R-F 분할, server.ts에서 재노출).
import { MockServer } from "./server";
import { mcpHttp } from "./mcp";

/** fetch 대체 함수 생성 */
export function createMockFetch(server: MockServer, realFetch?: typeof fetch): typeof fetch {
  return async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(typeof input === "string" ? input : input instanceof URL ? input.href : input.url, "http://mock.local");
    const prefix = "/physicsai/api";
    if (url.pathname === "/physicsai/mcp") {
      // mcp.md §23.2 ⑤(b): 방금 발급한 토큰으로 HTTP MCP initialize 흉내
      const r = mcpHttp(server, (init?.method ?? "GET").toUpperCase(), new Headers(init?.headers).get("Authorization"));
      return new Response(JSON.stringify(r.body ?? null), { status: r.status, headers: { "Content-Type": "application/json" } });
    }
    if (!url.pathname.startsWith(prefix)) {
      if (realFetch) return realFetch(input, init);
      return new Response("not found", { status: 404 });
    }
    const method = (init?.method ?? "GET").toUpperCase();
    const headers0 = new Headers(init?.headers);
    // jsdom Headers는 Range를 버린다 — 일반 객체로 온 Range는 직접 넘긴다(브라우저 Headers는 그대로 보존)
    const raw = init?.headers && !(init.headers instanceof Headers) && !Array.isArray(init.headers) ? (init.headers as Record<string, string>) : {};
    const range = raw.Range ?? raw.range ?? headers0.get("Range");
    const headers = { get: (k: string) => (k.toLowerCase() === "range" ? range : headers0.get(k)), has: (k: string) => (k.toLowerCase() === "range" ? range != null : headers0.has(k)) } as Headers;
    let body: Record<string, unknown> | null = null;
    let rawBody: Blob | null = null;
    if (typeof init?.body === "string") body = JSON.parse(init.body);
    else if (init?.body instanceof Blob) rawBody = init.body;
    const r = server.handle(method, url.pathname.slice(prefix.length) || "/", url.searchParams, body, headers, rawBody);
    const h = new Headers(r.headers);
    if (r.status === 304 || r.status === 204) return new Response(null, { status: r.status, headers: h });
    if (r.bytes !== undefined) {
      h.set("Content-Type", r.contentType ?? "application/octet-stream");
      return new Response(r.bytes.slice().buffer as ArrayBuffer, { status: r.status, headers: h });
    }
    if (r.text !== undefined) {
      h.set("Content-Type", r.contentType ?? "text/plain");
      return new Response(r.text, { status: r.status, headers: h });
    }
    h.set("Content-Type", "application/json");
    return new Response(JSON.stringify(r.body ?? null), { status: r.status, headers: h });
  };
}
