// S17 HV 그래프(phase3.md §22.12, 자체 SVG): x = 반복, y = HV(하이퍼볼륨), 점 옆 개선율 %, 수렴 기준 문구. 기존 수렴 그래프(단일 목적)를 다목적에서 대신한다.
import { niceTicks, tickLabel, useWidth } from "../../../components/Chart";
import type { SurrogateOpt } from "../../../api/surrogateOpt";
import { fmtNum } from "../../../lib/format";

const M = { l: 58, r: 28, t: 14, b: 40 };

export function HvChart({ opt }: { opt: SurrogateOpt }) {
  const { ref, width } = useWidth<HTMLDivElement>(560);
  const hist = (opt.hv_history ?? []).filter((h) => h.hv != null && Number.isFinite(h.hv));
  const tol = Number((opt.settings as { tol_rel?: number }).tol_rel ?? 0.01);
  if (!hist.length) return <p className="muted small" data-testid="hv-none">아직 HV를 계산한 반복이 없습니다.</p>;
  const height = 240;
  const iw = Math.max(60, width - M.l - M.r);
  const ih = height - M.t - M.b;
  const xs = hist.map((h) => h.iter_no);
  const ys = hist.map((h) => h.hv as number);
  const T = Number((opt.settings as { iterations?: number }).iterations ?? 0);
  const x0 = -0.3;
  const x1 = Math.max(T, ...xs, 1) + 0.3;
  const y0 = Math.min(...ys, 0);
  let y1 = Math.max(...ys);
  if (y0 === y1) y1 = y0 + 1;
  y1 += (y1 - y0) * 0.1;
  const sx = (v: number) => M.l + ((v - x0) / (x1 - x0)) * iw;
  const sy = (v: number) => M.t + ih - ((v - y0) / (y1 - y0)) * ih;
  const yt = niceTicks(y0, y1, 4);
  const xt = Array.from({ length: Math.floor(x1) + 1 }, (_, i) => i);
  const path = hist.map((h, i) => `${i ? "L" : "M"}${sx(h.iter_no).toFixed(1)},${sy(h.hv as number).toFixed(1)}`).join("");
  return (
    <div className="so-hv" data-testid="so-hv">
      <div ref={ref} className="chart">
        <svg width={width} height={height} role="img" aria-label="HV 그래프">
          {yt.map((v) => (
            <g key={`y${v}`}>
              <line className="chart-grid" x1={M.l} x2={M.l + iw} y1={sy(v)} y2={sy(v)} />
              <text className="chart-tick" x={M.l - 6} y={sy(v)} dy="0.32em" textAnchor="end">{tickLabel(v)}</text>
            </g>
          ))}
          {xt.map((v) => (
            <text key={`x${v}`} className="chart-tick" x={sx(v)} y={M.t + ih + 16} textAnchor="middle">{v}</text>
          ))}
          <line className="chart-axis" x1={M.l} x2={M.l + iw} y1={M.t + ih} y2={M.t + ih} />
          <line className="chart-axis" x1={M.l} x2={M.l} y1={M.t} y2={M.t + ih} />
          <path className="chart-line" d={path} />
          {hist.map((h) => (
            <g key={h.iter_no} data-testid={`hv-pt-${h.iter_no}`}>
              <circle className="chart-pt" cx={sx(h.iter_no)} cy={sy(h.hv as number)} r={3.5}>
                <title>{`반복 ${h.iter_no} · HV ${fmtNum(h.hv, 3)}${h.front_size != null ? ` · 전선 ${h.front_size}점` : ""}`}</title>
              </circle>
              {h.improvement_rel != null && (
                <text className="chart-tick so-hv-imp" x={sx(h.iter_no)} y={sy(h.hv as number) - 9} textAnchor="middle">
                  {h.improvement_rel >= 0 ? "+" : ""}{(h.improvement_rel * 100).toFixed(1)}%
                </text>
              )}
            </g>
          ))}
          <text className="chart-label" x={M.l + iw / 2} y={height - 6} textAnchor="middle">반복</text>
          <text className="chart-label" transform={`translate(12 ${M.t + ih / 2}) rotate(-90)`} textAnchor="middle">HV(하이퍼볼륨)</text>
        </svg>
      </div>
      <div className="legend small">
        <span className="lg line" aria-hidden="true" />
        <span>검증된 전선의 HV(클수록 좋음)</span>
        <span className="muted" data-testid="hv-rule">수렴 기준: HV 개선 &lt; {Number((tol * 100).toPrecision(3))}%</span>
      </div>
    </div>
  );
}
