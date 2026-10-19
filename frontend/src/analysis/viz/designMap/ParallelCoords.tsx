// S12 평행 좌표(phase3.md §17.5-7): 축 = 파라미터 전부(원 단위, 템플릿 순서) + 오른쪽 끝 값 축, 선 색 = 값.
// 값 축 브러싱: 세로로 끌어 [lo, hi] → 범위 밖 선 흐리게(0.12), 머리 "값 lo ~ hi · k개 run", 더블클릭·"범위 해제"로 해제(탭 안 상태).
import { useRef, useState, type KeyboardEvent, type MouseEvent } from "react";
import { tickLabel, useWidth } from "../../../components/Chart";
import type { DesignMapMetric } from "../../../api/designMap";
import { axisValue, brushText, tipLines, type MapData, type MapRun, type PcAxis } from "./designMapData";

export function ParallelCoords({ data, axes, colorOf, selected, onSelect, metric }: { data: MapData; axes: PcAxis[]; colorOf: (v: number) => string; selected: number | null; onSelect: (doe: number) => void; metric: DesignMapMetric | undefined }) {
  const { ref, width } = useWidth<HTMLDivElement>(360);
  const svgRef = useRef<SVGSVGElement>(null);
  const [brush, setBrush] = useState<[number, number] | null>(null);
  const [drag, setDrag] = useState<[number, number] | null>(null);
  const [hover, setHover] = useState<MapRun | null>(null);
  const m = { l: 28, r: 44, t: 26, b: 28 };
  const W = Math.max(240, Math.min(width, 640));
  const iw = W - m.l - m.r;
  const ih = Math.max(160, Math.round(iw * 0.8));
  const H = ih + m.t + m.b;
  const ax = (i: number) => m.l + (axes.length > 1 ? (i / (axes.length - 1)) * iw : iw / 2);
  const ay = (a: PcAxis, v: number) => m.t + ih - ((v - a.lo) / (a.hi - a.lo)) * ih;
  const vAxis = axes[axes.length - 1];
  const vFromY = (y: number) => vAxis.lo + ((m.t + ih - y) / ih) * (vAxis.hi - vAxis.lo);
  const inBrush = (r: MapRun) => !brush || (r.v >= brush[0] && r.v <= brush[1]);
  const count = brush ? data.runs.filter(inBrush).length : data.runs.length;
  const isSel = (r: MapRun) => !r.other && r.doe_no === selected;
  const ordered = [...data.runs.filter((r) => !isSel(r)), ...data.runs.filter(isSel)];
  const localY = (e: MouseEvent) => e.clientY - (svgRef.current?.getBoundingClientRect().top ?? 0);
  const down = (e: MouseEvent) => {
    e.preventDefault();
    const y = localY(e);
    setDrag([y, y]);
  };
  // 끌기 중 이동·놓기는 그림 전체에서 받는다(값 축 밖으로 나가도 이어짐)
  const move = (e: MouseEvent) => drag && setDrag([drag[0], Math.min(m.t + ih, Math.max(m.t, localY(e)))]);
  const up = () => {
    if (drag && Math.abs(drag[1] - drag[0]) >= 3) {
      const [a, b] = [vFromY(drag[0]), vFromY(drag[1])];
      setBrush([Math.min(a, b), Math.max(a, b)]);
    }
    setDrag(null);
  };
  const key = (e: KeyboardEvent, doe: number) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onSelect(doe);
    }
  };
  const tip = hover ? tipLines(hover, data.params, metric) : null;
  const band = drag ? [Math.min(drag[0], drag[1]), Math.max(drag[0], drag[1])] : brush ? [ay(vAxis, brush[1]), ay(vAxis, brush[0])] : null;
  return (
    <div ref={ref} className="chart dm-plot">
      <div className="dm-brush-head small" data-testid="dm-brush-head">
        {brush ? (
          <>
            <span>{brushText(brush[0], brush[1], count)}</span>
            <button type="button" className="btn small ghost" onClick={() => setBrush(null)}>
              범위 해제
            </button>
          </>
        ) : (
          <span className="muted">값 축을 세로로 끌어 범위를 고릅니다 · run {data.runs.length}개</span>
        )}
      </div>
      <svg ref={svgRef} width={W} height={H} role="img" aria-label={`평행 좌표: 변수 ${axes.length - 1}개 · ${vAxis.label}`} data-testid="dm-pc" onMouseMove={move} onMouseUp={up} onMouseLeave={up}>
        {ordered.map((r) => {
          const on = isSel(r);
          const alt = !!r.other;
          const d = axes.map((a, i) => `${i ? "L" : "M"}${ax(i).toFixed(1)},${ay(a, axisValue(r, a)).toFixed(1)}`).join("");
          return (
            <path
              key={`${alt ? "o" : "b"}${r.doe_no}`}
              d={d}
              className={`dm-line${on ? " on" : ""}${inBrush(r) ? "" : " dim"}${r.hollow ? " alt" : ""}`}
              stroke={on ? undefined : colorOf(r.v)}
              role={alt ? "img" : "button"}
              tabIndex={alt ? undefined : 0}
              aria-label={alt ? `비교 선 #${r.doe_no}` : `선 DOE #${r.doe_no}`}
              aria-pressed={alt ? undefined : on}
              onClick={alt ? undefined : () => onSelect(r.doe_no)}
              onKeyDown={alt ? undefined : (e) => key(e, r.doe_no)}
              onMouseEnter={() => setHover(r)}
              onMouseLeave={() => setHover(null)}
              onFocus={() => setHover(r)}
              onBlur={() => setHover(null)}
            />
          );
        })}
        {axes.map((a, i) => (
          <g key={a.key} className={a.isValue ? "dm-axis value" : "dm-axis"}>
            <line className="chart-axis" x1={ax(i)} x2={ax(i)} y1={m.t} y2={m.t + ih} />
            {a.ticks.map((t) => (
              <text key={t} className="chart-tick" x={ax(i) - 4} y={ay(a, t)} dy="0.32em" textAnchor="end">
                {tickLabel(t)}
              </text>
            ))}
            <text className="chart-label" x={ax(i)} y={m.t - 10} textAnchor={i === axes.length - 1 ? "end" : i === 0 ? "start" : "middle"}>
              {a.label}
            </text>
          </g>
        ))}
        {band && <rect className="dm-brush" x={ax(axes.length - 1) - 9} y={band[0]} width={18} height={Math.max(1, band[1] - band[0])} pointerEvents="none" />}
        <rect
          className="dm-brush-hit"
          x={ax(axes.length - 1) - 14}
          y={m.t}
          width={28}
          height={ih}
          data-testid="dm-brush-area"
          aria-label="값 축 범위 고르기"
          onMouseDown={down}
          onDoubleClick={() => setBrush(null)}
        />
      </svg>
      {tip && hover && (
        <div className="dm-tip" role="tooltip" data-testid="dm-tip" style={{ left: Math.max(0, W / 2 - 90), top: m.t }}>
          <div className="strong">{tip[0]}</div>
          <div>{tip[1]}</div>
          <div>{tip[2]}</div>
        </div>
      )}
    </div>
  );
}
