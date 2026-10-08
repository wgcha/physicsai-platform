import { useEffect, useRef } from "react";

/**
 * interval마다 fn 실행. interval=null이면 멈춘다.
 * 탭이 숨겨지면(document.visibilityState === "hidden") 멈추고, 돌아오면 즉시 1회 실행 후 재개(§10.9).
 * immediate=true면 시작 시 즉시 1회.
 */
export function usePolling(fn: () => unknown, interval: number | null, immediate = true, deps: unknown[] = []) {
  const fnRef = useRef(fn);
  fnRef.current = fn;

  useEffect(() => {
    if (interval === null) return;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let stopped = false;

    const run = async () => {
      try {
        await fnRef.current();
      } catch {
        /* 호출부에서 처리 */
      }
    };
    const schedule = () => {
      if (stopped) return;
      clearTimeout(timer);
      if (document.visibilityState === "hidden") return;
      timer = setTimeout(async () => {
        await run();
        schedule();
      }, interval);
    };
    const onVisibility = () => {
      if (document.visibilityState === "hidden") {
        clearTimeout(timer);
      } else {
        void run().then(schedule);
      }
    };

    if (immediate) void run().then(schedule);
    else schedule();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      stopped = true;
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [interval, immediate, ...deps]);
}
