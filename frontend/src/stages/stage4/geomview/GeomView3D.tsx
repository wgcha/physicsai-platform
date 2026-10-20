// 피처 표 옆 [3D | 그림] 2단 전환(geometry-view.md §7.2·§6.9): ④ native 세트 상세·①-2 파라미터 표가 같이 쓴다.
// 기본 3D — WebGL 불가·컨텍스트 손실·view.status ≠ READY·available=false면 그림만. 표 행 ↔ 3D 면 양방향 선택은 부모의 row로 공유.
// 미리보기(§7.3)는 preview_available && paramSetId일 때만(④). 겹쳐 보기: 공칭 반투명 + 변경 형상(변위 색) / FE 메시.
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { api, type GeomView } from "../../../api";
import { GeomViewer, type Overlay } from "./GeomViewer";
import { PreviewPanel } from "./PreviewPanel";
import { useGeomPreview } from "./useGeomPreview";
import { chooseRow, NO_SELECTION, pickFace, type Selection } from "./selection";
import { webglAvailable } from "./webgl";
import { buildFaceRows, dispMax, failureHighlight, hasRow3d, LOST_WEBGL_3D, NO_WEBGL_3D, previewValues, rowHighlight, type ViewManifest } from "./viewerCore";
import { fmtLegend, legendGradient, legendTicks } from "./contour/colormap";

export type GeomView3DProps = Parameters<typeof GeomView3D>[0];

export function GeomView3D({
  loadKey,
  load,
  row,
  onRow,
  picture,
  paramSetId,
  userRanges,
  canPreview = false,
}: {
  /** 바뀌면 다시 읽는다(세트 id·추출 작업 id) */
  loadKey: string;
  load: () => Promise<GeomView>;
  row: string | null;
  onRow: (row: string | null) => void;
  /** 그림 탭(기존 PNG) */
  picture: ReactNode;
  paramSetId?: string | null;
  userRanges?: Record<string, { min?: number | null; max?: number | null }>;
  canPreview?: boolean;
}) {
  const [view, setView] = useState<GeomView | null>(null);
  const [manifest, setManifest] = useState<ViewManifest | null>(null);
  const [gl] = useState(webglAvailable);
  const [lost, setLost] = useState(false);
  const [tab, setTab] = useState<"3d" | "png">("3d");
  const [sel, setSel] = useState<Selection>(NO_SELECTION);
  const [edits, setEdits] = useState<Record<string, number>>({});
  const [fe, setFe] = useState(false);
  const [feTab, setFeTab] = useState(false);

  useEffect(() => {
    let alive = true;
    setView(null);
    setManifest(null);
    load()
      .then(async (v) => {
        if (!alive) return;
        setView(v);
        if (v.status === "READY" && v.available && v.manifest_artifact_id && gl) {
          const m = await api.artifactJson<ViewManifest>(v.manifest_artifact_id);
          if (alive) setManifest(m);
        }
      })
      .catch(() => alive && setView(null)); // 뷰 없음(404·409) = 그림만
    return () => {
      alive = false;
    };
    // load는 loadKey로 바뀐다
  }, [loadKey, gl]);

  const previewOn = !!view?.preview_available && !!paramSetId;
  const pv = useGeomPreview(previewOn ? paramSetId! : null);
  useEffect(() => setSel((s) => (s.row === row ? s : { row, choices: null })), [row]);

  const ready = view?.status === "READY" && !!view.available && !!view.glb_artifact_id;
  const usable = ready && gl && !lost && !!manifest;
  // update OK면 형상 GLB가 있다(FE 실패여도 형상은 표시), update FAIL이면 GLB 없음 → 공칭 + 빨강 표시
  const okPreview = pv.preview?.status === "DONE" && !!pv.glb;
  const failPreview = pv.preview?.status === "DONE" && pv.preview.result_status === "FAIL" ? pv.manifest : null;
  const active = okPreview && pv.manifest && pv.manifest.features.length ? pv.manifest : manifest;
  const faceRows = useMemo(() => (manifest ? buildFaceRows(manifest) : new Map<string, string[]>()), [manifest]);
  const fail = useMemo(() => failureHighlight(failPreview), [failPreview]);
  const highlight = useMemo(() => {
    const h = active ? rowHighlight(active, row) : rowHighlight({ features: [] } as unknown as ViewManifest, null);
    return fail.red.size ? { ...h, red: fail.red } : h;
  }, [active, row, fail]);
  const showFe = feTab && !!pv.feGlb;
  const overlay = useMemo<Overlay | null>(() => {
    if (!okPreview) return null;
    return showFe ? { buf: pv.feGlb!, kind: "fe", dispMax: dispMax(pv.manifest, true) } : { buf: pv.glb!, kind: "shape", dispMax: dispMax(pv.manifest, false) };
  }, [okPreview, showFe, pv.glb, pv.feGlb, pv.manifest]);

  const note = ready && (!gl || lost) ? (lost ? LOST_WEBGL_3D : NO_WEBGL_3D) : null;
  if (!usable) {
    return (
      <div className="gv-wrap">
        {note && (
          <p className="muted small" data-testid="gv-fallback">
            {note}
          </p>
        )}
        {picture}
      </div>
    );
  }

  const max = overlay?.dispMax ?? null;
  const pickedNo3d = row && !hasRow3d(manifest, row);
  return (
    <div className="gv-wrap" data-testid="gv-panel">
      <div className="seg gv-tabs" role="tablist" aria-label="형상 보기">
        <button type="button" role="tab" aria-selected={tab === "3d"} className={tab === "3d" ? "on" : ""} onClick={() => setTab("3d")}>
          3D
        </button>
        <button type="button" role="tab" aria-selected={tab === "png"} className={tab === "png" ? "on" : ""} onClick={() => setTab("png")}>
          그림
        </button>
        {okPreview && pv.feGlb && tab === "3d" && (
          <>
            <button type="button" className={!feTab ? "on" : ""} aria-pressed={!feTab} onClick={() => setFeTab(false)}>
              형상
            </button>
            <button type="button" className={feTab ? "on" : ""} aria-pressed={feTab} onClick={() => setFeTab(true)}>
              FE 메시
            </button>
          </>
        )}
      </div>
      {tab === "png" ? (
        picture ?? <p className="muted small">행을 고르면 하이라이트 그림(이동 면 주황·고정 면 파랑)을 봅니다</p>
      ) : (
        <>
          <GeomViewer
            glbId={view.glb_artifact_id!}
            manifest={manifest}
            highlight={highlight}
            overlay={overlay}
            redClusters={fail.clusters}
            points={fail.points}
            onLost={() => setLost(true)}
            onPick={(hit) => {
              const next = pickFace(sel, faceRows, hit);
              setSel(next);
              if (next.row !== row) onRow(next.row);
            }}
          >
            {sel.choices && (
              <div className="gv-choices" role="listbox" aria-label="이 면을 쓰는 피처">
                <div className="small muted">이 면을 쓰는 피처</div>
                {sel.choices.map((r) => (
                  <button
                    key={r}
                    type="button"
                    role="option"
                    aria-selected={r === row}
                    className="link small mono"
                    onClick={() => {
                      setSel(chooseRow(sel, r));
                      onRow(r);
                    }}
                  >
                    {r}
                  </button>
                ))}
              </div>
            )}
            {pickedNo3d && <div className="gv-note small muted">3D 대응 없음(쉘 두께 등 — 표에서만)</div>}
            {overlay && max != null && (
              <div className="gv-legend" data-testid="disp-legend" aria-label="변위 범례">
                <div className="small">{overlay.kind === "fe" ? "노드 이동(mm)" : "공칭 형상과의 거리(mm)"}</div>
                <div className="gv-legend-body">
                  <div className="gv-legend-bar" style={{ background: legendGradient() }} />
                  <div className="gv-legend-ticks small mono">
                    {legendTicks(0, max, 3).map((t, i) => (
                      <span key={i}>{fmtLegend(t)}</span>
                    ))}
                  </div>
                </div>
              </div>
            )}
          </GeomViewer>
          {previewOn && (
            <PreviewPanel
              manifest={manifest}
              row={row && hasRow3d(manifest, row) ? row : null}
              userRange={row ? userRanges?.[row] ?? null : null}
              edits={edits}
              onEdit={(r, v) =>
                setEdits((e) => {
                  const n = { ...e };
                  if (v == null) delete n[r];
                  else n[r] = v;
                  return n;
                })
              }
              fe={fe}
              onFe={setFe}
              state={pv}
              canRun={canPreview}
              onRun={() => {
                setFeTab(false);
                void pv.run({ values: previewValues(manifest, edits), fe: fe ? "check" : "off" });
              }}
              onReset={() => {
                setEdits({});
                pv.reset();
              }}
            />
          )}
          {showFe && pv.preview?.fe_status && pv.preview.fe_status !== "PASS" && (
            <p className="small warn-text" data-testid="fe-fail">
              FE {pv.preview.fe_status}: {pv.preview.message_ko ?? pv.preview.fe_code}
            </p>
          )}
        </>
      )}
    </div>
  );
}
