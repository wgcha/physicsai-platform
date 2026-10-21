// mcp.md §4.4 API 토큰 타입 — 생성 타입 별칭
import type { S } from "./typesBase";

export type ApiToken = S["ApiToken"];
export type ApiTokenAdmin = S["ApiTokenAdmin"];
export type ApiTokenCreate = S["ApiTokenCreate"];
export type ApiTokenCreated = S["ApiTokenCreated"];
export type ApiTokenScope = ApiToken["scope"];
export type ApiTokenStatus = ApiToken["status"];
