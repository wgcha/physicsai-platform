import { useStudy } from "../../app/StudyContext";
import { ParamSetCard } from "./ParamSetCard";
import { PredictWorkspace } from "./PredictWorkspace";

/** ④ 단일 예측(§16.5) */
export function Stage4() {
  const { currentParamSet } = useStudy();
  return (
    <div className="stage-grid stage4">
      <ParamSetCard />
      {currentParamSet && <PredictWorkspace key={currentParamSet.id} ps={currentParamSet} />}
    </div>
  );
}
