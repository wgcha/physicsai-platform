// ③-5 모델 비교: loss 곡선 겹치기(기존 Chart 재사용) + 범례 + 로그 스케일 토글(phase3.md §4.3)
import { useState } from "react";
import { Chart } from "../../components/Chart";
import { fmtNum } from "../../lib/format";
import { canUseLog, modelLegend, type CompareSeries } from "./compare";
import type { CompareColumn } from "./ModelCompareTable";

export function ModelCompareChart({ series, columns }: { series: (CompareSeries | null)[]; columns: CompareColumn[] }) {
  const [logPref, setLogPref] = useState(true);
  const logOk = canUseLog(columns.map((c) => c.model));
  const logY = logOk && logPref;
  const drawn = series.filter((s): s is CompareSeries => !!s && s.pts.length > 0);

  return (
    <div className="losschart compare-chart">
      <div className="losschart-head">
        <span className="field-label">loss 곡선 겹치기</span>
        <label className="check small">
          <input type="checkbox" checked={logY} disabled={!logOk} onChange={(e) => setLogPref(e.target.checked)} /> 로그 스케일
        </label>
      </div>
      {!logOk && <div className="muted small">0 이하 loss가 있어 선형 축으로 표시</div>}
      {drawn.length > 0 ? (
        <Chart
          height={240}
          aspect={0.24}
          maxHeight={520}
          ariaLabel="loss 곡선 비교"
          logY={logY}
          xLabel="epoch"
          yLabel="loss"
          lines={drawn.map((s) => ({ name: s.id, pts: s.pts, className: `chart-line cmp cmp-${s.color}` }))}
          points={drawn
            .filter((s) => s.min)
            .map((s) => ({ x: s.min!.x, y: s.min!.y, r: 3.5, className: `chart-pt cmp cmp-${s.color}`, title: `${s.name} 최소 ${fmtNum(s.min!.y)} (epoch ${s.min!.x})` }))}
        />
      ) : (
        <p className="muted small">비교할 loss 곡선이 없습니다.</p>
      )}
      <ul className="compare-legend" aria-label="범례">
        {columns.map((c, i) => {
          if (!c.model) return null;
          const s = series[i];
          const has = !!s && s.pts.length > 0;
          return (
            <li key={c.id} className={has ? "" : "no-curve"}>
              <span className={`swatch cmp-${c.color}`} aria-hidden="true" />
              {modelLegend(c.model)}
              {!has && <span className="muted"> — 곡선 없음(로그 없음/형식 미확인)</span>}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
