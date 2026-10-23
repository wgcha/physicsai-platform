// 결과 3D 컨투어 뷰어(geometry-view.md §13.6): contour.glb 1회 + contour_frames.bin 프레임 단위 Range 로드(현재·다음 선로딩, 최근 8프레임).
// 정점 색 = 현재 프레임 스칼라(NaN 회색), 범례 [고정 | 프레임별], 타임스텝 슬라이더·재생/일시정지·속도·이전/다음, 변형 배율(변위 있을 때).
// 410(서버 캐시 정리됨)이면 onExpired → 부모가 다시 요청한다.
// 제어 모드(`control`, contour3d-default §3.1·§3.3 비교 모드): 프레임·배율·범례 범위를 부모가 정하고 내부 슬라이더·배율·범례 모드 줄은 숨긴다.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, errorMessage } from "../../../../api";
import { loadThree } from "../loadThree";
import type { ContourMeshInfo, ContourSceneApi } from "../threeScene";
import { isExpired } from "../expire";
import { fillColors, fmtLegend, legendGradient, legendTicks } from "./colormap";
import {
  applyDeform,
  applyDeformGather,
  ByteBudgetCache,
  decodeDispFor,
  decodeFrame,
  decodeScalarFor,
  defaultDeformScale,
  DEFORM_SCALES,
  DISP_BUDGET,
  DISP_DEFAULT_MAX_BYTES,
  dispRange,
  dispRecordBytes,
  extremeLabel,
  fmtTime,
  FPS_CHOICES,
  frameExtremes,
  frameRange,
  gatherValues,
  isQuantized,
  legendRange,
  LodGate,
  manifestHasDisp,
  nextFrame,
  prevFrame,
  SCALAR_BUDGET,
  tooltipText,
  warningLines,
  type Contour3dEx,
  type ContourManifest,
  type LegendMode,
  type LodLevel,
} from "./contourCore";

/** 비교 모드에서 부모가 쥐는 값. legend = 외부 범례 [min,max](null이면 이 뷰어의 고정 범위), showLegend = 이 뷰어 안에 범례 막대를 보일지, playing = 부모의 재생 중 여부(LOD 유지) */
export interface ViewerControl {
  frame: number;
  scale: number;
  legend: [number, number] | null;
  showLegend: boolean;
  playing?: boolean;
}

interface Geo extends ContourMeshInfo {
  /** (LOD) 원 정점 번호 → LOD 정점 번호 — 극값 마커 위치 찾기용, 처음 필요할 때 만든다 */
  inv?: Map<number, number>;
}
interface Frame {
  i: number;
  scalar: Float32Array;
  disp: Float32Array | null;
}

export function ContourViewer({ c, onExpired, control, onManifest, onScene }: { c: Contour3dEx; onExpired: () => void; control?: ViewerControl; onManifest?: (m: ContourManifest | null) => void; onScene?: (s: ContourSceneApi | null) => void }) {
  const box = useRef<HTMLDivElement>(null);
  const scene = useRef<ContourSceneApi | null>(null);
  const geo = useRef<{ full: Geo | null; lod: Geo | null }>({ full: null, lod: null });
  const man = useRef<ContourManifest | null>(null);
  const sCache = useRef(new ByteBudgetCache<Float32Array>(SCALAR_BUDGET));
  const dCache = useRef(new ByteBudgetCache<Float32Array>(DISP_BUDGET));
  const whole = useRef<{ s: ArrayBuffer | null; d: ArrayBuffer | null }>({ s: null, d: null });
  const inflight = useRef(new Map<string, Promise<unknown>>());
  const gate = useRef<LodGate | null>(null);
  const bufs = useRef<{ color: Record<LodLevel, Float32Array | null>; pos: Record<LodLevel, Float32Array | null>; vals: Float32Array | null }>({ color: { lod: null, full: null }, pos: { lod: null, full: null }, vals: null });
  const [m, setM] = useState<ContourManifest | null>(null);
  const [ready, setReady] = useState(false);
  const [geoVer, setGeoVer] = useState(0);
  const [level, setLevel] = useState<LodLevel>("full");
  const [useLod, setUseLod] = useState(false);
  const [fullReady, setFullReady] = useState(false);
  const [fullErr, setFullErr] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [idxOwn, setIdx] = useState(0);
  const [frame, setFrame] = useState<Frame | null>(null);
  const [dispFail, setDispFail] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [fps, setFps] = useState(5);
  const [mode, setMode] = useState<LegendMode>("global");
  const [scaleOwn, setScale] = useState(1);
  const [tip, setTip] = useState<{ x: number; y: number; text: string } | null>(null);
  const expired = useRef(onExpired);
  expired.current = onExpired;
  const report = useRef({ onManifest, onScene });
  report.current = { onManifest, onScene };
  const idx = control ? Math.max(0, Math.min(control.frame, (m?.frames.count ?? 1) - 1)) : idxOwn;
  const scale = control ? control.scale : scaleOwn;
  const isPlaying = control ? !!control.playing : playing;
  const frameRef = useRef<{ f: Frame | null; idx: number; m: ContourManifest | null }>({ f: null, idx: 0, m: null });
  frameRef.current = { f: frame, idx, m };

  const fail = useCallback((e: unknown) => {
    if (isExpired(e)) expired.current();
    else setError(errorMessage(e));
  }, []);

  useEffect(() => {
    const el = box.current;
    if (!el || !c.manifest_artifact_id || !c.glb_artifact_id || !c.frames_artifact_id) return;
    let alive = true;
    let made: ContourSceneApi | null = null;
    const offs: (() => void)[] = [];
    sCache.current.clear();
    dCache.current.clear();
    whole.current = { s: null, d: null };
    inflight.current.clear();
    geo.current = { full: null, lod: null };
    bufs.current = { color: { lod: null, full: null }, pos: { lod: null, full: null }, vals: null };
    man.current = null;
    setDispFail(false);
    setFullErr(null);
    setFullReady(false);
    setFrame(null);
    setTip(null);
    (async () => {
      const [mod, manifest] = await Promise.all([loadThree(), api.artifactJson<ContourManifest>(c.manifest_artifact_id!)]);
      if (!alive) return;
      man.current = manifest;
      void loadScalar(0).catch(() => undefined); // 첫 프레임은 메시와 함께 받는다(LOD 첫 표시)
      made = mod.createContourScene(el, { onLost: () => setError("3D 표시가 중단되었습니다(그래픽 컨텍스트 손실)") });
      const lod = !!manifest.lod && !!c.lod_artifact_id;
      const first = await api.artifactBuffer(lod ? c.lod_artifact_id! : c.glb_artifact_id!);
      if (!alive) return;
      const info = await made.setMesh(first.buffer, lod ? "lod" : "full");
      if (!alive) return;
      geo.current[lod ? "lod" : "full"] = info;
      const g = new LodGate(lod, (l) => alive && setLevel(l));
      gate.current = g;
      offs.push(made.onInteract((e) => (e === "start" ? g.start() : e === "end" ? g.end() : g.pulse())));
      offs.push(
        made.onPick((hit) => {
          const cur = frameRef.current;
          if (!hit || !cur.f || !cur.m) return setTip(null);
          const gi = geo.current[hit.level];
          const v = hit.level === "lod" ? (gi?.src?.[hit.vertex] ?? -1) : hit.vertex;
          if (v < 0) return setTip(null);
          setTip({ x: hit.x, y: hit.y, text: tooltipText(gi?.nodeIds?.[hit.vertex] ?? null, cur.f.scalar[v], cur.m.frames.list[cur.idx]?.scale, cur.m.unit) });
        }),
      );
      scene.current = made;
      setUseLod(lod);
      setLevel(g.level);
      setScale(defaultDeformScale(manifest));
      setIdx(0);
      setM(manifest);
      setReady(true);
      setGeoVer((v) => v + 1);
      report.current.onManifest?.(manifest);
      report.current.onScene?.(made);
      if (lod) {
        // 전체 해상도는 백그라운드로 — 받으면 조작이 멈춘 뒤 바꾼다
        try {
          const full = await api.artifactBuffer(c.glb_artifact_id!);
          if (!alive) return;
          geo.current.full = await made.setMesh(full.buffer, "full");
          if (!alive) return;
          setGeoVer((v) => v + 1);
          setFullReady(true);
          g.setFullReady(true);
        } catch (e) {
          if (!alive) return;
          if (isExpired(e)) expired.current();
          else setFullErr(errorMessage(e));
        }
      } else setFullReady(true);
    })().catch((e) => alive && fail(e));
    return () => {
      alive = false;
      offs.forEach((f) => f());
      gate.current?.dispose();
      gate.current = null;
      scene.current = null;
      report.current.onScene?.(null);
      report.current.onManifest?.(null);
      made?.dispose();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [c.manifest_artifact_id, c.glb_artifact_id, c.frames_artifact_id, c.lod_artifact_id, fail]);

  /** 같은 레코드를 동시에 두 번 받지 않는다 */
  const once = useCallback(<T,>(key: string, run: () => Promise<T>): Promise<T> => {
    const hit = inflight.current.get(key) as Promise<T> | undefined;
    if (hit) return hit;
    const p = run().finally(() => inflight.current.delete(key));
    inflight.current.set(key, p);
    return p;
  }, []);

  /** 레코드 읽기: Range 206이면 레코드 1개, Range 미지원(200 전체)이면 전체를 한 번 받아 그 안에서 디코딩 */
  const record = useCallback(
    async (kind: "s" | "d", artifact: string, range: [number, number]): Promise<{ buf: ArrayBuffer; off: number }> => {
      const w = whole.current;
      if (w[kind]) return { buf: w[kind]!, off: range[0] };
      const r = await api.artifactBuffer(artifact, range);
      if (r.partial) return { buf: r.buffer, off: 0 };
      w[kind] = r.buffer;
      return { buf: r.buffer, off: range[0] };
    },
    [],
  );

  /** schema 1(레코드에 변위가 섞임): 한 번 받아 스칼라·변위 캐시를 모두 채운다 */
  const fetchV1 = useCallback(
    (i: number) =>
      once(`v1:${i}`, async () => {
        const mm = man.current!;
        const { buf, off } = await record("s", c.frames_artifact_id!, frameRange(mm, i));
        const f = decodeFrame(buf, mm.mesh.nodes, mm.frames.has_disp, off);
        sCache.current.set(i, f.scalar);
        if (f.disp) dCache.current.set(i, f.disp);
      }),
    [once, record, c.frames_artifact_id],
  );

  const loadScalar = useCallback(
    async (i: number): Promise<Float32Array> => {
      const hit = sCache.current.get(i);
      if (hit) return hit;
      const mm = man.current!;
      if (!isQuantized(mm)) {
        await fetchV1(i);
        return sCache.current.get(i)!;
      }
      return once(`s:${i}`, async () => {
        const { buf, off } = await record("s", c.frames_artifact_id!, frameRange(mm, i));
        const v = decodeScalarFor(mm, i, buf, off);
        sCache.current.set(i, v);
        return v;
      });
    },
    [once, record, fetchV1, c.frames_artifact_id],
  );

  /** 변위는 변형 배율 > 0일 때만(schema 2 = 별도 파일 Range) */
  const loadDisp = useCallback(
    async (i: number): Promise<Float32Array> => {
      const hit = dCache.current.get(i);
      if (hit) return hit;
      const mm = man.current!;
      if (!isQuantized(mm)) {
        await fetchV1(i);
        return dCache.current.get(i)!;
      }
      if (!c.disp_artifact_id) throw new Error("변위 파일이 없습니다");
      return once(`d:${i}`, async () => {
        const { buf, off } = await record("d", c.disp_artifact_id!, dispRange(mm, i));
        const v = decodeDispFor(mm, i, buf, off);
        dCache.current.set(i, v);
        return v;
      });
    },
    [once, record, fetchV1, c.disp_artifact_id],
  );

  const hasDisp = !!m && manifestHasDisp(m) && !dispFail && (!isQuantized(m) || !!c.disp_artifact_id);
  const wantDisp = hasDisp && scale > 0;

  useEffect(() => {
    if (!ready || !m) return;
    let alive = true;
    const sp = loadScalar(idx);
    const dp = wantDisp
      ? loadDisp(idx).catch((e) => {
          if (isExpired(e)) throw e;
          setDispFail(true); // 변위 조회 실패 → 스칼라만으로 계속(C3F-19)
          return null;
        })
      : Promise.resolve(null);
    Promise.all([sp, dp])
      .then(([scalar, disp]) => {
        if (!alive) return;
        setFrame({ i: idx, scalar, disp });
        if (m.frames.count > 1) {
          const n = nextFrame(idx, m.frames.count);
          void loadScalar(n).catch(() => undefined); // 다음 프레임 선로딩
          if (wantDisp) void loadDisp(n).catch(() => undefined);
        }
      })
      .catch((e) => alive && fail(e));
    return () => {
      alive = false;
    };
  }, [ready, m, idx, wantDisp, loadScalar, loadDisp, fail]);

  const range = m ? (control ? (control.legend ?? legendRange(m, idx, "global")) : legendRange(m, idx, mode)) : null;
  const lo = range?.[0] ?? null;
  const hi = range?.[1] ?? null;
  useEffect(() => {
    const s = scene.current;
    const g = geo.current[level];
    if (!s || !frame || !g) return;
    const b = bufs.current;
    if (level === "full") {
      b.color.full = b.color.full?.length === g.nodes * 3 ? b.color.full : new Float32Array(g.nodes * 3);
      s.setColors(fillColors(frame.scalar, lo ?? 0, hi ?? 1, b.color.full, true), "full");
    } else if (g.src) {
      b.color.lod = b.color.lod?.length === g.nodes * 3 ? b.color.lod : new Float32Array(g.nodes * 3);
      b.vals = b.vals?.length === g.nodes ? b.vals : new Float32Array(g.nodes);
      s.setColors(fillColors(gatherValues(frame.scalar, g.src, b.vals), lo ?? 0, hi ?? 1, b.color.lod, true), "lod");
    }
  }, [frame, lo, hi, level, geoVer]);
  useEffect(() => {
    const s = scene.current;
    const g = geo.current[level];
    if (!s || !frame || !g) return;
    const b = bufs.current;
    const k = level;
    b.pos[k] = b.pos[k]?.length === g.base.length ? b.pos[k] : new Float32Array(g.base.length);
    const sc = wantDisp ? scale : 0;
    s.setPositions(level === "lod" && g.src ? applyDeformGather(g.base, frame.disp, sc, g.src, b.pos[k]!) : applyDeform(g.base, frame.disp, sc, b.pos[k]!), level);
  }, [frame, scale, wantDisp, level, geoVer]);
  // 위치·색을 채운 뒤에 보이는 단계를 바꾼다(전환 때 깜박임 방지)
  useEffect(() => {
    scene.current?.setLevel(level);
  }, [level, geoVer]);

  // 극값 마커(§5.5): 현재 프레임 최대·최소 정점의 원 위치(변형 반영) — LOD·전체 모두. 전체를 아직 못 받았고 LOD에 없는 정점은 위치를 알 수 없어 라벨만 보인다
  const extremes = useMemo(() => {
    if (!m) return [];
    return frameExtremes(m, idx).map((e) => {
      const f = geo.current.full;
      const l = geo.current.lod;
      let at = f ? e.vertex : -1; // 전체 메시에서의 정점 번호
      let j = -1; // LOD 정점 번호
      if (!f && l?.src) {
        l.inv ??= new Map(Array.from(l.src, (v, k) => [v, k] as const));
        j = l.inv.get(e.vertex) ?? -1;
        at = j;
      }
      const g = f ?? l;
      const nodeId = at >= 0 ? (g?.nodeIds?.[at] ?? null) : null;
      return { e, label: extremeLabel(e, nodeId, m.unit), base: at >= 0 && g ? ([g.base[at * 3], g.base[at * 3 + 1], g.base[at * 3 + 2]] as [number, number, number]) : null };
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [m, idx, geoVer]);
  useEffect(() => {
    const s = scene.current;
    if (!s || !frame) return;
    s.setMarkers(
      extremes.flatMap(({ e, base }) => {
        if (!base) return [];
        const d = wantDisp && frame.disp ? [frame.disp[e.vertex * 3], frame.disp[e.vertex * 3 + 1], frame.disp[e.vertex * 3 + 2]] : [0, 0, 0];
        const f = (k: number) => base[k] + (wantDisp ? scale : 0) * (Number.isFinite(d[k]) ? d[k] : 0);
        return [{ kind: e.kind, pos: [f(0), f(1), f(2)] as [number, number, number] }];
      }),
    );
  }, [extremes, frame, scale, wantDisp]);
  useEffect(() => setTip(null), [idx]);

  // 재생·조작 중에는 LOD(§7.3)
  useEffect(() => {
    gate.current?.setPlaying(isPlaying);
  }, [isPlaying, ready]);

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
          void loadScalar(n).catch(() => undefined);
          if (wantDisp) void loadDisp(n).catch(() => undefined);
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
  }, [playing, fps, m, loadScalar, loadDisp, wantDisp, control]);

  const info = m?.frames.list[idx];
  const warns = warningLines(m);
  const dispMB = m ? dispRecordBytes(m) : 0;
  const ticks = useMemo(() => (lo != null && hi != null ? legendTicks(lo, hi, 5) : []), [lo, hi]);
  const count = m?.frames.count ?? 0;
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
        {extremes.length > 0 && (
          <div className="gv-note small mono" data-testid="contour-extremes">
            {extremes.map(({ e, label }) => (
              <div key={e.kind} data-testid={`contour-extreme-${e.kind}`}>
                {label}
              </div>
            ))}
          </div>
        )}
        {tip && (
          <div className="gv-pt-tip" style={{ left: tip.x + 12, top: tip.y + 12 }} data-testid="contour-tip">
            {tip.text}
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
          {hasDisp && (
            <label className="small" title="변형 후 위치 = 원위치 + 배율 × 변위">
              변형 배율{" "}
              <select value={customScale ? "custom" : String(scale)} onChange={(e) => setScale(e.target.value === "custom" ? 2 : Number(e.target.value))} aria-label="변형 배율">
                {DEFORM_SCALES.map((s) => (
                  <option key={s} value={s}>
                    ×{s}
                  </option>
                ))}
                <option value="custom">직접</option>
              </select>
            </label>
          )}
          {hasDisp && customScale && <input className="num-input" aria-label="변형 배율 직접 입력" inputMode="decimal" value={scale} onChange={(e) => Number.isFinite(Number(e.target.value)) && setScale(Number(e.target.value))} />}
          {hasDisp && scale > 0 && dispMB > DISP_DEFAULT_MAX_BYTES && (
            <span className="muted small" data-testid="contour-disp-size">
              변형 데이터 프레임당 {(dispMB / 1048576).toFixed(1)} MB
            </span>
          )}
          <button type="button" className="btn small ghost" onClick={() => scene.current?.fit()} disabled={!ready}>
            맞춤
          </button>
        </div>
      )}
      {useLod && !fullReady && !fullErr && (
        <p className="muted small c3-note" data-testid="contour-full-loading">
          전체 해상도 받는 중…
        </p>
      )}
      {fullErr && (
        <p className="error-text small c3-note" data-testid="contour-full-error">
          전체 해상도를 받지 못해 간략 형상으로 표시합니다 — {fullErr}
        </p>
      )}
      {warns.map((w) => (
        <p key={w.code} className="muted small c3-note" data-testid="contour-warning" data-code={w.code}>
          {w.text}
        </p>
      ))}
    </div>
  );
}
