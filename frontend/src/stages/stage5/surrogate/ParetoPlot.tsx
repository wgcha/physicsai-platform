// S17 파레토 산점도(phase3.md §22.12, 자체 SVG): x = 목적 xi, y = 목적 yi, 원 단위, 축 라벨에 "↓ 좋음"/"↑ 좋음".
// 지배된 검증 점 = 회색 0.3 · 제약 위반 = 회색 × · 검증 파레토 해 = accent 채움 + 계단선 · 예측 전선 = 속 빈 점 + 점선 · 가중 추천점 = 굵은 링.
// 점 클릭 = 선택(표와 공유). 3목적은 PairPlots가 이 컴포넌트를 3개 그린다.
import { niceTicks, tickLabel, useWidth } from "../../../components/Chart";
import { fmtNum } from "../../../lib/format";
import type { ParetoModel, ParetoPt } from "./paretoView";
import { PRED_NOTE } from "./paretoView";

const M = { l: 58, r: 16, t: 12, b: 44 };

/** 계단선: 목적 y가 min이면 가로 → 세로, max이면 세로 → 가로(지배 영역의 경계, x 오름차순) */
export function stairPath(pts: [number, number][], yMin: boolean): string {
  if (!pts.length) return "";
  const s = [...pts].sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  let d = `M${s[0][0]} ${s[0][1]}`;
  for (let i = 1; i < s.length; i++) d += yMin ? ` H${s[i][0]} V${s[i][1]}` : ` V${s[i][1]} H${s[i][0]}`;
  return d;
}

/** 축 라벨 글자 폭 추정(한글·전각 ≈ 12px, 그 밖 ≈ 7px) — 좁은 쌍 그림에서 옆 그림과 겹치지 않게 말줄임에 쓴다. */
export function fitLabel(text: string, maxPx: number): string {
  const w = (c: string) => (c.charCodeAt(0) > 0x2e7f ? 12 : 7);
  const chars = [...text];
  if (chars.reduce((a, c) => a + w(c), 0) <= maxPx) return text;
  let acc = w("…");
  let out = "";
  for (const c of chars) {
    if (acc + w(c) > maxPx) break;
    acc += w(c);
    out += c;
  }
  return `${out}…`;
}

const dir = (s: string) => (s === "max" ? "↑ 좋음" : "↓ 좋음");

export function ParetoPlot({ model, xi, yi, sel, onToggle, showPred, recKey, height = 300, testid = "pareto-plot" }: {
  model: ParetoModel;
  xi: number;
  yi: number;
  sel: Set<string>;
  onToggle: (key: string) => void;
  showPred: boolean;
  recKey: string | null;
  height?: number;
  testid?: string;
}) {
  const { ref, width } = useWidth<HTMLDivElement>(560);
  const dx = model.defs[xi];
  const dy = model.defs[yi];
  const shown: ParetoPt[] = [...model.others, ...model.front, ...(showPred ? model.predicted : [])];
  const xs = shown.map((p) => p.f[xi]).filter(Number.isFinite);
  const ys = shown.map((p) => p.f[yi]).filter(Number.isFinite);
  let [x0, x1] = [Math.min(...xs), Math.max(...xs)];
  let [y0, y1] = [Math.min(...ys), Math.max(...ys)];
  if (!Number.isFinite(x0)) [x0, x1] = [0, 1];
  if (!Number.isFinite(y0)) [y0, y1] = [0, 1];
  if (x0 === x1) [x0, x1] = [x0 - 1, x1 + 1];
  if (y0 === y1) [y0, y1] = [y0 - 1, y1 + 1];
  const px = (x1 - x0) * 0.06;
  const py = (y1 - y0) * 0.08;
  [x0, x1, y0, y1] = [x0 - px, x1 + px, y0 - py, y1 + py];
  const iw = Math.max(60, width - M.l - M.r);
  const ih = Math.max(60, height - M.t - M.b);
  const xLabel = `${dx.label}${dx.unit ? ` [${dx.unit}]` : ""} ${dir(dx.sense)}`;
  const yLabel = `${dy.label}${dy.unit ? ` [${dy.unit}]` : ""} ${dir(dy.sense)}`;
  const sx = (v: number) => M.l + ((v - x0) / (x1 - x0)) * iw;
  const sy = (v: number) => M.t + ih - ((v - y0) / (y1 - y0)) * ih;
  const xt = niceTicks(x0, x1, Math.max(3, Math.floor(iw / 90)));
  const yt = niceTicks(y0, y1, Math.max(3, Math.floor(ih / 45)));
  const yMin = dy.sense !== "max";
  const frontXY = model.front.map((p) => [sx(p.f[xi]), sy(p.f[yi])] as [number, number]);
  const predXY = model.predicted.map((p) => [sx(p.f[xi]), sy(p.f[yi])] as [number, number]).sort((a, b) => a[0] - b[0]);
  const rec = model.front.find((p) => p.key === recKey) ?? null;
  const tip = (p: ParetoPt) =>
    `${p.kind === "pred" ? `${PRED_NOTE} · ` : p.kind === "viol" ? "제약 위반 · " : p.kind === "dom" ? "지배됨 · " : ""}${p.iter_no != null ? `반복 ${p.iter_no} DOE #${p.doe_no} · ` : ""}${dx.label} ${fmtNum(p.f[xi])} · ${dy.label} ${fmtNum(p.f[yi])}`;
  const hit = (p: ParetoPt, children: React.ReactNode) => (
    <g
      key={p.key}
      role="button"
      tabIndex={0}
      aria-pressed={sel.has(p.key)}
      aria-label={tip(p)}
      data-testid={`pt-${p.key}`}
      className={`so-pt ${p.kind}${sel.has(p.key) ? " selected" : ""}`}
      onClick={() => onToggle(p.key)}
      onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onToggle(p.key))}
    >
      <title>{tip(p)}</title>
      {children}
    </g>
  );
  return (
    <div ref={ref} className="chart so-pareto-plot" data-testid={testid}>
      <svg width={width} height={height} role="img" aria-label={`파레토 산점도 ${dx.label} – ${dy.label}`}>
        {xt.map((v) => (
          <g key={`x${v}`}>
            <line className="chart-grid" x1={sx(v)} x2={sx(v)} y1={M.t} y2={M.t + ih} />
            <text className="chart-tick" x={sx(v)} y={M.t + ih + 16} textAnchor="middle">{tickLabel(v)}</text>
          </g>
        ))}
        {yt.map((v) => (
          <g key={`y${v}`}>
            <line className="chart-grid" x1={M.l} x2={M.l + iw} y1={sy(v)} y2={sy(v)} />
            <text className="chart-tick" x={M.l - 6} y={sy(v) + 4} textAnchor="end">{tickLabel(v)}</text>
          </g>
        ))}
        <line className="chart-axis" x1={M.l} x2={M.l + iw} y1={M.t + ih} y2={M.t + ih} />
        <line className="chart-axis" x1={M.l} x2={M.l} y1={M.t} y2={M.t + ih} />
        <text className="chart-label" x={M.l + iw / 2} y={height - 6} textAnchor="middle"><title>{xLabel}</title>{fitLabel(xLabel, iw)}</text>
        <text className="chart-label" transform={`translate(13 ${M.t + ih / 2}) rotate(-90)`} textAnchor="middle"><title>{yLabel}</title>{fitLabel(yLabel, ih)}</text>
        {frontXY.length > 1 && <path className="so-stair" data-testid="pareto-stair" d={stairPath(frontXY, yMin)} fill="none" />}
        {showPred && predXY.length > 1 && <path className="so-pred-line" data-testid="pareto-pred-line" d={`M${predXY.map(([a, b]) => `${a} ${b}`).join(" L")}`} fill="none" />}
        {model.others.map((p) => (
          <g key={p.key} data-testid={`pt-${p.key}`} className={`so-pt ${p.kind}`}>
            <title>{tip(p)}</title>
            {p.kind === "viol" ? (
              <path className="so-x" d={`M${sx(p.f[xi]) - 3.5} ${sy(p.f[yi]) - 3.5} l7 7 M${sx(p.f[xi]) + 3.5} ${sy(p.f[yi]) - 3.5} l-7 7`} />
            ) : (
              <circle className="so-dot" cx={sx(p.f[xi])} cy={sy(p.f[yi])} r={3.6} />
            )}
          </g>
        ))}
        {showPred && model.predicted.map((p) => hit(p, <circle className="so-hollow" cx={sx(p.f[xi])} cy={sy(p.f[yi])} r={4.6} />))}
        {model.front.map((p) => hit(p, <circle className="so-front" cx={sx(p.f[xi])} cy={sy(p.f[yi])} r={5} />))}
        {[...sel].map((k) => {
          const p = [...model.front, ...model.others, ...model.predicted].find((x) => x.key === k);
          return p && (p.kind !== "pred" || showPred) ? <circle key={`s${k}`} className="so-sel" cx={sx(p.f[xi])} cy={sy(p.f[yi])} r={8.5} pointerEvents="none" /> : null;
        })}
        {rec && <circle className="so-rec" data-testid="pareto-rec" data-key={rec.key} cx={sx(rec.f[xi])} cy={sy(rec.f[yi])} r={10.5} pointerEvents="none" />}
      </svg>
    </div>
  );
}

/** 범례 한 줄(산점도·쌍 그림 공용) */
export function ParetoLegend({ predicted }: { predicted: boolean }) {
  return (
    <div className="legend small so-legend" data-testid="pareto-legend">
      <span className="lg so-lg-front" aria-hidden="true" /><span>검증된 파레토 해</span>
      <span className="lg so-lg-dom" aria-hidden="true" /><span>지배된 검증 점</span>
      <span className="lg so-lg-x" aria-hidden="true">×</span><span>제약 위반</span>
      {predicted && (<><span className="lg so-lg-hollow" aria-hidden="true" /><span>{PRED_NOTE}</span></>)}
      <span className="lg so-lg-rec" aria-hidden="true" /><span>가중 추천점</span>
    </div>
  );
}
