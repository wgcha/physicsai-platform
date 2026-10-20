// WebGL 확인(geometry-view.md §7.4): WebGL2 → WebGL1 컨텍스트 생성 시도, 실패면 그림으로 대체. 첫 화면 청크에 남는 작은 모듈.

/** WebGL2 → WebGL1 컨텍스트 생성 시도. 실패면 false(그림 탭 고정) */
export function detectWebGL(doc: Document = document): boolean {
  try {
    const c = doc.createElement("canvas");
    const ctx = (c.getContext("webgl2") as unknown) || (c.getContext("webgl") as unknown);
    return !!ctx;
  } catch {
    return false;
  }
}

let cache: boolean | null = null;
/** WebGL 확인은 한 번만(시험은 resetWebGLCache로 다시) */
export function webglAvailable(): boolean {
  cache ??= detectWebGL();
  return cache;
}
export function resetWebGLCache() {
  cache = null;
}
