// 결과 3D 컨투어 생성·폴링·취소(geometry-view.md §13.5·§13.6, 열 때 생성): POST /contour3d → 200 적중(바로 표시) | 202 →
// GET /contour3d/{id} 0.5초 폴링(진행 단계·경과·예상) → DONE. 410·EXPIRED(서버 캐시 정리됨)면 같은 원본으로 다시 요청한다.
import { useCallback, useEffect, useRef, useState } from "react";
import { api, errorMessage, type Contour3d, type Contour3dCreate } from "../../../../api";
import { POLL } from "../../../../lib/poll";
import { sleep } from "../expire";

const active = (c: Contour3d) => c.status === "QUEUED" || c.status === "RUNNING";

export function useContour3d(source: Contour3dCreate) {
  const [c, setC] = useState<Contour3d | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const gen = useRef(0);
  const src = useRef(source);
  src.current = source;
  useEffect(
    () => () => {
      gen.current++;
    },
    [],
  );

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
    const my = ++gen.current;
    setError(null);
    setBusy(true);
    try {
      const r = await api.createContour3d(src.current);
      if (my !== gen.current) return;
      setC(r);
      setBusy(false);
      await poll(r, my);
    } catch (e) {
      if (my === gen.current) setError(errorMessage(e));
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

  return { c, error, busy, start, cancel };
}
