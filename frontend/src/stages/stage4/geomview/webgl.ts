// WebGL 확인(geometry-view.md §7.4): WebGL2 → WebGL1 → 없음으로 구분해 시도하고, 못 쓰면 그림으로 대체한다.
// three(r163+)는 WebGL2만 쓰므로 3D 가능 = webgl2. 첫 화면 청크에 남는 작은 모듈(진단 문자열도 여기).

export type GlLevel = "webgl2" | "webgl" | "none";
export interface GlInfo {
  level: GlLevel;
  /** 드라이버가 알려준 렌더러 문자열(SwiftShader·ANGLE 등, 없으면 null) */
  renderer: string | null;
  /** 컨텍스트를 못 만든 이유(예외 메시지·null 반환) */
  error: string | null;
}

type Ctx = { getExtension?: (n: string) => unknown; getParameter?: (p: number) => unknown };

function rendererOf(ctx: Ctx): string | null {
  try {
    const ext = ctx.getExtension?.("WEBGL_debug_renderer_info") as { UNMASKED_RENDERER_WEBGL: number } | null | undefined;
    const v = ext ? ctx.getParameter?.(ext.UNMASKED_RENDERER_WEBGL) : null;
    return typeof v === "string" ? v : null;
  } catch {
    return null;
  }
}

/** WebGL2 → WebGL1 순으로 컨텍스트 생성을 시도하고 어디까지 되는지 돌려준다 */
export function probeWebGL(doc: Document = document): GlInfo {
  try {
    const c = doc.createElement("canvas");
    const gl2 = c.getContext("webgl2") as unknown as Ctx | null;
    if (gl2) return { level: "webgl2", renderer: rendererOf(gl2), error: null };
    const c1 = doc.createElement("canvas");
    const gl1 = c1.getContext("webgl") as unknown as Ctx | null;
    if (gl1) return { level: "webgl", renderer: rendererOf(gl1), error: "WEBGL2_UNSUPPORTED" };
    return { level: "none", renderer: null, error: "CONTEXT_NULL" };
  } catch (e) {
    return { level: "none", renderer: null, error: e instanceof Error ? `${e.name}: ${e.message}`.slice(0, 80) : String(e) };
  }
}

/** WebGL2 또는 WebGL1 컨텍스트가 만들어지는가(구 API — 시험·호환용) */
export function detectWebGL(doc: Document = document): boolean {
  return probeWebGL(doc).level !== "none";
}

let cache: GlInfo | null = null;
/** WebGL 확인은 한 번만(시험은 resetWebGLCache로 다시) */
export function webglInfo(): GlInfo {
  cache ??= probeWebGL();
  return cache;
}
/** 3D 가능 여부 = WebGL2 */
export function webglAvailable(): boolean {
  return webglInfo().level === "webgl2";
}
export function resetWebGLCache() {
  cache = null;
  lastError = null;
}

// ---------------------------------------------------------------- 실패 사유 문구(패널에 항상 한 줄)

export type GvFailKind = "no-webgl" | "webgl1" | "lost" | "init" | "chunk" | "glb" | "view" | "noview" | "loading";
export interface GvFailure {
  kind: GvFailKind;
  /** 짧은 오류 코드(HTTP 410·NETWORK·예외 이름 등) */
  code?: string;
}

export const GV_REASON: Record<Exclude<GvFailKind, "init" | "glb" | "view" | "noview">, string> = {
  "no-webgl": "이 PC는 WebGL을 쓸 수 없어 그림으로 표시합니다(하드웨어 가속 꺼짐·원격 데스크톱·GPU 없음 추정)",
  webgl1: "이 PC의 브라우저는 WebGL 2를 지원하지 않아 그림으로 표시합니다(구버전 브라우저·그래픽 드라이버 추정)",
  lost: "3D 표시가 중단되었습니다(그래픽 컨텍스트 손실) — 그림으로 표시합니다",
  chunk: "3D 화면 모듈을 불러오지 못해 그림으로 표시합니다(네트워크 또는 이전 캐시 — 새로고침 후 다시 시도)",
  loading: "3D 형상을 불러오는 중…",
};

export function gvReasonText(f: GvFailure): string {
  const c = f.code ? `: ${f.code}` : "";
  switch (f.kind) {
    case "init":
      return `3D 화면을 시작하지 못해 그림으로 표시합니다(그래픽 초기화 오류${c})`;
    case "glb":
      return `3D 형상 파일을 불러오지 못해 그림으로 표시합니다(${f.code ?? "알 수 없음"})`;
    case "view":
      return `3D 형상 정보를 불러오지 못해 그림으로 표시합니다(${f.code ?? "알 수 없음"})`;
    case "noview":
      return `이 형상은 3D 변환본이 없어 그림으로 표시합니다${f.code ? `(${f.code})` : ""}`;
    default:
      return GV_REASON[f.kind];
  }
}

/** 다시 시도로 풀릴 수 있는 사유(환경 문제는 제외) */
export const retryable = (f: GvFailure) => f.kind !== "no-webgl" && f.kind !== "webgl1" && f.kind !== "loading";

/** 오류 → 짧은 코드(HTTP 상태·코드, 네트워크, 예외 이름) */
export function errCode(e: unknown): string {
  const x = e as { status?: unknown; code?: unknown; name?: unknown; message?: unknown } | null;
  if (x && typeof x.status === "number") return `HTTP ${x.status}${typeof x.code === "string" && x.code ? ` ${x.code}` : ""}`;
  if (e instanceof TypeError && /fetch|network|load/i.test(e.message)) return "NETWORK";
  if (e instanceof Error) return `${e.name}: ${e.message}`.slice(0, 80);
  return String(x?.message ?? e).slice(0, 80);
}

let lastError: string | null = null;
/** 마지막 3D·그림 오류(진단 한 줄 — 화면에만 표시, 서버로 보내지 않는다) */
export function noteGvError(kind: string, code?: string) {
  lastError = `${kind}${code ? ` ${code}` : ""}`;
}
export const lastGvError = () => lastError;

/** 진단 한 줄: 브라우저 · WebGL 단계/렌더러 · 마지막 오류 */
export function diagText(info: GlInfo = webglInfo()): string {
  const ua = typeof navigator !== "undefined" ? navigator.userAgent : "-";
  return `브라우저: ${ua} · WebGL: ${info.level}${info.renderer ? ` (${info.renderer})` : ""}${info.error ? ` [${info.error}]` : ""} · 마지막 오류: ${lastError ?? "없음"}`;
}
