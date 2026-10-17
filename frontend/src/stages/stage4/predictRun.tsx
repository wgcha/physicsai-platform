// ④ 실행 영역 공용 조각: 모델 선택 줄(기본 Final)·PBS 검증 해석. 파라미터 입력(PredictWorkspace)과 준비된 입력(PreparedPredictCard)이 함께 쓴다.
import { useState, type ReactNode } from "react";
import type { Job, Model } from "../../api";
import { useApp } from "../../app/AppContext";
import { useStudy } from "../../app/StudyContext";
import { useCanExecute, useJobRunner } from "../../hooks/useJobRunner";
import { Advanced } from "../../components/ui";
import { ScxJobStatus, useScxMode } from "../../components/HpcScx";

export const PBS_DISABLED_TEXT = "PBS 연결 안 됨(관리자 설정 필요)";

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

/** "PBS 검증 해석"(scx면 "검증 해석(SCX)", D3-58)(§16.5 기존 규칙): PBS 구성 + 성공한 예측 결과 + 실행 권한일 때만 활성 */
export function usePredictVerify(pjob: Job | null, hasResult: boolean) {
  const { status } = useApp();
  const canExec = useCanExecute();
  const verify = useJobRunner("PREDICT_VERIFY");
  const hpcConfigured = !!status?.hpc.configured;
  // D3-58: availability(/status.hpc.mode)가 scx면 게이트웨이 중립 이름
  const scx = useScxMode();
  const label = scx ? "검증 해석(SCX)" : "PBS 검증 해석";
  const vjob: Job | null = verify.job && (verify.job.params as { predict_job_id?: string }).predict_job_id === pjob?.id ? verify.job : null;
  const verifyValues = vjob?.state === "SUCCEEDED" ? ((vjob.result as { verify_values?: Record<string, number> } | null)?.verify_values ?? null) : null;

  const button: ReactNode = canExec ? (
    <button
      type="button"
      className="btn"
      disabled={!hpcConfigured || !hasResult || !canExec}
      title={!hpcConfigured ? PBS_DISABLED_TEXT : !hasResult ? "성공한 예측 결과가 필요합니다" : undefined}
      onClick={() => pjob && void verify.run({ predict_job_id: pjob.id, hpc: { queue: null, ncpus: null, walltime: null } })}
    >
      {label}
    </button>
  ) : undefined;

  const notes: ReactNode = (
    <>
      {canExec && !hpcConfigured && <p className="muted small pbs-note" data-testid="pbs-note">{PBS_DISABLED_TEXT}</p>}
      {verify.error && <p className="error-text small">{verify.error}</p>}
      {vjob && <p className="small">{scx ? "검증 해석" : "PBS 검증"}: {vjob.state}</p>}
      {vjob && scx && <ScxJobStatus job={vjob} canAct={canExec} />}
    </>
  );

  return { button, notes, verifyValues };
}
