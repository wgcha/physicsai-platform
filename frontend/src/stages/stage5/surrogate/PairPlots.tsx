// S17 3목적 쌍 그림(phase3.md §22.12): f₁–f₂, f₁–f₃, f₂–f₃ 세 산점도, 같은 표시 규칙·선택 공유. 평행 좌표는 없다(§22.18 미결 1).
import { ParetoPlot } from "./ParetoPlot";
import type { ParetoModel } from "./paretoView";

const PAIRS: [number, number][] = [[0, 1], [0, 2], [1, 2]];

export function PairPlots({ model, sel, onToggle, showPred, recKey }: { model: ParetoModel; sel: Set<string>; onToggle: (k: string) => void; showPred: boolean; recKey: string | null }) {
  return (
    <div className="so-pairs" data-testid="pair-plots">
      {PAIRS.map(([i, j]) => (
        <ParetoPlot key={`${i}${j}`} model={model} xi={i} yi={j} sel={sel} onToggle={onToggle} showPred={showPred} recKey={recKey} height={260} testid={`pair-${i + 1}-${j + 1}`} />
      ))}
    </div>
  );
}
