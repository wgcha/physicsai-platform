import { TrainProvider } from "./TrainContext";
import { CadExtractCard } from "./CadExtractCard";
import { DoeGenCard } from "./DoeGenCard";
import { ParamTableCard } from "./ParamTableCard";
import { ResultCollectCard } from "./ResultCollectCard";
import { RunResponseCard } from "./RunResponseCard";
import { SolveCard } from "./SolveCard";

/** ① 학습데이터 생성: ①-1 → ①-2 → ①-3 → ①-4 → ①-5 (+①-6 선택) — phase2.md §14.2 */
export function Stage1() {
  return (
    <TrainProvider>
      <div className="stage-grid stage1">
        <CadExtractCard />
        <ParamTableCard />
        <DoeGenCard />
        <SolveCard />
        <ResultCollectCard />
        <RunResponseCard />
      </div>
    </TrainProvider>
  );
}
