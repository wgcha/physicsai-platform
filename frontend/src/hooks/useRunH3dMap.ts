// 해석 DOE의 run_key → h3d_rel 맵(contour3d-default C3D-10, GV-C3): GET /train-does/{id}/runs를 페이지(≤200)로 끝까지 읽는다. DOE마다 1회(화면 메모리).
// ⑤ 결과 표 행에는 h3d 경로가 없어 TrainRun.h3d_rel(기존 API)에서 얻는다.
import { useEffect, useState } from "react";
import { api, errorMessage } from "../api";

export interface RunH3dMap {
  /** 읽는 중이면 null */
  map: Map<string, string | null> | null;
  error: string | null;
}

export function useRunH3dMap(doeId: string | null): RunH3dMap {
  const [st, setSt] = useState<{ id: string | null; map: Map<string, string | null> | null; error: string | null }>({ id: null, map: null, error: null });
  useEffect(() => {
    if (!doeId) return;
    let alive = true;
    (async () => {
      const m = new Map<string, string | null>();
      let cursor: string | null = null;
      do {
        const page: { items: { run_key: string; h3d_rel?: string | null }[]; nextCursor: string | null } = await api.trainRuns(doeId, { cursor, limit: 200 });
        for (const r of page.items) m.set(r.run_key, r.h3d_rel ?? null);
        cursor = page.nextCursor;
      } while (cursor && m.size < 5000);
      if (alive) setSt({ id: doeId, map: m, error: null });
    })().catch((e) => alive && setSt({ id: doeId, map: null, error: errorMessage(e) }));
    return () => {
      alive = false;
    };
  }, [doeId]);
  return doeId && st.id === doeId ? { map: st.map, error: st.error } : { map: null, error: null };
}
