// ⑤ 그래프 카드(phase3.md §19.6·§19.7; ④ BatchGraphTabs에서 이동): 탭 [변수–응답] [설계공간 지도] [영향도] [커브(출처 a만)].
// 입력은 결과 표(ResultTable) + 선택적 비교 표(겹쳐 보기, other). 탭 선택은 브라우저별 기억(physicsai.stage4.batchGraphTab 키 그대로, try/catch, 기본 response).
import { useMemo, useState } from "react";
import { Card } from "../../components/ui";
import { PLOT_HINT, plotKind } from "../stage4/batch/batchTable";
import { ResponsePlot2D } from "../../analysis/viz/ResponsePlot2D";
import { ResponsePlot3D } from "../../analysis/viz/ResponsePlot3D";
import { CurveOverlay } from "../../analysis/viz/CurveOverlay";
import { DesignMap } from "../../analysis/viz/designMap/DesignMap";
import { readTab, writeTab, type GraphTab } from "../../analysis/viz/designMap/designMapData";
import { tablePlotPoints, type ResultTable } from "../../analysis/resultTable";
import { NO_RESP_HINT } from "../../analysis/perfColumns";
import { InfluencePanel } from "./InfluencePanel";

export const NO_RESP_TEXT = "응답 없음 — 응답 값이 있는 표에서 변수–응답 그래프와 영향도를 쓸 수 있습니다";
export const NO3D_COMPARE_TEXT = "3D 그래프는 겹쳐 볼 수 없습니다 — 비교 표는 2D(변수 1개)에서 겹쳐 그립니다";
export const OTHER_RESP_MISSING = (name: string) => `비교 표에 응답 ${name}이(가) 없어 겹쳐 그리지 않습니다`;

const TABS: { key: GraphTab; label: string }[] = [
  { key: "response", label: "변수–응답" },
  { key: "map", label: "설계공간 지도" },
  { key: "influence", label: "영향도" },
  { key: "curve", label: "커브" },
];

export function AnalysisTabs({ table, other, pickVars, pickResp, selected, onSelect, series, onSeries }: { table: ResultTable; other: ResultTable | null; pickVars: string[]; pickResp: string | null; selected: number | null; onSelect: (no: number) => void; series: string | null; onSeries: (s: string) => void }) {
  const [saved, setSaved] = useState<GraphTab>(readTab);
  const curveOn = table.source === "predict";
  const tab: GraphTab = saved === "curve" && !curveOn ? "response" : saved;
  const tabs = TABS.filter((t) => t.key !== "curve" || curveOn);
  const kind = plotKind(pickVars, pickResp ? [pickResp] : []);
  const varsKey = pickVars.join("|");
  const pts = useMemo(() => (pickResp && kind !== "none" ? tablePlotPoints(table, pickVars, pickResp) : []), [table, pickResp, kind, varsKey]);
  const otherHas = !!other && !!pickResp && other.responses.some((r) => r.name === pickResp);
  const otherPts = useMemo(() => (other && pickResp && otherHas && kind === "2d" ? tablePlotPoints(other, pickVars, pickResp) : []), [other, pickResp, otherHas, kind, varsKey]);
  const labels3 = useMemo(() => [pickVars[0] ?? "", pickVars[1] ?? "", pickResp ?? ""] as [string, string, string], [varsKey, pickResp]);
  const pts3 = useMemo(() => pts.map((p) => ({ doe_no: p.doe_no, run_key: p.run_key, x: p.v[0], y: p.v[1], z: p.r })), [pts]);
  const choose = (t: GraphTab) => {
    setSaved(t);
    writeTab(t);
  };
  const hasResp = table.responses.length > 0;
  const succeeded = table.rows.filter((r) => r.state === "SUCCEEDED").length;
  return (
    <Card
      span={3}
      title="응답 그래프"
      className="batch-plot analysis-plot"
      aside={
        <div className="tabs graph-tabs" role="tablist" aria-label="그래프 종류">
          {tabs.map((t) => (
            <button key={t.key} type="button" role="tab" aria-selected={tab === t.key} onClick={() => choose(t.key)}>
              {t.label}
            </button>
          ))}
        </div>
      }
    >
      {tab === "map" ? (
        <DesignMap table={table} other={other} selected={selected} onSelect={onSelect} series={series} onSeries={onSeries} />
      ) : tab === "influence" ? (
        <>
          <InfluencePanel table={table} resp={pickResp} title={other ? table.origin.label : undefined} />
          {other && <InfluencePanel table={other} resp={pickResp && other.responses.some((r) => r.name === pickResp) ? pickResp : other.responses[0]?.name ?? null} title={other.origin.label} />}
        </>
      ) : tab === "curve" ? (
        <div role="region" aria-label="커브 겹쳐보기" className="batch-curves">
          <CurveOverlay batchId={table.origin.id} selected={selected} version={succeeded} name={series} onName={onSeries} />
        </div>
      ) : kind === "none" || !pickResp ? (
        <p className="muted small" data-testid="plot-hint">
          {hasResp ? PLOT_HINT : table.source === "predict" ? `${NO_RESP_TEXT} — ${NO_RESP_HINT}` : NO_RESP_TEXT}
        </p>
      ) : kind === "2d" ? (
        <>
          <ResponsePlot2D
            pts={pts.map((p) => ({ doe_no: p.doe_no, run_key: p.run_key, x: p.v[0], y: p.r }))}
            xLabel={pickVars[0]}
            yLabel={pickResp}
            selected={selected}
            onSelect={onSelect}
            hollow={table.source === "solver"}
            label={table.origin.label}
            other={other && otherHas ? { pts: otherPts.map((p) => ({ doe_no: p.doe_no, run_key: p.run_key, x: p.v[0], y: p.r })), hollow: other.source === "solver", label: other.origin.label } : null}
          />
          {other && !otherHas && <p className="muted small" data-testid="plot-other-missing">{OTHER_RESP_MISSING(pickResp)}</p>}
        </>
      ) : (
        <>
          <ResponsePlot3D pts={pts3} labels={labels3} selected={selected} onSelect={onSelect} />
          {other && <p className="muted small" data-testid="plot-3d-compare">{NO3D_COMPARE_TEXT}</p>}
        </>
      )}
    </Card>
  );
}
