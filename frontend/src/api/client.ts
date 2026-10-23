// 계약 §5.4·§10.1: 상대경로 /physicsai/api, 비GET에 X-PhysicsAI-Request: 1, 오류 {detail:{code,message}}.
import type { ApiErrorDetail } from "./types";
import { geomErrorText } from "../lib/geometry";
import { ASM_FIRST_TEXT, isAsmMissing } from "../lib/asmMatch";

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

/** 업로드 청크 PUT(application/octet-stream, upload-report.md §4) — 본문은 Blob 그대로(multipart 아님), 오류는 {detail:{code,message,received?}} */
export async function putBinary<T>(path: string, query: Query, body: Blob, extraHeaders: Record<string, string> = {}): Promise<T> {
  const url = buildUrl(path, query);
  let res: Response;
  try {
    res = await fetch(url, {
      method: "PUT",
      headers: { Accept: "application/json", "Content-Type": "application/octet-stream", "X-PhysicsAI-Request": "1", ...extraHeaders },
      credentials: "same-origin",
      body,
    });
  } catch {
    throw new ApiError(0, { code: "NETWORK_ERROR", message: "서버에 연결할 수 없습니다." });
  }
  if (!res.ok) {
    signal401(res.status);
    throw await toError(res);
  }
  return (await res.json()) as T;
}

/** 파일 응답 + 서버가 준 파일 이름(Content-Disposition filename* 우선) — 보고서 내려받기(upload-report.md §9.4) */
export async function fetchFile(path: string, query?: Query | URLSearchParams): Promise<{ blob: Blob; filename: string | null }> {
  const url = query instanceof URLSearchParams ? API_PREFIX + path + (query.toString() ? `?${query.toString()}` : "") : buildUrl(path, query);
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
  return { blob: await res.blob(), filename: dispositionName(res.headers.get("Content-Disposition")) };
}

export function dispositionName(h: string | null): string | null {
  if (!h) return null;
  const star = /filename\*\s*=\s*([^']*)'[^']*'([^;]+)/i.exec(h);
  if (star) {
    try {
      return decodeURIComponent(star[2].trim());
    } catch {
      /* 아래 filename= 으로 */
    }
  }
  const plain = /filename\s*=\s*"?([^";]+)"?/i.exec(h);
  return plain ? plain[1].trim() : null;
}

/** 산출물 바이너리(ArrayBuffer). range = [시작, 끝](포함) → `Range: bytes=a-b`. partial = 206(서버가 범위를 지원)
 * 410 ARTIFACT_EXPIRED(서버측 캐시 정리됨)는 ApiError(410)로 던진다 — 호출부가 다시 요청한다(geometry-view.md §6.6) */
export async function fetchBuffer(path: string, range?: [number, number], onProgress?: (loaded: number) => void): Promise<{ buffer: ArrayBuffer; partial: boolean }> {
  const url = buildUrl(path);
  let res: Response;
  try {
    res = await fetch(url, { credentials: "same-origin", headers: range ? { Range: `bytes=${range[0]}-${range[1]}` } : undefined });
  } catch {
    throw new ApiError(0, { code: "NETWORK_ERROR", message: "서버에 연결할 수 없습니다." });
  }
  if (!res.ok) {
    signal401(res.status);
    throw await toError(res);
  }
  const partial = res.status === 206;
  // 진행률 콜백(읽은 바이트)이 있으면 스트림으로 읽는다 — 압축 전송이면 총량은 호출부가 안다(manifest bytes)
  const reader = onProgress ? res.body?.getReader?.() : undefined;
  if (!reader) return { buffer: await res.arrayBuffer(), partial };
  const parts: Uint8Array[] = [];
  let loaded = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    parts.push(value);
    loaded += value.byteLength;
    onProgress!(loaded);
  }
  const out = new Uint8Array(loaded);
  let at = 0;
  for (const q of parts) {
    out.set(q, at);
    at += q.byteLength;
  }
  return { buffer: out.buffer, partial };
}

export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) {
    if (isAsmMissing(e.detail)) return ASM_FIRST_TEXT; // 확정된 조립 매칭 없음(asm-match.md AM-C2 10)
    const missing = (e.detail as { missing?: unknown }).missing;
    if (Array.isArray(missing) && missing.length) return `${e.message} (${missing.join(", ")})`;
    // 형상 엔진 오류 코드(geometry-engine.md §7.6): 서버 문구가 한국어가 아니면 코드 표의 한국어
    return geomErrorText(e.code, e.message);
  }
  if (e instanceof Error) return e.message;
  return String(e);
}
