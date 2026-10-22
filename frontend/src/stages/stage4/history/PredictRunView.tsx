// ④ 실행 결과(phase3 §21.2.3, 기존 OpenedJob 대체): 머리 → 입력·경로 카드 → 기존 PredictResultCard → 검증 버튼 줄.
// 일괄 예측 하위 작업(?job=<하위 PREDICT id>)도 같은 화면 — 그때는 상세 API가 NOT_PREDICT_RUN이라 입력·경로 카드 없이 기존 머리만.
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, api, errorMessage, type Job, type PredictJobParams } from "../../../api";
import { predictRunsApi, type PredictRunDetail } from "../../../api/predictRuns";
import { useStudy } from "../../../app/StudyContext";
import { Card } from "../../../components/ui";
import { usePolling } from "../../../hooks/usePolling";
import { isTerminal } from "../../../lib/format";
import { POLL } from "../../../lib/poll";
import { PredictContourCard, PredictResultCard } from "../PredictResult";
import { useFemVerifyButton } from "../verify/useFemVerifyButton";

import { RunInputsCard } from "./RunInputsCard";
import { baseName, mdHm, sourceLabel } from "./runListText";

export function PredictRunView({ id, onBackToList }: { id: string; onBackToList: () => void }) {
  const { study } = useStudy();
  const [job, setJob] = useState<Job | null>(null);
  const [run, setRun] = useState<PredictRunDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadRun = useCallback(async () => {
    try {
      setRun(await predictRunsApi.detail(id));
    } catch (e) {
      // 일괄 하위·다른 유형 = 입력·경로 카드 없음(기존 화면)
      if (!(e instanceof ApiError && (e.code === "NOT_PREDICT_RUN" || e.status === 404))) setError(errorMessage(e));
      setRun(null);
    }
  }, [id]);
  const loadJob = useCallback(async () => {
    const j = await api.job(id);
    setJob((prev) => {
      if (prev && !isTerminal(prev.state) && isTerminal(j.state)) void loadRun();
      return j;
    });
  }, [id, loadRun]);
  useEffect(() => {
    setJob(null);
    setRun(null);
    setError(null);
    loadJob().catch((e) => setError(errorMessage(e)));
    void loadRun();
  }, [id, loadJob, loadRun]);
  usePolling(loadJob, job && !isTerminal(job.state) ? POLL.jobActive : null, false, [id, job?.state]);

  const pbs = useFemVerifyButton(job ? { kind: "predict_job", job_id: job.id } : null, job?.state === "SUCCEEDED", job);
  const br = job?.batch ?? null;
  const p = job?.params as PredictJobParams | undefined;
  const base = `/p/${study.project_id}/s/${study.id}/stage/4`;
  const label = run ? sourceLabel(run) : p?.input_mode === "prepared" ? p.starter_name || baseName(p.input_path) : "";
  const title = br ? `일괄 예측 ${br.label} · DOE #${br.doe_no ?? "?"}` : `예측 · ${mdHm(job?.created_at)}${label ? ` · ${label}` : ""}`;

  return (
    <>
      <Card
        span={9}
        title={title}
        aside={
          br ? (
            <Link to={`${base}/batch/${br.id}`}>← 일괄 예측 결과</Link>
          ) : (
            <button type="button" className="link" onClick={onBackToList}>
              ← 실행 목록
            </button>
          )
        }
      >
        {error ? <p className="error-text small">{error}</p> : !run && <p className="muted small mono ellipsis">{p?.input_path ?? id}</p>}
        {run && run.state === "FAILED" && run.failure && <p className="error-text small">{run.failure.code} — {run.failure.message}</p>}
        <div className="run-action-row">
          {pbs.button}
          {pbs.notes}
        </div>
      </Card>
      {run && <RunInputsCard run={run} />}
      <PredictContourCard job={job} span={run ? "half" : 12} />
      <PredictResultCard job={job} verifyValues={pbs.verifyValues} />
    </>
  );
}
