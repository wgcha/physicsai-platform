// S14 겹쳐 보기 범례(phase3.md §19.6): 해석(solver) = 속 빈 원·점선, 예측(predict) = 채운 점·실선. 두 표 라벨과 함께.
export interface LegendItem {
  label: string;
  hollow: boolean;
}

export function SourceLegend({ items }: { items: [LegendItem, LegendItem] }) {
  return (
    <ul className="plot-legend small" aria-label="범례" data-testid="plot-legend">
      {items.map((it, i) => (
        <li key={i}>
          <span className={`lg-mark${it.hollow ? " hollow" : ""}`} aria-hidden="true" />{it.label}
          <span className="muted"> ({it.hollow ? "해석 · 속 빈 원" : "예측 · 채운 점"})</span>
        </li>
      ))}
    </ul>
  );
}
