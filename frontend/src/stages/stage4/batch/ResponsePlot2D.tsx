// ④ B 응답 그래프 2D(phase3.md §14.8): x = 변수 반영값, y = 응답, 점 = DOE run, x 정렬 선, 선택 run 강조, 점 클릭 = 행 선택. 자체 SVG.
import type { KeyboardEvent } from "react";
import { niceTicks, tickLabel, useWidth } from "../../../components/Chart";

export interface Pt2 {
  doe_no: number;
  run_key: string;
  x: number;
  y: number;
}

export function ResponsePlot2D({ pts, xLabel, yLabel, selected, onSelect }: { pts: Pt2[]; xLabel: string; yLabel: string; selected: number | null; onSelect: (doe: number) => void }) {
  const { ref, width } = useWidth<HTMLDivElement>(420);
  const height = Math.round(Math.max(240, Math.min(width * 0.62, 420)));
  const m = { l: 56, r: 12, t: 10, b: 40 };
  const iw = Math.max(40, width - m.l - m.r);
  const ih = Math.max(40, height - m.t - m.b);
  if (!pts.length) return <p className="muted small">응답 값이 있는 run이 아직 없습니다.</p>;
  const xs = pts.map((p) => p.x);
  const ys = pts.map((p) => p.y);
  let [x0, x1] = [Math.min(...xs), Math.max(...xs)];
  let [y0, y1] = [Math.min(...ys), Math.max(...ys)];
  if (x0 === x1) [x0, x1] = [x0 - 1, x1 + 1];
  if (y0 === y1) [y0, y1] = [y0 - 1, y1 + 1];
  const px = (x1 - x0) * 0.05;
  const py = (y1 - y0) * 0.08;
  [x0, x1, y0, y1] = [x0 - px, x1 + px, y0 - py, y1 + py];
  const sx = (x: number) => m.l + ((x - x0) / (x1 - x0)) * iw;
  const sy = (y: number) => m.t + ih - ((y - y0) / (y1 - y0)) * ih;
  const sorted = [...pts].sort((a, b) => a.x - b.x || a.doe_no - b.doe_no);
  const d = sorted.map((p, i) => `${i ? "L" : "M"}${sx(p.x).toFixed(1)},${sy(p.y).toFixed(1)}`).join("");
  const xt = niceTicks(x0, x1, Math.max(3, Math.floor(iw / 80)));
  const yt = niceTicks(y0, y1, Math.max(3, Math.floor(ih / 45)));
  const key = (e: KeyboardEvent, doe: number) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onSelect(doe);
    }
  };
  const sel = pts.find((p) => p.doe_no === selected) ?? null;
  return (
    <div ref={ref} className="chart rplot">
      <svg width={width} height={height} role="img" aria-label={`응답 그래프 2D: ${xLabel} – ${yLabel}`} data-testid="plot2d">
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
        <path className="chart-line s1" d={d} />
        {pts.map((p) => (
          <circle
            key={p.doe_no}
            className={p.doe_no === selected ? "rpt on" : "rpt"}
            cx={sx(p.x)}
            cy={sy(p.y)}
            r={p.doe_no === selected ? 6 : 4}
            role="button"
            tabIndex={0}
            aria-label={`점 DOE #${p.doe_no}`}
            aria-pressed={p.doe_no === selected}
            onClick={() => onSelect(p.doe_no)}
            onKeyDown={(e) => key(e, p.doe_no)}
          >
            <title>{`DOE #${p.doe_no} · ${xLabel} ${tickLabel(p.x)} · ${yLabel} ${tickLabel(p.y)}`}</title>
          </circle>
        ))}
        {sel && <circle className="rpt on" cx={sx(sel.x)} cy={sy(sel.y)} r={6} pointerEvents="none" />}
        <text className="chart-label" x={m.l + iw / 2} y={height - 6} textAnchor="middle">
          {xLabel}
        </text>
        <text className="chart-label" transform={`translate(12 ${m.t + ih / 2}) rotate(-90)`} textAnchor="middle">
          {yLabel}
        </text>
      </svg>
    </div>
  );
}
