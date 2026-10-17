// S12 세로 색 막대(phase3.md §17.6): 머리 = 지표 라벨·단위, 위 최대·아래 최소 숫자(fmtNum). 값 전부 같으면 색 1개(중간색)·숫자 1개.
import { useId } from "react";
import { fmtNum } from "../../../../lib/format";
import { VIRIDIS, viridis } from "./colormap";

export function Colorbar({ label, min, max, height }: { label: string; min: number; max: number; height: number }) {
  const gid = `dm-grad-${useId().replace(/[^A-Za-z0-9_-]/g, "")}`;
  const flat = !(max > min);
  const h = Math.max(80, height);
  return (
    <figure className="dm-colorbar" aria-label={`색 막대: ${label}`} data-testid="dm-colorbar">
      <figcaption className="dm-colorbar-head">{label}</figcaption>
      <div className="dm-colorbar-body">
        <svg width={14} height={h} aria-hidden="true">
          <defs>
            <linearGradient id={gid} x1="0" y1="1" x2="0" y2="0">
              {VIRIDIS.map((c, i) => (
                <stop key={c} offset={i / (VIRIDIS.length - 1)} stopColor={c} />
              ))}
            </linearGradient>
          </defs>
          <rect className="dm-colorbar-ramp" x={0.5} y={0.5} width={13} height={h - 1} fill={flat ? viridis(0.5) : `url(#${gid})`} />
        </svg>
        <div className="dm-colorbar-ticks" style={{ height: h }}>
          {flat ? (
            <span className="dm-colorbar-mid" data-testid="dm-cb-single">
              {fmtNum(min)}
            </span>
          ) : (
            <>
              <span data-testid="dm-cb-max">{fmtNum(max)}</span>
              <span data-testid="dm-cb-min">{fmtNum(min)}</span>
            </>
          )}
        </div>
      </div>
    </figure>
  );
}
