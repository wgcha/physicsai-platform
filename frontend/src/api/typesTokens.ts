// mcp.md §4.4 API 토큰 타입 — 생성 타입 별칭
import type { S } from "./typesBase";

export type ApiToken = S["ApiToken"];
export type ApiTokenAdmin = S["ApiTokenAdmin"];
export type ApiTokenCreate = S["ApiTokenCreate"];
export type ApiTokenCreated = S["ApiTokenCreated"];
export type ApiTokenScope = ApiToken["scope"];
export type ApiTokenStatus = ApiToken["status"];

/** mcp.md §23.4 GET /mcp/connection(세션 전용) · §17 ping · 도구 스펙(format=mcp&visible=true) */
export type McpConnection = S["McpConnection"];
export type McpPing = S["Ping"];
export interface McpToolSpec {
  name: string;
  description: string;
  annotations?: { "x-risk"?: "read" | "run" | "admin" } & Record<string, unknown>;
}
export interface McpTools {
  tools: McpToolSpec[];
  visible?: string[];
}
