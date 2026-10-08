import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { usePolling } from "../hooks/usePolling";

function setVisibility(v: "visible" | "hidden") {
  Object.defineProperty(document, "visibilityState", { configurable: true, get: () => v });
  document.dispatchEvent(new Event("visibilitychange"));
}

describe("usePolling (V-FE-3)", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => {
    vi.useRealTimers();
    setVisibility("visible");
  });

  it("주기 실행, 숨김 탭 중지, 복귀 즉시 1회", async () => {
    const fn = vi.fn();
    renderHook(() => usePolling(fn, 1000));
    await act(async () => {});
    expect(fn).toHaveBeenCalledTimes(1);
    await act(async () => void (await vi.advanceTimersByTimeAsync(3000)));
    expect(fn).toHaveBeenCalledTimes(4);
    await act(async () => setVisibility("hidden"));
    await act(async () => void (await vi.advanceTimersByTimeAsync(5000)));
    expect(fn).toHaveBeenCalledTimes(4);
    await act(async () => setVisibility("visible"));
    expect(fn).toHaveBeenCalledTimes(5);
    await act(async () => void (await vi.advanceTimersByTimeAsync(1000)));
    expect(fn).toHaveBeenCalledTimes(6);
  });

  it("interval=null이면 멈춘다", async () => {
    const fn = vi.fn();
    renderHook(() => usePolling(fn, null));
    await act(async () => void (await vi.advanceTimersByTimeAsync(5000)));
    expect(fn).not.toHaveBeenCalled();
  });
});
