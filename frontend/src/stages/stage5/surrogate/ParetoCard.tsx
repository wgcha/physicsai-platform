// S17 다목적 결과의 파레토 영역(phase3.md §22.12): ② 파레토 카드(2목적 산점도 / 3목적 쌍 그림) ③ 가중치 카드 ④ 파레토 표.
// 선택(점 클릭 ↔ 표 체크)·가중치 슬라이더·예측 전선 토글 상태를 세 카드가 공유하도록 이 구역 컴포넌트가 들고 있다.
import { useMemo, useState } from "react";
import type { SurrogateOpt } from "../../../api/surrogateOpt";
import { Card } from "../../../components/ui";
import { PairPlots } from "./PairPlots";
import { ParetoLegend, ParetoPlot } from "./ParetoPlot";
import { ParetoTable } from "./ParetoTable";
import { WeightSliders } from "./WeightSliders";
import { buildParetoModel, initialSliders, readWeights, writeWeights } from "./paretoView";
import { UNVERIFIED_BADGE, isSurrogateOnly, objectiveDefs } from "./soRules";

export const NO_FRONT_TEXT = "검증된 파레토 해가 생기면 전선이 표시됩니다";

export function ParetoSection({ o, base, onChanged, downloadCsv }: { o: SurrogateOpt; base: string; onChanged: () => void; downloadCsv: () => void }) {
  const m = objectiveDefs(o).length;
  const dflt = useMemo(() => initialSliders(o, m), [o.id, JSON.stringify(o.weights), m]);
  const [u, setU] = useState<number[]>(() => readWeights(o.id, m) ?? dflt);
  const [stored, setStored] = useState<boolean>(() => readWeights(o.id, m) !== null);
  const [sel, setSel] = useState<Set<string>>(new Set());
  const [showPred, setShowPred] = useState(true);
  const model = useMemo(() => buildParetoModel(o, u), [o, u]);
  const toggle = (k: string) =>
    setSel((s) => {
      const n = new Set(s);
      if (n.has(k)) n.delete(k);
      else n.add(k);
      return n;
    });
  const change = (i: number, v: number) => {
    const n = u.map((x, j) => (j === i ? v : x));
    setU(n);
    setStored(true);
    writeWeights(o.id, n);
  };
  const reset = () => {
    setU(dflt);
    setStored(false);
    writeWeights(o.id, null);
  };
  const isDefault = !stored && u.every((x, i) => x === dflt[i]);
  if (!model)
    return (
      <Card span={9} title="파레토 전선">
        <p className="muted small" data-testid="pareto-wait">{NO_FRONT_TEXT}</p>
      </Card>
    );
  const hasPred = model.predicted.length > 0;
  return (
    <>
      <Card span={6} title="파레토 전선" className="so-pareto-card" aside={
        <span className="run-action-row">
          {isSurrogateOnly(o) && <span className="pill warn" data-testid="unverified-badge">{UNVERIFIED_BADGE}</span>}
          <label className="check small">
            <input type="checkbox" checked={showPred} onChange={(e) => setShowPred(e.target.checked)} /> 대리모델 예측 전선
          </label>
        </span>
      }>
        {model.defs.length >= 3 ? (
          <PairPlots model={model} sel={sel} onToggle={toggle} showPred={showPred} recKey={model.rec.key} />
        ) : (
          <ParetoPlot model={model} xi={0} yi={1} sel={sel} onToggle={toggle} showPred={showPred} recKey={model.rec.key} />
        )}
        <ParetoLegend predicted={showPred && hasPred} />
        <p className="muted small">점을 누르면 아래 표에서 선택됩니다. 채운 점 = 검증된 해(실제 예측 체인 값), 속 빈 점 = 대리모델 예측(미검증).</p>
      </Card>
      <WeightSliders model={model} u={u} onChange={change} onReset={reset} isDefault={isDefault} />
      <ParetoTable o={o} model={model} sel={sel} onToggle={toggle} showPred={showPred} base={base} onChanged={onChanged} downloadCsv={downloadCsv} />
    </>
  );
}
