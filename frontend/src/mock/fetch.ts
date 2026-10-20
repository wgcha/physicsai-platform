// fetch 가로채기: /physicsai/api/* 요청을 MockServer.handle로 보낸다(R-F 분할, server.ts에서 재노출).
import { MockServer } from "./server";

/** fetch 대체 함수 생성 */
export function createMockFetch(server: MockServer, realFetch?: typeof fetch): typeof fetch {
  return async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(typeof input === "string" ? input : input instanceof URL ? input.href : input.url, "http://mock.local");
    const prefix = "/physicsai/api";
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
    if (typeof init?.body === "string") body = JSON.parse(init.body);
    const r = server.handle(method, url.pathname.slice(prefix.length) || "/", url.searchParams, body, headers);
    const h = new Headers(r.headers);
    if (r.status === 304) return new Response(null, { status: 304, headers: h });
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
