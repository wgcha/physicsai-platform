import type { MockServer } from "../mock/server";

/** server.handle 호출 기록 */
export function recordCalls(server: MockServer) {
  const calls: string[] = [];
  const orig = server.handle.bind(server);
  server.handle = (m, p, q, b, h, r) => {
    calls.push(`${m} ${p}`);
    return orig(m, p, q, b, h, r);
  };
  return calls;
}
