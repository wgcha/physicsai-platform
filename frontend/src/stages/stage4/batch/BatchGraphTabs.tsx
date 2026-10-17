// ④ B 그래프 카드(phase3.md §14.8 "응답 그래프" 자리, §17.6 S12): 탭 [변수–응답](표 머리 변수 체크·응답 라디오 → 2D/3D/안내)
// · [설계공간 지도](PLS·PCA·평행 좌표). 탭 선택은 브라우저별 기억(physicsai.stage4.batchGraphTab, try/catch, 기본 response).
// 응답 정의가 없어도 설계공간 지도는 커브 값으로 쓸 수 있다.
import { useMemo, useState } from "react";
import type { PredictBatch } from "../../../api";
import { Card } from "../../../components/ui";
import { PLOT_HINT, plotKind, plotPoints } from "./batchTable";
import { ResponsePlot2D } from "./ResponsePlot2D";
import { ResponsePlot3D } from "./ResponsePlot3D";
import { DesignMap } from "./designMap/DesignMap";
import { readTab, writeTab, type GraphTab } from "./designMap/designMapData";

const TABS: { key: GraphTab; label: string }[] = [
  { key: "response", label: "변수–응답" },
  { key: "map", label: "설계공간 지도" },
];

export function BatchGraphTabs({ b, showResp, noRespText, pickVars, pickResp, selected, onSelect, series, onSeries }: { b: PredictBatch; showResp: boolean; noRespText: string; pickVars: string[]; pickResp: string | null; selected: number | null; onSelect: (doe: number) => void; series: string | null; onSeries: (s: string) => void }) {
  const [tab, setTab] = useState<GraphTab>(readTab);
  const kind = plotKind(pickVars, pickResp ? [pickResp] : []);
  const varsKey = pickVars.join("|");
  const pts = useMemo(() => (pickResp && kind !== "none" ? plotPoints(b.rows, pickVars, pickResp) : []), [b, pickResp, kind, varsKey]);
  const labels3 = useMemo(() => [pickVars[0] ?? "", pickVars[1] ?? "", pickResp ?? ""] as [string, string, string], [varsKey, pickResp]);
  const pts3 = useMemo(() => pts.map((p) => ({ doe_no: p.doe_no, run_key: p.run_key, x: p.v[0], y: p.v[1], z: p.r })), [pts]);
  const choose = (t: GraphTab) => {
    setTab(t);
    writeTab(t);
  };
  return (
    <Card
      span={3}
      title="응답 그래프"
      className="batch-plot"
      aside={
        <div className="tabs graph-tabs" role="tablist" aria-label="그래프 종류">
          {TABS.map((t) => (
            <button key={t.key} type="button" role="tab" aria-selected={tab === t.key} onClick={() => choose(t.key)}>
              {t.label}
            </button>
          ))}
        </div>
      }
    >
      {tab === "map" ? (
        <DesignMap batchId={b.id} version={`${b.predict.succeeded}|${b.status}`} selected={selected} onSelect={onSelect} series={series} onSeries={onSeries} />
      ) : kind === "none" || !pickResp ? (
        <p className="muted small" data-testid="plot-hint">
          {showResp ? PLOT_HINT : noRespText}
        </p>
      ) : kind === "2d" ? (
        <ResponsePlot2D pts={pts.map((p) => ({ doe_no: p.doe_no, run_key: p.run_key, x: p.v[0], y: p.r }))} xLabel={pickVars[0]} yLabel={pickResp} selected={selected} onSelect={onSelect} />
      ) : (
        <ResponsePlot3D pts={pts3} labels={labels3} selected={selected} onSelect={onSelect} />
      )}
    </Card>
  );
}
