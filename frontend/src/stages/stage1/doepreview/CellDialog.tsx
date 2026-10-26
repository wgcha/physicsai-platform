// 셀 클릭 → 기존 3D 뷰어(GeomViewer) 대화상자 1개(doe-preview.md §7 "클릭"): 공칭 반투명 + 셀 GLB 변위 색(같은 범위) + 실패 빨강.
// WebGL 컨텍스트는 이 창이 열려 있는 동안 1개, 닫으면 dispose. WebGL 불가·3D 적재 실패면 같은 PNG를 2배(640×480)로 + 값 표.
import { useEffect, useMemo, useState } from "react";
import { API_PREFIX, api, errorMessage } from "../../../api";
import type { DoePreviewCell } from "../../../api/types";
import { useMediaImageState } from "../../stage4/ContourMedia";
import { MediaDialog } from "../../stage4/geomview/contour/MediaDialog";
import { GeomViewer, type Overlay } from "../../stage4/geomview/GeomViewer";
import { fmtLegend, legendGradient, legendTicks } from "../../stage4/geomview/contour/colormap";
import { EMPTY_HIGHLIGHT, failureHighlight, type PreviewManifest, type ViewManifest } from "../../stage4/geomview/viewerCore";
import { gvReasonText, webglAvailable, type GvFailure } from "../../stage4/geomview/webgl";
import { cellLabel, failInfo, relPct } from "./gridModel";

interface Loaded {
  nominal: ViewManifest;
  cell: PreviewManifest | null;
  overlay: Overlay | null;
}

function ValuesTable({ cell }: { cell: DoePreviewCell }) {
  const rel = new Map((cell.top_changes ?? []).map((t) => [t.name, t.rel]));
  const rows = Object.entries(cell.values ?? {});
  if (!rows.length) return <p className="muted small">공칭(변경 없음)</p>;
  return (
    <table className="table compact dp-values" aria-label="표본 변수 값">
      <thead>
        <tr>
          <th>변수</th>
          <th className="num">값</th>
          <th className="num">범위 대비</th>
        </tr>
      </thead>
      <tbody>
        {rows.map(([k, v]) => (
          <tr key={k}>
            <td className="mono small">{k}</td>
            <td className="num mono">{Number(v.toPrecision(5))}</td>
            <td className="num mono small muted">{rel.has(k) ? relPct(rel.get(k)!) : ""}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function BigPng({ cell, label }: { cell: DoePreviewCell; label: string }) {
  const img = useMediaImageState(cell.png_artifact_id ? `${API_PREFIX}/artifacts/${cell.png_artifact_id}/media` : null);
  return (
    <div className="dp-big" data-testid="dp-big-png">
      {img.src && <img src={img.src} alt={`${label} 형상(확대)`} width={640} height={480} />}
      {img.error && (
        <span className="small error-text" role="alert">
          그림을 불러오지 못했습니다({img.error})
        </span>
      )}
    </div>
  );
}

export function CellDialog({ cell, nominal, range, gallery, onClose }: { cell: DoePreviewCell; nominal: DoePreviewCell | null; range: [number, number]; gallery: boolean; onClose: () => void }) {
  const label = cellLabel(cell, gallery);
  const gl = webglAvailable();
  const canLoad = gl && !!nominal?.glb_artifact_id && !!nominal?.manifest_artifact_id;
  const [data, setData] = useState<Loaded | null>(null);
  const [failure, setFailure] = useState<GvFailure | null>(null);
  useEffect(() => {
    if (!canLoad) return;
    let alive = true;
    setData(null);
    setFailure(null);
    (async () => {
      const own = !cell.nominal;
      const [nm, cm, glb] = await Promise.all([
        api.artifactJson<ViewManifest>(nominal!.manifest_artifact_id!),
        own && cell.manifest_artifact_id ? api.artifactJson<PreviewManifest>(cell.manifest_artifact_id) : Promise.resolve(null),
        own && cell.glb_artifact_id ? api.artifactBuffer(cell.glb_artifact_id) : Promise.resolve(null),
      ]);
      if (!alive) return;
      setData({ nominal: nm, cell: cm, overlay: glb ? { buf: glb.buffer, kind: "shape", dispMax: range[1] } : null });
    })().catch((e) => alive && setFailure({ kind: "view", code: errorMessage(e).slice(0, 60) }));
    return () => {
      alive = false;
    };
    // cell·nominal은 artifact id가 같으면 같은 내용
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [canLoad, cell.glb_artifact_id, cell.manifest_artifact_id, nominal?.glb_artifact_id, nominal?.manifest_artifact_id]);
  const red = useMemo(() => failureHighlight(data?.cell ?? null), [data]);
  const highlight = useMemo(() => ({ ...EMPTY_HIGHLIGHT, red: red.red }), [red]);
  const fail = failInfo(cell);
  const show3d = canLoad && !failure;
  const reason: GvFailure | null = !gl ? { kind: "no-webgl" } : failure ?? (!canLoad ? { kind: "noview" } : null);

  return (
    <MediaDialog title={`${label} — 형상`} onClose={onClose}>
      <div className="dp-dialog" data-testid="dp-dialog">
        {fail && (
          <p className="small" data-testid="dp-dialog-fail">
            <span className="pill bad">{fail.badge}</span> {fail.text}
          </p>
        )}
        {show3d ? (
          data ? (
            <GeomViewer
              glbId={nominal!.glb_artifact_id!}
              manifest={data.nominal}
              highlight={highlight}
              overlay={data.overlay}
              redClusters={red.clusters}
              points={red.points}
              onPick={() => undefined}
              onLost={() => setFailure({ kind: "lost" })}
              onFail={setFailure}
            >
              <div className="gv-legend" data-testid="dp-dialog-legend" aria-label="변위 범례">
                <div className="small">공칭 형상과의 거리(mm)</div>
                <div className="gv-legend-body">
                  <div className="gv-legend-bar" style={{ background: legendGradient() }} />
                  <div className="gv-legend-ticks small mono">
                    {legendTicks(0, range[1], 3).map((t, i) => (
                      <span key={i}>{fmtLegend(t)}</span>
                    ))}
                  </div>
                </div>
              </div>
            </GeomViewer>
          ) : (
            <p className="muted small">3D 불러오는 중…</p>
          )
        ) : (
          <>
            {reason && (
              <p className="muted small" data-testid="dp-dialog-fallback" role="status">
                {gvReasonText(reason)}
              </p>
            )}
            <BigPng cell={cell} label={label} />
          </>
        )}
        <ValuesTable cell={cell} />
      </div>
    </MediaDialog>
  );
}
