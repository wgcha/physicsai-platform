import { useState } from "react";
import { useStudy } from "../../app/StudyContext";
import { useCanExecute, useJobRunner } from "../../hooks/useJobRunner";
import { Card, RunAction } from "../../components/ui";
import { PathInput } from "../../components/PathInput";
import { FeatureGate } from "../../components/FeatureGate";
import { fmtTime } from "../../lib/format";
import { useTrain } from "./TrainContext";

// ---------------------------------------------------------------- ①-1
export function CadExtractCard() {
  const { study } = useStudy();
  const { setup, reloadSetup } = useTrain();
  const canExec = useCanExecute();
  const { job, run, error } = useJobRunner("TD_EXTRACT_PARAMS", () => void reloadSetup());
  const [path, setPath] = useState("");
  const [ok, setOk] = useState(false);
  const params = setup?.parameters ?? [];

  return (
    <Card step="①-1" title="CAD 파라미터 추출">
      <PathInput
        studyId={study.id}
        purpose="CAD_FILE"
        label="CAD 파일 경로 (.prt)"
        placeholder="E:/shared/AI_WORK/cushion/00_inbox/cad/cushion_parametric_modeling.prt"
        value={path}
        onChange={setPath}
        canExecute={canExec}
        onInspected={(r) => setOk(!!r?.ok)}
        renderSummary={(r) => (
          <div className="summary-line">
            <span className="mono">{String(r.summary.file_name ?? "")}</span> · {Math.round(Number(r.summary.size ?? 0) / 1024).toLocaleString()} KB
            {r.summary.extension_ok === false && <span className="error-text small"> · 확장자 불가</span>}
          </div>
        )}
      />
      <FeatureGate feature="train_extract">
        {(enabled) => (
          <RunAction
            canExecute={canExec}
            label="파라미터 추출"
            onRun={() => void run({ cad_path: path.trim() })}
            job={job}
            disabled={!enabled || !ok}
            disabledReason={enabled ? "CAD 파일 경로를 입력하고 확인하세요" : undefined}
            error={error}
          />
        )}
      </FeatureGate>
      {setup?.cad && (
        <div className="result-line small">
          <span>
            추출 <b>{params.length}</b>개 (사용 가능 {params.filter((p) => p.valid).length})
          </span>
          <span className="mono ellipsis" title={setup.cad.display_path ?? undefined}>
            {setup.cad.file_name}
          </span>
          <span className="muted">{fmtTime(setup.updated_at)}</span>
        </div>
      )}
    </Card>
  );
}
