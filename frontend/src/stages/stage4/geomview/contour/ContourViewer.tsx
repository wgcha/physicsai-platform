// 결과 3D 컨투어 뷰어(geometry-view.md §13.6): contour.glb 1회 + contour_frames.bin 프레임 단위 Range 로드(현재·다음 선로딩, 최근 8프레임).
// 정점 색 = 현재 프레임 스칼라(NaN 회색), 범례 [고정 | 프레임별], 타임스텝 슬라이더·재생/일시정지·속도·이전/다음, 변형 배율(변위 있을 때).
// 410(서버 캐시 정리됨)이면 onExpired → 부모가 다시 요청한다.
// 제어 모드(`control`, contour3d-default §3.1·§3.3 비교 모드): 프레임·배율·범례 범위를 부모가 정하고 내부 슬라이더·배율·범례 모드 줄은 숨긴다.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, errorMessage, type Contour3d } from "../../../../api";
import { loadThree } from "../loadThree";
import type { ContourSceneApi } from "../threeScene";
import { isExpired } from "../expire";
import { fillColors, fmtLegend, legendGradient, legendTicks } from "./colormap";
import { applyDeform, decodeFrame, DEFORM_SCALES, FPS_CHOICES, FrameCache, fmtTime, frameRange, legendRange, nextFrame, prevFrame, type ContourManifest, type DecodedFrame, type LegendMode } from "./contourCore";

/** 비교 모드에서 부모가 쥐는 값. legend = 외부 범례 [min,max](null이면 이 뷰어의 고정 범위), showLegend = 이 뷰어 안에 범례 막대를 보일지 */
export interface ViewerControl {
  frame: number;
  scale: number;
  legend: [number, number] | null;
  showLegend: boolean;
}

export function ContourViewer({ c, onExpired, control, onManifest, onScene }: { c: Contour3d; onExpired: () => void; control?: ViewerControl; onManifest?: (m: ContourManifest | null) => void; onScene?: (s: ContourSceneApi | null) => void }) {
  const box = useRef<HTMLDivElement>(null);
  const scene = useRef<ContourSceneApi | null>(null);
  const base = useRef<Float32Array | null>(null);
  const cache = useRef(new FrameCache<DecodedFrame>(8));
  const full = useRef<ArrayBuffer | null>(null);
  const colors = useRef<Float32Array | null>(null);
  const pos = useRef<Float32Array | null>(null);
  const [m, setM] = useState<ContourManifest | null>(null);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [idxOwn, setIdx] = useState(0);
  const [frame, setFrame] = useState<DecodedFrame | null>(null);
  const [playing, setPlaying] = useState(false);
  const [fps, setFps] = useState(5);
  const [mode, setMode] = useState<LegendMode>("global");
  const [scaleOwn, setScale] = useState(1);
  const expired = useRef(onExpired);
  expired.current = onExpired;
  const report = useRef({ onManifest, onScene });
  report.current = { onManifest, onScene };
  const idx = control ? Math.max(0, Math.min(control.frame, (m?.frames.count ?? 1) - 1)) : idxOwn;
  const scale = control ? control.scale : scaleOwn;

  const fail = useCallback((e: unknown) => {
    if (isExpired(e)) expired.current();
    else setError(errorMessage(e));
  }, []);

  useEffect(() => {
    const el = box.current;
    if (!el || !c.manifest_artifact_id || !c.glb_artifact_id || !c.frames_artifact_id) return;
    let alive = true;
    let made: ContourSceneApi | null = null;
    cache.current.clear();
    full.current = null;
    (async () => {
      const [mod, manifest, glb] = await Promise.all([loadThree(), api.artifactJson<ContourManifest>(c.manifest_artifact_id!), api.artifactBuffer(c.glb_artifact_id!)]);
      if (!alive) return;
      made = mod.createContourScene(el, { onLost: () => setError("3D 표시가 중단되었습니다(그래픽 컨텍스트 손실)") });
      const r = await made.setMesh(glb.buffer);
      if (!alive) return;
      base.current = r.base;
      colors.current = new Float32Array(r.nodes * 3);
      pos.current = new Float32Array(r.base.length);
      scene.current = made;
      setM(manifest);
      setScale(manifest.frames.has_disp ? 1 : 0);
      setIdx(0);
      setReady(true);
      report.current.onManifest?.(manifest);
      report.current.onScene?.(made);
    })().catch((e) => alive && fail(e));
    return () => {
      alive = false;
      scene.current = null;
      report.current.onScene?.(null);
      report.current.onManifest?.(null);
      made?.dispose();
    };
  }, [c.manifest_artifact_id, c.glb_artifact_id, c.frames_artifact_id, fail]);

  /** 프레임 i 읽기: Range 206이면 레코드 1개, Range 미지원(200 전체)이면 전체를 한 번 받아 그 안에서 디코딩 */
  const load = useCallback(
    async (i: number): Promise<DecodedFrame> => {
      const man = m!;
      const hit = cache.current.get(i);
      if (hit) return hit;
      const n = man.mesh.nodes;
      const hd = man.frames.has_disp;
      let f: DecodedFrame;
      if (full.current) f = decodeFrame(full.current, n, hd, frameRange(man, i)[0]);
      else {
        const r = await api.artifactBuffer(c.frames_artifact_id!, frameRange(man, i));
        if (r.partial) f = decodeFrame(r.buffer, n, hd);
        else {
          full.current = r.buffer;
          f = decodeFrame(r.buffer, n, hd, frameRange(man, i)[0]);
        }
      }
      cache.current.set(i, f);
      return f;
    },
    [m, c.frames_artifact_id],
  );

  useEffect(() => {
    if (!ready || !m) return;
    let alive = true;
    load(idx)
      .then((f) => {
        if (!alive) return;
        setFrame(f);
        if (m.frames.count > 1) void load(nextFrame(idx, m.frames.count)).catch(() => undefined); // 다음 프레임 선로딩
      })
      .catch((e) => alive && fail(e));
    return () => {
      alive = false;
    };
  }, [ready, m, idx, load, fail]);

  const range = m ? (control ? (control.legend ?? legendRange(m, idx, "global")) : legendRange(m, idx, mode)) : null;
  const lo = range?.[0] ?? null;
  const hi = range?.[1] ?? null;
  useEffect(() => {
    const s = scene.current;
    if (!s || !frame || !colors.current) return;
    s.setColors(fillColors(frame.scalar, lo ?? 0, hi ?? 1, colors.current, true));
  }, [frame, lo, hi]);
  useEffect(() => {
    const s = scene.current;
    if (!s || !frame || !base.current || !pos.current) return;
    s.setPositions(applyDeform(base.current, frame.disp, scale, pos.current));
  }, [frame, scale]);

  // 재생: 1000/fps마다 다음 프레임(받아 둔 뒤 넘김, 반복). 재생 중에만 연속 렌더
  useEffect(() => {
    scene.current?.setLoop(playing);
    if (!playing || !m || control) return;
    let alive = true;
    let t: ReturnType<typeof setTimeout>;
    const tick = () => {
      t = setTimeout(async () => {
        if (!alive) return;
        setIdx((i) => {
          const n = nextFrame(i, m.frames.count);
          void load(n).catch(() => undefined);
          return n;
        });
        tick();
      }, 1000 / fps);
    };
    tick();
    return () => {
      alive = false;
      clearTimeout(t);
    };
  }, [playing, fps, m, load, control]);

  const info = m?.frames.list[idx];
  const ticks = useMemo(() => (lo != null && hi != null ? legendTicks(lo, hi, 5) : []), [lo, hi]);
  const count = m?.frames.count ?? 0;
  const hasDisp = !!m?.frames.has_disp;
  const customScale = !(DEFORM_SCALES as readonly number[]).includes(scale);

  return (
    <div className="c3-viewer" data-testid="contour-viewer">
      <div className="gv-stage c3-stage" ref={box}>
        {!ready && !error && <div className="gv-msg muted small">3D 컨투어 불러오는 중…</div>}
        {error && (
          <div className="gv-msg error-text small" role="alert">
            {error}
          </div>
        )}
        {m && range && (!control || control.showLegend) && (
          <div className="gv-legend" data-testid="contour-legend">
            <div className="small">
              {m.display?.field ?? "값"}
              {m.display?.comp ? ` · ${m.display.comp}` : ""} {m.unit ? `(${m.unit})` : ""}
            </div>
            <div className="gv-legend-body">
              <div className="gv-legend-bar" style={{ background: legendGradient() }} />
              <div className="gv-legend-ticks small mono">
                {ticks.map((v, i) => (
                  <span key={i}>{fmtLegend(v)}</span>
                ))}
              </div>
            </div>
            {!control && (
            <div className="seg c3-legend-mode" role="group" aria-label="범례 범위">
              <button type="button" className={mode === "global" ? "on" : ""} aria-pressed={mode === "global"} onClick={() => setMode("global")} title="전체 프레임 min·max">
                고정
              </button>
              <button type="button" className={mode === "frame" ? "on" : ""} aria-pressed={mode === "frame"} onClick={() => setMode("frame")} title="이 프레임 min·max">
                프레임별
              </button>
            </div>
            )}
          </div>
        )}
      </div>
      {m && !control && (
        <div className="c3-controls">
          <button type="button" className="btn small ghost" onClick={() => setIdx((i) => prevFrame(i, count))} disabled={count < 2} aria-label="이전 프레임">
            이전
          </button>
          <button type="button" className="btn small" onClick={() => setPlaying((p) => !p)} disabled={count < 2} aria-pressed={playing}>
            {playing ? "일시정지" : "재생"}
          </button>
          <button type="button" className="btn small ghost" onClick={() => setIdx((i) => nextFrame(i, count))} disabled={count < 2} aria-label="다음 프레임">
            다음
          </button>
          <input className="c3-slider" type="range" min={0} max={Math.max(0, count - 1)} step={1} value={idx} onChange={(e) => setIdx(Number(e.target.value))} aria-label="타임스텝" />
          <span className="small mono c3-frame" data-testid="contour-frame">
            {idx + 1}/{count} · t = {fmtTime(info?.time)}
          </span>
          <label className="small">
            속도{" "}
            <select value={fps} onChange={(e) => setFps(Number(e.target.value))} aria-label="재생 속도">
              {FPS_CHOICES.map((f) => (
                <option key={f} value={f}>
                  {f} fps
                </option>
              ))}
            </select>
          </label>
          <label className="small" title={hasDisp ? "변형 후 위치 = 원위치 + 배율 × 변위" : "변위가 없는 결과입니다"}>
            변형 배율{" "}
            <select value={customScale ? "custom" : String(scale)} disabled={!hasDisp} onChange={(e) => setScale(e.target.value === "custom" ? 2 : Number(e.target.value))} aria-label="변형 배율">
              {DEFORM_SCALES.map((s) => (
                <option key={s} value={s}>
                  ×{s}
                </option>
              ))}
              <option value="custom">직접</option>
            </select>
          </label>
          {hasDisp && customScale && <input className="num-input" aria-label="변형 배율 직접 입력" inputMode="decimal" value={scale} onChange={(e) => Number.isFinite(Number(e.target.value)) && setScale(Number(e.target.value))} />}
          <button type="button" className="btn small ghost" onClick={() => scene.current?.fit()} disabled={!ready}>
            맞춤
          </button>
        </div>
      )}
    </div>
  );
}
