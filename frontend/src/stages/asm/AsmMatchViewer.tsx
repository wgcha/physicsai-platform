// 조립 매칭 3D(asm-match.md §3.2): geometry-view의 FE GLB 뷰어(GeomViewer, kind "fe")를 그대로 쓴다.
// 검사 GLB(match_fe.glb)의 `_DIST_MM`(노드 → CAD 경계 거리)으로 색을 칠하고, 선택 행의 worst 위치를 점으로 표시한다.
import { useEffect, useMemo, useState } from "react";
import { api, errorMessage, type AsmCheck } from "../../api";
import { distScale, glbArtifactId } from "../../lib/asmMatch";
import { GeomViewer, type Overlay } from "../stage4/geomview/GeomViewer";
import { EMPTY_HIGHLIGHT, type ViewManifest } from "../stage4/geomview/viewerCore";
import { fmtLegend, legendGradient, legendTicks } from "../stage4/geomview/contour/colormap";
import { webglInfo } from "../stage4/geomview/webgl";

const NO_FAIL = new Set<string>();

export function AsmMatchViewer({ check, selected }: { check: AsmCheck; selected: string | null }) {
  const id = glbArtifactId(check.glb_url);
  const [buf, setBuf] = useState<ArrayBuffer | null>(null);
  const [error, setError] = useState<string | null>(null);
  const gl = webglInfo().level === "webgl2";
  const bodies = check.rows.map((r) => r.body).join("\n");

  useEffect(() => {
    if (!id || !gl) return;
    let alive = true;
    setBuf(null);
    setError(null);
    api
      .artifactBuffer(id)
      .then((r) => alive && setBuf(r.buffer))
      .catch((e) => alive && setError(errorMessage(e)));
    return () => {
      alive = false;
    };
  }, [id, gl, check.seq]);

  // GLB 노드 이름 = 행 바디 이름(§4.3 10). 면 대응(manifest)은 쓰지 않는다
  const manifest = useMemo<ViewManifest>(
    () => ({ schema_version: 1, kind: "solid", mode: "nominal", status: "OK", bodies: bodies.split("\n").filter(Boolean).map((b) => ({ body: b, node: b, edges_node: `${b}.edges`, faces: [] })), features: [] }),
    [bodies],
  );
  const max = useMemo(() => Math.max(0, ...check.rows.map((r) => distScale(r) ?? 0)) || null, [check]);
  const overlay = useMemo<Overlay | null>(() => (buf ? { buf, kind: "fe", dispMax: max } : null), [buf, max]);
  const row = check.rows.find((r) => r.body === selected) ?? check.rows.find((r) => r.status === "FAIL") ?? check.rows[0];
  const points = useMemo(() => (row?.worst?.points ?? []).map((p, i) => ({ xyz: p.xyz, label: i === 0 ? `${row.body} 최대 ${p.dist_mm.toFixed(2)} mm` : "" })), [row]);

  if (!id) return <p className="muted small" data-testid="asm-3d-none">검사 3D 파일이 없습니다.</p>;
  if (!gl) return <p className="muted small" data-testid="asm-3d-none">3D를 쓸 수 없습니다(WebGL2 필요) — 표의 거리 값으로 확인하세요.</p>;
  if (error)
    return (
      <p className="error-text small" role="alert">
        3D를 불러오지 못했습니다 — {error}
      </p>
    );
  if (!overlay) return <p className="muted small">3D 불러오는 중…</p>;
  return (
    <div data-testid="asm-3d">
      <GeomViewer
        glbId={id}
        manifest={manifest}
        highlight={EMPTY_HIGHLIGHT}
        overlay={overlay}
        redClusters={NO_FAIL}
        points={points}
        onPick={() => undefined}
        onLost={() => setError("그래픽 컨텍스트를 잃었습니다")}
        onFail={(f) => setError(f.code ?? f.kind)}
      >
        {max != null && (
          <div className="gv-legend" data-testid="asm-legend" aria-label="경계 거리 범례">
            <div className="small">CAD 경계와의 거리(mm)</div>
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
    </div>
  );
}
