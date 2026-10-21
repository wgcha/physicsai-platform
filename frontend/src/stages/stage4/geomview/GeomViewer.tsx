// 형상 3D 뷰어(geometry-view.md §7.2): GLB 로드(동적 import three), 면 클릭 → _FACE_ID, 하이라이트·치수선, 바디 표시/숨김,
// 쉘 고정 영역 마커 토글, 회전·확대·이동(OrbitControls) + [맞춤]. 겹쳐 보기(미리보기 형상·FE)는 overlay로 받는다.
import { useEffect, useRef, useState, type ReactNode } from "react";
import { api, errorMessage } from "../../../api";
import { loadThree } from "./loadThree";
import { errCode, type GvFailure } from "./webgl";
import type { GeomSceneApi } from "./threeScene";
import type { FixedCluster, Highlight, Vec3, ViewManifest } from "./viewerCore";

export interface Overlay {
  buf: ArrayBuffer;
  kind: "shape" | "fe";
  dispMax: number | null;
}

export function GeomViewer({
  glbId,
  manifest,
  highlight,
  overlay,
  redClusters,
  points,
  onPick,
  onLost,
  onFail,
  children,
}: {
  glbId: string;
  manifest: ViewManifest;
  highlight: Highlight;
  overlay: Overlay | null;
  redClusters: Set<string>;
  points: { xyz: Vec3; label: string }[];
  onPick: (hit: { body: string; face: number } | null, additive?: boolean) => void;
  onLost: () => void;
  /** three 적재·GLB 받기·장면 초기화 실패(원인 구분) — 부모가 그림 폴백 + 다시 시도로 바꾼다 */
  onFail?: (f: GvFailure) => void;
  children?: ReactNode;
}) {
  const box = useRef<HTMLDivElement>(null);
  const scene = useRef<GeomSceneApi | null>(null);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [showFixed, setShowFixed] = useState(true);
  const pick = useRef(onPick);
  pick.current = onPick;
  const lost = useRef(onLost);
  lost.current = onLost;
  const failCb = useRef(onFail);
  failCb.current = onFail;
  const clusters: FixedCluster[] = manifest.fixed_clusters ?? [];

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    let alive = true;
    let made: GeomSceneApi | null = null;
    setReady(false);
    setError(null);
    (async () => {
      // 원인을 구분해 보고한다: chunk(three 모듈) · glb(형상 파일) · init(그래픽 초기화)
      const tag = <T,>(kind: GvFailure["kind"], p: Promise<T>) => p.catch((e) => Promise.reject({ gvKind: kind, e }));
      const [m, data] = await Promise.all([tag("chunk", loadThree()), tag("glb", api.artifactBuffer(glbId))]);
      if (!alive) return;
      try {
        made = m.createGeomScene(el, { onPick: (h, additive) => pick.current(h, additive), onLost: () => lost.current() });
        await made.setNominal(data.buffer, manifest);
      } catch (e) {
        throw { gvKind: "init", e };
      }
      if (!alive) return;
      scene.current = made;
      setReady(true);
    })().catch((x: { gvKind?: GvFailure["kind"]; e?: unknown }) => {
      if (!alive) return;
      const kind = x?.gvKind ?? "init";
      const raw = x?.gvKind ? x.e : x;
      const code = errCode(raw);
      if (failCb.current) failCb.current({ kind, code });
      else setError(errorMessage(raw));
    });
    return () => {
      alive = false;
      scene.current = null;
      made?.dispose();
    };
  }, [glbId, manifest]);

  useEffect(() => {
    if (ready) scene.current?.setHighlight(highlight);
  }, [ready, highlight]);
  useEffect(() => {
    if (!ready || !scene.current) return;
    void scene.current.setOverlay(overlay?.buf ?? null, overlay?.kind ?? "shape", overlay?.dispMax ?? null).catch((e) => setError(errorMessage(e)));
  }, [ready, overlay]);
  useEffect(() => {
    if (!ready) return;
    for (const b of manifest.bodies) scene.current?.setBodyVisible(b.body, !hidden.has(b.body));
  }, [ready, hidden, manifest]);
  useEffect(() => {
    if (ready) scene.current?.setFixed(showFixed, clusters, redClusters);
  }, [ready, showFixed, redClusters, manifest]);
  useEffect(() => {
    if (ready) scene.current?.setPoints(points);
  }, [ready, points]);

  const toggle = (b: string) =>
    setHidden((h) => {
      const n = new Set(h);
      if (n.has(b)) n.delete(b);
      else n.add(b);
      return n;
    });

  return (
    <div className="gv" data-testid="geom-viewer">
      <div className="gv-tools">
        <button type="button" className="btn small ghost" onClick={() => scene.current?.fit()} disabled={!ready} title="전체가 보이게 뷰를 되돌립니다">
          맞춤
        </button>
        {manifest.bodies.length > 1 &&
          manifest.bodies.map((b) => (
            <label key={b.body} className="check small mono">
              <input type="checkbox" checked={!hidden.has(b.body)} onChange={() => toggle(b.body)} aria-label={`${b.body} 표시`} />
              {b.body}
            </label>
          ))}
        {manifest.kind === "shell" && clusters.length > 0 && (
          <label className="check small">
            <input type="checkbox" checked={showFixed} onChange={(e) => setShowFixed(e.target.checked)} />
            고정 영역({clusters.length})
          </label>
        )}
        <span className="muted small gv-hint">끌기 회전 · 휠 확대 · 오른쪽 끌기 이동 · 면 클릭 = 변수 선택(Ctrl = 추가)</span>
      </div>
      <div className="gv-stage" ref={box}>
        {!ready && !error && <div className="gv-msg muted small">3D 불러오는 중…</div>}
        {error && (
          <div className="gv-msg error-text small" role="alert">
            3D를 불러오지 못했습니다 — {error}
          </div>
        )}
        {children}
      </div>
    </div>
  );
}
