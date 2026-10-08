// 계약 §5.4·§10.1: 상대경로 /physicsai/api, 비GET에 X-PhysicsAI-Request: 1, 오류 {detail:{code,message}}.
import type { ApiErrorDetail } from "./types";

export const API_PREFIX = "/physicsai/api";

export class ApiError extends Error {
  status: number;
  code: string;
  detail: ApiErrorDetail;
  constructor(status: number, detail: ApiErrorDetail) {
    super(detail.message);
    this.status = status;
    this.code = detail.code;
    this.detail = detail;
  }
}

const FALLBACK_MESSAGES: Record<number, string> = {
  401: "로그인이 필요합니다. 대시보드에서 로그인하세요.",
  403: "권한이 없습니다.",
  404: "대상을 찾을 수 없습니다.",
  409: "현재 상태에서는 처리할 수 없습니다.",
  422: "입력값을 확인하세요.",
  503: "서버를 사용할 수 없습니다. 잠시 후 다시 시도하세요.",
};

/** ETag 캐시(GET /jobs/{id} 등): url → {etag, body} */
const etagCache = new Map<string, { etag: string; body: unknown }>();

/** 세션 만료 등으로 401을 받으면 앱 전체에 알린다(AuthGate가 로그인 안내로 전환) */
export const AUTH_LOST_EVENT = "physicsai:auth-lost";
function signal401(status: number) {
  if (status === 401 && typeof window !== "undefined") window.dispatchEvent(new Event(AUTH_LOST_EVENT));
}

/** 응답 헤더 X-Next-Cursor(B2) */
export async function requestPage<T>(path: string, query?: Query): Promise<{ items: T; nextCursor: string | null }> {
  const url = buildUrl(path, query);
  let res: Response;
  try {
    res = await fetch(url, { headers: { Accept: "application/json" }, credentials: "same-origin" });
  } catch {
    throw new ApiError(0, { code: "NETWORK_ERROR", message: "서버에 연결할 수 없습니다." });
  }
  if (!res.ok) {
    signal401(res.status);
    throw await toError(res);
  }
  return { items: (await res.json()) as T, nextCursor: res.headers.get("X-Next-Cursor") };
}

export function clearApiCache() {
  etagCache.clear();
}

type Query = Record<string, string | number | boolean | null | undefined>;

export function buildUrl(path: string, query?: Query): string {
  let url = API_PREFIX + path;
  if (query) {
    const qs = Object.entries(query)
      .filter(([, v]) => v !== undefined && v !== null && v !== "")
      .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
      .join("&");
    if (qs) url += "?" + qs;
  }
  return url;
}

async function toError(res: Response): Promise<ApiError> {
  let detail: ApiErrorDetail = {
    code: `HTTP_${res.status}`,
    message: FALLBACK_MESSAGES[res.status] ?? `요청 실패 (${res.status})`,
  };
  try {
    const body = await res.json();
    if (body && typeof body === "object" && body.detail && typeof body.detail === "object") {
      detail = { ...detail, ...body.detail };
    }
  } catch {
    /* 본문 없음 */
  }
  return new ApiError(res.status, detail);
}

export async function request<T>(
  method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE",
  path: string,
  opts: { query?: Query; body?: unknown; etag?: boolean } = {},
): Promise<T> {
  const url = buildUrl(path, opts.query);
  const headers: Record<string, string> = { Accept: "application/json" };
  if (method !== "GET") headers["X-PhysicsAI-Request"] = "1";
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  const cached = method === "GET" && opts.etag ? etagCache.get(url) : undefined;
  if (cached) headers["If-None-Match"] = cached.etag;

  let res: Response;
  try {
    res = await fetch(url, {
      method,
      headers,
      credentials: "same-origin",
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    });
  } catch {
    throw new ApiError(0, { code: "NETWORK_ERROR", message: "서버에 연결할 수 없습니다." });
  }
  if (res.status === 304 && cached) return cached.body as T;
  if (!res.ok) {
    signal401(res.status);
    throw await toError(res);
  }
  if (res.status === 204) return undefined as T;
  const body = (await res.json()) as T;
  if (method === "GET" && opts.etag) {
    const etag = res.headers.get("ETag");
    if (etag) etagCache.set(url, { etag, body });
  }
  return body;
}

/** 산출물 본문(blob) — 내려받기는 id로만(§6.8) */
export async function fetchBlob(path: string): Promise<Blob> {
  const url = buildUrl(path);
  let res: Response;
  try {
    res = await fetch(url, { credentials: "same-origin" });
  } catch {
    throw new ApiError(0, { code: "NETWORK_ERROR", message: "서버에 연결할 수 없습니다." });
  }
  if (!res.ok) {
    signal401(res.status);
    throw await toError(res);
  }
  return res.blob();
}

export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) {
    const missing = (e.detail as { missing?: unknown }).missing;
    if (Array.isArray(missing) && missing.length) return `${e.message} (${missing.join(", ")})`;
    return e.message;
  }
  if (e instanceof Error) return e.message;
  return String(e);
}
