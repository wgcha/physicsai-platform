import { TrainProvider } from "./TrainContext";
import { CadExtractCard, DoeGenCard, ParamTableCard } from "./TrainCards";
import { ResultCollectCard, RunResponseCard, SolveCard } from "./SolveCards";

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
