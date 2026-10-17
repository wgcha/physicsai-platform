// S12 투영 그림(phase3.md §17.5·§17.6): PLS·PCA 2D(바이플롯 화살표) 또는 1D 산점(x = 변수·PLS1, y = 값). 자체 SVG, 정사각.
// 점 색 = 값(viridis), 점 클릭 = setSelected(doe_no), 고른 run = 강조색 테두리·맨 위. 툴팁 3줄(DOE#·변수·값).
import { useState, type KeyboardEvent } from "react";
import { niceTicks, tickLabel, useWidth } from "../../../components/Chart";
import type { DesignMapMetric, DesignMapParameter } from "../../../api/designMap";
import { tipLines, type PlotPoint, type Projection } from "./designMapData";

type Drawn = Exclude<Projection, { kind: "message" }>;

export function ProjectionPlot({ proj, colorOf, showArrows, selected, onSelect, params, metric }: { proj: Drawn; colorOf: (v: number) => string; showArrows: boolean; selected: number | null; onSelect: (doe: number) => void; params: DesignMapParameter[]; metric: DesignMapMetric | undefined }) {
  const { ref, width } = useWidth<HTMLDivElement>(360);
  const [hover, setHover] = useState<PlotPoint | null>(null);
  const m = { l: 52, r: 14, t: 12, b: 44 };
  const iw = Math.max(80, Math.min(width, 640) - m.l - m.r);
  const ih = iw; // 정사각
  const W = iw + m.l + m.r;
  const H = ih + m.t + m.b;
  const arrows = proj.kind === "biplot" && showArrows ? proj.arrows : [];
  const xs = [...proj.points.map((p) => p.x), ...arrows.map((a) => a.x), ...(proj.kind === "biplot" ? [0] : [])];
  const ys = [...proj.points.map((p) => p.y), ...arrows.map((a) => a.y), ...(proj.kind === "biplot" ? [0] : [])];
  const dom = (v: number[]): [number, number] => {
    let [a, b] = [Math.min(...v), Math.max(...v)];
    if (!(b > a)) [a, b] = [a - 1, b + 1];
    const pad = (b - a) * 0.08;
    return [a - pad, b + pad];
  };
  const [x0, x1] = dom(xs);
  const [y0, y1] = dom(ys);
  const sx = (x: number) => m.l + ((x - x0) / (x1 - x0)) * iw;
  const sy = (y: number) => m.t + ih - ((y - y0) / (y1 - y0)) * ih;
  const xt = niceTicks(x0, x1, Math.max(3, Math.floor(iw / 80)));
  const yt = niceTicks(y0, y1, Math.max(3, Math.floor(ih / 60)));
  const isSel = (p: PlotPoint) => !p.run.other && p.run.doe_no === selected;
  const ordered = [...proj.points.filter((p) => !isSel(p)), ...proj.points.filter(isSel)];
  const key = (e: KeyboardEvent, doe: number) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onSelect(doe);
    }
  };
  const xTip = proj.kind === "biplot" ? proj.tip : proj.xTip;
  const yTip = proj.kind === "biplot" ? proj.tip : null;
  const tip = hover ? tipLines(hover.run, params, metric) : null;
  return (
    <div ref={ref} className="chart dm-plot">
      <svg width={W} height={H} role="img" aria-label={`설계공간 지도: ${proj.xLabel} – ${proj.yLabel}`} data-testid={proj.kind === "biplot" ? `dm-${proj.method}` : "dm-1d"}>
        <defs>
          <marker id="dm-arrowhead" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M0,0 L8,4 L0,8 z" className="dm-arrowhead" />
          </marker>
        </defs>
        {yt.map((v) => (
          <g key={`y${v}`}>
            <line className="chart-grid" x1={m.l} x2={m.l + iw} y1={sy(v)} y2={sy(v)} />
            <text className="chart-tick" x={m.l - 6} y={sy(v)} dy="0.32em" textAnchor="end">
              {tickLabel(v)}
            </text>
          </g>
        ))}
        {xt.map((v) => (
          <g key={`x${v}`}>
            <line className="chart-grid" x1={sx(v)} x2={sx(v)} y1={m.t} y2={m.t + ih} />
            <text className="chart-tick" x={sx(v)} y={m.t + ih + 16} textAnchor="middle">
              {tickLabel(v)}
            </text>
          </g>
        ))}
        <rect className="dm-frame" x={m.l} y={m.t} width={iw} height={ih} />
        {proj.kind === "biplot" && (
          <>
            <line className="dm-zero" x1={sx(0)} x2={sx(0)} y1={m.t} y2={m.t + ih} />
            <line className="dm-zero" x1={m.l} x2={m.l + iw} y1={sy(0)} y2={sy(0)} />
          </>
        )}
        {arrows.map((a) => (
          <g key={a.name} className="dm-arrow" data-testid="dm-arrow">
            <line x1={sx(0)} y1={sy(0)} x2={sx(a.x)} y2={sy(a.y)} markerEnd="url(#dm-arrowhead)" />
            <text x={sx(a.x)} y={sy(a.y)} dx={a.x >= 0 ? 4 : -4} dy={a.y >= 0 ? -4 : 12} textAnchor={a.x >= 0 ? "start" : "end"}>
              {a.name}
            </text>
          </g>
        ))}
        {ordered.map((p) => {
          const on = isSel(p);
          const alt = !!p.run.other;
          const c = colorOf(p.run.v);
          return (
            <circle
              key={`${alt ? "o" : "b"}${p.run.doe_no}`}
              className={`dm-pt${on ? " on" : ""}${p.run.hollow ? " hollow" : ""}${alt ? " other" : ""}`}
              cx={sx(p.x)}
              cy={sy(p.y)}
              r={on ? 7 : 5}
              fill={p.run.hollow ? "none" : c}
              style={p.run.hollow && !on ? { stroke: c, strokeWidth: 2 } : undefined}
              pointerEvents="all"
              role={alt ? "img" : "button"}
              tabIndex={alt ? undefined : 0}
              aria-label={alt ? `비교 지도 점 #${p.run.doe_no}` : `지도 점 DOE #${p.run.doe_no}`}
              aria-pressed={alt ? undefined : on}
              onClick={alt ? undefined : () => onSelect(p.run.doe_no)}
              onKeyDown={alt ? undefined : (e) => key(e, p.run.doe_no)}
              onMouseEnter={() => setHover(p)}
              onMouseLeave={() => setHover(null)}
              onFocus={() => setHover(p)}
              onBlur={() => setHover(null)}
            />
          );
        })}
        <text className="chart-label dm-axis-label" x={m.l + iw / 2} y={H - 8} textAnchor="middle" data-testid="dm-xlabel">
          {xTip && <title>{xTip}</title>}
          {proj.xLabel}
        </text>
        <text className="chart-label dm-axis-label" transform={`translate(14 ${m.t + ih / 2}) rotate(-90)`} textAnchor="middle" data-testid="dm-ylabel">
          {yTip && <title>{yTip}</title>}
          {proj.yLabel}
        </text>
      </svg>
      {tip && hover && (
        <div className="dm-tip" role="tooltip" data-testid="dm-tip" style={{ left: Math.min(sx(hover.x) + 10, W - 180), top: Math.max(0, sy(hover.y) - 64) }}>
          <div className="strong">{tip[0]}</div>
          <div>{tip[1]}</div>
          <div>{tip[2]}</div>
        </div>
      )}
    </div>
  );
}
