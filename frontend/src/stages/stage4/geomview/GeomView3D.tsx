// 피처 표 옆 상시 3D 미리보기 창 + [3D | 그림] 전환(geometry-view.md §7.2·§6.9): ④ native 세트 상세·①-2 파라미터 표가 같이 쓴다.
// 기본 3D(공칭 형상은 선택 없이도 보임) — WebGL 불가·컨텍스트 손실·view.status ≠ READY·available=false면 그림만.
// 표 행 ↔ 3D 면 양방향 다중 선택은 부모의 rows로 공유(행마다 팔레트 색, 호버 = 임시 하이라이트, 치수선은 선택 1개일 때만).
// 미리보기(§7.3)는 preview_available && paramSetId일 때만(④). 겹쳐 보기: 공칭 반투명 + 변경 형상(변위 색) / FE 메시.
import { useEffect, useMemo, useState } from "react";
import { api, type GeomView } from "../../../api";
import { GeomViewer, type Overlay } from "./GeomViewer";
import { PreviewPanel } from "./PreviewPanel";
import { useGeomPreview } from "./useGeomPreview";
import { chooseRow, pickFace } from "./selection";
import { errCode, webglInfo, type GvFailure } from "./webgl";
import { PngGrid } from "./PngGrid";
import { ViewFallback } from "./ViewFallback";
import { buildFaceRows, dispMax, failureHighlight, hasRow3d, previewValues, rowHighlight, selectionColor, type ViewManifest } from "./viewerCore";
import { fmtLegend, legendGradient, legendTicks } from "./contour/colormap";

export type GeomView3DProps = Parameters<typeof GeomView3D>[0];

export function GeomView3D({
  loadKey,
  load,
  rows,
  hover = null,
  onRows,
  pngOf,
  firstRow,
  paramSetId,
  userRanges,
  canPreview = false,
}: {
  /** 바뀌면 다시 읽는다(세트 id·추출 작업 id) */
  loadKey: string;
  load: () => Promise<GeomView>;
  /** 선택 행(선택 순서 = 색 순서) */
  rows: string[];
  /** 표에서 마우스를 올린 행(임시 하이라이트) */
  hover?: string | null;
  /** 3D 면 클릭으로 선택이 바뀜(focus = 표에서 스크롤할 행) */
  onRows: (rows: string[], focus?: string | null) => void;
  /** 그림 탭·폴백: 행 → 하이라이트 PNG artifact id(선택 1개 = 그 PNG, 여럿 = 격자) */
  pngOf: (row: string) => string | null;
  /** 선택이 없을 때 그림 탭의 [첫 변수 보기]로 고를 행 */
  firstRow?: string | null;
  paramSetId?: string | null;
  userRanges?: Record<string, { min?: number | null; max?: number | null }>;
  canPreview?: boolean;
}) {
  const [view, setView] = useState<GeomView | null>(null);
  const [manifest, setManifest] = useState<ViewManifest | null>(null);
  const [info] = useState(webglInfo);
  const gl = info.level === "webgl2"; // three는 WebGL2 필요
  // 3D를 못 쓰는 이유(없으면 3D 표시): lost·init·glb·chunk(GeomViewer) · view(뷰·manifest 읽기) · noview(변환본 없음)
  const [failure, setFailure] = useState<GvFailure | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [tab, setTab] = useState<"3d" | "png">("3d");
  const [choices, setChoices] = useState<{ list: string[]; additive: boolean } | null>(null);
  const [edits, setEdits] = useState<Record<string, number>>({});
  const [fe, setFe] = useState(false);
  const [feTab, setFeTab] = useState(false);

  useEffect(() => {
    if (!gl) return;
    let alive = true;
    setView(null);
    setManifest(null);
    setFailure(null);
    setLoaded(false);
    (async () => {
      let v: GeomView;
      try {
        v = await load();
      } catch (e) {
        // 뷰 없음(404·409) = 변환본 없음(그림만), 그 밖(401·네트워크 등)은 원인 표시
        const st = (e as { status?: number }).status;
        if (alive) setFailure({ kind: st === 404 || st === 409 ? "noview" : "view", code: errCode(e) });
        return;
      }
      if (!alive) return;
      setView(v);
      if (v.status === "READY" && v.available && v.manifest_artifact_id) {
        try {
          const m = await api.artifactJson<ViewManifest>(v.manifest_artifact_id);
          if (alive) setManifest(m);
        } catch (e) {
          if (alive) setFailure({ kind: "view", code: errCode(e) });
        }
      } else if (alive) setFailure({ kind: "noview", code: v.status === "READY" ? "UNAVAILABLE" : v.status });
    })().finally(() => alive && setLoaded(true));
    return () => {
      alive = false;
    };
    // load는 loadKey로 바뀐다
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadKey, gl, attempt]);

  const previewOn = !!view?.preview_available && !!paramSetId;
  const pv = useGeomPreview(previewOn ? paramSetId! : null);
  const rowsKey = rows.join("\n");
  useEffect(() => setChoices(null), [rowsKey]);
  const row = rows.length === 1 ? rows[0] : null; // ④ 미리보기 입력은 단일 선택일 때만(다중 = 하이라이트 전용)

  const ready = view?.status === "READY" && !!view.available && !!view.glb_artifact_id;
  const usable = ready && gl && !failure && !!manifest;
  // update OK면 형상 GLB가 있다(FE 실패여도 형상은 표시), update FAIL이면 GLB 없음 → 공칭 + 빨강 표시
  const okPreview = pv.preview?.status === "DONE" && !!pv.glb;
  const failPreview = pv.preview?.status === "DONE" && pv.preview.result_status === "FAIL" ? pv.manifest : null;
  const active = okPreview && pv.manifest && pv.manifest.features.length ? pv.manifest : manifest;
  const faceRows = useMemo(() => (manifest ? buildFaceRows(manifest) : new Map<string, string[]>()), [manifest]);
  const fail = useMemo(() => failureHighlight(failPreview), [failPreview]);
  const highlight = useMemo(() => {
    const h = active ? rowHighlight(active, rows, hover) : rowHighlight({ features: [] } as unknown as ViewManifest, null);
    return fail.red.size ? { ...h, red: fail.red } : h;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, rowsKey, hover, fail]);
  const no3d = manifest ? rows.filter((r) => !hasRow3d(manifest, r)) : [];
  const legend = manifest ? rows.map((r, i) => ({ row: r, color: selectionColor(i) })).filter((x) => hasRow3d(manifest, x.row)) : [];
  const showFe = feTab && !!pv.feGlb;
  const overlay = useMemo<Overlay | null>(() => {
    if (!okPreview) return null;
    return showFe ? { buf: pv.feGlb!, kind: "fe", dispMax: dispMax(pv.manifest, true) } : { buf: pv.glb!, kind: "shape", dispMax: dispMax(pv.manifest, false) };
  }, [okPreview, showFe, pv.glb, pv.feGlb, pv.manifest]);

  const png = { rows, pngOf, firstRow, onRows };
  if (!usable) {
    // 빈 패널 없음: 이유 한 줄(+ 다시 시도) + 선택 변수 그림
    const reason: GvFailure = !gl ? { kind: info.level === "webgl" ? "webgl1" : "no-webgl" } : failure ?? (loaded ? { kind: "noview" } : { kind: "loading" });
    return <ViewFallback reason={reason} onRetry={() => setAttempt((n) => n + 1)} {...png} />;
  }

  const max = overlay?.dispMax ?? null;
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
        <PngGrid {...png} />
      ) : (
        <>
          <GeomViewer
            glbId={view.glb_artifact_id!}
            manifest={manifest}
            highlight={highlight}
            overlay={overlay}
            redClusters={fail.clusters}
            points={fail.points}
            key={attempt}
            onLost={() => setFailure({ kind: "lost" })}
            onFail={setFailure}
            onPick={(hit, additive = false) => {
              const next = pickFace(rows, faceRows, hit, additive);
              if (next.kind === "choices") return setChoices({ list: next.choices, additive });
              setChoices(null);
              onRows(next.rows, next.focus);
            }}
          >
            {choices && (
              <div className="gv-choices" role="listbox" aria-label="이 면을 쓰는 피처">
                <div className="small muted">이 면을 쓰는 피처</div>
                {choices.list.map((r) => (
                  <button
                    key={r}
                    type="button"
                    role="option"
                    aria-selected={rows.includes(r)}
                    className="link small mono"
                    onClick={() => {
                      setChoices(null);
                      onRows(chooseRow(rows, r, choices.additive), r);
                    }}
                  >
                    {r}
                  </button>
                ))}
              </div>
            )}
            {no3d.length > 0 && <div className="gv-note small muted">3D 대응 없음(쉘 두께 등 — 표에서만)</div>}
            {legend.length > 0 && (
              <ul className="gv-sel-legend small" data-testid="sel-legend" aria-label="선택 변수 범례">
                {legend.map((x) => (
                  <li key={x.row} className="mono">
                    <span className="gv-sel-swatch" style={{ background: x.color }} />
                    {x.row}
                  </li>
                ))}
              </ul>
            )}
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
