// 목 서버 공용: 응답 형식(MockResp)·오류·라우트 문맥·권한 검사. 모든 라우트 모듈이 쓴다(F5).
import type { Me } from "../api/types";
import type { MockServer } from "./server";

export interface MockResp {
  status: number;
  body?: unknown;
  text?: string;
  contentType?: string;
  headers?: Record<string, string>;
}

export const err = (status: number, code: string, message: string, extra: Record<string, unknown> = {}): MockResp => ({
  status,
  body: { detail: { code, message, ...extra } },
});
export const ok = (body: unknown, status = 200): MockResp => ({ status, body });

/** 인증·CSRF 검사를 통과한 요청 */
export interface RouteCtx {
  method: string;
  path: string;
  seg: string[];
  query: URLSearchParams;
  body: Record<string, unknown> | null;
  headers: Headers;
  me: Me;
}

/** 라우트 모듈 함수: 맡은 경로면 응답, 아니면 null(다음 라우트로). 등록 순서는 server.ts ROUTES 한 곳 */
export type Route = (srv: MockServer, c: RouteCtx) => MockResp | null;

export function needPower(srv: MockServer, projectId: string): MockResp | null {
  const r = srv.role(projectId);
  return r === "power" || r === "admin" ? null : err(403, "PERMISSION_DENIED", "실행 권한(power 이상)이 필요합니다.", { required: "power" });
}

export function needAdmin(me: Me): MockResp | null {
  return me.is_global_admin ? null : err(403, "PERMISSION_DENIED", "전역 관리자만 할 수 있습니다.", { required: "global_admin" });
}
