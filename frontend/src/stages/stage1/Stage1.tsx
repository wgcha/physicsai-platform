import { Cell } from "../../design/Grid";
import { TrainProvider } from "./TrainContext";
import { AsmMatchSlot } from "./AsmMatchSlot";
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
      <>
        <Cell span={12} className="card stage-basis" testId="stage1-basis">
          <div className="run-action-row">
            <span className="pill" data-testid="assembly-basis">조립 기준(학습 데이터)</span>
            <span className="muted small">데이터 생성·학습은 조립 입력으로만 합니다. 쿠션 입력은 ④ 예측·⑥ 최적화에서 고릅니다.</span>
          </div>
        </Cell>
        <CadExtractCard />
        <ParamTableCard />
        <AsmMatchSlot />
        <DoeGenCard />
        <SolveCard />
        <ResultCollectCard />
        <RunResponseCard />
      </>
    </TrainProvider>
  );
}
