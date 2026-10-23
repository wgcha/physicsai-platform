// 비교 모드(contour3d-default §3.3, C3D-7·8): ⑥ 기존안 | 최적안, ④ FEM 검증 예측 | FEM — 3D 뷰어 2개 나란히.
// 시점 연결(기본 켬)·공통 범례(두 manifest range의 합집합, 아니면 개별 + 문구)·공용 시간 슬라이더(pairFrame)·재생·변형 배율은 공용.
// 한쪽 원본이 없으면(FEM 검증에서 예측 job 없음) 있는 쪽 하나를 단독 뷰어로 보인다. 3D를 쓸 수 없으면 media(PNG)가 그 자리에 나온다(C3D-2).
import { Suspense, useCallback, useEffect, useState, type ReactNode } from "react";
import type { Contour3dCreate } from "../../../../api";
import { ChunkErrorBoundary } from "../../../../lib/lazyWithReload";
import { useInView } from "../../../../hooks/useInView";
import type { ContourSceneApi } from "../threeScene";
import { fmtLegend, legendGradient, legendTicks } from "./colormap";
import { commonLegend, defaultDeformScale, DEFORM_SCALES, FPS_CHOICES, fmtTime, manifestHasDisp, nextFrame, pairFrame, prevFrame, showsMedia, unionBox, type ContourManifest } from "./contourCore";
import { ContourStateView, useContour3dEnabled, useContour3dOff, type SlotRender } from "./ContourSlot";
import { ReasonLine } from "./ContourReason";
import { MediaButton } from "./MediaDialog";
import { useContour3d } from "./useContour3d";

export interface CompareSide {
  label: string;
  source: Contour3dCreate | null;
  /** 열 머리 보조(목적 값·변수 요약 등) */
  head?: ReactNode;
}

export function ContourCompare3D({ left, right, media = null, mediaTitle, children }: { left: CompareSide; right: CompareSide; media?: ReactNode; mediaTitle?: string; children: (r: SlotRender) => ReactNode }) {
  const enabled = useContour3dEnabled();
  const off = useContour3dOff(!!left.source || !!right.source);
  const [inView, ref] = useInView();
  const L = useContour3d(enabled ? left.source : null, { visible: inView });
  const R = useContour3d(enabled ? right.source : null, { visible: inView });
  const [mL, setML] = useState<ContourManifest | null>(null);
  const [mR, setMR] = useState<ContourManifest | null>(null);
  const [sL, setSL] = useState<ContourSceneApi | null>(null);
  const [sR, setSR] = useState<ContourSceneApi | null>(null);
  const [frame, setFrame] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [fps, setFps] = useState(5);
  const [scaleOwn, setScale] = useState<number | null>(null);
  const [link, setLink] = useState(true);
  const [common, setCommon] = useState(true);
  const live = enabled && (!!left.source || !!right.source);
  const both = live && !!left.source && !!right.source;

  // 시점 연결: 한쪽을 돌리면 다른 쪽이 따라간다(setCamera는 변경 알림을 내지 않아 재귀 없음)
  useEffect(() => {
    if (!link || !sL || !sR) return;
    const a = sL.onCameraChange((s) => sR.setCamera(s));
    const b = sR.onCameraChange((s) => sL.setCamera(s));
    return () => {
      a();
      b();
    };
  }, [link, sL, sR]);
  // 처음 맞춤 = 두 메시 bbox 합집합으로 같은 카메라
  const fitBoth = useCallback(() => {
    if (!sL || !sR) return;
    const box = unionBox(sL.getBox(), sR.getBox());
    if (!box) return;
    sL.fitBox(box);
    sR.fitBox(box);
  }, [sL, sR]);
  useEffect(() => {
    if (sL && sR) fitBoth();
  }, [sL, sR, fitBoth]);

  const count = mL?.frames.count ?? mR?.frames.count ?? 0;
  const at = Math.max(0, Math.min(frame, count - 1));
  const rightFrame = mL && mR ? pairFrame(mL, mR, at) : at;
  // 변형 배율 컨트롤은 불러온 양쪽 모두 변위가 있을 때만(한쪽만 없어도 숨김). 기본 배율은 큰 쪽 기준(변위 레코드가 크면 0)
  const loaded = [mL, mR].filter((x): x is ContourManifest => !!x);
  const hasDisp = loaded.length > 0 && loaded.every(manifestHasDisp);
  const scale = scaleOwn ?? (loaded.length ? Math.min(...loaded.map(defaultDeformScale)) : 0);
  const leg = commonLegend(mL, mR);
  const useCommon = common && leg.shareable;
  const customScale = !(DEFORM_SCALES as readonly number[]).includes(scale);

  // 재생(공용): 1000/fps마다 다음 프레임(반복)
  useEffect(() => {
    if (!playing || count < 2) return;
    const t = setInterval(() => setFrame((i) => nextFrame(i, count)), 1000 / fps);
    return () => clearInterval(t);
  }, [playing, fps, count]);

  if (!live)
    return (
      <>
        {children({
          aside: null,
          mode: "media",
          body: (
            <div className="contour-slot media">
              {off && <ReasonLine text={off} />}
              {media}
            </div>
          ),
        })}
      </>
    );

  const ctl = (m: ContourManifest | null, idx: number) => ({ frame: idx, scale: hasDisp && m && manifestHasDisp(m) ? scale : 0, legend: useCommon ? leg.range : null, showLegend: !useCommon, playing });
  const inline = both ? showsMedia(L) || showsMedia(R) : showsMedia(left.source ? L : R);
  const aside = (
    <span className="run-action-row">
      {both && leg.note && <span className="muted small" data-testid="c3-legend-note">{leg.note}</span>}
      {both && useCommon && leg.range && <span className="muted small" data-testid="c3-legend-common">같은 범례({fmtLegend(leg.range[0])}–{fmtLegend(leg.range[1])})로 비교</span>}
      {media != null && !inline && <MediaButton title={mediaTitle}>{media}</MediaButton>}
    </span>
  );

  // 한쪽 원본만 있으면 단독 뷰어(자체 조작)
  if (!both) {
    const one = left.source ? { side: left, c: L } : { side: right, c: R };
    return (
      <>
        {children({
          aside,
          mode: "3d",
          body: (
            <div className="contour-slot" ref={ref} data-testid="contour-slot">
              <ChunkErrorBoundary extra={media}>
                <Suspense fallback={<div className="c3-box muted small">불러오는 중…</div>}>
                  <ContourStateView ctl={one.c} media={media} />
                </Suspense>
              </ChunkErrorBoundary>
            </div>
          ),
        })}
      </>
    );
  }

  const column = (side: CompareSide, c: typeof L, idx: number, m: ContourManifest | null, onM: (m: ContourManifest | null) => void, onS: (s: ContourSceneApi | null) => void, tag: string) => (
    <div className="c3-col" data-testid={`contour-${tag}`}>
      <div className="so-contour-head">
        <b>{side.label}</b>
        {side.head}
      </div>
      <ContourStateView ctl={c} viewer={{ control: ctl(m, idx), onManifest: onM, onScene: onS }} />
    </div>
  );
  const t = (m: ContourManifest | null, i: number) => fmtTime(m?.frames.list[i]?.time);
  const ready = !!mL || !!mR;
  const ticks = leg.range ? legendTicks(leg.range[0], leg.range[1], 5).reverse() : [];
  const info = mL ?? mR;
  const body = (
    <div className="contour-slot c3-compare" ref={ref} data-testid="contour-compare3d">
      <ChunkErrorBoundary extra={media}>
        <Suspense fallback={<div className="c3-box muted small">불러오는 중…</div>}>
          <div className="c3-cols">
            {column(left, L, at, mL, setML, setSL, "left")}
            {column(right, R, rightFrame, mR, setMR, setSR, "right")}
          </div>
        </Suspense>
      </ChunkErrorBoundary>
      {inline && media}
      {ready && useCommon && leg.range && info && (
        <div className="c3-common-legend" data-testid="contour-legend-common">
          <span className="small">
            {info.display?.field ?? "값"}
            {info.display?.comp ? ` · ${info.display.comp}` : ""} {info.unit ? `(${info.unit})` : ""}
          </span>
          <div className="gv-legend-bar" style={{ background: legendGradient().replace("to top", "to right") }} />
          <div className="small mono c3-common-ticks">
            {ticks.map((v, i) => (
              <span key={i}>{fmtLegend(v)}</span>
            ))}
          </div>
        </div>
      )}
      {ready && (
        <div className="c3-controls">
          <button type="button" className="btn small ghost" onClick={() => setFrame(prevFrame(at, count))} disabled={count < 2} aria-label="이전 프레임">
            이전
          </button>
          <button type="button" className="btn small" onClick={() => setPlaying((p) => !p)} disabled={count < 2} aria-pressed={playing}>
            {playing ? "일시정지" : "재생"}
          </button>
          <button type="button" className="btn small ghost" onClick={() => setFrame(nextFrame(at, count))} disabled={count < 2} aria-label="다음 프레임">
            다음
          </button>
          <input className="c3-slider" type="range" min={0} max={Math.max(0, count - 1)} step={1} value={at} onChange={(e) => setFrame(Number(e.target.value))} aria-label="타임스텝" />
          <span className="small mono c3-frame" data-testid="contour-frame">
            {at + 1}/{count} · t = {t(mL, at)}
            {mL && mR && rightFrame !== at ? ` | ${right.label} ${rightFrame + 1} · t = ${t(mR, rightFrame)}` : ""}
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
          <label className="check small">
            <input type="checkbox" checked={link} onChange={(e) => setLink(e.target.checked)} />
            시점 연결
          </label>
          <div className="seg c3-legend-mode" role="group" aria-label="범례 범위">
            <button type="button" className={useCommon ? "on" : ""} aria-pressed={useCommon} disabled={!leg.shareable} onClick={() => setCommon(true)} title="두 결과의 값 범위를 합쳐 한 범례로">
              공통
            </button>
            <button type="button" className={!useCommon ? "on" : ""} aria-pressed={!useCommon} onClick={() => setCommon(false)} title="각 결과의 고정 범례">
              개별
            </button>
          </div>
          <button type="button" className="btn small ghost" onClick={fitBoth} disabled={!sL || !sR}>
            맞춤
          </button>
        </div>
      )}
    </div>
  );
  return <>{children({ aside, mode: "3d", body })}</>;
}
