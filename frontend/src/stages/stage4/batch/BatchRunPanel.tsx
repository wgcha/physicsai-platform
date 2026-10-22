// ④ B 일괄 예측 결과의 오른쪽 "고른 DOE" 카드(BatchResult에서 분할, R-F — 동작 불변).
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, type Job, type PredictBatchRow, type PredictResult as PR, type ViewKey } from "../../../api";
import { useStudy } from "../../../app/StudyContext";
import { Card, CopyButton } from "../../../components/ui";
import { useFemVerifyButton } from "../verify/useFemVerifyButton";
import { ContourMedia } from "../ContourMedia";
import { ContourSlot } from "../geomview/contour/ContourSlot";
import { POLL } from "../../../lib/poll";
import { ResultListTree } from "../PredictResult";
import { ROW_STATE_LABEL } from "./batchTable";

/** 고른 DOE: 머리 DOE #N · run_key, 컨투어(방향별 스크린샷·영상) + 접힌 결과 목록, 경로 복사·단일 예측으로 열기·FEM 검증 */
export function RunPanel({ row, base, canCapture, view, onView, psId, batchId }: { row: PredictBatchRow | null; base: string; canCapture: boolean; view: ViewKey | null; onView: (v: ViewKey) => void; psId: string; batchId: string }) {
  const navigate = useNavigate();
  const { paramSets } = useStudy();
  const [job, setJob] = useState<Job | null>(null);
  useEffect(() => {
    setJob(null);
    if (!row?.job_id || row.state !== "SUCCEEDED") return;
    let alive = true;
    api.job(row.job_id).then((j) => alive && setJob(j)).catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [row?.job_id, row?.state]);
  const result = job?.state === "SUCCEEDED" ? (job.result as unknown as PR | null) : null;
  const pbs = useFemVerifyButton(row ? { kind: "batch_run", batch_id: batchId, doe_no: row.doe_no } : null, !!result, job);
  const done = !!row && row.state === "SUCCEEDED" && !!row.job_id;
  // C3D-4: 행을 훑어 바꿀 때는 머무른 뒤에만 3D를 요청한다(ContourSlot의 delayMs). 같은 칸 하나를 행마다 재사용한다
  return (
    <ContourSlot
      source={done ? { source_kind: "PREDICT_H3D", source_ref: { job_id: row!.job_id! } } : null}
      media={done ? <ContourMedia key={row!.job_id} jobId={row!.job_id!} view={view} onView={onView} canCapture={canCapture} captureViews={paramSets.find((p) => p.id === psId)?.display?.views ?? null} /> : null}
      mediaTitle={row ? `그림/영상 — DOE #${row.doe_no}` : undefined}
      delayMs={POLL.contourDwell}
    >
      {({ aside, body }) =>
        !row ? (
          <Card span="half" title="DOE" className="batch-run-panel">
            <p className="muted small">표나 그래프에서 run을 고르세요.</p>
          </Card>
        ) : (
          <Card span="half" title={`DOE #${row.doe_no}`} step={row.run_key} className="batch-run-panel" aside={aside}>
            {!done ? (
              <p className="muted small">{ROW_STATE_LABEL[row.state]} — 예측이 끝나면 컨투어와 결과 목록이 나옵니다.</p>
            ) : (
              <>
                {body}
                {result ? <ResultListTree artifactId={result.preview_json_artifact_id} /> : <p className="muted small">불러오는 중…</p>}
              </>
            )}
            <div className="run-action-row">
              <CopyButton text={row.folder} label="경로 복사" />
              <button type="button" className="btn small" disabled={!row.job_id || row.state !== "SUCCEEDED"} onClick={() => navigate(`${base}?job=${row.job_id}`)}>
                단일 예측으로 열기
              </button>
              {pbs.button}
            </div>
            {pbs.notes}
          </Card>
        )
      }
    </ContourSlot>
  );
}
