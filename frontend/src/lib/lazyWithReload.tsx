// 지연 적재(동적 import) 실패 대응: 업데이트 뒤 브라우저가 캐시한 옛 index.html이 옛 해시의 청크를 요청하면
// 서버(try_files)가 index.html을 돌려줘 import가 실패한다 → 빈 패널. 처음 실패하면 한 번만 새로고침하고,
// 다시 실패하면 빈 화면 대신 안내 상자(원인 코드 포함)를 보인다.
import { Component, lazy, type ComponentType, type LazyExoticComponent, type ReactNode } from "react";

export const RELOAD_FLAG = "physicsai:chunk-reload-at";
/** 이 시간 안에 또 실패하면 새로고침해도 소용없다고 보고 안내 상자로 간다 */
export const RELOAD_WINDOW_MS = 60_000;

/** 시험에서 location.reload를 바꿔 끼우기 위한 훅 */
export const reloadHooks = { reload: () => window.location.reload() };

export class ChunkLoadFailed extends Error {
  readonly code: string;
  constructor(readonly cause: unknown) {
    super("화면 파일을 불러오지 못했습니다");
    this.name = "ChunkLoadFailed";
    this.code = chunkErrorCode(cause);
  }
}

const PATTERNS: [RegExp, string][] = [
  [/Failed to fetch dynamically imported module/i, "DYNAMIC_IMPORT_FAILED"],
  [/error loading dynamically imported module/i, "DYNAMIC_IMPORT_FAILED"],
  [/Importing a module script failed/i, "DYNAMIC_IMPORT_FAILED"],
  [/Loading (CSS )?chunk .* failed/i, "CHUNK_LOAD_ERROR"],
  [/MIME type|text\/html/i, "CHUNK_MIME_HTML"],
  [/Unexpected token '?<'?/i, "CHUNK_MIME_HTML"],
];

export function chunkErrorCode(e: unknown): string {
  const name = (e as { name?: string } | null)?.name;
  if (name === "ChunkLoadError") return "CHUNK_LOAD_ERROR";
  const msg = String((e as { message?: string } | null)?.message ?? e);
  return PATTERNS.find(([re]) => re.test(msg))?.[1] ?? "";
}

export const isChunkLoadError = (e: unknown) => chunkErrorCode(e) !== "";

function shouldReload(): boolean {
  try {
    const at = Number(sessionStorage.getItem(RELOAD_FLAG) ?? "0");
    if (at && Date.now() - at < RELOAD_WINDOW_MS) return false;
    sessionStorage.setItem(RELOAD_FLAG, String(Date.now()));
    return true;
  } catch {
    return false; // 저장소 불가: 무한 새로고침 위험이 있으니 새로고침하지 않고 바로 안내
  }
}

/** import()를 감싼다: 적재 실패 → (1회) 새로고침, 다음엔 ChunkLoadFailed. 새로고침 중에는 끝나지 않는 Promise(화면 전환 중) */
export function importWithReload<T>(factory: () => Promise<T>): Promise<T> {
  return factory().catch((e: unknown) => {
    if (!isChunkLoadError(e)) throw e;
    if (shouldReload()) {
      reloadHooks.reload();
      return new Promise<T>(() => undefined);
    }
    throw new ChunkLoadFailed(e);
  });
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function lazyWithReload<T extends ComponentType<any>>(factory: () => Promise<{ default: T }>): LazyExoticComponent<T> {
  return lazy(() => importWithReload(factory));
}

export function ChunkErrorBox({ error }: { error: unknown }) {
  const code = error instanceof ChunkLoadFailed ? error.code : chunkErrorCode(error);
  return (
    <div className="c3-box error-text small" role="alert" data-testid="chunk-error">
      화면 파일이 갱신되었습니다. 새로고침(Ctrl+F5) 해 주세요{code && <> · <code>{code}</code></>}
    </div>
  );
}

/** 지연 적재 컴포넌트를 감싸 적재 실패를 안내 상자로 바꾼다(다른 오류는 그대로 위로). extra = 상자 아래에 계속 보일 대체 화면 */
export class ChunkErrorBoundary extends Component<{ children: ReactNode; extra?: ReactNode }, { error: unknown }> {
  state = { error: null as unknown };
  static getDerivedStateFromError(error: unknown) {
    return { error };
  }
  render() {
    const { error } = this.state;
    if (error == null) return this.props.children;
    if (!(error instanceof ChunkLoadFailed) && !isChunkLoadError(error)) throw error;
    return (
      <>
        <ChunkErrorBox error={error} />
        {this.props.extra}
      </>
    );
  }
}
