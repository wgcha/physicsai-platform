// ④ 실행 영역 공용 조각: 모델 선택 줄(기본 Final). 파라미터 입력(PredictWorkspace)과 준비된 입력(PreparedPredictCard)이 함께 쓴다.
import { useState } from "react";
import type { Model } from "../../api";
import { useStudy } from "../../app/StudyContext";
import { Advanced } from "../../components/ui";

export interface ModelChoice {
  modelId: string;
  setModelId: (id: string) => void;
  activeModels: Model[];
  chosenModel: Model | null;
}

/** 모델 선택: 빈 값이면 Final 모델(기본) */
export function useModelChoice(): ModelChoice {
  const { models } = useStudy();
  const [modelId, setModelId] = useState("");
  const activeModels = models.filter((m) => m.status === "ACTIVE");
  const finalModel = activeModels.find((m) => m.is_final) ?? null;
  const chosenModel = activeModels.find((m) => m.id === modelId) ?? finalModel;
  return { modelId, setModelId, activeModels, chosenModel };
}

export function ModelLine({ choice }: { choice: ModelChoice }) {
  const { modelId, setModelId, activeModels, chosenModel } = choice;
  return (
    <div className="model-line">
      <span className="field-label">모델</span>
      {chosenModel ? (
        <span>
          <b>{chosenModel.name}</b> v{chosenModel.version} {chosenModel.is_final && <span className="final-badge">Final</span>}
        </span>
      ) : (
        <span className="muted">Final 모델이 없습니다 — ③-5에서 지정하세요</span>
      )}
      <Advanced label="다른 모델">
        <select value={modelId} onChange={(e) => setModelId(e.target.value)} aria-label="모델 선택">
          <option value="">Final 모델(기본)</option>
          {activeModels.map((m) => (
            <option key={m.id} value={m.id}>
              {m.name} v{m.version}
            </option>
          ))}
        </select>
      </Advanced>
    </div>
  );
}
