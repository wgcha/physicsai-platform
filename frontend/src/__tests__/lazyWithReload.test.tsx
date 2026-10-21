// 업데이트 뒤 옛 index.html이 옛 청크를 요청해 동적 import가 실패할 때: 1회 새로고침, 다시 실패하면 안내 상자.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { Suspense } from "react";
import { ChunkErrorBoundary, RELOAD_FLAG, chunkErrorCode, importWithReload, lazyWithReload, reloadHooks } from "../lib/lazyWithReload";
import { isStaleBuild } from "../lib/buildHash";
import { renderApp } from "../test/render";

const FAIL = () => Promise.reject(new TypeError("Failed to fetch dynamically imported module: https://x/physicsai/assets/GeomView3D-abc123.js"));
const Ok = () => <div>패널 본문</div>;

function mount(factory: () => Promise<{ default: () => JSX.Element }>) {
  const Lazy = lazyWithReload(factory);
  return render(
    <ChunkErrorBoundary extra={<div>그림 대체</div>}>
      <Suspense fallback={<div>불러오는 중</div>}>
        <Lazy />
      </Suspense>
    </ChunkErrorBoundary>,
  );
}

describe("lazyWithReload", () => {
  const reload = vi.fn();
  beforeEach(() => {
    sessionStorage.clear();
    reload.mockReset();
    reloadHooks.reload = reload;
    vi.spyOn(console, "error").mockImplementation(() => undefined);
  });
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllEnvs();
  });

  it("정상 적재는 새로고침 없이 그린다", async () => {
    mount(() => Promise.resolve({ default: Ok }));
    expect(await screen.findByText("패널 본문")).toBeTruthy();
    expect(reload).not.toHaveBeenCalled();
  });

  it("첫 실패 → 한 번만 새로고침(오류 상자 없음), 두 번째 실패 → 빈 화면 대신 안내 상자와 원인 코드", async () => {
    mount(FAIL);
    await waitFor(() => expect(reload).toHaveBeenCalledTimes(1));
    expect(sessionStorage.getItem(RELOAD_FLAG)).toBeTruthy();
    expect(screen.queryByTestId("chunk-error")).toBeNull();
    // 새로고침 뒤에도 같은 실패(플래그 유지) → 상자
    mount(FAIL);
    const box = await screen.findByTestId("chunk-error");
    expect(box.textContent).toContain("화면 파일이 갱신되었습니다. 새로고침(Ctrl+F5) 해 주세요");
    expect(box.textContent).toContain("DYNAMIC_IMPORT_FAILED");
    expect(screen.getByText("그림 대체")).toBeTruthy();
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it("MIME text/html 실패도 같은 처리, 청크 오류가 아닌 실패는 그대로 던진다", async () => {
    expect(chunkErrorCode(new TypeError("'text/html' is not a valid JavaScript MIME type"))).toBe("CHUNK_MIME_HTML");
    expect(chunkErrorCode(Object.assign(new Error("x"), { name: "ChunkLoadError" }))).toBe("CHUNK_LOAD_ERROR");
    await expect(importWithReload(() => Promise.reject(new Error("boom")))).rejects.toThrow("boom");
    expect(reload).not.toHaveBeenCalled();
  });
});

describe("새 버전 알림(VersionBadge)", () => {
  afterEach(() => vi.unstubAllEnvs());
  it("isStaleBuild: 둘 다 있고 다를 때만", () => {
    expect(isStaleBuild("a", "b")).toBe(true);
    expect(isStaleBuild("a", "a")).toBe(false);
    expect(isStaleBuild(null, "b")).toBe(false);
    expect(isStaleBuild("a", null)).toBe(false);
  });
  it("번들 해시가 서버 build.source_hash와 다르면 상단에 새로고침 안내, 같으면 없음", async () => {
    vi.stubEnv("VITE_BUILD_HASH", "a".repeat(64));
    const { unmount } = renderApp("/");
    expect((await screen.findByTestId("stale-build")).textContent).toContain("새 버전이 배포되었습니다 · 새로고침");
    unmount();
    vi.stubEnv("VITE_BUILD_HASH", "f".repeat(64)); // 목 서버의 source_hash
    renderApp("/");
    await screen.findByTestId("version-badge");
    expect(screen.queryByTestId("stale-build")).toBeNull();
  });
});
