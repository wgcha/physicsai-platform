// 미리보기 요청·폴링·결과 적재(geometry-view.md §6.4·§6.5·§7.3): POST → 200 캐시 적중(즉시) | 202 → GET 0.5초 폴링 → DONE이면
// manifest(JSON)·GLB(형상·FE)를 받는다. 410(캐시 정리됨)이면 같은 값으로 다시 요청(1회). 새 요청은 이전 폴링을 버린다.
import { useCallback, useEffect, useRef, useState } from "react";
import { api, errorMessage, type GeomPreview, type GeomPreviewCreate } from "../../../api";
import { POLL } from "../../../lib/poll";
import { isExpired, sleep } from "./expire";
import type { PreviewManifest } from "./viewerCore";

export interface GeomPreviewState {
  preview: GeomPreview | null;
  manifest: PreviewManifest | null;
  glb: ArrayBuffer | null;
  feGlb: ArrayBuffer | null;
  error: string | null;
  /** 진행 시작 시각(ms) — 실행 중일 때만 */
  since: number | null;
  /** 마지막 요청 본문(다시 버튼) */
  last: GeomPreviewCreate | null;
}

const EMPTY: GeomPreviewState = { preview: null, manifest: null, glb: null, feGlb: null, error: null, since: null, last: null };
const active = (p: GeomPreview) => p.status === "QUEUED" || p.status === "RUNNING";

export function useGeomPreview(paramSetId: string | null) {
  const [s, setS] = useState<GeomPreviewState>(EMPTY);
  const gen = useRef(0);
  useEffect(
    () => () => {
      gen.current++;
    },
    [],
  );

  const run = useCallback(
    async (body: GeomPreviewCreate) => {
      if (!paramSetId) return;
      const my = ++gen.current;
      const alive = () => my === gen.current;
      setS({ ...EMPTY, since: Date.now(), last: body });
      for (let attempt = 0; attempt < 2; attempt++) {
        try {
          let p = await api.createPreview(paramSetId, body);
          if (!alive()) return;
          setS((x) => ({ ...x, preview: p }));
          while (active(p)) {
            await sleep(POLL.preview);
            if (!alive()) return;
            p = await api.preview(p.id);
            if (!alive()) return;
            setS((x) => ({ ...x, preview: p }));
          }
          if (p.status !== "DONE") {
            setS((x) => ({ ...x, since: null }));
            return;
          }
          const manifest = p.manifest_artifact_id ? await api.artifactJson<PreviewManifest>(p.manifest_artifact_id) : null;
          const glb = p.glb_artifact_id ? (await api.artifactBuffer(p.glb_artifact_id)).buffer : null;
          const feGlb = p.fe_glb_artifact_id ? (await api.artifactBuffer(p.fe_glb_artifact_id)).buffer : null;
          if (!alive()) return;
          setS((x) => ({ ...x, preview: p, manifest, glb, feGlb, since: null }));
          return;
        } catch (e) {
          if (!alive()) return;
          if (isExpired(e) && attempt === 0) continue; // 캐시가 정리됨 → 같은 값으로 다시 만든다
          setS((x) => ({ ...x, error: errorMessage(e), since: null }));
          return;
        }
      }
    },
    [paramSetId],
  );

  const reset = useCallback(() => {
    gen.current++;
    setS(EMPTY);
  }, []);

  return { ...s, run, reset };
}
