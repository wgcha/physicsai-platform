// 결과 3D 컨투어 생성·폴링·취소(geometry-view.md §13.5·§13.6): POST /contour3d → 200 적중(바로 표시) | 202 →
// GET /contour3d/{id} 0.5초 폴링(진행 단계·경과·예상) → DONE. 410·EXPIRED(서버 캐시 정리됨)면 같은 원본으로 다시 요청한다.
// 자동 요청(contour3d-default C3D-3~6, `auto`): 칸이 보일 때 한 번(행 선택은 머무른 뒤), 429 PREVIEW_BUSY면 칸이 보이는 동안 일정 간격으로 다시,
// 403 PERMISSION_DENIED(읽기 사용자의 미적중)는 denied로 알린다. source가 null이면 아무것도 하지 않는다.
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api, errorMessage, type Contour3d, type Contour3dCreate } from "../../../../api";
import { POLL } from "../../../../lib/poll";
import { sleep } from "../expire";

const active = (c: Contour3d) => c.status === "QUEUED" || c.status === "RUNNING";

export interface ContourAuto {
  /** 칸이 화면에 보이는가(IntersectionObserver) — 보일 때만 요청한다 */
  visible: boolean;
  /** 머무름(ms, 기본 0 = 바로). 행 선택은 POLL.contourDwell */
  delayMs?: number;
  /** 429 재요청 간격(ms, 기본 POLL.contourRetry) */
  retryMs?: number;
}

export function useContour3d(source: Contour3dCreate | null, auto?: ContourAuto) {
  const [c, setC] = useState<Contour3d | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  /** 429: 앞선 생성이 끝나면 이어서 요청하는 중 */
  const [queued, setQueued] = useState(false);
  /** 403: 읽기 사용자가 캐시 없는 결과를 요청함 */
  const [denied, setDenied] = useState(false);
  const gen = useRef(0);
  const src = useRef(source);
  src.current = source;
  const key = source ? JSON.stringify(source) : "";
  useEffect(
    () => () => {
      gen.current++;
    },
    [],
  );

  // 원본이 바뀌면 이전 상태를 비운다(이전 요청·폴링은 버린다 — 서버 작업은 취소하지 않는다, C3D-4)
  const prevKey = useRef(key);
  useEffect(() => {
    if (prevKey.current === key) return;
    prevKey.current = key;
    gen.current++;
    setC(null);
    setError(null);
    setBusy(false);
    setQueued(false);
    setDenied(false);
  }, [key]);

  const poll = useCallback(async (first: Contour3d, my: number) => {
    let cur = first;
    while (active(cur)) {
      await sleep(POLL.preview);
      if (my !== gen.current) return;
      cur = await api.contour3d(cur.id);
      if (my !== gen.current) return;
      setC(cur);
    }
  }, []);

  /** 생성 요청(캐시 적중이면 바로 DONE) — 다시·만료 재요청도 같은 함수 */
  const start = useCallback(async () => {
    if (!src.current) return;
    const my = ++gen.current;
    setError(null);
    setDenied(false);
    setBusy(true);
    try {
      const r = await api.createContour3d(src.current);
      if (my !== gen.current) return;
      setQueued(false);
      setC(r);
      setBusy(false);
      await poll(r, my);
    } catch (e) {
      if (my !== gen.current) return;
      if (e instanceof ApiError && e.status === 429) setQueued(true);
      else if (e instanceof ApiError && e.status === 403 && e.code === "PERMISSION_DENIED") {
        setQueued(false);
        setDenied(true);
      } else {
        setQueued(false);
        setError(errorMessage(e));
      }
    } finally {
      if (my === gen.current) setBusy(false);
    }
  }, [poll]);

  const cancel = useCallback(async () => {
    if (!c) return;
    const my = ++gen.current;
    try {
      const r = await api.cancelContour3d(c.id);
      if (my === gen.current) setC(r);
    } catch (e) {
      if (my !== gen.current) return;
      setError(errorMessage(e));
      // 이미 끝났으면(409 JOB_TERMINAL) 현재 상태를 다시 읽고 폴링을 이어 간다
      try {
        const r = await api.contour3d(c.id);
        if (my !== gen.current) return;
        setC(r);
        await poll(r, my);
      } catch {
        /* 표시는 위 오류로 */
      }
    }
  }, [c, poll]);

  // 자동 요청: 아직 아무것도 없는 상태(c 없음·오류 없음·거부 아님)에서, 보이는 동안 한 번(429면 간격을 두고 반복)
  const on = !!auto && !!source;
  const visible = !!auto?.visible;
  const delay = auto?.delayMs ?? 0;
  const retry = auto?.retryMs ?? POLL.contourRetry;
  useEffect(() => {
    if (!on || !visible || c || error || denied || busy) return;
    const t = setTimeout(() => void start(), queued ? retry : delay);
    return () => clearTimeout(t);
  }, [on, visible, c, error, denied, busy, queued, delay, retry, key, start]);

  return { c, error, busy, queued, denied, start, cancel };
}

export type ContourCtl = ReturnType<typeof useContour3d>;
