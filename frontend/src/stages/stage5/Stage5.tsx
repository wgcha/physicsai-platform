import { useCallback, useEffect, useState } from "react";
import { api, type Optimization, type OptResponse, type ResponseCandidates } from "../../api";
import { useStudy } from "../../app/StudyContext";
import { useCanExecute, useJobRunner } from "../../hooks/useJobRunner";
import { Card } from "../../components/ui";
import { ResponseAddRow, ResponseTable } from "./ResponseTable";
import { OptInputCard } from "./OptInputCard";
import { OptResult } from "./OptResult";
import { OptRunCard } from "./OptRunCard";
import { type RunSettings } from "./rules";

/** ⑤ 최적화(phase2.md §14.5) */
export function Stage5() {
  const { study } = useStudy();
  const canExec = useCanExecute();
  const [modelId, setModelId] = useState("");
  const [responses, setResponses] = useState<OptResponse[]>([]);
  const [cands, setCands] = useState<ResponseCandidates | null>(null);
  const [opts, setOpts] = useState<Optimization[]>([]);
  const [s, setS] = useState<RunSettings>({
    approach: "OPT", method: "ARSM", maxDesigns: "25", runNominal: true, studyFolder: "HST_PHYSICSAI_OPTIMIZATION", abs: "0.001", rel: "1.0", dv: "0.001", onFailed: "IGNORE",
  });
  const loadOpts = useCallback(() => api.optimizations(study.id).then(setOpts).catch(() => undefined), [study.id]);
  const runner = useJobRunner("OPTIMIZE", () => void loadOpts());

  useEffect(() => {
    api.responseCandidates(study.id, modelId || null).then(setCands).catch(() => setCands(null));
  }, [study.id, modelId]);
  useEffect(() => {
    void loadOpts();
  }, [loadOpts, runner.job?.id, runner.job?.version]);

  const latest = [...opts].sort((a, b) => b.created_at.localeCompare(a.created_at))[0] ?? null;

  return (
    <div className="stage-grid stage5">
      <OptInputCard modelId={modelId} setModelId={setModelId} />
      <Card step="⑤-2" title="응답">
        <ResponseTable rows={responses} onChange={setResponses} readOnly={!canExec} />
        {canExec && <ResponseAddRow candidates={cands} rows={responses} onAdd={(r) => setResponses([...responses, r])} />}
        <p className="muted small">Goal이 CONSTRAINT일 때만 Bound·Value를 씁니다. 단위계 mm-ton-s.</p>
      </Card>
      <OptRunCard s={s} setS={setS} responses={responses} modelId={modelId} runner={runner} />
      <Card step="⑤-4" title="결과">
        <OptResult opt={latest} job={runner.job} />
      </Card>
    </div>
  );
}
