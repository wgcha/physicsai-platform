// 경량 SVG 차트(외부 차트 라이브러리 없음, 계약 §4.5).
import { useLayoutEffect, useRef, useState, type ReactNode } from "react";

export function useWidth<T extends HTMLElement>(fallback = 600) {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(fallback);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => {
      const w = el.clientWidth;
      if (w > 0) setWidth(w);
    };
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return { ref, width };
}

export function niceTicks(min: number, max: number, count = 5): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max)) return [];
  if (min === max) return [min];
  const span = max - min;
  const step0 = span / Math.max(1, count);
  const mag = Math.pow(10, Math.floor(Math.log10(step0)));
  const norm = step0 / mag;
  const step = (norm >= 5 ? 10 : norm >= 2 ? 5 : norm >= 1 ? 2 : 1) * mag;
  const start = Math.ceil(min / step) * step;
  const out: number[] = [];
  for (let v = start; v <= max + step * 1e-9; v += step) out.push(Number(v.toPrecision(12)));
  return out;
}

function logTicks(min: number, max: number): number[] {
  const lo = Math.floor(Math.log10(min));
  const hi = Math.ceil(Math.log10(max));
  const out: number[] = [];
  for (let e = lo; e <= hi; e++) out.push(Math.pow(10, e));
  return out.filter((v) => v >= min * 0.999 && v <= max * 1.001);
}

export function tickLabel(v: number): string {
  const a = Math.abs(v);
  if (a !== 0 && (a >= 1e4 || a < 1e-2)) {
    const s = v.toExponential(0);
    return s.replace("e+", "e");
  }
  return String(Number(v.toPrecision(4)));
}

export interface LineSeries {
  name: string;
  pts: [number, number][];
  className?: string;
}

export interface PointMark {
  x: number;
  y: number;
  className?: string;
  r?: number;
  title?: string;
}

export interface ChartProps {
  height: number;
  lines?: LineSeries[];
  points?: PointMark[];
  xLabel?: string;
  yLabel?: string;
  logY?: boolean;
  xDomain?: [number, number];
  yDomain?: [number, number];
  /** 배경 사각형(예: 학습 범위) */
  band?: { x: [number, number]; y: [number, number] };
  ariaLabel: string;
  /** 폭에 비례한 높이(4K 대응): height = clamp(height, width*aspect, maxHeight) */
  aspect?: number;
  maxHeight?: number;
  children?: ReactNode;
}

export function Chart({ height: baseHeight, aspect, maxHeight = 640, lines = [], points = [], xLabel, yLabel, logY, xDomain, yDomain, band, ariaLabel }: ChartProps) {
  const { ref, width } = useWidth<HTMLDivElement>();
  const height = aspect ? Math.round(Math.max(baseHeight, Math.min(width * aspect, maxHeight))) : baseHeight;
  const m = { l: 58, r: 14, t: 10, b: xLabel ? 40 : 26 };
  const iw = Math.max(40, width - m.l - m.r);
  const ih = Math.max(40, height - m.t - m.b);

  const xs: number[] = [];
  const ys: number[] = [];
  for (const s of lines) for (const [x, y] of s.pts) if (Number.isFinite(x) && Number.isFinite(y)) (xs.push(x), ys.push(y));
  for (const p of points) if (Number.isFinite(p.x) && Number.isFinite(p.y)) (xs.push(p.x), ys.push(p.y));
  if (band) xs.push(...band.x), ys.push(...band.y);

  let [x0, x1] = xDomain ?? [Math.min(...xs), Math.max(...xs)];
  let [y0, y1] = yDomain ?? [Math.min(...ys), Math.max(...ys)];
  if (!Number.isFinite(x0) || !Number.isFinite(x1)) [x0, x1] = [0, 1];
  if (!Number.isFinite(y0) || !Number.isFinite(y1)) [y0, y1] = [0, 1];
  if (x0 === x1) [x0, x1] = [x0 - 1, x1 + 1];
  const useLog = !!logY && y0 > 0;
  if (useLog) {
    y0 = Math.pow(10, Math.floor(Math.log10(y0) * 10) / 10);
    y1 = Math.pow(10, Math.ceil(Math.log10(y1) * 10) / 10);
    if (y0 === y1) y1 = y0 * 10;
  } else {
    if (y0 === y1) [y0, y1] = [y0 - 1, y1 + 1];
    if (!yDomain) {
      const pad = (y1 - y0) * 0.06;
      y0 -= pad;
      y1 += pad;
    }
  }
  if (!xDomain && points.length && !lines.length) {
    const pad = (x1 - x0) * 0.04;
    x0 -= pad;
    x1 += pad;
  }

  const sx = (x: number) => m.l + ((x - x0) / (x1 - x0)) * iw;
  const sy = useLog
    ? (y: number) => m.t + ih - ((Math.log10(Math.max(y, 1e-300)) - Math.log10(y0)) / (Math.log10(y1) - Math.log10(y0))) * ih
    : (y: number) => m.t + ih - ((y - y0) / (y1 - y0)) * ih;

  const xt = niceTicks(x0, x1, Math.max(3, Math.floor(iw / 90)));
  const yt = useLog ? logTicks(y0, y1) : niceTicks(y0, y1, Math.max(3, Math.floor(ih / 45)));

  return (
    <div ref={ref} className="chart">
      <svg width={width} height={height} role="img" aria-label={ariaLabel}>
        {band && (
          <rect
            className="chart-band"
            x={sx(band.x[0])}
            y={sy(band.y[1])}
            width={Math.max(0, sx(band.x[1]) - sx(band.x[0]))}
            height={Math.max(0, sy(band.y[0]) - sy(band.y[1]))}
          />
        )}
        {yt.map((v) => (
          <g key={`y${v}`}>
            <line className="chart-grid" x1={m.l} x2={m.l + iw} y1={sy(v)} y2={sy(v)} />
            <text className="chart-tick" x={m.l - 6} y={sy(v)} dy="0.32em" textAnchor="end">
              {tickLabel(v)}
            </text>
          </g>
        ))}
        {xt.map((v) => (
          <text key={`x${v}`} className="chart-tick" x={sx(v)} y={m.t + ih + 16} textAnchor="middle">
            {tickLabel(v)}
          </text>
        ))}
        <line className="chart-axis" x1={m.l} x2={m.l + iw} y1={m.t + ih} y2={m.t + ih} />
        <line className="chart-axis" x1={m.l} x2={m.l} y1={m.t} y2={m.t + ih} />
        {lines.map((s) => {
          const d = s.pts
            .filter(([x, y]) => Number.isFinite(x) && Number.isFinite(y) && (!useLog || y > 0))
            .map(([x, y], i) => `${i ? "L" : "M"}${sx(x).toFixed(1)},${sy(y).toFixed(1)}`)
            .join("");
          return <path key={s.name} className={s.className ?? "chart-line"} d={d} />;
        })}
        {points.map((p, i) => (
          <circle key={i} className={p.className ?? "chart-pt"} cx={sx(p.x)} cy={sy(p.y)} r={p.r ?? 3}>
            {p.title && <title>{p.title}</title>}
          </circle>
        ))}
        {xLabel && (
          <text className="chart-label" x={m.l + iw / 2} y={height - 6} textAnchor="middle">
            {xLabel}
          </text>
        )}
        {yLabel && (
          <text className="chart-label" transform={`translate(12 ${m.t + ih / 2}) rotate(-90)`} textAnchor="middle">
            {yLabel}
          </text>
        )}
      </svg>
    </div>
  );
}

/** 표 안의 작은 loss 스파크라인(로그 축) */
export function Sparkline({ pts, width = 120, height = 28 }: { pts: [number, number][]; width?: number; height?: number }) {
  const good = pts.filter(([x, y]) => Number.isFinite(x) && y > 0);
  if (good.length < 2) return <span className="muted">–</span>;
  const xs = good.map((p) => p[0]);
  const ly = good.map((p) => Math.log10(p[1]));
  const x0 = Math.min(...xs), x1 = Math.max(...xs);
  const y0 = Math.min(...ly), y1 = Math.max(...ly);
  const sx = (x: number) => 2 + ((x - x0) / (x1 - x0 || 1)) * (width - 4);
  const sy = (y: number) => 2 + (1 - (y - y0) / (y1 - y0 || 1)) * (height - 4);
  const d = good.map(([x], i) => `${i ? "L" : "M"}${sx(x).toFixed(1)},${sy(ly[i]).toFixed(1)}`).join("");
  return (
    <svg className="sparkline" width={width} height={height} aria-label="loss 곡선">
      <path d={d} />
    </svg>
  );
}
